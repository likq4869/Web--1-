"""多证据身份融合领域层：对数似然比加权融合（Log-Opinion Pool）。

职责：把车牌 / 二维码 / NFC / 外观 / 共现等多源证据融合成单一身份置信度，
并按阈值输出 BIND / SUGGEST / UNBOUND 三态决策。
依赖：仅标准库（math、dataclasses、enum）；零 I/O，纯函数。
边界：不读图、不查库、不做网络调用；输入输出均为可序列化 plain data。

融合公式（说明书 §4.6）::

    logit(P) = Σᵢ wᵢ · log(pᵢ / (1 − pᵢ))
    P = sigmoid(logit(P)) = 1 / (1 + exp(−logit(P)))

其中 pᵢ 是第 i 条证据的置信度，wᵢ 是该证据源的可靠性权重（见
DEFAULT_FUSION_POLICY）。这就是朴素贝叶斯在对数几率下的融合形式：
每条证据按其似然比对最终置信度"投票"，强证据（车牌 0.95）一票即可主导，
弱证据（共现 0.45）多条也难以把结果拉过阈值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

# 自动绑定阈值：综合置信度 ≥ 该值才可直接绑定，无需人工介入。
# 取值依据：说明书 §4.6 决策阈值表（≥0.85 自动绑定）。
AUTO_BIND_THRESHOLD = 0.85
# 疑似阈值：综合置信度落入 [SUGGEST, AUTO) 时生成"疑似"记录，管理员快速确认。
# 取值依据：说明书 §4.6（0.60~0.85 疑似）；低于该值 → UNBOUND，进待识别池。
SUGGEST_THRESHOLD = 0.60
# 无证据先验：没有任何证据时的综合置信度。
# 取值依据：说明书 §4.6（p_none = 0.05，无任何证据）。
PRIOR_NONE = 0.05
# 概率钳制边界：logit 在 p=0/1 处发散，钳制到该区间内再计算。
PROB_CLAMP_EPS = 1e-6


class EvidenceMethod(StrEnum):
    """证据来源。与 vehicles / identity_resolutions 表的枚举字符串一致."""

    PLATE = "plate"
    QR = "qr"
    NFC = "nfc"
    APPEARANCE = "appearance"
    COOCCUR = "cooccur"
    MANUAL = "manual"
    NONE = "none"


class IdentityDecision(StrEnum):
    """融合决策三态。"""

    BIND = "bind"
    SUGGEST = "suggest"
    UNBOUND = "unbound"


@dataclass(frozen=True)
class Evidence:
    """单条身份证据。

    Attributes:
        method: 证据来源。
        confidence: 证据置信度，必须在 [0, 1] 内（端点 0/1 会被钳制，不报错）。
        detail: 可读证据说明，用于日志与 UI 展示。
        subject_id: 该证据指向的学号；无指向时为 None。
        vehicle_id: 该证据指向的车辆档案 ID；无指向时为 None。
    """

    method: EvidenceMethod
    confidence: float
    detail: str = ""
    subject_id: str | None = None
    vehicle_id: str | None = None


@dataclass(frozen=True)
class Contribution:
    """单条证据对融合结果的数值贡献（可解释展示用）。

    Attributes:
        method: 证据来源。
        weight: 融合权重 wᵢ。
        logit_term: 该证据的加权对数似然比 wᵢ·logit(pᵢ)，正值为支持、负值为反对。
        confidence: 原始证据置信度。
    """

    method: EvidenceMethod
    weight: float
    logit_term: float
    confidence: float


@dataclass(frozen=True)
class IdentityOutcome:
    """融合决策结果。

    Attributes:
        vehicle_id: 判定的车辆；冲突/无证据时为 None。
        subject_id: 判定的学号；冲突/无指向时为 None。
        confidence: 综合置信度，恒在 [0, 1] 内。
        method: 主证据（|logit 贡献| 最大的证据来源）。
        evidence: 全部输入证据。
        contributions: 逐证据数值贡献，与 evidence 一一对应。
        decision: BIND / SUGGEST / UNBOUND。
        reason: 决策理由人话。
    """

    vehicle_id: str | None
    subject_id: str | None
    confidence: float
    method: EvidenceMethod
    evidence: tuple[Evidence, ...]
    contributions: tuple[Contribution, ...]
    decision: IdentityDecision
    reason: str


@dataclass(frozen=True)
class FusionPolicy:
    """融合策略：各证据源权重，可注入以便测试与调参。

    Attributes:
        weights: 证据源 → 可靠性权重。NONE 恒为 0（不贡献）。
    """

    weights: dict[EvidenceMethod, float] = field(default_factory=dict)


# 默认权重表：
# PLATE/QR 1.0 —— OCR 与二维码识别可靠，置信度即权重 1 倍投票；
# NFC 1.2 —— 读卡是物理接触证据，误报率最低，略放大；
# APPEARANCE 0.8 —— 外观相似度易受光照/遮挡影响，打八折；
# COOCCUR 0.5 —— 图谱推断是间接证据（说明书 p_cooccur=0.45），权重减半；
# MANUAL 1.5 —— 人工登记/确认是金标准，一票定音；
# NONE 0.0 —— 无证据标记，不参与融合。
DEFAULT_FUSION_POLICY = FusionPolicy(
    weights={
        EvidenceMethod.PLATE: 1.0,
        EvidenceMethod.QR: 1.0,
        EvidenceMethod.NFC: 1.2,
        EvidenceMethod.APPEARANCE: 0.8,
        EvidenceMethod.COOCCUR: 0.5,
        EvidenceMethod.MANUAL: 1.5,
        EvidenceMethod.NONE: 0.0,
    }
)


def _clamp_probability(prob: float) -> float:
    """把概率钳制到 [eps, 1-eps]，防止 logit 发散。"""
    return min(max(prob, PROB_CLAMP_EPS), 1.0 - PROB_CLAMP_EPS)


def _logit(prob: float) -> float:
    """对数几率 log(p/(1-p))，输入须已钳制。"""
    clamped = _clamp_probability(prob)
    return math.log(clamped / (1.0 - clamped))


def _sigmoid(logit_value: float) -> float:
    """数值稳定的 sigmoid，避免大指数溢出。"""
    if logit_value >= 0.0:
        return 1.0 / (1.0 + math.exp(-logit_value))
    exp_value = math.exp(logit_value)
    return exp_value / (1.0 + exp_value)


def classify_confidence(
    confidence: float,
    *,
    auto_threshold: float = AUTO_BIND_THRESHOLD,
    suggest_threshold: float = SUGGEST_THRESHOLD,
) -> IdentityDecision:
    """按阈值把综合置信度映射为三态决策（含边界：恰好命中上界归入更高档）。

    Args:
        confidence: 综合置信度。
        auto_threshold: 自动绑定阈值。
        suggest_threshold: 疑似阈值。

    Returns:
        ≥ auto → BIND；≥ suggest → SUGGEST；否则 UNBOUND。
    """
    if confidence >= auto_threshold:
        return IdentityDecision.BIND
    if confidence >= suggest_threshold:
        return IdentityDecision.SUGGEST
    return IdentityDecision.UNBOUND


def fuse_evidence(
    evidences: list[Evidence],
    policy: FusionPolicy | None = None,
) -> IdentityOutcome:
    """融合多条证据，输出身份判定。

    判定流程：
    1. 空证据 → UNBOUND，置信度为无证据先验 PRIOR_NONE；
    2. 校验每条证据置信度在 [0, 1] 内且有限，否则 ValueError；
    3. 冲突检测：多条证据指向不同学号（或不同车辆）→ 强制 UNBOUND；
    4. 加权对数似然比求和 → sigmoid 得综合置信度；
    5. 仅有零权重证据（如 NONE）→ UNBOUND，先验置信度；
    6. 按阈值分类；无指向学号时即使高分也只能 UNBOUND（进待识别池）。

    Args:
        evidences: 待融合的证据列表。
        policy: 融合策略；为 None 时用默认策略。

    Returns:
        融合决策结果，confidence 恒在 [0, 1] 内。

    Raises:
        ValueError: 证据置信度超出 [0, 1] 或非有限值。
    """
    active_policy = policy if policy is not None else DEFAULT_FUSION_POLICY
    for item in evidences:
        if not math.isfinite(item.confidence) or not 0.0 <= item.confidence <= 1.0:
            raise ValueError(f"证据 {item.method.value} 置信度非法：{item.confidence}")

    if not evidences:
        return IdentityOutcome(
            vehicle_id=None,
            subject_id=None,
            confidence=PRIOR_NONE,
            method=EvidenceMethod.NONE,
            evidence=(),
            contributions=(),
            decision=IdentityDecision.UNBOUND,
            reason="无任何证据，转待识别池",
        )

    contributions = tuple(
        Contribution(
            method=item.method,
            weight=active_policy.weights.get(item.method, 0.0),
            logit_term=active_policy.weights.get(item.method, 0.0) * _logit(item.confidence),
            confidence=item.confidence,
        )
        for item in evidences
    )

    subjects = {item.subject_id for item in evidences if item.subject_id is not None}
    vehicles = {item.vehicle_id for item in evidences if item.vehicle_id is not None}
    conflict = len(subjects) > 1 or len(vehicles) > 1

    total_weight = sum(item.weight for item in contributions)
    if total_weight <= 0.0:
        return IdentityOutcome(
            vehicle_id=None,
            subject_id=None,
            confidence=PRIOR_NONE,
            method=EvidenceMethod.NONE,
            evidence=tuple(evidences),
            contributions=contributions,
            decision=IdentityDecision.UNBOUND,
            reason="仅有零权重证据，转待识别池",
        )

    logit_sum = sum(item.logit_term for item in contributions)
    confidence = _sigmoid(logit_sum)
    # 主证据 = |logit 贡献| 最大的证据（最能左右结果的那一条）。
    primary_index = max(range(len(contributions)), key=lambda i: abs(contributions[i].logit_term))
    primary = evidences[primary_index]

    if conflict:
        detail = (
            f"学号冲突 {sorted(subjects)}" if len(subjects) > 1 else f"车辆冲突 {sorted(vehicles)}"
        )
        return IdentityOutcome(
            vehicle_id=None,
            subject_id=None,
            confidence=confidence,
            method=primary.method,
            evidence=tuple(evidences),
            contributions=contributions,
            decision=IdentityDecision.UNBOUND,
            reason=f"多证据指向不一致（{detail}），拒绝绑定，转人工确认",
        )

    decision = classify_confidence(confidence)
    if decision is not IdentityDecision.UNBOUND and primary.subject_id is None:
        return IdentityOutcome(
            vehicle_id=primary.vehicle_id,
            subject_id=None,
            confidence=confidence,
            method=primary.method,
            evidence=tuple(evidences),
            contributions=contributions,
            decision=IdentityDecision.UNBOUND,
            reason="证据未指向任何已登记学生，转待识别池",
        )
    reason_map = {
        IdentityDecision.BIND: f"综合置信度 {confidence:.2f} 达到自动绑定线，转自动绑定",
        IdentityDecision.SUGGEST: f"综合置信度 {confidence:.2f} 落入疑似区间，需人工快速确认",
        IdentityDecision.UNBOUND: f"综合置信度 {confidence:.2f} 低于疑似线，转待识别池",
    }
    return IdentityOutcome(
        vehicle_id=primary.vehicle_id,
        subject_id=primary.subject_id,
        confidence=confidence,
        method=primary.method,
        evidence=tuple(evidences),
        contributions=contributions,
        decision=decision,
        reason=reason_map[decision],
    )


_METHOD_DISPLAY: dict[EvidenceMethod, str] = {
    EvidenceMethod.PLATE: "车牌识别",
    EvidenceMethod.QR: "二维码",
    EvidenceMethod.NFC: "NFC 读卡",
    EvidenceMethod.APPEARANCE: "外观特征",
    EvidenceMethod.COOCCUR: "共现推断",
    EvidenceMethod.MANUAL: "人工登记",
    EvidenceMethod.NONE: "无证据",
}

_DECISION_DISPLAY: dict[IdentityDecision, str] = {
    IdentityDecision.BIND: "自动绑定",
    IdentityDecision.SUGGEST: "疑似，需人工确认",
    IdentityDecision.UNBOUND: "无法确认，转待识别池",
}


def explain_outcome(outcome: IdentityOutcome) -> str:
    """把融合结果翻译成人话，供日志与管理后台展示。

    Args:
        outcome: 融合决策结果。

    Returns:
        多行中文说明：判定行 + 主证据行 + 逐证据贡献行。
    """
    lines = [
        f"判定：{_DECISION_DISPLAY[outcome.decision]}"
        f"（综合置信度 {outcome.confidence:.2f}）",
        f"主证据：{_METHOD_DISPLAY[outcome.method]}",
    ]
    if outcome.subject_id is not None:
        lines.append(f"指向学生：{outcome.subject_id}")
    if outcome.vehicle_id is not None:
        lines.append(f"指向车辆：{outcome.vehicle_id}")
    for item, contrib in zip(outcome.evidence, outcome.contributions, strict=True):
        sign = "支持" if contrib.logit_term >= 0 else "反对"
        lines.append(
            f"· {_METHOD_DISPLAY[item.method]}：{item.detail or '—'}"
            f"（置信度 {item.confidence:.2f}，权重 {contrib.weight:.1f}，{sign}）"
        )
    lines.append(f"理由：{outcome.reason}")
    return "\n".join(lines)
