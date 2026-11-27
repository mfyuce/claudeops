"""Stuck session tespiti ve recovery.

Stuck = transkriptteki son mesaj 'user' + CPU < 2%
(session mesajı aldı ama işlemedi — rate-limit/hang sinyali).

Referans: [[mass-faz1-ratelimit-stuck]] — son=user + terminal boş = stuck.
Recovery: kill + resume (son user mesajı transkriptte zaten var → CLI kaldığı yerden devam eder).

Tespit provider.last_message_role() üzerinden gider (CliProvider arayüzü) —
DOĞRUDAN claude'un jsonl'ına bakmaz, böylece agy/codex/copilot/ucli
session'ları için de çalışır (claude-özel bir dosya formatına hardcode değil).

claude'da hangi konuşmaya bakılacağı KESİN bilinmeli (TBD#419): `Session.sid`, yoksa sürecin kendi
`sessions/<pid>.json` kaydı. İkisi de yoksa oturum takılmış sayılmaz (dizindeki en yeni dosya kardeşinki olabilir);
yeniden açma da kararın verildiği konuşmayı sürdürür.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .discovery import find_sessions
from .kill import kill_session, kill_session_and_parent, KILL_GRACE_SECONDS
from .providers import get_provider
from .providers.claude_provider import _live_transcript, live_or_spawn_effort, live_or_spawn_model
from .session import Session
from .settings import default_model_for
from .spawn import _ids_held_by_others, spawn_session, detect_display
from .tmux_backend import is_tmux_backed
from .turns import is_busy_now


# CPU eşiği: bunun altındaysa ve son mesaj user'sa → stuck
STUCK_CPU_THRESHOLD = 2.0


@dataclass
class StuckInfo:
    session: Session
    last_role: str
    sid: Optional[str] = None   # kararın verildiği konuşma (claude'da hep dolu)


def find_stuck(sessions: Optional[List[Session]] = None) -> List[StuckInfo]:
    """Stuck session'ları döndür (CPU düşük + son rol = user + gerçekten busy değil)."""
    if sessions is None:
        sessions = find_sessions(measure_cpu=True)

    stuck = []
    for s in sessions:
        if s.cpu >= STUCK_CPU_THRESHOLD:
            continue  # işliyor, stuck değil
        provider = get_provider(s.cli)
        if not provider.wants_stuck_recovery():
            continue  # ör. düz shell: idle CPU normal, "stuck" kavramı yok — kill+resume ETME
        if _is_busy(provider, s):
            continue  # API yanıtı bekliyor (network-bound, CPU düşük) — SAĞLIKLI, stuck değil
        sid = s.sid
        if s.cli == "claude":
            sid = _own_conversation(s)
            if sid is None:
                continue  # hangi konuşma olduğu bilinmiyor → stuck sayma
        role = provider.last_message_role(s.cwd, sid)
        if role is None:
            continue  # transkript yok/desteklenmiyor → bilinmiyor, stuck sayma
        if role == "user":
            stuck.append(StuckInfo(session=s, last_role=role, sid=sid))
    return stuck


def _own_conversation(s: Session) -> Optional[str]:
    """claude oturumunun konuşma kimliği: `s.sid`, yoksa sürecin kendi kaydı (`_live_transcript` doğrulaması: pid,
    procStart, cwd). Çözülemezse None."""
    if s.sid:
        return s.sid
    path = _live_transcript(s.cwd, None, s.pid)
    return path.stem if path else None


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
    claude'da kararın verildiği konuşma (`info.sid`) sürdürülür; bilinmiyorsa ya da başka bir canlı oturum onu
    tutuyorsa süreç ÖLDÜRÜLMEZ ve "skipped: ..." döner.
    Returns: "recovered (<spawn kind>)" | "dry-run" | "skipped: <neden>". Öldürmenin sonucu (`already_dead` vb.) BİLEREK yok sayılır ve
    resume her zaman denenir; "kill-failed" diye bir dönüş YOK (eski belge yanlıştı).
    """
    if display is None:
        display = detect_display()

    s = info.session

    if dry_run:
        return "dry-run"

    sid = s.sid
    resume_id = None            # claude dışı: sağlayıcının kendi resume araması (davranış aynı)
    if s.cli == "claude":
        sid = resume_id = getattr(info, "sid", None) or _own_conversation(s)
        if sid is None:
            return "skipped: konuşma kimliği bilinmiyor"
        if sid in _ids_held_by_others(s.name):
            return "skipped: konuşmayı başka bir canlı oturum tutuyor"

    # canlı model/effort (jsonl): terminalde `/model` yapılmış session spawn-anı argv değerine DÖNMESİN (handover ile
    # aynı kural). Öldürmeden ÖNCE okunur: sid'siz oturumun kimliği sürecin kendi `sessions/<pid>.json` kaydından
    # çözülür, kayıt süreçle birlikte geçersizleşir.
    model = live_or_spawn_model(s.cli, s.cwd, sid, s.model or default_model_for(get_provider(s.cli)), pid=s.pid)
    effort = live_or_spawn_effort(s.cli, s.cwd, sid, s.effort or "max", pid=s.pid)

    # PROC-02: tmux/gnome ebeveynini de temizler (yalnız pid öldürmek tmux oturumunu/pencereyi artık bırakıyordu)
    kill_session_and_parent(s.pid, grace=grace, name=s.name)
    # already_dead olsa bile respawn et — proc ölmüş ama resume yine gerekli

    # Resume — prompt yok, jsonl'deki son user mesajı tetikleyecek
    kind = spawn_session(
        name=s.name,
        cwd=s.cwd,
        model=model,
        display=display,
        # PROC-04 artığı: kip okunamadıysa sağlayıcının KENDİ varsayılanı (`rc.py` ile aynı kural); sabit "auto" ucli'de
        # geçersiz kipti ve sağlayıcıdan bağımsız tam bypass varsayıyordu
        permission_mode=s.permission_mode or get_provider(s.cli).permission_modes()[0],
        effort=effort,
        force_new=False,
        dry_run=False,
        cli=s.cli,
        resume_id=resume_id,
    )
    return f"recovered ({kind})"
