# rs/state (W0-a): `cops-state` crate'i

Durum (26 Kas 2026 akşam): açık işler 1-4 kapandı (madde 5 sahibe soru olarak aşağıda). **Birleştirmeye hazır DEĞİL**:
eşleme tablosunda 157 EKSİK satır var, sahip soruları (S1-S10) cevapsız.
Kod: `31f9868` (ilk), bu tur `d438cd1`, `a4dfdda`, `becc4d6`, `56ebd96`, `15b97b5`, `bd11a27` ve belge commit'i.
Doğrulama (rust/ içinde): `cargo fmt -p cops-state --check`, `cargo clippy -p cops-state --all-targets -- -D warnings`,
`cargo test -p cops-state` (13 birim + 46 entegrasyon/parite testi = 59, 11 test ikilisi). Parite testleri `python3` ve
kullanıcı site paketlerini (`websockets`) ister; yalnız geçici dizine yazar (`HOME` ve `CLAUDEOPS_DIR` geçici, `TestEnv`).

DİKKAT (paylaşılan Cargo hedefi): `claudeops-wt-rs-rev` worktree'sinde de `rust/crates/cops-state` kopyası var. Cargo
1.98 çalışma alanı üyesinin `-C metadata` özetine yolu katmıyor; iki worktree `~/.cargo-target` içinde AYNI
`libcops_state-<özet>.rlib` dosyasını birbirinin üstüne yazıyor (bu turda iki kez "modül yok" derleme hatası buna
bağlandı). Bu izin komutları `CARGO_TARGET_DIR=~/.cargo-target/rs-state` ile koşuldu.

## Genel API

| Modül | Python karşılığı | Ana tipler ve işlevler |
|---|---|---|
| `json` | `json` modülü | `Json` (sıra korur; `parse`, `parse_lossy`, `to_compact`, `to_indented`, `py_eq`, `truthy`, `get`, `as_array_mut`; serde `Serialize`), `Map`, `py_float_repr` |
| `pycompat` | Python yerleşikleri | `str_of`, `repr`, `repr_str`, `str_or_empty`, `strip`, `is_space`, `is_printable`, `decimal_value`, `parse_int` (`PyInt`, sınırsız), `parse_float`, `prefix_chars` |
| `pytime` | `datetime(...).timestamp()` | `naive_local_timestamp` (CPython `local_to_seconds`) |
| `paths` | `paths.py` | `StateDir::{resolve, at, join, doc_path, roster_tsv, models_tsv, claude_models_json, settings_json, instances_json, db, apply_env, ensure_private}`, `expanduser`/`expanduser_with`, `home`, `claude_dir`, `sessions_dir`, `projects_dir`, `config_json`, `guard_lock`, `ucli_key_file`, `normpath`, `abs_normpath`, `realpath`, `parse_proc_stat`, `proc_stat_fields`, `proc_ppid`; test: `under_test`, `guard_write`, `live_dirs`, `TestEnv` |
| `fsutil` | `atomic_json.py`, `web._atomic_write_text` | `atomic_write_json`, `atomic_write_text`, `atomic_write_tsv`, `create_unique`, `write_corrupt_copy`, `FileLock::{acquire, acquire_within, roster, blocking}` |
| `store` | `store.py` | `Store::open` (oluşturmaz, göç yok), `get_doc(_raw)`, `set_doc`, `update_doc`, `delete_doc`, `list_docs`, `doc_version`, `export_docs`, `replace_tsv`, `delete_tsv`, `tsv_text`, `tsv_rows(file, active)`, `tsv_files`, `schema_version`, `append_log`, `read_log`, `tail_log`, `trim_log`, `list_streams`, `export_all`, `import_all`, `backup`; `StoreError`, `LogRow`, `ImportCounts`, `SCHEMA_VERSION` = 2 |
| `statedocs` | `statedocs.py` | `StateDocs::{new, isolated, backend, db_ready, register_doc_prefix, name_for, store, read, read_opts, read_with(on_corrupt), write, mirror_log, shadow_tsv, effective_backend}`; `Backend`, `Read` (`Value`/`Lossy`/`Missing`/`Corrupt`), `WriteOutcome`, `MIRROR_EVERY`, `MIRROR_KEEP` |
| `settings` | `settings.py` (okuma) | `load`, `SettingsReader::{load, last_good}`, `Settings::{get, str_of, sub_str, flag_default_on, routing_guidance_enabled, tunnel_watch_enabled}`, `defaults`, `backup_if_corrupt`, `OFF_WORDS` |
| `settings_read` | `settings.py` okuyucuları | `Settings::{resolved_binary, byok_env_for, ucli_limit_overrides, ucli_usage_warn_thresholds, ucli_reasoning_mode, ucli_stream_enabled, ucli_show_reasoning_enabled, ucli_state_dir_enabled, ucli_services, ucli_cost_config, ucli_script_mode, ucli_endpoint, ucli_web_config, daemon_config, uzakgoz_config, derbent_config, reader_config}`, `normalize_ucli_services`, `valid_http_url`, `which`, `SysEnv`, `SettingsTypeError`, `UcliCost`, `DaemonConfig`, sabitler |
| `roster` | `roster.py`, `web.py` TSV | `Roster::{raw_rows, entries, by_name, models, fleet_status, lock, register_project}`, `RosterGuard::{append, set_active, replace}`, `read_text`, `normpath`, `known_names`, `blueprint_cwds` |
| `instances` | `instances.py` | `Instances::{read_strict, load, get, mutate, try_mutate, record, mark_started, mark_models_gone, forget, rename_blueprint, add_missing}`, `derived_name`, `auto_name`, `created_at_from_name`, `infer_blueprint`, `DIAG_PREFIX` |

Kullanım kuralları (sonraki izler için):
- Süreç başına TEK `StateDocs` (`Arc`): kirli/eşitlendi kayıtları, okuyucu önbellekleri ve DB bağlantısı onda.
- API yanıtında `Json` doğrudan `serde_json` ile yazılır, sıra korunur.
- `serde_json` `preserve_order` AÇILMAZ: workspace geneline yayılır; enterprise `cops-ent-auth` testi sıralı anahtara dayanıyor.
- Süreç taraması ve sağlayıcı varsayılanları çağırandan gelir (`register_project`in `running` ve `default_model` parametreleri).
- `HOME`/`PATH` kullanan okuyucular `SysEnv` alır (`SysEnv::from_process()`); testler açık değer verir.
- `Settings` sır (`byok`) taşır; `Debug` içeriği göstermez; loglanmaz, yanıtlanmaz.
- `FileLock` tutamacı `Send` değil: kilit iş parçacığına bağlı (yeniden giriş iş parçacığı başına). Async kod kilidi `spawn_blocking` içinde alıp bırakır.
- Python'un istisna fırlattığı bozuk değerler Rust'ta açık hata döner (`SettingsTypeError`, `InstancesError::Corrupt`), sessizce yutulmaz.

## Durum parçaları: tek yazar, doğruluk kaynağı, kilit sözleşmesi

| Parça | Doğruluk kaynağı | Yazarlar | Kilit (Python <-> Rust) | Ayna |
|---|---|---|---|---|
| `settings.json` | dosya | yalnız Python (`save_settings`) | `file_lock(settings.json)` <-> `FileLock::acquire` | `dual`/`db` kipte DB `settings` belgesi gölge (dosya doğruluk kaynağı) |
| `roster.tsv`, `models.tsv` | dosya | Python panel/CLI + Rust `RosterGuard` | `<dizin>/roster.lock` (`roster_lock` <-> `Roster::lock`/`FileLock::roster`) | DB `tsv_rows` gölge (`shadow_tsv`), dışa aktarım |
| `instances` | `db` kipte DB; `files`/`dual` kipte dosya | Python `instances._mutate` + Rust `Instances::try_mutate` | `instances.json.lock` (`_locked` <-> `FileLock::blocking`) + DB `BEGIN IMMEDIATE` | `db` kipte dosya ayna |
| `DB_READY` belgeleri ve `steward/`, `orchestration/` önekleri | `db` kipte DB | `statedocs.write_json` <-> `StateDocs::write` | DB işlemi | dosya ayna (yalnız dışa aktarım ve geri dönüş) |
| diğer belgeler | dosya (`db` istense de `dual`) | aynı | çağıranın `file_lock`u | DB gölge |
| `log` akışları | DB (`mirror_log`) | dosya günlüğü yazanlar | DB işlemi | dosya günlüğü asıl |

Python ve Rust aynı kilit dosyalarını kullanır: `tests/lock_e2e.rs` (Python tutarken Rust bekler/zaman aşımına düşer,
Rust tutarken Python'un `flock`u meşgul görür, roster ve instances kilitleri ortak) ve `tests/parity.rs::concurrent_writers_lose_nothing`
(Python 40 + Rust 4x10 eşzamanlı yazım: kayıp güncelleme yok).

## Kararlar

- Rust DB oluşturmaz, göç çalıştırmaz; sürüm açılışta ve her yazım işlemi içinde denetlenir.
- Test algısı: ikili `.../deps/<ad>-<16 hex>` ise `CLAUDEOPS_DIR` yokken süreç başına geçici dizin (`atexit` siler); test
  ikilisinde canlı dizine yazım (ve canlı dizine çözülen `StateDir::resolve`) yazımdan ÖNCE panik verir.
- `default_settings.json` ve `default_ucli_services.json` Python'dan üretildi; parite testi ayrışmayı yakalar.
- `unicode_tables.rs` Python 3.10 (unicodedata 13.0.0) `str.isprintable`, ondalık rakam ve NFKC verisinden üretildi;
  `parity_settings::unicode_tables_match_python` HER kod noktasını Python'la karşılaştırır. Python sürümü değişirse test
  kırmızı olur, tablo yeniden üretilir.
- Ondalık yazımında eşit uzaklıkta iki en kısa aday varsa çift basamak seçilir (Python `repr`). Aynı hata enterprise
  `crates/cops-ent-auth/src/pyjson.rs::py_float_repr` içinde duruyor (kod okuması, orada test koşulmadı).
- Workspace'te kilitli özet crate'i yok: `.corrupt-<sha8>` adı için küçük SHA-256 (`sha256.rs`, `hashlib`e karşı parite).
  Yeni crate eklenmedi; `rusqlite` için `backup` özelliği açıldı (Cargo.lock'ta yalnız `tempfile` dev bağımlılığı kalktı).

## Python'dan sapmalar (eski madde 4) ve karar

| Sapma | Python | Rust (şimdi) | Karar, kanıt |
|---|---|---|---|
| `FileLock` yeniden giriş | aynı iş parçacığında iç içe alınır | AYNI (`56ebd96`): yol `normpath(abspath)`, iç içe alma yeni `flock` almaz, düşürme sırası önemsiz | Python gibi. `fsutil::tests::reentrant_same_thread_exclusive_across_threads`, `tests/lock_e2e.rs` |
| `FileLock` zaman aşımı / yabancı ya da bağ kilit dosyası | uyarı + kilitsiz sürer | `TimedOut` / `PermissionDenied` / `ELOOP` hatası | Değiştirilmedi: S1, S5. `fsutil::tests::lock_symlink_refused` |
| Süreç içi bekleyen iş parçacığı | `RLock` süresiz bekler | `flock` 30 sn sonra hata | S1 kapsamında |
| `CLAUDEOPS_STORE_BACKEND` | her çağrıda okunur | AYNI (`56ebd96`; `isolated` okumaz) | Python gibi. `tests/env_backend.rs` |
| `db` kipte KALICI DB hatası (DB yok, şema yeni, Postgres) | dosyaya yazar, belgeyi kirli sayar | hiçbir yere yazmaz, hata döner | SIKI KALDI. Gerekçe (veri kaybı): Rust bu DB'ye hiç yazamayacağı için dosyaya yazdığı değer db-hazır belgede Python okuyucularına görünmez ve Python'un sonraki ayna yazımı onu ezer (sessiz kayıp, iki süreç farklı değer görür). Geçici hata (kilit) Python gibi `DbDeferred`. `parity.rs::schema_mismatch_never_writes`, `db_transient_failure_defers_and_recovers` |
| TSV alanında sekme / satır sonu | denetlenmez (yalnız `cwd`) | `InvalidInput`, hiçbir dosya yazılmaz | SIKI KALDI. Gerekçe (güvenlik + veri bütünlüğü): satır sonu yeni roster satırı enjekte eder, sekme `cli` sütununu kaydırır. `parity_instances::register_model_newline_documented_divergence`, S3 |
| `~kullanici` | `pwd` ile genişletilir | AYNI (`d438cd1`, `paths::expanduser_with`; `HOME` yoksa passwd) | Python gibi. `parity_settings::expanduser_and_proc_match_python` |
| Eşlenmemiş vekil (`"\ud800"`) | okunur, yazılamaz | AYNI: `Read::Lossy` (U+FFFD ile okunur, DB'ye aktarılmaz), yazıcı hata | Python gibi; U+FFFD yalnız Rust dizesinde tutulamadığı için. `parity_instances::lone_surrogate_readable_not_writable` |
| UTF-8 olmayan `settings.json` | istisna | varsayılanlar | Değiştirilmedi: S2. `parity_settings::settings_non_utf8_documented_divergence` |
| `Instances::load` önbelleği | dosya anahtarlı önbellek | `files`/`dual`: AYNI (`becc4d6`); `db`: önbelleksiz | `db` kısmı S4. `parity_instances::load_cache_semantics` |
| `load_settings` G/Ç hatası | varsayılanlar önbelleğe girer | varsayılanlar döner, önbelleğe GİRMEZ | Ders listesi (last_good) gereği UYGULANDI, S7'de onay istenir. `parity_settings::settings_io_error_keeps_last_good` |
| `Store::backup` meşgul DB | süresiz bekler (0,25 sn aralık) | 30 sn sonra hata | Sınırlı bekleme dersi (H8); tek tutamaç |
| `add_missing` kayıt değeri liste çiftleri (`dict([[k, v]])`) | sözlüğe çevrilir | hata | Önemsiz (yalnız göç aracı); kayıtlar her zaman nesne |
| `proc_ppid` alan eksik | `IndexError` | `ProcError::Parse` | İkisi de hata |
| `load_instances` `stat` EACCES | istisna | boş sözlük | Okuyucu toleranslı; yazıcı (`try_mutate`) yine hata verir |

## Sahibe soruldu

Python davranışı hatalı olabilir; Rust'ta SESSİZ düzeltme ya da SESSİZ taklit yok. Rust'ın şimdiki davranışı (S7 hariç
hepsinde değişmedi) yazılı; karar sahibin.

| # | Konu | Python | Rust (şimdi) | Seçenek A | Seçenek B | Öneri |
|---|---|---|---|---|---|---|
| S1 | `file_lock` 30 sn zaman aşımı | uyarı (yol başına bir kez) + yalnız iş parçacığı kilidiyle, süreçler arası KORUMASIZ sürer: kayıp güncelleme olabilir | `TimedOut`, oku-değiştir-yaz yapılmaz | Rust da kilitsiz sürsün | Python da hata versin (çağıran 503/uyarı) | B |
| S2 | UTF-8 olmayan `settings.json` | `load_settings` `UnicodeDecodeError` fırlatır (except listesinde yok): `/api/status` ve her ayar okuyucusu düşer | varsayılanlar (`store_backend` dahil `files`) | Rust da hata dönsün | Python varsayılana düşsün (`save_settings` zaten `.corrupt` yedekler); `store_backend` için son iyi değer | B |
| S3 | `_register_project` `model` alanı | iç `\n`/`\t` kabul: models/roster'a sahte satır yazılır (testte `sahte\t/etc` satırı oluştu) | reddeder, dosyaya dokunmaz | Rust Python gibi kabul etsin | Python da reddetsin (`model_bad_chars`) | B |
| S4 | `db` kipte `load_instances` önbelleği | anahtar yalnız ayna dosyanın (inode, mtime, boyut); ayna yazılamazsa (hata yutulur) ya da başka süreç yalnız DB'yi değiştirirse bayat liste (ör. `name_in_use` kaçar) | `db` kipte önbelleksiz (her okumada DB) | Rust'a Python önbelleği | İki dilde anahtara DB `doc_version` eklensin ya da `db` kipte önbellek kapansın | B |
| S5 | `file_lock` kilit dosyası sembolik bağ / başkasının | uyarı + kilitsiz sürer | hata | Rust kilitsiz sürsün | Python hata versin | B |
| S6 | `instances._locked` | süresiz `flock` bekler (`7b9a1ff` sınırı yalnız `file_lock`a uygulanmış) | aynı (süresiz, `FileLock::blocking`) | ikisi de süresiz kalsın | ikisine 30 sn sınır + hata | B |
| S7 | `load_settings` G/Ç hatası (EACCES, EMFILE) | `stat` başarılı `open` başarısızsa varsayılanlar o imzayla önbelleğe girer, dosya değişene dek varsayılan döner (belgesi "okunamazsa önbellek yok" diyor) | UYGULANDI: önbelleğe girmez, son iyi değer korunur, hata geçince yeni içerik | Rust'ı Python'a eşitle (geri al) | Python'u kendi belgesine uydur | B |
| S8 | `normalize_ucli_services` `models` sıfır olmayan sayı / `true` | `TypeError` (`ucli_services()` fırlatır; belge "asla fırlatmaz") | `SettingsTypeError` (aynı sonuç, açık hata) | böyle kalsın | ikisi de geçersiz değeri boş listeye düşürsün | B |
| S9 | `resolved_binary` `provider_bin[cli]` dize değil (sayı, `null`, liste) | `AttributeError`, spawn düşer | `SettingsTypeError` | böyle kalsın | ikisi de geçersiz değeri yok sayıp PATH'e baksın | B |
| S10 | `expanduser("~a\0b")` | `ValueError` | genişletmeden döner (sonra "dizin yok") | Rust hata dönsün | Python'daki gibi kalsın (önemsiz) | A gerekmez, B |

## Ders listesi

`docs/rust-lessons-from-python.md` bölüm 2.1 (12 madde) ve bölüm 3 (20 madde). Her "karşılandı" satırındaki testin o şeyi
gerçekten sınadığı okunarak doğrulandı; fd sızıntı testi (bilerek eklenen bir sızıntıyla) ve canlı dizin koruması
(`create_unique`ten koruma çıkarılarak) geçici olarak bozulan kodla kırmızıya döndü, kod geri alındı.

### 2.1 cops-state

| Madde | Durum | Kanıt / gerekçe |
|---|---|---|
| Her durum parçası için tek yazar ve doğruluk kaynağı yazılı; ayna yalnız dışa aktarım (H3) | karşılandı | bu belge "Durum parçaları" tablosu; `parity.rs::statedocs_modes_with_python` (db-hazır belgede db kipi dosyaya bakmaz) |
| Yeni durum SQLite; yeni JSON/JSONL durum dosyası yok (H2) | karşılandı | crate yeni durum dosyası açmaz (yalnız Python'un var olan dosyaları + `.corrupt-<sha8>` kanıt kopyası, Python kuralı); `tests/scan.rs::no_direct_file_writes` |
| Dosya yazımı yalnız atomik yazıcı (aynı dizinde tmp, dosya + dizin fsync, izin açılışta); `std::fs::write` yok (H2) | karşılandı | `fsutil.rs:38` `write_replace` (O_EXCL+O_NOFOLLOW, fsync, rename, dizin fsync); `scan.rs::no_direct_file_writes`; `parity_store::atomic_write_text_matches_python` (bayt + izin + geçici dosya kalmaz) |
| Oku-değiştir-yaz kilit altında, zaman aşımlı flock; kilit yolu normalize (`0872f86`) (H2) | karşılandı | `RosterGuard` (`roster.rs`), `Instances::try_mutate`, `Store::update_doc` (`BEGIN IMMEDIATE`); `FileLock` 30 sn + `abs_normpath`: `fsutil::tests::reentrant_same_thread_exclusive_across_threads` (`alt/../belge.json` aynı kilit, zaman aşımı); istisna `FileLock::blocking` süresiz (Python ile aynı, S6) |
| Python ile paylaşılan belge: kilit sözleşmesi belgeli, iki yazarlı e2e (R1-3) (H2, H14) | karşılandı | "Durum parçaları" tablosu + `tests/lock_e2e.rs` başlığı; `lock_e2e::python_lock_blocks_rust_and_back`, `roster_and_instances_locks_shared`; `parity.rs::concurrent_writers_lose_nothing` |
| "Yok", "boş", "bozuk" ayrı; bozuk belge yazımdan önce `.corrupt-<sha>` yedeği (`d63c39d`) (H5) | karşılandı | `Read::{Value, Lossy, Missing, Corrupt}`; boş TSV ile yok TSV ayrı (`parity.rs::roster_reads_and_writes_match_python` boş/silinen dosya); Rust yazıcıları bozuk belgenin üstüne yazmaz (`parity.rs::instances_match_python`, `parity_instances::bad_encoding_files_not_overwritten`); yedek: `fsutil::write_corrupt_copy`, `settings::backup_if_corrupt`, `StateDocs::read_with(on_corrupt)`: `parity_store::sha256_and_corrupt_backup_match_python`, `mirror_log_and_on_corrupt_match_python` |
| Ayarda varsayılanların derin kopyası paylaşılmaz; sözlük olmayan blok yamayı çökertmez/silmez (`de592ee`, `683a750`) (H5) | karşılandı | okuma: `Settings::from_text` varsayılanları kopyalar, `DICT_KEYS` sözlük değilse `{}` (`parity.rs::settings_match_python`, `settings::tests::merge_rules`, 59 durumlu `parity_settings::settings_readers_match_python`); yama yazımı Rust'ta yok (ayar yazımı Python'da, T7) |
| Sır/token "yoksa oluştur" kilit altında `create_new`; boş token reddi (`de592ee`, `6eaf870`) (H2, H5) | kapsam dışı | bu crate sır/token üretmez; `web.token` ve kimlik: `cops-auth` / rs/gate ve T9. `create_unique` ve `write_corrupt_copy` O_EXCL kullanır |
| Durum/yol çözümü tek `state_dir()`; `$HOME` doğrudan kullanılmaz (`f7f9dbc`) (H14) | karşılandı | `StateDir::resolve`; `scan.rs::home_only_in_paths` (HOME yalnız `paths.rs`te). Bilinçli istisna: `ucli_key_file` Python gibi `~/.claude/claudeops` (anahtarı ucli oraya yazar) |
| Önbellek hata durumunda `last_good` korunur; N+1. hata testi (D:1782) (H3) | karşılandı | `SettingsReader::load` G/Ç hatasını önbelleğe almaz, `last_good()`; `parity_settings::settings_io_error_keeps_last_good` (5 ardışık hata, sonra yeni içerik; Python farkı S7) |
| Mod/bayrak geçişi (db/dual/files) testi: kapalı dönemde karşı yazarın verisi (R2-3, R2-4) (H3) | karşılandı | `parity_instances::mode_transitions_match_python` (files yazarı -> db tembel içe aktarma -> db yazımı -> kapalı dönemde files yazarı -> db/dual okuma; iki dil her adımda aynı) |
| Testler yalnız `TestEnv` ile; canlı dizine yazım panik (H16) | karşılandı | `paths::TestEnv`, `guard_write`; `tests/guard.rs::writers_panic_in_live_dir_and_write_nothing` (11 yazıcı, dizin ağacı değişmez), `real_live_dir_is_guarded_without_touching_it`; parite ortamı `tests/common` `TestEnv` kullanır |

### Bölüm 3 (birleştirme öncesi 20 madde)

| # | Madde (kısa) | Durum | Kanıt / gerekçe |
|---|---|---|---|
| 1 | Hedef çözümü `Unique`; önek/"en yeni" tahmini yok (H7) | karşılandı (bu iz) | roster satırı yalnız TAM ilk alan eşleşmesiyle bulunur (`roster.rs:166` `find_line`), yoksa işlem yok (`parity.rs::roster_reads_and_writes_match_python` `set_active(.., "yok")` false); oturum hedefleme kapsam dışı: T4 / rs/tmux |
| 2 | Her yazım atomik ya da işlem; çok yazarlı belgede kilit sözleşmesi (H2) | karşılandı | `fsutil.rs:38`, `store.rs:209` (`BEGIN IMMEDIATE` + sürüm denetimi); "Durum parçaları" tablosu; `tests/lock_e2e.rs` |
| 3 | Belirsiz/kurulamayan durum "başarı" ya da "yok" olmuyor (H13, H10, H9) | karşılandı | `Read` dört değer; kalıcı DB hatası `WriteError::Db` (`parity.rs::schema_mismatch_never_writes`); bozuk instances yazılmaz (`parity_instances::bad_records_fail_like_python`); `Store::open` DB yoksa `Missing` (oluşturmaz) |
| 4 | Eylem sonucu doğrulanıyor; NEGATİF test (H9) | karşılandı | `WriteOutcome::{Written, DbDeferred}`; negatif testler: `db_transient_failure_defers_and_recovers`, `schema_mismatch_never_writes`, `bad_records_fail_like_python`, `bad_encoding_files_not_overwritten`, `guard.rs` |
| 5 | `let _`, `.ok()`, `unwrap_or_default()`, `expect` taraması; yutulan hata gerekçeli (H9, H20) | karşılandı | `tests/scan.rs::swallow_patterns_match_allowlist` (dosya başına sayı); gerekçeler aşağıda "Hata yutma taraması". `unwrap`/`expect` test dışı kodda yok |
| 6 | Önbellek/ayar bayatlamıyor; hata `last_good`u ezmiyor (H3) | karşılandı | `SettingsReader` imza (mtime, boyut, inode) anahtarlı, G/Ç hatası önbelleğe girmez (`settings_io_error_keeps_last_good`); instances önbelleği dosya anahtarlı, db kipte yok (`load_cache_semantics`); kip ortamı her çağrıda (`env_backend.rs`) |
| 7 | Her döngü/bekleme sınırlı (H8) | karşılandı (istisna S6) | `FileLock` 30 sn (`reentrant_...`, `lock_e2e::python_lock_blocks_rust_and_back` 300 ms), `Store::backup` 30 sn (`BACKUP_RETRIES`), `create_unique` 100 deneme, `realpath` 40 bağ, `getpw` 4 tampon; `FileLock::blocking` süresiz (Python `_locked` ile aynı; sahibe S6) |
| 8 | Dış CLI/TUI davranışı fixture'lı (H4) | kapsam dışı | bu crate CLI/TUI sürmez; rs/tmux (W0-b), rs/prov |
| 9 | Alt süreç/bağlantı sahibi belli; fd sızıntı testi (H1) | karşılandı | crate alt süreç açmaz; DB bağlantısı `Store` ile düşer; `tests/fd_leak.rs` (ayrı ikili, 60 tur tüm yollar + hata yolları; bilerek eklenen 1 sızıntıyla kırmızıya döndüğü doğrulandı) |
| 10 | Girdi sınırları: boş, negatif/dev, NaN/inf, bozuk UTF-8, tip hatalı JSON (H5) | karşılandı | `parity_settings::settings_readers_match_python` (NaN, inf, 1e400, -1, 10^23, yanlış tipler), `int_float_parse_match_python`, `str_repr_match_python`, `parity.rs::settings_match_python`, `bad_encoding_files_not_overwritten`, `lone_surrogate_readable_not_writable`, `parity.rs::json_bytes_match_python` |
| 11 | Ad/işaret ayrıştırma tek modülde, corpus'lu, Python'la eşit (H6, H14) | karşılandı (bu iz) | `instances.rs` `match_dated` (DERIVED/AUTO aynı eşleyici): `parity_instances::name_patterns_and_created_at_match_python` (Unicode rakam, sondaki `\n`, tembel önek), `parity.rs::name_helpers_match_python`; STEWARD-* işaretleri kapsam dışı: rs/stew |
| 12 | Paylaşılan kural (strip, yol, state_dir) altın vektör + diferansiyel; `$HOME` yok (H14) | karşılandı | `pycompat` tüm kod noktalarında (`unicode_tables_match_python`), `expanduser_and_proc_match_python`, `parity.rs::name_helpers_match_python` (normpath); `scan.rs::home_only_in_paths` |
| 13 | Sırlar log/argv/URL'de yok; yetki matrisi (H12, H13) | karşılandı (bu iz) | `Settings` `Debug` içeriği gizler (`settings::tests::debug_hides_secrets`); DB URL hatasında yalnız şema (`schema_mismatch_never_writes` `Unsupported("postgresql")`); kimlik/yetki matrisi kapsam dışı: `cops-auth`, rs/gate, T9 |
| 14 | `SafePath`/canonical IP; symlink/`..` testleri (H17) | karşılandı (bu iz) | geçici ve kilit dosyaları `O_NOFOLLOW`, kilit dosyası bize ait normal dosya olmalı (`fsutil::tests::lock_symlink_refused`: bağ hedefi oluşmaz); `..` normalize (`reentrant_...`); DB yalnız durum dizini altında (`statedocs_modes_with_python` dışarıdaki yol); IP/SSRF kapsam dışı: rs/gate, rs/hosts |
| 15 | Vekil/WS kullanıcı yolundan e2e (H15, H18, H21) | kapsam dışı | vekil/WS yok; rs/gate, T2 |
| 16 | Yeni uç/route tablo eşitliği (H10, H14) | kapsam dışı | bu crate uç eklemez; rs/gate, T1 |
| 17 | Testler yalıtılmış (`TestEnv`, port 0, RAII); canlı dizin değişmedi (H16) | karşılandı | `TestEnv` (RAII), `guard.rs`; ağ portu yok; Python alt süreci geçici `HOME`/`CLAUDEOPS_DIR` (`tests/common`) |
| 18 | Uzak host sürüm/yetenek, devre kesici (H10, H11) | kapsam dışı | uzak çağrı yok; rs/hosts, T5 |
| 19 | İkili sürümü (`GIT_SHA`), canlı = main, geri dönüş (H11) | kapsam dışı | kütüphane crate'i, ikili yok; copsd / rs/gate |
| 20 | Ölçüm/kanıt; `--dry-run` yan etkisiz; Python'a yeni özellik yok (H21) | karşılandı | performans ya da kök neden iddiası yok; kuru çalıştırma yok; `git diff da8cee6..HEAD -- py/` boş (Python'a dokunulmadı) |

### Hata yutma taraması (test dışı kod; `tests/scan.rs` sayıları denetler)

| Yer | Kalıp | Gerekçe |
|---|---|---|
| `fsutil.rs` `fsync_dir` | `let _ = d.sync_all()` | dizin fsync en iyi çaba (Python `_fsync_dir` `OSError` yutar) |
| `fsutil.rs` `write_replace` | `let _ = f.set_permissions(..)` | umask'ı aşan chmod; Python `contextlib.suppress(OSError)` |
| `fsutil.rs` `write_replace`, `atomic_write_*` (4) | `let _ = fs::remove_file(tmp)` | önceki çöküşten kalan geçici dosyayı / hata sonrası geçiciyi silme; asıl hata dönülür (Python aynı) |
| `fsutil.rs` `atomic_write_json/text` (2) | `.ok()` | var olan dosyanın izni: yoksa `None` = umask (Python `_existing_mode`) |
| `fsutil.rs` `FileLock::drop` | `let _ = HELD.try_with(..)` | iş parçacığı sonlanırken yerel depo yok olabilir; kayıt zaten düşüyor |
| `json.rs` `as_f64` | `.ok()` | büyük tam sayının kayan noktası; ayrıştırılamazsa sayı değil |
| `paths.rs` atexit ve `TestEnv::drop` (2) | `let _ = remove_dir_all` | temizlikte hata bildirilecek yer yok; kalan geçici dizin `/tmp` temizliğine |
| `paths.rs` `getpw` | `.ok()` | NUL içeren ad: passwd kaydı yok (S10) |
| `pycompat.rs` (2) | `.ok()` | sayı metni dönüşümü; hata = Python `ValueError` = `None` |
| `pytime.rs` | `.ok()` | `time_t` taşması = `None` (Python `OverflowError`) |
| `roster.rs` (3) | `unwrap_or_default()` | dosya yok = boş içerik (Python `FileNotFoundError` -> `""`); hata türleri `?` ile ayrı döner |
| `roster.rs` `fleet_status` | `unwrap_or_default()` | models satırında model yok = `""` (Python aynı) |
| `settings.rs` imza, `backup_if_corrupt` (2) | `.ok()` | `stat` hatası = imza yok (önbellek yok); okunamayan dosya yedeklenmez (Python `OSError` -> dön) |
| `settings_read.rs` port | `.ok()` | 1024..65535 aralığı zaten süzüldü |
| `statedocs.rs` `sig`, `read_file` (3) | `.ok()` | Python `_sig` `OSError` -> `None`; `_file_read` UTF-8/JSON hatası -> `Corrupt` |
| `statedocs.rs` `new` | `unwrap_or_default()` | `CLAUDEOPS_DB_URL` yok = SQLite (Python `""`); UTF-8 olmayan değer de SQLite'a düşer (Python `DbError`; önemsiz) |
| `statedocs.rs` `shadow_tsv_inner` | `unwrap_or_default()` | gölge yok = `""` (Python `or ""`) |
| `statedocs.rs` `mirror_log` | `let _ = st.trim_log(..)` | Python `mirror_log` tüm hataları yutar (günlük -> log döngüsü olmasın); sonraki eşikte yeniden |
| `store.rs` `backup` | `let _ = remove_file(tmp)` | hata sonrası geçici dosya; asıl hata dönülür |

## Eşleme tablosu

Ölçüm anı: 26 Kas 2026, HEAD `e5a684e`. Tanım listesi `ast` ile üretildi: sekiz modülün her modül düzeyi ataması (aynı
satırdaki iki ad iki satır) ve her `def`/`class` tanımı (iç içe ve sınıf yöntemleri dahil) 211; `commands/web.py`den TSV
sabitine, TSV yardımcılarına ya da `roster.lock`a doğrudan dokunan tanımlar ile `_NAME_VALID_RE`, `_blueprint_cwds`,
`_all_known_names`, `_generate_new_chat_name` 23. Python testleri okunarak eşlendi, KOŞULMADI. Rust tarafı: `cargo test -p cops-state` bu ağaçta 59/59 geçti.

Okuma kuralı:
- `tamam`: Rust karşılığı var VE adı yazılan test açılıp o satırın ana davranışını sınadığı görüldü.
- `EKSİK`: kapsam içi olup Rust'ta kod yok, davranış farklı ya da en az bir anlamlı dal sınanmıyor (parantez içinde hangisi).
  Test satırında "kısmi", testin Python iddialarının yalnız bir bölümünü karşıladığı anlamına gelir.
- `kapsam dışı`: gerekçe ve iz. `W0-a` = bu iz (Rust'ta taşınacak kavram yok).
- Rust dosyaları `rust/crates/cops-state/src/`, testleri `rust/crates/cops-state/tests/` altındadır (`paths.rs`, `fsutil.rs`,
  `settings_read.rs` içindeki birim testleri `src/` altında).

### Sayım

| Satır türü | Toplam | tamam | kapsam dışı | EKSİK |
|---|---|---|---|---|
| Tanım satırı | 234 | 128 | 31 | 75 |
| Test metodu satırı | 306 | 111 | 113 | 82 |
| Dosya satırı (kalan metotlar) | 103 | 0 | 103 | 0 |
| Toplam | 643 | 239 | 247 | 157 |

Listelenen 31 test dosyasının 189 metodu tek tek yazıldı; diğer dosyalardan 117 metot tek tek, kalan 1715 metot 103 dosya
satırıyla yazıldı.

### EKSİK özeti (gruplu)

Kod eksiği ya da davranış farkı:

| # | Konu | Not |
|---|---|---|
| K1 | `Store::replace_tsv` boş metinde 1 döner, Python 0 | `store.rs` `Ok(lines.len().max(1))`; Python sayıyı "empty" satırını eklemeden önce alır. Belgeli sapma değildi |
| K2 | `steward_config`, `steward_ids` yok | ayar okuma bu izin tanımında; rs/stew'a devredilecekse cops kararı |
| K3 | `default_model_for`, `default_effort_for`, `resolved_model_for` yok | sağlayıcı nesnesi ister; rs/prov'a devredilecekse cops kararı |
| K4 | `statedocs` günlüğü `diag.log`a gitmiyor | varsayılan günlükçü `eprintln!`; Python `diag_log` |
| K5 | `file_lock` uyarı ve kilitsiz sürme yok | belgeli sapma, sahip sorusu S1 ve S5 |
| K6 | `known_names` canlı süreç adlarını içermiyor, testi de yok | süreç taraması T1/T4 girdisi |

Yalnız test eksiği (kod var):

| Grup | Sınanmayanlar |
|---|---|
| paths | `home`, `claude_dir`, `sessions_dir`, `projects_dir`, `config_json`, `guard_lock`, `claude_models_json`, `proc_stat_fields`, `proc_ppid`, `ensure_private` (0700), `apply_env` ve geçici dizin silme, `CLAUDEOPS_TEST_REAL_DIR=1`, `ucli_key_file` (parite testi kopyayı karşılaştırıyor) |
| statedocs | kip önbelleği (5 sn), `register_doc_prefix`, imza atlaması (`synced`), `file_truth=false`, dual dosya yokken/bozukken DB'den okuma, dual boş DB'ye tembel aktarım, okumada DB hatasından dosyaya düşme, dual yazım hatası sonrası eşitleme, ayna hatası, günlük iletileri, `mirror_log` kırpma sabitleri ve hata yutma, `shadow_tsv` atlama dalları |
| store / dbapi | geri alma (ROLLBACK), yedek hatasında temizlik ve ikinci yedek, olmayan belge sürümü ve silmesi, `sqlite:` url ve tanınmayan şema, `CLAUDEOPS_DB_URL`, WAL/`synchronous`, `schema_version` tablosu ve tablosuz eski DB, `BUSY_TIMEOUT_MS` paritesi, dual kipte instances gölgesi |
| settings | ucli env/kimlik sınırları ve tavanlar, alan adı sınırları ve 64 tavanı, `ucli_web` flavor'sız adres, kırpma, sözlük olmayan blok (`ucli_web`, `ucli_cost`, `ucli_usage_warn`, diğer sözlük anahtarları), `read` script kipi, tanınmayan akıl yürütme değeri, önbellek isabeti, olmayan dosyada yedek yok |
| roster / instances | `name` başlık dışlaması, `cwd_bad_chars`, olmayan dosyada `set_active`, eşzamanlı aç/kapat, `DIAG_PREFIX` paritesi, aynı cli'de `cli_opts` korunması |
| atomik yazım ve kilit | fsync sırası, sembolik bağlı geçici ad, açık/korunan kip (JSON), umask (JSON), dizinsiz ad, eşzamanlı yazım, hata sonrası geçici dosya, panikte kilit bırakma, yabancı kilit dosyasında uid/tür reddi, `LOCK_TIMEOUT` paritesi |

### Tabloda görülen tutarsızlıklar

- `src/settings_read.rs` modül belgesi parite testini `tests/parity.rs::settings_readers_match_python` diye anıyor; test
  `tests/parity_settings.rs` içinde.
- Rust göç yapmıyor; `docs/rust-sprint-plan.md` göçü taşıyacak bir iz yazmıyor. Göç satırları T6 (CLI) ve Postgres
  satırları T9 diye işaretlendi; bu atama cops onayı ister.
- `commands/close.py` `models.tsv` yazıyor (`# CLOSED` biçimi) ama görevdeki modül listesinde yok; testleri T6 sayıldı.
- Sprint planı T4 listesinde `register` de var; `_register_project` bu izde taşınmış, `_edit_project` taşınmamış (T4).
- W1-pre ve T satırlarındaki diğer iz worktree'leri bu turda okunmadı: "o izde var" iddiası değil, sorumluluk ataması.

### Tanımlar

#### `py/claudeops/paths.py` (20)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `HOME` (paths.py:5) | paths.rs::home | yok | EKSİK: test yok (`home()` hiçbir testte çağrılmıyor) |
| `CLAUDE_DIR` (paths.py:6) | paths.rs::claude_dir | yok | EKSİK: test yok |
| `_test_code_loaded` (paths.py:9) | yok (test algısı `_under_test_runner` satırında) | yok | kapsam dışı: Python modül tablosuna (`sys.modules`) özgü algı, Rust'ta taşınacak kavram yok; iz W0-a |
| `_under_test_runner` (paths.py:24) | paths.rs::under_test, looks_like_test_binary | paths.rs::test_binary_detection, under_cargo_test_never_real_dir | EKSİK: test yok (`CLAUDEOPS_TEST_REAL_DIR=1` kapatma dalı) |
| `os.environ['CLAUDEOPS_DIR']` (paths.py:43) | paths.rs::StateDir::apply_env, test_dir, remove_test_dir | yok | EKSİK: test yok (alt sürece devir ve çıkışta silme); Rust ortama kendiliğinden yazmaz |
| `CLAUDEOPS_DIR` (paths.py:45) | paths.rs::StateDir::resolve, resolve_from | paths.rs::rules, under_cargo_test_never_real_dir | tamam |
| `STATE_DIR` (paths.py:46) | paths.rs::StateDir::root | paths.rs::under_cargo_test_never_real_dir | tamam |
| `REPO_DIR` (paths.py:50) | yok | yok | kapsam dışı: yalnız tanı oturumunun cwd'si (`/api/diag/ask`); iz T4 |
| `ROSTER_TSV` (paths.py:52) | paths.rs::StateDir::roster_tsv | parity.rs::roster_reads_and_writes_match_python | tamam |
| `MODELS_TSV` (paths.py:53) | paths.rs::StateDir::models_tsv | parity.rs::roster_reads_and_writes_match_python | tamam |
| `CLAUDE_MODELS_JSON` (paths.py:54) | paths.rs::StateDir::claude_models_json | yok | EKSİK: test yok |
| `SESSIONS_DIR` (paths.py:56) | paths.rs::sessions_dir | yok | EKSİK: test yok |
| `PROJECTS_DIR` (paths.py:57) | paths.rs::projects_dir | yok | EKSİK: test yok |
| `CONFIG_JSON` (paths.py:58) | paths.rs::config_json | yok | EKSİK: test yok |
| `parse_proc_stat` (paths.py:60) | paths.rs::parse_proc_stat | parity_settings.rs::expanduser_and_proc_match_python | tamam |
| `proc_stat_fields` (paths.py:66) | paths.rs::proc_stat_fields | yok | EKSİK: test yok |
| `proc_ppid` (paths.py:72) | paths.rs::proc_ppid | yok | EKSİK: test yok |
| `ucli_key_file` (paths.py:76) | paths.rs::ucli_key_file | parity_settings.rs::expanduser_and_proc_match_python (kısmi) | EKSİK: parite testi Rust işlevini değil testteki kopyayı karşılaştırıyor; işlev yalnız `"x"` ile sonek için çağrılıyor, boş hizmet dalı sınanmıyor |
| `GUARD_LOCK` (paths.py:83) | paths.rs::guard_lock | yok | EKSİK: test yok |
| `ensure_private_state_dir` (paths.py:86) | paths.rs::StateDir::ensure_private | guard.rs::writers_panic_in_live_dir_and_write_nothing (yalnız koruma paniği) | EKSİK: test yok (dizin oluşturma ve 0700) |

#### `py/claudeops/statedocs.py` (26)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `MODES` (statedocs.py:19) | statedocs.rs::Backend, Backend::parse | env_backend.rs::env_backend_read_per_call | tamam |
| `_CACHE` (statedocs.py:20) | statedocs.rs::State.backend, BACKEND_TTL | yok | EKSİK: test yok (5 sn önbelleğin tutması ve süresinin dolması) |
| `_LOCK` (statedocs.py:21) | statedocs.rs::State (Mutex) | yok | EKSİK: test yok (testler kipi zorladığı için önbellek kilidi yolu eşzamanlı sınanmıyor) |
| `backend` (statedocs.py:24) | statedocs.rs::StateDocs::backend | env_backend.rs::env_backend_read_per_call; parity.rs::backend_from_settings_file | EKSİK: test yok (5 sn önbellek davranışı; diğer dallar sınanıyor) |
| `DB_READY` (statedocs.py:47) | statedocs.rs::DB_READY | parity.rs::constants_match_python | tamam |
| `DB_READY_PREFIXES` (statedocs.py:50) | statedocs.rs::DB_READY_PREFIXES | parity.rs::constants_match_python | tamam |
| `_EXT_PREFIXES` (statedocs.py:53) | statedocs.rs::State.ext_prefixes | yok | EKSİK: test yok |
| `register_doc_prefix` (statedocs.py:56) | statedocs.rs::StateDocs::register_doc_prefix | yok | EKSİK: test yok (kabul ve red) |
| `db_ready` (statedocs.py:63) | statedocs.rs::StateDocs::db_ready | parity.rs::statedocs_modes_with_python, constants_match_python | tamam |
| `_DIRTY` (statedocs.py:67) | statedocs.rs::State.dirty | parity.rs::db_transient_failure_defers_and_recovers | tamam |
| `name_for` (statedocs.py:70) | statedocs.rs::StateDocs::name_for | parity.rs::statedocs_modes_with_python | tamam |
| `_effective` (statedocs.py:77) | statedocs.rs::StateDocs::effective | parity.rs::statedocs_modes_with_python | tamam |
| `_db_ok` (statedocs.py:82) | statedocs.rs::StateDocs::db_ok | parity.rs::statedocs_modes_with_python (dizin dışı yol) | tamam |
| `_log` (statedocs.py:93) | statedocs.rs::StateDocs::log, with_logger | yok | EKSİK: kod (varsayılan günlükçü stderr; Python `diag.log`a yazar) ve test (import/drift/recover iletileri) |
| `_file_read` (statedocs.py:101) | statedocs.rs::read_file, read_with | parity_store.rs::mirror_log_and_on_corrupt_match_python | tamam |
| `_MISSING` (statedocs.py:116) | statedocs.rs::Read::Missing | parity_instances.rs::load_cache_semantics (olmayan dosya) | tamam |
| `_SYNCED` (statedocs.py:119) | statedocs.rs::State.synced | yok | EKSİK: test yok (imza değişmemişse DB karşılaştırması atlanır) |
| `_sig` (statedocs.py:122) | statedocs.rs::sig | parity.rs::statedocs_modes_with_python (elle düzenleme algılanır) | tamam |
| `read_json` (statedocs.py:130) | statedocs.rs::StateDocs::read, read_opts, read_with, read_db | parity.rs::statedocs_modes_with_python; parity_instances.rs::mode_transitions_match_python | EKSİK: test yok (`file_truth=false`; dual kipte dosya yokken DB'den okuma; DB açılamazken dosyaya düşme) |
| `write_json` (statedocs.py:175) | statedocs.rs::StateDocs::write | parity.rs::statedocs_modes_with_python, db_transient_failure_defers_and_recovers, schema_mismatch_never_writes | EKSİK: test yok (dual kipte DB yazımı düşünce imzanın unutulması; db kipinde ayna hatasının yutulması). db kipinde kalıcı hata sapması belgeli |
| `_MIRROR_N` (statedocs.py:214) | statedocs.rs::State.mirror_n | yok | EKSİK: test yok (eşikte kırpma) |
| `_MIRROR_KEEP` (statedocs.py:215) | statedocs.rs::MIRROR_KEEP | yok | EKSİK: test yok (değer Python'la karşılaştırılmıyor) |
| `_MIRROR_EVERY` (statedocs.py:216) | statedocs.rs::MIRROR_EVERY | yok | EKSİK: test yok (değer Python'la karşılaştırılmıyor) |
| `mirror_log` (statedocs.py:219) | statedocs.rs::StateDocs::mirror_log | parity_store.rs::mirror_log_and_on_corrupt_match_python | EKSİK: test yok (DB hatasının yutulması ve eşikte kırpma) |
| `_TSV_FILES` (statedocs.py:236) | statedocs.rs::TSV_FILES | yok | EKSİK: test yok (başka adlı dosyanın atlanması) |
| `shadow_tsv` (statedocs.py:239) | statedocs.rs::StateDocs::shadow_tsv, shadow_tsv_inner | parity.rs::roster_reads_and_writes_match_python (force, boş, silinen) | EKSİK: test yok (`force=false` imza atlaması; files kipi, dizin dışı yol ve başka ad atlaması) |

#### `py/claudeops/store.py` (36)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `MIGRATIONS` (store.py:21) | store.rs::SCHEMA_VERSION (yalnız sayı) | parity.rs::constants_match_python | kapsam dışı: göç metni Rust'a taşınmadı (karar: Rust göç yapmaz); sürüm sayısı sınanıyor; iz T6 (planda göç için ayrı iz yazılı değil) |
| `BUSY_TIMEOUT_MS` (store.py:58) | store.rs::BUSY_TIMEOUT_MS | yok | EKSİK: test yok (değer Python'la karşılaştırılmıyor) |
| `StoreError` (store.py:61) | store.rs::StoreError | parity.rs::db_roundtrip_both_ways, schema_mismatch_never_writes | tamam |
| `Store` (store.py:65) | store.rs::Store | parity.rs::db_roundtrip_both_ways | tamam |
| `Store.__init__` (store.py:66) | store.rs::Store::open | parity.rs::db_roundtrip_both_ways, schema_mismatch_never_writes | kapsam dışı: DB oluşturma, 0600 ve göç Rust'ta yok (karar); açma ve sürüm reddi sınanıyor; iz T6 |
| `Store._conn` (store.py:82) | store.rs::Store::conn | parity.rs::concurrent_writers_lose_nothing | tamam |
| `Store.close` (store.py:89) | store.rs::Store (Drop) | fd_leak.rs::no_fd_leak | tamam |
| `Store._tx` (store.py:95) | store.rs::Store::write | parity.rs::concurrent_writers_lose_nothing | tamam |
| `Store._migrate` (store.py:99) | yok (yalnız store.rs::check) | yok | kapsam dışı: Rust göç yapmaz (karar); iz T6 |
| `Store.schema_version` (store.py:105) | store.rs::Store::schema_version | parity_store.rs::export_import_backup_match_python | tamam |
| `Store.get_doc` (store.py:109) | store.rs::Store::get_doc, get_doc_raw | parity.rs::db_roundtrip_both_ways | tamam |
| `Store.set_doc` (store.py:113) | store.rs::Store::set_doc | parity.rs::db_roundtrip_both_ways | tamam |
| `Store.update_doc` (store.py:119) | store.rs::Store::update_doc | parity.rs::db_roundtrip_both_ways, concurrent_writers_lose_nothing | EKSİK: test yok (hata ya da panikte geri alma) |
| `Store.delete_doc` (store.py:132) | store.rs::Store::delete_doc | parity.rs::db_roundtrip_both_ways | EKSİK: test yok (olmayan belgede false) |
| `Store.list_docs` (store.py:136) | store.rs::Store::list_docs | parity.rs::db_roundtrip_both_ways | tamam |
| `Store.doc_version` (store.py:140) | store.rs::Store::doc_version | parity.rs::db_roundtrip_both_ways | EKSİK: test yok (olmayan belgede 0) |
| `Store._put` (store.py:145) | store.rs::Store::put | parity.rs::db_roundtrip_both_ways | tamam |
| `Store.append_log` (store.py:153) | store.rs::Store::append_log | parity_store.rs::log_functions_match_python | tamam |
| `Store.read_log` (store.py:158) | store.rs::Store::read_log | parity_store.rs::log_functions_match_python | tamam |
| `Store.tail_log` (store.py:164) | store.rs::Store::tail_log | parity_store.rs::log_functions_match_python | tamam |
| `Store.trim_log` (store.py:170) | store.rs::Store::trim_log | parity_store.rs::log_functions_match_python | tamam |
| `Store.replace_tsv` (store.py:178) | store.rs::Store::replace_tsv | parity.rs::roster_reads_and_writes_match_python (satırlar) | EKSİK: kod (boş metinde Rust 1 döner, `lines.len().max(1)`; Python 0 döner) ve test (dönüş değeri karşılaştırılmıyor) |
| `Store.delete_tsv` (store.py:204) | store.rs::Store::delete_tsv | parity.rs::roster_reads_and_writes_match_python (silinen dosya) | tamam |
| `Store.tsv_text` (store.py:209) | store.rs::Store::tsv_text | parity_store.rs::export_import_backup_match_python | tamam |
| `Store.tsv_rows` (store.py:213) | store.rs::Store::tsv_rows | parity_store.rs::tsv_rows_filter_and_files_match_python | tamam |
| `Store.backup` (store.py:222) | store.rs::Store::backup | parity_store.rs::export_import_backup_match_python | EKSİK: test yok (hata sonrası geçici dosya temizliği) |
| `Store.list_streams` (store.py:251) | store.rs::Store::list_streams | parity_store.rs::log_functions_match_python | tamam |
| `Store.tsv_files` (store.py:254) | store.rs::Store::tsv_files | parity_store.rs::tsv_rows_filter_and_files_match_python | tamam |
| `Store.export_all` (store.py:257) | store.rs::Store::export_all | parity_store.rs::export_import_backup_match_python | tamam |
| `Store.import_all` (store.py:266) | store.rs::Store::import_all | parity_store.rs::export_import_backup_match_python | tamam |
| `Store.export_docs` (store.py:289) | store.rs::Store::export_docs | parity_store.rs::export_import_backup_match_python | tamam |
| `_split` (store.py:294) | yok | yok | kapsam dışı: göç deyim bölücüsü; Rust göç yapmaz; iz T6 |
| `_DEFAULT` (store.py:299) | statedocs.rs::State.store | parity.rs::db_transient_failure_defers_and_recovers | tamam |
| `_DEFAULT_LOCK` (store.py:300) | statedocs.rs::State (Mutex) | parity.rs::concurrent_writers_lose_nothing | tamam |
| `default_path` (store.py:303) | paths.rs::StateDir::db | parity.rs::db_roundtrip_both_ways | tamam |
| `default_store` (store.py:308) | statedocs.rs::StateDocs::store | parity.rs::db_transient_failure_defers_and_recovers | tamam |

#### `py/claudeops/settings.py` (51)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `SETTINGS_JSON` (settings.py:28) | paths.rs::StateDir::settings_json | parity.rs::settings_match_python | tamam |
| `DEFAULT_SETTINGS` (settings.py:38) | settings.rs::defaults, default_settings.json | parity.rs::constants_match_python | tamam |
| `_LOAD_CACHE` (settings.py:239) | settings.rs::SettingsReader.cache | parity.rs::settings_match_python (geçersiz kılma); parity_settings.rs::settings_io_error_keeps_last_good | EKSİK: test yok (değişmeyen dosyada önbellek isabeti) |
| `load_settings` (settings.py:242) | settings.rs::SettingsReader::load, load | parity.rs::settings_match_python | tamam |
| `_load_settings_uncached` (settings.py:268) | settings.rs::read, Settings::from_text | parity.rs::settings_match_python | EKSİK: test yok (sözlük olması gereken 12 anahtarın yalnız birkaçı sözlük olmayan değerle sınanıyor, ör. `ucli_web` yok) |
| `save_settings` (settings.py:304) | yok | yok | kapsam dışı: ayar yazımı Python'da kalır; iz T7 |
| `_backup_if_corrupt` (settings.py:316) | settings.rs::backup_if_corrupt, fsutil.rs::write_corrupt_copy | parity_store.rs::sha256_and_corrupt_backup_match_python | EKSİK: test yok (dosya yok durumu) |
| `_DICT_ONLY_KEYS` (settings.py:349) | yok | yok | kapsam dışı: yalnız yama yazımında kullanılır; iz T7 |
| `_save_settings_locked` (settings.py:352) | yok | yok | kapsam dışı: ayar yazımı Python'da kalır; iz T7 |
| `resolved_binary` (settings.py:442) | settings_read.rs::Settings::resolved_binary, which | parity_settings.rs::settings_readers_match_python | tamam |
| `_KNOWN_BINARY_PATHS` (settings.py:466) | settings_read.rs::known_binary_paths | parity_settings.rs::defaults_lists_match_python | tamam |
| `default_model_for` (settings.py:478) | yok | yok | EKSİK: kod yok (sağlayıcı nesnesi ister; rs/prov'a devri cops kararı) |
| `default_effort_for` (settings.py:504) | yok | yok | EKSİK: kod yok (sağlayıcı nesnesi ister; rs/prov'a devri cops kararı) |
| `resolved_model_for` (settings.py:513) | yok | yok | EKSİK: kod yok (sağlayıcı nesnesi ister; rs/prov'a devri cops kararı) |
| `byok_env_for` (settings.py:532) | settings_read.rs::Settings::byok_env_for | parity_settings.rs::settings_readers_match_python | tamam |
| `ucli_limit_overrides` (settings.py:555) | settings_read.rs::Settings::ucli_limit_overrides | parity_settings.rs::settings_readers_match_python | tamam |
| `USAGE_WARN_DEFAULTS` (settings.py:578) | settings_read.rs::USAGE_WARN_DEFAULTS | parity_settings.rs::defaults_lists_match_python | tamam |
| `ucli_usage_warn_thresholds` (settings.py:581) | settings_read.rs::Settings::ucli_usage_warn_thresholds | parity_settings.rs::settings_readers_match_python | EKSİK: test yok (sözlük olmayan blok) |
| `routing_guidance_enabled` (settings.py:601) | settings.rs::Settings::routing_guidance_enabled | parity_settings.rs::settings_readers_match_python | tamam |
| `tunnel_watch_enabled` (settings.py:608) | settings.rs::Settings::tunnel_watch_enabled | parity_settings.rs::settings_readers_match_python | tamam |
| `_REASONING_LEVELS` (settings.py:615) | settings_read.rs::UCLI_REASONING_LEVELS | parity_settings.rs::settings_readers_match_python | tamam |
| `ucli_reasoning_mode` (settings.py:618) | settings_read.rs::Settings::ucli_reasoning_mode | parity_settings.rs::settings_readers_match_python | EKSİK: test yok (tanınmayan değerin `auto` olması) |
| `_ON_WORDS` (settings.py:632) | settings_read.rs::ON_WORDS | parity_settings.rs::defaults_lists_match_python | tamam |
| `UCLI_STREAM_DEFAULT` (settings.py:637) | settings_read.rs::UCLI_STREAM_DEFAULT | parity_settings.rs::defaults_lists_match_python | tamam |
| `ucli_stream_enabled` (settings.py:640) | settings_read.rs::Settings::ucli_stream_enabled | parity_settings.rs::settings_readers_match_python | tamam |
| `UCLI_SHOW_REASONING_DEFAULT` (settings.py:655) | settings_read.rs::UCLI_SHOW_REASONING_DEFAULT | parity_settings.rs::defaults_lists_match_python | tamam |
| `ucli_show_reasoning_enabled` (settings.py:658) | settings_read.rs::Settings::ucli_show_reasoning_enabled | parity_settings.rs::settings_readers_match_python | tamam |
| `UCLI_STATE_DIR_DEFAULT` (settings.py:674) | settings_read.rs::UCLI_STATE_DIR_DEFAULT | parity_settings.rs::defaults_lists_match_python | tamam |
| `ucli_state_dir_enabled` (settings.py:677) | settings_read.rs::Settings::ucli_state_dir_enabled | parity_settings.rs::settings_readers_match_python | tamam |
| `_HOST_RE` (settings.py:696) | settings_read.rs::valid_host | parity_settings.rs::settings_readers_match_python (kısmi) | EKSİK: test yok (63 ve 253 uzunluk sınırı, tek etiket) |
| `_MAX_FETCH_DOMAINS` (settings.py:697) | settings_read.rs::MAX_FETCH_DOMAINS | parity_settings.rs::defaults_lists_match_python | tamam |
| `_valid_http_url` (settings.py:700) | settings_read.rs::valid_http_url | settings_read.rs::url_rules; parity_settings.rs::unicode_tables_match_python, settings_readers_match_python | tamam |
| `_OFF_WORDS` (settings.py:713) | settings.rs::OFF_WORDS | parity.rs::constants_match_python | tamam |
| `UZAKGOZ_DEFAULT_DIR` (settings.py:716) | settings_read.rs::UZAKGOZ_DEFAULT_DIR | parity_settings.rs::defaults_lists_match_python | tamam |
| `_daemon_config` (settings.py:719) | settings_read.rs::Settings::daemon_config | parity_settings.rs::settings_readers_match_python | tamam |
| `uzakgoz_config` (settings.py:742) | settings_read.rs::Settings::uzakgoz_config | parity_settings.rs::settings_readers_match_python | tamam |
| `DERBENT_DEFAULT_DIR` (settings.py:747) | settings_read.rs::DERBENT_DEFAULT_DIR | parity_settings.rs::defaults_lists_match_python | tamam |
| `derbent_config` (settings.py:750) | settings_read.rs::Settings::derbent_config | parity_settings.rs::settings_readers_match_python | tamam |
| `reader_config` (settings.py:756) | settings_read.rs::Settings::reader_config | parity_settings.rs::settings_readers_match_python | tamam |
| `DEFAULT_UCLI_SERVICES` (settings.py:769) | settings_read.rs::default_ucli_services, default_ucli_services.json | parity_settings.rs::defaults_lists_match_python | tamam |
| `UCLI_REASONING_LEVELS` (settings.py:784) | settings_read.rs::UCLI_REASONING_LEVELS | parity_settings.rs::defaults_lists_match_python | tamam |
| `_SVC_ID_RE` (settings.py:785) | settings_read.rs::normalize_ucli_services (id_ok) | parity_settings.rs::settings_readers_match_python (kısmi) | EKSİK: test yok (2 ve 20 uzunluk sınırı) |
| `_SVC_ENV_RE` (settings.py:786) | settings_read.rs::normalize_ucli_services (env_ok) | yok | EKSİK: test yok (yalnız env'i geçersiz olan durum yok) |
| `normalize_ucli_services` (settings.py:789) | settings_read.rs::normalize_ucli_services | parity_settings.rs::settings_readers_match_python (kısmi) | EKSİK: test yok (env reddi, id/env uzunluk sınırları, 60 model ve 20 effort tavanı) |
| `ucli_services` (settings.py:828) | settings_read.rs::Settings::ucli_services | parity_settings.rs::settings_readers_match_python | tamam |
| `ucli_cost_config` (settings.py:832) | settings_read.rs::Settings::ucli_cost_config | parity_settings.rs::settings_readers_match_python | EKSİK: test yok (sözlük olmayan blok) |
| `ucli_script_mode` (settings.py:858) | settings_read.rs::Settings::ucli_script_mode | parity_settings.rs::settings_readers_match_python | EKSİK: test yok (`read` değeri; yalnız `full` ve geçersizler sınanıyor) |
| `ucli_endpoint` (settings.py:868) | settings_read.rs::Settings::ucli_endpoint | parity_settings.rs::settings_readers_match_python | tamam |
| `ucli_web_config` (settings.py:875) | settings_read.rs::Settings::ucli_web_config | parity_settings.rs::settings_readers_match_python | EKSİK: test yok (64 alan adı tavanı; sözlük olmayan blok; flavor'sız geçerli adres; adresin kırpılması) |
| `steward_ids` (settings.py:911) | yok | yok | EKSİK: kod yok (ayar okuma; rs/stew'a devri cops kararı) |
| `steward_config` (settings.py:920) | yok | yok | EKSİK: kod yok (ayar okuma, kimlik birleştirme ve sınırlama; rs/stew'a devri cops kararı) |

#### `py/claudeops/roster.py` (5)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `RosterEntry` (roster.py:10) | roster.rs::RosterEntry | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_parse_tsv` (roster.py:17) | roster.rs::parse_active, read_text | parity.rs::roster_reads_and_writes_match_python | tamam |
| `read_models` (roster.py:32) | roster.rs::Roster::models | parity.rs::roster_reads_and_writes_match_python | tamam |
| `read_roster` (roster.py:41) | roster.rs::Roster::entries | parity.rs::roster_reads_and_writes_match_python | tamam |
| `roster_by_name` (roster.py:58) | roster.rs::Roster::by_name | parity_instances.rs::roster_by_name_and_blueprint_cwds_match_python | tamam |

#### `py/claudeops/instances.py` (29)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `INSTANCES_JSON` (instances.py:22) | paths.rs::StateDir::instances_json | parity.rs::instances_match_python | tamam |
| `_LOCK_PATH` (instances.py:23) | instances.rs::Instances::try_mutate (`instances.json.lock`) | parity.rs::concurrent_writers_lose_nothing; lock_e2e.rs::roster_and_instances_locks_shared | tamam |
| `_VERSION` (instances.py:24) | instances.rs::VERSION | parity.rs::instances_match_python | tamam |
| `AUTO_NAME_RE` (instances.py:27) | instances.rs::auto_name | parity_instances.rs::name_patterns_and_created_at_match_python | tamam |
| `DERIVED_NAME_RE` (instances.py:29) | instances.rs::derived_name | parity_instances.rs::name_patterns_and_created_at_match_python | tamam |
| `DIAG_PREFIX` (instances.py:31) | instances.rs::DIAG_PREFIX | yok | EKSİK: test yok (değer Python'la karşılaştırılmıyor) |
| `InstancesCorrupt` (instances.py:34) | instances.rs::InstancesError::Corrupt | parity_instances.rs::bad_encoding_files_not_overwritten | tamam |
| `_cache_key` (instances.py:38) | statedocs.rs::State.reader_cache (FileKey) | parity_instances.rs::load_cache_semantics | tamam |
| `_cache` (instances.py:39) | statedocs.rs::State.reader_cache | parity_instances.rs::load_cache_semantics | tamam |
| `read_strict` (instances.py:42) | instances.rs::Instances::read_strict, read_checked | parity.rs::instances_match_python; parity_instances.rs::bad_encoding_files_not_overwritten | tamam |
| `load_instances` (instances.py:58) | instances.rs::Instances::load | parity.rs::instances_match_python; parity_instances.rs::load_cache_semantics | tamam |
| `get_instance` (instances.py:79) | instances.rs::Instances::get | parity.rs::register_project_across_languages | tamam |
| `_locked` (instances.py:84) | fsutil.rs::FileLock::blocking | lock_e2e.rs::roster_and_instances_locks_shared | tamam |
| `_mutate` (instances.py:94) | instances.rs::Instances::try_mutate, mutate | parity.rs::instances_match_python, concurrent_writers_lose_nothing | tamam |
| `record_instance` (instances.py:108) | instances.rs::Instances::record | parity.rs::instances_match_python | tamam |
| `record_instance._apply` (instances.py:116) | instances.rs::Instances::record (kapanış) | parity.rs::instances_match_python | tamam |
| `mark_started` (instances.py:135) | instances.rs::Instances::mark_started | parity.rs::instances_match_python | EKSİK: test yok (aynı cli ve seçeneksiz başlatmada `cli_opts` korunur) |
| `mark_started._apply` (instances.py:140) | instances.rs::Instances::mark_started (kapanış) | parity.rs::instances_match_python | EKSİK: test yok (aynı cli ve seçeneksiz başlatmada `cli_opts` korunur) |
| `add_missing` (instances.py:155) | instances.rs::Instances::add_missing | parity.rs::instances_match_python | tamam |
| `add_missing._apply` (instances.py:158) | instances.rs::Instances::add_missing (kapanış) | parity.rs::instances_match_python | tamam |
| `mark_models_gone` (instances.py:169) | instances.rs::Instances::mark_models_gone | parity_instances.rs::mark_models_gone_matches_python | tamam |
| `mark_models_gone.fn` (instances.py:172) | instances.rs::Instances::mark_models_gone (kapanış) | parity_instances.rs::mark_models_gone_matches_python | tamam |
| `forget_instance` (instances.py:192) | instances.rs::Instances::forget | parity.rs::instances_match_python | tamam |
| `forget_instance._apply` (instances.py:195) | instances.rs::Instances::forget (kapanış) | parity.rs::instances_match_python | tamam |
| `rename_blueprint` (instances.py:205) | instances.rs::Instances::rename_blueprint | parity.rs::instances_match_python | tamam |
| `rename_blueprint._apply` (instances.py:206) | instances.rs::Instances::rename_blueprint (kapanış) | parity.rs::instances_match_python | tamam |
| `_norm` (instances.py:217) | instances.rs::infer_blueprint (norm) | parity.rs::name_helpers_match_python | tamam |
| `infer_blueprint` (instances.py:221) | instances.rs::infer_blueprint | parity.rs::name_helpers_match_python | tamam |
| `created_at_from_name` (instances.py:238) | instances.rs::created_at_from_name | parity_instances.rs::name_patterns_and_created_at_match_python; tz.rs::midnight_dst_matches_python | tamam |

#### `py/claudeops/atomic_json.py` (13)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `_existing_mode` (atomic_json.py:32) | fsutil.rs::atomic_write_json, atomic_write_text (kip süzgeci) | parity_store.rs::atomic_write_text_matches_python | EKSİK: test yok (JSON yazıcıda var olan iznin korunması) |
| `_fsync_dir` (atomic_json.py:44) | fsutil.rs::fsync_dir | yok | EKSİK: test yok (fsync, rename, dizin fsync sırası) |
| `_open_tmp` (atomic_json.py:58) | fsutil.rs::write_replace | parity_store.rs::atomic_write_text_matches_python (kısmi) | EKSİK: test yok (geçici adda sembolik bağ reddi; umask'ı aşan açık kip) |
| `atomic_write_json` (atomic_json.py:71) | fsutil.rs::atomic_write_json | parity.rs::statedocs_modes_with_python | EKSİK: test yok (var olan iznin korunması, kipsiz yeni dosya, hata sonrası temizlik) |
| `atomic_write_text` (atomic_json.py:101) | fsutil.rs::atomic_write_text | parity_store.rs::atomic_write_text_matches_python | EKSİK: test yok (hata sonrası temizlik, eşzamanlı yazım) |
| `LOCK_TIMEOUT_SECONDS` (atomic_json.py:124) | fsutil.rs::LOCK_TIMEOUT | yok | EKSİK: test yok (değer Python'la karşılaştırılmıyor) |
| `_LOCKS_GUARD` (atomic_json.py:125) | yok | yok | kapsam dışı: Python'un süreç içi kilit tablosunun koruyucusu; Rust'ta ortak tablo yok (iş parçacığı yerel kayıt ve ayrı fd flock); iz W0-a |
| `_THREAD_LOCKS` (atomic_json.py:126) | fsutil.rs::HELD ve fd başına flock | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `_HELD` (atomic_json.py:127) | fsutil.rs::HELD | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `_WARNED_LOCKS` (atomic_json.py:128) | yok | yok | EKSİK: kod yok (uyarı ve kilitsiz sürme yok, hata dönülür; sahip sorusu S1 ve S5 bekliyor) |
| `file_lock` (atomic_json.py:132) | fsutil.rs::FileLock::acquire, acquire_within | fsutil.rs::reentrant_same_thread_exclusive_across_threads, lock_symlink_refused; lock_e2e.rs::python_lock_blocks_rust_and_back | tamam |
| `roster_lock` (atomic_json.py:169) | fsutil.rs::FileLock::roster | lock_e2e.rs::roster_and_instances_locks_shared | tamam |
| `_file_lock_outer` (atomic_json.py:177) | fsutil.rs::FileLock::acquire_within | lock_e2e.rs::python_lock_blocks_rust_and_back; fsutil.rs::lock_symlink_refused | EKSİK: test yok (başkasının sahip olduğu ya da normal olmayan kilit dosyasında uid/tür reddi (yalnız sembolik bağ sınanıyor)) |

#### `py/claudeops/dbapi.py` (31)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `SQLITE` (dbapi.py:20) | yok (tek motor) | yok | kapsam dışı: motor seçimi sabiti; Rust yalnız SQLite; iz T9 |
| `POSTGRES` (dbapi.py:20) | yok | yok | kapsam dışı: Postgres yolu; iz T9 |
| `BUSY_TIMEOUT_MS` (dbapi.py:21) | store.rs::BUSY_TIMEOUT_MS | yok | EKSİK: test yok (değer Python'la karşılaştırılmıyor) |
| `VERSION_TABLE` (dbapi.py:22) | store.rs::version (`schema_version` metni) | yok | EKSİK: test yok (tablo sürümünün belirleyici olduğu durum) |
| `_MIGRATE_LOCK_KEY` (dbapi.py:23) | yok | yok | kapsam dışı: Postgres göç kilidi; iz T9 |
| `_WRITER_LOCK_KEY` (dbapi.py:24) | yok | yok | kapsam dışı: Postgres yazar kilidi; iz T9 |
| `DbError` (dbapi.py:27) | store.rs::StoreError | parity.rs::schema_mismatch_never_writes | tamam |
| `backend_of` (dbapi.py:31) | store.rs::sqlite_path_from_url | parity.rs::schema_mismatch_never_writes (yalnız postgresql) | EKSİK: test yok (`sqlite:` kabulü, tanınmayan şema reddi) |
| `sqlite_path` (dbapi.py:40) | store.rs::sqlite_path_from_url | yok | EKSİK: test yok |
| `translate` (dbapi.py:48) | yok | yok | kapsam dışı: Postgres yer tutucu çevirisi; iz T9 |
| `ddl` (dbapi.py:75) | yok | yok | kapsam dışı: göç metni belirteçleri; Rust göç yapmaz; iz T6 |
| `split_statements` (dbapi.py:83) | yok | yok | kapsam dışı: göç deyim bölücüsü; Rust göç yapmaz; iz T6 |
| `Conn` (dbapi.py:123) | store.rs::Store (rusqlite Connection) | yok | kapsam dışı: iki motor soyutlaması; Rust rusqlite'ı doğrudan kullanır, davranışlar yöntem satırlarında; iz T9 |
| `Conn.__init__` (dbapi.py:126) | yok | yok | kapsam dışı: motor alanları (`pg`, `for_update`, `serialize_writes`); iz T9 |
| `Conn.execute` (dbapi.py:134) | yok | yok | kapsam dışı: `?` çevirili motor soyutlaması; rusqlite doğrudan; iz T9 |
| `Conn.executemany` (dbapi.py:142) | yok | yok | kapsam dışı: motor soyutlaması; rusqlite doğrudan; iz T9 |
| `Conn.insert` (dbapi.py:148) | store.rs::Store::append_log (last_insert_rowid) | parity_store.rs::log_functions_match_python | tamam |
| `Conn.begin_write` (dbapi.py:155) | store.rs::Store::write (Immediate) | parity.rs::concurrent_writers_lose_nothing | tamam |
| `Conn.commit` (dbapi.py:160) | store.rs::Store::write | parity.rs::db_roundtrip_both_ways | tamam |
| `Conn.rollback` (dbapi.py:163) | store.rs::Store::write (Transaction Drop) | yok | EKSİK: test yok (işlem ortasında hata sonrası geri alma) |
| `Conn.xact_lock` (dbapi.py:166) | yok | yok | kapsam dışı: Postgres advisory kilidi (SQLite'ta işlevsiz); iz T9 |
| `Conn.close` (dbapi.py:171) | store.rs::Store (Drop) | fd_leak.rs::no_fd_leak | tamam |
| `connect` (dbapi.py:175) | store.rs::Store::open | parity.rs::db_roundtrip_both_ways (açma) | EKSİK: test yok (WAL ve `synchronous=NORMAL` ayarı doğrulanmıyor) |
| `Tx` (dbapi.py:199) | store.rs::Store::write | parity.rs::concurrent_writers_lose_nothing | tamam |
| `Tx.__init__` (dbapi.py:202) | store.rs::Store::write | parity.rs::concurrent_writers_lose_nothing | tamam |
| `Tx.__enter__` (dbapi.py:205) | store.rs::Store::write | parity.rs::concurrent_writers_lose_nothing | tamam |
| `Tx.__exit__` (dbapi.py:209) | store.rs::Store::write | yok (yalnız commit yolu) | EKSİK: test yok (hata yolunda ROLLBACK) |
| `schema_version` (dbapi.py:217) | store.rs::version, check | parity.rs::schema_mismatch_never_writes (yalnız user_version) | EKSİK: test yok (`schema_version` tablosu yolu ve tablosuz eski DB) |
| `_entry` (dbapi.py:232) | yok | yok | kapsam dışı: göç girdisi seçimi; iz T6 |
| `migrate` (dbapi.py:239) | yok | yok | kapsam dışı: Rust göç yapmaz (karar); iz T6 |
| `default_url` (dbapi.py:266) | statedocs.rs::StateDocs::new (`CLAUDEOPS_DB_URL`) | yok | EKSİK: test yok (ortamdan okuma) |

#### `py/claudeops/commands/web.py` (23)

| Python adı (dosya:satır) | Rust karşılığı | Parite / birim testi | Durum |
|---|---|---|---|
| `_read_tsv_raw` (commands/web.py:617) | roster.rs::Roster::raw_rows, parse_raw | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_fleet_status` (commands/web.py:645) | roster.rs::Roster::fleet_status | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_all_known_names` (commands/web.py:686) | roster.rs::known_names (süreç adları hariç) | yok | EKSİK: test yok; kod kısmi (canlı süreç `name`/`base` kümesi yok, T1/T4 girdisi) |
| `_generate_new_chat_name` (commands/web.py:697) | yok | yok | kapsam dışı: yeni sohbet adı üretimi süreç taramasına bağlı (`/api/new-chat`); iz T4 |
| `_atomic_write_text` (commands/web.py:715) | fsutil.rs::atomic_write_tsv, roster.rs::RosterGuard::write | parity.rs::roster_reads_and_writes_match_python (bayt, izin, gölge) | tamam |
| `_first_rows` (commands/web.py:750) | roster.rs::first_rows | parity.rs::roster_reads_and_writes_match_python (yinelenen ad) | EKSİK: test yok (`name` başlık satırının dışlanması; models örneğinde başlık yok) |
| `_append_tsv_line` (commands/web.py:759) | roster.rs::RosterGuard::append | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_append_tsv_line_unlocked` (commands/web.py:765) | roster.rs::RosterGuard::append | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_NAME_VALID_RE` (commands/web.py:777) | roster.rs::valid_project_name | parity.rs::register_project_across_languages | tamam |
| `_register_project` (commands/web.py:780) | roster.rs::Roster::register_project | parity.rs::register_project_across_languages; parity_instances.rs::register_model_newline_documented_divergence | EKSİK: test yok (`cwd_bad_chars` dalı; diğer redler ve başarı sınanıyor). S3 sapması belgeli |
| `_edit_project` (commands/web.py:817) | yok (yazım ilkelleri RosterGuard::replace, Instances::rename_blueprint) | yok | kapsam dışı: `/api/edit` uç eylemi, süreç taraması ister; iz T4 |
| `_blueprint_cwds` (commands/web.py:881) | roster.rs::blueprint_cwds | parity_instances.rs::roster_by_name_and_blueprint_cwds_match_python | tamam |
| `_roster_lock` (commands/web.py:985) | roster.rs::Roster::lock | lock_e2e.rs::roster_and_instances_locks_shared | tamam |
| `_toggle_comment` (commands/web.py:992) | roster.rs::RosterGuard::set_active | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_find_tsv_line` (commands/web.py:1001) | roster.rs::find_line | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_toggle_comment_unlocked` (commands/web.py:1014) | roster.rs::RosterGuard::set_active, edit_line | parity.rs::roster_reads_and_writes_match_python | EKSİK: test yok (olmayan dosyada false) |
| `_replace_tsv_line` (commands/web.py:1029) | roster.rs::RosterGuard::replace | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_replace_tsv_line_unlocked` (commands/web.py:1038) | roster.rs::RosterGuard::replace, edit_line | parity.rs::roster_reads_and_writes_match_python | tamam |
| `_retire` (commands/web.py:3162) | yok | yok | kapsam dışı: süreç durdurma ve TSV yazımı uç eylemi; iz T4 |
| `_close_project` (commands/web.py:3193) | yok | yok | kapsam dışı: süreç durdurma ve TSV yazımı uç eylemi; iz T4 |
| `_adopt` (commands/web.py:3935) | yok | yok | kapsam dışı: `/api/adopt` uç eylemi (spawn); iz T4 |
| `_reactivate_and_start` (commands/web.py:4055) | yok | yok | kapsam dışı: yeniden etkinleştirip başlatma uç eylemi; iz T4 |
| `_snapshot_resume` (commands/web.py:4233) | yok | yok | kapsam dışı: anlık görüntüden devam uç eylemi (spawn); iz T4 |

### Python testleri: listelenen dosyalar (her `test_*` metodu)

| Python testi (dosya::Sınıf::metot) | Rust testi | Durum |
|---|---|---|
| `test_agy_sids_store.py::AgySidsStoreTest::test_db_ready` | parity.rs::constants_match_python | tamam |
| `test_agy_sids_store.py::AgySidsStoreTest::test_remember_writes_db_and_mirror` | yok | kapsam dışı: `agy_provider` kayıt işlevleri (genel db kipi ve ayna `parity.rs::statedocs_modes_with_python`ta); iz W1-pre sağlayıcı |
| `test_agy_sids_store.py::AgySidsStoreTest::test_unchanged_value_does_not_rewrite` | yok | kapsam dışı: `agy_provider` mantığı; iz W1-pre sağlayıcı |
| `test_agy_sids_store.py::AgySidsStoreTest::test_concurrent_remembers_lose_nothing` | yok | kapsam dışı: `agy_provider` kilitli yazımı; iz W1-pre sağlayıcı |
| `test_atomic_json_fd_dirsync.py::DirFsyncTest::test_directory_is_fsynced_after_replace` | yok | EKSİK: test yok (fsync sırası) |
| `test_atomic_json_fd_dirsync.py::FdopenLeakTest::test_fd_closed_when_fdopen_fails` | yok | EKSİK: test yok (yazım hatasında geçici dosya ve tanıtıcı kalmaması) |
| `test_atomic_json_lock.py::TestFileLockFallback::test_symlink_lock_warns_once_and_still_runs` | fsutil.rs::lock_symlink_refused (yalnız hedef yaratılmaz) | EKSİK: kod yok (uyarıp kilitsiz sürme; S5) |
| `test_atomic_json_lock.py::TestFileLockFallback::test_normal_lock_no_warning` | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `test_atomic_json_lock.py::TestAtomicWriteTmp::test_utf8_with_mode_and_stale_symlink_tmp_not_followed` | yok | EKSİK: test yok (bayat sembolik bağlı geçici ad) |
| `test_atomic_json_lock.py::TestAtomicWriteTmp::test_default_mode_respects_umask` | parity_store.rs::atomic_write_text_matches_python (yalnız metin yazıcı) | EKSİK: test yok (JSON yazıcıda kipsiz yeni dosya ve umask) |
| `test_atomic_json_lock_timeout.py::LockTimeout::test_times_out_instead_of_hanging` | lock_e2e.rs::python_lock_blocks_rust_and_back (süre sınırı) | EKSİK: kod yok (zaman aşımından sonra sürme; Rust hata döner, S1) |
| `test_atomic_json_lock_timeout.py::LockTimeout::test_normal_acquire` | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `test_atomic_json_mode.py::AtomicModeTest::test_existing_mode_preserved_text` | parity_store.rs::atomic_write_text_matches_python | tamam |
| `test_atomic_json_mode.py::AtomicModeTest::test_existing_mode_preserved_json` | yok | EKSİK: test yok |
| `test_atomic_json_mode.py::AtomicModeTest::test_explicit_mode_beats_umask` | yok | EKSİK: test yok |
| `test_atomic_json_mode.py::AtomicModeTest::test_no_tmp_left` | parity_store.rs::atomic_write_text_matches_python | tamam |
| `test_atomic_json_thread_locks_bounded.py::ThreadLocksBoundedTest::test_entries_removed_after_use` | fsutil.rs::reentrant_same_thread_exclusive_across_threads (HELD boşalır) | tamam |
| `test_atomic_json_thread_locks_bounded.py::ThreadLocksBoundedTest::test_nested_same_path_ok_and_cleaned` | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `test_atomic_json_thread_locks_bounded.py::ThreadLocksBoundedTest::test_exception_still_cleans` | yok | EKSİK: test yok (panik sırasında kilidin bırakılması) |
| `test_atomic_json_thread_locks_bounded.py::ThreadLocksBoundedTest::test_unusable_lock_file_warns_once_per_path` | yok | EKSİK: kod yok (uyarı ve kilitsiz sürme; S5) |
| `test_atomic_json_thread_locks_bounded.py::ThreadLocksBoundedTest::test_concurrent_threads_stay_mutually_exclusive` | fsutil.rs::reentrant_same_thread_exclusive_across_threads; parity.rs::concurrent_writers_lose_nothing | tamam |
| `test_atomic_text_concurrent.py::AtomicTextTest::test_concurrent_writers_leave_one_complete_file_and_no_tmp` | yok | EKSİK: test yok (eşzamanlı `atomic_write_text`) |
| `test_atomic_text_concurrent.py::AtomicTextTest::test_mode_600_and_unicode` | parity_store.rs::atomic_write_text_matches_python | tamam |
| `test_atomic_write_text_fsync.py::AtomicWriteFsync::test_fsync_before_replace_and_dir_after` | yok | EKSİK: test yok (TSV yazıcıda fsync sırası) |
| `test_bad_encoding_state_files.py::BadBytes::test_instances` | parity_instances.rs::bad_encoding_files_not_overwritten | tamam |
| `test_bad_encoding_state_files.py::BadBytes::test_hosts` | yok | kapsam dışı: `hosts.py` okuyucusu; iz T5 |
| `test_bad_encoding_state_files.py::SaveHostKeepsUnknownFields::test_unknown_field_survives_upsert_and_dns_outside_lock` | yok | kapsam dışı: `hosts.save_host`; iz T5 |
| `test_claude_models_store.py::ClaudeModelsStoreTest::test_is_db_ready` | parity.rs::constants_match_python | tamam |
| `test_claude_models_store.py::ClaudeModelsStoreTest::test_write_goes_to_db_and_mirror_and_reads_from_db` | yok | kapsam dışı: claude sağlayıcısı ve `model_freshness` (genel db kipi ayrıca sınanıyor); iz W1-pre sağlayıcı |
| `test_claude_models_store.py::ClaudeModelsStoreTest::test_db_wins_over_corrupt_or_missing_file` | yok | kapsam dışı: claude sağlayıcısının model listesi; iz W1-pre sağlayıcı |
| `test_claude_models_store.py::ClaudeModelsStoreTest::test_fallback_to_hardcoded_when_empty` | yok | kapsam dışı: claude sağlayıcısının yedek listesi; iz W1-pre sağlayıcı |
| `test_core_projects_roster.py::T::test_roster_projects_included_with_cwd` | yok | kapsam dışı: `extensions.core_projects` (eklenti kancası); iz T9 |
| `test_dbapi.py::Translate::test_placeholders` | yok | kapsam dışı: Postgres çevirisi; iz T9 |
| `test_dbapi.py::Translate::test_string_literals_and_percent` | yok | kapsam dışı: Postgres çevirisi; iz T9 |
| `test_dbapi.py::Translate::test_backend_of` | parity.rs::schema_mismatch_never_writes (yalnız postgresql) | EKSİK: test yok (`sqlite:` yolu, tanınmayan şema) |
| `test_dbapi.py::Ddl::test_sqlite_ddl_identical_to_legacy` | yok | kapsam dışı: göç metni; iz T6 |
| `test_dbapi.py::Ddl::test_pg_ddl` | yok | kapsam dışı: Postgres göç metni; iz T9 |
| `test_dbapi.py::Ddl::test_split_pg_dollar_quote` | yok | kapsam dışı: Postgres deyim bölücü; iz T9 |
| `test_dbapi.py::LegacyUserVersion::test_old_db_without_schema_version_table` | yok | EKSİK: test yok (`schema_version` tablosu olmayan DB'nin Rust'ta açılması) |
| `test_dbapi.py::LegacyUserVersion::test_newer_user_version_still_refused` | parity.rs::schema_mismatch_never_writes | tamam |
| `test_dbapi.py::FakePsycopg::test_pg_statements` | yok | kapsam dışı: Postgres SQL'i; iz T9 |
| `test_dbapi.py::FakePsycopg::test_pg_migrate_uses_version_table_and_lock` | yok | kapsam dışı: Postgres göçü; iz T9 |
| `test_dbapi.py::FakePsycopg::test_missing_psycopg2` | yok | kapsam dışı: Postgres sürücüsü; iz T9 |
| `test_dbapi.py::MigrateEntries::test_per_backend_entry_and_own_version_table` | yok | kapsam dışı: göç; iz T6 |
| `test_dbapi.py::MigrateEntries::test_randhex_token` | yok | kapsam dışı: göç belirteci; iz T6 |
| `test_dbapi.py::SqliteStoreStillWorks::test_store_roundtrip_with_layer` | parity.rs::db_roundtrip_both_ways; parity_store.rs::log_functions_match_python | tamam |
| `test_dbapi.py::RealPostgres::test_store_on_pg` | yok | kapsam dışı: gerçek Postgres; iz T9 |
| `test_orch_store_db.py::OrchStoreDbTest::test_prefix_is_db_ready` | parity.rs::constants_match_python | tamam |
| `test_orch_store_db.py::OrchStoreDbTest::test_db_mode_load_from_db_when_file_missing_or_stale` | yok | kapsam dışı: `orch_store` okuyucusu (genel db kipi ayrıca sınanıyor); iz T7 |
| `test_orch_store_db.py::OrchStoreDbTest::test_dual_mode_file_wins` | yok | kapsam dışı: `orch_store` taslağı; iz T7 |
| `test_orch_store_db.py::OrchStoreDbTest::test_list_runs_uses_mirror_in_db_mode` | yok | kapsam dışı: `orch_store.list_runs`; iz T7 |
| `test_orch_store_db.py::OrchStoreDbTest::test_corrupt_file_in_db_mode_returns_db` | yok | kapsam dışı: `orch_store` okuyucusu; iz T7 |
| `test_p2_atomic_writes.py::AtomicWriteTextTest::test_writes_and_leaves_no_tmp` | parity_store.rs::atomic_write_text_matches_python | tamam |
| `test_p2_atomic_writes.py::AtomicWriteTextTest::test_tmp_name_is_per_thread` | yok | EKSİK: test yok (geçici adın benzersizliği) |
| `test_p2_atomic_writes.py::AtomicWriteTextTest::test_concurrent_writers_never_raise` | yok | EKSİK: test yok (eşzamanlı `atomic_write_text`) |
| `test_p2_atomic_writes.py::AtomicWriteTextTest::test_failed_write_removes_tmp` | yok | EKSİK: test yok |
| `test_p2_atomic_writes.py::WriteLessonTest::test_concurrent_lessons_no_tmp_race_and_no_stale_tmp` | yok | kapsam dışı: `web_review` ders yazımı; iz T8 |
| `test_p2_atomic_writes.py::CloseModelsTest::test_comment_and_restore` | yok | kapsam dışı: `close.py` (`# CLOSED` biçimi, `cops close`), bu turun modül listesinde değil; iz T6 |
| `test_p2_atomic_writes.py::CloseModelsTest::test_dry_run_and_missing_do_not_write` | yok | kapsam dışı: `cops close`; iz T6 |
| `test_p2_atomic_writes.py::CloseModelsTest::test_missing_file_is_notfound` | yok | kapsam dışı: `cops close`; iz T6 |
| `test_p2_atomic_writes.py::CloseModelsTest::test_concurrent_closes_lose_no_update` | yok | kapsam dışı: `cops close`; iz T6 |
| `test_p2_atomic_writes.py::FilesWriteTextFsyncTest::test_fsync_before_replace` | yok | kapsam dışı: `files.write_text`; iz T3 |
| `test_p2_atomic_writes.py::QuotaTest::test_parse_reset_invalid_day_returns_none` | yok | kapsam dışı: `steward_quota`; iz T10 |
| `test_p2_atomic_writes.py::QuotaTest::test_parse_reset_leap_day_rollover_does_not_raise` | yok | kapsam dışı: `steward_quota`; iz T10 |
| `test_p2_atomic_writes.py::QuotaTest::test_parse_reset_normal` | yok | kapsam dışı: `steward_quota`; iz T10 |
| `test_p2_atomic_writes.py::QuotaTest::test_num_rejects_nan_inf` | yok | kapsam dışı: `steward_quota`; iz T10 |
| `test_p2_atomic_writes.py::QuotaTest::test_decide_nan_limit_falls_back_to_default_final` | yok | kapsam dışı: `steward_quota`; iz T10 |
| `test_paths_isolation.py::CustomRunnerTest::test_script_that_loaded_unittest_is_isolated` | yok | kapsam dışı: Python koşucu algısı (`sys.modules`); Rust karşılığı derleme biçiminden; iz W0-a |
| `test_paths_isolation.py::CustomRunnerTest::test_script_that_loaded_a_repo_test_module_is_isolated` | yok | kapsam dışı: Python koşucu algısı; iz W0-a |
| `test_paths_isolation.py::CustomRunnerTest::test_plain_script_uses_real_dir` | paths.rs::rules, test_binary_detection | tamam |
| `test_paths_isolation.py::IsolationTest::test_state_dir_is_not_live_under_runner` | paths.rs::under_cargo_test_never_real_dir (dizin) | EKSİK: test yok (alt sürece ortam devri) |
| `test_paths_isolation.py::IsolationTest::test_runner_detection` | paths.rs::test_binary_detection | EKSİK: test yok (`CLAUDEOPS_TEST_REAL_DIR=1`) |
| `test_proc_stat_parse.py::ProcStatTest::test_plain` | paths.rs::parse_proc_stat_rules | tamam |
| `test_proc_stat_parse.py::ProcStatTest::test_comm_with_space_and_paren` | paths.rs::parse_proc_stat_rules; parity_settings.rs::expanduser_and_proc_match_python | tamam |
| `test_proc_stat_parse.py::ProcStatTest::test_starttime_index` | parity_settings.rs::expanduser_and_proc_match_python (tüm alan listesi) | tamam |
| `test_proc_stat_parse.py::ProcStatTest::test_no_paren_raises` | paths.rs::parse_proc_stat_rules | tamam |
| `test_proc_stat_parse.py::ProcStatTest::test_own_ppid` | yok | EKSİK: test yok (`proc_ppid`) |
| `test_proc_stat_parse.py::ProcStatTest::test_no_inline_copies` | yok | kapsam dışı: Python kaynak taraması (kopya ayrıştırıcı yasağı); iz T1 |
| `test_review_store.py::PureTest::test_parse_remote` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::PureTest::test_dest_guard_fails_closed_on_check_ignore_error` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::PureTest::test_dest_guard_localized_not_a_repo_is_rejected_not_open` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::PureTest::test_dest_guard` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::PureTest::test_unrecognized_remote_makes_repo_unknown_not_private` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::PureTest::test_visibility_any_public_wins_and_cache` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_dry_run_lists_without_touching_anything` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_commit_refuses_when_prv_remote_is_public_or_unverifiable` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_gitdir_visibility_classifies_remotes_fresh` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_visibility_cache_is_bounded` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_glob_chars_in_filename_are_literal` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_junk_files_skipped` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_secret_written_between_scan_and_add_is_unstaged` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_saved_page_files_dirs_are_skipped` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_act_commits_only_reviews_to_prv_and_pushes_both` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_unpushed_local_commit_is_pushed_on_next_run` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_no_commit_yet_and_nothing_new_is_noop` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_act_works_from_foreign_cwd` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::CommitTest::test_refuses_main_repo_git_dir` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::StoreCommitGateTest::test_off_dry_first_then_act_daily` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::ParseRemotePortTest::test_ssh_port_and_alt_hosts` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_review_store.py::ParseRemotePortTest::test_unknown_not_cached` | yok | kapsam dışı: `review_store` (bulgu deposu, görünürlük koruması, -prv commit); iz T8 |
| `test_settings_cache.py::Cache::test_unchanged_file_parsed_once` | yok | EKSİK: test yok (önbellek isabeti) |
| `test_settings_cache.py::Cache::test_change_is_seen` | parity.rs::settings_match_python (aynı okuyucu, değişen dosya) | tamam |
| `test_settings_cache.py::Cache::test_callers_get_copies` | yok | kapsam dışı: Rust `Arc<Settings>` döner ve değiştirme yöntemi yoktur; iz W0-a |
| `test_settings_cache.py::Cache::test_missing_file_defaults_and_save_roundtrip` | parity.rs::settings_match_python (yalnız yok dosya) | kapsam dışı: `save_settings` turu; iz T7 |
| `test_settings_corrupt_backup.py::CorruptBackupTest::test_corrupt_file_backed_up_before_write` | parity_store.rs::sha256_and_corrupt_backup_match_python (yedek kararı) | kapsam dışı: yazım öncesi sıra ve tanı kaydı `save_settings` yolunda; iz T7 |
| `test_settings_corrupt_backup.py::CorruptBackupTest::test_valid_and_missing_file_not_backed_up` | parity_store.rs::sha256_and_corrupt_backup_match_python (geçerli dosya) | EKSİK: test yok (dosya yok durumu) |
| `test_settings_corrupt_backup.py::CorruptBackupTest::test_non_object_json_is_corrupt` | parity_store.rs::sha256_and_corrupt_backup_match_python | tamam |
| `test_settings_zero_and_test_cmd.py::SettingsZeroTest::test_numeric_zero_kept_empty_string_removes` | yok | kapsam dışı: yama yazımı; iz T7 |
| `test_settings_zero_and_test_cmd.py::SettingsZeroTest::test_false_still_off_and_bool_not_numeric` | yok | kapsam dışı: yama yazımı; iz T7 |
| `test_settings_zero_and_test_cmd.py::TestCmdEnvTest::test_pythonpath_has_py_root` | yok | kapsam dışı: `cops test`; iz T6 |
| `test_statedocs.py::StateDocsTests::test_files_mode_never_touches_db` | parity.rs::statedocs_modes_with_python | tamam |
| `test_statedocs.py::StateDocsTests::test_dual_writes_both_and_reads_db` | parity.rs::statedocs_modes_with_python (kısmi) | EKSİK: test yok (`file_truth=false`) |
| `test_statedocs.py::StateDocsTests::test_lazy_import_from_file` | parity_instances.rs::mode_transitions_match_python (yalnız db kipi) | EKSİK: test yok (dual kipte DB boşken tembel içe aktarma) |
| `test_statedocs.py::StateDocsTests::test_db_mode_db_is_truth_file_is_mirror` | parity.rs::statedocs_modes_with_python | tamam |
| `test_statedocs.py::StateDocsTests::test_db_mode_reader_mid_write_sees_db_no_drift` | parity_instances.rs::mode_transitions_match_python | tamam |
| `test_statedocs.py::StateDocsTests::test_db_write_failure_recovers_from_file_on_next_read` | parity.rs::db_transient_failure_defers_and_recovers | tamam |
| `test_statedocs.py::StateDocsTests::test_dual_db_write_failure_resyncs_on_next_read` | yok | EKSİK: test yok |
| `test_statedocs.py::StateDocsTests::test_steward_prefix_is_db_ready` | parity.rs::statedocs_modes_with_python, constants_match_python | tamam |
| `test_statedocs.py::StateDocsTests::test_db_failure_falls_back_to_file` | parity.rs::schema_mismatch_never_writes (dual yazım) | EKSİK: test yok (okumada dosyaya düşme); db kipinde kalıcı hatada yazmama bilinçli sapma |
| `test_statedocs.py::StateDocsTests::test_backend_from_settings_and_default` | parity.rs::backend_from_settings_file | tamam |
| `test_statedocs.py::StateDocsTests::test_outside_claudeops_dir_is_files_only` | parity.rs::statedocs_modes_with_python; parity_store.rs::mirror_log_and_on_corrupt_match_python | tamam |
| `test_statedocs.py::StateDocsTests::test_file_truth_dual_heals_drift_and_survives_hand_edit` | parity.rs::statedocs_modes_with_python (drift onarımı) | EKSİK: test yok (dosya silinince DB'den okuma) |
| `test_statedocs.py::StateDocsTests::test_first_import_is_not_logged_as_drift` | yok | EKSİK: test yok (günlük iletisi) |
| `test_statedocs.py::StateDocsTests::test_dual_skips_db_compare_when_file_unchanged` | yok | EKSİK: test yok |
| `test_statedocs.py::StateDocsTests::test_mirror_log_modes` | parity_store.rs::mirror_log_and_on_corrupt_match_python (kipler) | EKSİK: test yok (DB hatasının yutulması) |
| `test_statedocs_hosts_diag.py::HostsDiagDual::test_hosts_dual_roundtrip_and_perm` | yok | kapsam dışı: `hosts.py`; iz T5 |
| `test_statedocs_hosts_diag.py::HostsDiagDual::test_hosts_hand_edit_wins_in_dual` | yok | kapsam dışı: `hosts.py`; iz T5 |
| `test_statedocs_hosts_diag.py::HostsDiagDual::test_hosts_db_mode_without_file` | yok | kapsam dışı: `hosts.py`; iz T5 |
| `test_statedocs_hosts_diag.py::HostsDiagDual::test_diag_log_mirrors` | yok | kapsam dışı: `diaglog` yazıcısı (`mirror_log` ayrıca sınanıyor); iz T1 |
| `test_statedocs_writers.py::WritersShadowTests::test_name_for` | parity.rs::statedocs_modes_with_python, roster_reads_and_writes_match_python | tamam |
| `test_statedocs_writers.py::WritersShadowTests::test_steward_save_load_shadow` | yok | kapsam dışı: `steward._save_json/_load_json`; iz T10 |
| `test_statedocs_writers.py::WritersShadowTests::test_steward_corrupt_backup_kept_and_db_recovers` | parity_store.rs::mirror_log_and_on_corrupt_match_python (yalnız geri çağrı) | EKSİK: test yok (dual kipte bozuk dosyada DB kopyasının dönmesi) |
| `test_statedocs_writers.py::WritersShadowTests::test_non_ready_docs_stay_file_even_in_db_mode` | parity.rs::statedocs_modes_with_python | tamam |
| `test_statedocs_writers.py::WritersShadowTests::test_ready_docs_db_only_in_db_mode` | parity.rs::statedocs_modes_with_python | tamam |
| `test_statedocs_writers.py::WritersShadowTests::test_mocked_writer_never_touches_db_or_file` | guard.rs::writers_panic_in_live_dir_and_write_nothing (farklı mekanizma) | kapsam dışı: Rust'ta yazıcı enjeksiyonu yok; iz W0-a |
| `test_statedocs_writers.py::WritersShadowTests::test_instances_shadow` | parity.rs::instances_match_python (files ve db) | EKSİK: test yok (dual kipte instances DB gölgesi) |
| `test_steward_settings.py::TestIds::test_valid` | yok | kapsam dışı: `steward.valid_steward_id` (saf kural); iz T10 |
| `test_steward_settings.py::TestIds::test_brain_name` | yok | kapsam dışı: `steward.brain_name_for`; iz T10 |
| `test_steward_settings.py::TestStewardSettings::test_golden_default_empty` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_settings.py::TestStewardSettings::test_handover_defer_fields` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_settings.py::TestStewardSettings::test_default_ignores_stewards_block` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_settings.py::TestStewardSettings::test_default_brain_name_override_kept` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_settings.py::TestStewardSettings::test_ids` | yok | EKSİK: kod yok (`steward_ids`) |
| `test_steward_settings.py::TestStewardSettings::test_custom_cfg` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_settings.py::TestStewardSettings::test_unknown_and_invalid_sid` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_settings.py::TestStewardSettings::test_custom_bad_values_tolerated` | yok | EKSİK: kod yok (`steward_config`, `steward_ids`) |
| `test_steward_settings.py::TestSaveTwoLevel::test_partial_update_keeps_other_ids` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_steward_settings.py::TestSaveTwoLevel::test_empty_removes_field_none_removes_id` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_steward_settings.py::TestSaveTwoLevel::test_invalid_ids_skipped_and_other_keys_untouched` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_steward_settings.py::TestSaveTwoLevel::test_bool_and_steward_block_unaffected` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_steward_settings.py::TestSaveTwoLevel::test_non_dict_stored_recovers` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_store.py::StoreTests::test_file_mode_0600` | parity.rs::db_roundtrip_both_ways (Python'un açtığı DB) | kapsam dışı: DB oluşturma Rust'ta yok; iz T6 |
| `test_store.py::StoreTests::test_schema_version_and_idempotent_reopen` | parity_store.rs::export_import_backup_match_python; parity.rs::db_roundtrip_both_ways | tamam |
| `test_store.py::StoreTests::test_newer_db_refused` | parity.rs::schema_mismatch_never_writes | tamam |
| `test_store.py::StoreTests::test_doc_roundtrip_default_version_delete` | parity.rs::db_roundtrip_both_ways (kısmi) | EKSİK: test yok (olmayan belgede sürüm 0, ikinci silmede false) |
| `test_store.py::StoreTests::test_update_none_keeps_old_and_exception_rolls_back` | parity.rs::db_roundtrip_both_ways (None yazmaz) | EKSİK: test yok (hata/panikte geri alma) |
| `test_store.py::StoreTests::test_list_docs_prefix_escapes_like` | parity.rs::db_roundtrip_both_ways | tamam |
| `test_store.py::StoreTests::test_threads_update_doc_no_lost_updates` | parity.rs::concurrent_writers_lose_nothing | tamam |
| `test_store.py::StoreTests::test_processes_update_doc_no_lost_updates` | parity.rs::concurrent_writers_lose_nothing | tamam |
| `test_store.py::StoreTests::test_log_append_read_tail_trim` | parity_store.rs::log_functions_match_python | tamam |
| `test_store.py::StoreTests::test_backup_leaves_no_tmp_and_unique_names` | parity_store.rs::export_import_backup_match_python (tek çağrı) | EKSİK: test yok (üst üste ikinci yedek) |
| `test_store.py::StoreTests::test_backup_failure_cleans_tmp` | yok | EKSİK: test yok |
| `test_store.py::StoreTests::test_backup_consistent_and_private` | parity_store.rs::export_import_backup_match_python | tamam |
| `test_store.py::StoreTests::test_export_docs` | parity_store.rs::export_import_backup_match_python | tamam |
| `test_store_edge.py::Edge::test_empty_tsv_is_empty_string_not_none` | parity.rs::roster_reads_and_writes_match_python (boş dosya satırı) | EKSİK: kod (`replace_tsv` boş metinde 1 döner, Python 0) ve test |
| `test_store_edge.py::Edge::test_split_respects_quotes` | yok | kapsam dışı: göç deyim bölücü; iz T6 |
| `test_store_pg.py::PgStoreTests::test_schema_version_and_idempotent_reopen` | yok | kapsam dışı: Postgres; iz T9 |
| `test_store_pg.py::PgStoreTests::test_backend_is_postgres` | yok | kapsam dışı: Postgres; iz T9 |
| `test_store_tsv.py::TsvTests::test_roundtrip_exact_and_rows` | parity_store.rs::tsv_rows_filter_and_files_match_python; parity.rs::roster_reads_and_writes_match_python | tamam |
| `test_store_tsv.py::TsvTests::test_replace_overwrites_and_files_isolated` | parity.rs::roster_reads_and_writes_match_python; parity_store.rs::export_import_backup_match_python | tamam |
| `test_store_tsv.py::TsvTests::test_deleted_file_clears_shadow_and_empty_file_not_rewritten` | parity.rs::roster_reads_and_writes_match_python (silinen ve boş) | EKSİK: test yok (boş dosyada gereksiz yeniden yazım olmaması) |
| `test_store_tsv.py::TsvTests::test_shadow_syncs_on_change_only` | yok | EKSİK: test yok |
| `test_store_tsv.py::TsvTests::test_files_mode_and_outside_dir_and_other_names_skip` | yok | EKSİK: test yok |
| `test_store_tsv.py::TsvTests::test_web_write_functions_shadow` | parity.rs::roster_reads_and_writes_match_python | tamam |
| `test_ucli_key_path.py::UcliKeyPathTest::test_default_and_service` | parity_settings.rs::expanduser_and_proc_match_python (kopya üzerinden) | EKSİK: test yok (Rust `ucli_key_file` iki dal) |
| `test_ucli_key_path.py::UcliKeyPathTest::test_callers_share_helper` | yok | kapsam dışı: ucli sağlayıcısı ve `web_review` çağıranları; iz W1-pre sağlayıcı |
| `test_ucli_services_settings.py::ServicesTests::test_defaults_when_empty` | parity_settings.rs::settings_readers_match_python, defaults_lists_match_python | tamam |
| `test_ucli_services_settings.py::ServicesTests::test_groq_label` | parity_settings.rs::defaults_lists_match_python | tamam |
| `test_ucli_services_settings.py::ServicesTests::test_invalid_dropped_evren_always_present` | parity_settings.rs::settings_readers_match_python (kısmi) | EKSİK: test yok (geçersiz env reddi) |
| `test_ucli_services_settings.py::ServicesTests::test_services_map_follows_settings` | yok | kapsam dışı: `ucli_session_opts`; iz W1-pre sağlayıcı |
| `test_ucli_services_settings.py::ServicesTests::test_effort_follows_model` | yok | kapsam dışı: `ucli_session_opts.effort_levels_for`; iz W1-pre sağlayıcı |
| `test_web_roster_lock.py::RosterLockTest::test_toggle_creates_lock_and_works` | parity.rs::roster_reads_and_writes_match_python; lock_e2e.rs::roster_and_instances_locks_shared | tamam |
| `test_web_roster_lock.py::RosterLockTest::test_replace_keeps_comment` | parity.rs::roster_reads_and_writes_match_python | tamam |
| `test_web_roster_lock.py::RosterLockTest::test_missing_file_false` | yok | EKSİK: test yok (olmayan dosyada false) |
| `test_web_roster_lock.py::RosterLockTest::test_concurrent_toggles_no_lost_update` | yok | EKSİK: test yok (eşzamanlı aç/kapat) |
| `test_web_roster_lock.py::RosterLockTest::test_concurrent_appends_no_lost_line` | parity.rs::concurrent_writers_lose_nothing | tamam |
| `test_web_roster_lock.py::RosterLockTest::test_web_close_migrate_share_one_lock` | lock_e2e.rs::roster_and_instances_locks_shared (yol ortak) | kapsam dışı: `close` ve `migrate-instances` çağıranları; iz T6 |
| `test_web_roster_lock.py::RosterLockTest::test_lock_reentrant_in_same_thread` | fd_leak.rs::no_fd_leak (kilit içinde ikinci alma) | tamam |
| `test_web_roster_lock.py::RosterLockTest::test_data04_first_row_wins_like_writers` | parity.rs::roster_reads_and_writes_match_python (ilk satır) | EKSİK: test yok (`name` başlık dışlaması) |

### Python testleri: diğer dosyalarda kapsam modülü davranışını sınayan metotlar

| Python testi (dosya::Sınıf::metot) | Rust testi | Durum |
|---|---|---|
| `test_authz.py::ResourcesTest::test_doc_prefix` | yok | EKSİK: test yok (`register_doc_prefix`) |
| `test_close_base_name.py::TsvFinder::test_find_and_edit` | parity.rs::roster_reads_and_writes_match_python | tamam |
| `test_db_cmd.py::DriftMaterializeTest::test_drift_states` | yok | kapsam dışı: `cops db drift`; iz T6 |
| `test_db_cmd.py::DriftMaterializeTest::test_materialize_dry_then_apply_private_atomic` | yok | kapsam dışı: `cops db materialize`; iz T6 |
| `test_db_cmd.py::DriftMaterializeTest::test_path_escape_and_unknown_rejected` | yok | kapsam dışı: `cops db` yol denetimi; iz T6 |
| `test_db_cmd.py::DbCmdTest::test_export_import_roundtrip` | parity_store.rs::export_import_backup_match_python | tamam |
| `test_db_cmd.py::DbCmdTest::test_bad_format_refused` | parity_store.rs::export_import_backup_match_python | tamam |
| `test_db_cmd.py::DbCmdTest::test_cli_export_dry_and_apply` | yok | kapsam dışı: `cops db export/import` komutu; iz T6 |
| `test_extensions_routes.py::ReaderConfig::test_validation` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_guard_lock_safety.py::GuardLockSafetyTest::test_default_lock_path_is_per_user` | yok | EKSİK: test yok (`guard_lock` yolu) |
| `test_model_watch.py::MarkInstancesGoneTests::test_marks_gone_clears_on_return_and_skips_empty_scan` | parity_instances.rs::mark_models_gone_matches_python | tamam |
| `test_p3_fixes.py::FileLockReentrantTest::test_nested_same_thread_does_not_deadlock` | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `test_quota_scoped_api_credit.py::TestCreditWindow::test_config_dates_validated` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_resolved_binary_override.py::ResolvedBinaryOverrideTest::test_valid_executable_override_wins` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_resolved_binary_override.py::ResolvedBinaryOverrideTest::test_tilde_expanded` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_resolved_binary_override.py::ResolvedBinaryOverrideTest::test_missing_or_non_executable_falls_back_to_path` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_review.py::TestConfigRole::test_defaults_and_settings` | yok | EKSİK: kod yok (`steward_config`) |
| `test_review_fixes_2026_11_04.py::FileLockPathNormalizationTest::test_spellings_of_one_path_share_one_lock_entry` | fsutil.rs::reentrant_same_thread_exclusive_across_threads | tamam |
| `test_review_fixes_batch.py::TestAtomicJson::test_bare_filename_works` | yok | EKSİK: test yok (dizinsiz göreli ad) |
| `test_review_fixes_batch.py::TestAtomicJson::test_tmp_removed_on_failure_and_fsync_called` | yok | EKSİK: test yok |
| `test_review_lowrisk_fixes.py::DerivedNameRe::test_digit_ending_blueprint_keeps_full_date` | parity_instances.rs::name_patterns_and_created_at_match_python | tamam |
| `test_review_uzops_p3.py::P3::test_non_dict_byok_patch_keeps_block` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_routing_guidance.py::DefaultsTest::test_claude_defaults_to_newest_sonnet_medium` | yok | EKSİK: kod yok (`default_model_for`, `default_effort_for`) |
| `test_routing_guidance.py::DefaultsTest::test_provider_without_model_choices_gives_empty_default` | yok | EKSİK: kod yok (`default_model_for`) |
| `test_routing_guidance.py::DefaultsTest::test_override_wins_and_invalid_override_falls_back` | yok | EKSİK: kod yok (`default_effort_for`) |
| `test_routing_guidance.py::DefaultsTest::test_other_providers_keep_old_top_level_effort` | yok | EKSİK: kod yok (`default_effort_for`) |
| `test_routing_guidance.py::GuidanceTest::test_enabled_by_default_and_bundled_path_used` | parity_settings.rs::settings_readers_match_python (yalnız bayrak) | kapsam dışı: `routing` yönerge yolu; iz W1-pre sağlayıcı |
| `test_routing_guidance.py::GuidanceTest::test_off_disables_flag` | yok | kapsam dışı: kayıt turu ve spawn komutu; iz W1-pre sağlayıcı |
| `test_snapshot_db.py::SnapshotDbTest::test_db_ready` | parity.rs::constants_match_python | tamam |
| `test_steward_ask_gate.py::ConfigTest::test_defaults_and_validation` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_core_b.py::SettingsTest::test_defaults_parse_and_clamp` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_generic.py::TestConfig::test_generic_defaults_to_sonnet_medium` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_generic.py::TestConfig::test_own_block_is_the_owners_explicit_choice` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_generic.py::TestConfig::test_default_can_never_be_generic` | yok | EKSİK: kod yok (`steward_config`) |
| `test_steward_launch_cli.py::InstanceRecordsCliOptsTest::test_record_and_mark_started_persist_and_clear_on_cli_change` | parity.rs::instances_match_python (kısmi) | EKSİK: test yok (aynı cli ve seçeneksiz başlatmada `cli_opts` korunur) |
| `test_steward_reviewer_gate.py::TestReviewerCreate::test_default_is_never_reviewer` | yok | EKSİK: kod yok (`steward_config`) |
| `test_tunnel_proto.py::SavePath::test_default_unmanaged` | parity.rs::constants_match_python | tamam |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_the_watchdog_is_on_by_default` | parity_settings.rs::settings_readers_match_python; parity.rs::constants_match_python | tamam |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_on_in_any_case_and_odd_values_mean_enabled` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_every_off_spelling_disables_it_including_non_strings` | parity.rs::constants_match_python; parity_settings.rs::settings_readers_match_python | tamam |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_a_missing_key_in_a_stored_file_falls_back_to_the_default` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_the_value_round_trips_through_save_settings_as_a_plain_scalar` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_the_panel_sends_the_value_to_the_browser_unredacted` | yok | kapsam dışı: panel ayar yanıtı; iz T7 |
| `test_tunnel_watch_setting.py::TunnelWatchSettingTests::test_saving_it_through_the_web_handler_is_accepted` | yok | kapsam dışı: `/api/settings` POST; iz T7 |
| `test_ucli_brain_mcp.py::BrainUcliTests::test_settings_override_service_model_and_cap` | yok | EKSİK: kod yok (`steward_config`) |
| `test_ucli_brain_mcp.py::BrainUcliTests::test_defaults` | yok | EKSİK: kod yok (`steward_config`) |
| `test_ucli_cost_credit.py::CreditTest::test_config_parse` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_effort.py::ReasoningModeTests::test_unset_empty_and_unknown_values_mean_auto` | parity_settings.rs::settings_readers_match_python (yalnız yok) | EKSİK: test yok (tanınmayan değer auto) |
| `test_ucli_effort.py::ReasoningModeTests::test_off_words_switch_it_off` | parity_settings.rs::settings_readers_match_python; parity.rs::constants_match_python | tamam |
| `test_ucli_effort.py::ReasoningModeTests::test_a_named_level_forces_that_level_case_insensitively` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_effort.py::ReasoningModeTests::test_a_non_dict_ucli_limits_is_tolerated` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_effort.py::ReasoningModeTests::test_it_does_not_leak_into_the_numeric_overrides` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_endpoint.py::UcliEndpointTest::test_default_is_evren` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_endpoint.py::UcliEndpointTest::test_custom_valid_endpoint_wins_and_trailing_slash_dropped` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_endpoint.py::UcliEndpointTest::test_invalid_endpoint_falls_back_and_empty_clears` | parity_settings.rs::settings_readers_match_python (okuma kısmı) | tamam |
| `test_ucli_endpoint.py::UcliEndpointTest::test_model_list_fetch_uses_configured_endpoint` | yok | kapsam dışı: ucli model listesi çekimi; iz W1-pre sağlayıcı |
| `test_ucli_metrics.py::Idle::test_settings_default_key` | parity.rs::constants_match_python | tamam |
| `test_ucli_quota_warn.py::ThresholdSettingTests::test_unset_means_one_million_and_three_million` | parity_settings.rs::settings_readers_match_python, defaults_lists_match_python | tamam |
| `test_ucli_quota_warn.py::ThresholdSettingTests::test_custom_values_win_as_strings_or_numbers_with_separators` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_quota_warn.py::ThresholdSettingTests::test_off_words_and_zero_disable_a_level` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_quota_warn.py::ThresholdSettingTests::test_garbage_falls_back_to_the_default_of_that_level` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_quota_warn.py::ThresholdSettingTests::test_a_non_dict_setting_is_tolerated` | yok | EKSİK: test yok (sözlük olmayan `ucli_usage_warn`) |
| `test_ucli_quota_warn.py::ThresholdSettingTests::test_the_setting_is_part_of_the_schema_and_merges_per_field` | yok | kapsam dışı: alan bazlı yama yazımı; iz T7 |
| `test_ucli_script.py::ScriptModeSettingTests::test_default_and_garbage_mean_off` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_script.py::ScriptModeSettingTests::test_read_and_full_in_any_spelling` | parity_settings.rs::settings_readers_match_python (yalnız full) | EKSİK: test yok (`read`) |
| `test_ucli_script.py::ScriptModeSettingTests::test_default_settings_carry_the_key` | parity.rs::constants_match_python | tamam |
| `test_ucli_script.py::SaveScriptSettingTests::test_mode_round_trips_and_an_empty_one_switches_the_layer_off` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_script.py::SaveScriptSettingTests::test_saving_the_mode_leaves_the_other_ucli_panels_alone` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_script.py::SaveScriptSettingTests::test_a_hand_edited_non_dict_value_degrades_to_off` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_script.py::SaveScriptSettingTests::test_the_panel_endpoint_returns_the_field_on_the_wire` | yok | kapsam dışı: `/api/settings` POST; iz T7 |
| `test_ucli_show_reasoning.py::SettingTests::test_default_off_and_words` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_start_opts.py::CostCapTests::test_config_parsing_is_safe` | parity_settings.rs::settings_readers_match_python (kısmi) | EKSİK: test yok (sözlük olmayan `ucli_cost`) |
| `test_ucli_start_opts.py::CostCapTests::test_credit_total_parsing_is_safe` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_state_dir.py::TestSetting::test_default_off_and_words` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_stream.py::StreamSettingTests::test_the_shipped_default_is_on` | parity_settings.rs::defaults_lists_match_python | tamam |
| `test_ucli_stream.py::StreamSettingTests::test_an_untouched_install_asks_for_the_stream_and_off_still_wins` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_stream.py::StreamSettingTests::test_missing_empty_and_garbage_fall_back_to_the_default` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_stream.py::StreamSettingTests::test_on_words_enable_in_any_spelling` | parity_settings.rs::settings_readers_match_python, defaults_lists_match_python | tamam |
| `test_ucli_stream.py::StreamSettingTests::test_off_words_disable_even_when_the_default_is_on` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_stream.py::StreamSettingTests::test_the_stream_key_is_not_mistaken_for_a_numeric_limit` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_stream.py::SaveStreamSettingTests::test_it_round_trips_and_an_empty_value_goes_back_to_the_default` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_stream.py::SaveStreamSettingTests::test_it_does_not_disturb_the_other_limit_fields` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_stream.py::SaveStreamSettingTests::test_a_hand_edited_non_dict_value_degrades_to_the_default` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_empty_unset_and_garbage_mean_the_defaults_search_via_the_managed_searxng` | parity_settings.rs::settings_readers_match_python (yalnız yok) | EKSİK: test yok (sözlük olmayan blok) |
| `test_ucli_web.py::UcliWebConfigTests::test_search_docker_can_be_turned_off_in_every_spelling` | parity_settings.rs::settings_readers_match_python; parity.rs::constants_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_search_docker_stays_on_for_on_values_and_for_empty_or_null` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_an_explicit_address_wins_and_switches_the_managed_one_off` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_a_filled_but_invalid_address_does_not_fall_back_to_the_managed_searxng` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_valid_searxng_address_defaults_the_flavor` | yok | EKSİK: test yok (flavor verilmemiş geçerli adres) |
| `test_ucli_web.py::UcliWebConfigTests::test_https_and_explicit_flavor_in_any_case` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_brave_is_not_supported_yet_and_fails_closed` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_invalid_addresses_keep_search_off` | parity_settings.rs::settings_readers_match_python; settings_read.rs::url_rules | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_whitespace_around_the_address_is_trimmed_not_rejected` | yok | EKSİK: test yok |
| `test_ucli_web.py::UcliWebConfigTests::test_domains_are_split_lowercased_and_deduplicated_in_order` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_domains_accept_a_list_too` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_invalid_domains_are_dropped_not_fixed` | parity_settings.rs::settings_readers_match_python (kısmi) | EKSİK: test yok (joker, şema, yol, port, uzun etiket) |
| `test_ucli_web.py::UcliWebConfigTests::test_whitespace_is_a_separator_not_part_of_a_name` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::UcliWebConfigTests::test_single_label_hosts_are_valid` | yok | EKSİK: test yok |
| `test_ucli_web.py::UcliWebConfigTests::test_domain_count_is_capped` | yok | EKSİK: test yok (64 tavanı) |
| `test_ucli_web.py::UcliWebConfigTests::test_fetch_domains_do_not_need_a_search_address` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_ucli_web.py::SaveSettingsTests::test_defaults_are_off_and_cache_aware` | parity.rs::constants_match_python, settings_match_python | tamam |
| `test_ucli_web.py::SaveSettingsTests::test_ucli_web_merges_per_field_and_empty_removes_the_field` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_web.py::SaveSettingsTests::test_a_boolean_search_docker_round_trips_and_false_does_not_mean_remove` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_web.py::SaveSettingsTests::test_the_off_switch_does_not_disturb_the_other_fields` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_web.py::SaveSettingsTests::test_a_list_value_is_stored_as_a_comma_separated_string` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_web.py::SaveSettingsTests::test_other_dict_settings_are_unaffected_by_the_list_handling` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_ucli_web.py::SaveSettingsTests::test_a_non_dict_stored_value_degrades_to_empty` | parity.rs::settings_match_python (başka anahtarlar) | EKSİK: test yok (sözlük olmayan `ucli_web` blokunun `{}` olması) |
| `test_ucli_web.py::SaveSettingsTests::test_the_escape_hatch_persists` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_usage_byok_host_routed.py::Endpoint::test_set_read_clear_never_echoes_value` | parity_settings.rs::settings_readers_match_python (yalnız okuma) | kapsam dışı: `/api/settings/byok` yazım ucu; iz T7 |
| `test_usage_fresh.py::ResolvedBinaryFallback::test_claude_found_outside_path` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_usage_fresh.py::ResolvedBinaryFallback::test_provider_bin_override_used_by_usage_fresh_argv` | yok | kapsam dışı: sağlayıcı `usage_fresh_argv`; iz W1-pre sağlayıcı |
| `test_uzakgoz_config.py::ConfigTests::test_defaults_when_empty_or_garbage` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_uzakgoz_config.py::ConfigTests::test_dir_needs_cargo_toml` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_uzakgoz_config.py::ConfigTests::test_bin_must_be_executable_file` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_uzakgoz_config.py::ConfigTests::test_port_range` | parity_settings.rs::settings_readers_match_python | tamam |
| `test_uzakgoz_config.py::ConfigTests::test_save_merges_and_empty_removes` | yok | kapsam dışı: `save_settings`; iz T7 |
| `test_uzakgoz_config.py::DerbentConfigTests::test_same_contract_own_key` | parity_settings.rs::settings_readers_match_python | tamam |

### Python testleri: kalan metotlar (dosya başına tek satır)

Bu dosyalarda kalan metotlar kapsam modüllerini yardımcı olarak (yol yaması, ayar kurma, taklit) kullanır.

| Dosya (kalan / toplam metot) | Neyi sınıyor | Durum |
|---|---|---|
| `steward_testlib.py` (0 / 0) | steward testlerinin ortak yardımcı sınıfı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_adopt_valueerror.py` (6 / 6) | `/api/adopt` hata yolu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_authz.py` (44 / 45) | eylem tablosu ve yetki kancaları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T9 |
| `test_cache_info.py` (12 / 12) | oturum satırında önbellek alanı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T1 |
| `test_check_cmd.py` (5 / 5) | `cops check` | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_close_base_name.py` (2 / 3) | `cops close` taban ad indirgeme | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_close_order.py` (1 / 1) | `cops close` sırası | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_close_uncomment.py` (2 / 2) | `cops close` geri açma | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_diag_ask_valueerror.py` (1 / 1) | `/api/diag/ask` hata yolu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_diag_log_isolation.py` (2 / 2) | `diaglog` yolu ve yalıtımı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T1 |
| `test_empty_fleet_p0.py` (9 / 9) | değnekçi boş filo davranışı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_extensions_routes.py` (18 / 19) | eklenti rotaları ve okuma listesi ucu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T9 |
| `test_files_resolve_exact_first.py` (5 / 5) | dosya uçlarının ad çözümü | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T3 |
| `test_graphical_session.py` (15 / 15) | masaüstü oturumu etkinleştirme | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_guard_digit_names.py` (2 / 2) | guard'ın rakamlı adları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_guard_lock_safety.py` (3 / 4) | guard kilidi güvenliği | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_handover_cache_policy.py` (50 / 50) | devir önbellek politikası | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_hosts.py` (8 / 8) | `hosts.py` kilitli yazım ve erişim | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T5 |
| `test_live_model_effort.py` (17 / 17) | canlı model/effort ucu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_live_sessions_adhoc.py` (3 / 3) | canlı oturum keşfi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T1 |
| `test_memory_prv.py` (19 / 19) | hafıza yedeği komutu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_migrate_pg.py` (4 / 4) | SQLite'tan Postgres'e kopya | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T9 |
| `test_mirror_marker.py` (20 / 20) | mirror işaretçisi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T2 |
| `test_mirror_window.py` (41 / 41) | mirror penceresi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T2 |
| `test_model_watch.py` (5 / 6) | model tazelik izleme | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_needs_ho_transcript.py` (4 / 4) | devir gereği transkript seçimi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_p3_fixes.py` (3 / 4) | çeşitli P3 düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_quota_scoped_api_credit.py` (8 / 9) | API kredisi penceresi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_quota_stop_skips_reviewer.py` (1 / 1) | kota durdurma | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_review.py` (52 / 53) | reviewer saf çekirdeği | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_20261125_upload_newchat.py` (3 / 3) | yükleme ve yeni sohbet yarışları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_review_26kas_races.py` (4 / 4) | web yarış düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_review_anthropic_key.py` (3 / 3) | reviewer anahtar seçimi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_findings_flow.py` (59 / 59) | bulgu akışı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_fixes_2026_11_04.py` (14 / 15) | çeşitli review düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_review_fixes_batch.py` (13 / 15) | çeşitli review düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_review_lowrisk_fixes.py` (3 / 4) | çeşitli review düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_review_remote.py` (21 / 21) | uzak reviewer | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_remote_verify.py` (6 / 6) | uzak doğrulama | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_self_verify.py` (18 / 18) | kendi doğrulama | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_slots.py` (27 / 27) | reviewer yuvaları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_stills_batch1.py` (2 / 2) | review düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_review_uzops_p3.py` (2 / 3) | web token ve MCP kuyruğu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_routing_guidance.py` (7 / 13) | yönerge dosyaları ve eşitleme | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_run_tunnel_script.py` (29 / 29) | tünel betiği | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_snapshot_db.py` (4 / 5) | anlık görüntü deposu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_snapshot_mirrors.py` (40 / 40) | anlık görüntü ve mirror | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_snapshot_resume_superseded.py` (3 / 3) | anlık görüntüden devam | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_spawn_priority.py` (2 / 2) | spawn önceliği | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_steward_advance.py` (19 / 19) | değnekçi motoru | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_ask_gate.py` (24 / 25) | ASK kapısı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_audit_p9.py` (24 / 24) | çoklu değnekçi denetimi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_brain.py` (34 / 34) | beyin oturumu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_bridges_e2e.py` (10 / 10) | köprü e2e | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_cli.py` (27 / 27) | `cops steward` komutu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_core_a.py` (120 / 120) | değnekçi saf çekirdeği | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_core_b.py` (75 / 76) | değnekçi çekirdeği ve özet | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_ctx.py` (21 / 21) | bağlam eşiği | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_digests.py` (6 / 6) | özetler | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_engine_multi.py` (16 / 16) | çoklu motor | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_generic.py` (22 / 25) | generic rol | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_http.py` (55 / 55) | değnekçi uçları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_jobs.py` (57 / 57) | iş kuyruğu istemcisi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_launch_cli.py` (14 / 15) | başlatma seçenekleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_quota_http.py` (6 / 6) | kota uçları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_remote.py` (31 / 31) | uzak yönetim | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_remote_cards.py` (16 / 16) | uzak kartlar | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_remote_facts.py` (19 / 19) | uzak oturum bilgisi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_remote_surface.py` (25 / 25) | uzak yüzey | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_steward_review_api.py` (14 / 14) | reviewer uçları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_steward_reviewer_gate.py` (18 / 19) | reviewer rol kapısı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_steward_upper_main.py` (17 / 17) | ana oturum uyarısı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_triage_fixes_20261107.py` (7 / 7) | triyaj düzeltmeleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_trust_dialog.py` (18 / 18) | güven diyaloğu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_tunnel_proto.py` (8 / 9) | tünel protokolü ayarı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_type_hints_resolve.py` (2 / 2) | Python tip ipuçları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_ucli_agents.py` (14 / 14) | ucli ajanları | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_ucli_brain_mcp.py` (24 / 26) | ucli beyin | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T10 |
| `test_ucli_cost_credit.py` (3 / 4) | maliyet ve kredi hesabı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_ucli_effort.py` (24 / 29) | ucli effort ve komut | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_ucli_fresh_handover.py` (6 / 6) | ucli taze devir | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_ucli_max_session_usd.py` (6 / 6) | oturum USD tavanı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_ucli_metrics.py` (18 / 19) | ucli metrikleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_ucli_metrics_file_arg.py` (3 / 3) | metrik dosyası bayrağı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_ucli_phase.py` (30 / 30) | canlı aşama | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T1 |
| `test_ucli_quota_warn.py` (15 / 21) | canlı kota uyarısı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T1 |
| `test_ucli_request_timeout.py` (14 / 14) | ucli zaman aşımı bayrağı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_ucli_script.py` (6 / 13) | ucli script kipi bayrağı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_ucli_show_reasoning.py` (2 / 3) | akıl yürütme bayrağı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_ucli_start_opts.py` (30 / 32) | başlatma seçenekleri ve tavan | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T4 |
| `test_ucli_state_dir.py` (8 / 9) | ucli durum dizini | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_ucli_stream.py` (3 / 12) | ucli akış bayrağı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_ucli_usage.py` (13 / 13) | ucli kullanım sayacı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T1 |
| `test_ucli_web.py` (33 / 58) | ucli web bayrakları ve arama kapsayıcısı | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz W1-pre sağlayıcı |
| `test_usage_byok_host_routed.py` (5 / 6) | byok ucu yönlendirmesi | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_usage_cli.py` (4 / 4) | `cops usage` | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_usage_fresh.py` (14 / 16) | taze kullanım okuma | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_usage_fresh_tui.py` (11 / 11) | kullanım TUI okuması | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_usage_poll.py` (8 / 8) | kullanım yoklaması | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_uzakgoz_config.py` (3 / 9) | uzakgoz daemon çözümü | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T7 |
| `test_watch_actions.py` (31 / 31) | `cops watch` eylemleri | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T6 |
| `test_web_review_runner.py` (49 / 49) | reviewer koşucusu | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |
| `test_web_review_tick.py` (11 / 11) | reviewer tick | kapsam dışı: yardımcı kullanım, sınanan konu bu izde değil; iz T8 |

## Açık işler (hepsi bitmeden birleştirmeye hazır sayılmaz)

1. ~~Ders listesi~~ (bu tur, yukarıda).
2. ~~Eşleme tablosu~~ (yukarıda "Eşleme tablosu"). Tablodaki EKSİK satırları kapanmadan birleştirmeye hazır sayılmaz:
   kod eksikleri K1-K6 ve test eksikleri "EKSİK özeti"nde.
3. ~~Taşınmamış işlevler~~ (bu tur: settings okuyucuları `d438cd1`; store/statedocs `a4dfdda`; instances/roster/paths
   `d438cd1`, `becc4d6`).
4. ~~Sapmalar~~ (yukarıdaki tablo).
5. Sahip cevapları S1-S10 (yukarıda); cevaba göre iki dilde birlikte değişiklik.
