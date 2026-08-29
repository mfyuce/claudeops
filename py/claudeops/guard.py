"""Guard — eksik session'ları tespit ve respawn (crash-recovery).

Tasarım kararları:
- Base-name bazlı isimler (suffix YOK): session adı = base (hc, co, mo...).
  Çalışan session adı base'e indirgenir (hc58→hc, geçiş savunması) → hc varsa
  guard yeni hc açmaz.
- guard.lock (flock) → cron + manuel çakışmasını önler.
- Tek-tek spawn + delay → rate-limit riski düşük ([[mass-faz1-ratelimit-stuck]]).
"""
from __future__ import annotations
import fcntl
import os
import time
from contextlib import contextmanager
from typing import List, Optional
from dataclasses import dataclass, field

from .discovery import find_sessions, duplicates
from .roster import read_roster, read_models, RosterEntry
from .spawn import spawn_session, detect_display
from .paths import GUARD_LOCK


@contextmanager
def guard_lock(timeout: float = 10.0):
    """guard.lock'u exclusive flock ile tut."""
    lock_dir = os.path.dirname(GUARD_LOCK)
    os.makedirs(lock_dir, exist_ok=True)
    fd = open(GUARD_LOCK, "w")
    try:
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f"guard.lock {timeout:.0f}s içinde alınamadı — başka guard çalışıyor")
                time.sleep(0.5)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fd.close()
        except Exception:
            pass


@dataclass
class GuardResult:
    missing: List[RosterEntry]
    spawned: List[tuple]   # [(name, kind), ...]
    dups: List[str]
    error: Optional[str] = None
    closed: List[str] = field(default_factory=list)   # roster'da ama models.tsv'de yorumlu → guard AÇMAZ


def guard_once(
    display: Optional[str] = None,
    dry_run: bool = False,
    spawn_delay: float = 1.0,
) -> GuardResult:
    """Bir guard pass'ı: eksik session'ları bul ve aç.

    Base-name bazlı eşleme: çalışan session adı base'e indirgenir (hc58→hc,
    geçiş savunması) → hc çalışıyorsa guard yeni hc açmaz. İsimler artık
    suffix'siz (base-name); spawn adı = roster entry.name.
    """
    if display is None:
        display = detect_display()

    running = find_sessions(measure_cpu=False)
    roster = read_roster()
    models = read_models()

    # Base-name bazlı çalışan session seti (s.base: hc58→hc, hc→hc)
    running_bases = {s.base for s in running}

    # Sadece models.tsv'de aktif (# ile başlamayanlar) olanları dikkate al
    active_bases = set(models.keys())
    # Kapalı: roster'da olup models.tsv'de yorumlu (close/EMEKLİ) → guard AÇMAZ, görünür kıl
    closed = sorted(e.name for e in roster if e.name not in active_bases)
    missing = [e for e in roster if e.name in active_bases and e.name not in running_bases]
    dups = duplicates(running)
    spawned = []

    for entry in missing:
        name = entry.name
        model = models.get(entry.name) or entry.model or "claude-sonnet-4-6"
        if not model:
            model = "claude-sonnet-4-6"
        try:
            kind = spawn_session(
                name=name,
                cwd=entry.cwd,
                model=model,
                display=display,
                dry_run=dry_run,
                cli=entry.cli,
            )
        except Exception as e:
            kind = f"error:{e}"
        spawned.append((name, kind))
        if not dry_run and spawn_delay > 0 and entry is not missing[-1]:
            time.sleep(spawn_delay)

    return GuardResult(missing=missing, spawned=spawned, dups=dups, closed=closed)
