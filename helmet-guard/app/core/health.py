"""健康检查纯逻辑：模型 / 采集 / 数据库只读检查。

职责：心跳解析、模型就绪判定、采集状态判定、数据库只读检查。
依赖：sqlalchemy、app.db（SQLite）、app（模式与路径配置）。
边界：不含 FastAPI 路由装配；不建库，只做只读检查。

双库兼容（MySQL 8.0 / phpStudy）：
- SQLite 模式（默认 / 测试）：沿用原生 `sqlite3` 连接，行为与拆分前逐字等价。
- MySQL 模式（`DATABASE_URL` 以 `mysql` 开头）：改走 SQLAlchemy Session +
  仓储层只读查询，避免 `?` 占位符与 `sqlite_master` 方言在 MySQL 下报错。
  由 B-2 从 `app/main.py` 拆出，SQLite 行为逐字等价。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import get_db_path, get_heartbeat_expire_seconds, get_mode, resolve_weights
from app.db import connect, tables_exist

# 心跳行的解析结果：source_id/run_id/mode/updated_at + detail_parsed
Heartbeat = dict[str, Any]
# 模型状态：ready/reason/weights(/run_id)
ModelInfo = dict[str, Any]
# 点位采集状态：fps/stage 等
CaptureInfo = dict[str, Any]
# 统一 API 响应体
ApiResponse = dict[str, Any]


def is_mysql_mode() -> bool:
    """是否运行于 MySQL 模式（`DATABASE_URL` 以 mysql 开头）。

    Returns:
        MySQL 模式返回 True；SQLite/测试模式返回 False。
        配置解析失败时保守返回 False（沿用 SQLite 路径）。
    """
    try:
        from app.core.config import get_settings

        return get_settings().resolved_database_url.startswith("mysql")
    except Exception:
        return False


def _detail_of(row: Any) -> str | None:
    """兼容四种心跳行形态，取出 detail 原始字符串。

    Args:
        row: `sqlite3.Row`（支持 `row["detail"]` 但不是 `Mapping`/`dict`）
            / `Mapping` / `dict` / ORM 对象。

    Returns:
        detail 字符串；取不到时返回 None。
    """
    if isinstance(row, dict):
        value = row.get("detail")
        return str(value) if value is not None else None
    # `sqlite3.Row` 与 `Mapping` 都支持 `row["detail"]`；
    # `sqlite3.Row` 不是 `Mapping` 子类，故不做 `isinstance` 守卫直接尝试。
    try:
        value = row["detail"]
        return str(value) if value is not None else None
    except (KeyError, TypeError, IndexError):
        pass
    detail = getattr(row, "detail", None)
    return str(detail) if detail is not None else None


def hb_detail(row: Any) -> dict[str, Any]:
    """解析心跳 detail JSON；非法或非对象时按空对象处理。"""
    try:
        raw = _detail_of(row)
        parsed = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    # 心跳 detail 是采集进程写入的 JSON 对象；非对象时按空对象处理
    return parsed if isinstance(parsed, dict) else {}


def _row_to_dict(row: Any) -> dict[str, Any]:
    """把 sqlite3.Row / dict / ORM 心跳行归一化为普通字典。"""
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, Mapping):
        try:
            return dict(row)
        except (TypeError, ValueError):
            pass
    out: dict[str, Any] = {}
    for key in ("source_id", "run_id", "mode", "updated_at", "detail"):
        if hasattr(row, key):
            out[key] = getattr(row, key)
        else:
            try:
                out[key] = row[key]
            except (KeyError, TypeError, IndexError):
                out[key] = None
    return out


def all_heartbeats(conn: sqlite3.Connection) -> list[Heartbeat]:
    """读取全部心跳行并附加解析后的 detail（SQLite 路径）。"""
    rows = conn.execute("SELECT source_id,run_id,mode,updated_at,detail FROM heartbeats").fetchall()
    out: list[Heartbeat] = []
    for r in rows:
        d = _row_to_dict(r)
        d["detail_parsed"] = hb_detail(r)
        out.append(d)
    return out


def all_heartbeats_mysql(session: Session) -> list[Heartbeat]:
    """读取全部心跳行（MySQL 路径，仓储只读）。

    Args:
        session: 已指向 MySQL 的会话。

    Returns:
        心跳字典列表（含 `detail_parsed`）。
    """
    from app.repositories.dashboard import DashboardRepository

    out: list[Heartbeat] = []
    for row in DashboardRepository(session).heartbeat_rows():
        d = dict(row)
        d["detail_parsed"] = hb_detail(d)
        out.append(d)
    return out


def model_status(latest: Heartbeat | None) -> ModelInfo:
    """判定模型就绪状态（demo 直接就绪；live 以采集心跳为准）。"""
    mode = get_mode()
    if mode == "demo":
        return {"ready": True, "reason": "demo 模式使用合成事件，无需专用权重", "weights": None}
    # live：以采集进程上报的模型加载状态为准
    if latest is None:
        weights = str(resolve_weights(os.getenv("HELMET_GUARD_WEIGHTS", "weights/helmet_best.pt")))
        return {
            "ready": False,
            "reason": f"live 无采集心跳，需启动检测进程（期望权重 {weights}）",
            "weights": weights,
        }
    detail = latest.get("detail_parsed", {}) or {}
    weights = str(
        detail.get("weights")
        or resolve_weights(os.getenv("HELMET_GUARD_WEIGHTS", "weights/helmet_best.pt"))
    )
    if detail.get("stage") == "model_failed":
        return {
            "ready": False,
            "reason": f"模型加载失败：{detail.get('error', '未知错误')}",
            "weights": weights,
            "run_id": latest.get("run_id"),
        }
    if not detail.get("model_loaded"):
        return {
            "ready": False,
            "reason": "模型尚未加载（采集进程未报告就绪）",
            "weights": weights,
            "run_id": latest.get("run_id"),
        }
    if not detail.get("model_ok", False):
        return {
            "ready": False,
            "reason": f"权重被拒绝：{detail.get('model_info', '')}",
            "weights": weights,
            "run_id": latest.get("run_id"),
        }
    return {
        "ready": True,
        "reason": f"采集进程已加载模型：{detail.get('model_info', '')}",
        "weights": weights,
        "run_id": latest.get("run_id"),
    }


def capture_status(latest: Heartbeat | None, rows: list[Heartbeat]) -> CaptureInfo:
    """判定点位采集状态（首帧 / 心跳过期 / 停止 / 预览）。"""
    mode = get_mode()
    if latest is None:
        if mode == "demo":
            return {"ready": False, "reason": "demo 模式无实时采集", "heartbeats": []}
        return {"ready": False, "reason": "live 无采集心跳，需启动检测进程", "heartbeats": []}
    detail = latest.get("detail_parsed", {}) or {}
    hb_mode = latest.get("mode", "")
    # camera_check 心跳：仅预览，不做业务采集
    if hb_mode.startswith("camera_check"):
        return {
            "ready": False,
            "reason": f"camera_check 预览中（run={latest.get('run_id')}），"
            "仅显示 person 等类别，不写业务数据",
            "heartbeats": rows,
        }
    if mode == "demo" and not hb_mode.startswith("live"):
        return {"ready": False, "reason": "demo 模式无实时采集", "heartbeats": rows}
    stage = detail.get("stage", "")
    frames = detail.get("frames", 0)
    if stage == "stopped" or hb_mode.endswith("-stopped"):
        return {
            "ready": False,
            "reason": f"采集已停止 run={latest.get('run_id')} frames={frames}",
            "heartbeats": rows,
        }
    if stage == "model_failed":
        return {
            "ready": False,
            "reason": f"模型加载失败，未开始采集：{detail.get('error', '')}",
            "heartbeats": rows,
        }
    if not detail.get("had_first_frame") or frames <= 0:
        return {
            "ready": False,
            "reason": f"无首帧 run={latest.get('run_id')} 采集进程尚未收到有效画面",
            "heartbeats": rows,
        }
    # 心跳过期检查
    try:
        latest_dt = datetime.fromisoformat(latest["updated_at"])
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        age = (datetime.now().astimezone() - latest_dt).total_seconds()
    except (ValueError, TypeError, KeyError):
        # 时间戳格式非法：视为心跳已过期，避免误报为在线。
        age = 1e9
    expire = get_heartbeat_expire_seconds()
    if age > expire:
        return {"ready": False, "reason": f"心跳过期 {age:.0f}s>{expire}s", "heartbeats": rows}
    return {
        "ready": True,
        "reason": f"采集中 run={latest.get('run_id')} frames={frames}",
        "heartbeats": rows,
    }


def _mysql_db_info() -> dict[str, Any]:
    """MySQL 只读检查：返回 db_info（不建库）。

    Returns:
        db_info 字典；`ok` 为 True 时附带脱敏后的连接目标。
    """
    try:
        from app.core.config import get_settings
        from app.core.deps import build_engine

        url = get_settings().resolved_database_url
        # 日志/响应中绝不输出口令：只保留主机与库名。
        try:
            after_at = url.split("@", 1)[1] if "@" in url else url
        except (IndexError, AttributeError):
            after_at = "mysql"
        engine = build_engine()
        try:
            with Session(engine, future=True) as session:
                session.execute(text("SELECT 1")).scalar_one()
                # 至少核心表存在才算就绪（与 SQLite 的 tables_exist 对齐）。
                from sqlalchemy import inspect as _inspect

                names = set(_inspect(engine).get_table_names() or [])
                required = {"sources", "passes", "events", "reviews", "heartbeats", "alerts"}
                if not required.issubset(names):
                    return {
                        "ok": False,
                        "reason": "数据库未初始化：请先导入 Sql/helmet_guard_mysql.sql",
                        "path": f"mysql:{after_at}",
                    }
            return {"ok": True, "path": f"mysql:{after_at}"}
        finally:
            with suppress(Exception):
                engine.dispose()
    except Exception as exc:
        return {"ok": False, "reason": f"数据库不可用：{exc}", "path": "mysql"}


def db_status() -> tuple[dict[str, Any], Any | None]:
    """只读检查：不建库。返回 (db_info, conn_or_None)。

    MySQL 模式返回 `(db_info, None)`，调用方需改走仓储层；
    `system.py` 已按此分支处理。SQLite 模式保持原 `(db_info, conn)` 语义。
    """
    if is_mysql_mode():
        return _mysql_db_info(), None
    path = get_db_path()
    try:
        conn = connect()
    except (sqlite3.Error, OSError) as exc:
        return {"ok": False, "reason": f"数据库不可用：{exc}", "path": str(path)}, None
    try:
        if not tables_exist(conn):
            conn.close()
            return {
                "ok": False,
                "reason": "数据库未初始化：请先启动应用或运行种子",
                "path": str(path),
            }, None
        conn.execute("SELECT 1").fetchone()
        return {"ok": True, "path": str(path)}, conn
    except (sqlite3.Error, OSError) as exc:
        # 关闭失败不应掩盖原始异常（此时正要返回数据库错误原因）
        with suppress(sqlite3.Error, OSError):
            conn.close()
        return {"ok": False, "reason": str(exc), "path": str(path)}, None


def require_db() -> Any:
    """获取可用连接；不可用时抛 503（遗留原生 SQL 路由共用）。

    MySQL 模式下直接抛 503 并提示改走 ORM 路由；
    遗留路由已在入口按 `is_mysql_mode()` 分流，不会走到这里。
    """
    if is_mysql_mode():
        raise HTTPException(status_code=503, detail="MySQL 模式请走 ORM 查询接口")
    db, conn = db_status()
    if conn is None:
        raise HTTPException(status_code=503, detail=db.get("reason", "数据库未就绪"))
    return conn


__all__ = [
    "ApiResponse",
    "CaptureInfo",
    "Heartbeat",
    "ModelInfo",
    "all_heartbeats",
    "all_heartbeats_mysql",
    "capture_status",
    "db_status",
    "hb_detail",
    "is_mysql_mode",
    "model_status",
    "require_db",
]
