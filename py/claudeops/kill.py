"""Nazik kill — SIGTERM + grace + sadece canlıysa SIGKILL.

Kural ([[claude-2183-conversation-truncation]]):
  SIGTERM → ~8-10s bekle → sadece hâlâ canlıysa SIGKILL.
  Grace < 2s = lazy-checkpoint flushing bitmeden keser → jsonl TRUNCATE.
  0.3s'de SIGKILL = haftalarca veri kaybı (2026-06-21 kanıtlandı, adad34f).
"""
from __future__ import annotations
import signal
import subprocess
import time
from typing import Literal, Optional

import psutil

KillResult = Literal["clean", "forced", "already_dead"]

# Minimum güvenli grace süresi — lazy-checkpoint flush için gerekli
# ([[claude-2183-conversation-truncation]]: 0.3s = truncation, 8s = güvenli kanıtlandı)
KILL_GRACE_SECONDS: float = 10.0


def _close_windows_by_exact_title(title: str) -> int:
    """`wmctrl -l` çıktısını parse edip title'ı BİREBİR eşleşen (substring DEĞİL —
    ör. `co` `cops`'un içinde geçiyor, ikisi de aynı anda canlı roster'da olabilir)
    pencereleri `xdotool windowkill` ile kapatır. `windowkill` (WM_DELETE_WINDOW
    DEĞİL, X-seviyesinde XKillClient) bilerek seçildi — gnome-terminal'in "işlem
    çalışıyor, kapatılsın mı?" onay diyaloğunu tetikleme riskini bypass eder (o an
    pencerede zaten boş/orphan bir bash prompt'u var, kaybedilecek iş yok).

    Best-effort: wmctrl/xdotool yoksa ya da hiç eşleşme yoksa sessizce 0 döner,
    çağıran akışı (kill) ASLA etkilemez/kesmez."""
    try:
        r = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
    except Exception:
        return 0
    closed = 0
    for line in r.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[3] == title:
            try:
                subprocess.run(["xdotool", "windowkill", parts[0]], capture_output=True, timeout=5)
                closed += 1
            except Exception:
                pass
    return closed


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


def kill_session_and_parent(pid: int, grace: float = KILL_GRACE_SECONDS,
                             name: Optional[str] = None) -> KillResult:
    """kill_session + parent bash'i de öldür (terminal penceresi kapansın).

    TODO-b kök sebep fix: spawn.py terminali `bash -c "...; exec bash"` ile açıyor,
    yani claude proc'u öldürmek terminali kapatmaz — parent bash `exec bash`'e düşüp
    boş prompt'ta orphan kalır. Parent, kill'den ÖNCE resolve edilmeli (sonrasında
    pid kaybolur/reuse riski) ([[review: parent-bash race]]).

    tmux-backed session'larda bu "parent'ı da öldür" tetiği YASAK: pane'in parent'ı
    paylaşılan tmux SERVER'ı olabilir (bash'in `-c` son-komut exec-optimizasyonuna
    göre değişken, garantili değil) — parent'ı köre kılıç öldürmek TÜM tmux-backed
    filoyu tek seferde silebilir. tmux-backed ise ad-bazlı (`tmux kill-session -t
    NAME`) temizlik yapılır, PID ancestry'sine hiç dokunulmaz.
    """
    from .tmux_backend import is_tmux_backed, tmux_kill_session

    tmux_backed = False
    try:
        tmux_backed = is_tmux_backed(pid)
    except Exception:
        tmux_backed = False  # tespit başarısızsa davranışı DEĞİŞTİRME, legacy yol

    if tmux_backed:
        result = kill_session(pid, grace=grace)
        if name:
            tmux_kill_session(name)  # best-effort, idempotent (zaten ölmüşse sorun yok)
            # Session artık silindi → attached client (gnome-terminal'in "tmux
            # new-session -A ...; exec bash" komutu) döner, `; exec bash`'e düşüp
            # BOŞ pencerede ORPHAN kalır (TODO.md "tmux-backed stop orphan",
            # 2026-08-28). PID-ancestry'nin bu fonksiyonda tmux-backed için YASAK
            # olma sebebiyle AYNI sebepten (claude'un parent'ı paylaşımlı tmux
            # SERVER'a çıkıyor) outer gnome-terminal penceresiyle bir PID ilişkisi
            # de YOK — pencereyi ancak title'ından (spawn.py `--title={name}`,
            # tmux.conf `set-titles-string '#S'` ile teyitli) bulup kapatabiliriz.
            # Session zaten silindiği için bu artık güvenli (paylaşımlı server'a
            # dokunmuyor, sadece kendi penceresini) — TBD#11'in riski geçmişte kaldı.
            time.sleep(0.5)  # client'ın exec bash'e düşüp yerleşmesi için kısa settle
            _close_windows_by_exact_title(name)
        return result

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
