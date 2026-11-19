"""决策证据持久化：passes 表新增检测框与原图尺寸列。

背景：
    P3-2 审批中心要求「证据帧 + 检测框叠加」始终在场（AGENTS.md 原则 1），
    且检测框必须与原图同坐标系 —— 容器 `aspect-ratio` 取
    `image_width / image_height`，横竖图都不会整体偏移。
    但 `passes` 表原先只存三态结论与 model_raw，检测框（归一化 xyxy）
    与原图宽高从未落库，导致审批详情无法还原证据。

变更：
    passes 新增三列（均可空，向后兼容既有行）：
      - boxes          JSON 字符串：[{label, confidence, xyxy:[x1,y1,x2,y2]}]
      - image_width    INTEGER：原图宽（像素）
      - image_height   INTEGER：原图高（像素）

降级：
    既有数据这三列为 NULL，审批详情仍可展示文本结论；
    仅「检测框叠加」缺失，不阻塞审批流程。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_decision_evidence"
down_revision = "0005_decision_review_appeal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为 passes 表新增证据列。"""
    with op.batch_alter_table("passes") as batch:
        batch.add_column(sa.Column("boxes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("image_width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("image_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    """移除证据列。"""
    with op.batch_alter_table("passes") as batch:
        batch.drop_column("image_height")
        batch.drop_column("image_width")
        batch.drop_column("boxes")
