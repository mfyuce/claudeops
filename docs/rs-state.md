# rs/state (W0-a): `cops-state` crate'i

Durum (26 Kas 2026 17:25): kod ve parite testleri yazıldı, **birleştirmeye hazır DEĞİL** (aşağıda "Açık işler").
Kod: `31f9868`. Doğrulama: `cargo fmt --check`, `cargo clippy -p cops-state --all-targets -- -D warnings`,
`cargo test -p cops-state` (5 birim + 13 parite, hepsi geçti). Parite testleri `python3` ve kullanıcı site paketlerini
(`websockets`) ister; yalnız geçici dizine yazar (`HOME` ve `CLAUDEOPS_DIR` geçici).

## Genel API

| Modül | Python karşılığı | Ana tipler ve işlevler |
|---|---|---|
| `json` | `json` modülü | `Json` (sıra korur; `parse`, `to_compact`, `to_indented`, `py_eq`, `truthy`, `get`; serde `Serialize`), `Map`, `py_float_repr` |
| `paths` | `paths.py` (dizin) | `StateDir::{resolve, at, join, doc_path, roster_tsv, models_tsv, settings_json, instances_json, db, apply_env, ensure_private}` |
| `fsutil` | `atomic_json.py` | `atomic_write_json`, `atomic_write_tsv`, `FileLock::{acquire, acquire_within, blocking}` |
| `store` | `store.py` | `Store::open` (oluşturmaz, göç yok), `get_doc`, `get_doc_raw`, `set_doc`, `update_doc`, `delete_doc`, `list_docs`, `doc_version`, `export_docs`, `replace_tsv`, `delete_tsv`, `tsv_text`, `tsv_rows`; `StoreError`, `SCHEMA_VERSION` = 2 |
| `statedocs` | `statedocs.py` | `StateDocs::{new, isolated, backend, db_ready, register_doc_prefix, name_for, store, read, read_opts, write, shadow_tsv}`; `Backend`, `Read` (`Value`/`Missing`/`Corrupt`), `WriteOutcome` |
| `settings` | `settings.py` (okuma) | `load`, `SettingsReader` (imzaya bağlı önbellek), `Settings::{get, str_of, sub_str, flag_default_on}`, `defaults` |
| `roster` | `roster.py`, `web.py` TSV | `Roster::{raw_rows, entries, models, fleet_status, lock, register_project}`, `RosterGuard::{append, set_active, replace}`, `read_text`, `normpath`, `known_names` |
| `instances` | `instances.py` | `Instances::{read_strict, load, get, mutate, record, mark_started, forget, rename_blueprint, add_missing}`, `derived_name`, `infer_blueprint` |

Kullanım kuralları (sonraki izler için):
- Süreç başına TEK `StateDocs` (`Arc`): kirli/eşitlendi kayıtları ve DB bağlantısı onda.
- API yanıtında `Json` doğrudan `serde_json` ile yazılır, sıra korunur.
- `serde_json` `preserve_order` AÇILMAZ: workspace geneline yayılır; enterprise `cops-ent-auth` testi sıralı anahtara dayanıyor.
- Süreç taraması ve sağlayıcı varsayılanları çağırandan gelir (`register_project`in `running` ve `default_model` parametreleri).
- `Settings` sır (`byok`) taşır; loglanmaz, yanıtlanmaz.

## Kararlar

- Rust DB oluşturmaz, göç çalıştırmaz; sürüm açılışta ve her yazım işlemi içinde denetlenir.
- Test algısı: ikili `.../deps/<ad>-<16 hex>` ise `CLAUDEOPS_DIR` yokken süreç başına geçici dizin (`atexit` siler).
- `default_settings.json` Python `DEFAULT_SETTINGS`ten üretildi; parite testi ayrışmayı yakalar.
- Ondalık yazımında eşit uzaklıkta iki en kısa aday varsa çift basamak seçilir (Python `repr`). Test bunu yakaladı.
  Aynı hata enterprise `crates/cops-ent-auth/src/pyjson.rs::py_float_repr` içinde duruyor (kod okuması, orada test koşulmadı).

## Açık işler (hepsi bitmeden birleştirmeye hazır sayılmaz)

1. `docs/rust-lessons-from-python.md` (17:24'te dosya yoktu): genel liste ve bu izin kontrol listesi burada madde
   madde karşılanacak (test adı ya da gerekçe).
2. Eşleme tablosu (sahip EK 2). Her `ast` tanımı için satır: Python adı (dosya:satır), Rust karşılığı, parite testi,
   durum (tamam / kapsam dışı: neden ve iz). Boş ya da "sonra" satırı olmayacak.
   - Modüller ve tanım sayısı: paths 20, statedocs 26, store 36, settings 51, roster 5, instances 29, atomic_json 13,
     dbapi 31; ayrıca `commands/web.py` TSV işlevleri. Sayım: modül düzeyi atamalar + iç içe `def`/`class`.
   - Her `test_*` metodu için de satır. İlgili dosyalar: `atomic_json*`, `atomic_text_concurrent`,
     `atomic_write_text_fsync`, `p2_atomic_writes`, `statedocs*`, `store*`, `dbapi`, `settings_*`,
     `ucli_services_settings`, `steward_settings`, `paths_isolation`, `proc_stat_parse`, `ucli_key_path`,
     `web_roster_lock`, `bad_encoding_state_files`, `*_store`, `orch_store_db`, `core_projects_roster`; ayrıca bu
     modülleri kullanan diğer testler tek tek taranacak.
3. Henüz taşınmamış, bu izin işi olanlar:
   - settings okuyucuları: `resolved_binary`, `byok_env_for`, `ucli_*` okuyucuları, `normalize_ucli_services`,
     `_valid_http_url`, `_daemon_config`/`uzakgoz_config`/`derbent_config`, `reader_config` (Python `str`/`int`/`float`
     dönüşümleri aynen).
   - `statedocs.mirror_log`, `on_corrupt` geri çağrısı; `Store` günlük işlevleri, `export_all`, `import_all`, `backup`,
     `tsv_files`.
   - `roster_by_name`; `instances.mark_models_gone`, `created_at_from_name`, `AUTO_NAME_RE`, `load_instances` önbelleği;
     `_blueprint_cwds`; `paths` sabitleri, `/proc` yardımcıları, `ucli_key_file`; `atomic_write_text`.
4. Python'dan şu anki sapmalar (Python gibi yapılacak ya da gerekçesi tabloya yazılacak):
   - `FileLock`: yeniden girilebilir değil ve zaman aşımında hata verir; Python iç içe alır ve kilitsiz sürer.
   - `StateDocs`: ortam `CLAUDEOPS_STORE_BACKEND` kurulumda bir kez okunuyor; Python her çağrıda okur.
   - db kipinde şema Python'dan yeniyse Rust hiçbir yere yazmaz; Python dosyaya yazıp belgeyi kirli sayar.
   - TSV alanında sekme ya da satır sonu reddediliyor; Python `model` alanını denetlemiyor.
   - `~kullanici` genişletilmiyor.
   - Eşlenmemiş vekil (`\ud800`) içeren belge bozuk sayılıyor; Python okur (utf-8 yazamaz).
   - UTF-8 olmayan `settings.json`: Rust varsayılanlara düşer; Python istisna fırlatır.
   - `Instances::load` önbelleksiz.
5. Python hatası olabilecekler (sahibe soruldu / sorulacak): `file_lock` zaman aşımında kilitsiz sürmesi;
   `load_settings`in UTF-8 olmayan dosyada patlaması; `_register_project`in `model`de satır sonunu kabul etmesi;
   db kipinde ayna dosya yazılamazsa `load_instances` önbelleğinin bayat kalması.
