"""为既有 SQLite 库补齐缺失列（幂等）。

用途：demo 库由 `init_db()` 原生建表管理，不在 Alembic 版本控制内。
新增列（如 passes.boxes）后，既有库不会自动获得新列 —— 本脚本
按「缺失才加」的规则补齐，不修改、不删除任何既有行。

边界：只执行 ADD COLUMN；不执行 DROP / DELETE / UPDATE。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 期望的列定义：(表名, 列名, 类型)
EXPECTED_COLUMNS: list[tuple[str, str, str]] = [
    ("passes", "boxes", "TEXT"),
    ("passes", "image_width", "INTEGER"),
    ("passes", "image_height", "INTEGER"),
]


def ensure_columns(db_path: Path) -> list[str]:
    """补齐缺失列。

    Args:
        db_path: 数据库文件路径。

    Returns:
        本次实际新增的列描述列表。
    """
    added: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        for table, column, column_type in EXPECTED_COLUMNS:
            existing = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                # 表本身不存在时跳过（该表由 init_db 负责创建）。
                continue
            if column in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
            added.append(f"{table}.{column}")
        conn.commit()
    finally:
        conn.close()
    return added


def main() -> None:
    """命令行入口。"""
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/helmet_demo.db")
    if not target.exists():
        print(f"db not found: {target}")
        return
    added = ensure_columns(target)
    if added:
        print(f"added columns: {', '.join(added)}")
    else:
        print("schema already up to date")


if __name__ == "__main__":
    main()
