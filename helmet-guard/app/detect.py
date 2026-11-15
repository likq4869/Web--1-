"""独立采集 CLI：摄像头编号 / 授权 MP4 / 本地图片 + 本地权重文件。

模式：
- camera_check：允许 COCO 通用权重，仅预览 person 等类别，不写业务数据。
- demo：演示模式，预览 + 心跳，不写真实业务判定。
- live：必须专用头盔权重（拒绝 yolov8n 等 COCO 权重），写通行/事件/心跳。

统一规则：CLI --mode 优先于环境变量，通过 apply_effective_mode 写回环境，
后续 get_mode()/get_db_path() 一致。--mode live 配合 demo 环境变量时，
有效模式为 live，后续建库/心跳都走 live 库。

心跳 detail 为 JSON：采集进程报告模型加载、首帧、运行及停止状态，
/health 直接读取该心跳，不再猜测文件状态。
{"weights":..,"model_loaded":bool,"model_ok":bool,"model_info":str,
 "had_first_frame":bool,"frames":int,"stage":str,"error":str}

退出码：0 正常；2 参数/模型/视频源错误，可读信息。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import cv2

from . import apply_effective_mode, get_db_path, resolve_weights
from .alerts import request_alert
from .config import get_point_config
from .db import connect, init_db
from .store import insert_pass_with_event, update_heartbeat, upsert_source
from .tracks import FrameEvidence, PassDeduper, decide_pass, match_head_to_rider
from .vision import inspect_weights_file, is_helmet_weights

VALID_RUN_MODES = ("camera_check", "demo", "live")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Helmet Guard 采集进程")
    p.add_argument("--source", default="0", help="摄像头编号 / 本地视频 / 图片")
    p.add_argument("--weights", default="_smoke/yolov8n.pt", help="本地权重文件")
    p.add_argument(
        "--mode", default=None, help="camera_check|demo|live，默认跟随 HELMET_GUARD_MODE"
    )
    p.add_argument("--source-id", default="gate-east")
    p.add_argument("--run-id", default=None)
    p.add_argument("--imgsz", type=int, default=480)
    p.add_argument("--conf", type=float, default=0.35)
    p.add_argument("--show", action="store_true", default=True)
    p.add_argument("--no-show", action="store_false", dest="show")
    p.add_argument("--save-dir", default=None, help="标注帧保存目录（可选）")
    p.add_argument("--max-frames", type=int, default=0, help="最多处理帧数，0 不限")
    p.add_argument("--dshow", action="store_true", help="Windows DirectShow 打开摄像头")
    return p.parse_args(argv)


def hb_detail(
    weights: str = "",
    model_loaded: bool = False,
    model_ok: bool = False,
    model_info: str = "",
    had_first_frame: bool = False,
    frames: int = 0,
    stage: str = "starting",
    error: str = "",
) -> str:
    return json.dumps(
        {
            "weights": weights,
            "model_loaded": model_loaded,
            "model_ok": model_ok,
            "model_info": model_info,
            "had_first_frame": had_first_frame,
            "frames": frames,
            "stage": stage,
            "error": error,
        },
        ensure_ascii=False,
    )


def open_capture(source: str, dshow: bool) -> tuple[cv2.VideoCapture, bool]:
    if source.isdecimal():
        idx = int(source)
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW if dshow else cv2.CAP_ANY)
        if not cap.isOpened() and not dshow:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # 默认后端失败再试 DSHOW
        if not cap.isOpened():
            raise SystemExit(
                f"无法打开摄像头 {idx}：先用 Windows 相机确认硬件，"
                f"再关闭占用程序后重试（可试 --source 1 / --dshow）"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap, True
    path = Path(source)
    if not path.is_file():
        raise SystemExit(f"视频/图片文件不存在：{source}")
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"视频源读取失败：{source}")
    return cap, False


def report(conn_mode: str, source_id: str, run_id: str, detail: str) -> None:
    c = connect()
    try:
        update_heartbeat(c, source_id, run_id, conn_mode, detail)
    finally:
        c.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode is not None and args.mode.strip().lower() not in VALID_RUN_MODES:
        print(f"mode 非法：{args.mode}，可选 camera_check/demo/live", file=sys.stderr)
        return 2
    # 统一采集模式与数据库路径：CLI 优先，写回环境
    mode = apply_effective_mode(args.mode)

    weights_path = resolve_weights(args.weights)
    cfg = get_point_config()
    run_id = args.run_id or f"{mode}-run-{time.strftime('%Y%m%d-%H%M%S')}"
    init_db()  # 保留启动建表（采集进程启动时建库）
    conn = connect()
    try:
        upsert_source(conn, args.source_id, cfg.name, "online")
        update_heartbeat(
            conn,
            args.source_id,
            run_id,
            mode,
            hb_detail(weights=str(weights_path), stage="starting"),
        )
    finally:
        conn.close()

    # 1) 权重检查（损坏/缺失）：上报 model_failed 心跳后退出
    try:
        names, info = inspect_weights_file(weights_path)
    except (FileNotFoundError, RuntimeError) as exc:
        report(
            mode,
            args.source_id,
            run_id,
            hb_detail(
                weights=str(weights_path),
                model_loaded=False,
                model_ok=False,
                stage="model_failed",
                error=str(exc),
            ),
        )
        print(str(exc), file=sys.stderr)
        return 2
    ok_weights, _ = is_helmet_weights(names)
    print(f"权重：{weights_path} 类别={dict(names)}")
    print(f"权重检查：{info}")

    if mode == "live" and not ok_weights:
        report(
            mode,
            args.source_id,
            run_id,
            hb_detail(
                weights=str(weights_path),
                model_loaded=True,
                model_ok=False,
                model_info=info,
                stage="model_failed",
                error="live 业务拒绝 COCO 通用权重",
            ),
        )
        print(
            "live 业务拒绝启动：当前为 COCO 通用权重或缺少 helmet/no helmet 类；"
            "请指定专用权重（如 weights/helmet_best.pt）后再试。",
            file=sys.stderr,
        )
        return 2
    if mode in ("camera_check", "demo") and not ok_weights:
        print("提示：通用权重仅做 camera_check 预览（person 等），不做头盔业务判定。")

    try:
        # ultralytics 未在 __all__ 中显式导出 YOLO，from-import 会触发
        # mypy attr-defined 误报；已在 pyproject 的 mypy overrides 中
        # 针对 ultralytics 模块单独放宽（仅放开导出检查）。
        import ultralytics

        model = ultralytics.YOLO(str(weights_path))
    except Exception as exc:  # noqa: BLE001
        report(
            mode,
            args.source_id,
            run_id,
            hb_detail(
                weights=str(weights_path),
                model_loaded=False,
                model_ok=False,
                model_info=info,
                stage="model_failed",
                error=str(exc),
            ),
        )
        print(f"模型加载失败：{exc}", file=sys.stderr)
        return 2

    # 模型加载成功，上报就绪（尚未首帧）
    report(
        mode,
        args.source_id,
        run_id,
        hb_detail(
            weights=str(weights_path),
            model_loaded=True,
            model_ok=ok_weights,
            model_info=info,
            had_first_frame=False,
            frames=0,
            stage="running",
        ),
    )

    # live 类别映射（专用权重）：找 cyclists / helmet / no helmet 的 id
    lower = {str(v).strip().lower(): k for k, v in dict(names).items()}
    rider_cids = {v for k, v in lower.items() if k in ("cyclists", "cyclist", "rider")}
    helmet_cid = next((v for k, v in lower.items() if k == "helmet"), None)
    nohelmet_cid = next(
        (
            v
            for k, v in lower.items()
            if k in ("no helmet", "no-helmet", "no_helmet", "without helmet")
        ),
        None,
    )

    try:
        cap, is_camera = open_capture(args.source, args.dshow)
    except SystemExit as exc:
        # 打开失败 = 无首帧
        report(
            mode,
            args.source_id,
            run_id,
            hb_detail(
                weights=str(weights_path),
                model_loaded=True,
                model_ok=ok_weights,
                model_info=info,
                had_first_frame=False,
                frames=0,
                stage="no_first_frame",
                error=str(exc),
            ),
        )
        print(str(exc), file=sys.stderr)
        return 2

    window = "Helmet Guard - Q or Esc 退出"
    save_dir = Path(args.save_dir) if args.save_dir else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    deduper = PassDeduper()
    evidences: dict[str, list[FrameEvidence]] = {}
    frames, had_frame, saved = 0, False, 0
    exit_code = 0
    last_beat = time.time()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if is_camera or not had_frame:
                    # 无首帧：读帧失败且此前无有效画面
                    exit_code = 2
                    report(
                        mode,
                        args.source_id,
                        run_id,
                        hb_detail(
                            weights=str(weights_path),
                            model_loaded=True,
                            model_ok=ok_weights,
                            model_info=info,
                            had_first_frame=had_frame,
                            frames=frames,
                            stage="no_first_frame",
                            error=f"视频源读取失败：{args.source}",
                        ),
                    )
                    print(f"视频源读取失败：{args.source}", file=sys.stderr)
                    break
                break  # 文件源读完
            had_frame = True
            frames += 1
            h, w = frame.shape[:2]

            if mode == "live":
                results = model.track(
                    frame,
                    device="cpu",
                    imgsz=args.imgsz,
                    conf=args.conf,
                    verbose=False,
                    tracker="bytetrack.yaml",
                    persist=True,
                )
            else:
                results = model.predict(
                    frame, device="cpu", imgsz=args.imgsz, conf=args.conf, verbose=False
                )
            # ultralytics 的返回类型标注为 list|Iterator 的联合体，
            # 但实测 predict/track 均返回可下标序列；此处显式收敛为序列类型。
            result_list = cast("Sequence[Any]", results)
            annotated = result_list[0].plot()
            boxes = result_list[0].boxes

            if mode == "live" and boxes is not None and len(boxes):
                # ultralytics 的 boxes 属性标注为 Tensor|ndarray 联合体；
                # 推理结果实际为 torch.Tensor，统一经 cast 收敛后再取 CPU 张量。
                boxes_t = cast("Any", boxes)
                xyxy = boxes_t.xyxy.cpu().tolist()
                cls = boxes_t.cls.cpu().tolist()
                tids = (
                    boxes_t.id.cpu().tolist()
                    if boxes_t.id is not None
                    else [f"noid-{i}" for i in range(len(xyxy))]
                )
                riders: list[tuple[str, list[float]]] = []
                heads: list[tuple[str, list[float]]] = []
                for (x1, y1, x2, y2), c, t in zip(xyxy, cls, tids, strict=True):
                    nb = [x1 / w, y1 / h, x2 / w, y2 / h]
                    if int(c) in rider_cids:
                        riders.append((str(t), nb))
                    elif helmet_cid is not None and int(c) == helmet_cid:
                        heads.append(("helmet", nb))
                    elif nohelmet_cid is not None and int(c) == nohelmet_cid:
                        heads.append(("no helmet", nb))
                for tid, rbox in riders:
                    cx = (rbox[0] + rbox[2]) / 2
                    cy = (rbox[1] + rbox[3]) / 2
                    # 骑行证据：Cyclists 框中心进入 ROI（几何与跨帧一致由窗口投票保证）
                    riding = (rbox[2] - rbox[0]) > 0.03 and (0.0 <= cx <= 1.0)
                    from .vision import in_rect as _in

                    riding = riding and _in(cx, cy, cfg.roi)
                    head = match_head_to_rider(rbox, heads)
                    ev = evidences.setdefault(tid, [])
                    ev.append(FrameEvidence(riding=riding, head=head))
                    if deduper.check_crossing(
                        args.source_id, run_id, tid, cx, cy, cfg.roi, cfg.count_line_y
                    ):
                        status = decide_pass(ev, cfg.min_frames, cfg.min_consistent)
                        if status != "excluded":
                            ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
                            pid = deduper.pass_id(args.source_id, run_id, tid)
                            passed = {
                                "pass_id": pid,
                                "source_id": args.source_id,
                                "run_id": run_id,
                                "occurred_at": ts,
                                "rider_status": status,
                                "model_raw": f"track-{tid}",
                                "created_at": ts,
                            }
                            event = None
                            if status == "bare":
                                eid = deduper.event_id(args.source_id, run_id, tid)
                                event = {
                                    "event_id": eid,
                                    "pass_id": pid,
                                    "source_id": args.source_id,
                                    "run_id": run_id,
                                    "occurred_at": ts,
                                    "model_label": "no helmet",
                                    "reason": "live: 稳定未戴盔证据",
                                    "created_at": ts,
                                }
                            c2 = connect()
                            try:
                                insert_pass_with_event(c2, passed, event)
                            finally:
                                c2.close()
                            print(f"[{run_id}] track={tid} 判定={status}")
                            if status == "bare" and event is not None:
                                q, why = request_alert(
                                    event["event_id"],
                                    args.source_id,
                                    run_id,
                                    alert_enabled=cfg.alert_enabled,
                                    in_zone=True,
                                    frame_ok=True,
                                    heartbeat_fresh=True,
                                    cooldown_s=cfg.alert_cooldown_s,
                                )
                                print(f"提醒入队={q}（{why}）")

            if time.time() - last_beat > 2.0:
                report(
                    mode,
                    args.source_id,
                    run_id,
                    hb_detail(
                        weights=str(weights_path),
                        model_loaded=True,
                        model_ok=ok_weights,
                        model_info=info,
                        had_first_frame=had_frame,
                        frames=frames,
                        stage="running",
                    ),
                )
                last_beat = time.time()

            if save_dir:
                cv2.imwrite(str(save_dir / f"frame_{frames:05d}.jpg"), annotated)
                saved += 1
            if args.show:
                cv2.imshow(window, annotated)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
            if args.max_frames and frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        # 销毁窗口失败不应影响收尾（此时正在上报停止心跳）
        with suppress(Exception):
            cv2.destroyAllWindows()
        # 停止状态：有首帧 -> stopped；无首帧 -> no_first_frame
        stage = "stopped" if had_frame else "no_first_frame"
        c4 = connect()
        try:
            update_heartbeat(
                c4,
                args.source_id,
                run_id,
                mode + "-stopped",
                hb_detail(
                    weights=str(weights_path),
                    model_loaded=True,
                    model_ok=ok_weights,
                    model_info=info,
                    had_first_frame=had_frame,
                    frames=frames,
                    stage=stage,
                ),
            )
        finally:
            c4.close()
    print(f"完成：mode={mode} run={run_id} frames={frames} saved={saved} db={get_db_path()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
