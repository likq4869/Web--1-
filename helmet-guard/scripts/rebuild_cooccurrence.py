"""共现矩阵全量重算脚本（每日凌晨离线任务的手动入口）。

用法::

    python scripts/rebuild_cooccurrence.py --db <sqlite 路径>
    python scripts/rebuild_cooccurrence.py --db data/live.db --window-minutes 5

说明：
- Celery beat 接入前，先用本脚本 + 操作系统定时任务（cron / 计划任务）
  每日凌晨执行即可；接入 Celery 后把 `main()` 的核心两行搬进 task 即可。
- 本脚本只读写 `identity_resolutions` 与 `vehicle_cooccurrence` 两张表，
  不碰证据图片与原始数据集。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="全量重算车辆共现矩阵")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=5,
        help="时间窗口长度（分钟），默认 5",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行全量重算并打印统计。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.services.identity.cooccurrence import rebuild_cooccurrence

    args = parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 1
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            stats = rebuild_cooccurrence(session, window_minutes=args.window_minutes)
            session.commit()
    finally:
        engine.dispose()
    pairs = len(stats)
    confident = sum(1 for item in stats.values() if item.confidence >= 0.60)
    print(f"重算完成：共 {pairs} 对，置信度达线 {confident} 对")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
