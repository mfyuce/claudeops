"""claudeops durum deposu (TBD#142 / K1-K10): stdlib `sqlite3`, WAL, ORM YOK.

İki ilkel yeter (dosya-tabanlı state'in tamamı bunlara iner):
  * `docs`  : ad -> JSON belge (hosts.json, quota.json, settings...). Okuma-değiştirme-yazma `update_doc` ile TEK
              `BEGIN IMMEDIATE` işleminde (eski kilitsiz RMW sorunlarının, TBD#64, çaresi).
  * `log`   : akış adı + artan id -> JSON satır (diag.log, steward/log.jsonl benzeri ekleme-günlükleri).
Şema sürümü `PRAGMA user_version`; `MIGRATIONS` listesine YALNIZ sona ekleme yapılır (var olan öğe DEĞİŞTİRİLMEZ).
Bağlantı thread başına; yazı serileştirmesi SQLite'ın kilidiyle (`busy_timeout`), süreçler arası da çalışır
(`cops` servis kapalıyken DB'yi doğrudan açar, K4). Motorlar arası taşınabilirlik için standart SQL; motora özgü
özellik yok (K1: ileride PostgreSQL'e dönüşebilir).
"""
from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

MIGRATIONS: List[str] = [
    # v1
    """
    CREATE TABLE docs (
        name    TEXT PRIMARY KEY,
        body    TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        updated REAL NOT NULL
    );
    CREATE TABLE log (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        stream TEXT NOT NULL,
        ts     REAL NOT NULL,
        body   TEXT NOT NULL
    );
    CREATE INDEX log_stream_id ON log(stream, id);
    """,
]

BUSY_TIMEOUT_MS = 5000


class StoreError(Exception):
    pass


class Store:
    def __init__(self, path: str):
        self.path = path
        self._tl = threading.local()
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        # İlk oluşturmadan itibaren 0600 (sır içerebilir; çok kullanıcılı makine).
        if not os.path.exists(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(fd)
        self._migrate()

    # -- bağlantı ---------------------------------------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tl, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)  # autocommit; işlemi biz açarız
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            c.execute("PRAGMA synchronous=NORMAL")
            self._tl.c = c
        return c

    def close(self) -> None:
        c = getattr(self._tl, "c", None)
        if c is not None:
            c.close()
            self._tl.c = None

    def _tx(self):
        return _Tx(self._conn())

    # -- migrasyon --------------------------------------------------------------------------------------------
    def _migrate(self) -> None:
        c = self._conn()
        with _Tx(c):   # BEGIN IMMEDIATE: iki süreç aynı anda migrate ederse biri bekler, sonra user_version'ı görür
            ver = c.execute("PRAGMA user_version").fetchone()[0]
            if ver > len(MIGRATIONS):
                raise StoreError(f"DB sürümü ({ver}) bu kodun bildiğinden ({len(MIGRATIONS)}) yeni; kod eski")
            for i in range(ver, len(MIGRATIONS)):
                for stmt in _split(MIGRATIONS[i]):
                    c.execute(stmt)
                c.execute(f"PRAGMA user_version={i + 1}")

    def schema_version(self) -> int:
        return self._conn().execute("PRAGMA user_version").fetchone()[0]

    # -- docs -------------------------------------------------------------------------------------------------
    def get_doc(self, name: str, default: Any = None) -> Any:
        row = self._conn().execute("SELECT body FROM docs WHERE name=?", (name,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set_doc(self, name: str, obj: Any) -> int:
        """Belgeyi tümden değiştirir; yeni sürüm numarasını döndürür."""
        body = json.dumps(obj, ensure_ascii=False)
        with self._tx() as c:
            return self._put(c, name, body)

    def update_doc(self, name: str, fn: Callable[[Any], Any], default: Any = None) -> Any:
        """Atomik okuma-değiştirme-yazma: `fn(eski)` yeni değeri döndürür (None dönerse yazılmaz, eski aynen kalır).
        `fn` işlem içinde çalışır: UZUN iş / ağ / başka DB çağrısı yapma. Yeni değeri döndürür."""
        with self._tx() as c:
            row = c.execute("SELECT body FROM docs WHERE name=?", (name,)).fetchone()
            cur = default if row is None else json.loads(row[0])
            new = fn(cur)
            if new is None:
                return cur
            self._put(c, name, json.dumps(new, ensure_ascii=False))
            return new

    def delete_doc(self, name: str) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM docs WHERE name=?", (name,)).rowcount > 0

    def list_docs(self, prefix: str = "") -> List[str]:
        like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return [r[0] for r in self._conn().execute("SELECT name FROM docs WHERE name LIKE ? ESCAPE '\\' ORDER BY name", (like,))]

    def doc_version(self, name: str) -> int:
        row = self._conn().execute("SELECT version FROM docs WHERE name=?", (name,)).fetchone()
        return 0 if row is None else row[0]

    @staticmethod
    def _put(c: sqlite3.Connection, name: str, body: str) -> int:
        c.execute(
            "INSERT INTO docs(name, body, version, updated) VALUES(?,?,1,?) "
            "ON CONFLICT(name) DO UPDATE SET body=excluded.body, version=docs.version+1, updated=excluded.updated",
            (name, body, time.time()))
        return c.execute("SELECT version FROM docs WHERE name=?", (name,)).fetchone()[0]

    # -- log --------------------------------------------------------------------------------------------------
    def append_log(self, stream: str, obj: Any) -> int:
        with self._tx() as c:
            cur = c.execute("INSERT INTO log(stream, ts, body) VALUES(?,?,?)",
                            (stream, time.time(), json.dumps(obj, ensure_ascii=False)))
            return int(cur.lastrowid)

    def read_log(self, stream: str, limit: int = 100, after_id: int = 0) -> List[Tuple[int, float, Any]]:
        """`after_id`'den sonraki satırlar, en eskiden yeniye (id, ts, nesne)."""
        rows = self._conn().execute(
            "SELECT id, ts, body FROM log WHERE stream=? AND id>? ORDER BY id LIMIT ?", (stream, after_id, int(limit))).fetchall()
        return [(i, t, json.loads(b)) for i, t, b in rows]

    def tail_log(self, stream: str, n: int = 100) -> List[Tuple[int, float, Any]]:
        """Son `n` satır, en eskiden yeniye."""
        rows = self._conn().execute(
            "SELECT id, ts, body FROM log WHERE stream=? ORDER BY id DESC LIMIT ?", (stream, int(n))).fetchall()
        return [(i, t, json.loads(b)) for i, t, b in reversed(rows)]

    def trim_log(self, stream: str, keep: int) -> int:
        """Akışta en yeni `keep` satırı bırakır; silinen sayıyı döndürür."""
        with self._tx() as c:
            return c.execute(
                "DELETE FROM log WHERE stream=? AND id <= COALESCE((SELECT id FROM log WHERE stream=? ORDER BY id DESC LIMIT 1 OFFSET ?), 0)",
                (stream, stream, int(keep))).rowcount

    # -- yedek ------------------------------------------------------------------------------------------------
    def backup(self, dest: str) -> None:
        """Tutarlı anlık kopya (`sqlite3` backup API; düz `cp` WAL yüzünden tutarsız olabilir, K7). Hedef 0600."""
        tmp = dest + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        out = sqlite3.connect(tmp)
        try:
            self._conn().backup(out)
        finally:
            out.close()
        os.replace(tmp, dest)

    def export_docs(self) -> Dict[str, Any]:
        """Tüm belgeler {ad: nesne} (K6 `cops db export` çekirdeği)."""
        return {n: self.get_doc(n) for n in self.list_docs()}


class _Tx:
    """`BEGIN IMMEDIATE` ... COMMIT/ROLLBACK (yazar kilidi baştan alınır; okuyan-sonra-yazan yarışı olmaz)."""
    def __init__(self, c: sqlite3.Connection):
        self.c = c

    def __enter__(self) -> sqlite3.Connection:
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, et, ev, tb) -> bool:
        if et is None:
            self.c.execute("COMMIT")
        else:
            self.c.execute("ROLLBACK")
        return False


def _split(script: str) -> Iterator[str]:
    for s in script.split(";"):
        s = s.strip()
        if s:
            yield s


_DEFAULT: Optional[Store] = None
_DEFAULT_LOCK = threading.Lock()


def default_path() -> str:
    from .paths import CLAUDEOPS_DIR
    return os.path.join(CLAUDEOPS_DIR, "claudeops.db")


def default_store() -> Store:
    """Süreç genelinde tek örnek (K3: `~/.claude/claudeops/claudeops.db`, `CLAUDEOPS_DIR` ile yönlendirilebilir)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None or _DEFAULT.path != default_path():
            _DEFAULT = Store(default_path())
        return _DEFAULT
