"""Stuck session tespiti ve recovery.

Stuck = jsonl'deki son 'role' değeri 'user' + CPU < 2%
(session mesajı aldı ama işlemedi — rate-limit/hang sinyali).

Referans: [[mass-faz1-ratelimit-stuck]] — jsonl son=user + terminal boş = stuck.
Recovery: kill + resume (son user mesajı jsonl'de zaten var → claude kaldığı yerden devam eder).
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import List, Optional

from .discovery import find_sessions
from .kill import kill_session, KILL_GRACE_SECONDS
from .providers import get_provider
from .session import Session
from .spawn import find_latest_jsonl, spawn_session, detect_display


# CPU eşiği: bunun altındaysa ve son mesaj user'sa → stuck
STUCK_CPU_THRESHOLD = 2.0

# Tail için okunacak byte miktarı — 32KB: büyük handover mesajları ~2KB,
# 32KB yeterli tampon; 8KB'de son mesaj büyükse stuck tespiti kaçabilirdi.
_TAIL_BYTES = 32768


def _last_role(jsonl_path: str) -> Optional[str]:
    """jsonl'deki son role değerini döndür (user / assistant / None)."""
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")

        last_role = None
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                role = d.get("role")
                if role in ("user", "assistant"):
                    last_role = role
            except json.JSONDecodeError:
                continue
        return last_role
    except Exception:
        return None


@dataclass
class StuckInfo:
    session: Session
    last_role: str
    jsonl_path: str


def find_stuck(sessions: Optional[List[Session]] = None) -> List[StuckInfo]:
    """Stuck session'ları döndür (CPU düşük + son rol = user)."""
    if sessions is None:
        sessions = find_sessions(measure_cpu=True)

    stuck = []
    for s in sessions:
        if s.cpu >= STUCK_CPU_THRESHOLD:
            continue  # işliyor, stuck değil
        if not get_provider(s.cli).has_conversation():
            continue  # ör. düz shell: idle CPU normal, "stuck" kavramı yok — kill+resume ETME
        jsonl = find_latest_jsonl(s.cwd)
        if not jsonl:
            continue  # jsonl yok, not stuck
        role = _last_role(str(jsonl))
        if role == "user":
            stuck.append(StuckInfo(session=s, last_role=role, jsonl_path=str(jsonl)))
    return stuck


def recover_stuck(
    info: StuckInfo,
    display: Optional[str] = None,
    grace: float = KILL_GRACE_SECONDS,
    dry_run: bool = False,
) -> str:
    """Stuck session'ı kapat ve resume ile yeniden aç.

    Resume'da prompt YOK — jsonl'deki son user mesajı zaten var,
    claude kaldığı yerden devam eder.
    Returns: "recovered" | "dry-run" | "kill-failed"
    """
    if display is None:
        display = detect_display()

    s = info.session

    if dry_run:
        return "dry-run"

    result = kill_session(s.pid, grace=grace)
    # already_dead olsa bile respawn et — proc ölmüş ama resume yine gerekli

    # Resume — prompt yok, jsonl'deki son user mesajı tetikleyecek
    kind = spawn_session(
        name=s.name,
        cwd=s.cwd,
        model=s.model or "claude-sonnet-4-6",
        display=display,
        permission_mode=s.permission_mode or "auto",
        effort=s.effort or "max",
        force_new=False,
        dry_run=False,
        cli=s.cli,
    )
    return f"recovered ({kind})"
