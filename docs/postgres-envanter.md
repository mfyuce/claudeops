# Postgres hazırlığı: SQLite'a özgü kullanım envanteri (21 Kas 2026)

Kapsam: çekirdek (`py/claudeops`), enterprise (`claudeops-enterprise`), Rust `dalgic`. Yöntem: `sqlite3` kullanan dosyaların tamamı
tarandı (grep + okuma). Sahip kararı: çok kullanıcı prod'da veritabanı Postgres, bugün SQLite. Sonraki adım: ince DB-API katmanı (TODO maddesi 2).

## 1. Kullanan modüller (üç SQLite kullanıcısı, başka yok)

| Modül | Dosya | DB |
|---|---|---|
| Çekirdek durum deposu | `py/claudeops/store.py` (`docs`, `log`, `tsv_rows`) | `claudeops.db` |
| Notlar (enterprise) | `claudeops_enterprise/notes/{store,service,ops,federation,fedview}.py` | `notes.db` |
| Dalgıç (Rust, sqlx) | `crates/dalgic/src/{lib,store}.rs` | `dalgic.db` |

`statedocs.py`, `db_cmd.py`, `chat_dump.py`, sağlayıcı dosyaları `sqlite3` içe aktarmaz ya da yalnız `store.py` arayüzünü/dosya adını kullanır
(`chat_dump.py`'daki tek eşleşme Python `strftime`, SQL değil). Auth/kota/fwd depoları dosya (JSON/JSONL) tabanlıdır, DB'ye taşınırken
ayrıca envantere girer.

## 2. SQLite'a özgü kullanımlar ve Postgres karşılığı

| # | Kullanım | Nerede | Postgres karşılığı / not |
|---|---|---|---|
| 1 | `PRAGMA user_version` göç sürümü | `store.py:7,100,106,109`, `notes/store.py:62-72` | `schema_version(version int)` tablosu (TODO 2: göç tablosu); `PRAGMA user_version=` yazımı kalkar |
| 2 | `PRAGMA journal_mode=WAL`, `busy_timeout`, `synchronous` | `store.py:81-83`, `notes/store.py:59-61`, `dalgic store.rs:126` | PG'de karşılığı yok (MVCC); `busy_timeout` yerine `lock_timeout`/`statement_timeout`; yalnız SQLite bağlantısında uygulanır |
| 3 | `BEGIN IMMEDIATE` (yazar kilidi baştan) | `store.py:300` (`_Tx`), `notes/store.py:65` | PG: `BEGIN` + gerekirse `SELECT ... FOR UPDATE` ya da `pg_advisory_xact_lock`; göç yarışı için advisory lock |
| 4 | `isolation_level=None` (autocommit, elle işlem) | `store.py:80`, `notes/store.py:57` | psycopg `autocommit=True` + elle `BEGIN`; aynı kalıp taşınır |
| 5 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `store.py:30` (`log.id`), `notes/store.py:16` (`audit.id`) | `BIGINT GENERATED ALWAYS AS IDENTITY` |
| 6 | `cursor.lastrowid` | `store.py:159` | `INSERT ... RETURNING id` |
| 7 | `INSERT OR IGNORE` | `notes/service.py:464,598`, `federation.py:45` | `INSERT ... ON CONFLICT DO NOTHING` |
| 8 | `ON CONFLICT(...) DO UPDATE SET x=excluded.x` | `store.py:150`, `service.py:202,206,363,482,600`, `ops.py:79`, `store.rs:203,294` | AYNI sözdizimi PG'de çalışır (`excluded` aynı); taşınabilir |
| 9 | `?` yer tutucu | `store.py` (20), `notes/*` (~25) | psycopg `%s` ya da katmanda çeviri (TODO 2); Rust tarafı zaten `$1..$n` (sqlx) |
| 10 | `rowcount` ile başarı/yarış denetimi | `store.py:136,178`, `service.py:104,215`, `ops.py:89` | psycopg `cursor.rowcount` aynı anlamda (UPDATE/DELETE) |
| 11 | `lower(hex(randomblob(16)))` DB kimliği | `notes/store.py` v3 | PG: `md5(random()::text || clock_timestamp()::text)` ya da `gen_random_uuid()` (pgcrypto/PG13+) |
| 12 | Tetikleyici ile `items.rev` tekdüze sayaç (`CREATE TRIGGER ... BEGIN UPDATE ... END`, `WHEN NEW.rev = OLD.rev`) | `notes/store.py` v3 | PG tetikleyici = ayrı `FUNCTION ... RETURNS trigger` + `CREATE TRIGGER ... EXECUTE FUNCTION`; ya da tetikleyicisiz `SEQUENCE`/`nextval`. EN ZOR parça: göç deyimleri `;` ile bölünüyor |
| 13 | `ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT 0` + `UPDATE ... ROW_NUMBER() OVER` | `notes/store.py` v3 | PG'de geçerli; alt sorgu takma adı (`SELECT rn FROM (...) WHERE i=items.id`) PG'de `UPDATE ... FROM` biçimine çevrilmeli |
| 14 | `REAL` zaman damgası (epoch saniye) | her yerde (`ts`, `created`, `updated`) | `DOUBLE PRECISION` (aynen) ya da `timestamptz`; öneri: `DOUBLE PRECISION` koru, davranış değişmez |
| 15 | Tip esnekliği (sütun tipi bağlayıcı değil: `INTEGER` sütuna metin yazılabilir) | tüm şemalar | PG kesin tipli: yazım hataları artık hata verir; göç sırasında veri doğrulama şart |
| 16 | `DROP TABLE IF EXISTS` | `notes/store.py` v4 | PG'de geçerli |
| 17 | `LIKE ? ESCAPE '\\'` | `store.py:140` | PG'de geçerli; PG'de `LIKE` büyük/küçük harfe DUYARLI, SQLite'ta ASCII'de duyarsız: davranış farkı, gerekirse `ILIKE` |
| 18 | `COUNT(*) c ... GROUP BY` takma adlar | `service.py:616`, `fedview.py:88` | PG'de geçerli (takma ad `AS` ile yazmak güvenli) |
| 19 | Boolean yerine `INTEGER 0/1` | `owner_wait`, `gone`, `migrated`, `conflict` | PG `INTEGER` olarak aynen kalabilir (öneri: dokunma) |
| 20 | Dosya tabanlı kilit/yedek varsayımı (tek dosya, `cp` ile yedek, `-wal/-shm`) | `cops db`, `backups/*.db`, `disk_clean`, `memory_backup` | PG'de `pg_dump`; yedek/geri yükleme yolları db_url ayrımı gerektirir |
| 21 | Çok süreçli erişim: iki süreç aynı dosyada, `busy_timeout` ile bekleme | `store.py` başlığı (TBD#64) | PG bağlantı havuzu; süreçler arası kilit gerekmez |
| 22 | `check_same_thread=False` + elle `NotesService` kilidi | `notes/store.py:57` | psycopg bağlantısı iş parçacığı başına ya da havuz |

## 3. Rust `dalgic`

Hazır: `db_url` boşsa SQLite, `postgres://`/`postgresql://` ise PG (`store.rs:102-111`, sqlx `Any` havuzu, `migrate()` her iki yolda), yer
tutucular `$n`, upsert `ON CONFLICT`, Cargo'da `postgres` özelliği açık. Açık: PG yolu bir PG sunucusuna karşı HİÇ çalıştırılmadı (bu makinede PG
yok), yani `migrate()` ile göç dosyalarının PG'de geçtiği kanıtsız; SQLite-özgü sözdizimi kalıp kalmadığı ancak gerçek PG'ye karşı test
(TODO 3) ile görülür. `PRAGMA journal_mode=WAL` yalnız `open_sqlite` içinde (doğru).

## 4. Sonuç ve sıra

- Taşınabilir (değişiklik yok ya da küçük): 8, 10, 14, 16, 18, 19.
- Mekanik çeviri (katmanda): 1, 2, 3, 4, 5, 6, 7, 9, 21, 22.
- Davranış kararı gerektiren: 12 (tetikleyici sayaç), 15 (tip sıkılığı), 17 (LIKE duyarlılığı), 20 (yedek).
- Bağımlılık: PG sunucusu bu makinede kurulu değil; kurulum (apt/sudo) sahibe ait. İki arka uçlu test (TODO 3) için kapsayıcı ya da kullanıcı alanında
  derlenmiş PG gerekir; yoksa PG testleri atlanır (TODO'daki şart).
- Önerilen ilk adım: `py/claudeops/dbapi.py` (bağlantı fabrikası, `?`→`%s` çevirisi, `RETURNING`, `schema_version` göçü, `db_url`). `store.py` ve
  `notes/store.py` bunun üstüne taşınır; 12 numara önce `SEQUENCE` seçeneğiyle prototiplenir.

## 5. Test altyapısı (21 Kas)

- `scripts/test-pg.sh [modüller...]`: yerelde bulunan `postgres:16-alpine` ile geçici kapsayıcı (tmpfs, yalnız 127.0.0.1, rastgele port, bitince silinir), `CLAUDEOPS_TEST_PG_URL` verip `py/tests` altında modülleri koşar (varsayılan `test_dbapi`). varaka'nın ya da canlı DB'ye dokunmaz.
- `test_dbapi.py` (gerçek PG testi dahil) ve `test_store_pg.py` (mevcut `StoreTests`/`Edge` testleri PG'de, her test kendi şemasında; SQLite'a özgü 7 test atlanır). URL yoksa hepsi atlanır, normal paket etkilenmez.
- İLK GERÇEK PG DOĞRULAMASI: `store.py` göçü (IDENTITY, DOUBLE PRECISION, `schema_version`), `ON CONFLICT`, `RETURNING id`, advisory lock, iş parçacığıyla `update_doc` kayıpsızlığı PG 16'da geçti.
- Henüz PG'ye taşınmayanlar: `notes/store.py` (tetikleyici sayacı, envanter 12) ve Rust `dalgic` PG yolu (sqlx).
