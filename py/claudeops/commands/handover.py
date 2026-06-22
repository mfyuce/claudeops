"""`handover` — Faz 1 wrap-up (eski session kapat, mesajla yeniden aç).

Kullanım:
  py/cops handover --from-suffix=54 [--dry-run]
  py/cops handover --from-suffix=54 --batch-size=5 --batch-delay=30
  py/cops handover --from-suffix=54 --message='özel mesaj'
  py/cops handover --from-suffix=54 --message-file=/path/to/msg.txt

Faz 2 için: py/cops rc hc54 hcr54 ... --suffix=55 --new --kill-first --one-by-one
Faz 3 için: claudeops layout grid 4 --claude-only --pin=...
"""
from __future__ import annotations
import os
import sys
from ..handover import handover_faz1, HANDOVER_MSG_DEFAULT
from ..spawn import detect_display


def register(sub):
    p = sub.add_parser("handover", help="Faz 1: wrap-up mesajı gönder (eski kapat, yeni aç)")
    p.add_argument("--from-suffix", type=int, required=True, metavar="N",
                   help="hangi suffix'teki session'lar (ör. 54)")
    p.add_argument("--message", default=None, metavar="MSG",
                   help="wrap-up mesajı (varsayılan: HANDOVER_MSG_DEFAULT)")
    p.add_argument("--message-file", default=None, metavar="FILE",
                   help="mesajı dosyadan oku")
    p.add_argument("--batch-size", type=int, default=5, metavar="N",
                   help="grup büyüklüğü — rate-limit önlemi (varsayılan: 5)")
    p.add_argument("--batch-delay", type=float, default=30.0, metavar="SEC",
                   help="gruplar arası bekleme sn (varsayılan: 30)")
    p.add_argument("--proc-wait", type=float, default=15.0, metavar="SEC",
                   help="proc görünme bekleme sn (varsayılan: 15)")
    p.add_argument("--grace", type=float, default=10.0, metavar="SEC",
                   help="kill grace süresi (varsayılan: 10)")
    p.add_argument("--display", default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="sadece göster, gerçek kill/spawn yapma")
    p.set_defaults(func=run)


def run(args) -> int:
    # Mesajı belirle
    if args.message_file:
        try:
            with open(args.message_file) as f:
                message = f.read()
        except Exception as e:
            print(f"✗ mesaj dosyası okunamadı: {e}", file=sys.stderr)
            return 1
    elif args.message:
        message = args.message
    else:
        message = HANDOVER_MSG_DEFAULT

    display = args.display or detect_display()

    print(f"=== handover faz1: suffix={args.from_suffix}"
          f"{' (dry-run)' if args.dry_run else ''} ===")
    print(f"  batch={args.batch_size}, delay={args.batch_delay:.0f}s, "
          f"display={display}")
    print()

    summary = handover_faz1(
        from_suffix=args.from_suffix,
        message=message,
        display=display,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        batch_delay=args.batch_delay,
        proc_wait=args.proc_wait,
        grace=args.grace,
    )

    print()
    print("═" * 50)
    print(f"  opened={summary.opened}  failed={summary.failed}  skipped={summary.skipped}"
          f"  toplam={len(summary.results)}")

    if summary.failed:
        print("\n  ⚠ Başarısız session'lar:")
        for r in summary.results:
            if r.status.startswith("failed"):
                print(f"    {r.name}: {r.status} {r.detail}")

    if summary.failed == 0 and not args.dry_run:
        print()
        print("  Sonraki adım (Faz 2):")
        print(f"  py/cops rc <isimler>{args.from_suffix} \\")
        print(f"    --suffix=<YENİ> --new --kill-first --one-by-one \\")
        print(f"    --prompt='devam'")

    return 1 if summary.failed else 0
