"""`list` / `ls` — çalışan session'ları göster (read-only, ilk devralınan komut).

Bash `claudeops list`'in karşılığı; ek olarak CPU'yu birinci sınıf gösterir
(bu gece öğrenilen ders: session.json status/bridge GECİKMELİ, CPU güvenilir).
"""
from __future__ import annotations

from ..discovery import find_sessions, duplicates


def register(sub):
    p = sub.add_parser("list", aliases=["ls"], help="çalışan session'ları listele")
    p.add_argument("--no-cpu", action="store_true", help="CPU ölçme (daha hızlı)")
    p.add_argument("--base", help="sadece bu taban isim (ör. hc)")
    p.set_defaults(func=run)


def run(args) -> int:
    sessions = find_sessions(measure_cpu=not args.no_cpu)
    if args.base:
        sessions = [s for s in sessions if s.base == args.base]
    sessions.sort(key=lambda s: s.name)

    print(f"{'NAME':<13}{'PID':>8}  {'MODEL':<7}{'CPU%':>6}  {'KIND':<6} CWD")
    print("-" * 80)
    for s in sessions:
        kind = "fresh" if s.is_fresh else "resume"
        print(f"{s.name:<13}{s.pid:>8}  {s.model_short:<7}{s.cpu:>6.1f}  {kind:<6} {s.cwd}")

    print(f"\n  {len(sessions)} session", end="")
    dups = duplicates(sessions)
    if dups:
        print(f"  |  ⚠ DUP: {', '.join(dups)}")
    else:
        print("  |  dup yok")
    return 0
