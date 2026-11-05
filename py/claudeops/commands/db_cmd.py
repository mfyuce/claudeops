"""`db` — SQLite durum deposu (TBD#142): durum, dışa/içe aktarma (K6).

  py/cops db status                      # yol, şema, belge/tsv/akış sayıları
  py/cops db export [--out DOSYA]        # belgeler+tsv+günlük JSON (varsayılan backups/db-export-<tarih>.json, 0600); yalnız okur
  py/cops db import DOSYA [--apply]      # varsayılan KURU çalışma; --apply önce `.db` yedeği alır, sonra yazar
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
    sp.add_parser("status")
    e = sp.add_parser("export")
    e.add_argument("--out", default="")
    i = sp.add_parser("import")
    i.add_argument("file")
    i.add_argument("--apply", action="store_true")
    p.set_defaults(func=run)


def _store_obj():
    return _store.default_store()


def run(args) -> int:
    cmd = getattr(args, "dcmd", None) or "status"
    st = _store_obj()
    if cmd == "status":
        print(f"db: {st.path}  şema v{st.schema_version()}")
        docs = st.list_docs()
        print(f"belge: {len(docs)}  tsv dosyası: {st.tsv_files()}  günlük akışı: {len(st.list_streams())}")
        return 0
    if cmd == "export":
        out = args.out or os.path.join(CLAUDEOPS_DIR, "backups", "db-export-" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        data = st.export_all()
        fd = os.open(out + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(out + ".tmp", out)
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
