"""Nazik kill — SIGTERM + grace + sadece canlıysa SIGKILL.

Kural ([[claude-2183-conversation-truncation]]):
  SIGTERM → ~8-10s bekle → sadece hâlâ canlıysa SIGKILL.
  Grace < 2s = lazy-checkpoint flushing bitmeden keser → jsonl TRUNCATE.
  0.3s'de SIGKILL = haftalarca veri kaybı (2026-06-21 kanıtlandı, adad34f).
"""
from __future__ import annotations
import signal
from typing import Literal, Optional

import psutil

KillResult = Literal["clean", "forced", "already_dead"]

# Minimum güvenli grace süresi — lazy-checkpoint flush için gerekli
# ([[claude-2183-conversation-truncation]]: 0.3s = truncation, 8s = güvenli kanıtlandı)
KILL_GRACE_SECONDS: float = 10.0


def kill_session(pid: int, grace: float = KILL_GRACE_SECONDS) -> KillResult:
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
    except psutil.TimeoutExpired:
        pass  # zombie — kernel reap'i bekliyor, kill tamamlandı
    return "forced"


def kill_session_and_parent(pid: int, grace: float = KILL_GRACE_SECONDS) -> KillResult:
    """kill_session + parent bash'i de öldür (terminal penceresi kapansın).

    TODO-b kök sebep fix: spawn.py terminali `bash -c "...; exec bash"` ile açıyor,
    yani claude proc'u öldürmek terminali kapatmaz — parent bash `exec bash`'e düşüp
    boş prompt'ta orphan kalır. Parent, kill'den ÖNCE resolve edilmeli (sonrasında
    pid kaybolur/reuse riski) ([[review: parent-bash race]]).
    """
    parent_pid: Optional[int] = None
    parent_create_time: Optional[float] = None
    try:
        proc = psutil.Process(pid)
        parent = proc.parent()
        if parent and parent.name() == "bash":
            parent_pid = parent.pid
            parent_create_time = parent.create_time()
    except psutil.NoSuchProcess:
        pass

    result = kill_session(pid, grace=grace)

    if parent_pid is not None:
        try:
            p = psutil.Process(parent_pid)
            if p.create_time() == parent_create_time:
                p.kill()
        except psutil.NoSuchProcess:
            pass

    return result
