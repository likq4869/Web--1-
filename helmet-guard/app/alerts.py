"""现场提醒：单独队列、事件去重、点位限频、默认静默。"""

from __future__ import annotations

import sqlite3
import time
import wave
from pathlib import Path

from . import ALERT_TEXT
from .db import connect, tables_exist
from .store import _tx_begin, _tx_commit, _tx_rollback, enqueue_alert, now_iso

_last_alert_at: dict[str, float] = {}


def should_alert(
    alert_enabled: bool,
    event_id: str,
    source_id: str,
    in_zone: bool,
    frame_ok: bool,
    heartbeat_fresh: bool,
    cooldown_s: int,
) -> tuple[bool, str]:
    """人工确认未戴盔且目标仍在提醒区时才入队；否则过期/静默。

    event_id 保留在签名中：去重在 request_alert 层按 event_id 入队实现，
    此处保留是为了让判定逻辑的输入完整可读，便于将来按事件维度细化限频。
    """
    del event_id  # 明确标记「有意未使用」，避免误删接口契约
    if not alert_enabled:
        return False, "silent: 提醒开关关闭（默认静默）"
    if not in_zone:
        return False, "expired: 目标已离开提醒区"
    if not frame_ok:
        return False, "expired: 画面不可判定"
    if not heartbeat_fresh:
        return False, "expired: 心跳过期"
    now = time.time()
    last = _last_alert_at.get(source_id, 0.0)
    if now - last < cooldown_s:
        return False, f"suppressed: 点位限频 {cooldown_s}s 内已提醒"
    return True, "ok"


def _require_tables(conn: sqlite3.Connection) -> None:
    if not tables_exist(conn):
        raise RuntimeError("数据库未初始化：请先启动应用或运行种子")


def request_alert(
    event_id: str,
    source_id: str,
    run_id: str,
    alert_enabled: bool,
    in_zone: bool = True,
    frame_ok: bool = True,
    heartbeat_fresh: bool = True,
    cooldown_s: int = 60,
    note: str = "",
) -> tuple[bool, str]:
    """提醒入队：判定通过则入队，否则按静默/过期记录原因。

    run_id 保留在签名中：提醒记录当前只按 event_id 关联，但调用方（采集进程）
    按「点位 + 运行」组织请求，保留运行维度便于将来按运行维度追溯与限频。
    """
    del run_id  # 明确标记「有意未使用」，避免误删接口契约
    ok, reason = should_alert(
        alert_enabled, event_id, source_id, in_zone, frame_ok, heartbeat_fresh, cooldown_s
    )
    conn = connect()
    try:
        # 查询/提醒入口不再建库：只读检查，表缺失直接报错
        _require_tables(conn)
        if not ok:
            status = "silent" if reason.startswith("silent") else "expired"
            enqueue_alert(
                conn, f"alert-{event_id}", event_id, source_id, status=status, note=reason
            )
            return False, reason
        # 同一通行事件去重：UNIQUE(event_id) 保证一次通行最多提醒一次
        enqueue_alert(
            conn,
            f"alert-{event_id}",
            event_id,
            source_id,
            status="queued",
            note=note or f"{ALERT_TEXT}（待播放）",
        )
        _last_alert_at[source_id] = time.time()
        return True, "queued"
    finally:
        conn.close()


def mark_played(event_id: str) -> None:
    conn = connect()
    try:
        _require_tables(conn)
        _tx_begin(conn)
        try:
            conn.execute(
                "UPDATE alerts SET status='played',updated_at=? WHERE event_id=?",
                (now_iso(), event_id),
            )
            _tx_commit(conn)
        except sqlite3.Error:
            _tx_rollback(conn)
            raise
    finally:
        conn.close()


def play_wav(path: str | Path) -> tuple[bool, str]:
    """播放本地 WAV，播报文案对应「骑行请佩戴头盔」。返回 (成功, 说明)。"""
    p = Path(path)
    if not p.is_file():
        return False, f"WAV 不存在：{p}"
    try:
        with wave.open(str(p), "rb") as wf:
            frames, rate = wf.getnframes(), wf.getframerate()
            duration = frames / rate if rate else 0
        import winsound

        winsound.PlaySound(str(p), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True, f"playing {p.name} ~{duration:.1f}s"
    except (OSError, wave.Error, RuntimeError) as exc:
        return False, f"播放失败：{exc}"


def make_demo_wav(path: str | Path, seconds: float = 1.0, freq: float = 880.0) -> Path:
    """生成演示用 WAV（正弦提示音），用于无真实播报文件时验证队列流程。"""
    import math
    import struct

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    n = int(rate * seconds)
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for i in range(n):
            v = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            wf.writeframes(struct.pack("<h", v))
    return p
