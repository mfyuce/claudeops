# rs-b0: copsd bağlamı (Rust dalga 2, İz B0)

Dal `rs/gate`, taban `main` `da6e993c`. Plan: `docs/rust-wave2-plan.md` bölüm 2 (R1-R6) ve 3 (B0). Canlı davranış
değişmez: rota tablosu yine boş, mevcut uçların yanıtları aynı (ölçüm aşağıda).

## Yapılanlar

| Madde | Kod | Test |
|---|---|---|
| 1. `RouteCtx`a süreç başına tek durum bağlamı + `SysEnv` | `copsd/src/routes.rs` (`RouteCtx::new`, alanlar `docs: Arc<ReadDocs>`, `env: SysEnv`), `copsd/src/state.rs` (`ReadDocs`) | `tests/state_ctx.rs` |
| 1. Durum dizini `cops-state` kuralıyla, test altında canlı dizin yok (H16) | `copsd::state_dir` -> `StateDir::resolve` | `state_ctx::state_dir_under_test_is_never_live`, mevcut `tests/state_dir.rs` (4) |
| 2. `cops_tmux::set_swallow_hook` -> copsd günlüğü | `copsd::tmux_swallow_line`, `log_tmux_swallow` (açılışta kurulur) | `state_ctx::tmux_swallow_line_keeps_only_a_short_first_line` |
| 3. `cops-procscan` `Config::from_env` durum dizinini `cops-state`ten alır (H14) | `cops-procscan/src/lib.rs` (`from_env`, yeni `Config::for_dirs`), `Cargo.toml` `cops-state` satırı | `config_tests` (2), `cops-cli` `list_bin` (değişmedi, geçiyor) |
| 4. R1 kararı | `copsd` `cops-steward-core`a BAĞLANMADI; `Cargo.toml` yorumu | `cargo tree` (aşağıda) |
| 5. `cops-local` <-> `cops-state::Store` | yalnız değerlendirme (aşağıda) | - |
| 6. Parite uç listesi | `cops-parity/requests/endpoints.json` (boş `requests`) | `route_force::parity_list_matches_registered_routes`, `parity_gap_check_is_red_on_mismatch` |
| 7. Kayıtlı her rota `force_proxy` ile Python'a | `tests/route_force.rs::check_forced` | gerçek tablo + 3 sahte tablo testi (biri geçer, ikisi yardımcının kırmızı olabildiğini gösterir) |
| 8. İkili boyutu + RSS | ölçüm betiği scratch'te (aşağıda) | - |

### 1. `ReadDocs`: neden çıplak `Arc<StateDocs>` değil

Koddan doğrulandı (`cops-state/src/statedocs.rs`, `roster.rs`, `instances.rs`):
- `StateDocs::new` / `isolated` / `with_logger` yan etkisiz: yalnız `CLAUDEOPS_DB_URL` okunur; dosya, dizin, DB, izin dokunulmaz.
  `backend()` `settings.json` okur, yazmaz. (`state_ctx::route_ctx_construction_touches_nothing`: dizin içeriği önce/sonra aynı;
  `route_ctx_on_missing_dir_creates_nothing`.)
- AMA okuma yolları yazar: `StateDocs::read` `dual` kipte DB'yi dosyaya uydurur (`set_doc`, "drift"/"import"), `db` kipte DB'de
  olmayan db-hazır belgeyi dosyadan içe aktarır (tembel içe aktarma), hata dalında `diag.log`a ekler; `StateDocs::store()`
  DB'yi yazılabilir açar (`PRAGMA journal_mode=WAL`); `Roster::raw_rows`/`entries`/`by_name` `shadow_tsv` ile `tsv_rows`
  tablosunu yazar; `Instances::load`/`get` `docs.read` üzerinden içe aktarabilir.
- Bu yüzden `RouteCtx.docs` = `Arc<ReadDocs>`: içindeki TEK `StateDocs` dışarı verilmez; `ReadDocs::read` Python
  `statedocs.read_json(name, path)` (`file_truth=True`) kararını verir ama DB'yi yalnız `read_only_store()` ile açar,
  içe aktarma/uydurma/günlük yazmaz; günlükçü stderr'e çevrilir (`diag.log` yok). Kanıt: `state_ctx::db_mode_reads_db_and_never_imports`
  ve `dual_mode_file_is_truth_and_db_is_not_reconciled` hem `ReadDocs`in yazmadığını hem aynı okumanın ham `StateDocs` ile
  YAZDIĞINI gösterir (karşılaştırma testi; ham yol yazmazsa test kırmızı).
- B1 için sonuç: `Instances`/`Roster` okuyucuları `&StateDocs` ister ve yazar; R2 altında copsd bunları olduğu gibi
  KULLANAMAZ. Seçenek: `cops-state`e salt okuma kipi (ör. `StateDocs::read_only(dir)`: içe aktarma/uydurma/`shadow_tsv`
  kapalı, DB `open_read_only`) ya da B1'in `ReadDocs::read` + saf ayrıştırıcıları kullanması. `cops-state` B0 yol
  listesinde olmadığı için yapılmadı (cops kararı).
- `ReadDocs::read` Python'dan sapmaları: (a) `db` kipte DB'de olmayan belge dosyadan okunur ama DB'ye AKTARILMAZ (Python aktarır);
  (b) Python'un süreç içi `dirty` kaydı (son DB yazımı başarısız -> dosya daha yeni) Rust'ta yok: Rust hiç yazmadığı için
  kendi kirli kaydı olamaz, Python'unkini göremez; Python'un DB yazımı kalıcı başarısızsa ve dosya daha yeniyse Rust DB'deki
  eski değeri görür (Python aynı süreçte dosyayı görür). (c) her okumada yeni salt okunur bağlantı (önbellek yok).

### Eşleme (Python karşılığı olan davranışlar)

| Python | Rust | Durum |
|---|---|---|
| `paths.CLAUDEOPS_DIR` (`CLAUDEOPS_DIR` env, test koşucusunda geçici dizin, yoksa `HOME/.claude/claudeops`) | `copsd::state_dir` (`--state-dir` > `cops_state::StateDir::resolve` > `paths::home()/.claude/claudeops`) | eş; `--state-dir` yalnız copsd'de. Fark: Python göreli `CLAUDEOPS_DIR`de `SystemExit`, Rust kabul eder (önceki davranış, değişmedi) |
| `paths.HOME` (`expanduser("~")`, `HOME` yoksa passwd) | `HOME` tanımsız/boşsa `cops_state::paths::home()` (passwd) | eş; ÖNCE `"/.claude/claudeops"` (HOME tanımsızken boş dize) idi |
| `_under_test_runner` -> geçici dizin | `cops_state::paths::under_test` (cargo test ikilisi) | eş (H16) |
| `statedocs.read_json(name, path)` | `copsd::state::ReadDocs::read` | karar eş, yan etki YOK (yukarıdaki sapmalar) |
| `statedocs.backend()` | `ReadDocs::backend` (`StateDocs::backend`) | eş |
| `agy_provider.AGY_SIDS_JSON` (`CLAUDEOPS_DIR/agy_sids.json`), `CONVERSATIONS_CACHE`, `paths.CLAUDE_DIR` | `cops_procscan::Config::from_env` / `for_dirs` | eş; `HOME` yoksa `None` (çağıran Python'a devreder, `docs/rs-proc.md` madde 12 değişmedi) |
| `tmux_backend` yutulan hata günlüğü (`_delete_buffer` vb. `diag`) | `copsd::tmux_swallow_line` (stderr = servis günlüğü) | Rust'a özgü biçim: kod + sayaç + İLK satır, denetim karakteri `?`, 160 karakter |

## R1 (`serde_json` `preserve_order`): ölçüm ve karar

Ölçüm (`CARGO_TARGET_DIR=~/.cargo-target/rs-gate`, günlükler `gate-logs/b0-*`):
- `cargo tree -e features -i serde_json -p copsd`: `preserve_order` YOK (taban ve B0 sonrası). `--workspace`: VAR (3 satır,
  kaynak yalnız `cops-steward-core`).
- Cargo özellik birleşimi derlenen paket kümesine göredir: `cargo build --release -p copsd` özelliksiz, `cargo build --release`
  (kökten, tüm üyeler) ya da `cargo build -p copsd -p cops-steward-core` özellikli copsd üretir. Kanıt: aynı kaynaktan iki release
  ikilisinde `indexmap` dizesi 0 / 47.
- Canlı ikili (`~/.claude/claudeops/bin/copsd`, `414821e547a1`, salt okundu): `indexmap` dizesi 0 -> özelliksiz derlenmiş
  (`-p copsd`). Belgeler tutarsız: `docs/copsd-app-cookie-plan.md` `cargo build --release -p copsd`, `front_cmd.py` engel metni
  `cargo build --release` (kökten = özellikli) diyor.
- KAPI UYARISI: `cargo test --workspace` copsd'yi ÖZELLİKLİ derleyip sınar; yani kapı bugün canlıya giden yapılandırmayı
  (özelliksiz) sınamıyor. B0 kabulünde ayrıca `cargo test -p copsd` koşuldu (aşağıda).
- Uç çıktısı (iki ikili, aynı kaynak `da6e993c`, geçici dizin): anahtar sırası DEĞİŞİYOR, her copsd JSON ucunda:
  `/api/steward/questions` özelliksiz alfabetik (`answer, answered_at, ...`), özellikli `FIELDS` sırası (`id, project, text, ...`,
  Python'un yazdığı sıra); `/api/front/stats` (`endpoints, ok, ...` -> `ok, started_at, totals, ...`), `/api/metrics/names`,
  hata gövdeleri (`{"error":..,"ok":false}` -> `{"ok":false,"error":..}`). Değerler aynı; JSON anlamı aynı (`cops-parity`
  nesneyi sırasız karşılaştırır).
- Enterprise (`claudeops-enterprise` `b2779d1`, salt okuma, ayrı hedef dizini, `--offline --locked`):
  `cargo test -p cops-ent-auth --features serde_json/preserve_order`: 1 kırmızı, `tests/golden.rs::bloom_and_generations`
  (`assertion failed: "cur_kisa"`; test `json!({...}).to_string()` özetini Python `sort_keys=True` sanıyor, yorumu da öyle
  diyor). Özelliksiz aynı test 13/13 geçti. `copsd-ent` çekirdeği git rev (`87b01ab`) ile alır: copsd `cops-steward-core`a
  bağlanırsa `copsd-ent` ikilisinde `cops-ent-auth` da özellikli derlenir (aynı `serde_json`).
- Seçenek (a) maliyeti (`cops-steward-core`dan özelliği kaldırmak): `src` içinde 94 `serde_json::Map`/`Map<String, Value>` ve
  96 `json!` kullanımı (24 dosya); `PORTING.md` kural 7 `state` sözlüğünün ekleme sırasını (Python dict) bu özelliğe bağlıyor:
  kaldırmak davranış değişikliği, parite vektörlerinin yeniden doğrulanması ve `src` değişikliği ister. B0 yol listesini aşıyor:
  UYGULANMADI.

Karar (B0): copsd `cops-steward-core`a bağlanmaz; `copsd` ikilisinde özellik yok (`cargo tree` 0 satır). Öneri (B4 öncesi
cops/sahip): (b) özelliği bilinçli kabul etmek daha ucuz görünüyor: copsd çıktısı Python sırasına yaklaşır; bedeli enterprise
golden testinin anahtarları açıkça sıralaması ve `cops-ent-auth`ın `serde_json::Map` sırasına dayanan üretim yolu olup
olmadığının taranması (bu iş taranmadı). Hangisi seçilirse seçilsin: canlı derleme komutu tek yerde sabitlenmeli
(`-p copsd` mi kök mü) ve kapı o yapılandırmayı sınamalı.

## 5. `cops-local` `docs` okuması `cops-state::Store` ile tekleşsin mi (değerlendirme)

Bugün `cops-local::questions` her istekte `claudeops.db`yi kendi `rusqlite` bağlantısıyla salt okunur açar, şema sürümüne
bakmaz ve `store_backend`ten bağımsız olarak HEP DB'yi okur. Python'da `steward/*` db-hazır belge: `db` kipte (canlıda) doğruluk
DB'dir, ama `files`/`dual` kipte doğruluk DOSYADIR; o kiplerde `cops-local` bayat DB değerini döndürebilir. Öneri: EVET,
uç B4'e taşınırken `ReadDocs::read("steward/questions" | "steward/stewards/<sid>/questions", <dosya yolu>)` ile tekleşsin
(kip kuralı + `CLAUDEOPS_DB_URL` + şema sürüm denetimi tek yerde). `cops-local::learned` (copsd'nin KENDİ yazdığı
`rootrel_learned` tablosu) ayrı kalır. B0'da kod değişmedi (`cops-local` yol listesinde değil).

## R2 notu: copsd bugün de yazıyor

"Tek yazar Python" yalnız Python'un belgeleri için doğru. copsd açılışta ve çalışırken: `metrics.db`yi oluşturur/yazar
(`cops-metrics`, `cops-progress` günlük iş), `claudeops.db`ye `CREATE TABLE IF NOT EXISTS rootrel_learned` + `journal_mode=WAL`
uygular ve öğrenilen kökleri yazar (`cops-local/src/learned.rs`, `cops-proxy` mount), eski `rootrel_learned.json`u
`.json.migrated` adıyla taşır. Ölçümde geçici dizinde `claudeops.db-wal/-shm` ve `metrics.db*` oluştu (taban ve B0 aynı).
B0 bunlara dokunmadı; yeni bir yazım eklemedi.

## 7. Test yardımcısı

`copsd/tests/route_force.rs::check_forced(table, force_line)`: her `(yöntem, desen)` için somut yol (`*` -> `b0-probe`),
(1) boş `front_force_proxy` ile istek Rust'ta cevaplanmalı (`x-cops-served: local`; kanca üstlenmiyorsa denetim boş olurdu:
HATA), (2) `force_line(desen)` yazılınca sahte Python'a gitmeli (`x-cops-served: python` + sahte gövde). Gerçek tablo bugün
0 rota (test sayıyı basar). Sahte tablo (GET önek + GET tam + `own_auth` POST): doğru önekle geçer; yanlış önekle ve hiç
üstlenmeyen kancayla yardımcı KIRMIZI döner (iki test). Parite listesi denetimi (`parity_gaps`): her rota için en az bir
`expect: local` istek, her istek bir rotaya düşer; sahte uyuşmazlıkla kırmızı.

`cops-parity requests/endpoints.json`: B1+ izleri her yeni rota için `"expect": "local"` istek ekler. Not: boş listeyle
`cops-parity` çıkış kodu 1 verir ("hiç istek koşmadı"); liste dolana dek canlı koşuda bu dosya kullanılmaz (`basic.json` değişmedi).

## 8. Boyut ve RSS

Ölçüm: release, `-p copsd` (canlı ile aynı biçim), geçici `--state-dir` + geçici `HOME` (scratch), loopback rastgele port,
kapalı upstream, token + küçük DB; açılıştan 0,5 sn sonra (boşta) ve 200x(`/api/steward/questions` + vekillenen istek) + metrik
uçları sonrası `/proc/<pid>/status`. Yalnız başlatılan PID kapatıldı. 3 tur, sırayla (taban, B0).

| İkili | Boyut (bayt) | VmRSS boşta (KB) | VmRSS yük sonrası (KB) |
|---|---|---|---|
| taban `da6e993c` | 5 716 376 | 6 052 - 6 356 | 6 436 - 6 868 |
| B0 | 5 891 624 (+175 248, +%3,1) | 6 120 - 6 464 | 6 708 - 6 760 |
| (bilgi) taban + `preserve_order` | 5 708 952 | 6 480 (1 tur) | 6 608 (1 tur) |

Bütçe (strangler planı bölüm 7, öneri): boşta RSS 20 MB altı: karşılanıyor. Fark gürültü düzeyinde. Yanıt gövdeleri
(`questions`, metrik hata gövdesi, `series`) iki ikilide bayt bayt aynı; `front_stats` ve `names` sayılar/sürüm dışında aynı.
Her iki ikilide de geçici `HOME` altında hiçbir dosya oluşmadı; durum dizinindeki dosyalar aynı. Koddan: `--state-dir`
verildiğinde token, gizli, DB, metrik DB, mount, `front_force_proxy`, `instances.json` yolları `state_path` ile o dizine
düşer; copsd'nin okuduğu diğer ortam değişkenleri yalnız `CLAUDEOPS_FRONT_SECRET`, `COPSD_LISTEN/UPSTREAM`,
`CLAUDEOPS_DIR` (B0: `CLAUDEOPS_DB_URL`, `CLAUDEOPS_STORE_BACKEND`, `HOME`, `PATH` da `StateDocs`/`SysEnv` ile).

## Kabul koşuları

Betik `~/.cargo-target/rs-gate/gate-logs/b0-gate.sh` (günlükler aynı dizinde, `b0-*`):
- `cargo test --workspace --no-fail-fast`: 1053 geçti, 0 kaldı, 1 yok sayıldı (tek koşu, oynaklık görülmedi).
- `cargo clippy --workspace --all-targets -- -D warnings`: temiz. `cargo fmt --all --check`: temiz.
- Eşlemeler `--check`: steward `map.py` (EKSİK 0), procscan `mapping.py` (2216 satır, EKSİK 0, hata 0), review `map_table.py`
  (temiz), hosts `mapping.py` (1310 satır, AÇIK 0, hata 0). Üretilen dosya güncellenmesi gerekmedi.
- Ayrıca özelliksiz yapılandırma: `cargo test -p copsd --no-fail-fast` hepsi geçti (`build_rerun` 1, `cli` 7, `ctx_front`,
  `force_proxy` 1, `route_force` 6, `state_ctx` 8, `state_dir` 4).
- Geliştirme sırasında bir kez `cargo test -p copsd -p cops-procscan` koşusunda `cops-procscan`
  `usage::tests::cache_first_none_then_value_and_error_keeps_last_good` düştü (5 sn zamanlama penceresi, yük altında;
  B0 değişikliğiyle ilgisiz); `--test-threads=1` ile 52/52, tam kapıda da geçti.
- `cargo tree -e features -i serde_json -p copsd`: `preserve_order` 0 satır.
- Python: dokunulmadı, koşulmadı (değişiklik Python'a dokunmuyor).

## Planda yanlış/eksik çıkanlar

- R1 "copsd steward-core'a bağlanınca birleşir": eksik. Birleşim bugün de `--workspace` derlemelerinde var; kapı copsd'yi
  özellikli sınıyor, canlı ikili özelliksiz. Anahtar sırası etkisi "değişebilir" değil: ölçüldü, değişiyor.
- R1 "cops-ent-auth testi sıralı anahtara dayanıyor": doğru (`golden::bloom_and_generations`, ölçüldü).
- R2 "Rust uçları yalnız OKUR (`StateDocs` ...)": `StateDocs`in okuma API'si yazıyor (yukarıda); `Instances`/`Roster`
  okuyucuları da. copsd ayrıca kendi DB'lerine ve `claudeops.db`ye (`rootrel_learned`) zaten yazıyor.
- B0 "`RouteCtx`a `Arc<StateDocs>`": salt okuma güvencesi için `Arc<ReadDocs>` (içinde tek `StateDocs`).
- B0 yolları "`cops-procscan/src/` (yalnız yapılandırma)": `cops-procscan/Cargo.toml`a `cops-state` satırı da gerekti.
- B1 "`cops-state` (`Instances`, `Roster`, `StateDocs`) + `cops-procscan`": R2 ile çelişiyor (bkz. bölüm 1); B1 yol listesine
  `cops-state` (salt okuma kipi) eklenmeli ya da `ReadDocs` + saf ayrıştırıcı.
- Bölüm 1 tablosu: `cops-procscan`un tüketicisi `cops-cli` (doğru); artık `cops-procscan` de `cops-state`e bağımlı.

## Doğrulanmayanlar

- Canlı çift üzerinde `basic.json` paritesi ve başsız tarayıcıda panel yüklemesi (8765/28765'e dokunulmadı; cops kapısı).
- `copsd-ent` (enterprise) yeni `RouteCtx` alanlarıyla derlemesi: `copsd-ent` `RouteCtx`i kurmuyor (grep), yalnız
  `copsd::state_dir`i çağırıyor; derlenmedi (rev yükseltmesi cops işi).
- `cops-ent-auth`ın üretim kodunda `serde_json::Map` sırasına dayanan yol olup olmadığı (yalnız test koşuldu).
- 60 sn CPU ölçümü (yalnız boyut ve RSS istendi).
- `ReadDocs`in Postgres `CLAUDEOPS_DB_URL`deki davranışı: `read_only_store` `Unsupported` döner, dosyaya düşülür (koddan; koşulmadı).
