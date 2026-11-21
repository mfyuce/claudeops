"""SQLite -> Postgres veri taşıma çekirdeği (`cops db migrate-to-pg`, TODO Postgres hazırlığı madde 4). ORM yok, `dbapi` üstünde.

`migrate_tables(src, dst, spec, apply)`: `spec = [{"table", "order", "identity": kimlik sütunu | None}]`. Varsayılan KURU: yalnız kaynak sayımı +
özet (sha256) + hedefte aynı tablolar boş mu denetimi. `apply`: hedefte tablo BOŞ olmalı (dolu = reddedilir, üzerine yazılmaz), satırlar tek
işlemde kopyalanır, kimlik sütunu varsa `OVERRIDING SYSTEM VALUE` ile yazılır ve dizi MAX+1'e ayarlanır, sonra her tablo için sayım + özet
karşılaştırılır; fark varsa işlem GERİ ALINIR (hiçbir şey yazılmaz). Kaynak yalnız okunur (SQLite dosyası değişmez). KURU koşu da hedefte (boş) şemayı kurar (DDL, veri yok). Geri dönüş planı: kaynak
SQLite dosyası olduğu gibi durur; `db_url`i kaldırmak yeterli."""
from __future__ import annotations
import hashlib
from typing import Any, Dict, List, Sequence

from . import dbapi

CHUNK = 500


class MigrateError(Exception):
    pass


def columns(c: "dbapi.Conn", table: str) -> List[str]:
    cur = c.execute(f"SELECT * FROM {table} LIMIT 0")
    return [d[0] for d in cur.description]


def table_digest(c: "dbapi.Conn", table: str, order: str, cols: Sequence[str]) -> Dict[str, Any]:
    """(satır sayısı, sha256): satırlar `order` sırasında, değerler `repr` ile (float/int/str/None; SQLite REAL ile PG DOUBLE PRECISION aynı repr)."""
    h = hashlib.sha256()
    n = 0
    cur = c.execute(f"SELECT {','.join(cols)} FROM {table} ORDER BY {order}")
    while True:
        rows = cur.fetchmany(CHUNK)
        if not rows:
            break
        for r in rows:
            h.update(repr(tuple(r)).encode("utf-8"))
            h.update(b"\n")
            n += 1
    return {"count": n, "sha256": h.hexdigest()}


def _count(c: "dbapi.Conn", table: str) -> int:
    return int(c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def migrate_tables(src: "dbapi.Conn", dst: "dbapi.Conn", spec: Sequence[Dict[str, Any]], apply: bool = False) -> Dict[str, Any]:
    if src.pg or not dst.pg:
        raise MigrateError("kaynak SQLite, hedef Postgres olmalı")
    report: Dict[str, Any] = {"apply": apply, "tables": {}, "ok": True, "error": ""}
    for t in spec:
        name = t["table"]
        cols = columns(src, name)
        dst_cols = columns(dst, name)
        if cols != dst_cols:
            raise MigrateError(f"{name}: sütunlar farklı (kaynak {cols}, hedef {dst_cols}); önce aynı şema sürümüne göç et")
        report["tables"][name] = {"source": table_digest(src, name, t["order"], cols), "target_rows_before": _count(dst, name)}
    pre_clear = {t["table"] for t in spec if t.get("pre_clear")}      # göçle kendiliğinden dolan tablo (ör. notes meta.db_id): boşaltılıp kaynaktan yazılır
    busy = [n for n, v in report["tables"].items() if v["target_rows_before"] and n not in pre_clear]
    if busy:
        report["ok"] = False
        report["error"] = "hedefte dolu tablo var (üzerine yazılmaz): " + ", ".join(busy)
        return report
    if not apply:
        return report
    with dbapi.Tx(dst):
        for t in spec:
            name = t["table"]
            cols = columns(src, name)
            if t.get("pre_clear"):
                dst.execute(f"DELETE FROM {name}")
            for trig in t.get("disable_triggers", ()):
                dst.execute(f"ALTER TABLE {name} DISABLE TRIGGER {trig}")
            ph = ",".join("?" for _ in cols)
            ovr = " OVERRIDING SYSTEM VALUE" if t.get("identity") else ""
            sql = f"INSERT INTO {name}({','.join(cols)}){ovr} VALUES({ph})"
            cur = src.execute(f"SELECT {','.join(cols)} FROM {name} ORDER BY {t['order']}")
            while True:
                rows = cur.fetchmany(CHUNK)
                if not rows:
                    break
                dst.executemany(sql, [tuple(r) for r in rows])
            for trig in t.get("disable_triggers", ()):
                dst.execute(f"ALTER TABLE {name} ENABLE TRIGGER {trig}")
            if t.get("identity"):
                col = t["identity"]
                dst.execute(f"SELECT setval(pg_get_serial_sequence('{name}', '{col}'), COALESCE((SELECT MAX({col}) FROM {name}), 0) + 1, false)")
            for seq in t.get("sequences", ()):         # ör. notes items_rev_seq: MAX(rev)+1
                dst.execute(f"SELECT setval('{seq[0]}', COALESCE((SELECT MAX({seq[1]}) FROM {name}), 0) + 1, false)")
            got = table_digest(dst, name, t["order"], cols)
            want = report["tables"][name]["source"]
            report["tables"][name]["target"] = got
            if got != want:
                raise MigrateError(f"{name}: doğrulama farkı (kaynak {want}, hedef {got}); işlem geri alındı")
    report["verified"] = True
    return report


STORE_SPEC: List[Dict[str, Any]] = [
    {"table": "docs", "order": "name"},
    {"table": "log", "order": "id", "identity": "id"},
    {"table": "tsv_rows", "order": "file, seq"},
]


def migrate_store(sqlite_path: str, url: str, apply: bool = False) -> Dict[str, Any]:
    """`claudeops.db` (docs/log/tsv_rows) -> PG. Hedef şema `Store` göçüyle kurulur (yalnız --apply'da; kuru koşuda hedef DB'de tablo yoksa
    yalnız kaynak özeti verilir)."""
    from . import store as _store
    if dbapi.backend_of(url) != dbapi.POSTGRES:
        raise MigrateError("--url postgresql:// olmalı")
    src_store = _store.Store(sqlite_path, "")
    src = dbapi.connect("", sqlite_path)
    try:
        dst_store = _store.Store("", url)        # şemayı kurar/göç eder (idempotent); kuru koşuda da güvenli (yalnız DDL)
        dst = dst_store._conn()
        return migrate_tables(src, dst, STORE_SPEC, apply)
    finally:
        src.close()
        src_store.close()
