"""`kill` — session'ı nazikçe kapat (SIGTERM + 8s grace + sadece canlıysa SIGKILL)."""
from __future__ import annotations
from ..discovery import find_by_name
from ..kill import kill_session_and_parent


def register(sub):
    p = sub.add_parser("kill", help="session'ı nazikçe kapat (SIGTERM + 8s grace)")
    p.add_argument("names", nargs="+", metavar="NAME",
                   help="session adları (ör. hc54 sase54)")
    p.add_argument("--grace", type=float, default=8.0, metavar="SEC",
                   help="SIGKILL öncesi bekleme sn (varsayılan: 8)")
    p.add_argument("--dry-run", action="store_true",
                   help="sadece göster, öldürme")
    p.set_defaults(func=run)


def run(args) -> int:
    errors = 0
    for name in args.names:
        procs = find_by_name(name, measure_cpu=False)
        if not procs:
            print(f"  {name}: proc bulunamadı")
            errors += 1
            continue
        for s in procs:
            if args.dry_run:
                print(f"  [dry-run] {name} pid={s.pid} — öldürülmeyecek")
                continue
            print(f"  {name} pid={s.pid} → SIGTERM + {args.grace:.0f}s grace...",
                  end="", flush=True)
            result = kill_session_and_parent(s.pid, grace=args.grace, name=s.name)
            print(f" {result}")
    return errors
