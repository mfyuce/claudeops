"""Çalışan claude session'larını psutil ile keşfet.

Bash'teki `ps -eo args | grep -P '^claude' | grep -- '--remote-control NAME(\\s|$)'`
zincirinin yerine geçer. psutil cmdline'ı LİSTE olarak verir → quoting/anchor/substring
tuzakları YOK (bu gece hc53≠hcr53 ve trailing-space bug'ları tam bu yüzden çıkmıştı).
"""
from __future__ import annotations
from typing import List, Optional
import os
import time
import psutil

from .session import Session


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    """cmdline listesinde `flag`'ten SONRAKİ değeri döndür (yoksa None)."""
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


def _is_claude_proc(cmd: List[str]) -> bool:
    """Gerçek claude CLI proc'u mu? (gnome-terminal/bash wrapper'ları DEĞİL).

    Bash `^claude` anchor'ının karşılığı: argv[0]'ın basename'i 'claude'.
    'bash -c "claude ..."' wrapper'ında argv[0]='bash' → eler.
    """
    return bool(cmd) and os.path.basename(cmd[0]) == "claude"


def find_sessions(measure_cpu: bool = True) -> List[Session]:
    """Tüm çalışan RC session'larını döndür (her isim için tek Session — dup varsa hepsi)."""
    raw = []  # (proc, cmdline)
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            if not _is_claude_proc(cmd):
                continue
            if _arg(cmd, "--remote-control") is None:
                continue
            raw.append((p, cmd))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # CPU'yu toplu ölç: önce hepsini "prime" et, kısa bekle, sonra oku
    # (per-proc interval=0.1 yerine tek 0.3s → 27 proc için ~0.3s, 2.7s değil)
    if measure_cpu:
        for p, _ in raw:
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass
        time.sleep(0.3)

    sessions: List[Session] = []
    for p, cmd in raw:
        try:
            cpu = 0.0
            if measure_cpu:
                try:
                    cpu = p.cpu_percent(None)
                except psutil.Error:
                    cpu = 0.0
            try:
                cwd = p.cwd()  # bash'teki readlink /proc/PID/cwd + encoding'in yerine
            except (psutil.Error, FileNotFoundError):
                cwd = ""
            name = _arg(cmd, "--remote-control")
            if not name:
                continue  # --remote-control son arg veya değer yok → atla
            if not cwd:
                continue  # proc TOCTOU ölümü — cwd alınamadı
            sessions.append(Session(
                name=name,
                pid=p.pid,
                cwd=cwd,
                sid=_arg(cmd, "--resume"),
                model=_arg(cmd, "--model"),
                permission_mode=_arg(cmd, "--permission-mode"),
                effort=_arg(cmd, "--effort"),
                cpu=cpu,
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sessions


def find_by_name(name: str, measure_cpu: bool = False) -> List[Session]:
    """Belirli isimdeki session'lar (dup tespiti için liste döner)."""
    return [s for s in find_sessions(measure_cpu=measure_cpu) if s.name == name]


def duplicates(sessions: List[Session]) -> List[str]:
    """Birden fazla proc'u olan isimler (guard yarışı / dup felaketi tespiti)."""
    from collections import Counter
    counts = Counter(s.name for s in sessions)
    return sorted(n for n, c in counts.items() if c > 1)
