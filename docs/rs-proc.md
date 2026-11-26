# rs/proc: cops-procscan (Rust sprinti W1-pre, süreç taraması)

Durum (26 Kas 2026 gece): kod, testler, altın vektörler ve canlı parite koşucusu var. Eşleme tablosunda ([rs-proc-mapping.md](rs-proc-mapping.md)) EKSİK satır yok (`--check --strict` 0). TBD#365 uygulandı: "Python hataları" listesindeki maddeler hem Python'da (ayrı `fix:` commit'i, kırmızı-sonra-yeşil test) hem Rust'ta düzeltildi; Rust bozuk kaydı atlayıp sayar. Birleştirme için açık: sohbet geçmişi okumanın izi bir VARSAYIM (cops onayı bekler, aşağıda); parite koşucusunun `cops-parity`ye geçişi (Açık işler).

## Kapsam (taşınan)
| Python | Rust (`rust/crates/cops-procscan/src`) |
|---|---|
| `discovery.py` | `discovery.rs`, `session.rs`, `status.rs` |
| `providers/*` matches_proc/extract_name/extract_info | `providers.rs` |
| `session.py` | `session.rs` |
| `mirrors.py` | `mirrors.rs` |
| `commands/ls.py` | `list.rs`, `bin/cops-procscan.rs` |
| `needs_ho.py` | `needs_ho.rs` |
| `session_usage.py` (+ `model_usage._family`) | `usage.rs` |
| `tmux_backend.is_tmux_backed`, `web._ucli_flags/_usage_total/_process_started_at` | `status.rs` |
| `claude_provider._encode_cwd/jsonl_path_for` | `transcript.rs` |
| `paths.parse_proc_stat/proc_ppid` | `procfs.rs` |

**Varsayım (cops onayı bekler):** sohbet geçmişi okuma işlevleri (`last_exchange`, `full_history`, `sid_for_stopped_session` ve yardımcıları, testleriyle) bu crate'in kapsamı DIŞINDA sayıldı ve T1'e (`/api/status` ve sohbet okuma) yazıldı. Sprint planında bunlar için ayrı satır yok; cops başka iz verirse tablo verisi (`mapping.py` `CHAT`) değişmeli.

İkili (salt okur): `cops-procscan list|ls [--json] [--no-cpu] [--base AD]`, `scan [--no-cpu]` (çıktıda ayrıca `diag`, `agy_learned`), `usage DOSYA`, `needs-ho DURUM_DIZINI CWD [JSONL]` (tek yazımı yok; git'i yalnız okur).

## Ölçüm
- `cargo test -p cops-procscan`: **78 test** (46 birim, 22 sahte `/proc`, 6 altın vektör, 2 gerçek süreç, 1 alt süreç yaşam döngüsü, 1 git); `clippy --all-targets -D warnings` ve `fmt --check` temiz (26 Kas gece, TBD#365 sonrası).
- Altın vektörler (`parity/gen_golden.py` -> `tests/golden/`, Python 3.10.12): RFH 39, taban/yedek ad + cwd kodlama + `fmt_tokens` 54, `committed_after` 1155 çift, sağlayıcı tanıma + `extract_info` 50 argv, watch hedefi 20, transkript fikstürü 28 (iki işlev), kullanım fikstürü 23 (iki ardışık çağrı). Tek bilinen fark: `nan_line` (sapma 4), testte adıyla listeli.
- Canlı parite (`parity/run.py`, 26 Kas akşam, bu makine): sayılar "Parite koşucusu" bölümünde.
- Tarama maliyeti: 636 süreç, release `list --no-cpu` 0,06-0,11 sn (3 koşu, 26 Kas öğle). Parite koşusunun tamamı 3-6 dk (çoğu Python içe aktarma + 120 transkriptin iki dilde okunması).

## Kararlar
- Başka kullanıcının sürecinden yalnız `status` okunur (tip kapısı `OwnProc`); FIFO testi içerik okunmadığını sınar.
- Crate durum dosyası yazmaz; tek yazım `NeedsHo::repo_baseline_set` (çağıranın verdiği dizin).
- Süreç kimliği `ProcId{pid,start_time}` (`Session.proc_id`, JSON'a yazılmaz). Eylemden önce `ProcFs::verify` `Liveness::Same` dönmeli; `Replaced`/`Gone`/`NotOwn`/`Unknown` ayrı. Crate sinyal göndermez.
- Süreç öldürme yalnız `proc_cmd::ChildGuard` (kendi git/wmctrl çocuğu; `Drop`ta kill+wait). Crate düzeyi `clippy.toml` `disallowed-methods`: `libc::kill/killpg/tgkill/raise`, `std::process::Child::kill` (tek izinli yer `allow` ile işaretli). Denendi: eklenen bir `libc::kill` çağrısı clippy'yi kırdı.
- Üretim kodunda `unwrap/expect/panic` `deny` (testler hariç).
- Yutulan hatalar `Scan.diag` (`ScanDiag`) sayaçlarında: okunamayan `/proc` kökü (`proc_root_error`), okunamayan `sessions/` (`sessions_dir_error`; yokluğu hata değil), kaybolan/okunamayan süreç, okunamayan cmdline/cwd/stat, okunamayan ya da geçersiz oturum dosyası, kökü nesne olmayan ya da `name`i dizgi olmayan oturum dosyası (`session_files_bad`, TBD#365), bozuk agy dosyası. Davranış ve JSON çıktısı Python gibi kalır.
- Bozuk kayıt sayaçları (TBD#365): transkript kararları `needs_ho::Checked{value, skipped}` döner (nesne olmayan satır, nesne olmayan `message`, dizgi olmayan `text` bloğu); kullanım `Usage.skipped_rows` (JSON'a yazılmaz; dosya başına `FileState.bad`). Python karşılıkları süreç geneli `_skipped` sayaçları (`discovery`, `needs_ho`, `session_usage`); log'a yazılmaz (tarama her tick'te koşar, aynı bozuk dosya log'u taşırırdı).
- Yeni bağımlılıklar: `libc`, `regex`, `sha1`, `serde` (`rust/Cargo.lock` da değişti).

## Python'dan bilinen sapmalar
1. `jsonl_path_for`: "cwd'deki en yeni dosya" düşüşü YOK (iz görevi böyle istedi). Python `_usage_total` sid dosyası yoksa başka oturumun sayacını gösterebilir (parite koşucusu bu düşüşe giren oturumları ayrıca sayar ve karşılaştırmaz).
2. Alt kabuk ata zinciri (`_ancestors`, yalnız `stat` okur) başka kullanıcının sürecinde durur, Python geçer: gizlilik kuralı. tmux ata yürüyüşü artık sapma DEĞİL: Python `is_tmux_backed` de başka kullanıcının atasında durur, cmdline'ını okumaz (Python düzeltildi: 6ae5da3).
3. agy sid öğrenme yazılmaz; `Scan::agy_learned` döner. Yazım `cops-state` ile (T1) yapılmadan `/api/status` Rust'a alınmamalı. `agy_sids` DB yerine dosya aynasından okunur.
4. serde farkları: `NaN`/`Infinity` ve 128'den derin JSON reddedilir. Transkriptte `NaN` içeren satır Python'da sayılır, Rust'ta atlanır (altın `nan_line`, parite koşucusunda `known_deviation`). claude transkriptlerini Node `JSON.stringify` yazar, bu belirteçleri üretmez. Yinelenen anahtar Python gibi son değeri alır (altın `dup_keys`, transkript ve kullanım).
5. `procStart`/pid gibi alanlarda dizi/nesne değerlerinin `str()` yazımı birebir değil (yalnız eşitlik denetimi).
6. Unicode rakamlar: Python `int("٣")`/`float("١")` kabul eder (oturum dosyasında dizgi pid, transkriptte dizgi token sayısı, `--max-cost-usd`); Rust yalnız ASCII.
7. `fromisoformat` Python 3.10 kuralıyla (yerel yorumlayıcı 3.10.12). 3.11+ (`Z`, `+0300`, kısa biçimler) kabul eder: başka sürümlü uzak hostta Python sonucu farklı olabilir.
8. Canlılık: Python `os.kill(pid, 0)` çekirdek kuralı (gönderen uid = hedefin gerçek YA DA saklı uid'i); Rust yalnız gerçek uid'e bakar. Fark yalnız başka kullanıcının çalıştırdığı, saklı uid'i bize ait süreçte.
9. `--max-cost-usd` `NaN`/`inf`: Python `float` kabul eder ve `json.dumps` geçersiz JSON (`NaN`) yazar; Rust değeri kabul eder, serde `null` yazar. `_ucli_flags`ın pid başına süresiz önbelleği (pid yeniden kullanımında bayat rozet) Rust'ta yok (önbellek T1'in işi).
10. Artık sapma DEĞİL (numara korunuyor): arka plan iş parçacığı başlatılamazsa iki dil de `None` döner ve `running`i geri alır, sonraki çağrı yeniden dener (Python düzeltildi: 6ae5da3; Rust testi `usage::tests::spawn_failure_does_not_lock_the_path`).
11. Kullanım önbelleği taşması artık sapma DEĞİL (numara korunuyor): iki tablo da Python `dict` gibi ekleme sırasını tutar (`usage::Ordered`) ve en eski eklenenleri atar (dosya durumu 1, özet 200). Testler `usage::tests::file_cache_evicts_in_insertion_order`, `summary_cache_evicts_oldest_200`; aynı senaryolar 26 Kas'ta Python `session_usage` üzerinde elle koşuldu, sonuç aynı (bir kerelik denetim, parite koşucusunda adım değil). Küçülen dosya artık iki dilde de yer açtırmaz (Python düzeltildi: 6ae5da3; Python testi `test_procscan_tbd365.UsageRowsTest.test_shrinking_file_does_not_evict_another_when_full`).
12. `HOME` tanımsızsa `Config::from_env` `None` döner; Python `expanduser` parola veritabanına düşer.
13. `Scan.mirrors` her taramada doldurulur (Python'da yalnız `mirrors_out` verilirse).

## Python hataları (TBD#365, sahip 26 Kas: ikisi de düzelsin)
Her madde Python'da ayrı `fix:` commit'inde kırmızı-sonra-yeşil testle (`py/tests/test_procscan_tbd365.py`, 14 test, düzeltmeden önce 14'ü de kırmızı) ve Rust'ta aynı güvenli davranışla düzeltildi. Altın vektörler yeni Python davranışından yeniden üretildi (altında Python istisnası kalmadı).
- Nesne olmayan ya da `name`i dizgi olmayan `sessions/*.json` tüm taramayı düşürüyordu. Şimdi dosya atlanır ve sayılır (Python `discovery._skipped["session_file"]`, Rust `ScanDiag.session_files_bad`; `ScanError` kaldırıldı, `find_sessions` hata döndürmez). Python düzeltildi: 6ae5da3
- Transkriptte nesne olmayan satır / nesne olmayan `message` / dizgi olmayan `text` `needs_ho`yu istisnayla bitiriyordu. Şimdi satır (ya da dizgi olmayan blok) atlanır ve sayılır; aynı satırın dizgi blokları sayılmaya devam eder, önceden düşmeyen girdide sonuç değişmez (Python `needs_ho._skipped["transcript_row"]`, Rust `Checked.skipped`; `BadTranscript` kaldırıldı). Python düzeltildi: 6ae5da3
- Kullanım toplamı `None` oluyordu (dizgi olmayan doğru `message.model`; tur anahtarında hashlenemeyen `message.id`/`requestId`/`uuid`; ana ya da herhangi bir alt ajan dosyasında). Şimdi yalnız o satır atlanır ve sayılır, toplam ilk çağrıda doğru (Python `session_usage._skipped["usage_row"]`, Rust `Usage.skipped_rows`). Aynı `_from_row`u kullanan gün dökümü (`day_usage`) de artık bozuk satırda dosyanın kalanını kaybetmiyor. Tur anahtarı Python sözlük eşitliğiyle (`1 == 1.0 == true`) birebir kaldı. Python düzeltildi: 6ae5da3
- Dolu dosya önbelleğinde (2000) küçülen transkript en eski başka girdiyi attırıyordu. Şimdi yalnız yeni girdi yer açtırır, küçülen dosya yerinde sıfırlanır (zararsızdı; düzeltme bir satır). Python düzeltildi: 6ae5da3
- `cached_usage_for_path` iş parçacığı başlatamazsa `running` açık kalıyor, yol bir daha yenilenmiyordu. Şimdi bayrak geri alınır (Rust zaten böyleydi; Rust'a sınamak için test kancası eklendi). Python düzeltildi: 6ae5da3
- `needs_ho` baseline yazımı atomik değildi. Şimdi Python `atomic_json.atomic_write_text`, Rust `needs_ho::write_atomic` (aynı dizinde `O_EXCL|O_NOFOLLOW` geçici dosya, `fsync`, `rename`). Python düzeltildi: 6ae5da3
- `sid` yol parçası olarak süzülmüyordu (`jsonl_path_for`). Şimdi `/` ya da NUL içeren sid yok sayılır (Python NUL'da `ValueError`la da düşüyordu); Python'da sid yokmuş gibi eski tahmine düşer (sapma 1 aynen). Python düzeltildi: 6ae5da3
- Python başka kullanıcının süreç İÇERİĞİNİ okuyordu: `process_iter(["pid","cmdline","uids"])` (`find_sessions`, `mirrors.running_mirrors`) uid süzgecinden önce herkesin cmdline'ını çekiyordu; `is_tmux_backed` başka kullanıcının atasının cmdline'ını okuyordu. Şimdi `process_iter(["pid","uids"])` + yalnız kendi sürecinde `cmdline()`; tmux yürüyüşü başka kullanıcının atasında durur. Sonuç değişmez (bizim `tmux -L cops` sunucumuz bizimdir). Rust zaten böyleydi. Python düzeltildi: 6ae5da3
- Negatif/sıfır `pid`li oturum dosyası Python'da `os.kill(<=0, 0)` ile süreç GRUBUNU yokluyor, canlı sanılabiliyordu. Şimdi atlanır (Rust zaten atlıyordu). Python düzeltildi: 6ae5da3

Düzeltilmeyen: yok. Not: Python `_ancestors` (alt kabuk katlama) başka kullanıcının `stat`ını okumaya devam eder; bu listede değildi, içerik değil, sapma 2'de kalır.

## Parite koşucusu (`rust/crates/cops-procscan/parity/`)
- `pyenv.py`: `CLAUDEOPS_DIR` claudeops import edilmeden önce geçici dizine, `CLAUDEOPS_EXTENSIONS` boş, `GIT_OPTIONAL_LOCKS=0`, bayt kodu yazılmaz. Audit hook geçici dizin dışına her yazma açılışını, silme/taşıma/dizin oluşturmayı, sqlite bağlantısını ve sinyali durdurur (ilk denemede `py/**/__pycache__` yazımlarını da yakaladı). `os.kill(pid,0)` sinyalsiz taklitle değişir; psutil'in başka kullanıcının cmdline/environ/cwd okuması engellenir. `web.py` içe aktarılmaz (bağımlılıkları yok): `_ucli_flags` kaynağından ast ile derlenir.
- Kod okuması (yazım yolları): `discovery`/`providers` keşif yolunda tek yazım `agy_provider._remember_agy_sid` (koşucuda yazmayan kayıtçıyla değişir, Rust `agy_learned` ile karşılaştırılır); `session_usage` yalnız bellek önbelleği; `needs_ho` yalnız `repo_baseline_set` (fikstürde geçici dizine bilerek çağrılır); `statedocs.read_json` `dual` kipte DB'ye yazabilir: DB geçici dizindedir.
- `gen_golden.py`: altın vektörleri üretir (`tests/golden/`, `.gitattributes` `-text`: CRLF ve bozuk UTF-8 fikstürleri bayt bayt korunur).
- `run.py`: `list` (JSON + tablo), `scan` (oturum alanları + türetilmiş alanlar + mirrors/duplicates/orphans/agy_learned), gerçek transkriptlerde usage ve transkript işaretleri, fikstür depolarında ve canlı oturum cwd'lerinde needs_ho. Rust Python'dan önce ve sonra koşar; fark iki görüntüde de varsa kalıcı. Çıktı yalnız sayı ve alan adı. Koşum: `python3 -I rust/crates/cops-procscan/parity/run.py`.
- Son koşu (26 Kas gece, TBD#365 sonrası, iki koşu, ikisi de çıkış 1, süre 2-6 dk): tek kalıcı fark `scan` `usage_total` (koşu 1'de 2, koşu 2'de 1 satır); diğer her şey eşit. Neden canlı filo: Python kullanımı iki Rust görüntüsünün ARASINDA okur, o sırada yazmakta olan oturumun transkripti büyürse Python değeri iki görüntüden de farklı çıkar. Kanıt: aynı oturum transkriptleri, okuma boyunca boyutu değişmeyenlerle sınırlanıp üç kez karşılaştırıldı (28-29 dosya), fark 0; `usage_real` (123 transkript) fark 0. Koşucunun karşılaştırma kuralı gevşetilmedi; bu fark `cops-parity`ye geçişte (Açık işler) boyut damgalı karşılaştırmayla kapatılmalı.
  - `list --json --no-cpu`: Python 29, Rust 29/29 satır, kalıcı fark 0; tablo bir Rust görüntüsüyle aynı (33 satır).
  - `scan`: mirrors (5), duplicates, orphans, agy_learned eşit; Python en-yeni-dosya düşüşü 0; Python'un engellenen yazımı 0.
  - transkript işaretleri: 123 x 3 fark 0. needs_ho: 1276 fikstür durumu x 4 sinyal fark 0 (14 bilinen `nan_line`), canlı 29 cwd x 4 sinyal fark 0.
  - Koşucu değişikliği: fikstür baseline'ı artık Python ad/içerik kuralıyla (`_repo_key`, `rev-parse HEAD`) düz yazılıyor; `repo_baseline_set`in `atomic_write_text`i (`os.fdopen`) pyenv korumasına takılıyordu, koruma gevşetilmedi.

## Test eşlemesi (Python testi -> Rust)
Dosya düzeyi özet. Test durumu düzeyinde bağlayıcı olan [rs-proc-mapping.md](rs-proc-mapping.md).
| Python | Rust |
|---|---|
| test_discovery_sid | `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan`, `discovers_each_cli_and_names`, `is_fresh_without_json_entry_for_every_cli`, `session::tests::is_fresh_flag_and_sid_combinations` |
| test_discovery_bg_fold (fold) | `session::tests::background_folds_into_single_front`, `background_fold_edge_cases_like_python`, `fake_proc::background_session_folds`; KillBgTests: kapsam dışı (kill, T4) |
| test_discovery_subshell | `session::tests::subshell_tree_like_python`, `subshells_fold_only_for_shell`, `real_proc::real_background_subshell_is_one_session` |
| test_ls_json | `list::tests::*`, canlı parite `list_json`/`list_table` |
| test_mirror_marker (note/spec/gerçek süreç) | `mirrors::tests::*`, altın `mirror_spec`, `real_proc::real_viewer_process_is_seen`, `fake_proc::mirrors_terminal_and_ucli_flag_edges`; panel işaretleme satırları kapsam dışı (web, T1) |
| test_mirror_window (mirrors kısmı) | `mirrors::tests::focus_reports_exit_status_and_passes_exact_args`, `fake_proc::mirrors_terminal_and_ucli_flag_edges`; pencere açma/döşeme kapsam dışı (web/watch) |
| test_orphan_cli | `discovery::tests::fallback_names`, altın `fallback_name`, `fake_proc::tmux_terminal_and_orphans`, `mirrors_terminal_and_ucli_flag_edges` (fd/0 okunamaz) |
| test_proc_stat_parse | `procfs::tests::stat_with_parens_in_comm`, `fake_proc::own_ppid_from_real_proc` |
| test_rfh_marker | `needs_ho::tests::*`, altın `rfh` |
| test_triage_fixes_20261107 (needs_ho) | `needs_ho::tests::only_assistant_rows_carry_the_marker`, altın `transcripts` |
| test_review_fixes_2026_11_04 (committed_since) | `needs_ho::tests::iso_times_compare_as_instants`, altın `committed_after`, `needs_ho_git` |
| test_session_usage | `fake_proc::usage_dedups_subagents_and_increments`, `usage::tests::*` (UsageCache, tahliye sırası, bozuk satır sayacı, anahtar eşitliği, fmt_tokens), altın `usage` |
| test_procscan_tbd365 (TBD#365) | `fake_proc::bad_session_files_are_skipped_and_counted`, `other_users_processes_are_never_read`, `transcript_requires_exact_sid`, `needs_ho::tests::broken_input_is_skipped_and_counted`, `needs_ho_decides_with_bad_rows`, `baseline_is_written_atomically`, `usage::tests::bad_row_is_skipped_and_counted`, `spawn_failure_does_not_lock_the_path`, `file_cache_evicts_in_insertion_order`, altın `transcripts`/`usage`; `day_usage` kapsam dışı (T7) |
| test_usage_cli | `usage_for_path`/`fmt_tokens` (yukarıda), `fake_proc::probe_usage_total_claude_exact_sid_without_blocking`; CLI tablosu kapsam dışı (T6) |
| test_proc07_io_ucli_not_fleet (matches_proc) | `providers::tests::detect`, altın `detect_info`; `_io_ask` kapsam dışı (web) |
| test_web_ucli_flags | `fake_proc::ucli_flags`, `ucli_flags_all_set`, `ucli_flags_lost_process_is_none_and_not_cached`, `mirrors_terminal_and_ucli_flag_edges`, `py::tests::python_string_rules` (`float`); `tools` alanı ve pid önbelleği kapsam dışı (T1) |
| test_ucli_web (ayrıştırma yönü) | `providers::tests::ucli_effort_presets`, `ucli_effort_unknown_when_any_limit_changed_or_missing`, `ucli_every_preset_without_context_flag`, altın `detect_info`; argv üretimi kapsam dışı |

## Açık işler
- [x] Eşleme tablosu (sahip EK 2): [rs-proc-mapping.md](rs-proc-mapping.md), üreten ve denetleyen `rust/crates/cops-procscan/parity/mapping.py`. 536 tanım (144 karşılandı, 392 kapsam dışı, 0 EKSİK); 115 test dosyasında 1552 test durumu (93 karşılandı, 1459 kapsam dışı, 0 EKSİK).
  - Koşum (repo kökünden): `python3 -I rust/crates/cops-procscan/parity/mapping.py` yazar; `--check` tabloyu `ast` ve Rust kaynağıyla karşılaştırır (eksik/fazla/boş satır, uydurma Rust adı, bayat tablo ya da veri = çıkış 1); `--check --strict` EKSİK varken de 1 döner. `py/` modülleri içe aktarılmaz.
  - Sınır: betik adların varlığını sınar, testin davranışı kapsadığını sınamaz ve testleri koşturmaz. Crate davranışını sınamayan test dosyaları dosya başına gerekçe/izle girildi (adet + ad özeti; dosya değişince betik durur, `--pins` yeni özeti basar).
- [x] Eşleme tablosundaki 13 EKSİK kapandı: Rust testleri yazıldı; iki davranış Python'a eşitlendi (önbellek tahliye sırası; `ucli_flags` `cmdline`ı okunamayan süreçte artık "bütün bayraklar kapalı" yerine `None`).
- [ ] Sohbet geçmişi okumanın izi: T1 varsayıldı ("Kapsam" bölümü), cops onayı bekliyor.
- [x] TBD#365: "Python hataları" maddeleri iki dilde düzeltildi (yukarıda; Python `fix:` commit'i 6ae5da3).
- [ ] Parite koşucusu: canlı filoda `scan` `usage_total` karşılaştırması büyüyen transkriptte yanlış fark üretiyor (yukarıda); boyut damgalı karşılaştırma gerekli.
- [ ] Parite koşucusu: rsgate'in `cops-parity`si (`rs/gate`) main'e birleşince `parity/run.py` yerine ona geçilecek (sahip, TBD#365 cevabı). O zamana dek kapı `parity/run.py`.
- [ ] `ProcId` doğrulamasını kullanan kill yolu T4'te (crate yalnız tipi ve `verify`ı sağlar).
- [ ] Tick içi tarama maliyeti T1'de `/api/status`a bağlanınca ölçülmeli (CPU kipi +0,3 sn bekler).
- [ ] `Config::from_env` `$HOME`/`$CLAUDEOPS_DIR`i doğrudan okur; `cops-state` birleşince `state_dir()` oradan alınmalı (H14).

## Ders listesi karşılığı (`docs/rust-lessons-from-python.md`, 26 Kas)
T = `tests/fake_proc.rs`, R = `tests/real_proc.rs`, C = `tests/child_lifecycle.rs`, G = `tests/golden.rs`, birim testleri `modül::tests::ad`.

### 2.4 cops-procscan
| Madde | Durum | Test / gerekçe |
|---|---|---|
| `ProcId{pid,start_time}`, sinyalden önce doğrulama | karşılandı (tip + doğrulama); kill T4 | `Session.proc_id`, `ProcFs::verify`; T `sessions_carry_proc_id_and_verify_detects_reuse` (Same/Replaced/Gone/NotOwn/Unknown), R alt kabuk testi gerçek süreçte Same -> Gone. CPU örneklemesi pid yeniden kullanımını `starttime` ile eler. |
| EPERM/ESRCH, yalnız kendi UID | karşılandı | `kill(pid,0)` yok; `ProcFs::access` (Own/NotOwn/Gone/Unreadable); T `other_users_processes_are_never_read` |
| Tüm taramalar UID süzgeçli | karşılandı | aynı test; `mirrors::running_mirrors` de `own_processes`; T `mirrors_terminal_and_ucli_flag_edges` (başkasının görüntüleyicisi) |
| `kill` tek modül, lint ile yasak | karşılandı (crate düzeyi) | `clippy.toml` `disallowed-methods`; tek istisna `proc_cmd::ChildGuard`. Workspace geneli lint T4'te. |
| Alt süreç kill+wait, zombi testi | karşılandı | `ChildGuard` `Drop`ta kill+wait; `proc_cmd::tests::guard_reaps_on_drop`; C 100 koşu (başarı + zaman aşımı + kapalı stdout + torun): biçilmemiş çocuk 0, zombi 0, fd farkı 0. Torun boruyu tutarsa okuyucu iş parçacığı torunla yaşar (Python `subprocess.run` ile aynı, belgelendi). |
| app-server ve alt kabuk ikinci satır üretmez | karşılandı | `providers::tests::detect`, altın `detect_info` (codex alt komutları), `session::tests::subshell_tree_like_python`, R `real_background_subshell_is_one_session`. app-server ÇOCUĞU Python keşfinde de elenmez (`orphan_watch`, T7). |
| Hayalet tmux oturumu | kapsam dışı | spawn/tmux işi: W0-b + T4. |
| Tarama maliyeti ölçülür | KISMİ | 636 süreç, release 0,06-0,11 sn. Tick içi maliyet T1'de. |
| %50/10 dk yanlış pozitif | karşılandı | T `tmux_terminal_and_orphans` |

### 3. Birleştirme öncesi 20 madde
| # | Durum | Test / gerekçe |
|---|---|---|
| 1 | karşılandı | yıkıcı eylem yok; transkript yalnız tam sid: T `transcript_requires_exact_sid`; `find_by_name` tam ad; `ProcId` |
| 2 | karşılandı | tek yazım `repo_baseline_set` atomik (`write_atomic`), Python da (TBD#365); `needs_ho::tests::baseline_is_written_atomically` |
| 3 | karşılandı | `ScanDiag` okunamayan `/proc` kökünü ve `sessions/`i "yok"tan ayırır; `Liveness::Unknown`, `Access::Unreadable`; T `unreadable_roots_are_not_absence`. Git hatası "temiz" sayılır (Python aynı; sinyal yalnız devir önerisi). |
| 4 | uygulanmaz | crate eylem yapmaz (`focus_window` sonucu döner, negatif test var) |
| 5 | karşılandı | yutulan okuma hataları `ScanDiag` sayaçlarında; agy dosyası `AgyState::unreadable`; T `broken_proc_fields`, `broken_agy_files`. Log yok (kütüphane; sayaçları çağıran yayımlar). |
| 6 | karşılandı | ayar/sır önbelleği yok; `UsageCache` hata eski değeri ezmez: `usage::tests::cache_first_none_then_value_and_error_keeps_last_good`, TTL: `cache_respects_ttl` |
| 7 | karşılandı | ata yürüyüşü 64/6 adım, git 15 sn, wmctrl 3 sn |
| 8 | KISMİ | argv fixture'ları altın `detect_info` (50); sürüm etiketli CLI fixture dizini yok; ekran okuma yok |
| 9 | karşılandı | `ChildGuard`, C (fd/zombi) |
| 10 | karşılandı | altın `transcripts`/`usage` (bozuk UTF-8, CRLF, eşsiz vekil, NaN, yinelenen anahtar, tip hataları), T bozuk `/proc` alanları ve bozuk agy dosyaları, `py::tests` |
| 11 | karşılandı | RFH tek modül (`needs_ho::rfh_marker_in`), Python altın vektörü G `rfh_marker` (39), transkript düzeyi G `transcripts_needs_ho` |
| 12 | KISMİ | altın vektör + canlı diferansiyel koşucu var; `Config::from_env` `$HOME` kullanır (`cops-state` birleşince) |
| 13 | karşılandı | sır okunmaz/yazılmaz; `environ`den yalnız `COPS_NAME`; parite çıktısı yalnız sayı/alan adı |
| 14 | karşılandı | `sid` tek yol parçası olmalı (`/`, NUL yok sayılır), Python da (TBD#365); T `transcript_requires_exact_sid` |
| 15 | uygulanmaz | vekil/WS yok |
| 16 | uygulanmaz | uç/route yok |
| 17 | karşılandı | testler yalnız geçici dizin ve kendi açtığı süreçler; parite koşucusu audit hook ile canlı duruma yazamaz (koşu sonunda engellenen yazım 0) |
| 18 | uygulanmaz | uzak host kodu yok |
| 19 | uygulanmaz | canlı ikili değil; T1 bağlayınca `copsd` sürümü |
| 20 | karşılandı | ölçümler yukarıda; `--dry-run` yok; Python'a dokunulmadı |

### 1. Hata sınıfları (bu crate'e değen önleme satırları)
| Sınıf | Durum | Karşılık |
|---|---|---|
| H1 süreç yaşam döngüsü | karşılandı | `ProcId`+`verify`, `ChildGuard`, `disallowed-methods`, C fd/zombi testi |
| H2 atomik yazım | karşılandı | tek yazım (baseline) atomik; Python da düzeltildi (TBD#365) |
| H3 bayat önbellek | karşılandı | `UsageCache` last-good testi; agy durumu her taramada okunur |
| H4 dış CLI varsayımı | KISMİ | sağlayıcı tanıma tek modül + altın argv; sürüm etiketli fixture yok (ekran okuma bu izde yok) |
| H5 bozuk girdi | karşılandı | bozuk dosya fikstürleri (altın + sahte `/proc`), `deny(unwrap/expect/panic)`; bozuk kayıt atlanır ve sayılır (TBD#365); proptest yok |
| H6 işaretçi ayrıştırma | karşılandı | RFH tek fonksiyon + altın corpus; yalnız asistan satırı |
| H7 kimlik çözümleme | karşılandı | tam sid transkript, en-yeni düşüşü yok, `ProcId` |
| H8 sınırsız döngü | karşılandı | tüm döngüler adım/süre sınırlı |
| H9 sessiz başarı | karşılandı | `ScanDiag`, `Liveness::Unknown`, `Access::Unreadable` |
| H14 parite | karşılandı | altın vektörler + `parity/run.py` |
| H16 test yalıtımı | karşılandı | geçici dizin, kendi süreçleri, pyenv koruması |
| H17 yol | karşılandı | `sid` yol parçası olarak süzülür; Python da (TBD#365) |
| H20 gözlemlenebilirlik | KISMİ | sayaçlar var, log yayını çağıranda |
| H21 ölçüm | karşılandı | sayılar ölçümle |
| H10-H13, H15, H18, H19 | uygulanmaz | uzak host, dağıtım, sır, yetki, vekil, HTTP/WS, faz mantığı bu crate'te yok |
