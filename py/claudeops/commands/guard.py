"""`guard` — eksik session'ları tespit et ve aç (crash-recovery)."""
from __future__ import annotations
import os
from ..guard import guard_once, guard_lock
from ..spawn import detect_display


def register(sub):
    p = sub.add_parser("guard", help="eksik session'ları tespit et ve aç (crash-recovery)")
    p.add_argument("--dry-run", action="store_true",
                   help="sadece göster, spawn etme")
    p.add_argument("--display", default=None, metavar="DISPLAY",
                   help="X display (varsayılan: otomatik tespit)")
    p.add_argument("--no-lock", action="store_true",
                   help="guard.lock atlat (test için)")
    p.add_argument("--delay", type=float, default=1.0, metavar="SEC",
                   help="spawn'lar arası bekleme (varsayılan: 1s)")
    p.set_defaults(func=run)


def run(args) -> int:
    display = args.display or detect_display()

    def _run():
        result = guard_once(display=display, dry_run=args.dry_run, spawn_delay=args.delay)

        if result.error:
            print(f"✗ {result.error}")
            return 1

        if result.dups:
            print(f"⚠ DUP: {', '.join(result.dups)}")

        if result.closed:
            print(f"⊘ kapalı (guard açmaz): {', '.join(result.closed)}")

        if not result.missing:
            print("✓ tüm session'lar çalışıyor")
            return 0

        for name, kind in result.spawned:
            print(f"  {name} → {kind}")

        # Spawn hatası `error:...` olarak listelenir; eskiden yine "N session spawn edildi" + çıkış 0 dönüyordu
        # (cron/izleyici başarısızlığı göremiyordu; review 2026-11-04 E7/4A R-01).
        failed = [n for n, kind in result.spawned if str(kind).startswith("error:")]
        ok = len(result.spawned) - len(failed)
        verb = "gösterildi (dry-run)" if args.dry_run else "spawn edildi"
        print(f"\n  {ok} session {verb}" + (f", {len(failed)} HATA: {', '.join(failed)}" if failed else ""))
        return 1 if failed else 0

    if args.no_lock:
        return _run()

    try:
        with guard_lock():
            return _run()
    except TimeoutError as e:
        print(f"✗ {e}")
        return 1
