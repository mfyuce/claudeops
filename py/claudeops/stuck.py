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
from .tmux_backend import is_tmux_backed
from .turns import is_busy_now


# CPU eşiği: bunun altındaysa ve son mesaj user'sa → stuck
STUCK_CPU_THRESHOLD = 2.0


@dataclass
class StuckInfo:
    session: Session
    last_role: str


def find_stuck(sessions: Optional[List[Session]] = None) -> List[StuckInfo]:
    """Stuck session'ları döndür (CPU düşük + son rol = user + gerçekten busy değil)."""
    if sessions is None:
        sessions = find_sessions(measure_cpu=True)

    stuck = []
    for s in sessions:
        if s.cpu >= STUCK_CPU_THRESHOLD:
            continue  # işliyor, stuck değil
        provider = get_provider(s.cli)
        if not provider.has_conversation():
            continue  # ör. düz shell: idle CPU normal, "stuck" kavramı yok — kill+resume ETME
        if _is_busy(provider, s):
            continue  # API yanıtı bekliyor (network-bound, CPU düşük) — SAĞLIKLI, stuck değil
        role = provider.last_message_role(s.cwd, s.sid)
        if role is None:
            continue  # transkript yok/desteklenmiyor → bilinmiyor, stuck sayma
        if role == "user":
            stuck.append(StuckInfo(session=s, last_role=role))
    return stuck


def _is_busy(provider, s: Session) -> bool:
    """`web.py::_is_busy_cached`'in önbelleksiz hâli (2026-10-03 review PROC-05)
    — `find_stuck()` web'in sık poll döngüsü gibi çağrılmıyor, 2sn TTL'e gerek
    yok. CPU<2%+son-mesaj-user "stuck" imzası, API yanıtı bekleyen (network-
    bound, CPU doğal olarak düşük) SAĞLIKLI bir turla AYNIYDI — `--recover`
    öyle bir session'ı turun ortasında öldürebiliyordu. Belirsiz durumda
    (`live_busy` None, tmux-backed değil, pattern yok) False döner — yani
    MEVCUT CPU+rol sezgisine geri düşer, davranışı değiştirmez; sadece GERÇEK
    busy kanıtı varsa stuck sayımından çıkarır."""
    live = provider.live_busy(s.cwd, s.sid)
    if live is not None:
        return live
    if not is_tmux_backed(s.pid):
        return False
    pattern = provider.busy_status_pattern()
    if not pattern:
        return False
    return is_busy_now(s.name, pattern)


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
