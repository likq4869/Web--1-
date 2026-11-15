"""Helmet Guard 模式与路径配置。demo / live 使用不同的 SQLite 文件。"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID_MODES = ("demo", "live")
VALID_RUN_MODES = ("camera_check", "demo", "live")


def get_mode() -> str:
    mode = os.getenv("HELMET_GUARD_MODE", "demo").strip().lower()
    return mode if mode in ("demo", "live") else "demo"


def db_path_for_mode(mode: str) -> Path:
    """按运行模式解析 SQLite 路径，demo/live 互相隔离。"""
    m = (mode or "").strip().lower()
    if m == "live":
        return PROJECT_ROOT / "data" / "helmet_live.db"
    return PROJECT_ROOT / "data" / "helmet_demo.db"


def get_db_path() -> Path:
    override = os.getenv("HELMET_GUARD_DB", "").strip()
    if override:
        return Path(override)
    return db_path_for_mode(get_mode())


def resolve_effective_mode(cli_mode: str | None) -> str:
    """CLI --mode 优先于环境变量；空则跟随环境。非法回落 demo。"""
    if cli_mode and cli_mode.strip().lower() in VALID_RUN_MODES:
        return cli_mode.strip().lower()
    # camera_check 只来自 CLI，环境变量只有 demo/live
    return get_mode()


def apply_effective_mode(cli_mode: str | None) -> str:
    """统一采集模式与数据库路径：CLI 模式写回环境，后续 get_mode/get_db_path 一致。

    显式 HELMET_GUARD_DB（临时库）仍优先，用于测试隔离。
    --mode live 配合 demo 环境变量时，有效模式为 live，后续建库/心跳都走 live。
    """
    effective = resolve_effective_mode(cli_mode)
    # camera_check / demo 都映射到 demo 库；live 映射到 live 库
    api_mode = "live" if effective == "live" else "demo"
    os.environ["HELMET_GUARD_MODE"] = api_mode
    return effective


def get_heartbeat_expire_seconds() -> int:
    try:
        return int(os.getenv("HELMET_GUARD_HEARTBEAT_EXPIRE", "30").strip())
    except ValueError:
        return 30


def resolve_weights(path_str: str) -> Path:
    """相对路径相对项目根目录解析，避免 cwd 不同导致 live 权重误判。"""
    p = Path(path_str)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


HEARTBEAT_EXPIRE_SECONDS = 30  # 兼容旧引用，实际以 get_heartbeat_expire_seconds() 为准
ALERT_TEXT = "骑行请佩戴头盔"
EVENTS_PAGE_SIZE_MAX = 50
