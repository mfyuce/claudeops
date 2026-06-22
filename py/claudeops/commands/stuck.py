"""`stuck` — stuck session'ları tespit et, opsiyonel olarak kurtar.

Stuck = son jsonl girişi user mesajı + CPU < 2%.

Kullanım:
  py/cops stuck               # stuck olanları listele
  py/cops stuck --recover     # stuck olanları kill + resume ile kurtar
  py/cops stuck --recover --dry-run
  py/cops stuck --suffix=54   # sadece *54 session'larını kontrol et
"""
from __future__ import annotations
from ..discovery import find_sessions
from ..stuck import find_stuck, recover_stuck, STUCK_CPU_THRESHOLD
from ..spawn import detect_display


def register(sub):
    p = sub.add_parser("stuck", help="stuck session'ları tespit et (son=user + düşük CPU)")
    p.add_argument("--recover", action="store_true",
                   help="stuck olanları kill+resume ile kurtar")
    p.add_argument("--dry-run", action="store_true",
                   help="--recover ile: sadece göster, yapma")
    p.add_argument("--suffix", type=int, default=None, metavar="N",
                   help="sadece bu suffix'i kontrol et (ör. 54)")
    p.add_argument("--no-cpu", action="store_true",
                   help="CPU ölçmeden hızlı kontrol (daha az güvenilir)")
    p.add_argument("--display", default=None)
    p.add_argument("--grace", type=float, default=8.0, metavar="SEC")
    p.set_defaults(func=run)


def run(args) -> int:
    sessions = find_sessions(measure_cpu=not args.no_cpu)
    if args.suffix is not None:
        sessions = [s for s in sessions if s.suffix == args.suffix]

    stuck_list = find_stuck(sessions)

    if not stuck_list:
        print(f"✓ stuck session yok (CPU eşiği: {STUCK_CPU_THRESHOLD}%, "
              f"{len(sessions)} session kontrol edildi)")
        return 0

    print(f"⚠ {len(stuck_list)} stuck session (son=user, CPU<{STUCK_CPU_THRESHOLD}%):")
    print(f"{'NAME':<13}{'PID':>8}  {'CPU%':>6}  {'JSONL':>10}")
    print("-" * 55)
    for info in stuck_list:
        s = info.session
        jsonl_short = info.jsonl_path.split("/")[-1][:20]
        print(f"{s.name:<13}{s.pid:>8}  {s.cpu:>6.1f}  {jsonl_short}")

    if not args.recover:
        print()
        print("  Kurtarmak için: py/cops stuck --recover [--dry-run]")
        return 1  # stuck var = hata kodu

    # Recovery
    display = args.display or detect_display()
    print()
    errors = 0
    for info in stuck_list:
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"  {prefix}{info.session.name} pid={info.session.pid}...",
              end="", flush=True)
        result = recover_stuck(info, display=display, grace=args.grace, dry_run=args.dry_run)
        print(f" {result}")
        if result == "kill-failed":
            errors += 1

    return errors
