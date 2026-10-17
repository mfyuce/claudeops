"""`cache` — claude istem önbelleğinin soğuk uyanış israfını transkriptlerden ölç (yalnız okur).

Kullanım:
  py/cops cache                  # son 7 gün, ilk 10 oturum
  py/cops cache --days 30 --top 20
  py/cops cache --project claudeops   # yalnız dizin adında "claudeops" geçen projeler

Hiçbir oturuma dokunmaz, hiçbir şey göndermez, fiyat varsaymaz (bkz. `cache_report.py`).
"""
from __future__ import annotations
from ..cache_report import analyze, render, scan
from ..providers.claude_provider import PROMPT_CACHE_TTL_SECONDS


def register(sub):
    p = sub.add_parser("cache", help="istem önbelleği soğuk uyanışlarını transkriptlerden say (yalnız okur)")
    p.add_argument("--days", type=float, default=7.0, metavar="N", help="son N günde değişen transkriptler (varsayılan 7)")
    p.add_argument("--top", type=int, default=10, metavar="K", help="soğukta en çok yazan ilk K oturum (varsayılan 10)")
    p.add_argument("--ttl", type=int, default=PROMPT_CACHE_TTL_SECONDS, metavar="SEC",
                   help=f"önbellek ömrü sn (varsayılan {PROMPT_CACHE_TTL_SECONDS}; boşluk kovası etiketleri 3600'e göredir)")
    p.add_argument("--project", default="", metavar="TEXT", help="yalnız adında TEXT geçen proje dizinleri")
    p.set_defaults(func=run)


def run(args) -> int:
    rep = analyze(scan(days=args.days, project=args.project), ttl=args.ttl)
    print(render(rep, days=args.days, top=args.top))
    return 0
