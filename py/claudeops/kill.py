"""Nazik kill — SIGTERM + grace + sadece canlıysa SIGKILL.

Kural ([[claude-2183-conversation-truncation]]):
  SIGTERM → ~8-10s bekle → sadece hâlâ canlıysa SIGKILL.
  Grace < 2s = lazy-checkpoint flushing bitmeden keser → jsonl TRUNCATE.
  0.3s'de SIGKILL = haftalarca veri kaybı (2026-06-21 kanıtlandı, adad34f).
"""
from __future__ import annotations
import signal
from typing import Literal

import psutil

KillResult = Literal["clean", "forced", "already_dead"]


def kill_session(pid: int, grace: float = 8.0) -> KillResult:
    """SIGTERM → grace saniye bekle → hâlâ canlıysa SIGKILL.

    Returns:
        "clean"       — SIGTERM yeterliydi, process temiz kapandı
        "forced"      — grace doldu, SIGKILL gerekti
        "already_dead" — process zaten çalışmıyordu
    """
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return "already_dead"

    try:
        proc.send_signal(signal.SIGTERM)
    except psutil.NoSuchProcess:
        return "already_dead"

    try:
        proc.wait(timeout=grace)
        return "clean"
    except psutil.TimeoutExpired:
        pass

    # Grace doldu — hâlâ canlı, SIGKILL
    try:
        proc.kill()
        proc.wait(timeout=2.0)
    except psutil.NoSuchProcess:
        pass
    return "forced"
