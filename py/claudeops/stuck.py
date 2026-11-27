"""Stuck session tespiti ve recovery.

Stuck = transkriptteki son mesaj 'user' + CPU < 2%
(session mesajı aldı ama işlemedi — rate-limit/hang sinyali).

Referans: [[mass-faz1-ratelimit-stuck]] — son=user + terminal boş = stuck.
Recovery: kill + resume (son user mesajı transkriptte zaten var → CLI kaldığı yerden devam eder).

Tespit provider.last_message_role() üzerinden gider (CliProvider arayüzü) —
DOĞRUDAN claude'un jsonl'ına bakmaz, böylece agy/codex/copilot/ucli
session'ları için de çalışır (claude-özel bir dosya formatına hardcode değil).

claude, codex, agy ve copilot'ta hangi konuşmaya bakılacağı KESİN bilinmeli (TBD#419, TBD#425): claude'da
yalnız sürecin kendi `sessions/<pid>.json` kaydı; codex ve copilot'ta `Session.sid` (keşif onu yalnız
komut satırından alır); agy'de yalnız sürecin komut satırındaki `--conversation` (keşfin `Session.sid`i cwd
önbelleğinden tahmin olabilir). Kimlik yoksa ya da tam eşleşen kayıt yoksa oturum takılmış sayılmaz (dizindeki en yeni
konuşma kardeşinki olabilir); yeniden açma da kararın verildiği konuşmayı sürdürür.

Komut satırı kimliği CLI içinde `/new`, `/resume`, `/clear` ile BAYATLAR (TBD#427, rs/prov 28 Kas): claude'da karar
yalnız sürecin kendi kaydından (claude konuşma değişince kaydı yeniler; komut satırından gelmiş olabilecek
`Session.sid` karar vermez); copilot'ta süreç yalnız o konuşmanın `session-state/<kimlik>/inuse.<pid>.hold` dosyasını
tutuyorsa (`/new` yeni konuşmanınkini de açar, eskisini bırakmaz; ölçüm 1.0.117); codex ve agy'de canlı konuşmayı
gösteren yerel kanıt YOK (codex 0.166 konuşmaları ortak app-server süreci tutar, eskisini kapatmaz), yalnız AYNI
dizinde süreç başladıktan sonra yazılmış başka konuşma varsa karar verilmez. Kalan sınır: yeni konuşmada hiç yazı
yoksa (codex/agy) fark edilmez.
"""
from __future__ import annotations
from dataclasses import dataclass
import glob
import json
import os
import re
from typing import List, Optional

import psutil

from .discovery import find_sessions
from .kill import kill_session, kill_session_and_parent, KILL_GRACE_SECONDS
from .providers import get_provider
from .providers import agy_provider, codex_provider
from .providers.base import _path_part_ok
from .providers.claude_provider import _live_transcript, live_or_spawn_effort, live_or_spawn_model
from .session import Session
from .settings import default_model_for
from .spawn import _ids_held_by_others, spawn_session, detect_display
from .tmux_backend import is_tmux_backed
from .turns import is_busy_now


# CPU eşiği: bunun altındaysa ve son mesaj user'sa → stuck
STUCK_CPU_THRESHOLD = 2.0

# Kararı yalnız kesin bilinen konuşmadan verilen sağlayıcılar (ucli'de kimlik oturum adının kendisi).
_OWN_ID_CLIS = ("claude", "codex", "agy", "copilot")


@dataclass
class StuckInfo:
    session: Session
    last_role: str
    sid: Optional[str] = None   # kararın verildiği konuşma (`_OWN_ID_CLIS`te hep dolu)


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
        if s.cli in _OWN_ID_CLIS:
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
    """`_OWN_ID_CLIS` oturumunun kesin konuşma kimliği (modül açıklaması); çözülemezse ya da komut satırı kimliğinin
    bayatladığına dair kanıt varsa None. claude kaydı `_live_transcript` doğrulamasından geçer (pid, procStart, cwd)."""
    if s.cli == "claude":
        # `Session.sid` kayıt yoksa komut satırından gelir (keşif): yalnız kaydın kendisi karar verir
        path = _live_transcript(s.cwd, None, s.pid)
        return path.stem if path else None
    sid = _argv_conversation(s) if s.cli == "agy" else s.sid
    if not sid or not _argv_id_current(s, sid):
        return None
    return sid


# copilot'un açık konuşma işareti: `session-state/<kimlik>/inuse.<pid>.hold` (ve `.lock`), süreç açık tutar.
_COPILOT_INUSE_RE = re.compile(r"/session-state/([^/]+)/inuse\.(\d+)\.(?:hold|lock)$")


def _argv_id_current(s: Session, sid: str) -> bool:
    """Komut satırındaki kimliğin bayatladığına dair kanıt yok mu (modül açıklaması). Okunamayan her şey = bayat
    olabilir (False)."""
    try:
        proc = psutil.Process(s.pid)
        if s.cli == "copilot":
            held = set()
            for f in proc.open_files():
                m = _COPILOT_INUSE_RE.search(str(getattr(f, "path", "")))
                if m and int(m.group(2)) == s.pid:
                    held.add(m.group(1))
            return held == {sid}
        started = float(proc.create_time())
    except (psutil.Error, OSError, TypeError, ValueError):
        return False
    if s.cli == "codex":
        return not _codex_newer_here(s.cwd, sid, started)
    if s.cli == "agy":
        return not _agy_cache_moved(s.cwd, sid, started)
    return True


def _codex_newer_here(cwd: str, sid: str, started: float) -> bool:
    """Aynı dizinde, süreç başladıktan sonra yazılmış başka rollout var mı (başı okunamayan = var sayılır)."""
    target = os.path.normpath(os.path.abspath(cwd))
    for path in glob.glob(os.path.join(codex_provider.SESSIONS_DIR, "*", "*", "*", "*.jsonl")):
        try:
            if os.stat(path).st_mtime < started:
                continue
        except OSError:
            continue
        if codex_provider._rollout_sid_matches(path, sid):
            continue
        meta = codex_provider._session_meta(path)
        raw = meta.get("cwd") if meta else None
        if not isinstance(raw, str) or os.path.normpath(os.path.abspath(raw)) == target:
            return True
    return False


def _agy_cache_moved(cwd: str, sid: str, started: float) -> bool:
    """agy'nin kendi cwd önbelleği bu dizinde, süreç başladıktan sonra yazılmış başka konuşmayı mı gösteriyor
    (okunamayan önbellek = gösteriyor sayılır)."""
    try:
        with open(agy_provider.CONVERSATIONS_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        return False
    except (OSError, ValueError, RecursionError):
        return True
    if not isinstance(cache, dict):
        return True
    cur = cache.get(cwd)
    if not isinstance(cur, str) or not cur.strip() or cur.strip() == sid:
        return False
    cur = cur.strip()
    if not _path_part_ok(cur):
        return True
    try:
        return os.stat(os.path.join(agy_provider.CONVERSATIONS_DIR, f"{cur}.db")).st_mtime >= started
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _argv_conversation(s: Session) -> Optional[str]:
    """Sürecin komut satırındaki devam kimliği. `extract_info` cwd ve ad verilmeden çağrılır: yalnız argv okunur,
    öğrenilen eşleşmeye yazılmaz. Süreç okunamıyorsa ya da artık o CLI değilse None."""
    try:
        cmd = psutil.Process(s.pid).cmdline()
    except (psutil.Error, OSError):
        return None
    provider = get_provider(s.cli)
    if not provider.matches_proc(cmd):
        return None
    return provider.extract_info(cmd).get("sid") or None


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
    `_OWN_ID_CLIS`te kararın verildiği konuşma (`info.sid`) sürdürülür; bilinmiyorsa ya da başka bir canlı oturum onu
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
    resume_id = None            # ötekiler (ucli): sağlayıcının kendi resume araması
    if s.cli in _OWN_ID_CLIS:
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
