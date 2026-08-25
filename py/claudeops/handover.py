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
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .discovery import find_sessions, find_by_name
from .kill import kill_session_and_parent, KILL_GRACE_SECONDS
from .needs_ho import needs_ho
from .session import Session
from .spawn import find_latest_jsonl, detect_display, spawn_session

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

HANDOVER_MSG_DEFAULT_EN = (
    "FIRST: CLAUDE.md SIZE OPTIMIZATION. This file gets loaded into context at the start of "
    "every session, so it should stay short and to the point.\n"
    "- Prune stale or no-longer-relevant info; move it to DONE.md if it's still worth keeping.\n"
    "- Remove anything repetitive or easily re-derived by reading the code.\n"
    "- Goal: noticeably smaller than before + more up to date.\n"
    "THEN continue with the handover flow below.\n\n"
    "═══════════════════════════════════════════════\n\n"
    "We're wrapping up this conversation and moving to a new session. RECORDING THIS IS CRITICAL.\n\n"
    "Please check the following and fill in anything missing:\n"
    "- Is there anything we discussed but never wrote down?\n"
    "- If you switched between tasks, was the earlier one recorded in TODO?\n"
    "- Is everything committed and pushed? (to all remotes)\n"
    "- Are TODO.md, CLAUDE.md, DONE.md, TOBEDECIDED.md up to date?\n"
    "- Are we ready for a new session?\n\n"
    "DERIVE THE REAL WORK FROM CHANGED FILES + GIT HISTORY:\n"
    "- Look at every file changed in roughly the last day. What was done, added, fixed.\n"
    "- Write each finding to the right place: finished work → DONE.md; open work → TODO.md; "
    "architectural info → CLAUDE.md.\n"
    "THEN commit + push all updates (to all remotes).\n\n"
    "Finally, append a 5-10 line summary to the end of CLAUDE.md under the heading "
    "\"## READY FOR HANDOVER ($(date))\".\n"
    "When done, reply with the \"READY FOR HANDOVER\" summary."
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


def _wait_proc(name: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_by_name(name, measure_cpu=False):
            return True
        time.sleep(1.0)
    return False


def _spawn_faz1(session: Session, message: str, display: str, dry_run: bool) -> str:
    """Eski session'ı kapat, wrap-up mesajıyla yeniden aç. Returns kind string.

    spawn_session()'a delege eder (eskiden kendi gnome-terminal Popen'ı vardı —
    CLAUDE* env filtresi olmadan, [[spawn-env-leak-disables-transcript]] bug'ına
    açıktı; artık web.py ile aynı ortak, güvenli yoldan geçiyor).
    """
    if not find_latest_jsonl(session.cwd):
        return "skipped-no-jsonl"
    return spawn_session(
        name=session.name,
        cwd=session.cwd,
        model=session.model or "claude-sonnet-5",
        display=display,
        permission_mode="auto",
        effort="max",
        force_new=False,
        prompt=message,
        dry_run=dry_run,
    )


def handover_faz1(
    message: str = HANDOVER_MSG_DEFAULT,
    display: Optional[str] = None,
    dry_run: bool = False,
    batch_size: int = 5,
    batch_delay: float = 30.0,
    proc_wait: float = 15.0,
    grace: float = KILL_GRACE_SECONDS,
    kill_settle: float = 3.0,
) -> Faz1Summary:
    """Faz 1: tüm aktif fleet'e wrap-up mesajı gönder (eski proc kapat, yeni aç).

    İsimler base-name (suffix yok) → tüm canlı session'lar (co/ulaksec hariç) hedef.
    batch_size + batch_delay: rate-limit önlemi ([[mass-faz1-ratelimit-stuck]]).
    kill_settle: kill onaylandıktan SONRA, respawn'dan ÖNCE bekleme. Faz1 AYNI
      --remote-control ismini reuse eder; proc ölse de server-side bridge deregister
      gecikir → settle olmadan isim çakışması (remote'da inactive flicker).
      ([[handover-edge-cases]] bridge trap)
    """
    if display is None:
        display = detect_display()

    # Ho başında timestamp yaz — needs_ho baseline karşılaştırması için (bash _handover_stamp)
    from .paths import STATE_DIR
    import datetime
    try:
        ts_file = STATE_DIR / "last-handover.ts"
        ts_file.parent.mkdir(parents=True, exist_ok=True)
        ts_file.write_text(datetime.datetime.now().astimezone().isoformat())
    except Exception:
        pass

    sessions = find_sessions(measure_cpu=False)
    targets = [
        s for s in sessions
        if s.base not in HO_EXCLUDE_BASES
    ]
    targets.sort(key=lambda s: s.base)

    summary = Faz1Summary()

    for i, session in enumerate(targets):
        # Batch delay
        if i > 0 and i % batch_size == 0 and not dry_run:
            print(f"  [{i}/{len(targets)}] batch tamamlandı, {batch_delay:.0f}s bekleniyor...")
            time.sleep(batch_delay)

        print(f"  {session.name} (pid={session.pid})...", end="", flush=True)

        # needs_ho kontrolü — skip kriteri: RFH var + repo temiz + yeni commit yok
        jsonl = find_latest_jsonl(session.cwd)
        jsonl_path = str(jsonl) if jsonl else None
        if not dry_run and not needs_ho(session.pid_str if hasattr(session, 'pid_str') else str(session.pid), session.cwd, jsonl_path):
            print(" skip (needs_ho=False: RFH var, repo temiz, yeni commit yok)")
            summary.results.append(Faz1Result(session.name, "skipped-no-ho"))
            continue

        # 1. Kill eski proc (dry-run'da atla)
        if not dry_run:
            kill_result = kill_session_and_parent(session.pid, grace=grace)
            # Server-side RC bridge'in AYNI ismi bırakması için settle.
            # proc.wait ölümü onaylar AMA bridge deregister async gecikir → aynı
            # isimle hemen respawn = çakışma. already_dead'de bridge zaten yok, atla.
            if kill_settle > 0 and kill_result != "already_dead":
                time.sleep(kill_settle)

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
