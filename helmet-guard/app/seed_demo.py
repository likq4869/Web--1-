"""演示种子：可重复执行，确定性事件标识。7 戴盔、2 未戴盔、1 未知。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .db import connect, init_db
from .store import insert_pass_with_event, upsert_source

SOURCE_ID = "gate-east"
RUN_ID = "demo-run-001"
BASE_TS = "2026-11-05T08:00:00+00:00"

# 10 条通行：7 helmeted / 2 bare / 1 unknown；bare 生成候选事件
PASSES: list[tuple[str, str]] = [
    ("demo-pass-001", "helmeted"),
    ("demo-pass-002", "helmeted"),
    ("demo-pass-003", "bare"),
    ("demo-pass-004", "helmeted"),
    ("demo-pass-005", "helmeted"),
    ("demo-pass-006", "unknown"),
    ("demo-pass-007", "helmeted"),
    ("demo-pass-008", "bare"),
    ("demo-pass-009", "helmeted"),
    ("demo-pass-010", "helmeted"),
]


def seed(db_path: Path | None = None) -> dict[str, Any]:
    from . import get_mode

    explicit_env = os.getenv("HELMET_GUARD_DB", "").strip() != ""
    explicit = explicit_env or db_path is not None
    if get_mode() == "live" and not explicit:
        raise SystemExit(
            "拒绝在 live 默认库执行演示种子："
            "live 环境误跑演示种子已拦截；"
            "如确需写入请设置 HELMET_GUARD_DB 指向临时库"
        )
    path = init_db(db_path)
    conn = connect(path)
    try:
        upsert_source(conn, SOURCE_ID, "东校门", "online", BASE_TS)
        for i, (pass_id, status) in enumerate(PASSES):
            ts = BASE_TS.replace("08:00:00", f"08:{i:02d}:00")
            model_raw = {"helmeted": "helmet", "bare": "no helmet", "unknown": ""}[status]
            passed = {
                "pass_id": pass_id,
                "source_id": SOURCE_ID,
                "run_id": RUN_ID,
                "occurred_at": ts,
                "rider_status": status,
                "model_raw": model_raw,
                "created_at": ts,
            }
            event = None
            if status == "bare":
                event = {
                    "event_id": f"evt-{pass_id}",
                    "pass_id": pass_id,
                    "source_id": SOURCE_ID,
                    "run_id": RUN_ID,
                    "occurred_at": ts,
                    "model_label": "no helmet",
                    "reason": "demo: 未戴盔候选",
                    "created_at": ts,
                }
            insert_pass_with_event(conn, passed, event)
    finally:
        conn.close()
    return {"db": str(path), "passes": len(PASSES), "events": 2, "run_id": RUN_ID}


def main() -> None:
    info = seed()
    print(
        f"seed ok: db={info['db']} passes={info['passes']} "
        f"events={info['events']} run={info['run_id']}"
    )


if __name__ == "__main__":
    main()
