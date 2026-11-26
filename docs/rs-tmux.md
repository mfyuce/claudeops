# İz W0-b: `cops-tmux` (dal `rs/tmux`)

Durum (26 Kas 2026): **birleştirmeye hazır DEĞİL.** Kod ve testler yeşil; ders listesi madde madde işlendi (aşağıda). Eşleme tablosu, genişletilmiş Python paritesi ve iki sahip kararı (TBD 366, 367) bekliyor ("Açık işler").

## Yapılan
`rust/crates/cops-tmux`, `py/claudeops/tmux_backend.py` karşılığı. `ast` listesindeki işlevlerin hepsinin Rust karşılığı yazıldı (satır satır tablo henüz yok).

| Rust dosyası | İçerik |
|---|---|
| `runner.rs` | `Tmux` (soket, zaman aşımlı alt süreç: tek iş parçacığında `poll`, zaman aşımında kill + toplama), `exact_target`, `escape_arg`, `base_argv` |
| `diag.rs` | yutulan hata sayacı + günlük kancası (`Swallowed`, `swallowed_count`, `set_swallow_hook`) |
| `query.rs` | oturum/pane listesi (pid, cwd), capture, aralık, boyut, snapshot, maskeli giriş, istemciler, `set_ctx` |
| `keys.rs` | `send_text`, `send_raw`, özel tuş, boyut, `message`, `MaskGuard` |
| `mask.rs` | `tty_is_masked` (`O_NOCTTY`) |
| `text.rs` | `strip_ansi`, `typed_input_in_box`, `input_box`, `ctx_label` |
| `shell.rs` | `shlex.quote`, kabuk parçaları, `spawn_direct`, `kill_session`, `ghost_session` |
| `proc.rs` | `/proc` üstünden `is_tmux_backed`, `pid_childless`, `find_outer_bash_pids`, `CtxPusher` |

Testler (74): 25 birim, 19 argv (`tests/fake_tmux.sh`), 10 gerçek tmux, 6 yaşam döngüsü, 3 Python paritesi, 1 sızıntı (`leak.rs`), 2 `O_NOCTTY` (`mask_noctty.rs`, biri ayrı süreçte koşan yardımcı), 3 yutulan hata (`swallow.rs`), 3 kaynak denetimi (`hygiene.rs`), 2 `tmux.conf` kuralı (`conf.rs`). `cargo test -p cops-tmux` ve `cargo clippy -p cops-tmux --all-targets -- -D warnings` temiz; 5 ardışık tam koşuda 74/74, oynaklık yok. Gerçek tmux testleri geçici `TMUX_TMPDIR` + rastgele soket + `-f /dev/null` (ya da paketli conf) kullanır; `-L cops` sunucusuna dokunmaz (`tests_never_touch_the_live_socket` denetler).

Testin gerçekten yakaladığı elle sınandı (mutasyon, geri alındı): `mask.rs`ten `O_NOCTTY` çıkarılınca `probing_a_pty_never_makes_it_the_controlling_terminal` kırmızı ("pty'yi denetim terminali edindi"); eski (iş parçacıklı) `runner.rs` ile `no_fd_thread_or_zombie_survives_any_outcome` kırmızı (fd 6 -> 12: torun sürecin tuttuğu borular okuyucu iş parçacıklarıyla birlikte yaşıyordu).

## Kararlar
- Çağrılar bloklayıcı (tokio yok); hata `TmuxError`, Python'daki `None`/`False` karşılığı.
- Her gönderim `MaskGuard` ister. `UserTyped` = Python'daki `tmux_send_*`; `RefuseMasked` = Python `_context`teki ön denetim (bilinmeyen durumda gönderir, bkz. TBD).
- `list_sessions` / `list_panes` / `session_panes` Python'da yok. Yalnız bunlar `tmux -u` kullanır (UTF-8 olmayan yerelde sekme `_` oluyor). `-u` sunucu başlatan komuta verilmez (`is_tmux_backed` sunucu argv'sine bakar).
- Pane kaydı `␞\n` ile biter (cwd satır sonu içerebilir).
- `kill_session` ilkel işlemdir; süreç/pencere temizliği ve devir kuralları kapatma modülünde (T4) kalır.
- `/proc` okuyucusu küçük ve özeldir; `cops-procscan` birleşince ortaklaştırılabilir.
- `rust/Cargo.lock` izin verilen yollar dışında olduğu için commit EDİLMEDİ; ilk `cargo` koşusu `libc`/`regex` girdileriyle günceller.
- Alt süreç G/Ç'si iş parçacıksız: stdin yazımı ve iki çıktı tek döngüde `poll` ile, süre sınırına dek. Süre dolunca borular kapanır, tmux istemcisi SIGKILL + toplanır (`REAP_GRACE` 1 sn, aşılırsa arka planda beklenir). Torun süreç boruyu açık tutsa bile çağıran süre sınırında döner, geride iş parçacığı/fd kalmaz. Python `subprocess.run(timeout=)` ile aynı sonuç (`Timeout`).
- Süre sınırı `MAX_TIMEOUT` (1 sa) ile kırpılır: `Duration::MAX` önceden `Instant` taşmasıyla panik atıyordu.
- Yutulan hata yok: asıl sonucu değiştirmeyen temizlik hatası (`delete-buffer`, çıkış kodu zaten hata iken yarım stdin, kill/toplama) `swallowed_count` sayacına ve günlüğe gider (varsayılan stderr'e tek satır; copsd `set_swallow_hook` ile kendi günlüğüne bağlar). Günlük metni tmux stderr'i ya da G/Ç hatasıdır, gönderilen metni içermez.
- Rust daha sıkı (Python değişmedi): tmux 0 ile çıktığı halde girdisini (stdin) sonuna dek almadıysa sonuç `Io` hatasıdır (Python `communicate` `BrokenPipe`'ı yutar ve yarım tamponu yapıştırırdı). Gerçek `load-buffer` girdiyi hep EOF'a dek okur; yalnız bozuk tmux'ta görünür.
- `client_session` `Result<Option<String>>`: `Ok(None)` = istemci yok, `Err` = tmux sorulamadı. Python ikisine de `None` der; davranış (mesaj gönderilmez) aynı, sebep korunur.

## Python hatası? (Rust birebir taşıdı; sahibe soruldu)
Sonda: tmux 3.2a, yalıtılmış soket, 26 Kas.

| # | Davranış | Etki |
|---|---|---|
| P1 | `_exact("")` = `=:` başka bir oturuma çözülüyor | boş adla gönderim yanlış oturuma gider |
| P2 | `=$0:` ad değil oturum kimliği sayılıyor | `$` ile başlayan ad yanlış oturumu hedefler |
| P3 | `=zeta:0:` `zeta` oturumunun penceresine gidiyor | `:` içeren ad yanlış hedef (tmux adlarda `:` bırakmaz) |
| P4 | `new-session -s 'semi;'` "unknown command: -c" | `;` ile biten adla/cwd ile oturum açılamaz |
| P5 | `LC_ALL=C`de `-F` sekmesi `_` oluyor (sondada `list-panes`) | `tmux_client_session` ve `tmux_ghost_session` bu yerelde bulamaz (çıkarım; bu iki işlev C yerelinde ayrıca denenmedi) |
| P6 | `tmux_set_ctx` etiketi kaçırmıyor | sondaki `;` kaybolur (`ctx_label` hiç üretmez; zararsız) |
| P7 | `find_outer_bash_pids` yedek taraması kullanıcıya göre süzmüyor | başka kullanıcının aynı adlı penceresi listeye girer |

Yeni bulunan, sahibe HENÜZ sorulmamış iki aday (Rust Python'la aynı davranır, düzeltilmedi):

| # | Davranış | Etki |
|---|---|---|
| P8 | `send_text`/`send_raw` tek satırlık metni `send-keys -l -- <metin>` argv'siyle verir (Python `tmux_send_keys` aynı) | metin, `UserTyped` parola dahil, tmux istemcisinin ömrü boyunca `/proc/<pid>/cmdline`ta; `hidepid` yoksa çok kullanıcılı makinede başka kullanıcı görebilir (CLAUDE: "token argv'ye girmez"). Çok satırlı metin stdin'den gider, açık yok |
| P9 | Yapıştırma zaman aşımına uğrarsa `cops-rs-*` tamponu silinmez (Python da yalnız tmux "olmadı" deyince siler) | metin tmux sunucusunda kalır (`show-buffer` ile okunur), sunucu kapanana dek bellekte |

## Ders listesi (`docs/rust-lessons-from-python.md`)
"Karşılandı" yalnız testi olan madde için yazıldı. Test adları `rust/crates/cops-tmux` altında (`src/*` birim, `tests/*` entegrasyon).

### Bölüm 2.2 (cops-tmux)
| Madde | H | Durum | Kanıt / gerekçe |
|---|---|---|---|
| Hedef hep `=ad`, önek yok, tam ad yoksa işlem yok | H7 | kısmen | `prefix_name_never_matches_another_session` (her çağrı), `resize_release_and_kill_use_the_exact_target`, `ghost_is_only_an_old_childless_shell`. AÇIK: P1-P3 (boş ad, `$N`, `:`'lı ad başka oturuma çözülür), TBD 366 |
| `send-keys` tek kurucu, `-l --`, `;` kaçışı, `-help`, `--- a/f`, `abc;` | H4 | karşılandı | `literal_text_raw_and_special_keys_arrive_unchanged` (gerçek tmux), `single_line_is_literal_send_then_enter`, `raw_escapes_only_a_trailing_semicolon`, `writes_match_python` |
| ANSI ayıklama + ayrı ANSI'li kopya, gri öneri | H4 | karşılandı | `capture_plain_strips_colour`, `strips_sgr_and_osc`, `typed_vs_suggestion`, `pure_functions_match_python_on_random_screens` |
| Enjeksiyon öncesi maske; diyalog sınıflandırması; `Unknown` = gönderme | H4 | kısmen | maske: `masked_pane_refuses_injection_but_accepts_user_typing`, `masked_guard_asks_for_the_tty_before_sending`. AÇIK: maske durumu bilinmiyorken gönderim (Python gibi), TBD 367. Diyalog sınıflandırması bu modülde yok: `trust_dialog`/sağlayıcılar (T4) |
| Diyalog yalnız pane sonunda | H4 | başka iz | `trust_dialog` (T4); bu crate ekranı sınıflandırmaz |
| Teslim doğrulaması (kutuda kalan metin ≠ teslim) | H9 | başka iz | `tmux_backend`de yok (T4/T10). Burada `Ok` = tmux kabul etti; olumsuz yollar madde 4'te |
| Copy-mode yok; `pane_is_masked_input` `O_NOCTTY` ile açar | H1, H4 | karşılandı | `history_read_never_enters_copy_mode` (`pane_in_mode` 0), `probing_a_pty_never_makes_it_the_controlling_terminal` (ctty'siz oturum lideri pty'yi yoklar, ctty edinmez; karşı sınama `O_NOCTTY`'siz açışın edindiğini görür; mutasyonla doğrulandı) |
| `tmux.conf` sürüm sınırı (düz `set-option -g` + sürüm kapılı satır) | H4 | karşılandı | `main_conf_is_only_plain_global_options_and_version_gated_includes` (Python `test_tmux_strip.py` ile aynı kural), `spawn_direct_uses_conf_env_and_cwd_and_keeps_the_session_after_exit` (tmux 3.2a yükler). 3.0a ile gerçek yükleme yerelde denenemez |
| Kill sırası; ölü ad sonrası kardeş yaşar | H7 | kısmen | `prefix_name_never_matches_another_session` (`kill_session("abc")` `abc_1`'e dokunmaz), `spawn_direct_...` (ikinci kill `Err`). Sıra (önce oturum, sonra süreç) kapatma modülünde (T4) |
| `display-menu` komutlarında oturum adı yok, `#{client_name}` | H4 | karşılandı | `menu_commands_take_the_client_name_never_the_session_name` |
| Gerçek tmux gidiş-dönüş | H4 | karşılandı | `tests/real_tmux.rs`, `tests/lifecycle.rs`, `tests/parity.rs` |

### Bölüm 3 (birleştirme öncesi genel liste)
| # | H | Durum | Kanıt / gerekçe |
|---|---|---|---|
| 1 Hedef `Unique`, önek/"en yeni" yok | H7 | kısmen | 2.2 ilk satır. Yıkıcı tek ilkel `kill_session` (exact). "En yeni" tahmini yok. AÇIK: P1-P3 (TBD 366) |
| 2 `atomic_write` / kilit sözleşmesi | H2 | geçerli değil + test | crate dosya yazmaz; `no_state_dir_home_file_writes_or_signals_outside_the_runner` (`fs::write`, `File::create`, `create_dir`, `remove_file` yok). tmux tampon adı süreç+sıra ile benzersiz (`multiline_uses_load_paste_then_single_enter`) |
| 3 Belirsiz/okunamayan ≠ başarı/yok | H13, H10, H9 | kısmen | `has_session`: tmux yok/zaman aşımı `Err`, "oturum yok" `Ok(false)` (`no_server_is_an_error_not_a_panic`); `client_count` `Err` ≠ 0, `client_session` `Err` ≠ `None` (`broken_output_is_unknown_not_a_panic`); maske `None` (`prefix_name_...`); hayalet belirsizlikte `false` (`empty_or_garbage_is_not_ghost`); yarım stdin başarı değil (`input_cut_short_by_a_failing_tmux_is_counted_and_failure_returned`, `leak.rs` `deaf`). AÇIK: maske `None` iken gönderim (TBD 367) |
| 4 Eylem sonucu doğrulanıyor; NEGATİF test | H9 | kısmen | tmux düzeyi olumsuzlar: `paste_failure_deletes_the_buffer_and_sends_no_enter`, `load_failure_stops_before_paste`, `raw_is_split_into_chunks_and_stops_at_the_first_failure`, `message_falls_back_to_no_duration_and_reports_total_failure`, maske/önek testleri. `Delivery{Confirmed,...}` ekran doğrulaması T4/T10'da (bu crate `Ok` = "tmux kabul etti" der, teslim demez) |
| 5 `let _`/`.ok()`/`unwrap_or_default`/`expect` yok; yutulan hata sayaç+log | H9, H20 | karşılandı (iki yol testsiz) | `no_swallowed_result_or_panic_in_production_code` (`let _ =`, `unwrap_or_default`, `.unwrap()`, `panic!` sıfır; tek `expect` sabit regex; `.ok()` yalnız "bilinmiyor = None" okuyucularında), `failed_buffer_cleanup_is_counted_logged_and_the_paste_error_returned`, `input_cut_short_...`, `every_kind_has_a_distinct_code`. Testsiz: `KillChild`/`ReapChild` (kendi çocuğuna SIGKILL başarısız olamaz, 1 sn'de toplanmayan süreç D durumu ister; kod sayaç+günlük taşır) |
| 6 Açılışta bir kez okunan önbellek/ayar yok; hata `last_good`'u ezmez | H3 | karşılandı | tek önbellek `CtxPusher` (pid anahtarlı, başarısız yazım not edilmez): `ctx_push_skips_unchanged_and_rewrites_on_new_pid_or_value`, `failed_ctx_push_is_retried`, `ctx_push_cache_is_bounded_and_thread_safe`. Conf yolu her çağrıda çözülür. Bilinen (Python eşi): dışarıdan silinen `@cops_ctx` aynı pid'de yeniden yazılmaz |
| 7 Her döngü/bekleme sınırlı; bildirim durumu kalıcı | H8 | karşılandı | `exec` döngüsü `deadline`a bağlı (`hung_program_times_out`, `leak.rs` `hang`/`grandchild`), `MAX_TIMEOUT` (`huge_timeout_is_clamped_not_a_panic`), toplama `REAP_GRACE`; test beklemeleri `common::wait_until` 10 sn, ETXTBSY yeniden denemesi 200 kez. Kalıcı bildirim: geçerli değil (crate bildirim/yeniden deneme politikası üretmez) |
| 8 Dış TUI davranışı fixture'lı; `Unknown`'da gönderim yok | H4 | kısmen | giriş kutusu/gri öneri: `typed_vs_suggestion`, Python ile rastgele ekran diferansiyeli (`pure_functions_match_python_on_random_screens`). Gerçek CLI sürümlü ekran fixture'ları diyalog sınıflandırmasıyla T4'te. `Unknown` = TBD 367 |
| 9 Süreç/bağlantı sahibi, kill+wait, boşaltılan stderr, fd sızıntı testi | H1 | karşılandı (bir yol testsiz) | `no_fd_thread_or_zombie_survives_any_outcome` (başarı, hata, zaman aşımı, boruyu tutan torun, 3 MB çıktı, 1,4 MB girdi; fd ve iş parçacığı sayısı aynı, zombi yok), `probing_a_pty_...` (100 yoklamada fd sabit), `hung_program_times_out`. Testsiz: `REAP_GRACE` aşımı (arka plan toplayıcı) |
| 10 Girdi sınırları | H5 | kısmen | `disallowed_key_and_bad_size_spawn_nothing`, `resize_applies_and_release_restores_auto_size` (sınırlar), NUL (`raw_escapes_only_a_trailing_semicolon`), bozuk UTF-8/biçim (`broken_output_is_unknown_not_a_panic`, `universal_newlines_like_python_text_mode`, `malformed_snapshot_is_an_error`, `parsers_keep_free_text_last_and_reject_garbage`, `outer_bash_with_garbage_client_pids_is_empty`), `Duration::MAX`/sıfır (`huge_timeout_is_clamped_not_a_panic`). Token/NaN: geçerli değil (süreler `Duration`). AÇIK: boş ad P1 (TBD 366) |
| 11 Metin ayrıştırma tek modül, corpus, Python vektörleri | H6, H14 | karşılandı | `text.rs` tek modül; `pure_functions_match_python_on_random_screens`, `ctx_label_rounds_like_python`, `stat_line_with_spaces_and_parens_in_name`, `cmdline_split_like_psutil`. İşaretçi (STEWARD-*) ayrıştırma bu crate'te yok |
| 12 Python'la paylaşılan kural altın vektör + diferansiyel; `$HOME` yok | H14 | kısmen | `reads_match_python`, `writes_match_python`, `pure_functions_...`; `$HOME`/durum dizini yok: `no_state_dir_home_file_writes_...`. AÇIK: parite genişletmesi (Açık işler 2) |
| 13 Sır `Secret<T>`; log/argv/URL'de sızıntı yok | H12, H13 | kısmen | crate sır tutmaz; günlük/hata metni gönderilen metni içermez (`failed_buffer_cleanup_...`, `input_cut_short_...` SECRET arar). AÇIK: P8 (tek satırlık metin, parola dahil, argv'de), P9 (zaman aşımında tampon kalır); sahibe sorulacak. Yetki matrisi: geçerli değil (kimlik yok) |
| 14 `SafePath`/canonical IP; symlink, `..` | H17 | geçerli değil | ağ adresi yok. Yollar: conf yolu çağırandan, pty yolu kendi tmux sunucumuzdan; `tty_is_masked` salt okuma + `O_NONBLOCK`, tty değilse `None` (`unknown_for_empty_missing_and_non_tty`) |
| 15 Vekil/WS kullanıcı yolundan e2e | H15, H18, H21 | geçerli değil | vekil/WS yok. Kullanıcı yolu karşılığı: gerçek tmux'a gerçek pane ile gidiş-dönüş (`tests/real_tmux.rs`) |
| 16 Route tabloları eşitliği | H10, H14 | geçerli değil | uç/route eklenmedi |
| 17 Test yalıtımı; canlı dizin değişmez | H16 | karşılandı | `tests_never_touch_the_live_socket`; `common::Server` (geçici `TMUX_TMPDIR`, rastgele soket, `Drop`ta `kill-server`); `TempDir` RAII; canlı durum dizinine giden kod yok (`no_state_dir_home_file_writes_...`) |
| 18 Uzak host sürüm/yetenek, devre kesici, deploy smoke | H10, H11 | geçerli değil | crate yalnız yerel tmux soketi; uzak pane'ler federasyon izinde (`cops-hosts`) |
| 19 `GIT_SHA`, canlı = main, `*.prev`, restart kurtarma | H11 | geçerli değil | kütüphane crate'i; ikili sürümü ve geri dönüş copsd'de. Uzun iş yok (en uzun çağrı `send_text_timeout`) |
| 20 Ölçüm/kanıt; `--dry-run` yan etkisiz; Python'a yeni özellik yok | H21 | karşılandı | oynaklık 5 ardışık koşuyla ölçüldü; iki testin yakaladığı mutasyonla gösterildi (yukarıda); `--dry-run` yok; Python dosyası değişmedi (`git status`) |

Bölüm 1'deki ilgili sınıflar: H1 (madde 9), H4 (2.2, madde 8), H5 (madde 10), H7 (madde 1), H8 (madde 7), H9/H20 (madde 4, 5), H14 (madde 11, 12), H16 (madde 17). Kontrol listesinin atıf verdiği diğer sınıflar (H2, H3, H10-H13, H15, H17-H19, H21) yukarıdaki satırlarda gerekçesiyle.

## Açık işler (birleştirmeden önce)
1. Eşleme tablosu (sahip EK 2): `tmux_backend.py`nin her `ast` tanımı (dosya:satır | Rust yol::ad | parite testi | durum) ve ilgili her `test_*` metodu. İlgili dosyalar: `test_tmux_*.py`, `test_tty_masked_input`, `test_input_box_typed`, `test_spawn_ghost_reclaim`, `test_outer_bash_list_clients`, `test_term_viewport`, `test_term_history`, `test_term_resize`, `test_kill_access_denied`, `test_proc08_model_switch_no_blind_enter`, `test_live_model_effort`, `test_watch_input` (çoğu başka ize ait: T2/T4/T10). Boş satır kalmayacak.
2. `tests/parity.py` + `parity.rs` genişlet: sabitler ve regex'ler (`patterns()`), `dim_fg`, `segment_typed`, kabuk parçaları, `tmux_conf_path`, `base_argv`, `spawn_direct`, `kill_session`, `ghost_session`, `pid_childless`, `is_tmux_backed`, `find_outer_bash_pids`, `set_ctx`/`push_ctx`, `message`, `client_session`, `release_size`; P1-P7 davranışlarının eşliği. (Ders listesi madde 12.)
3. TBD cevabına göre P1-P7 (TBD 366) ve maske durumu bilinmiyorken gönderim (TBD 367). Ders listesi madde 1, 3, 8, 10 bunlara bağlı.
4. P8 (argv'de metin/parola) ve P9 (zaman aşımında kalan tampon): sahibe soruldu (TBD 369). Ders listesi madde 13.
5. Testsiz iki yol (madde 5, 9): `KillChild`/`ReapChild` sayaçları ve `REAP_GRACE` arka plan toplayıcısı; tetiklemek için D durumunda süreç gerekir. Ya bir enjeksiyon noktası (test özelliği) eklenir ya da gerekçe kabul edilir.
6. copsd birleşince `set_swallow_hook` copsd günlüğüne bağlanmalı (yoksa yutulan hatalar stderr'e, yani servis günlüğüne gider).
