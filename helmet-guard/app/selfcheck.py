"""手机拍照自查：单张图片推理，不写库、不计入校门统计。

约定：
- 上传字段名 file（UniApp uni.uploadFile 的 name 对应）。
- 权重通过 HELMET_GUARD_SELFCHECK_WEIGHTS 配置，默认按候选顺序查找
  本地专用头盔权重（baseline > smoke）；缺失则 503 未就绪。
- 照片仅用于本次推理：不落库、不写 passes/events。
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from starlette.datastructures import UploadFile

from . import PROJECT_ROOT

MAX_BYTES = 10 * 1024 * 1024
# 单文件上限（解析后读取时强制执行）：累计超过即停并报 413。
# 分块读取时的硬上限：读到 MAX_BYTES+1 即判定超限，不再继续缓冲请求体；
# 按剩余限额控制单次读取，最大读取量严格为 MAX_BYTES + 1。
READ_HARD_LIMIT = MAX_BYTES + 1
READ_CHUNK_SIZE = 1024 * 1024
# 整个请求体上限（multipart 解析前）：单文件上限 + multipart 包裹开销余量。
# 由 main.py 中间件在解析前强制执行（读请求体时累计设限，超限直接 413
# 字符串 detail，不进入解析）；解析后单文件读取仍受 MAX_BYTES 约束。
# 两者缺一不可：前者防解析阶段堆内存，后者防单文件缓冲。
SELFCHECK_BODY_LIMIT = MAX_BYTES + 2 * 1024 * 1024
MIN_SIDE = 32
MAX_SIDE = 8000
# 完整解码前的像素总量上限（宽*高），防止超大维度图片解码时占满内存。
# 8000*8000=64M 过大，此处按约 3200 万像素设限（8000 边长下另一边至多 4000）。
MAX_PIXELS = 32_000_000
DEFAULT_CONF = 0.35
DEFAULT_IMGSZ = 640

# 候选专用权重（按优先级）：20epoch 基线 > smoke 验证权重
CANDIDATE_WEIGHTS = (
    "runs/detect/helmet-v2-baseline/weights/best.pt",
    "runs/detect/helmet-smoke/weights/best.pt",
)

_MODEL_CACHE: dict[str, Any] = {"path": "", "model": None, "names": {}, "version": ""}
# 同一进程内模型单例锁：加载、类别校验、统一发布原子完成。
# 预检与推理共用同一实例与版本，首次成功加载后 pin 住直到进程重启；
# 并发首次请求在该锁内只加载一次，不存在“元信息已发布、实例未发布”窗口。
_MODEL_LOCK = threading.Lock()
# CPU 单推理名额：同时只允许一个请求占用模型推理，无界排队改为可重试。
# 名额由事件循环非阻塞获取，所有权移交工作线程，只由工作线程实际结束时释放。
# 两种取消时机：排队等待时被取消与开始后被取消，均不由事件循环侧释放
# （await shield 隔离，工作线程继续占位到结束并释放）；仅任务提交失败
# （线程永不执行）由事件循环侧释放，避免名额泄漏。
_INFER_LOCK = threading.Lock()


class ImageTooLargeError(ValueError):
    """图片字节超限（读取时硬上限触发）。由接口转为 413。"""


# 向后兼容别名：早期代码与外部调用方使用 ImageTooLarge。
# 保留别名而非直接改名，避免一次性破坏既有引用（异常类名属于对外契约）。
ImageTooLarge = ImageTooLargeError


def _weights_display(p: Path) -> str:
    """客户端可见的权重标识：只给相对路径或文件名，不泄露本机绝对路径。"""
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return p.name


async def read_upload_limited(
    upload: UploadFile, limit: int = READ_HARD_LIMIT, chunk: int = READ_CHUNK_SIZE
) -> bytes:
    """分块读取上传文件，累计超过 limit 即停并报超限（解析后第二层）。

    第一层见 main.py 中间件：在解析前累计请求体并设限
    （SELFCHECK_BODY_LIMIT），超限直接 413 不进入解析，通过后重放给路由。
    本函数是解析后文件读取时的第二层，按剩余限额控制单次读取量，
    最大读取量严格为 limit（默认 MAX_BYTES + 1），避免一次多读 1MiB
    导致超限体被过度缓冲。请求体实际边界 = min(客户端发送体, 各层 limit)。
    """
    buf = bytearray()
    while True:
        remaining = limit - len(buf)
        if remaining <= 0:
            break
        # 按剩余限额裁剪单次读取：最后一次至多读到 limit，不多读。
        to_read = chunk if chunk <= remaining else remaining
        if to_read <= 0:
            break
        piece = await upload.read(to_read)
        if not piece:
            break
        buf.extend(piece)
        if len(buf) >= limit:
            break
    if len(buf) > MAX_BYTES:
        raise ImageTooLarge(
            f"图片过大（超过 {MAX_BYTES // 1024 // 1024}MB 上限），请压缩到 10MB 以内后重试"
        )
    return bytes(buf)


def try_acquire_infer() -> bool:
    """非阻塞获取单推理名额。成功返回 True，繁忙返回 False（由接口转 429）。"""
    return _INFER_LOCK.acquire(blocking=False)


def release_infer() -> None:
    """释放单推理名额（工作线程实际结束时调用）。"""
    # 未持有名额时释放会抛 RuntimeError；此处吞掉是幂等语义的一部分
    with suppress(RuntimeError):
        _INFER_LOCK.release()


def resolve_selfcheck_weights() -> Path | None:
    """解析自查权重：环境变量优先，否则按候选顺序找存在的本地文件。"""
    explicit = os.getenv("HELMET_GUARD_SELFCHECK_WEIGHTS", "").strip()
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p
    for rel in CANDIDATE_WEIGHTS:
        p = PROJECT_ROOT / rel
        if p.is_file():
            return p
    return None


# 权重 pin：首次成功加载后固定实例与版本直到进程重启。
# 预检与推理共用同一 _MODEL_CACHE 实例（同一 _MODEL_LOCK 内原子发布），
# 配置变更只提示重启，不自动切换（避免检测中途模型被换）。
_WEIGHTS_PIN: dict[str, str] = {"path": ""}


def _pinned_key() -> str:
    return _WEIGHTS_PIN.get("path", "")


def _ensure_model() -> tuple[Any, dict[int, str], str]:
    """确保模型已加载并返回 (model, names, version)，未就绪抛错。

    收口语义：只要当前进程已有成功加载的实例，直接复用该实例及版本，
    不再解析配置、不检查原文件是否存在；配置路径变化或原文件被移走
    也不切换实例（预检见 model_status 提示重启）。
    仅无模型时才解析路径、检查文件，并在 _MODEL_LOCK 内做唯一一次
    YOLO 加载 + 类别校验 + 原子发布，不存在半发布窗口。
    预检（model_status）与推理（_load_model）共用此入口。
    """
    from .vision import is_selfcheck_weights

    # 快路径：已有实例直接复用，不解析配置、不碰文件系统、不阻塞。
    model = _MODEL_CACHE.get("model")
    if model is not None and _MODEL_CACHE.get("path"):
        return model, _MODEL_CACHE.get("names", {}), _MODEL_CACHE.get("version", "")
    p = resolve_selfcheck_weights()
    if p is None or not p.is_file():
        raise FileNotFoundError(
            "自查模型未就绪：未找到本地专用头盔权重（已按 "
            "runs/detect/helmet-v2-baseline 与 helmet-smoke 查找）；"
            "请先完成电瓶车 v2 训练或设置 HELMET_GUARD_SELFCHECK_WEIGHTS"
        )
    disp = _weights_display(p)
    key = str(p)
    with _MODEL_LOCK:
        # 锁内复查：并发首次请求只加载一次，后到者直接复用。
        model = _MODEL_CACHE.get("model")
        if model is not None and _MODEL_CACHE.get("path"):
            return model, _MODEL_CACHE.get("names", {}), _MODEL_CACHE.get("version", "")
        # 锁内唯一一次 YOLO 加载 + 类别校验 + 原子发布。
        # ultralytics 未在 __all__ 中显式导出 YOLO，from-import 会触发
        # mypy attr-defined 误报；已在 pyproject 的 mypy overrides 中
        # 针对 ultralytics 模块单独放宽（仅放开导出检查）。
        import ultralytics

        try:
            model = ultralytics.YOLO(str(p))
            names = dict(model.names)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"自查模型未就绪：模型文件损坏或无法加载：{disp}，请重新训练或更换权重"
            ) from exc
        ok, reason = is_selfcheck_weights(names)
        if not ok:
            raise RuntimeError(f"权重被拒绝：{reason}（{disp}）")
        version = f"{disp} | ok: {reason}"
        # 原子发布：实例、类别映射、版本与 pin 一起生效，不存在半发布窗口。
        _MODEL_CACHE.update({"path": key, "model": model, "names": dict(names), "version": version})
        _WEIGHTS_PIN["path"] = key
        return model, dict(names), version


def model_status() -> ModelStatus:
    """预检与推理共用同一 _MODEL_CACHE 实例与就绪状态（权重 pin：更换需重启）。

    - 已加载：直接复用当前进程实例及版本，不解析配置、不检查原文件；
      配置路径变化或原文件被移走仍继续使用该实例，仅在 reason 中提示重启，
      不占推理名额，检测期间可用。
    - 仅无模型时才解析路径、检查文件，并在 _MODEL_LOCK 内做唯一一次
      YOLO 加载 + 类别校验 + 原子发布（见 _ensure_model），不存在半发布窗口。
    """
    # 已 pin / 已加载：直接复用当前进程实例及版本，不解析配置、不检查原文件
    # 是否存在；配置路径变化或原文件被移走仍继续使用该实例，仅提示重启。
    cached_path = _MODEL_CACHE.get("path")
    cached_model = _MODEL_CACHE.get("model")
    if cached_path and cached_model is not None:
        pinned = _pinned_key()
        current = str(resolve_selfcheck_weights()) if resolve_selfcheck_weights() else ""
        extra = ""
        if not Path(cached_path).is_file():
            extra = (
                f"（原权重文件已移走，当前仍使用内存实例，需重启恢复，"
                f"之前为 {_weights_display(Path(cached_path))}）"
            )
        elif pinned and current and current != pinned:
            extra = (
                f"（检测到权重配置变更，需重启生效，当前仍使用 {_weights_display(Path(pinned))}）"
            )
        return {
            "ready": True,
            "reason": f"自查权重就绪（缓存复用）{extra}",
            "weights": _weights_display(Path(cached_path)),
            "version": _MODEL_CACHE.get("version", ""),
        }

    p = resolve_selfcheck_weights()
    if p is None:
        return {
            "ready": False,
            "reason": "未找到本地专用头盔权重"
            "（已按 runs/detect/helmet-v2-baseline 与 helmet-smoke 查找），"
            "请先训练或配置 HELMET_GUARD_SELFCHECK_WEIGHTS",
            "weights": None,
        }
    disp = _weights_display(p)
    try:
        _model, names, info_version = _ensure_model()
    except FileNotFoundError:
        return {"ready": False, "reason": f"模型文件不存在：{disp}", "weights": disp}
    except RuntimeError as exc:
        msg = str(exc)
        # _ensure_model 内已做类别校验：此处按消息分类透出，不再二次校验。
        # 类别不符透出拒绝原因；其余 RuntimeError 均为损坏/无法加载（不泄露堆栈）。
        # 说明：已加载后不再因配置变更抛错（推理侧无“配置变更 503”分支），
        # 此处不会再出现“权重配置已变更”消息。
        if "权重被拒绝" in msg:
            return {"ready": False, "reason": msg, "weights": disp}
        return {
            "ready": False,
            "reason": f"模型文件损坏或无法加载：{disp}，请重新训练或更换权重",
            "weights": disp,
        }
    # _ensure_model 已保证类别校验通过（否则抛错），直接复用同一版本字符串。
    return {
        "ready": True,
        "reason": "专用权重就绪（已加载，实例与推理共用）",
        "weights": disp,
        "version": info_version,
    }


def _load_model() -> tuple[Any, dict[int, str], str]:
    """懒加载并缓存 YOLO 模型；与预检共用 _ensure_model 的同一实例与版本。

    已有实例直接复用，不再因配置变更抛错（无“配置变更 503”分支）；
    仅无模型时才解析路径、检查文件并加载校验。
    权重缺失/损坏/类别不符抛错（由接口转 503），客户端消息只含相对路径。
    """
    return _ensure_model()


def decode_image(data: bytes) -> Image.Image:
    """校验大小并解码；EXIF 自动摆正，保证预览与检测框同坐标系。

    解码前先用文件头尺寸做宽/高/像素总量预检，再完整 load，避免超大图占满内存。
    """
    import io as _io

    if not data:
        raise ValueError("图片为空，请重新拍摄或选择有效图片")
    if len(data) > MAX_BYTES:
        raise ValueError(f"图片过大（{len(data) / 1024 / 1024:.1f}MB），请压缩到 10MB 以内")
    try:
        header = Image.open(_io.BytesIO(data))
        hw, hh = header.size
    except (OSError, ValueError) as exc:
        raise ValueError(f"图片无法解码（可能已损坏）：{exc}") from exc
    if hw < MIN_SIDE or hh < MIN_SIDE:
        raise ValueError(f"图片过小（{hw}x{hh}），请停车后靠近拍摄单人单车，或选择更清晰的图片")
    if hw > MAX_SIDE or hh > MAX_SIDE:
        raise ValueError(f"图片过大（{hw}x{hh}），请压缩后重试")
    if hw * hh > MAX_PIXELS:
        raise ValueError(f"图片像素过多（{hw}x{hh}），请压缩后重试")
    try:
        opened = Image.open(_io.BytesIO(data))
        img = ImageOps.exif_transpose(opened)
        img.load()
    except (OSError, ValueError) as exc:
        raise ValueError(f"图片无法解码（可能已损坏）：{exc}") from exc
    if img.width < MIN_SIDE or img.height < MIN_SIDE:
        raise ValueError(
            f"图片过小（{img.width}x{img.height}），请停车后靠近拍摄单人单车，或选择更清晰的图片"
        )
    if img.width > MAX_SIDE or img.height > MAX_SIDE:
        raise ValueError(f"图片过大（{img.width}x{img.height}），请压缩后重试")
    if img.width * img.height > MAX_PIXELS:
        raise ValueError(f"图片像素过多（{img.width}x{img.height}），请压缩后重试")
    return img.convert("RGB")


# ---- 自查判定规则参数（集中管理，静态可审） ----
# 标注抽查（train 1930 图）：
# - 0=Cyclists 为人车整体框（w_med≈0.066,h_med≈0.089），多骑行者图占多数（0/1/2+ = 246/564/1120）。
# - 1=helmet / 2=no helmet 均为小头部框（面积中位 0.00033 / 0.00015）。
# - 随机 200 图：helmet 中心落入骑行者框 86%，no helmet 仅 23%，且 helmet 中心纵向
#   相对骑行者框中位 rel_y≈0.10（p90≈0.16），即头部框基本在骑行者框顶部。
# 结论：helmet/no helmet 都是头部范围框，必须先找到 Cyclists 再做归属，
# 行人裸头（无 Cyclists）不得判 bare；篮中/手中头盔（不在顶部）不得判 helmeted。
# HEAD_TOP_RATIO=0.45 为候选范围（与 tracks.match_head_to_rider 一致），限制：
# - 俯拍/仰拍、低头、背影时头部中心可能落到 45% 之外 -> 误 head_unassociated；
# - 骑行者框偏大（含整车）时顶部 45% 会混入胸部/车把区域 -> 篮中头盔可能误关联；
# - 远景小目标下中心点抖动大，归属不稳定。待真机近景样例复测后再调，勿与校门 ROI 耦合。
RIDER_LABELS = {"cyclists"}
HELMET_LABELS = {"helmet"}
BARE_LABELS = {"no helmet", "no-helmet", "no_helmet", "without helmet"}
# 头部中心需落在骑行者框内，且纵坐标位于骑行者框上部该比例内（与 tracks.match_head_to_rider 一致）
HEAD_TOP_RATIO = 0.45
# 同类重复框去重 IoU（同一人被检出两个重叠框时只保留高分）
DEDUP_IOU = 0.5
# 同一头部两种结论冲突 IoU（helmet 与 no helmet 重叠即视为同一头部证据冲突）
CONFLICT_IOU = 0.3

# 检测框的统一结构：label 为类别名，confidence 为置信度，xyxy 为归一化坐标
Box = dict[str, Any]
# 预检/推理状态返回结构：ready/weights/version/reason
ModelStatus = dict[str, Any]


def _norm_label(label: Any) -> str:
    """归一化类别名：容忍 None / 空值，统一小写并去空白。

    标注可能缺 label 字段（.get("label") 返回 None），此处显式容忍，
    返回空串表示「无类别」。
    """
    return str(label or "").strip().lower()


def _box_iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    bb = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _dedup_same_label(boxes: list[Box]) -> list[Box]:
    """同类框按 IoU 去重：同一人重复框只留高分。输入需已按 confidence 降序。"""
    kept: list[Box] = []
    for b in boxes:
        dup = any(_box_iou(b["xyxy"], k["xyxy"]) >= DEDUP_IOU for k in kept)
        if not dup:
            kept.append(b)
    return kept


def _same_head(a: list[float], b: list[float]) -> bool:
    """判断两个头部框是否指向同一头部：IoU 重叠，或小框中心落入大框（小目标 IoU 易为 0）。"""
    if _box_iou(a, b) >= CONFLICT_IOU:
        return True
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    bb = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    small, large = (a, b) if aa <= bb else (b, a)
    sx1, sy1, sx2, sy2 = small
    lx1, ly1, lx2, ly2 = large
    scx, scy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
    # 小框中心落入大框，且两框面积相近（避免把大框与小框误判为同一头部）
    return lx1 <= scx <= lx2 and ly1 <= scy <= ly2 and max(aa, bb) <= min(aa, bb) * 4 + 1e-9


def _cluster_heads(associated: list[Box]) -> list[list[Box]]:
    """头部聚类（团式合并）：新框只有与簇内所有成员都 _same_head 才可加入。

    避免传递合并：A-B 匹配、B-C 匹配但 A-C 分离时，C 另起新簇，
    调用方按多簇保守 unknown，而不是把三者误并为同一头部。
    """
    clusters: list[list[Box]] = []
    for b in sorted(associated, key=lambda x: float(x["confidence"]), reverse=True):
        placed = False
        for c in clusters:
            if all(_same_head(b["xyxy"], k["xyxy"]) for k in c):
                c.append(b)
                placed = True
                break
        if not placed:
            clusters.append([b])
    return clusters


def _head_belongs_to_rider(rider_xyxy: list[float], head_xyxy: list[float]) -> bool:
    """头部归属：头部中心在骑行者框内且位于上部 HEAD_TOP_RATIO。
    篮中/手中头盔（侧面、底部）不满足此条件，自然被排除。"""
    rx1, ry1, rx2, ry2 = rider_xyxy
    hx1, hy1, hx2, hy2 = head_xyxy
    cx, cy = (hx1 + hx2) / 2, (hy1 + hy2) / 2
    if not (rx1 <= cx <= rx2 and ry1 <= cy <= ry2):
        return False
    top_bottom = ry1 + (ry2 - ry1) * HEAD_TOP_RATIO
    return ry1 <= cy <= top_bottom


def decide_status(boxes: list[Box], conf_thres: float = DEFAULT_CONF) -> tuple[str, str, str]:
    """单骑行者三态判定（纯函数，可直接喂检测框做单测）。

    输入 boxes：[{label, confidence, xyxy(归一化)}]，label 沿用权重类别映射。
    返回 (status, reason_code, message)，status ∈ helmeted/bare/unknown。
    判定顺序：先选定唯一骑行者，再只用归属于该骑行者的头部框检查冲突；
    去重后仍有多个独立头部候选时按多人处理，保守 unknown。
    """
    if not boxes:
        return (
            "unknown",
            "no_target",
            "暂时无法判断：画面中没有可判定的头盔目标，请停车后拍摄单人单车，并让头部进入画面",
        )
    high = [b for b in boxes if float(b.get("confidence", 0.0)) >= conf_thres]
    if not high:
        return (
            "unknown",
            "low_confidence",
            "暂时无法判断：检测分数过低，请停车后靠近拍摄，保证光线充足并让头部无遮挡",
        )
    high = sorted(high, key=lambda b: float(b["confidence"]), reverse=True)

    riders = [b for b in high if _norm_label(b.get("label")) in RIDER_LABELS]
    helmets = [b for b in high if _norm_label(b.get("label")) in HELMET_LABELS]
    bares = [b for b in high if _norm_label(b.get("label")) in BARE_LABELS]
    riders = _dedup_same_label(riders)
    helmets = _dedup_same_label(helmets)
    bares = _dedup_same_label(bares)

    # 1. 先选定唯一骑行者：无骑行者时行人裸头不得判 bare
    if not riders:
        return (
            "unknown",
            "no_rider",
            "暂时无法判断：未找到可靠骑行者，行人裸头不判定为未戴盔，请停车后拍摄单人单车（人车同框）",
        )
    if len(riders) > 1:
        return (
            "unknown",
            "multiple_subjects",
            "暂时无法判断：画面中有多位骑行者，请停车后只拍一人再试",
        )
    rider = riders[0]

    # 2. 只取归属于该骑行者的头部框，再检查冲突（篮中/手中头盔不在顶部，已被排除）
    associated = [b for b in helmets + bares if _head_belongs_to_rider(rider["xyxy"], b["xyxy"])]
    if not associated:
        if helmets or bares:
            return (
                "unknown",
                "head_unassociated",
                "暂时无法判断：头部证据无法可靠关联到该骑行者（如遮挡、过远或头盔在手/车篮中），请停车后正对头部重拍",
            )
        return (
            "unknown",
            "no_head",
            "暂时无法判断：已找到骑行者但缺少头部证据，请停车后让头部进入画面且无遮挡",
        )

    # 3. 去重后仍有多个独立头部候选（团式聚类，防传递合并）-> 保守 unknown
    clusters = _cluster_heads(associated)
    if len(clusters) > 1:
        return (
            "unknown",
            "multiple_subjects",
            "暂时无法判断：该骑行者有多个独立头部候选，请停车后只拍一人、让单人头部清晰入镜再试",
        )

    # 4. 同一头部内既有戴盔又有未戴盔 -> 证据冲突，保守 unknown
    only = clusters[0]
    has_h = any(_norm_label(b.get("label")) in HELMET_LABELS for b in only)
    has_b = any(_norm_label(b.get("label")) in BARE_LABELS for b in only)
    if has_h and has_b:
        return (
            "unknown",
            "ambiguous_evidence",
            "暂时无法判断：该头部同时有戴盔与未戴盔证据，请停车后换角度重拍、让头部无遮挡",
        )
    if has_h:
        return ("helmeted", "has_helmet", "检测到佩戴头盔")
    return ("bare", "has_no_helmet", "检测到未佩戴头盔")


def infer(data: bytes, conf: float = DEFAULT_CONF, imgsz: int = DEFAULT_IMGSZ) -> dict[str, Any]:
    """完整自查推理（同步）：解码 -> YOLO -> 归一化框 -> 三态。照片不落库。

    由接口经工作线程调用，避免阻塞 ASGI 事件循环；纯函数部分可直接单测。
    """
    return _infer_sync(data, conf=conf, imgsz=imgsz)


def _infer_sync(
    data: bytes, conf: float = DEFAULT_CONF, imgsz: int = DEFAULT_IMGSZ
) -> dict[str, Any]:
    """同步推理实体：供工作线程执行，结束由调用方释放推理名额。"""
    img = decode_image(data)
    w, h = img.width, img.height
    model, names, version = _load_model()
    t0 = time.perf_counter()
    results = model.predict(img, device="cpu", imgsz=imgsz, conf=conf, verbose=False)
    inference_ms = (time.perf_counter() - t0) * 1000.0
    boxes: list[Box] = []
    r0 = results[0]
    if r0.boxes is not None and len(r0.boxes):
        xyxy = r0.boxes.xyxy.cpu().tolist()
        cls = r0.boxes.cls.cpu().tolist()
        confs = r0.boxes.conf.cpu().tolist()
        for (x1, y1, x2, y2), c, cf in zip(xyxy, cls, confs, strict=True):
            label = str(names.get(int(c), int(c)))
            boxes.append(
                {
                    "label": label,
                    "confidence": round(float(cf), 4),
                    "xyxy": [
                        round(x1 / w, 5),
                        round(y1 / h, 5),
                        round(x2 / w, 5),
                        round(y2 / h, 5),
                    ],
                }
            )
    # 置信度从高到低，方便前端展示识别依据
    boxes.sort(key=lambda b: b["confidence"], reverse=True)
    status, reason_code, message = decide_status(boxes, conf)
    return {
        "status": status,
        "reason_code": reason_code,
        "message": message,
        "model_version": version,
        "inference_ms": round(inference_ms, 1),
        "image_width": w,
        "image_height": h,
        "boxes": boxes,
    }
