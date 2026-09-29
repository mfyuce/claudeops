"""Stuck session tespiti ve recovery.

Stuck = transkriptteki son mesaj 'user' + CPU < 2%
(session mesajı aldı ama işlemedi — rate-limit/hang sinyali).

Referans: [[mass-faz1-ratelimit-stuck]] — son=user + terminal boş = stuck.
Recovery: kill + resume (son user mesajı transkriptte zaten var → CLI kaldığı yerden devam eder).

Tespit provider.last_message_role() üzerinden gider (CliProvider arayüzü) —
DOĞRUDAN claude'un jsonl'ına bakmaz, böylece agy/codex/copilot/ucli
session'ları için de çalışır (claude-özel bir dosya formatına hardcode değil).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .discovery import find_sessions
from .kill import kill_session, KILL_GRACE_SECONDS
from .providers import get_provider
from .session import Session
from .settings import default_model_for
from .spawn import spawn_session, detect_display


# CPU eşiği: bunun altındaysa ve son mesaj user'sa → stuck
STUCK_CPU_THRESHOLD = 2.0


@dataclass
class StuckInfo:
    session: Session
    last_role: str


def find_stuck(sessions: Optional[List[Session]] = None) -> List[StuckInfo]:
    """Stuck session'ları döndür (CPU düşük + son rol = user)."""
    if sessions is None:
        sessions = find_sessions(measure_cpu=True)

    stuck = []
    for s in sessions:
        if s.cpu >= STUCK_CPU_THRESHOLD:
            continue  # işliyor, stuck değil
        provider = get_provider(s.cli)
        if not provider.has_conversation():
            continue  # ör. düz shell: idle CPU normal, "stuck" kavramı yok — kill+resume ETME
        role = provider.last_message_role(s.cwd, s.sid)
        if role is None:
            continue  # transkript yok/desteklenmiyor → bilinmiyor, stuck sayma
        if role == "user":
            stuck.append(StuckInfo(session=s, last_role=role))
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
        model=s.model or default_model_for(get_provider(s.cli)),
        display=display,
        permission_mode=s.permission_mode or "auto",
        effort=s.effort or "max",
        force_new=False,
        dry_run=False,
        cli=s.cli,
    )
    return f"recovered ({kind})"
