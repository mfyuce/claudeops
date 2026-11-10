"""`label` — proje etiketleri (labels.py).

  py/cops label                            # tüm atamalar
  py/cops label NAME                       # projenin etiketleri
  py/cops label NAME +stuck -foo           # ekle / çıkar (bilinmeyen ad geçerliyse otomatik tanımlanır)
  py/cops label --find stuck               # bu etiketi taşıyan projeler
  py/cops label defs                       # tanımlar (sistem + kullanıcı)
  py/cops label defs add NAME [#rrggbb] [açıklama...]
  py/cops label defs rm NAME               # tanımı siler ve tüm projelerden çıkarır (sistem etiketi silinemez)
NAME blueprint/proje adı; tarihli oturum adı verilirse blueprint'ine (türev ön ek) çözülür. Yerel depo, servis yeniden başlatmaz.
"""
from __future__ import annotations

import argparse

from .. import labels


def register(sub):
    p = sub.add_parser("label", help="proje etiketleri: label NAME +stuck -x | --find stuck | defs [add|rm]")
    p.add_argument("--find", default="", metavar="LABEL")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.set_defaults(func=run)


def _err(msg: str) -> int:
    print(f"hata: {msg}")
    return 2


def run(args) -> int:
    rest = list(args.args or [])
    if args.find:
        names = labels.find(args.find)
        print("\n".join(names) if names else f"(etiket yok: {args.find})")
        return 0 if names else 1
    if rest and rest[0] == "defs":
        d = rest[1:]
        if not d:
            for n, v in labels.definitions().items():
                print(f"{n:18} {v['color']}  {'sistem' if v['system'] else 'özel  '}  {v['desc']}")
            return 0
        if d[0] == "add" and len(d) >= 2:
            color = d[2] if len(d) > 2 and d[2].startswith("#") else ""
            desc = " ".join(d[3:] if color else d[2:])
            res = labels.define(d[1], color, desc)
        elif d[0] == "rm" and len(d) == 2:
            res = labels.delete_def(d[1])
        else:
            return _err("kullanım: label defs [add NAME [#rrggbb] [açıklama] | rm NAME]")
        print("tamam" if res.get("ok") else f"hata: {res.get('error')}")
        return 0 if res.get("ok") else 1
    if not rest:
        for k, v in sorted(labels.assignments().items()):
            print(f"{k:24} {' '.join(v)}")
        return 0
    key = labels.key_for(rest[0])
    ops = rest[1:]
    if not ops:
        print(" ".join(labels.labels_of(key)) or "(etiket yok)")
        return 0
    add = [o[1:] for o in ops if o.startswith("+")]
    rem = [o[1:] for o in ops if o.startswith("-")]
    if len(add) + len(rem) != len(ops):
        return _err("işlemler +etiket ya da -etiket olmalı")
    res = labels.update(key, add, rem)
    if not res.get("ok"):
        return _err(res.get("error", ""))
    print(f"{key}: {' '.join(res['labels']) or '(etiket yok)'}")
    return 0
