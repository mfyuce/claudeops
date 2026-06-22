"""Handover Faz 1 — eski session'ı kapat, aynı masaya wrap-up mesajıyla yeniden aç.

Bash akışı (visible mode):
  1. Kill eski proc (SIGTERM + 10s grace + SIGKILL)
  2. Kill parent bash (terminal penceresi kapansın — SIGKILL, anlık)
  3. gnome-terminal aç: claude --resume SID -n NAME --remote-control NAME 'MSG'
  4. Proc-presence bekle (başarı kriteri = proc canlı, bridge-field DEĞİL)

Throttle ([[mass-faz1-ratelimit-stuck]]): rate-limit önlemek için batch_size'lı gruplar +
batch_delay arası bekleme.

Handover DOKUNMASIN: co + ulaksec ([[co-ulaksec-guard-yes-ho-no]]).
"""
from __future__ import annotations
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import List, Optional

import psutil

from .discovery import find_sessions, find_by_name
from .kill import kill_session
from .session import Session
from .spawn import find_latest_jsonl, detect_display

# Base name'ler: handover hiçbir zaman bunlara dokunmaz
HO_EXCLUDE_BASES = {"co", "ulaksec"}

HANDOVER_MSG_DEFAULT = (
    "ÖNCE: CLAUDE.md BÜYÜKLÜK OPTİMİZASYONU. Dosya her session başında context e "
    "yüklendiği için kısa ve öz olmalı.\n"
    "- Eskimiş veya artık geçerli olmayan bilgileri ayıkla; gerekiyorsa DONE.md ye taşı.\n"
    "- Tekrar eden / kod-okunarak öğrenilebilir bilgileri çıkar.\n"
    "- Hedef: bir önceki halinden belirgin şekilde küçük + daha güncel.\n"
    "SONRA aşağıdaki handover akışına devam et.\n\n"
    "═══════════════════════════════════════════════\n\n"
    "Bu konuşmayı bitiriyoruz, yeni session a geçeceğiz. KAYIT KRİTİK.\n\n"
    "Lütfen şunları kontrol et ve eksikse tamamla:\n"
    "- Konuşup da not almadığımız bir şey kaldı mı?\n"
    "- İşten işe geçtiysen eski iş TODO ya kaydedilmiş mi?\n"
    "- Her şey commit ve push lu mu? (tüm remote lara)\n"
    "- TODO.md, CLAUDE.md, DONE.md, TOBEDECIDED.md güncel mi?\n"
    "- Yeni session a hazır mıyız?\n\n"
    "DEĞİŞEN DOSYALARDAN + GIT HISTORY DEN GERÇEK İŞİ ÇIKAR:\n"
    "- Son ~1 günde değişen TÜM dosyalara bak. Ne yapılmış, ne eklenmiş, ne düzeltilmiş.\n"
    "- Çıkan her şeyi yerine yaz: biten iş → DONE.md; açık iş → TODO.md; "
    "mimari bilgi → CLAUDE.md.\n"
    "SONRA tüm güncellemeleri commit + push et (tüm remote lara).\n\n"
    "Sonunda CLAUDE.md nin sonuna "
    "\"## READY FOR HANDOVER ($(date))\" başlığıyla 5-10 satırlık özet ekle.\n"
    "Bitince \"READY FOR HANDOVER\" özetiyle dön."
)


@dataclass
class Faz1Result:
    name: str
    status: str        # "opened" | "skipped-no-jsonl" | "failed-noproc" | "dry-run"
    detail: str = ""


@dataclass
class Faz1Summary:
    results: List[Faz1Result] = field(default_factory=list)

    @property
    def opened(self):
        return sum(1 for r in self.results if r.status == "opened")

    @property
    def failed(self):
        return sum(1 for r in self.results if r.status.startswith("failed"))

    @property
    def skipped(self):
        return sum(1 for r in self.results if r.status.startswith("skipped"))


def _kill_session_and_parent(pid: int, grace: float = 10.0) -> str:
    """Proc + parent bash'i öldür. Parent bash SIGKILL (terminal kapansın).

    Parent bash SIGTERM'den ÖNCE resolve edilmeli — kill sonrası pid kaybolur
    (ya NoSuchProcess ya da pid reuse riski). ([[review: parent-bash race]])
    """
    # Parent'ı KILL'den ÖNCE al
    parent_to_kill = None
    try:
        proc = psutil.Process(pid)
        parent = proc.parent()
        if parent and parent.name() == "bash":
            parent_to_kill = parent
    except psutil.NoSuchProcess:
        pass

    result = kill_session(pid, grace=grace)

    if parent_to_kill is not None:
        try:
            parent_to_kill.kill()
        except psutil.NoSuchProcess:
            pass

    return result


def _wait_proc(name: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_by_name(name, measure_cpu=False):
            return True
        time.sleep(1.0)
    return False


def _spawn_faz1(session: Session, message: str, display: str, dry_run: bool) -> str:
    """Eski session'ı kapat, wrap-up mesajıyla yeniden aç. Returns kind string."""
    jsonl = find_latest_jsonl(session.cwd)
    if not jsonl:
        return "skipped-no-jsonl"

    sid = jsonl.stem
    model_parts = f"--model {shlex.quote(session.model)}" if session.model else ""

    inner = (
        f"cd {shlex.quote(session.cwd)} && "
        f"claude --resume {shlex.quote(sid)} "
        f"-n {shlex.quote(session.name)} "
        f"{model_parts} "
        f"--remote-control {shlex.quote(session.name)} "
        f"{shlex.quote(message)} "
        f"< /dev/null"
    )

    if dry_run:
        return f"dry-run:{sid[:8]}"

    env = os.environ.copy()
    env["DISPLAY"] = display
    subprocess.Popen(
        ["gnome-terminal", "--window", f"--title=handover:{session.name}",
         f"--working-directory={session.cwd}",
         "--", "bash", "-c", f"{inner}; exec bash"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return f"resume:{sid[:8]}"


def handover_faz1(
    from_suffix: int,
    message: str = HANDOVER_MSG_DEFAULT,
    display: Optional[str] = None,
    dry_run: bool = False,
    batch_size: int = 5,
    batch_delay: float = 30.0,
    proc_wait: float = 15.0,
    grace: float = 10.0,
) -> Faz1Summary:
    """Faz 1: tüm fleet'e wrap-up mesajı gönder (eski proc kapat, yeni aç).

    batch_size + batch_delay: rate-limit önlemi ([[mass-faz1-ratelimit-stuck]]).
    """
    if display is None:
        display = detect_display()

    sessions = find_sessions(measure_cpu=False)
    targets = [
        s for s in sessions
        if s.suffix == from_suffix and s.base not in HO_EXCLUDE_BASES
    ]
    targets.sort(key=lambda s: s.base)

    summary = Faz1Summary()

    for i, session in enumerate(targets):
        # Batch delay
        if i > 0 and i % batch_size == 0 and not dry_run:
            print(f"  [{i}/{len(targets)}] batch tamamlandı, {batch_delay:.0f}s bekleniyor...")
            time.sleep(batch_delay)

        print(f"  {session.name} (pid={session.pid})...", end="", flush=True)

        # 1. Kill eski proc (dry-run'da atla)
        if not dry_run:
            _kill_session_and_parent(session.pid, grace=grace)

        # 2. Yeni terminal aç
        kind = _spawn_faz1(session, message, display, dry_run)

        if kind.startswith("skipped"):
            print(f" {kind}")
            summary.results.append(Faz1Result(session.name, kind))
            continue

        if dry_run:
            print(f" {kind}")
            summary.results.append(Faz1Result(session.name, "dry-run", kind))
            continue

        # 3. Proc-presence bekle
        time.sleep(3)
        found = _wait_proc(session.name, timeout=proc_wait)
        if found:
            print(f" opened ({kind})")
            summary.results.append(Faz1Result(session.name, "opened", kind))
        else:
            print(f" WARN: proc görünmedi ({kind})")
            summary.results.append(Faz1Result(session.name, "failed-noproc", kind))

    return summary
