"""`py/cops searxng <status|provision|stop|rm>` — ucli `web_search` için otomatik yerel SearXNG kapsayıcısı.

Mantık `searxng.py`de. Bu komut iki iş içindir: (1) ayrık kurulum sürecinin giriş noktası (`provision`; spawn yolu
imaj çekmez, `ensure_search_url` bunu arka planda `python -m claudeops searxng provision` olarak başlatır) ve
(2) elle denetim/temizlik (`status`, `stop`, `rm`; yalnız claudeops'un etiketli, TAM adlı kapsayıcısına dokunur).
Çıktı JSON; başarısızlıkta çıkış kodu 1.
"""
from __future__ import annotations

import json

from .. import searxng

ACTIONS = ("status", "provision", "stop", "rm")


def register(sub) -> None:
    p = sub.add_parser("searxng", help="ucli web_search için otomatik yerel SearXNG (docker): "
                                       "searxng <status|provision|stop|rm>")
    p.add_argument("action", choices=ACTIONS,
                   help="status (durum) | provision (imaj+kapsayıcı kur, idempotent) | stop | rm (kapsayıcıyı sil)")
    p.set_defaults(func=run)


def run(args) -> int:
    if args.action == "status":
        out = searxng.status()
    elif args.action == "provision":
        out = searxng.provision()
    elif args.action == "stop":
        out = searxng.stop()
    else:
        out = searxng.remove()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1
