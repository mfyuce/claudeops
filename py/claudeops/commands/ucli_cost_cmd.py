"""`cops ucli-cost`: ucli harcama özeti + HIZ (USD/saat, son 15 dk ve 1 sa). Salt okunur; fiyat mantığı ucli_cost'ta."""
from __future__ import annotations

import json

from .. import ucli_cost


def register(sub):
    p = sub.add_parser("ucli-cost", help="ucli harcaması ve hızı (USD/saat)")
    p.add_argument("--json", action="store_true", help="makine okunur çıktı")
    p.add_argument("--window", type=float, default=60.0, metavar="DK", help="hız penceresi dakika (varsayılan 60)")
    p.add_argument("--by-session", action="store_true", help="oturum başına tablo (bugün USD, USD/saat)")
    p.set_defaults(func=run)


def run(args) -> int:
    try:
        rates = ucli_cost.rate_by_session(window_min=args.window)
    except Exception as e:      # noqa: BLE001 - CLI bozuk veriyle çökmesin
        print(f"  hata: {e}")
        return 1
    total = sum(rates.values())
    try:
        today = ucli_cost.per_session_usd()
    except Exception:           # noqa: BLE001
        today = {}
    names = sorted(set(rates) | set(today), key=lambda n: (-rates.get(n, 0.0), -today.get(n, 0.0), n))
    if args.json:
        print(json.dumps({"window_min": args.window, "rate_usd_per_hour": round(total, 4),
                          "today_usd": round(sum(today.values()), 4),
                          "by_session": {k: round(v, 4) for k, v in rates.items()},
                          "today_by_session": {k: round(v, 4) for k, v in today.items()}}, ensure_ascii=False))
        return 0
    print(f"  bugün toplam: ${sum(today.values()):.2f}")
    print(f"  hız (son {args.window:g} dk): ${total:.2f}/saat")
    if args.by_session:
        print(f"    {'oturum':<24} {'bugün USD':>10} {'USD/sa':>9}")
        for n in names:
            print(f"    {n:<24} {today.get(n, 0.0):>10.2f} {rates.get(n, 0.0):>9.2f}")
    return 0
