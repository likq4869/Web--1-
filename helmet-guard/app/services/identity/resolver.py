"""身份解析服务：多源证据编排 + 融合决策。

职责：按 车牌 → 二维码 → 外观 → 共现 顺序收集证据，调用领域层融合。
依赖：sqlalchemy 会话、仓储层、appearance 服务、OCR 协议。
边界：只做证据编排与融合调用；不做阈值决策（决策在领域层）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.identity_fusion import (
    Evidence,
    EvidenceMethod,
    FusionPolicy,
    IdentityOutcome,
    fuse_evidence,
)
from app.domain.plate import is_valid_plate
from app.domain.plate import normalize_plate as normalize_plate_text
from app.domain.vehicle_appearance import MATCH_MARGIN, MATCH_THRESHOLD, cosine_similarity
from app.models.identity import Vehicle
from app.repositories.vehicle import VehicleRepository, decode_embedding
from app.services.identity.appearance import extract_vehicle_embedding
from app.services.identity.plate_ocr import mask_plate
from app.services.identity.protocols import DefaultPlateReader, PlateReader


@dataclass(frozen=True)
class CooccurHint:
    """共现证据提示：某未知车与某已知车高频共现。

    Attributes:
        vehicle_id: 共现指向的已绑定车辆。
        subject_id: 该车辆的绑定学号。
        jaccard: 共现 Jaccard 系数。
    """

    vehicle_id: str
    subject_id: str
    jaccard: float


# 共现证据置信度映射：Jaccard → 证据置信度的线性区间。
# 取值依据：说明书 §4.6（p_cooccur = 0.45，为弱证据）；Jaccard 在 [0,1] 内
# 线性映射到 [0.30, 0.55]，最高也不超过 SUGGEST 线，保证共现单独无法 BIND。
COOCCUR_CONF_LOW = 0.30
COOCCUR_CONF_HIGH = 0.55
# 外观证据置信度钳制上限：单外观证据最高只给到 SUGGEST 区间顶部，避免
# 同色车误 BIND；多证据叠加可突破（由融合层对数似然比决定）。
APPEARANCE_CONF_CAP = 0.84


def cooccur_confidence(jaccard: float) -> float:
    """把共现 Jaccard 映射为证据置信度。"""
    clamped = min(max(jaccard, 0.0), 1.0)
    return COOCCUR_CONF_LOW + (COOCCUR_CONF_HIGH - COOCCUR_CONF_LOW) * clamped


def collect_qr_evidence(
    qr_text: str | None,
    *,
    subject_id: str | None,
    vehicle_id: str | None,
    confidence: float = 0.95,
) -> Evidence | None:
    """构造二维码证据（P1-4 扫码枪/检测模型接入前由调用方传入解码结果）。

    Args:
        qr_text: 二维码解码文本；None 表示本次未扫到码。
        subject_id: 码绑定的学号。
        vehicle_id: 码绑定的车辆。
        confidence: 扫码置信度，默认 0.95（二维码误码率极低）。

    Returns:
        有码时返回证据；无码时返回 None（证据缺席，不参与融合）。
    """
    if qr_text is None:
        return None
    return Evidence(
        method=EvidenceMethod.QR,
        confidence=confidence,
        detail=f"二维码解码成功（{qr_text}）",
        subject_id=subject_id,
        vehicle_id=vehicle_id,
    )


def collect_appearance_evidence(
    query_embedding: NDArray[np.floating],
    candidates: list[tuple[str, str | None, NDArray[np.floating]]],
    *,
    threshold: float = MATCH_THRESHOLD,
    margin: float = MATCH_MARGIN,
) -> Evidence | None:
    """按 P1-2 margin 规则从候选中选外观证据。

    Args:
        query_embedding: 本次通行的 128 维向量。
        candidates: (vehicle_id, subject_id, embedding) 候选列表。
        threshold: 相似度下限。
        margin: 冠军与亚军最小差距。

    Returns:
        命中且达线时返回证据（含 margin 差距说明）；歧义/未达线返回 None。
    """
    scored = [
        (vehicle_id, subject_id, float(cosine_similarity(query_embedding, emb)))
        for vehicle_id, subject_id, emb in candidates
    ]
    scored.sort(key=lambda item: item[2], reverse=True)
    if not scored or scored[0][2] < threshold:
        return None
    best_id, best_subject, best_score = scored[0]
    second_score = scored[1][2] if len(scored) > 1 else 0.0
    if len(scored) > 1 and (best_score - second_score) < margin:
        return None
    capped = min(best_score, APPEARANCE_CONF_CAP)
    gap = best_score - second_score
    return Evidence(
        method=EvidenceMethod.APPEARANCE,
        confidence=capped,
        detail=f"外观相似度 {best_score:.2f}（次高 {second_score:.2f}，差距 {gap:.2f}）",
        subject_id=best_subject,
        vehicle_id=best_id,
    )


def collect_cooccur_evidence(hints: list[CooccurHint]) -> Evidence | None:
    """从共现提示构造证据（取 Jaccard 最高的提示）。

    Args:
        hints: 共现提示列表。

    Returns:
        有提示时返回证据；无提示时返回 None。
    """
    if not hints:
        return None
    best = max(hints, key=lambda hint: hint.jaccard)
    return Evidence(
        method=EvidenceMethod.COOCCUR,
        confidence=cooccur_confidence(best.jaccard),
        detail=f"与车辆 {best.vehicle_id} 共现 Jaccard {best.jaccard:.2f}",
        subject_id=best.subject_id,
        vehicle_id=best.vehicle_id,
    )


def resolve_identity(
    event_id: str,
    frame: NDArray[np.uint8],
    rider_box: tuple[float, float, float, float],
    session: Session,
    *,
    plate_reader: PlateReader | None = None,
    qr_text: str | None = None,
    qr_subject_id: str | None = None,
    qr_vehicle_id: str | None = None,
    cooccur_hints: list[CooccurHint] | None = None,
    location: str | None = None,
    snapshot_id: str | None = None,
    policy: FusionPolicy | None = None,
) -> IdentityOutcome:
    """端到端身份解析：收集四类证据并融合。

    编排顺序：车牌 → 二维码 → 外观 → 共现 → 融合。每类证据缺席即跳过；
    全部缺席时返回 UNBOUND + NONE 证据。融合后若命中车辆，刷新其 last_seen
    并把本次 embedding 做渐进均值更新（说明书 §4.3.3 正反馈）。

    Args:
        event_id: 事件 ID（仅用于日志关联，不落库）。
        frame: BGR 帧图。
        rider_box: 骑行者框。
        session: 数据库会话。
        plate_reader: 车牌读取器；None 时用默认占位（未识别）。
        qr_text: 二维码解码文本；None 表示未扫到码。
        qr_subject_id: 二维码绑定的学号。
        qr_vehicle_id: 二维码绑定的车辆。
        cooccur_hints: 共现提示列表。
        location: 本次出现点位（透传用，当前不落库）。
        snapshot_id: 证据帧 ID（透传用，当前不落库）。
        policy: 融合策略；None 用默认策略。

    Returns:
        融合决策结果。
    """
    _ = (event_id, location, snapshot_id)  # 透传字段：供 P1-4 落库时使用。
    reader: PlateReader = plate_reader if plate_reader is not None else DefaultPlateReader()
    vehicle_repo = VehicleRepository(session)
    evidences: list[Evidence] = []

    plate = reader.read(frame, rider_box)
    if plate.text is not None:
        # OCR 原始文本仅作参考：必须先经领域层归一化与合法性校验，
        # 再用归一化文本查已登记车辆，避免脏文本（空格/全角/小写）查库落空。
        normalized_plate = normalize_plate_text(plate.text)
        matched: Vehicle | None = None
        if is_valid_plate(normalized_plate):
            matched = vehicle_repo.get_by_plate(normalized_plate)
        evidences.append(
            Evidence(
                method=EvidenceMethod.PLATE,
                confidence=plate.confidence,
                detail=(
                    f"车牌识别 {mask_plate(normalized_plate)}"
                    f"（类型 {plate.plate_type or '未知'}）"
                ),
                subject_id=matched.owner_id if matched is not None else None,
                vehicle_id=matched.vehicle_id if matched is not None else None,
            )
        )

    qr_evidence = collect_qr_evidence(
        qr_text, subject_id=qr_subject_id, vehicle_id=qr_vehicle_id
    )
    if qr_evidence is not None:
        evidences.append(qr_evidence)

    try:
        query_embedding: NDArray[np.float64] | None = extract_vehicle_embedding(frame, rider_box)
    except ValueError:
        query_embedding = None
    if query_embedding is not None:
        statement = select(Vehicle).where(Vehicle.embedding.is_not(None))
        rows = list(session.execute(statement).scalars().all())
        candidates: list[tuple[str, str | None, NDArray[np.floating]]] = []
        for row in rows:
            vector = decode_embedding(row.embedding)
            if vector is None or len(vector) != 128:
                continue
            candidates.append(
                (row.vehicle_id, row.owner_id, np.array(vector, dtype=np.float64))
            )
        appearance = collect_appearance_evidence(query_embedding, candidates)
        if appearance is not None:
            evidences.append(appearance)

    cooccur = collect_cooccur_evidence(cooccur_hints or [])
    if cooccur is not None:
        evidences.append(cooccur)

    outcome = fuse_evidence(evidences, policy)
    if outcome.vehicle_id is not None and query_embedding is not None:
        vehicle_repo.add_embedding_sample(
            outcome.vehicle_id, [float(v) for v in query_embedding]
        )
    return outcome
