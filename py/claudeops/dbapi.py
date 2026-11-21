"""İnce DB-API katmanı (Postgres hazırlığı, TODO 2026-11-20 madde 2; envanter: docs/postgres-envanter.md). ORM YOK.

Amaç: `store.py` gibi SQL yazan modüller `db_url`e göre SQLite ya da Postgres'e bağlansın; SQL metni tek (`?` yer tutucu) kalır.
  * `db_url`: "" / `sqlite:///yol` / `sqlite:yol` = SQLite (yol verilmezse çağıranın `path`i); `postgres://` / `postgresql://` = Postgres
    (`psycopg2`, tembel içe aktarma; yoksa açık hata).
  * `?` -> `%s` çevirisi (tırnak içi dizelerde dokunmaz; Postgres'te metindeki gerçek `%` -> `%%`).
  * `ddl()`: göç metinlerindeki `{PK_AUTO}` / `{REAL}` belirteçleri motora göre açılır (SQLite çıktısı eski göç metniyle BİREBİR aynı).
  * Göç sürümü: `schema_version` tablosu (tek satır). SQLite'ta eski `PRAGMA user_version` okunup tabloya aktarılır ve geriye dönük
    uyum için `user_version` da güncel tutulur.
  * Yazma işlemi: SQLite `BEGIN IMMEDIATE`, Postgres `BEGIN` + `xact_lock(anahtar)` (`pg_advisory_xact_lock`); `for_update` son eki.
  * `insert()`: SQLite `lastrowid`, Postgres `RETURNING id`.
Postgres yolu bu geliştirme makinesinde bir sunucuya karşı ÇALIŞTIRILMADI (sunucu yok): `CLAUDEOPS_TEST_PG_URL` verilirse test_dbapi
gerçek PG testlerini de koşar, yoksa atlar."""
from __future__ import annotations
import os
import re
import sqlite3
from typing import Any, Callable, Iterator, List, Optional, Sequence

SQLITE, POSTGRES = "sqlite", "postgres"
BUSY_TIMEOUT_MS = 5000
_VERSION_DDL = "CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
_MIGRATE_LOCK_KEY = 726_001      # pg_advisory_xact_lock: eşzamanlı göç sıraya girer


class DbError(Exception):
    pass


def backend_of(url: str) -> str:
    u = (url or "").strip().lower()
    if not u or u.startswith("sqlite:"):
        return SQLITE
    if u.startswith("postgres://") or u.startswith("postgresql://"):
        return POSTGRES
    raise DbError("db_url sqlite: ya da postgresql:// ile başlamalı")


def sqlite_path(url: str, default: str) -> str:
    u = (url or "").strip()
    if u.lower().startswith("sqlite:"):
        rest = re.sub(r"^sqlite:(//)?", "", u, flags=re.I).split("?")[0]
        return rest or default
    return default


def translate(sql: str, backend: str) -> str:
    """`?` yer tutucularını motora çevirir. Tek tırnaklı dizeler (içinde `?`/`%` olabilir) olduğu gibi kalır; Postgres'te DIŞARIDAKİ `%`
    `%%` olur (psycopg2 parametre biçimi), dize içindeki `%` de aynı nedenle `%%` yapılır."""
    if backend == SQLITE:
        return sql
    out: List[str] = []
    in_str = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if in_str and sql[i + 1:i + 2] == "'":      # '' kaçışı
                out.append("''")
                i += 2
                continue
            in_str = not in_str
            out.append(ch)
        elif ch == "%":
            out.append("%%")
        elif ch == "?" and not in_str:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def ddl(text: str, backend: str) -> str:
    """Göç metni belirteçleri: `{PK_AUTO}` (artan birincil anahtar), `{REAL}` (çift duyarlıklı gerçek: PG `REAL` 4 bayttır, epoch bozulur)."""
    if backend == POSTGRES:
        return text.replace("{PK_AUTO}", "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY").replace("{REAL}", "DOUBLE PRECISION")
    return text.replace("{PK_AUTO}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{REAL}", "REAL")


def split_statements(script: str, backend: str) -> Iterator[str]:
    """Göç betiğini deyimlere böler. SQLite: `sqlite3.complete_statement` (tetikleyici gövdesindeki `;` bölünmez). Postgres: tek tırnak
    dışındaki `;` (tetikleyici/işlev gövdesi `$$` içinde ise bölünmez)."""
    if backend == SQLITE:
        acc = ""
        for part in script.split(";"):
            acc += part
            if sqlite3.complete_statement(acc + ";"):
                if acc.strip():
                    yield acc.strip()
                acc = ""
            else:
                acc += ";"
        if acc.strip().rstrip(";").strip():
            yield acc.strip().rstrip(";")
        return
    acc, in_str, in_dollar, i = [], False, False, 0
    while i < len(script):
        two = script[i:i + 2]
        if not in_str and two == "$$":
            in_dollar = not in_dollar
            acc.append(two)
            i += 2
            continue
        ch = script[i]
        if ch == "'" and not in_dollar:
            in_str = not in_str
        if ch == ";" and not in_str and not in_dollar:
            stmt = "".join(acc).strip()
            if stmt:
                yield stmt
            acc = []
        else:
            acc.append(ch)
        i += 1
    stmt = "".join(acc).strip()
    if stmt:
        yield stmt


class Conn:
    """Tek bağlantı (çağıran iş parçacığına başına bir tane tutar). `execute` yerel imleci döndürür (fetchone/fetchall/rowcount/yineleme)."""

    def __init__(self, raw: Any, backend: str):
        self.raw = raw
        self.backend = backend
        self.pg = backend == POSTGRES
        self.for_update = " FOR UPDATE" if self.pg else ""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        q = translate(sql, self.backend)
        if self.pg:
            cur = self.raw.cursor()
            cur.execute(q, tuple(params))
            return cur
        return self.raw.execute(q, tuple(params))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> Any:
        q = translate(sql, self.backend)
        cur = self.raw.cursor()
        cur.executemany(q, [tuple(r) for r in rows])
        return cur

    def insert(self, sql: str, params: Sequence[Any] = (), id_col: str = "id") -> int:
        """INSERT sonrası yeni satır kimliği (SQLite `lastrowid`, Postgres `RETURNING`)."""
        if self.pg:
            cur = self.execute(sql + f" RETURNING {id_col}", params)
            return int(cur.fetchone()[0])
        return int(self.execute(sql, params).lastrowid)

    def begin_write(self) -> None:
        self.execute("BEGIN" if self.pg else "BEGIN IMMEDIATE")

    def commit(self) -> None:
        self.execute("COMMIT")

    def rollback(self) -> None:
        self.execute("ROLLBACK")

    def xact_lock(self, key: Any) -> None:
        """İşlem boyu anahtar kilidi (Postgres'te okuyan-sonra-yazan yarışı için; SQLite'ta yazar kilidi zaten tüm DB'yi tutar)."""
        if self.pg:
            self.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (str(key),))

    def close(self) -> None:
        self.raw.close()


def connect(url: str = "", path: str = "") -> Conn:
    be = backend_of(url)
    if be == SQLITE:
        raw = sqlite3.connect(sqlite_path(url, path), timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)   # autocommit; işlemi biz açarız
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        raw.execute("PRAGMA synchronous=NORMAL")
        return Conn(raw, be)
    try:
        import psycopg2          # type: ignore
    except ImportError as e:
        raise DbError("db_url postgresql:// ama psycopg2 kurulu değil") from e
    raw = psycopg2.connect(url)
    raw.autocommit = True
    return Conn(raw, be)


class Tx:
    """Yazma işlemi: `with Tx(conn) as c:` COMMIT, istisnada ROLLBACK."""

    def __init__(self, c: Conn):
        self.c = c

    def __enter__(self) -> Conn:
        self.c.begin_write()
        return self.c

    def __exit__(self, et, ev, tb) -> bool:
        if et is None:
            self.c.commit()
        else:
            self.c.rollback()
        return False


def schema_version(c: Conn) -> int:
    """Güncel göç sürümü; tablo yoksa 0 (SQLite'ta eski `user_version` varsa ondan)."""
    if c.pg:
        ok = c.execute("SELECT 1 FROM information_schema.tables WHERE table_name='schema_version' AND table_schema=current_schema()").fetchone()
    else:
        ok = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    tab = 0
    if ok:
        row = c.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
        tab = int(row[0]) if row else 0
    if not c.pg:      # SQLite: eski `user_version` de geçerli (daha yeni bir kod/araç onu ilerlettiyse "kod eski" korunur)
        return max(tab, int(c.execute("PRAGMA user_version").fetchone()[0]))
    return tab


def migrate(c: Conn, migrations: Sequence[str], on_newer: Optional[Callable[[int, int], None]] = None) -> int:
    """`migrations[i]` = sürüm i+1 betiği (YALNIZ sona ekleme). Tek işlemde, eşzamanlı çağrılar sıraya girer. Yeni sürüm numarasını döndürür."""
    with Tx(c):
        if c.pg:
            c.execute("SELECT pg_advisory_xact_lock(?)", (_MIGRATE_LOCK_KEY,))
        c.execute(_VERSION_DDL)
        ver = schema_version(c)
        if ver > len(migrations):
            if on_newer is not None:
                on_newer(ver, len(migrations))
            raise DbError(f"DB sürümü ({ver}) bu kodun bildiğinden ({len(migrations)}) yeni; kod eski")
        for i in range(ver, len(migrations)):
            for stmt in split_statements(ddl(migrations[i], c.backend), c.backend):
                c.execute(stmt)
            if not c.pg:
                c.execute(f"PRAGMA user_version={i + 1}")
            c.execute("INSERT INTO schema_version(id, version) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET version=excluded.version", (i + 1,))
        if ver == len(migrations):      # güncel DB (eski user_version'dan gelen ilk açılış dahil): tablo satırı mutlaka var
            c.execute("INSERT INTO schema_version(id, version) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET version=excluded.version", (ver,))
        return len(migrations)


def default_url() -> str:
    """Süreç geneli `db_url`: ortam `CLAUDEOPS_DB_URL` (boş = SQLite, bugünkü davranış)."""
    return os.environ.get("CLAUDEOPS_DB_URL", "").strip()
