"""`db` — SQLite durum deposu (TBD#142): durum, dışa/içe aktarma (K6).

  py/cops db status                      # yol, şema, belge/tsv/akış sayıları
  py/cops db export [--out DOSYA]        # belgeler+tsv+günlük JSON (varsayılan backups/db-export-<tarih>.json, 0600); yalnız okur
  py/cops db import DOSYA [--apply]      # varsayılan KURU çalışma; --apply önce `.db` yedeği alır, sonra yazar
  py/cops db status --drift              # her DB belgesini dosyasıyla JSON-eşitlik karşılaştırır (fark varsa çıkış 1)
  py/cops db materialize [AD...] [--apply]   # DB belgesini kendi dosyasına (AD.json) yazar; varsayılan KURU, --apply atomik 0600
İçe aktarma belge ve tsv'yi DEĞİŞTİRİR, günlük akışını yalnız akış boşsa ekler. Servis çalışırken yazma: dual modda dosya doğruluk
kaynağıdır, DB gölgedir; içe aktarma sonrası `cops db status` ve diag.log "statedocs drift" sayacına bak.
"""
from __future__ import annotations

import datetime
import json
import os

from .. import store as _store
from ..paths import CLAUDEOPS_DIR


def register(sub):
    p = sub.add_parser("db", help="SQLite durum deposu: status / export / import")
    sp = p.add_subparsers(dest="dcmd")
    s = sp.add_parser("status")
    s.add_argument("--drift", action="store_true")
    m = sp.add_parser("materialize")
    m.add_argument("names", nargs="*")
    m.add_argument("--apply", action="store_true")
    e = sp.add_parser("export")
    e.add_argument("--out", default="")
    i = sp.add_parser("import")
    i.add_argument("file")
    i.add_argument("--apply", action="store_true")
    p.set_defaults(func=run)


def doc_path(name: str, base: str = "") -> str:
    """Belge adı -> `base/AD.json`; `base` dışına çıkan ad (`..`, mutlak yol) ValueError."""
    base = os.path.realpath(base or CLAUDEOPS_DIR)
    if not name or name.startswith("/") or ".." in name.split("/"):
        raise ValueError(f"geçersiz belge adı: {name!r}")
    path = os.path.realpath(os.path.join(base, name + ".json"))
    if not path.startswith(base + os.sep):
        raise ValueError(f"belge adı CLAUDEOPS_DIR dışına çıkıyor: {name!r}")
    return path


def drift(st, names=None, base: str = ""):
    """[(ad, durum)]: eşit | fark | dosya_yok | okunamadi. SAF karşılaştırma (yalnız okur)."""
    out = []
    for name in (names if names else st.list_docs()):
        try:
            path = doc_path(name, base)
        except ValueError:
            out.append((name, "okunamadi"))
            continue
        if not os.path.exists(path):
            out.append((name, "dosya_yok"))
            continue
        try:
            with open(path, encoding="utf-8") as f:
                fv = json.load(f)
        except (OSError, ValueError):
            out.append((name, "okunamadi"))
            continue
        out.append((name, "eşit" if fv == st.get_doc(name) else "fark"))
    return out


def materialize(st, names, apply: bool, base: str = ""):
    """DB belgelerini dosyalarına yazar (kuru çalışma varsayılan). [(ad, yol, eylem)]; eylem: yazılacak|yazıldı|eşit|yok."""
    from ..atomic_json import atomic_write_json
    res = []
    for name in (names if names else st.list_docs()):
        path = doc_path(name, base)
        if name not in st.list_docs(name):
            res.append((name, path, "yok"))
            continue
        obj = st.get_doc(name)
        try:
            with open(path, encoding="utf-8") as f:
                same = json.load(f) == obj
        except (OSError, ValueError):
            same = False
        if same:
            res.append((name, path, "eşit"))
        elif apply:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic_write_json(path, obj, mode=0o600)
            res.append((name, path, "yazıldı"))
        else:
            res.append((name, path, "yazılacak"))
    return res


def _store_obj():
    return _store.default_store()


def run(args) -> int:
    cmd = getattr(args, "dcmd", None) or "status"
    st = _store_obj()
    if cmd == "status":
        print(f"db: {st.path}  şema v{st.schema_version()}")
        docs = st.list_docs()
        print(f"belge: {len(docs)}  tsv dosyası: {st.tsv_files()}  günlük akışı: {len(st.list_streams())}")
        if getattr(args, "drift", False):
            rows = drift(st)
            bad = [(n, s) for n, s in rows if s != "eşit"]
            for n, s in bad:
                print(f"  {s}: {n}")
            print(f"drift: {len(rows) - len(bad)} eşit, {len(bad)} farklı/eksik")
            return 1 if bad else 0
        return 0
    if cmd == "materialize":
        try:
            res = materialize(st, list(args.names), bool(args.apply))
        except ValueError as e:
            print(f"hata: {e}")
            return 1
        for n, path, act in res:
            if act != "eşit":
                print(f"  {act}: {n} -> {path}")
        todo = sum(1 for _, _, a in res if a == "yazılacak")
        print(f"{'YAZILDI' if args.apply else 'KURU'}: {sum(1 for _, _, a in res if a == 'yazıldı')} yazıldı, {todo} yazılacak, "
              f"{sum(1 for _, _, a in res if a == 'eşit')} eşit" + ("" if args.apply or not todo else "; --apply ile yaz"))
        return 0
    if cmd == "export":
        out = args.out or os.path.join(CLAUDEOPS_DIR, "backups", "db-export-" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        data = st.export_all()
        from ..atomic_json import atomic_write_json   # pid+thread'e özel tmp, O_NOFOLLOW, fsync, hata olursa temizlik (review R-3)
        atomic_write_json(out, data, mode=0o600)
        print(f"yazıldı: {out}  belge={len(data['docs'])} tsv={len(data['tsv'])} akış={len(data['logs'])}")
        return 0
    if cmd == "import":
        try:
            with open(args.file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"hata: {e}")
            return 1
        if not args.apply:
            print(f"KURU: belge={len(data.get('docs') or {})} tsv={len(data.get('tsv') or {})} akış={len(data.get('logs') or {})} içe alınacak; --apply ile yaz")
            return 0
        bak = os.path.join(CLAUDEOPS_DIR, "backups", "claudeops.db.before-import-" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        st.backup(bak)
        try:
            n = st.import_all(data)
        except _store.StoreError as e:
            print(f"hata: {e}")
            return 1
        print(f"içe alındı {n}; önceki db yedeği: {bak}")
        return 0
    return 1
