# İz rs/rev: review çekirdeği (`py/claudeops/review.py` -> `rust/crates/cops-review-core`)

## Durum (26 Kas 2026 akşam): BİRLEŞTİRMEYE HAZIR DEĞİL

Yapılan:
- Crate yazıldı: `targets`, `planner`, `limits`, `prompts` (`LensRegistry` = `register_lens` karşılığı), `parse`, `redact`,
  `agy`, `paths`, `flow`, `store`, `report`, `export`, `py` (Python dil davranışları), `clock`, `error`.
- `cargo clippy -p cops-review-core --all-targets -- -D warnings` temiz.
- Parite düzeneği: `cargo test -p cops-review-core --test parity`. Python `review.py` işlevleri sarılır
  (`tests/py/parity_hook.py`); Python'un review testleri ve `tests/py/parity_edges.py` koşarken her çağrı Rust'a da sorulur
  (unix soket, `tests/support/mod.rs`); depo işlevlerinde dosyalar da karşılaştırılır. `HOME` ve `CLAUDEOPS_DIR` geçicidir.

Son ölçüm (26 Kas, `c5a666a` + ders testleri): 123.620 çağrı, 103 işlev (karşılaştırılmayan sarılı işlev yok), **0 fark**,
`cargo test -p cops-review-core` ve clippy temiz. Aşağıdaki 1. maddedeki farklar `c5a666a`de kapandı.

## Açık işler (sırayla)

1. Parite farkları: **kapandı** (`c5a666a`, 0 fark). Nedenler: `finding_key` Unicode sürümü (`src/unicode13.rs`, canlı
   Python 3.10 = Unicode 13; Python sürümü yükselirse tablo yeniden üretilmeli, ulak_31/yuhem sürümü ayrıca bakılmadı),
   `counts_as_attempt` artık `Result<bool>`, geri kalanı düzenek hatası.
2. Python testleri parite koşusunda temiz (rc=0); tüm stderr `<rapor>.stderr` dosyasında.
3. Gerçek veri paritesi: **koştu** (26 Kas, reviewer deposunun geçici kopyası, 174.853 çağrı, 0 fark; kopya silindi).
4. **Eşleme tablosu (sahip EK 2, zorunlu):** `ast` ile `review.py`deki her işlev/sınıf/sabit/regex (modül düzeyi ~188 ad)
   ve ilgili `py/tests` dosyalarındaki her `test_*` (~495, 39 dosya) için satır: Python adı (dosya:satır) | Rust karşılığı |
   parite testi | durum. Kancanın raporundaki `by_test` test -> karşılaştırılan işlev eşlemesini veriyor; tablo ondan
   üretilebilir. Boş ya da "sonra" satırı kalmayacak.
5. **Python dersleri** (`docs/rust-lessons-from-python.md`, bölüm 2.7 ve bölüm 3'ün 20 maddesi): her madde burada test adı
   ya da gerekçeyle karşılandı: "Python dersleri" bölümü (boş satır yok). Açık kalan: "Python hatası?" 5-7 sahibe.
6. Python testlerinde olup parite kancasının atladığı (review işlevi taklit edilmiş) çağrılar için karşılık kontrolü.
7. `rust/Cargo.lock` commit'siz (izin verilen yollar dışında); cops birleştirmede üretir.

## Kararlar

- Dal `rs/state` üstüne ileri sarıldı (`da8cee6`): `cops-state` (`Json`, `py_float_repr`, `StateDocs`) kullanılır.
  `rs/rev` birleşmeden önce `rs/state` birleşmeli.
- Kayıtlar tipli struct değil `cops_state::Json` nesnesi: anahtar sırası ve bilinmeyen alanlar bayt düzeyinde korunur.
- `serde_json preserve_order` açılmaz (workspace geneline yayılır).
- Depolar `statedocs` üzerinden: canlıda `store_backend=db`, `steward/` belgelerinde doğruluk kaynağı DB, dosya ayna.
- Kilit Python ile aynı dosyada: `<kimlik kökü>/.lock`, `flock`, 10 sn.
- Python'un istisna fırlattığı yerde Rust `Err` döner; sessiz düzeltme yok.

## Bilinen küçük sapmalar (tabloya işlenecek)

- Regex `\b`/`\w` Unicode tanımı iki motorda birleşik işaretlerde ayrışabilir (redaksiyon sınırı).
- `casefold` yerine küçük harf + `ß` -> `ss` (yalnız `finding_key`/`report_bodyless`).
- `cops-state` db kipinde kalıcı DB hatasında hiçbir yere yazmaz ve hata döner (Python dosyaya düşer); eşlenmemiş vekil
  karakterli JSON "bozuk" sayılır.

## "Python hatası?" (davranış aynen korundu, sahibe soruldu: TOBEDECIDED rs/rev maddesi)

1. Tek bozuk alan planlayıcıyı düşürür: `blocked_modes` (`until`), `migrate_r10_sub` (`started_at`, her
   `load_history`de), `requeue_stale_verify`, nesne olmayan çift kaydında `counts_as_attempt`.
2. `usage_summary` sayı olmayan `seconds`ta, `usage_cost_usd` UTF-8 olmayan dosyada istisna fırlatır.
3. `files` kipinde UTF-8 olmayan depo dosyası istisna; bozuk JSON ise yedeklenip boş sayılır ve sonraki yazım üstüne yazar.
4. `register_lens` sonunda satır sonu olan adı kabul eder (regex `$`).
5. `finding_key`: `file://` öneki `[:#]` bölmesinden SONRA silinmeye çalışılır, bölme önce `file`da keser: `file://a.py` ile
   `file` aynı anahtar, `a.py` farklı (ölü kod; kanıt `tests/lessons.rs::finding_key_normalizes_path_link_and_turkish_case`).
6. Durum zincirinde bilgi kaybı (review dersleri §3, lessons 2.7): `approve`/`reject` ve koşucunun `exported` geçişi önceki
   doğrulama sonucunu (verified/unclear/refuted) ayrı alanda saklamaz; yalnız `verdict` gerekçe metni kalır. Rust aynı
   (`tests/lessons.rs::decision_keeps_verdict_fields`). Öneri: `verdict_state` alanı, Python'da ayrı `fix:`.
7. `changed_after_review`: `git log -- <yol>` `--literal-pathspecs` olmadan; `[a].py` gibi glob karakterli ad `a.py`nin
   commit'ine de uyar ve bulgu yanlışlıkla "değişti" sayılır. Rust aynı argv'yi kullanır
   (`tests/py/parity_edges.py::TestEdges.test_git_changed_after_review`). Git stderr'i iki dilde de atılır (loglanmaz).

## Python dersleri (`docs/rust-lessons-from-python.md` 2.7 ve bölüm 3)

Test adları: `lessons` = `rust/crates/cops-review-core/tests/lessons.rs`, `git_timeout` = `.../tests/git_timeout.rs`,
`edges` = `.../tests/py/parity_edges.py`, `parity` = `.../tests/parity.rs::python_suite_and_edges_match` (Python testi koşarken
her `review.py` çağrısı Rust'a da sorulur; aşağıda adı geçen Python testleri `py/tests/` altında ve bu düzenekte karşılaştırılır).
Durum: **karşılandı** (test var), **kapsam dışı** (gerekçe + iz), **Python hatası?** (davranış korundu, yukarıdaki liste).

### 2.7 Review çekirdeği

| Madde | Karşılayan test ya da gerekçe | Durum |
|---|---|---|
| Detached koşu, `recover_on_start`, restart testi | kapsam dışı: süreç yönetimi ve kurtarma `commands/web_review.py`de (koşucu, T8); çekirdek yalnız `update_pair`/yan dosya yolları verir (`test_web_review_runner::TestRecover.*` parity altında `update_pair`/`finding_paths`i karşılaştırır) | kapsam dışı (T8) |
| Kurtarma: `.io.jsonl` silinmez, sonsuz `running` yok (`81bccf6`) | kapsam dışı: `IoLog`, `_mark_partial` koşucuda (T8); çekirdek tarafı `update_pair` `running`/`started_at` kuralı: `test_review::TestPathsAndStores.test_running_without_started_at_does_not_carry_old_window_attempts` (parity), `edges::TestStoreEdges.test_pair_lifecycle` | karşılandı (çekirdek payı), kalan T8 |
| Gövdesiz/başlıksız rapor `error`, bulgu kaydı yok (`c34395e`) | `lessons::bodyless_report_detected`; `test_web_review_runner::TestBodyless.test_report_bodyless_rule` (parity); `error` kararı ve kayıt atlama koşucuda (T8) | karşılandı (çekirdek payı) |
| Kota taraması modelin kendi metnini taramaz (`d6d5a0e`) | `lessons::quota_scan_ignores_model_text`; `test_review_limit_effort::LimitScanTextsTests.*` (4 test, parity); `edges::TestEdges.test_text_functions` | karşılandı |
| `hit your usage limit ... try again at` kota bloğu (`ca9a717`) | `lessons::usage_limit_try_again_at_blocks`; `test_review_codex_usage_limit::CodexUsageLimit.*` (5 test, parity) | karşılandı |
| Tekilleştirme anahtarı: yol, Markdown `where`, Türkçe İ/I (`412f5d3`, `ae0fe1d`, `fa5102d`) | `lessons::finding_key_normalizes_path_link_and_turkish_case`; `test_review_cleanup_fixes::FindingKeyTest.*`, `test_review::TestPathsAndStores.test_finding_key_folds_turkish_case_and_accents` (parity); `edges::TestEdges.test_unicode_finding_key` (0..0x3100 tüm kod noktaları) | karşılandı; `file://` öneki: Python hatası? 5 |
| Aynı raporun bulguları asla `dup` değil, `undup` (`57b9417`) | `lessons::same_report_never_dup_other_report_dup_and_undup`; `test_review::TestPathsAndStores.test_dedup_same_report_never_and_undup`, `test_dedup_canonical_prefers_live_over_refuted` (parity) | karşılandı |
| Durum zincirinde bilgi kaybı yok (exported olunca verified/refuted silinmesin) | `lessons::decision_keeps_verdict_fields` (karar yalnız `state`/`decided_by`/`decided_at`i değiştirir, `verdict` gerekçesi ve alan sırası kalır); `edges::TestStoreEdges.test_findings_lifecycle`; `exported` geçişi koşucuda (T8) | Python hatası? 6 (önceki durum ayrı tutulmuyor, Rust aynı) |
| `redact_secrets` corpus'u (tırnaklı, kaçışlı, DSN, JSON, `sk-proj`) | `lessons::redact_secrets_corpus` (sırrın çıktıda OLMADIĞINI doğrular); `test_review::TestRedactLeaks.*`, `TestDsnRedact.*`, `TestDsnEdgeCases.*`, `TestLearnedPasswordLength.*` (parity); `edges::TestEdges.test_fuzz_redact_and_findings` (4000 rastgele girdi) | karşılandı; `\b`/`\w` Unicode sınırı: "Bilinen küçük sapmalar" |
| Dışa aktarma öncesi tarama TOCTOU yok (`aee9a43`, `09ee5d4`) | kapsam dışı: tarama ile `git add` arası `review_store.py`de (`test_review_store::CommitTest.test_secret_written_between_scan_and_add_is_unstaged`), çekirdekte değil; review deposu aktarımı izi (T8) | kapsam dışı (T8) |
| `dest_guard` kapalı, GitLab `internal` private değil, görünürlük taze (`2e24a72`, `c0a27ac`) | kapsam dışı: `review_store.py` (`dest_guard`, görünürlük önbelleği); `test_review_store::*` o modülü sınar (T8) | kapsam dışı (T8) |
| Aktarım doğru depoya (`export_root`), silinmiş worktree'ye gitmez | `lessons::export_root_routes_and_never_follows_deleted_worktree`; `test_review_export_target_repo::TestExportRootPure.*`, `TestComboWorktree.*` (parity); `edges::TestEdges.test_export_functions` | karşılandı (Python gibi: prefix dizini HİÇ yoksa ve cwd git değilse cwd döner) |
| Geçici dosya benzersiz, `O_EXCL`, 0600 | çekirdek geçici dosya açmaz; depo yazımı `cops-state` `atomic_write_json` (`create_new` + pid/sayaç adı, rs/state izi); kip: `lessons::lock_is_bounded_and_private` (findings ve `.lock` 0600) | karşılandı |
| `git` çağrısı `-C <kök>`, `--literal-pathspecs`, stderr loglanır | `edges::TestEdges.test_git_changed_after_review` (gerçek depo, commit zamanı mtime'ı ezer, Python ile aynı sonuç); `git_timeout::hung_git_is_killed_and_reaped` (10 sn zaman aşımı, kill+wait, fd sızıntısı yok); `-C` var | Python hatası? 7 (`--literal-pathspecs` yok, stderr atılır) |
| Uzak proje doğrulama sürücüsü, "yerel klasör yok" sessiz atlanmaz (`06bb269`, `83b738f`) | kapsam dışı: `RemoteReviewDriver` ve doğrulama yönlendirmesi koşucuda (`test_review_remote_verify::*`, `test_review_findings_flow::TestVerify.test_remote_routed_to_its_host_unknown_rejected`; T8) | kapsam dışı (T8) |
| Üretim ≠ düzeltme: `review_backlog_max`, düzeltilen oran (L1) | eşik çekirdekte: `test_review_backlog::BacklogTest.test_backlogged_projects`, `test_next_review_skips_backlogged`, `test_count_open_review_lines` (parity); `edges::TestEdges.test_planner_random`; düzeltilen oran ölçümü/raporu koşucu ve panel işi (T8) | karşılandı (eşik), oran T8 |
| Log gürültüsü: "not ready/no target" tekilleştirme | kapsam dışı: çekirdek log yazmaz; olaylar `web_review` tick'inde (T8) | kapsam dışı (T8) |

### Bölüm 3 (genel liste)

| # | Madde | Karşılayan test ya da gerekçe | Durum |
|---|---|---|---|
| 1 | Hedef çözümü `Unique` | çekirdekte yıkıcı eylem yok; kimlikler tam anahtarla: `pair_key`, fid (`decide_finding` bilinmeyen fid `ok:false`: `edges::TestStoreEdges.test_findings_lifecycle`), `export_root` kayıtlı adı tam eşler (`lessons::export_root_...`) | karşılandı |
| 2 | Atomik yazım + kilit sözleşmesi | Python ile aynı `<kök>/.lock` flock + `cops-state` atomik yazım: `lessons::lock_is_bounded_and_private`, `edges::TestStoreEdges.*` (dosya baytları Python'la karşılaştırılır) | karşılandı |
| 3 | Okunamayan durum "yok" olmuyor | UTF-8 olmayan depo `Err`: `lessons::broken_inputs_fail_loud_or_backup`; bozuk JSON yedeklenip boş sayılır (Python davranışı) | Python hatası? 3 (bozuk JSON sonraki yazımda ezilir) |
| 4 | Eylem sonucu doğrulanır, negatif test | `decide_finding` `ok:false` yolları `lessons::decision_keeps_verdict_fields`; `update_pair` geçersiz durum `Err`: `edges::TestStoreEdges.test_pair_lifecycle`; `apply_verdicts` uygulanan listesi döner | karşılandı |
| 5 | Hata yutma yok | denetim: `let _ =` yalnız zaman aşımındaki `kill/wait` (`git_timeout`) ve `corrupt_backup` mtime (Python `_corrupt_backup` da yutar); `.ok()?` yalnız Python'un `except OSError` dalları (`stale_reason`, `mtime`); `unwrap_or_default` yalnız saat biçimi/`cwd`; sayaç/log koşucuda | karşılandı (Python'la aynı yutma noktaları; sayaç T8) |
| 6 | Bayat önbellek/ayar | çekirdekte önbellek yok; ayar (`ReviewConfig`), katalog (`claude_catalog_from`) ve mercekler (`LensRegistry`) her çağrıda çağırandan gelir | karşılandı (yapısal) |
| 7 | Döngü/bekleme sınırlı | kilit 10 sn (`lessons::lock_is_bounded_and_private`), git 10 sn (`git_timeout::hung_git_is_killed_and_reaped`); başka döngü dış kaynak beklemez | karşılandı |
| 8 | Dış CLI davranışı fixture'lı | agy/copilot/codex çıktı örnekleri: `test_review_copilot_quota::*`, `test_review_slots::AgyUsageBlocksTest.*`, `test_review::TestRedactLabel.test_agy_label` (parity), `edges::TestEdges.test_text_functions`/`test_blocks_agy_copilot`; çekirdek CLI'ya gönderim yapmaz | karşılandı |
| 9 | Alt süreç sahibi, kapanış, fd sızıntısı | tek alt süreç `git`: stdin/stderr `null`, zaman aşımında kill+wait; `git_timeout::hung_git_is_killed_and_reaped` (fd sayısı ve süreç biçimi denetlenir) | karşılandı |
| 10 | Girdi sınırları (boş, negatif, NaN, bozuk UTF-8, tip hatalı JSON) | `edges::TestEdges.*` (TEXTS/SPECS, `window_seconds` NaN/inf, `test_planner_random` 2500 rastgele bozuk kayıt), `edges::TestStoreEdges.test_broken_files`/`test_roundtrip_formats`, `lessons::broken_inputs_fail_loud_or_backup` | karşılandı; tek bozuk alan planlayıcıyı düşürür: Python hatası? 1 |
| 11 | Metin işaret ayrıştırma tek modülde, corpus'lu, altın vektör | `parse.rs` (bulgu/verdict), `limits.rs` (kota), `redact.rs`; Python eşliği `parity` (68 bin+ çağrı) ve `edges::TestEdges.test_fuzz_redact_and_findings` | karşılandı |
| 12 | Paylaşılan kural diferansiyel testle, `$HOME` doğrudan yok | tüm `review.py` işlevleri `parity` ile; crate `HOME`/ortam okumaz (yollar çağırandan: `ReviewPaths::for_sid(state_dir, ...)`) | karşılandı |
| 13 | Sırlar `Secret<T>`, log/argv sızıntısı yok | çekirdek sır tutmaz, log yazmaz; rapor/çıktı maskeleme `lessons::redact_secrets_corpus`; argv/kimlik matrisi koşucu ve auth izinde | kapsam dışı (T8 / auth izi), maskeleme karşılandı |
| 14 | Yol girdileri `..`/symlink/mutlak | `where_relpath` mutlak ve `..`yu reddeder, `where_file` realpath kökün altında olmalı: `test_review_duration_summary::StaleTextTest.test_where_relpath` (parity), `edges::TestEdges.test_export_functions` (`/etc` symlink, `../a.py`), `edges::TestEdges.test_paths` (symlink bulgu dosyası) | karşılandı |
| 15 | Vekil/WS e2e | kapsam dışı: çekirdekte ağ/vekil yok (copsd/cops-proxy izleri) | kapsam dışı (rs/gate) |
| 16 | Yeni uç/route tabloları | kapsam dışı: çekirdek uç eklemez; review API uçları koşucu taşınırken (T8) | kapsam dışı (T8) |
| 17 | Test yalıtımı, canlı dizin değişmez | `parity` geçici `HOME`/`CLAUDEOPS_DIR` + `run_parity.py` canlı dizini reddeder; `tempfile` RAII; `git_timeout` `PATH`i yalnız kendi ikilisinde değiştirir | karşılandı |
| 18 | Uzak host sürüm/devre kesici | kapsam dışı: çekirdekte uzak çağrı yok (`RemoteReviewDriver`, federasyon: T8 / rs/hosts) | kapsam dışı (T8) |
| 19 | İkili sürümü, canlı=HEAD, geri dönüş | kapsam dışı: crate kütüphane, ikili ve canlıya alma cops birleştirmesinde (sprint planı "Sahip eki") | kapsam dışı (cops birleştirme) |
| 20 | Ölçümsüz iddia yok, `--dry-run` yan etkisiz, Python'a yeni özellik yok | bu izde `py/` değişmedi; Python'a dair her iddia ölçümle (bu bölümdeki beklenen değerler Python'dan koşturularak alındı); çekirdekte `--dry-run` yok (`lens=dry` yalnız istem/yol: `edges::TestEdges.test_paths`) | karşılandı |

## Koşucu arayüzü (bu izde YOK; koşucu taşınırken, T8)

Plan eki (sahip q20261126_140456_8f77, TBD#357): koşucu her koşuda `--usage-log` ve durum çıktısı üretir.
- Kullanım günlüğü: raporun yanında `<ts>.usage.jsonl`; satır başına JSON, `report::usage_summary` /
  `report::usage_cost_usd` şunları okur: `event` (`task_start` + `model`, `request`), `t` (ms), `seconds`,
  `usage.{prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens, total_tokens, input_tokens, output_tokens,
  cache_read_input_tokens, cache_creation_input_tokens}`.
- Durum çıktısı: biçim henüz kararlaştırılmadı (TBD#357'de yeni soru açık). Çekirdek durumu yalnız
  `ReviewStore::update_pair` ile yazar; yan dosya yolları `paths::{draft_path, partial_path, error_path, finding_path}`.
- Koşucu bir `LensRegistry` kurup eklentilerin merceklerini ona kaydeder; `claude_catalog` için `statedocs`
  `claude_models` belgesini okuyup `targets::claude_catalog_from`a verir.
