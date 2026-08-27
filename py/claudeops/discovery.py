"""Çalışan CLI session'larını (claude, agy, ...) psutil ile keşfet.

İki kaynak:
1. Proc-scan: her provider'ın `matches_proc`+`extract_name`'iyle tanınan proc'lar (asıl kaynak).
2. sessions/*.json: TUI içinden isim verilen claude proc'ları (cmdline'da RC yok ama json'da name var).
   → Bash all_sessions_tsv'nin iki-kaynak mantığı. Dedup: proc-scan öncelikli (daha fazla bilgi).

Not: claude 2.1.169 fresh --new session'lar sessions/<pid>.json YAZMIYOR (proc-scan yeterli).
claude 2.1.183+ TUI içi /name komutuyla verilen isimler proc cmdline'a yansımaz → json lazım.

Provider-agnostik: hangi CLI'ın hangi flag'lerle tanınacağı burada DEĞİL, her
provider'ın kendi `matches_proc`/`extract_name`/`extract_info`'sunda (providers/).
"""
from __future__ import annotations
from typing import Dict, List
import glob
import json
import os
import time
import psutil

from .session import Session
from .providers import PROVIDERS


def _sessions_from_json() -> Dict[str, Session]:
    """~/.claude/sessions/*.json → canlı session'ları döndür. {name: Session}

    Bash all_sessions_tsv birinci döngüsünün karşılığı: pid liveness + procStart doğrulaması.
    """
    sess_dir = os.path.expanduser("~/.claude/sessions")
    result: Dict[str, Session] = {}
    for f in glob.glob(os.path.join(sess_dir, "*.json")):
        try:
            with open(f) as fh:
                d = json.load(fh)
        except Exception:
            continue
        pid = d.get("pid")
        name = d.get("name") or ""
        if not pid or not name:
            continue
        try:
            pid = int(pid)
        except (ValueError, TypeError):
            continue
        # Liveness: proc yaşıyor mu?
        try:
            os.kill(pid, 0)
        except OSError:
            continue  # ölü proc → atla
        # procStart doğrulaması: OOM sonrası pid-reuse koruması (bash mantığı)
        want = str(d.get("procStart", "")).strip()
        if want:
            try:
                with open(f"/proc/{pid}/stat") as sf:
                    rest = sf.read().rsplit(")", 1)[1].split()
                if rest[19] != want:
                    continue  # procStart eşleşmiyor → stale json
            except Exception:
                pass  # /proc okuma başarısızsa geç (docker/container gibi)
        # cwd
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = d.get("cwd") or ""
        if not cwd:
            continue
        # SID: sessionId alanından
        sid = d.get("sessionId") or None
        result[name] = Session(
            name=name,
            pid=pid,
            cwd=cwd,
            sid=sid,
            model=None,      # json'da model bilgisi yok; cmdline merge'de doldurulur
            permission_mode=None,
            effort=None,
            cpu=0.0,
            cli="claude",     # bu kaynak (~/.claude/sessions/*.json) sadece claude'a özel
        )
    return result


def find_sessions(measure_cpu: bool = True) -> List[Session]:
    """Tüm çalışan session'ları döndür (her isim için tek Session — dup varsa hepsi).

    Kaynak 1: sessions/*.json (TUI-named + spawn-named, claude-only)
    Kaynak 2: proc-scan — her provider kendi `matches_proc`/`extract_name`'iyle
    tanır (bilgi zengini; json'u override eder). Dedup: proc-scan override →
    merge sonucunda her isim bir kez.
    """
    # Kaynak 1: sessions json (başlangıç seti)
    by_name: Dict[str, Session] = _sessions_from_json()

    # Kaynak 2: proc-scan → hangi provider'ın olduğunu ilk eşleşen belirler
    raw = []  # (proc, cmdline, provider)
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            provider = next((pr for pr in PROVIDERS.values() if pr.matches_proc(cmd)), None)
            if provider is None:
                continue
            raw.append((p, cmd, provider))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # CPU'yu toplu ölç: önce hepsini "prime" et, kısa bekle, sonra oku
    # (per-proc interval=0.1 yerine tek 0.3s → 27 proc için ~0.3s, 2.7s değil)
    cpu_primed: Dict[int, psutil.Process] = {}
    if measure_cpu:
        for p, _, _ in raw:
            try:
                p.cpu_percent(None)
                cpu_primed[p.pid] = p
            except psutil.Error:
                pass
        # json-kaynaklı proc'ları da prime et
        for s in by_name.values():
            if s.pid not in cpu_primed:
                try:
                    pr = psutil.Process(s.pid)
                    pr.cpu_percent(None)
                    cpu_primed[s.pid] = pr
                except psutil.Error:
                    pass
        time.sleep(0.3)

    for p, cmd, provider in raw:
        try:
            cpu = 0.0
            if measure_cpu:
                try:
                    cpu = p.cpu_percent(None)
                except psutil.Error:
                    cpu = 0.0
            try:
                cwd = p.cwd()
            except (psutil.Error, FileNotFoundError):
                cwd = ""
            name = provider.extract_name(p, cmd)
            if not name:
                continue
            if not cwd:
                continue
            info = provider.extract_info(cmd)
            by_name[name] = Session(
                name=name,
                pid=p.pid,
                cwd=cwd,
                sid=info.get("sid"),
                model=info.get("model"),
                permission_mode=info.get("permission_mode"),
                effort=info.get("effort"),
                cpu=cpu,
                cli=provider.name,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # JSON-only session'lar için CPU ölç
    if measure_cpu:
        for name, s in by_name.items():
            if s.cpu == 0.0 and s.pid in cpu_primed:
                try:
                    s.cpu = cpu_primed[s.pid].cpu_percent(None)
                except psutil.Error:
                    pass

    return list(by_name.values())


def find_by_name(name: str, measure_cpu: bool = False) -> List[Session]:
    """Belirli isimdeki session'lar (dup tespiti için liste döner)."""
    return [s for s in find_sessions(measure_cpu=measure_cpu) if s.name == name]


def duplicates(sessions: List[Session]) -> List[str]:
    """Birden fazla proc'u olan isimler (guard yarışı / dup felaketi tespiti)."""
    from collections import Counter
    counts = Counter(s.name for s in sessions)
    return sorted(n for n, c in counts.items() if c > 1)
