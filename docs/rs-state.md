# rs/state (W0-a): `cops-state` crate'i

Durum (26 Kas 2026 akşam): açık işler 1, 3, 4 ve 5 bu turda kapandı (madde 5 sahibe soru olarak aşağıda). **Birleştirmeye
hazır DEĞİL**: eşleme tablosu (madde 2) ayrı turda yapılacak, sahip soruları (S1-S10) cevapsız.
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

## Açık işler (hepsi bitmeden birleştirmeye hazır sayılmaz)

1. ~~Ders listesi~~ (bu tur, yukarıda).
2. Eşleme tablosu (sahip EK 2). Her `ast` tanımı için satır: Python adı (dosya:satır), Rust karşılığı, parite testi,
   durum (tamam / kapsam dışı: neden ve iz). Boş ya da "sonra" satırı olmayacak. AYRI TURDA yapılacak.
   - Modüller ve tanım sayısı: paths 20, statedocs 26, store 36, settings 51, roster 5, instances 29, atomic_json 13,
     dbapi 31; ayrıca `commands/web.py` TSV işlevleri. Sayım: modül düzeyi atamalar + iç içe `def`/`class`.
   - Her `test_*` metodu için de satır. İlgili dosyalar: `atomic_json*`, `atomic_text_concurrent`,
     `atomic_write_text_fsync`, `p2_atomic_writes`, `statedocs*`, `store*`, `dbapi`, `settings_*`,
     `ucli_services_settings`, `steward_settings`, `paths_isolation`, `proc_stat_parse`, `ucli_key_path`,
     `web_roster_lock`, `bad_encoding_state_files`, `*_store`, `orch_store_db`, `core_projects_roster`; ayrıca bu
     modülleri kullanan diğer testler tek tek taranacak.
   - Bilinen kapsam dışı adaylar (tabloda gerekçelenecek): `settings.save_settings`/`_save_settings_locked` (yazım
     Python'da, T7), `default_model_for`/`default_effort_for`/`resolved_model_for` (sağlayıcı nesnesi ister, rs/prov),
     `steward_ids`/`steward_config` (rs/stew), `dbapi` Postgres yolu (Rust yalnız SQLite), `paths.REPO_DIR` ve test
     koşucusu algısı (`_under_test_runner`, Rust karşılığı `under_test`), `Store` göçleri (Rust göç yapmaz).
3. ~~Taşınmamış işlevler~~ (bu tur: settings okuyucuları `d438cd1`; store/statedocs `a4dfdda`; instances/roster/paths
   `d438cd1`, `becc4d6`).
4. ~~Sapmalar~~ (yukarıdaki tablo).
5. Sahip cevapları S1-S10 (yukarıda); cevaba göre iki dilde birlikte değişiklik.
