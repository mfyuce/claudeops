# İz W0-b: `cops-tmux` (dal `rs/tmux`)

Durum (26 Kas 2026): **BİRLEŞTİRMEYE HAZIR.** Testler, clippy, fmt yeşil; ders listesi madde madde işlendi; eşleme tablosunda boş satır yok; TBD 366 ve 367 kararları iki tarafta uygulandı (Python `fix` commit'leri bu dalda). Açık: TBD 369 (P8/P9) cevabı ve "Açık işler" 6-8 (birleştirme sonrası / başka iz).

## Yapılan
`rust/crates/cops-tmux`, `py/claudeops/tmux_backend.py` karşılığı. `ast` listesindeki her tanımın Rust karşılığı var; satır satır tablo "Eşleme tablosu" bölümünde.

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

Testler (87): 29 birim, 20 argv (`tests/fake_tmux.sh`), 11 gerçek tmux, 6 yaşam döngüsü, 9 Python paritesi, 1 sızıntı (`leak.rs`), 2 `O_NOCTTY` (`mask_noctty.rs`, biri ayrı süreçte koşan yardımcı), 3 yutulan hata (`swallow.rs`), 3 kaynak denetimi (`hygiene.rs`), 3 `tmux.conf` kuralı (`conf.rs`). `cargo test -p cops-tmux` ve `cargo clippy -p cops-tmux --all-targets -- -D warnings` temiz; 5 ardışık tam koşuda 74/74 (genişletme sonrası 3 ardışık koşuda 82/82), oynaklık yok. Gerçek tmux testleri geçici `TMUX_TMPDIR` + rastgele soket + `-f /dev/null` (ya da paketli conf) kullanır; `-L cops` sunucusuna dokunmaz (`tests_never_touch_the_live_socket` denetler).

Testin gerçekten yakaladığı elle sınandı (mutasyon, geri alındı): `mask.rs`ten `O_NOCTTY` çıkarılınca `probing_a_pty_never_makes_it_the_controlling_terminal` kırmızı ("pty'yi denetim terminali edindi"); eski (iş parçacıklı) `runner.rs` ile `no_fd_thread_or_zombie_survives_any_outcome` kırmızı (fd 6 -> 12: torun sürecin tuttuğu borular okuyucu iş parçacıklarıyla birlikte yaşıyordu).

## Kararlar
- Çağrılar bloklayıcı (tokio yok); hata `TmuxError`, Python'daki `None`/`False` karşılığı.
- Her gönderim `MaskGuard` ister. `UserTyped` = Python'daki `tmux_send_*`; `RefuseMasked` = Python `_context`teki ön denetim. Durum bilinmiyorsa (`pane_is_masked_input` `None`) iki taraf da GÖNDERMEZ (TBD 367, sahip kararı 26 Kas; Rust `TmuxError::MaskUnknown`, Python `reason: mask_unknown`); "Maske durumu bilinmiyorken gönderim (TBD 367)" bölümü.
- `list_sessions` / `list_panes` / `session_panes` Python'da yok. Yalnız bunlar `tmux -u` kullanır (UTF-8 olmayan yerelde sekme `_` oluyor). `-u` sunucu başlatan komuta verilmez (`is_tmux_backed` sunucu argv'sine bakar).
- Pane kaydı `␞\n` ile biter (cwd satır sonu içerebilir).
- `kill_session` ilkel işlemdir; süreç/pencere temizliği ve devir kuralları kapatma modülünde (T4) kalır.
- `/proc` okuyucusu küçük ve özeldir; `cops-procscan` birleşince ortaklaştırılabilir.
- `rust/Cargo.lock` izin verilen yollar dışında olduğu için commit EDİLMEDİ; ilk `cargo` koşusu `libc`/`regex` girdileriyle günceller.
- Alt süreç G/Ç'si iş parçacıksız: stdin yazımı ve iki çıktı tek döngüde `poll` ile, süre sınırına dek. Süre dolunca borular kapanır, tmux istemcisi SIGKILL + toplanır (`REAP_GRACE` 1 sn, aşılırsa arka planda beklenir). Torun süreç boruyu açık tutsa bile çağıran süre sınırında döner, geride iş parçacığı/fd kalmaz. Python `subprocess.run(timeout=)` ile aynı sonuç (`Timeout`).
- Süre sınırı `MAX_TIMEOUT` (1 sa) ile kırpılır: `Duration::MAX` önceden `Instant` taşmasıyla panik atıyordu.
- Yutulan hata yok: asıl sonucu değiştirmeyen temizlik hatası (`delete-buffer`, çıkış kodu zaten hata iken yarım stdin, kill/toplama) `swallowed_count` sayacına ve günlüğe gider (varsayılan stderr'e tek satır; copsd `set_swallow_hook` ile kendi günlüğüne bağlar). Günlük metni tmux stderr'i ya da G/Ç hatasıdır, gönderilen metni içermez.
- Rust daha sıkı (Python'da bu davranış değişmedi): tmux 0 ile çıktığı halde girdisini (stdin) sonuna dek almadıysa sonuç `Io` hatasıdır (Python `communicate` `BrokenPipe`'ı yutar ve yarım tamponu yapıştırırdı). Gerçek `load-buffer` girdiyi hep EOF'a dek okur; yalnız bozuk tmux'ta görünür.
- Python'un `str.strip/split/splitlines` anlamı gereken her ayrıştırmada `text::py_*` yardımcıları (Rust `trim/lines/split_whitespace` `\x1c`-`\x1f` ve bazı satır sonlarında farklı). Sayı ayrıştırmada `str::trim` (Python `int()`/`float()` ile eş).
- `client_session` `Result<Option<String>>`: `Ok(None)` = istemci yok, `Err` = tmux sorulamadı. Python ikisine de `None` der; davranış (mesaj gönderilmez) aynı, sebep korunur.

## Python hataları (TBD 366: iki tarafta düzeltildi)
Sonda: tmux 3.2a, yalıtılmış soket, 26 Kas. Sahip kararı (TBD 366, 26 Kas): "hepsi iki tarafta düzelsin; Python'a ayrı `fix:` commit'leri + test". Her satırda Python düzeltmesi, Python testi ve eşitlenen Rust aynı commit'te.

| # | Davranış (eski) | Etki (eski) | Düzeltme (Python + Rust) | Commit, Python testi |
|---|---|---|---|---|
| P1 | `_exact("")` = `=:` başka bir oturuma çözülüyor | boş adla gönderim yanlış oturuma gider | `_addressable`/`addressable`: boş ad reddedilir; hiçbir tmux komutu çalışmaz (Python `None`/`False`/`[]`, kabuk parçasında `ValueError`; Rust `BadArgument("name")`) | `b51c368`, `test_tmux_target_names.py` |
| P2 | `=$0:` ad değil oturum kimliği sayılıyor | `$` ile başlayan ad yanlış oturumu hedefler | `$` ile başlayan ad reddedilir (aynı kapı) | `b51c368`, aynı |
| P3 | `=zeta:0:` tek başına `display-message`te `zeta`ya çözülüyor (has-session, kill-session, list-panes, capture-pane, send-keys "can't find window" ile reddeder) | `:` içeren adla maske yoklaması başka oturumun pty'sine bakar (tmux adlarda `:` bırakmaz) | `:` içeren ad reddedilir (aynı kapı). `=`, `@`, `%`, `.` içeren adlar doğru çözülür, değişmedi | `b51c368`, aynı |
| P4 | `new-session -s 'semi;'` "unknown command: -c" | `;` ile biten adla/cwd ile oturum açılamaz | `_tmux_arg`/`escape_arg`: `spawn_direct` (ad, cwd) ve yeni oturum kabuk parçası (ad, cwd, iç komut) sondaki `;`i `\;` yapar | `6536631`, `test_tmux_arg_semicolon.py` |
| P5 | `LC_ALL=C`de `-F` sekmesi `_` oluyor | `tmux_client_session` ve `tmux_ghost_session` bu yerelde bulamaz (`$TMUX` tanımlıyken gizli kalıyordu) | bu iki sorgu `tmux -u` (`_base_argv_utf8`/`text_utf8`); sunucu başlatan komuta `-u` verilmez | `104cbcd`, `test_tmux_list_utf8.py` |
| P6 | `tmux_set_ctx` etiketi kaçırmıyor | sondaki `;` kaybolur | etiket `_tmux_arg`/`escape_arg` ile | `6536631`, `test_tmux_arg_semicolon.py` |
| P7 | `find_outer_bash_pids` yedek taraması kullanıcıya göre süzmüyor | başka kullanıcının aynı adlı penceresi listeye girer | yalnız gerçek kullanıcısı `os.getuid()` olan süreç (Python psutil `uids().real`, Rust `/proc/<pid>/status` `Uid:`) | `328c18b`, `test_outer_bash_user_filter.py` (+ `test_outer_bash_list_clients.py` sahtesi `uids` taşır) |

Parite: P1-P5 PB'de (`python_bug_fixes_p1_to_p7_behave_the_same_in_rust`: ikiz sunucularda iki taraf da reddeder, oturumlar yerinde; P4 iki tarafta da oturum o ad ve dizinde açılır; P5 C yerelinde iki taraf da bulur), P6 PCL'de (yazılan değer eşit ve `a;`), P7 PF'de (yedek tarama eşit) + Rust `proc::tests::fallback_scan_counts_only_this_users_windows` (başka kullanıcı köprüde taklit edilemez; Python'da `os.getuid` sahtelenir). PC ayrıca `_addressable`, `_tmux_arg` ve kabuk parçalarını karşılaştırır.

Canlıya alınırken: hedeflenemeyen adla (boş, `$`, `:`) açılış artık yapılmaz; `spawn.py` kabuk parçası yolunda `ValueError` yükselir (eskiden `-A` başka oturuma bağlanırdı). Üretilen oturum adları (`<proje><tarih>[_N]`) bu sınıfta değil. P5 `winact` (şerit menüsü) ve PROC-03 hayalet geri almayı C yerelinde de çalışır yapar; P7 kapatma yolunda (`kill.py`) başka kullanıcının penceresini aday listesinden çıkarır.

Sahibe TBD 369 ile sorulan iki aday (Rust Python'la aynı davranır, düzeltilmedi):

| # | Davranış | Etki |
|---|---|---|
| P8 | `send_text`/`send_raw` tek satırlık metni `send-keys -l -- <metin>` argv'siyle verir (Python `tmux_send_keys` aynı) | metin, `UserTyped` parola dahil, tmux istemcisinin ömrü boyunca `/proc/<pid>/cmdline`ta; `hidepid` yoksa çok kullanıcılı makinede başka kullanıcı görebilir (CLAUDE: "token argv'ye girmez"). Çok satırlı metin stdin'den gider, açık yok |
| P9 | Yapıştırma zaman aşımına uğrarsa `cops-rs-*` tamponu silinmez (Python da yalnız tmux "olmadı" deyince siler) | metin tmux sunucusunda kalır (`show-buffer` ile okunur), sunucu kapanana dek bellekte |

## Maske durumu bilinmiyorken gönderim (TBD 367: iki tarafta kapalı yön)
Sahip kararı (26 Kas): "ikisi de göndermesin; Python'a da ayrı `fix:` + test". Commit `073578a`.

- Rust: `MaskGuard::RefuseMasked` yalnız `pane_is_masked_input` `Some(false)` iken gönderir; `Some(true)` `Masked`, `None` `MaskUnknown` (hiçbir `send-keys`/`load-buffer` çalışmaz). `UserTyped` (insanın kendi yazdığı, parola dahil) yoklamaya hiç uğramaz. Testler: `argv::masked_guard_asks_for_the_tty_before_sending`, `argv::unknown_mask_state_blocks_every_automatic_send_but_not_user_typing` (okunamayan pty, boş çıktı, tmux hatası), `real_tmux::unknown_mask_state_refuses_injection_on_a_real_server`.
- Python: maske ön denetimi yapan TEK otomatik gönderici `web._context`; `None`da artık göndermez (`test_context_mask_unknown.py`).

"Bilinmiyor" ne zaman döner (ölçüm 26 Kas, tmux 3.2a, yalıtılmış sunucu, pane başına 300 ardışık yoklama, Python `pane_is_masked_input`):

| Pane | Sonuç |
|---|---|
| `bash -i`, `sleep`, `cat`, ham kipli python (TUI gibi), `vi` | 300/300 `False` |
| `getpass` bekleyen python | 300/300 `True` |
| Yeni açılmış `bash -i`, açılıştan hemen sonra (40 oturum) | 40/40 `False` |
| Oturum yok | 300/300 `None` |
| `remain-on-exit on` ile süreci bitmiş pane | 300/300 `None` (pty silinmiş) |

Normal bir CLI pane'i ölçümde HİÇ bilinmiyor çıkmadı; `None` yalnız oturum/pane yokken, tmux 5 sn'de cevap vermezken ya da tmux kurulu değilken. Canlı `tmux.conf` `remain-on-exit off`: ölü pane = oturum yok. Yan bulgu: ölü pane'in `#{pane_tty}` numarası başka bir pty'ye yeniden verilirse yoklama O pty'yi okur (Rust testinde paralel koşuda `Some(false)` görüldü); ölü pane'e gönderim zaten bir sürece ulaşmaz, ayrıca düzeltilmedi.

Etkilenen çağıranlar (grep, 26 Kas):

| Çağıran | Engellenince | Not |
|---|---|---|
| `py/claudeops/commands/web.py:3858` `_context` ← `POST /api/context` (`web.py:6414`; host-routed `web_hosts.py:71`, uzak panelde o host'a deploy edilince) | `{"ok": true, "available": false, "reason": "mask_unknown"}`; komut gönderilmez, "gönderildi" sayılmaz, yeniden deneme yok (isteğe bağlı sorgu, kullanıcı yeniden basar) | panel (`webui`, bu işin yazma kapsamı dışında) `mask_unknown`u tanımıyor, genel `contextParseFailed` ("yanıt okunamadı") metnini gösterir: ayrı webui işi |

Python'un diğer otomatik göndericileri maske denetimi YAPMAZ, bu değişiklikten ETKİLENMEZ (bugün durum ne olursa olsun gönderirler): `web_steward.py:1462` `_send` (değnekçi yönergesi/rutin), `web_steward.py:1530` ve `web.py:2152` (güven diyaloğu), `web_steward.py:1655`, `:7167`, `:7169` (ham Enter/boşluk), `web.py:3314` `_handover`, `web.py:3414` `_compact`, `web.py:4579` `_v1_chat_completion`, `web.py:2934` (BTab), `handover.py:453` `handover_faz1`, `web_orch.py:285` `_send_prompt`, `providers/claude_provider.py:804`, `:906`, `:964` (model/effort geçişi). Kullanıcının yazdığı: `web.py:2791` `_term_input`, `:2824` `_term_key`, `:2856` `_term_raw` (Rust `UserTyped`).

Canlıya alınırken: Python tarafında yalnız `/api/context` etkilenir (ölçüme göre normal pane'de görünmez). Bu çağıranlar Rust'a taşınırken `RefuseMasked` seçerse durum bilinmediğinde `MaskUnknown` alır: değnekçi `_send` bunu `False` ("send failed", `_note_send_result`) gibi görür ve kendi yeniden deneme yoluna girer; mesaj kaybolmaz ama teslim gecikir. Çağıran `MaskUnknown`u `send failed`ten ayrı göstermeli (T10 değnekçi izi).

## Ders listesi (`docs/rust-lessons-from-python.md`)
"Karşılandı" yalnız testi olan madde için yazıldı. Test adları `rust/crates/cops-tmux` altında (`src/*` birim, `tests/*` entegrasyon).

### Bölüm 2.2 (cops-tmux)
| Madde | H | Durum | Kanıt / gerekçe |
|---|---|---|---|
| Hedef hep `=ad`, önek yok, tam ad yoksa işlem yok | H7 | karşılandı | `prefix_name_never_matches_another_session` (her çağrı), `resize_release_and_kill_use_the_exact_target`, `ghost_is_only_an_old_childless_shell`. P1-P3 (boş ad, `$N`, `:`'lı ad) iki tarafta düzeltildi (TBD 366): `exact_target_refuses_names_tmux_resolves_to_another_session`, PB (ikiz sunucularda red, oturumlar yerinde; `=eq`/`@1`/`%1` doğru hedeflenir) |
| `send-keys` tek kurucu, `-l --`, `;` kaçışı, `-help`, `--- a/f`, `abc;` | H4 | karşılandı | `literal_text_raw_and_special_keys_arrive_unchanged` (gerçek tmux), `single_line_is_literal_send_then_enter`, `raw_escapes_only_a_trailing_semicolon`, `writes_match_python` |
| ANSI ayıklama + ayrı ANSI'li kopya, gri öneri | H4 | karşılandı | `capture_plain_strips_colour`, `strips_sgr_and_osc`, `typed_vs_suggestion`, `pure_functions_match_python_on_random_screens` |
| Enjeksiyon öncesi maske; diyalog sınıflandırması; `Unknown` = gönderme | H4 | karşılandı (maske); diyalog başka iz | maske: `masked_pane_refuses_injection_but_accepts_user_typing`, `masked_guard_asks_for_the_tty_before_sending`; durum bilinmiyorken gönderim yok (TBD 367, iki tarafta): `unknown_mask_state_blocks_every_automatic_send_but_not_user_typing`, `unknown_mask_state_refuses_injection_on_a_real_server`. Diyalog sınıflandırması bu modülde yok: `trust_dialog`/sağlayıcılar (T4) |
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
| 1 Hedef `Unique`, önek/"en yeni" yok | H7 | karşılandı | 2.2 ilk satır. Yıkıcı tek ilkel `kill_session` (exact; hedeflenemeyen adda `BadArgument`, P1-P3 TBD 366). "En yeni" tahmini yok |
| 2 `atomic_write` / kilit sözleşmesi | H2 | geçerli değil + test | crate dosya yazmaz; `no_state_dir_home_file_writes_or_signals_outside_the_runner` (`fs::write`, `File::create`, `create_dir`, `remove_file` yok). tmux tampon adı süreç+sıra ile benzersiz (`multiline_uses_load_paste_then_single_enter`) |
| 3 Belirsiz/okunamayan ≠ başarı/yok | H13, H10, H9 | karşılandı | `has_session`: tmux yok/zaman aşımı `Err`, "oturum yok" `Ok(false)` (`no_server_is_an_error_not_a_panic`); `client_count` `Err` ≠ 0, `client_session` `Err` ≠ `None` (`broken_output_is_unknown_not_a_panic`); maske `None` (`prefix_name_...`); hayalet belirsizlikte `false` (`empty_or_garbage_is_not_ghost`); yarım stdin başarı değil (`input_cut_short_by_a_failing_tmux_is_counted_and_failure_returned`, `leak.rs` `deaf`); maske `None` iken otomatik gönderim yok, `MaskUnknown` (`unknown_mask_state_blocks_every_automatic_send_but_not_user_typing`, TBD 367) |
| 4 Eylem sonucu doğrulanıyor; NEGATİF test | H9 | kısmen | tmux düzeyi olumsuzlar: `paste_failure_deletes_the_buffer_and_sends_no_enter`, `load_failure_stops_before_paste`, `raw_is_split_into_chunks_and_stops_at_the_first_failure`, `message_falls_back_to_no_duration_and_reports_total_failure`, maske/önek testleri. `Delivery{Confirmed,...}` ekran doğrulaması T4/T10'da (bu crate `Ok` = "tmux kabul etti" der, teslim demez) |
| 5 `let _`/`.ok()`/`unwrap_or_default`/`expect` yok; yutulan hata sayaç+log | H9, H20 | karşılandı | `no_swallowed_result_or_panic_in_production_code` (`let _ =`, `unwrap_or_default`, `.unwrap()`, `panic!` sıfır; tek `expect` sabit regex; `.ok()` yalnız "bilinmiyor = None" okuyucularında), `failed_buffer_cleanup_is_counted_logged_and_the_paste_error_returned`, `input_cut_short_...`, `every_kind_has_a_distinct_code`. `KillChild`/`ReapChild`: `unreapable_child_is_counted_and_waited_in_background` (sahte süreç) |
| 6 Açılışta bir kez okunan önbellek/ayar yok; hata `last_good`'u ezmez | H3 | karşılandı | tek önbellek `CtxPusher` (pid anahtarlı, başarısız yazım not edilmez): `ctx_push_skips_unchanged_and_rewrites_on_new_pid_or_value`, `failed_ctx_push_is_retried`, `ctx_push_cache_is_bounded_and_thread_safe`. Conf yolu her çağrıda çözülür. Bilinen (Python eşi): dışarıdan silinen `@cops_ctx` aynı pid'de yeniden yazılmaz |
| 7 Her döngü/bekleme sınırlı; bildirim durumu kalıcı | H8 | karşılandı | `exec` döngüsü `deadline`a bağlı (`hung_program_times_out`, `leak.rs` `hang`/`grandchild`), `MAX_TIMEOUT` (`huge_timeout_is_clamped_not_a_panic`), toplama `REAP_GRACE`; test beklemeleri `common::wait_until` 10 sn, ETXTBSY yeniden denemesi 200 kez. Kalıcı bildirim: geçerli değil (crate bildirim/yeniden deneme politikası üretmez) |
| 8 Dış TUI davranışı fixture'lı; `Unknown`'da gönderim yok | H4 | kısmen | giriş kutusu/gri öneri: `typed_vs_suggestion`, Python ile rastgele ekran diferansiyeli (`pure_functions_match_python_on_random_screens`). Gerçek CLI sürümlü ekran fixture'ları diyalog sınıflandırmasıyla T4'te (kısmen bunun için). `Unknown`'da gönderim yok: karşılandı (`unknown_mask_state_refuses_injection_on_a_real_server`, TBD 367) |
| 9 Süreç/bağlantı sahibi, kill+wait, boşaltılan stderr, fd sızıntı testi | H1 | karşılandı | `no_fd_thread_or_zombie_survives_any_outcome` (başarı, hata, zaman aşımı, boruyu tutan torun, 3 MB çıktı, 1,4 MB girdi; fd ve iş parçacığı sayısı aynı, zombi yok), `probing_a_pty_...` (100 yoklamada fd sabit), `hung_program_times_out`. `REAP_GRACE` aşımı ve arka plan toplayıcısı: `unreapable_child_is_counted_and_waited_in_background` |
| 10 Girdi sınırları | H5 | karşılandı | `disallowed_key_and_bad_size_spawn_nothing`, `resize_applies_and_release_restores_auto_size` (sınırlar), NUL (`raw_escapes_only_a_trailing_semicolon`), bozuk UTF-8/biçim (`broken_output_is_unknown_not_a_panic`, `universal_newlines_like_python_text_mode`, `malformed_snapshot_is_an_error`, `parsers_keep_free_text_last_and_reject_garbage`, `outer_bash_with_garbage_client_pids_is_empty`), `Duration::MAX`/sıfır (`huge_timeout_is_clamped_not_a_panic`). Token/NaN: geçerli değil (süreler `Duration`). Boş/`$`/`:`'lı ad (P1-P3): `exact_target_refuses_names_tmux_resolves_to_another_session`; `;` ile biten argüman (P4, P6): PB, PCL |
| 11 Metin ayrıştırma tek modül, corpus, Python vektörleri | H6, H14 | karşılandı | `text.rs` tek modül; `pure_functions_match_python_on_random_screens`, `ctx_label_rounds_like_python`, `stat_line_with_spaces_and_parens_in_name`, `cmdline_split_like_psutil`. İşaretçi (STEWARD-*) ayrıştırma bu crate'te yok |
| 12 Python'la paylaşılan kural altın vektör + diferansiyel; `$HOME` yok | H14 | karşılandı | `tests/parity.rs` 9 test: her `tmux_backend` tanımı en az bir parite testinde ("Eşleme tablosu"); sahte tmux'ta argv + sonuç diferansiyeli, gerçek tmux'ta yaşam döngüsü/istemci/mesaj, P1-P7 düzeltmelerinin iki taraftaki eşliği; Python alt süreci geçici `HOME`/`CLAUDEOPS_DIR`/`TMUX_TMPDIR` ve rastgele soketle; `$HOME` yok: `no_state_dir_home_file_writes_...` |
| 13 Sır `Secret<T>`; log/argv/URL'de sızıntı yok | H12, H13 | kısmen | crate sır tutmaz; günlük/hata metni gönderilen metni içermez (`failed_buffer_cleanup_...`, `input_cut_short_...` SECRET arar). AÇIK: P8 (tek satırlık metin, parola dahil, argv'de), P9 (zaman aşımında tampon kalır); sahibe soruldu (TBD 369). Yetki matrisi: geçerli değil (kimlik yok) |
| 14 `SafePath`/canonical IP; symlink, `..` | H17 | geçerli değil | ağ adresi yok. Yollar: conf yolu çağırandan, pty yolu kendi tmux sunucumuzdan; `tty_is_masked` salt okuma + `O_NONBLOCK`, tty değilse `None` (`unknown_for_empty_missing_and_non_tty`) |
| 15 Vekil/WS kullanıcı yolundan e2e | H15, H18, H21 | geçerli değil | vekil/WS yok. Kullanıcı yolu karşılığı: gerçek tmux'a gerçek pane ile gidiş-dönüş (`tests/real_tmux.rs`) |
| 16 Route tabloları eşitliği | H10, H14 | geçerli değil | uç/route eklenmedi |
| 17 Test yalıtımı; canlı dizin değişmez | H16 | karşılandı | `tests_never_touch_the_live_socket`; `common::Server` (geçici `TMUX_TMPDIR`, rastgele soket, `Drop`ta `kill-server`); `TempDir` RAII; canlı durum dizinine giden kod yok (`no_state_dir_home_file_writes_...`) |
| 18 Uzak host sürüm/yetenek, devre kesici, deploy smoke | H10, H11 | geçerli değil | crate yalnız yerel tmux soketi; uzak pane'ler federasyon izinde (`cops-hosts`) |
| 19 `GIT_SHA`, canlı = main, `*.prev`, restart kurtarma | H11 | geçerli değil | kütüphane crate'i; ikili sürümü ve geri dönüş copsd'de. Uzun iş yok (en uzun çağrı `send_text_timeout`) |
| 20 Ölçüm/kanıt; `--dry-run` yan etkisiz; Python'a yeni özellik yok | H21 | karşılandı | oynaklık 5 ardışık koşuyla ölçüldü; iki testin yakaladığı mutasyonla gösterildi (yukarıda); `--dry-run` yok; Python'a yalnız sahibin onayladığı hata düzeltmeleri (TBD 366/367, ayrı `fix` commit'leri, her biri testli), yeni özellik yok |

Bölüm 1'deki ilgili sınıflar: H1 (madde 9), H4 (2.2, madde 8), H5 (madde 10), H7 (madde 1), H8 (madde 7), H9/H20 (madde 4, 5), H14 (madde 11, 12), H16 (madde 17). Kontrol listesinin atıf verdiği diğer sınıflar (H2, H3, H10-H13, H15, H17-H19, H21) yukarıdaki satırlarda gerekçesiyle.

## Eşleme tablosu (sahip EK 2, 26 Kas)
Üretim: satırların adları elle yazılmadı; `ast` ile çıkarıldı (`tmux_backend.py` üst düzey tanımları, ilgili test metotları), karşılık sütunları iz oturumunun değerlendirmesi. Doğrulama betiği tabloyu yeniden `ast` çıktısıyla karşılaştırır: tanım farkı 0, test metodu farkı 0, boş ya da "sonra" satırı 0, tabloda anılan her Rust test adı crate'te var.

Kapsam:
- Tanımlar: `py/claudeops/tmux_backend.py`nin TÜM üst düzey tanımları: 57 (39 işlev, 14 sabit, 4 regex; sınıf/yöntem yok).
- Test metotları (462): (a) metninde `tmux_backend` geçen 21 test dosyasının TÜM test metotları (335); (b) diğer test dosyalarında gövdesi `tmux_backend` adı anan (doğrudan, sınıf gövdesi ya da aynı dosyadaki yardımcı üzerinden; çoğu `mock.patch` ile başka modüldeki kopyayı sahteler) test metotları (127, 27 dosya).
- Sonuç: 462 test metodundan 87'si bu crate'te karşılandı (78 parite, 8 yalnız Rust testi, 1 tür denetimi), 375'i kapsam dışı (başka izin modülünü sınar; iz tabloda yazılı). TBD 366/367 düzeltmelerinin Python testleri (19 metot, 5 dosya) tabloda.

Parite testleri (`rust/crates/cops-tmux/tests/parity.rs`, köprü `tests/parity.py`):
- PR `reads_match_python`: gerçek tmux'ta okuma işlevleri (has_session, capture, capture_range, pane_size, snapshot, maske, client_count).
- PP `pure_functions_match_python_on_random_screens`: `strip_ansi`, `typed_input_in_box`, `input_box` (6.000 rastgele ekran), `ctx_label`.
- PW `writes_match_python`: send_keys/raw/special_key ile pane'e ulaşan baytlar, resize.
- PC `constants_patterns_and_shell_fragments_match_python`: tüm sabitler, 4 regex deseni, `tmux_available`, `tmux_conf_path`, `_base_argv`, `_exact`, `_addressable`, `_tmux_arg`, iki kabuk parçası (300 ad/cwd/komut bileşimi; hedeflenemeyen adda Python `ValueError` = Rust `BadArgument`).
- PD `dim_fg_and_segment_typed_match_python`: `_is_dim_fg`, `_seg_typed` (3.000'er rastgele girdi).
- PF `every_tmux_call_matches_python_argv_and_result_on_a_fake_tmux`: sahte tmux (`fake_tmux.sh`): tmux çağıran HER işlevde aynı çıktı/çıkış kodu senaryosunda Python ve Rust'ın argv kayıtları, `load-buffer` girdisi ve sonucu eşit (hata yolları, bozuk çıktılar, `push_ctx` dizileri, tmux kurulu değil); süreç tarafı gerçek `/proc` (`_pid_childless`, `is_tmux_backed`, `_outer_bash_via_list_clients`, yedek tarama).
- PL `lifecycle_matches_python_on_a_real_server`: `spawn_direct` (sunucuyu başlatan), hayalet, `_pid_childless`, `is_tmux_backed`, `tty_is_masked`, `kill_session`.
- PCL `clients_messages_ctx_and_sizes_match_python_on_a_real_server`: bağlı istemciyle `client_session`, `client_count`, dış bash, `tmux_message` (istemcinin durum satırında görünen metin eşit), `set_ctx`/`push_ctx` (yazılan seçenek eşit), `release_size`, maske (parola/ham/normal pane).
- PB `python_bug_fixes_p1_to_p7_behave_the_same_in_rust`: P1-P5 düzeltmeleri (ikiz sunucularda hedeflenemeyen adla iki taraf da reddeder, oturumlar yerinde; `=eq`/`@1`/`%1` doğru hedeflenir; `;`'li ad/cwd ile açılış; C yerelinde istemci/hayalet bulunur), düşmanca adlar; P6 PCL'de, P7 PF'de.

Bu turda bulunan farklar (Rust Python'a eşitlendi; parite testi farkı yakaladı, düzeltme sonrası yeşil; ikisi mutasyonla yeniden sınandı):
- `pane_size`: Python `stdout.strip().splitlines()[0].split()`; Rust ilk boş olmayan `\n` satırını alıyordu. Boşluk-yalnız ilk satır, `\f`/`\x1c` gibi satır sonları ve `\x1f` ayırıcıda sonuç farklıydı. `alternate_on` Python'da `bool(int())` (ör. `300` doğru), Rust `u8` ile hata veriyordu.
- `client_count`, `client_session`, `ghost_session`: Python `splitlines()`, Rust `lines()`; `\f`, `\v`, `\x1c`-`\x1e`, `\x85`, U+2028/2029 satır sonu sayılmıyordu (ör. `a\fb` Python 2 istemci, Rust 1).
- `_outer_bash_via_list_clients`: Python `str.split()` `\x1c`-`\x1f`yi de ayırıcı sayar.
- `tmux_conf_path`: Python yalnız paket dizinini çözer (`resolve().parent / data / tmux.conf`), Rust tüm yolu (`tmux.conf` bağ olsaydı farklı yol).
- Yeni ortak yardımcılar `text::py_strip/py_split/py_splitlines` (Python 3.10 vektörleriyle `str_helpers_match_python`). Ters yön de sınandı: `int()`/`float()` kırpması `str.strip`ten farklıdır (`\x1c`-`\x1f` atılmaz); Rust `str::trim` bununla zaten eşti, `pid_childless`/hayalet zaman damgası ona göre bırakıldı (parite testi yanlış eşitlemeyi yakaladı).

Bilinen, eşitlenmeyen biçim farkları (yalnız tmux'un üretmediği bozuk çıktıda): Python `int()` eksi sayıyı, `_` ayraçlı ve Unicode rakamlı sayıyı kabul eder; Rust `PaneSize`/`Snapshot` alanları `u32` olduğundan bu çıktıda `BadOutput` döner (Python garip bir demet). Hatalar `None`/`False` yerine `TmuxError` (tasarım kararı, yukarıda).

Python hatası gibi görünen yeni davranış: P3'ün kapsamı daraldı (yalnız `display-message`) ve P5'in `$TMUX` tanımlıyken gizlendiği bulundu. P1-P7 ve TBD 367 sonradan sahip kararıyla iki tarafta düzeltildi ("Python hataları", "Maske durumu bilinmiyorken gönderim"); P1-P9 dışında yeni aday yok.

<!-- eşleme tablosu: üretici betik, ast ile -->
| Python tanımı (dosya:satır ad, tür) | Rust yol::ad | Parite testi | Durum |
|---|---|---|---|
| `py/claudeops/tmux_backend.py:22` `TMUX_SOCKET` (sabit) | `runner::TMUX_SOCKET` | PC | eş |
| `py/claudeops/tmux_backend.py:23` `_TIMEOUT` (sabit) | `runner::DEFAULT_TIMEOUT` | PC | eş |
| `py/claudeops/tmux_backend.py:24` `_ANCESTOR_WALK_LIMIT` (sabit) | `proc::ANCESTOR_WALK_LIMIT` | PC | eş |
| `py/claudeops/tmux_backend.py:27` `tmux_available` (işlev) | `shell::tmux_available` | PC (aynı `PATH`) | eş |
| `py/claudeops/tmux_backend.py:31` `tmux_conf_path` (işlev) | `shell::tmux_conf_path(core_py_dir)` | PC | eş (yol parametre; yalnız paket dizini çözülür, bu turda Python'a eşitlendi) |
| `py/claudeops/tmux_backend.py:35` `_base_argv` (işlev) | `runner::Tmux::base_argv` | PC, PF (her argv) | eş |
| `py/claudeops/tmux_backend.py:39` `_base_argv_utf8` (işlev) | `runner::Tmux::text_utf8` (`-u -L <soket>`) | PF (client_session, ghost_session argv), PB (P5) | eş (yeni, P5 düzeltmesi, TBD 366) |
| `py/claudeops/tmux_backend.py:47` `_exact` (işlev) | `runner::exact_target` (`Result`) | PC, PB | eş (P1-P3 düzeltildi iki tarafta, TBD 366: hedeflenemeyen ad Python `ValueError`, Rust `BadArgument("name")`) |
| `py/claudeops/tmux_backend.py:71` `_addressable` (işlev) | `runner::addressable` | PC, PB | eş (yeni, P1-P3 düzeltmesi, TBD 366) |
| `py/claudeops/tmux_backend.py:79` `_tmux_arg` (işlev) | `runner::escape_arg` | PC (`_tmux_arg`, kabuk parçaları), PB (P4), PCL (P6) | eş (yeni, P4/P6 düzeltmesi, TBD 366) |
| `py/claudeops/tmux_backend.py:86` `tmux_new_session_shell_fragment` (işlev) | `shell::Tmux::new_session_shell_fragment` (+`shell_quote`) | PC | eş (conf yolu parametre; dönüş `Result`: hedeflenemeyen ad `BadArgument`; ad/cwd/iç komut `;` kaçışı, P1-P4 düzeltildi, TBD 366) |
| `py/claudeops/tmux_backend.py:105` `tmux_attach_shell_fragment` (işlev) | `shell::Tmux::attach_shell_fragment` | PC | eş (dönüş `Result`: hedeflenemeyen ad `BadArgument`, P1-P3 düzeltildi, TBD 366) |
| `py/claudeops/tmux_backend.py:113` `tmux_spawn_direct` (işlev) | `shell::Tmux::spawn_direct` | PF, PL, PB (P4) | eş (dönüş `Result`; P1-P4 düzeltildi iki tarafta, TBD 366) |
| `py/claudeops/tmux_backend.py:140` `tmux_has_session` (işlev) | `query::Tmux::has_session` | PR, PF, PB | eş (`Err` = Python `False`) |
| `py/claudeops/tmux_backend.py:149` `tmux_capture` (işlev) | `query::Tmux::capture` | PR, PF, PB | eş |
| `py/claudeops/tmux_backend.py:162` `tmux_capture_range` (işlev) | `query::Tmux::capture_range` | PR, PF | eş (`int()` zorlaması yerine `i64` türü) |
| `py/claudeops/tmux_backend.py:188` `ANSI_SGR_RE` (regex) | `text::ANSI_SGR_RE` (`patterns()`) | PC (desen metni), PP | eş |
| `py/claudeops/tmux_backend.py:189` `ANSI_OSC_RE` (regex) | `text::ANSI_OSC_RE` (`patterns()`) | PC, PP | eş |
| `py/claudeops/tmux_backend.py:192` `strip_ansi` (işlev) | `text::strip_ansi` | PP, PR | eş |
| `py/claudeops/tmux_backend.py:196` `tmux_send_keys` (işlev) | `keys::Tmux::send_text` (+`send_text_timeout`) | PW, PF (argv + `load-buffer` girdisi) | eş (tampon adı `cops-rs-*`; P8, P9 TBD 369) |
| `py/claudeops/tmux_backend.py:250` `ALLOWED_SPECIAL_KEYS` (sabit) | `keys::ALLOWED_SPECIAL_KEYS` | PC | eş |
| `py/claudeops/tmux_backend.py:253` `RESIZE_COLS` (sabit) | `keys::RESIZE_COLS` | PC | eş |
| `py/claudeops/tmux_backend.py:254` `RESIZE_ROWS` (sabit) | `keys::RESIZE_ROWS` | PC | eş |
| `py/claudeops/tmux_backend.py:257` `tmux_resize_window` (işlev) | `keys::Tmux::resize_window` | PW, PF | eş |
| `py/claudeops/tmux_backend.py:271` `ctx_label` (işlev) | `text::ctx_label` | PP | eş |
| `py/claudeops/tmux_backend.py:281` `tmux_set_ctx` (işlev) | `query::Tmux::set_ctx` | PF, PCL (P6) | eş (P6 düzeltildi iki tarafta, TBD 366) |
| `py/claudeops/tmux_backend.py:292` `_CTX_PUSHED` (sabit) | `proc::CtxPusher` (alan `pushed`, sınır `CTX_CACHE_LIMIT` 512) | PC (başlangıçta boş), PF, PCL (dizi) | eş (önbellek nesne başına, Python'da modül geneli) |
| `py/claudeops/tmux_backend.py:295` `push_ctx` (işlev) | `proc::CtxPusher::push` | PF (3 hata dizisi), PCL | eş |
| `py/claudeops/tmux_backend.py:309` `tmux_release_size` (işlev) | `keys::Tmux::release_size` | PF, PCL | eş |
| `py/claudeops/tmux_backend.py:321` `tmux_send_special_key` (işlev) | `keys::Tmux::send_special_key` | PW, PF | eş |
| `py/claudeops/tmux_backend.py:336` `_RAW_CHUNK_CHARS` (sabit) | `keys::RAW_CHUNK_CHARS` | PC | eş |
| `py/claudeops/tmux_backend.py:339` `tmux_send_raw` (işlev) | `keys::Tmux::send_raw` | PW, PF | eş |
| `py/claudeops/tmux_backend.py:375` `tmux_client_count` (işlev) | `query::Tmux::client_count` | PR, PF, PCL | eş (satır bölme bu turda Python `splitlines`e eşitlendi) |
| `py/claudeops/tmux_backend.py:396` `tmux_client_session` (işlev) | `query::Tmux::client_session` | PF, PCL, PB (P5) | eş (`Err`/`Ok(None)` ayrımı, Python ikisine `None`; satır bölme eşitlendi; P5 düzeltildi iki tarafta, TBD 366) |
| `py/claudeops/tmux_backend.py:420` `tmux_message` (işlev) | `keys::Tmux::message` (+`safe_message`) | PF, PCL (durum satırındaki metin) | eş |
| `py/claudeops/tmux_backend.py:453` `HISTORY_LIMIT` (sabit) | `query::HISTORY_LIMIT` | PC | eş |
| `py/claudeops/tmux_backend.py:456` `tmux_pane_size` (işlev) | `query::Tmux::pane_size` | PR, PF, PW, PB | eş (bu turda `strip/splitlines/split` ve `bool(int())` Python'a eşitlendi; eksi/Unicode rakamlı bozuk çıktıda Rust hata döner) |
| `py/claudeops/tmux_backend.py:492` `pane_is_masked_input` (işlev) | `query::Tmux::pane_is_masked_input` | PR, PF, PCL, PB | eş (`None` iken otomatik gönderim yok: Rust `MaskGuard::RefuseMasked` -> `MaskUnknown`, Python `web._context`, TBD 367) |
| `py/claudeops/tmux_backend.py:514` `tty_is_masked` (işlev) | `mask::tty_is_masked` | PL, PCL | eş |
| `py/claudeops/tmux_backend.py:541` `_SNAPSHOT_FORMAT` (sabit) | `query::SNAPSHOT_FORMAT` | PC | eş |
| `py/claudeops/tmux_backend.py:544` `_SGR_RE` (regex) | `text::SGR_RE` (`patterns()`) | PC, PP | eş |
| `py/claudeops/tmux_backend.py:545` `_ANSI_ANY_RE` (regex) | `text::ANSI_ANY_RE` (`patterns()`) | PC, PP | eş |
| `py/claudeops/tmux_backend.py:546` `_BOX_RULE_CHARS` (sabit) | `text::BOX_RULE_CHAR` | PC | eş |
| `py/claudeops/tmux_backend.py:547` `_PROMPT_CHAR` (sabit) | `text::PROMPT` | PC | eş |
| `py/claudeops/tmux_backend.py:550` `_is_dim_fg` (işlev) | `text::dim_fg` | PD, PP | eş (kullanılmayan `cur_dim` parametresi yok) |
| `py/claudeops/tmux_backend.py:577` `typed_input_in_box` (işlev) | `text::typed_input_in_box` | PP, PR | eş |
| `py/claudeops/tmux_backend.py:605` `input_box` (işlev) | `text::input_box` (`InputBox`) | PP, PR | eş |
| `py/claudeops/tmux_backend.py:631` `_seg_typed` (işlev) | `text::segment_typed` | PD, PP | eş |
| `py/claudeops/tmux_backend.py:643` `tmux_pane_snapshot` (işlev) | `query::Tmux::snapshot` (`Snapshot`) | PR, PF, PB | eş |
| `py/claudeops/tmux_backend.py:675` `_GHOST_SHELLS` (sabit) | `shell::GHOST_SHELLS` | PC | eş |
| `py/claudeops/tmux_backend.py:676` `GHOST_MIN_AGE_SECONDS` (sabit) | `shell::GHOST_MIN_AGE_SECONDS` | PC | eş |
| `py/claudeops/tmux_backend.py:679` `tmux_ghost_session` (işlev) | `shell::Tmux::ghost_session` | PF, PL, PB (P5) | eş (satır bölme eşitlendi; P5 düzeltildi iki tarafta, TBD 366) |
| `py/claudeops/tmux_backend.py:705` `_pid_childless` (işlev) | `proc::pid_childless` | PF, PL | eş |
| `py/claudeops/tmux_backend.py:714` `tmux_kill_session` (işlev) | `shell::Tmux::kill_session` | PF, PL, PB | eş (Python `None`, Rust `Result`) |
| `py/claudeops/tmux_backend.py:722` `_outer_bash_via_list_clients` (işlev) | `proc::Tmux::outer_bash_via_list_clients` | PF, PCL | eş |
| `py/claudeops/tmux_backend.py:750` `find_outer_bash_pids` (işlev) | `proc::Tmux::find_outer_bash_pids` | PF (yedek tarama, P7), PCL | eş (P7 düzeltildi iki tarafta, TBD 366: yalnız bu kullanıcının süreçleri) |
| `py/claudeops/tmux_backend.py:811` `is_tmux_backed` (işlev) | `proc::Tmux::is_tmux_backed` | PF, PL | eş |

| Python test metodu (`py/tests/` dosya::sınıf::metot) | Rust karşılığı / parite testi | Durum |
|---|---|---|
| `test_bg_work.py::SubagentActiveForUsesBoth::test_screen_makes_active_even_without_subagent_files` | yok: `bg_work`/`web_steward` meşguliyet kararı; tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_bg_work.py::SubagentActiveForUsesBoth::test_transcript_pending_makes_active` | yok: `bg_work`/`web_steward` meşguliyet kararı; tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_a_recent_request_gives_its_age_and_the_one_hour_ttl` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_a_cli_without_a_cache_lifetime_has_no_info_and_is_never_probed` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_no_matching_transcript_is_unknown_not_cold` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_an_expired_cache_still_reports_so_the_ui_can_show_cold` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_the_probe_is_cached_but_the_age_keeps_advancing` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_the_probe_is_repeated_after_the_ttl_and_sees_a_new_request` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_a_failing_provider_is_unknown_never_an_error_and_is_not_hammered` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_a_clock_skew_never_gives_a_negative_age` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_a_restarted_session_with_a_new_pid_is_probed_afresh` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::CacheInfoTests::test_retired_sessions_do_not_pile_up_in_the_cache` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::StatusPayloadCacheTests::test_both_running_row_builders_carry_the_cache_info` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_cache_info.py::StatusPayloadCacheTests::test_a_stopped_row_has_none` | yok: `/api/status` oturum satırı (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_context_mask_unknown.py::ContextMaskGuardTests::test_unknown_mask_state_sends_nothing_and_says_why` | `argv::unknown_mask_state_blocks_every_automatic_send_but_not_user_typing`, `real_tmux::unknown_mask_state_refuses_injection_on_a_real_server` (`MaskGuard::RefuseMasked`; `_context` ucu T2) | karşılandı (yalnız Rust testi) |
| `test_context_mask_unknown.py::ContextMaskGuardTests::test_masked_still_refused` | `real_tmux::masked_pane_refuses_injection_but_accepts_user_typing` | karşılandı (yalnız Rust testi) |
| `test_context_mask_unknown.py::ContextMaskGuardTests::test_known_unmasked_pane_gets_the_command` | `real_tmux::unknown_mask_state_refuses_injection_on_a_real_server` (durumu bilinen pane gönderimi alır) | karşılandı (yalnız Rust testi) |
| `test_directive_delivery.py::SendVerified::test_delivered_when_message_appears` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_old_identical_header_does_not_fake_delivery` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_pasted_text_in_box_gets_enter` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_pasted_text_ignoring_enter_gets_space_then_enter` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_permanently_stuck_paste_fails_without_resend` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_text_unsent_in_input_box_is_not_delivered` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_text_stuck_in_input_box_forever_fails_without_resend` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_placeholder_text_in_transcript_does_not_trigger_enter` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_pasted_placeholder_in_input_box_gets_enter` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_grey_suggestion_in_box_is_not_unsent_text` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_colored_typed_text_in_box_counts_as_unsent` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_resend_when_nothing_arrived` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::SendVerified::test_ucli_unverified_skip` | yok: direktif teslimi (`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_directive_delivery.py::HoDoneFresh::test_ho_done_live_session_stopped_exact_and_started_fresh` | yok: direktif teslimi (`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_handover_cache_policy.py::CallSiteWiringTests::test_cli_path_calls_the_shared_policy_once_per_target` | yok: devir model/effort (`handover`); tmux_backend adları (`is_tmux_backed`, `tmux_send_keys`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_handover_cache_policy.py::CallSiteWiringTests::test_web_path_calls_the_shared_policy_with_the_spawn_time_values` | yok: devir model/effort (`handover`); tmux_backend adları (`is_tmux_backed`, `tmux_send_keys`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_handover_cache_policy.py::CallSiteWiringTests::test_web_path_targets_the_resolved_session_for_unique_base` | yok: devir model/effort (`handover`); tmux_backend adları (`is_tmux_backed`, `tmux_send_keys`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_handover_cache_policy.py::CallSiteWiringTests::test_real_policy_runs_end_to_end_through_the_web_path` | yok: devir model/effort (`handover`); tmux_backend adları (`is_tmux_backed`, `tmux_send_keys`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_input_box_typed.py::TypedBoxTest::test_empty_box_is_not_typed` | `text::tests::typed_vs_suggestion`; PP, PR | karşılandı (parite) |
| `test_input_box_typed.py::TypedBoxTest::test_grey_suggestion_is_not_typed` | `text::tests::typed_vs_suggestion`; PP, PR | karşılandı (parite) |
| `test_input_box_typed.py::TypedBoxTest::test_default_color_text_is_typed` | `text::tests::typed_vs_suggestion`; PP, PR | karşılandı (parite) |
| `test_input_box_typed.py::TypedBoxTest::test_whitespace_only_and_borders_ignored` | `text::tests::typed_vs_suggestion`; PP, PR | karşılandı (parite) |
| `test_input_box_typed.py::TypedBoxTest::test_no_box_is_unknown` | `text::tests::typed_vs_suggestion`; PP, PR | karşılandı (parite) |
| `test_input_box_typed.py::TypedBoxTest::test_last_box_wins` | `text::tests::typed_vs_suggestion`; PP, PR | karşılandı (parite) |
| `test_input_box_typed.py::TypedBoxTest::test_ucli_uses_its_own_box_reader` | yok: `web_steward._box_has_typed_input`in ucli dalı (T10 değnekçi) | kapsam dışı |
| `test_input_box_typed.py::TypedBoxTest::test_helper_false_on_error_and_unknown` | yok: `web_steward._box_has_typed_input` yardımcısı, `tmux_pane_snapshot` sahte (T10) | kapsam dışı |
| `test_input_box_typed.py::KeepwarmApplyTest::test_box_full_skips_keepwarm` | yok: keepwarm uygulaması `web_steward` (T10) | kapsam dışı |
| `test_input_box_typed.py::KeepwarmApplyTest::test_box_empty_sends_keepwarm` | yok: keepwarm uygulaması `web_steward` (T10) | kapsam dışı |
| `test_input_box_typed.py::ApiNudgeApplyTest::test_box_full_skips_nudge` | yok: API dürtmesi `web_steward` (T10) | kapsam dışı |
| `test_input_box_typed.py::ApiNudgeApplyTest::test_target_denied_skips_nudge` | yok: API dürtmesi `web_steward` (T10) | kapsam dışı |
| `test_input_box_typed.py::ApiNudgeApplyTest::test_box_empty_sends_nudge` | yok: API dürtmesi `web_steward` (T10) | kapsam dışı |
| `test_kill_access_denied.py::KillAccessDeniedTests::test_access_denied_still_cleans_up` | yok: `kill.kill_session_and_parent` sırası (T4); ilkeller `kill_session`, `find_outer_bash_pids` PF/PL | kapsam dışı |
| `test_live_model_effort.py::LastAssistantSinceTests::test_since_returns_only_rows_written_after_the_process_started` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LastAssistantSinceTests::test_only_previous_incarnation_rows_means_unknown` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LastAssistantSinceTests::test_without_since_behaviour_is_unchanged` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LastAssistantSinceTests::test_row_without_timestamp_is_not_treated_as_old` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LastAssistantSinceTests::test_scan_stops_at_the_first_older_row` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_live_values_written_by_this_process_replace_cmdline_values` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_fresh_resume_without_a_turn_keeps_cmdline_values` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_effort_missing_in_live_rows_falls_back_per_field` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_another_sessions_file_is_ignored` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_non_claude_and_sidless_sessions_never_touch_the_file` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_unknown_process_start_falls_back` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_unchanged_file_is_not_reread_and_changed_file_is_` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEffortTests::test_read_error_falls_back_and_does_not_raise` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEndpointTests::test_live_model_ignores_previous_incarnation` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEndpointTests::test_live_effort_ignores_previous_incarnation` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::LiveModelEndpointTests::test_neighbour_transcript_is_not_reported` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_live_model_effort.py::EffortSwitchNoBlindEnter::test_no_dialog_no_enter` | yok: canlı model/effort okuma ve geçiş (`/api/live-model`, sağlayıcı) (T4) | kapsam dışı |
| `test_outer_bash_list_clients.py::ListClientsTests::test_client_parent_bash_found` | `lifecycle::outer_bash_is_found_through_the_client_list`; PF, PCL | karşılandı (parite) |
| `test_outer_bash_list_clients.py::ListClientsTests::test_failure_returns_empty` | `argv::outer_bash_with_garbage_client_pids_is_empty`; PF (rc 1, çöp pid) | karşılandı (parite) |
| `test_outer_bash_list_clients.py::ListClientsTests::test_find_uses_native_first_then_falls_back` | `lifecycle::outer_bash_is_found_through_the_client_list`, `lifecycle::outer_bash_falls_back_to_scanning_command_lines`; PF (istemci listesi dolu/boş) | karşılandı (parite) |
| `test_outer_bash_list_clients.py::ListClientsTests::test_fallback_matches_open_window_exact_target` | `lifecycle::outer_bash_falls_back_to_scanning_command_lines`; PF (yedek tarama, `attach-session -t =ad:` biçimi) | karşılandı (parite) |
| `test_outer_bash_user_filter.py::FallbackScanUserTests::test_own_window_is_found` | `proc::tests::fallback_scan_counts_only_this_users_windows`; PF (yedek tarama) | karşılandı (parite) |
| `test_outer_bash_user_filter.py::FallbackScanUserTests::test_another_users_window_with_the_same_name_is_not` | `proc::tests::fallback_scan_counts_only_this_users_windows` (başka kullanıcı parite köprüsünde taklit edilemez) | karşılandı (yalnız Rust testi) |
| `test_proc08_model_switch_no_blind_enter.py::NoBlindEnterTest::test_permission_dialog_is_not_confirmed` | yok: `apply_live_model_switch` diyalog kararı (T4 sağlayıcı) | kapsam dışı |
| `test_proc08_model_switch_no_blind_enter.py::NoBlindEnterTest::test_switch_dialog_confirmed_once` | yok: `apply_live_model_switch` diyalog kararı (T4 sağlayıcı) | kapsam dışı |
| `test_proc08_model_switch_no_blind_enter.py::NoBlindEnterTest::test_applied_without_dialog` | yok: `apply_live_model_switch` diyalog kararı (T4 sağlayıcı) | kapsam dışı |
| `test_review_fixes_2026_11_04.py::HandoverBatchFixes::test_dry_run_does_not_write_baseline_and_shows_skip` | yok: `handover`/`guard` düzeltmeleri; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_review_fixes_2026_11_04.py::HandoverBatchFixes::test_real_run_writes_baseline_atomically` | yok: `handover`/`guard` düzeltmeleri; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_review_fixes_2026_11_04.py::HandoverBatchFixes::test_sidless_session_in_shared_cwd_is_not_skipped` | yok: `handover`/`guard` düzeltmeleri; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_spawn_ghost_reclaim.py::GhostDetectTest::test_old_bare_bash_is_ghost` | `shell::tests::old_bare_bash_is_ghost`, `lifecycle::ghost_is_only_an_old_childless_shell`; PF, PL | karşılandı (parite) |
| `test_spawn_ghost_reclaim.py::GhostDetectTest::test_live_cli_is_not_ghost` | `shell::tests::live_cli_is_not_ghost`, `lifecycle::ghost_is_only_an_old_childless_shell`; PF, PL | karşılandı (parite) |
| `test_spawn_ghost_reclaim.py::GhostDetectTest::test_young_session_is_not_ghost` | `shell::tests::young_session_is_not_ghost`, `lifecycle::ghost_is_only_an_old_childless_shell`; PF, PL | karşılandı (parite) |
| `test_spawn_ghost_reclaim.py::GhostDetectTest::test_bash_with_child_is_not_ghost` | `shell::tests::bash_with_child_is_not_ghost`, `lifecycle::ghost_is_only_an_old_childless_shell`; PF, PL | karşılandı (parite) |
| `test_spawn_ghost_reclaim.py::GhostDetectTest::test_no_session_or_garbage` | `shell::tests::empty_or_garbage_is_not_ghost`, `lifecycle::ghost_is_only_an_old_childless_shell`; PF, PL | karşılandı (parite) |
| `test_spawn_ghost_reclaim.py::GhostDetectTest::test_mixed_panes` | `shell::tests::mixed_panes_are_not_ghost`, `lifecycle::ghost_is_only_an_old_childless_shell`; PF, PL | karşılandı (parite) |
| `test_spawn_ghost_reclaim.py::ReclaimTest::test_ghost_killed_and_tail_logged` | yok: `spawn` hayalet geri alma akışı (T4) | kapsam dışı |
| `test_spawn_ghost_reclaim.py::ReclaimTest::test_shell_provider_untouched` | yok: `spawn` hayalet geri alma akışı (T4) | kapsam dışı |
| `test_spawn_ghost_reclaim.py::ReclaimTest::test_not_ghost_untouched` | yok: `spawn` hayalet geri alma akışı (T4) | kapsam dışı |
| `test_spawn_ghost_reclaim.py::ReclaimTest::test_error_never_raises` | yok: `spawn` hayalet geri alma akışı (T4) | kapsam dışı |
| `test_steward_answer_dialog_blocked.py::PermissionDialog::test_classified_as_permission_not_pressed` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_answer_dialog_blocked.py::PermissionDialog::test_brain_restart_refused_while_dialog_open_but_not_when_stale` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_answer_dialog_blocked.py::TrustRecheckRace::test_stale_screen_after_accept_is_waited_out` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_answer_dialog_blocked.py::TrustRecheckRace::test_dialog_that_never_clears_still_fails` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_api_recovery.py::ApplyTest::test_nudge_sends_devam_to_tmux_session` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_api_recovery.py::ApplyTest::test_nudge_refused_when_not_tmux_or_not_running` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestO2UnknownRemoteState::test_an_unknown_state_stays_open_keeps_polling_and_is_logged_once` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestO2UnknownRemoteState::test_known_states_unchanged` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend::test_lock_timeout_while_recording_the_directive_does_not_unmark_the_delivery` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend::test_a_single_lock_timeout_on_the_delivery_mark_is_retried` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend::test_persistent_lock_timeout_on_the_mark_is_logged_not_raised` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend::test_next_tick_does_not_resend_what_already_went_out` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_audit_p9.py::TestD5LockTimeoutAfterSend::test_job_delivery_mark_timeout_is_not_raised_either` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_dialog_stuck.py::RecoverTest::test_unknown_dialog_presses_no_keys_and_notifies_once` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_dialog_stuck.py::RecoverTest::test_trust_unregistered_folder_not_touched` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_send_special_key`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_dialog_stuck.py::RecoverTest::test_trust_registered_folder_accepted` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_dialog_stuck.py::RecoverTest::test_accepted_then_waits_for_prompt_marker_before_send` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_dialog_stuck.py::RecoverTest::test_wait_prompt_ready_times_out_but_does_not_block` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_dialog_stuck.py::RecoverTest::test_wait_prompt_ready_immediate` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_generic.py::TestTourBacklog::test_generic_tour_item_has_backlog` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_generic.py::TestTourBacklog::test_plain_steward_tour_is_unchanged` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_http.py::WakeGateTest::test_gate_is_skipped_when_the_directive_just_opened_the_session` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_job_gate_and_qcap.py::Gate::test_rejected_without_service_no_question` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_job_gate_and_qcap.py::GateMessage::test_note_has_catalogue_hint_file_rule_and_closest_kinds` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_remote_facts.py::TestExact::test_stop_exact_requires_full_name` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`, `tmux_has_session`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_remote_facts.py::TestExact::test_stop_without_exact_keeps_unique_base` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`, `tmux_has_session`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_remote_facts.py::TestExact::test_term_input_exact` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`, `tmux_has_session`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_remote_facts.py::TestExact::test_handover_exact_refuses_before_touching_session` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`, `tmux_has_session`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_remote_facts.py::TestExact::test_term_resolve_exact` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`, `tmux_has_session`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_nudge_is_sent_as_one_line` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_nudge_skipped_when_input_box_has_text` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_close_handover_pauses_project_when_no_work` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_close_handover_keeps_phase_when_work_remains` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_close_stop_and_respawn_use_existing_paths` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_turn_failed_close_stops_and_asks_owner_once` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_idle.py::ApplyTest::test_close_rejects_unknown_mode` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_ucli_text_folded_not_truncated` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_non_ucli_untouched_and_no_recheck` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_claude_trust_dialog_blocks_send` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_text_left_in_box_sends_one_more_enter` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`, `tmux_send_raw`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_still_stuck_logs_error` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`, `tmux_send_raw`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_stuck_event_uses_caller_sid` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`, `tmux_send_raw`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_late_drawn_text_gets_enter` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`, `tmux_send_raw`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::UcliSendTest::test_empty_box_no_extra_enter` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`, `tmux_send_keys`, `tmux_send_raw`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_prefixed_empty_prompt` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_prefixed_with_text` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_text_wrapped_over_two_lines` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_waiting_for_response_is_empty` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_turn_output_after_prompt_is_empty` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_last_prompt_line_wins` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ucli_send.py::BoxTextTest::test_no_prompt` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ui_api.py::DirectiveDatedSessionTest::test_dated_session_gets_the_directive_without_a_start` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_steward_ui_api.py::DirectiveDatedSessionTest::test_two_live_sessions_are_ambiguous_and_nothing_starts` | yok: değnekçi motoru (`steward`/`web_steward`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T10) | kapsam dışı |
| `test_stop_with_handover.py::LocalTest::test_success_handover_then_exact_stop` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::LocalTest::test_handover_send_failure_does_not_stop` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::LocalTest::test_timeout_does_not_stop` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::LocalTest::test_unreadable_baseline_does_not_handover_or_stop` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::LocalTest::test_not_applicable_returns_none` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::LocalTest::test_english_message` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::ReaskTest::test_reask_then_ready` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_stop_with_handover.py::ReaskTest::test_reask_still_none_does_not_close` | yok: `/api/stop` devir + kapat (`web`); tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_a_page_is_exactly_the_requested_lines_and_matches_tmux` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_lines_are_in_order_and_just_above_the_screen` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_pages_tile_the_whole_buffer_without_gaps_or_overlap` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_the_visible_range_equals_the_live_viewport` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_colours_are_kept` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_the_range_is_clamped_to_the_real_buffer` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_one_request_never_returns_more_than_the_cap` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_the_default_cap_is_far_below_a_full_capture` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_reversed_and_out_of_range_requests_are_errors` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_the_reply_carries_what_the_client_needs_to_realign` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_history_growth_shifts_the_numbering_and_the_reply_says_so` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_session_gone_is_a_clear_error_and_drops_the_resolve_cache` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_a_failed_capture_after_a_good_size_query_drops_the_resolve_cache_too` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_a_full_screen_app_that_started_in_the_alternate_screen_has_no_history` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_the_reply_flags_the_alternate_screen_even_when_old_history_exists` | yok: `web._term_history` ucu (T2); alttaki `capture_range`/`pane_size` PR, PF | kapsam dışı |
| `test_term_history.py::TermHistoryTests::test_range_values_cannot_reach_the_tmux_command_line` | `Tmux::capture_range(&str, i64, i64)`: sayı olmayan değer derlenmez (tür denetimi, test gerekmez); aralıklar PR, PF. Metinden sayıya çevirme T2 ucunda | karşılandı (tür denetimi) |
| `test_term_history.py::TermHistoryRouteTests::test_local_page` | yok: `/api/term/history` rotası (T2) | kapsam dışı |
| `test_term_history.py::TermHistoryRouteTests::test_it_needs_the_token` | yok: `/api/term/history` rotası (T2) | kapsam dışı |
| `test_term_history.py::TermHistoryRouteTests::test_name_and_integer_range_are_required` | yok: `/api/term/history` rotası (T2) | kapsam dışı |
| `test_term_history.py::TermHistoryRouteTests::test_a_remote_host_is_proxied_with_a_clean_query` | yok: `/api/term/history` rotası (T2) | kapsam dışı |
| `test_term_history.py::TermHistoryRouteTests::test_a_remote_error_status_reaches_the_client` | yok: `/api/term/history` rotası (T2) | kapsam dışı |
| `test_term_history.py::TermHistoryRouteTests::test_the_path_is_listed_as_host_routed` | yok: `/api/term/history` rotası (T2) | kapsam dışı |
| `test_term_history.py::ProxyGetDedupTests::test_dedup_defaults_to_on_and_keeps_one_entry_per_url` | yok: `web_hosts.proxy_get` (T5 federasyon) | kapsam dışı |
| `test_term_history.py::ProxyGetDedupTests::test_a_page_request_without_dedup_leaves_no_trace` | yok: `web_hosts.proxy_get` (T5 federasyon) | kapsam dışı |
| `test_term_history.py::ProxyGetDedupTests::test_without_dedup_overlapping_identical_requests_are_not_turned_away` | yok: `web_hosts.proxy_get` (T5 federasyon) | kapsam dışı |
| `test_term_history.py::DedupLastGoodBoundTests::test_cache_is_lru_bounded` | yok: `web_hosts._dedup_last_good` (T5) | kapsam dışı |
| `test_term_poll_interval.py::InputNotifiesTests::test_text_key_and_raw_input_wake_the_watchers` | yok: `/ws/term` aralığı (`web_ws`); tmux_backend adları (`tmux_send_keys`, `tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T2) | kapsam dışı |
| `test_term_poll_interval.py::InputNotifiesTests::test_failed_send_does_not_wake` | yok: `/ws/term` aralığı (`web_ws`); tmux_backend adları (`tmux_send_keys`, `tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T2) | kapsam dışı |
| `test_term_poll_interval.py::InputNotifiesTests::test_rejected_key_and_empty_raw_do_not_wake` | yok: `/ws/term` aralığı (`web_ws`); tmux_backend adları (`tmux_send_keys`, `tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T2) | kapsam dışı |
| `test_term_poll_interval.py::InputNotifiesTests::test_other_sessions_are_not_woken` | yok: `/ws/term` aralığı (`web_ws`); tmux_backend adları (`tmux_send_keys`, `tmux_send_raw`, `tmux_send_special_key`) sahte ya da dolaylı (T2) | kapsam dışı |
| `test_term_resize.py::SizeFollowerTests::test_a_window_matching_the_pane_never_posts` | yok: `watch.SizeFollower` (`cops watch`, T6 CLI) | kapsam dışı |
| `test_term_resize.py::SizeFollowerTests::test_a_stable_different_size_posts_once_with_the_status_bar_row_removed` | yok: `watch.SizeFollower` (`cops watch`, T6 CLI) | kapsam dışı |
| `test_term_resize.py::SizeFollowerTests::test_a_changing_size_restarts_the_wait_and_arriving_at_the_expected_size_cancels` | yok: `watch.SizeFollower` (`cops watch`, T6 CLI) | kapsam dışı |
| `test_term_resize.py::SizeFollowerTests::test_a_rejected_request_disables_following_for_the_window_lifetime` | yok: `watch.SizeFollower` (`cops watch`, T6 CLI) | kapsam dışı |
| `test_term_resize.py::SizeFollowerTests::test_release_posts_only_after_a_size_was_sent` | yok: `watch.SizeFollower` (`cops watch`, T6 CLI) | kapsam dışı |
| `test_term_resize.py::SizeFollowerTests::test_the_same_size_is_not_sent_twice` | yok: `watch.SizeFollower` (`cops watch`, T6 CLI) | kapsam dışı |
| `test_term_resize.py::ViewerHookTests::test_observed_after_the_window_was_asked_to_match_the_pane` | yok: `watch.Viewer` kancası (T6) | kapsam dışı |
| `test_term_resize.py::ViewerHookTests::test_not_observed_when_resize_is_disabled_or_pane_unknown` | yok: `watch.Viewer` kancası (T6) | kapsam dışı |
| `test_term_resize.py::ServerSideTests::test_resizes_a_session_without_attached_clients` | yok: `web._term_resize` ucu (T2); alttaki resize/release PF, PW, PCL | kapsam dışı |
| `test_term_resize.py::ServerSideTests::test_refuses_when_a_client_is_attached_or_unknown` | yok: `web._term_resize` ucu (T2); alttaki resize/release PF, PW, PCL | kapsam dışı |
| `test_term_resize.py::ServerSideTests::test_rejects_out_of_range_and_non_integer_sizes` | yok: `web._term_resize` ucu (T2); alttaki resize/release PF, PW, PCL | kapsam dışı |
| `test_term_resize.py::ServerSideTests::test_release_does_not_need_a_size_and_skips_the_client_check` | yok: `web._term_resize` ucu (T2); alttaki resize/release PF, PW, PCL | kapsam dışı |
| `test_term_resize.py::ServerSideTests::test_the_route_is_host_routed` | yok: `web._term_resize` ucu (T2); alttaki resize/release PF, PW, PCL | kapsam dışı |
| `test_term_resize.py::TmuxArgvTests::test_bounds_are_enforced_before_any_subprocess` | `argv::disallowed_key_and_bad_size_spawn_nothing`, `real_tmux::resize_applies_and_release_restores_auto_size`; PW, PF | karşılandı (parite) |
| `test_term_resize.py::TmuxArgvTests::test_argv_uses_the_exact_target` | `argv::resize_release_and_kill_use_the_exact_target`; PF | karşılandı (parite) |
| `test_term_resolve_cache.py::CaptureFailureTests::test_gone_tmux_session_drops_the_entry_so_a_respawn_is_found_next_tick` | yok: `web._term_resolve_for_output` önbelleği; tmux_backend adları (`tmux_capture`) sahte ya da dolaylı (T2) | kapsam dışı |
| `test_term_viewport.py::SnapshotTests::test_returns_the_geometry_and_the_visible_screen` | PR (snapshot), PF | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_agrees_with_the_separate_calls_it_replaces` | PR (aynı ekranda snapshot, pane_size, capture, maske) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_it_is_one_tmux_process_running_two_commands` | `argv::snapshot_is_one_process_running_two_commands_without_utf8_flag`; PF (argv eşit) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_a_missing_session_is_none` | `real_tmux::no_server_is_an_error_not_a_panic`; PR (`yok`), PF (rc 1) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_the_alternate_screen_is_reported` | PR (`alt` pane) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_a_gone_session_never_falls_back_to_a_longer_sibling_name` | `real_tmux::prefix_name_never_matches_another_session`; PR (`pre`/`pre_1`) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_a_hostile_name_cannot_smuggle_a_tmux_command` | PB (`x; kill-server`, `x;`, `x;kill-session ...`: sonuç eşit, oturumlar yerinde) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_a_masked_prompt_is_visible_through_the_snapshot_pty` | `real_tmux::masked_pane_refuses_injection_but_accepts_user_typing`; PR (`pw` pane) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotTests::test_tty_is_masked_is_none_without_a_usable_path` | `mask::tests::unknown_for_empty_missing_and_non_tty`; PL (`""`, `/dev/null`, olmayan yol, dizin) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotParsingTests::test_an_empty_pty_field_is_kept_as_an_empty_string` | `query::tests::snapshot_with_empty_tty_keeps_empty_string`; PF | karşılandı (parite) |
| `test_term_viewport.py::SnapshotParsingTests::test_malformed_output_is_none` | `query::tests::malformed_snapshot_is_an_error`; PF (bozuk çıktılar) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotParsingTests::test_a_failing_tmux_is_none` | PF (rc 1) | karşılandı (parite) |
| `test_term_viewport.py::SnapshotParsingTests::test_a_missing_tmux_binary_is_none` | `runner::tests::missing_program_is_io_error`; PF (tmux yok bloğu) | karşılandı (parite) |
| `test_term_viewport.py::ViewportFrameTests::test_it_equals_the_classic_lite_frame_except_for_the_scrollback_derived_fields` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_the_first_line_is_self_contained_when_a_wrapped_colored_line_is_cut_at_the_top` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_the_frame_is_much_smaller_than_the_full_capture` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_a_masked_prompt_is_reported` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_the_classic_path_spawns_three_tmux_processes_and_the_viewport_path_one` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_it_falls_back_to_the_classic_frame_when_the_single_call_fails` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_a_gone_session_is_the_same_error_as_before_and_drops_the_resolve_cache` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::ViewportFrameTests::test_the_mode_is_read_from_the_visible_screen` | yok: `web._term_output` görünür ekran karesi (T2); alttaki snapshot PR, PF | kapsam dışı |
| `test_term_viewport.py::PlumbingTests::test_remote_query_adds_viewport_only_when_requested` | yok: uzak/yerel kademe aktarımı `web`/`web_hosts` (T2 yerel, T5 uzak) | kapsam dışı |
| `test_term_viewport.py::PlumbingTests::test_local_viewport_asks_the_viewport_frame_and_the_lite_wrapper_leaves_it_alone` | yok: uzak/yerel kademe aktarımı `web`/`web_hosts` (T2 yerel, T5 uzak) | kapsam dışı |
| `test_term_viewport.py::PlumbingTests::test_local_without_viewport_keeps_the_old_call_shape` | yok: uzak/yerel kademe aktarımı `web`/`web_hosts` (T2 yerel, T5 uzak) | kapsam dışı |
| `test_term_viewport.py::PlumbingTests::test_rest_tier_forwards_viewport_to_the_remote_host` | yok: uzak/yerel kademe aktarımı `web`/`web_hosts` (T2 yerel, T5 uzak) | kapsam dışı |
| `test_term_viewport.py::PlumbingTests::test_ws_tier_forwards_viewport_and_interval_to_the_relay` | yok: uzak/yerel kademe aktarımı `web`/`web_hosts` (T2 yerel, T5 uzak) | kapsam dışı |
| `test_term_viewport.py::PlumbingTests::test_ws_tier_without_viewport_keeps_the_old_call_shape` | yok: uzak/yerel kademe aktarımı `web`/`web_hosts` (T2 yerel, T5 uzak) | kapsam dışı |
| `test_term_viewport.py::RelayKeyTests::test_viewport_adds_the_query_parameter_the_label_and_the_key` | yok: WS aktarıcı anahtarı `web_hosts` (T5) | kapsam dışı |
| `test_term_viewport.py::RelayKeyTests::test_without_viewport_url_label_and_key_are_exactly_as_before` | yok: WS aktarıcı anahtarı `web_hosts` (T5) | kapsam dışı |
| `test_term_viewport.py::RelayKeyTests::test_viewer_with_and_without_viewport_never_share_a_relay` | yok: WS aktarıcı anahtarı `web_hosts` (T5) | kapsam dışı |
| `test_term_viewport.py::RouteTests::test_rest_viewport_returns_the_screen_only_frame` | yok: `/api/term/output`, `/ws/term` rotaları (T2) | kapsam dışı |
| `test_term_viewport.py::RouteTests::test_rest_without_viewport_is_untouched` | yok: `/api/term/output`, `/ws/term` rotaları (T2) | kapsam dışı |
| `test_term_viewport.py::RouteTests::test_ws_term_route_parses_viewport_and_passes_it_on` | yok: `/api/term/output`, `/ws/term` rotaları (T2) | kapsam dışı |
| `test_tmux_arg_semicolon.py::EscapeTests::test_only_a_trailing_semicolon_is_escaped` | `argv::raw_escapes_only_a_trailing_semicolon`; PC (`_tmux_arg` = `escape_arg`) | karşılandı (parite) |
| `test_tmux_arg_semicolon.py::EscapeTests::test_spawn_direct_argv_escapes_name_and_cwd` | PB (P4: `semi;` adı ve `w;` dizini iki tarafta da açılır) | karşılandı (parite) |
| `test_tmux_arg_semicolon.py::EscapeTests::test_shell_fragment_escapes_name_cwd_and_inner` | PC (ad `semi;`, cwd `/t;`, iç komut `x;`) | karşılandı (parite) |
| `test_tmux_arg_semicolon.py::EscapeTests::test_set_ctx_argv_escapes_the_label` | PCL (`a;` etiketi: yazılan değer eşit ve `a;`) | karşılandı (parite) |
| `test_tmux_arg_semicolon.py::RealTmuxSemicolonTests::test_spawn_with_semicolon_name_and_cwd_opens_that_session` | PB (P4: oturum o ad ve dizinde) | karşılandı (parite) |
| `test_tmux_arg_semicolon.py::RealTmuxSemicolonTests::test_ctx_label_keeps_its_trailing_semicolon` | `real_tmux::attached_client_is_counted_and_receives_safe_message` (`ctx 1K;`); PCL | karşılandı (parite) |
| `test_tmux_ctx_strip.py::CtxLabelTests::test_with_and_without_threshold` | `text::tests::ctx_label_rounds_like_python`; PP (`ctx_label` 132 girdi) | karşılandı (parite) |
| `test_tmux_ctx_strip.py::CtxLabelTests::test_unknown_is_empty` | `text::tests::ctx_label_rounds_like_python`; PP (`ctx_label` 132 girdi) | karşılandı (parite) |
| `test_tmux_ctx_strip.py::CtxLabelTests::test_label_has_no_strftime_or_format_chars` | `text::tests::ctx_label_rounds_like_python`; PP (`ctx_label` 132 girdi) | karşılandı (parite) |
| `test_tmux_ctx_strip.py::SetCtxTests::test_set_and_unset_argv` | `argv::ctx_set_and_unset_argv_and_failure`; PF, PCL | karşılandı (parite) |
| `test_tmux_ctx_strip.py::SetCtxTests::test_failure_and_oserror_are_quiet` | `argv::ctx_set_and_unset_argv_and_failure`, `runner::tests::missing_program_is_io_error`; PF (rc 1, tmux yok) | karşılandı (parite) |
| `test_tmux_ctx_strip.py::SetCtxTests::test_push_skips_unchanged_and_rewrites_on_new_pid_or_value` | `argv::ctx_push_skips_unchanged_and_rewrites_on_new_pid_or_value`; PF (dizi), PCL | karşılandı (parite) |
| `test_tmux_ctx_strip.py::SetCtxTests::test_failed_push_is_retried` | `argv::failed_ctx_push_is_retried`; PF (rc `1,0` ve `1,1,0`) | karşılandı (parite) |
| `test_tmux_ctx_strip.py::StripConfTests::test_strip_reads_cops_ctx_and_main_conf_stays_plain` | `conf::strip_reads_cops_ctx_and_main_conf_stays_plain` (veri dosyası, iki dilin ortak girdisi: parite anlamsız) | karşılandı (yalnız Rust testi) |
| `test_tmux_list_utf8.py::Utf8FlagArgvTests::test_tab_separated_queries_force_utf8` | PF (`client_session`, `ghost_session` argv `-u -L`) | karşılandı (parite) |
| `test_tmux_list_utf8.py::Utf8FlagArgvTests::test_other_queries_and_the_server_starting_spawn_do_not` | `argv::snapshot_is_one_process_running_two_commands_without_utf8_flag`; PF (argv eşit) | karşılandı (parite) |
| `test_tmux_list_utf8.py::CLocaleRealTmuxTests::test_client_session_and_ghost_are_found_in_the_c_locale` | PB (P5: C yerelinde gerçek istemci ve hayalet, iki taraf da bulur) | karşılandı (parite) |
| `test_tmux_send_keys_semicolon.py::SendKeysSemicolonArgv::test_trailing_semicolon_escaped` | `argv::single_line_is_literal_send_then_enter`; PF (`abc;`, `a\nb;`), PW | karşılandı (parite) |
| `test_tmux_send_keys_semicolon.py::RealTmux::test_literal_roundtrip` | `real_tmux::literal_text_raw_and_special_keys_arrive_unchanged`; PW (pane'e ulaşan bayt eşit) | karşılandı (parite) |
| `test_tmux_send_multiline.py::MultilineSendTest::test_multiline_uses_bracketed_paste_then_single_enter` | `argv::multiline_uses_load_paste_then_single_enter`, `real_tmux::multiline_goes_as_one_bracketed_paste`; PW, PF | karşılandı (parite) |
| `test_tmux_send_multiline.py::MultilineSendTest::test_single_line_keeps_literal_path` | `argv::single_line_is_literal_send_then_enter`; PF | karşılandı (parite) |
| `test_tmux_send_multiline.py::MultilineSendTest::test_paste_failure_returns_false_and_cleans_buffer` | `argv::paste_failure_deletes_the_buffer_and_sends_no_enter`, `swallow::failed_buffer_cleanup_is_counted_logged_and_the_paste_error_returned`; PF (paste rc 1, delete rc 1) | karşılandı (parite) |
| `test_tmux_send_raw_semicolon.py::SemicolonArgv::test_trailing_semicolon_escaped` | `argv::raw_escapes_only_a_trailing_semicolon`; PF (`foo;`, `;`, `bar\;`), PW | karşılandı (parite) |
| `test_tmux_send_raw_semicolon.py::SemicolonArgv::test_whole_semicolon_chunk` | `argv::raw_escapes_only_a_trailing_semicolon`; PF (`foo;`, `;`, `bar\;`), PW | karşılandı (parite) |
| `test_tmux_send_raw_semicolon.py::RealTmux::test_literal_roundtrip` | `real_tmux::literal_text_raw_and_special_keys_arrive_unchanged`; PW | karşılandı (parite) |
| `test_tmux_send_raw_semicolon.py::JobAttemptsResetOnStateChange::test_state_change_resets_attempts` | yok: `steward_jobs` teslim sayacı (T10) | kapsam dışı |
| `test_tmux_send_timeout.py::SendTimeoutTest::test_short_text_keeps_base_timeout_long_text_gets_more` | `keys::tests::timeout_grows_with_text` (süre argv'de görünmez, parite ölçemez) | karşılandı (yalnız Rust testi) |
| `test_tmux_strip.py::ConfigLoadTests::test_base_options_still_apply_when_the_strip_file_is_missing` | yok: `data/tmux-strip.conf`un tmux'taki davranışı (veri dosyası Python paketinde kalır, Rust aynı dosyayı yükler); şerit eylemleri `winact` (T6) | kapsam dışı |
| `test_tmux_strip.py::ConfigLoadTests::test_strip_file_turns_the_status_line_on_and_locates_the_launcher` | yok: `data/tmux-strip.conf`un tmux'taki davranışı (veri dosyası Python paketinde kalır, Rust aynı dosyayı yükler); şerit eylemleri `winact` (T6) | kapsam dışı |
| `test_tmux_strip.py::ConfigLoadTests::test_bindings_exist` | yok: `data/tmux-strip.conf`un tmux'taki davranışı (veri dosyası Python paketinde kalır, Rust aynı dosyayı yükler); şerit eylemleri `winact` (T6) | kapsam dışı |
| `test_tmux_strip.py::ConfigLoadTests::test_status_right_shows_the_count_the_alt_screen_marker_and_the_amber_threshold` | yok: `data/tmux-strip.conf`un tmux'taki davranışı (veri dosyası Python paketinde kalır, Rust aynı dosyayı yükler); şerit eylemleri `winact` (T6) | kapsam dışı |
| `test_tmux_strip.py::ConfigLoadTests::test_window_list_is_hidden_for_a_single_window_but_shown_when_there_are_several` | yok: `data/tmux-strip.conf`un tmux'taki davranışı (veri dosyası Python paketinde kalır, Rust aynı dosyayı yükler); şerit eylemleri `winact` (T6) | kapsam dışı |
| `test_tmux_strip.py::ConfigLoadTests::test_main_conf_only_uses_commands_every_supported_tmux_understands` | `conf::main_conf_is_only_plain_global_options_and_version_gated_includes` (aynı kural, statik) | karşılandı (yalnız Rust testi) |
| `test_tmux_strip.py::MenuTests::test_every_menu_item_calls_winact_with_only_the_client_name` | `conf::menu_commands_take_the_client_name_never_the_session_name` (statik) | karşılandı (yalnız Rust testi) |
| `test_tmux_strip.py::MenuTests::test_destructive_items_ask_first_and_only_y_runs_them` | yok: şerit menüsü uçtan uca (`winact`, T6) | kapsam dışı |
| `test_tmux_strip.py::MenuTests::test_a_hostile_session_name_neither_breaks_the_menu_nor_reaches_the_command` | yok: şerit menüsü uçtan uca (`winact`, T6) | kapsam dışı |
| `test_tmux_strip.py::MenuTests::test_clicking_the_right_status_block_opens_the_menu_but_the_left_block_does_not` | yok: şerit menüsü uçtan uca (`winact`, T6) | kapsam dışı |
| `test_tmux_strip.py::MenuTests::test_the_session_name_is_in_the_strip_and_the_window_list_is_hidden` | yok: şerit menüsü uçtan uca (`winact`, T6) | kapsam dışı |
| `test_tmux_strip.py::ClientHelpersTests::test_each_client_resolves_to_ITS_OWN_session` | `real_tmux::attached_client_is_counted_and_receives_safe_message`; PF (çok istemcili liste), PCL | karşılandı (parite) |
| `test_tmux_strip.py::ClientHelpersTests::test_a_message_really_appears_on_the_clients_status_line_and_cannot_run_commands` | `real_tmux::attached_client_is_counted_and_receives_safe_message`; PCL (durum satırındaki metin eşit, `#(...)` çalışmaz) | karşılandı (parite) |
| `test_tmux_strip.py::ClientHelpersTests::test_client_session_is_none_for_unknown_or_hostile_client_names` | `real_tmux::attached_client_is_counted_and_receives_safe_message`; PF, PCL | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_hash_is_doubled_so_a_shell_substitution_in_an_error_text_cannot_run` | `keys::tests::message_is_neutralised`, `argv::message_is_neutralised_in_argv`; PF, PCL | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_trailing_semicolons_are_dropped_because_they_are_tmux_command_separators` | `keys::tests::message_is_neutralised`, `argv::message_is_neutralised_in_argv`; PF, PCL | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_a_leading_dash_cannot_become_a_flag_and_newlines_collapse` | `keys::tests::message_is_neutralised`, `argv::message_is_neutralised_in_argv`; PF, PCL | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_the_target_is_the_clients_session_never_the_broken_dash_c_flag` | `keys::tests::message_is_neutralised`, `argv::message_is_neutralised_in_argv`; PF, PCL | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_a_vanished_client_is_false_and_sends_nothing` | `argv::message_to_a_vanished_or_flag_like_client_sends_nothing`; PF | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_a_client_that_looks_like_a_flag_is_rejected_without_calling_tmux` | `argv::message_to_a_vanished_or_flag_like_client_sends_nothing`; PF | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_falls_back_to_no_duration_on_a_tmux_without_display_message_d` | `argv::message_falls_back_to_no_duration_and_reports_total_failure`; PF (rc `1,0`, `1`) | karşılandı (parite) |
| `test_tmux_strip.py::TmuxMessageTests::test_failure_everywhere_is_false_not_an_exception` | `argv::message_falls_back_to_no_duration_and_reports_total_failure`; PF (rc `1,0`, `1`) | karşılandı (parite) |
| `test_tmux_target_names.py::AddressableTests::test_only_names_tmux_can_target_exactly_are_addressable` | `runner::tests::exact_target_refuses_names_tmux_resolves_to_another_session`, `runner::tests::exact_target_wraps_any_name_like_python`; PC (`_addressable`, `_exact`) | karşılandı (parite) |
| `test_tmux_target_names.py::AddressableTests::test_unaddressable_name_never_reaches_tmux` | PF (`""`, `$0`, `zeta:0`: iki tarafta da argv yok), PB (her çağrı `BadArgument`/`None`) | karşılandı (parite) |
| `test_tmux_target_names.py::AddressableTests::test_shell_fragments_refuse_an_unaddressable_name` | PC (kabuk parçaları: `ValueError` = `BadArgument`) | karşılandı (parite) |
| `test_tmux_target_names.py::RealTmuxTargetTests::test_unaddressable_names_touch_no_other_session` | PB (ikiz sunucularda okuma + kapatma; oturumlar yerinde) | karşılandı (parite) |
| `test_tmux_target_names.py::RealTmuxTargetTests::test_names_tmux_keeps_verbatim_are_still_targeted_exactly` | PB (`=eq`, `@1`, `%1` oturumları: okuma + kapatma eşit) | karşılandı (parite) |
| `test_tty_masked_input.py::TtyMaskedTest::test_icanon_without_echo_is_masked` | `real_tmux::masked_pane_refuses_injection_but_accepts_user_typing`, `mask_noctty::probing_a_pty_never_makes_it_the_controlling_terminal`; PCL (`pw`, `raw`, `norm` pane'leri), PR | karşılandı (parite) |
| `test_tty_masked_input.py::TtyMaskedTest::test_raw_no_echo_shell_is_not_masked` | `real_tmux::masked_pane_refuses_injection_but_accepts_user_typing`, `mask_noctty::probing_a_pty_never_makes_it_the_controlling_terminal`; PCL (`pw`, `raw`, `norm` pane'leri), PR | karşılandı (parite) |
| `test_tty_masked_input.py::TtyMaskedTest::test_normal_echo_is_not_masked` | `real_tmux::masked_pane_refuses_injection_but_accepts_user_typing`, `mask_noctty::probing_a_pty_never_makes_it_the_controlling_terminal`; PCL (`pw`, `raw`, `norm` pane'leri), PR | karşılandı (parite) |
| `test_tty_masked_input.py::TtyMaskedTest::test_empty_or_bad_path_is_none` | `mask::tests::unknown_for_empty_missing_and_non_tty`; PL | karşılandı (parite) |
| `test_tty_masked_input.py::TtyMaskedTest::test_pane_is_masked_input_uses_pane_tty` | `argv::masked_guard_asks_for_the_tty_before_sending`; PF (display-message argv), PR | karşılandı (parite) |
| `test_tty_masked_input.py::TtyMaskedTest::test_pane_is_masked_input_tmux_failure_is_none` | `real_tmux::no_server_is_an_error_not_a_panic`; PF (rc 1) | karşılandı (parite) |
| `test_ucli_fresh_handover.py::HandoverGateTest::test_ucli_handover_sends_message` | yok: ucli devri (`web`, `ucli_client`); tmux_backend adları (`is_tmux_backed`, `tmux_send_keys`) sahte ya da dolaylı (T4) | kapsam dışı |
| `test_ucli_phase.py::StatusPayloadPhaseTests::test_a_registered_running_ucli_row_carries_its_phase` | yok: `/api/status` `phase` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_ucli_phase.py::StatusPayloadPhaseTests::test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait` | yok: `/api/status` `phase` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_ucli_phase.py::StatusPayloadPhaseTests::test_a_frozen_stream_row_goes_amber_from_the_file_write_time` | yok: `/api/status` `phase` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_ucli_phase.py::StatusPayloadPhaseTests::test_a_stopped_row_and_a_phaseless_provider_have_no_phase` | yok: `/api/status` `phase` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_ucli_usage.py::StatusPayloadUsageTests::test_a_registered_running_ucli_row_carries_its_counters` | yok: `/api/status` `usage` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_ucli_usage.py::StatusPayloadUsageTests::test_an_unregistered_running_ucli_row_carries_its_counters` | yok: `/api/status` `usage` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_ucli_usage.py::StatusPayloadUsageTests::test_a_stopped_row_and_a_counterless_provider_have_no_usage` | yok: `/api/status` `usage` alanı; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T1) | kapsam dışı |
| `test_usage_cli.py::StatusUsageTotalTests::test_status_rows_carry_usage_total_without_blocking` | yok: `cops usage` + `usage_total`; tmux_backend adları (`is_tmux_backed`) sahte ya da dolaylı (T7) | kapsam dışı |
| `test_usage_fresh.py::FreshRun::test_usage_never_injects_into_live_sessions` | yok: oturumsuz kullanım okuması (`web`); tmux_backend adları (`tmux_send_keys`, `tmux_send_special_key`) sahte ya da dolaylı (T7) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_plain_characters` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_turkish_characters_are_single_tokens` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_arrow_and_function_sequences_are_one_token_each` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_a_lone_escape_is_the_escape_key` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_escape_followed_by_a_character_is_an_alt_combination` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_bracketed_paste_becomes_one_paste_token` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_paste_can_span_several_reads` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_an_unterminated_paste_expires_instead_of_swallowing_every_later_key` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_an_oversized_paste_is_dropped_whole_not_truncated` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_an_empty_paste_is_an_empty_token` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeyParserTests::test_an_end_marker_without_a_start_is_just_an_ignored_sequence` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_one_line_turns_line_breaks_and_tabs_into_spaces` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_one_line_drops_other_control_characters` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_drop_last_char` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_drop_last_char_takes_the_combining_mark_with_its_base` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_drop_last_word` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_tail_fit_keeps_a_short_text_whole` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_tail_fit_keeps_the_end_and_marks_the_cut` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_tail_fit_counts_wide_characters_as_two_columns` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TextHelperTests::test_tail_fit_zero_width` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_each_kind_goes_to_its_endpoint_with_its_field` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_request_carries_the_bearer_token_and_json_content_type` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_results_pair_the_sequence_number_with_the_outcome` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_non_ascii_text_survives` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_ok_false_body_is_an_error_with_the_panels_message` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_ok_false_without_a_message_still_says_something` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_wrong_token_is_reported_as_a_token_mismatch` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_other_http_errors` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_non_json_reply` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_panel_down_is_an_error_not_a_crash` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_an_unreadable_token_is_an_error_and_the_thread_survives` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_an_unexpected_exception_does_not_kill_the_sender` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_requests_arrive_in_submission_order` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_the_token_is_re_read_for_every_request` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_unknown_kind_is_a_programming_error` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_submit_returns_immediately_and_inflight_drains` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_close_lets_the_pending_message_go_out` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::InputSenderTests::test_close_without_any_submit_is_a_no_op` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_cbreak_state_and_exact_restore` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_poll_decodes_utf8` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_a_multibyte_character_split_across_reads_is_not_lost` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_enter_arrives_as_newline_in_cbreak` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_passthrough_turns_off_signals_and_carriage_return_translation` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_exit_after_passthrough_restores_the_original_state` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::KeysPtyTests::test_a_non_tty_stream_is_inert` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_i_opens_the_line_and_echoes_locally_without_sending` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_enter_sends_one_message_and_closes_the_line` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_enter_as_a_newline_character_also_sends` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_the_message_is_stripped` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_an_empty_or_blank_line_sends_nothing_and_stays_open` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_escape_cancels_without_sending_and_forgets_the_text` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_q_x_and_the_other_command_keys_are_text_while_composing` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_backspace_ctrl_u_and_ctrl_w` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_turkish_characters` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_arrow_function_and_alt_keys_are_ignored` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_other_control_characters_are_ignored` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_pasted_text_is_one_line` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_pasted_text_never_submits_early` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_the_line_is_capped` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_a_long_line_shows_its_tail_within_the_bar_width` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_the_hint_sits_at_the_right_edge_when_there_is_room` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_a_narrow_bar_drops_the_hint_before_the_text` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_the_hint_warns_when_the_connection_is_down` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ComposeTests::test_wide_characters_fit_the_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_not_live_blocks_the_message_and_keeps_the_line` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_the_kept_line_goes_out_once_the_connection_is_back` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_the_error_clears_at_the_next_key_and_the_line_comes_back` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_waiting_state_blocks_too` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_no_frame_yet_blocks` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_masked_input_blocks_the_message` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_masked_input_blocks_short_keys` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_masked_input_blocks_raw_keys` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::SendGateTests::test_the_error_flash_expires` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::FlashTests::test_sending_is_shown_until_the_result_arrives` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::FlashTests::test_success_flashes_green_then_disappears` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::FlashTests::test_failure_flashes_red_with_the_reason_for_longer` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::FlashTests::test_control_characters_in_an_error_never_reach_the_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::FlashTests::test_the_status_bar_is_back_after_the_flash` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_k_then_one_key_sends_it_and_closes_the_mode` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_every_key_of_the_medium_set_maps_to_the_panels_name` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_the_short_keys_are_all_names_the_panel_accepts_and_never_ctrl_c_or_ctrl_d` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI); kullandığı `ALLOWED_SPECIAL_KEYS` sabiti PC | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_every_name_has_a_label_for_the_status_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_an_unmapped_key_cancels_without_sending` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_ctrl_c_and_ctrl_d_characters_are_not_short_keys` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_q_in_the_mode_cancels_and_does_not_quit` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_k_again_cancels` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_only_one_key_per_k` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_a_pasted_block_cancels` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_a_pasted_line_break_or_tab_is_not_a_short_key` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_the_mode_times_out_without_sending` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_a_key_just_before_the_timeout_still_goes` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_not_live_blocks_and_says_so` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ShortKeyTests::test_the_result_is_named_after_the_key` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_capital_r_asks_for_confirmation_and_does_not_open_yet` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_lowercase_r_does_nothing` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_anything_but_enter_declines` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_a_pasted_line_break_does_not_confirm` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_a_pasted_exit_key_is_data_not_a_command` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_the_confirmation_times_out` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_confirming_opens_the_mode_and_switches_the_terminal_to_passthrough` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_every_key_goes_through_in_one_batch_per_poll` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_each_poll_is_its_own_request_in_order` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_the_command_keys_are_plain_input_in_raw_mode` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_ctrl_right_bracket_leaves_and_restores_the_terminal` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_keys_after_the_exit_key_in_the_same_read_are_normal_mode_keys` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_idle_lock_closes_the_mode` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_typing_keeps_the_lock_away` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_countdown_appears_only_near_the_lock` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_a_single_line_paste_is_forwarded_as_typed` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_a_multi_line_paste_is_refused_not_split_into_enters` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_not_live_drops_the_keys_and_shows_why_in_the_red_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_large_data_is_split_to_the_panels_per_request_limit` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_the_chunk_size_is_within_what_the_panel_accepts` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_raw_successes_are_silent_but_failures_show` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_shutdown_while_raw_restores_the_terminal_and_closes_the_sender` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_shutdown_outside_raw_leaves_the_terminal_alone` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_a_pending_batch_is_flushed_on_shutdown` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RawModeTests::test_without_a_keys_object_nothing_crashes` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_q_and_capital_q_quit` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_x_hides_the_popup_without_quitting` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_x_while_everything_is_fine_does_not_suppress_the_next_outage` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_other_keys_do_nothing` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_a_q_inside_an_escape_sequence_or_alt_combination_does_not_quit` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_pasted_text_never_acts_as_commands` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_a_single_character_paste_is_not_a_command_either` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_commands_work_when_they_arrive_together` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_quit_ignores_whatever_follows_it_in_the_same_read` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_uppercase_i_and_k_work_too` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::NormalModeTests::test_normal_bar_is_the_status_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TickTests::test_slow_when_idle_fast_in_every_input_mode` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TickTests::test_input_tick_is_much_faster_than_the_idle_tick` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TickTests::test_transports_follow_a_callable_tick` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TickTests::test_ws_transport_reads_the_tick_on_every_wait` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::TickTests::test_rest_transport_reads_the_tick_between_polls` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerIntegrationTests::test_the_overlay_replaces_the_status_bar_and_gives_it_back` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerIntegrationTests::test_typing_redraws_only_the_bar_not_the_body` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerIntegrationTests::test_the_key_hint_is_appended_to_the_normal_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerIntegrationTests::test_no_hint_by_default` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerIntegrationTests::test_an_overlay_returning_none_keeps_the_status_bar` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ScreenPasteTests::test_bracketed_paste_is_requested_and_released_only_when_asked` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ScreenPasteTests::test_read_only_viewers_do_not_touch_the_mode` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::WatchLoopInputTests::test_a_typed_message_goes_out_through_the_loop_and_q_ends_it` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::WatchLoopInputTests::test_the_transport_gets_a_tick_that_follows_the_mode` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::WatchLoopInputTests::test_keys_are_served_while_the_connection_is_down_but_nothing_is_sent` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::WatchLoopInputTests::test_the_reconnect_wait_wakes_at_the_input_tick_while_a_mode_is_open` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::WatchLoopInputTests::test_without_a_controller_the_old_behaviour_is_unchanged` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::RegisterTests::test_read_only_flag` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerProcessTests::test_full_session_compose_short_key_raw_and_exit` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerProcessTests::test_q_quits_and_a_pasted_q_does_not` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ViewerProcessTests::test_the_terminal_is_given_back_clean` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_watch_input.py::ReadOnlyProcessTests::test_read_only_sends_nothing` | yok: `watch.py` (`cops watch` aynası) girdi/klavye katmanı (T6 CLI) | kapsam dışı |
| `test_web_term_lite.py::ExtractionTests::test_changed_text_scans_only_new_lines` | yok: `web_term_lite` ayıklama; tmux_backend adları (`strip_ansi`) sahte ya da dolaylı (T2) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_name_is_resolved_from_the_client_and_the_action_runs_against_the_local_host` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_nothing_is_ever_printed_when_a_client_is_given` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_a_start_notice_is_shown_first_then_a_failure_is_shown_for_longer` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_destructive_successes_stay_silent_because_the_window_goes_away` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_sessionless_successes_are_confirmed_on_the_client` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_an_unresolvable_client_is_reported_and_nothing_runs` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::FromTmuxTests::test_a_crash_inside_the_action_becomes_a_message_and_releases_the_lock` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::ManualTests::test_explicit_name_and_host_without_a_client_print_the_result` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::ManualTests::test_failure_goes_to_stderr_with_exit_one` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::ManualTests::test_neither_name_nor_client_is_a_usage_error` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::LockTests::test_a_second_action_on_the_same_session_is_refused_without_running` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |
| `test_winact.py::LockTests::test_begin_and_end_are_logged` | yok: `cops winact` (şerit menüsü komutu); tmux_backend adları (yardımcı üzerinden) sahte ya da dolaylı (T6) | kapsam dışı |

## Açık işler
1. (Yapıldı 26 Kas) Eşleme tablosu ve parite genişletmesi: "Eşleme tablosu" bölümü.
2. (Yapıldı 26 Kas) `tests/parity.py` + `parity.rs`: 9 parite testi (aşağıdaki gösterge).
3. (Yapıldı 26 Kas) P1-P7 (TBD 366) ve maske durumu bilinmiyorken gönderim (TBD 367) iki tarafta düzeltildi: commit'ler `b51c368`, `6536631`, `104cbcd`, `328c18b`, `073578a`. Ders listesi madde 1, 3, 10 kapandı; 8 yalnız T4 fixture'ları için kısmen.
4. P8 (argv'de metin/parola) ve P9 (zaman aşımında kalan tampon): sahibe soruldu (TBD 369). Ders listesi madde 13.
5. (Yapıldı 26 Kas) `KillChild`/`ReapChild` ve `REAP_GRACE` yolları: `Reapable` arayüzü + sahte süreçle birim testi.
6. Birleştirme SONRASI (copsd bu crate'i kullanınca, bu dalda yapılamaz): `set_swallow_hook` copsd günlüğüne bağlanmalı (yoksa yutulan hatalar stderr'e, yani servis günlüğüne gider).
7. Panel (`webui`) `/api/context` `reason: mask_unknown`u tanımıyor (genel "yanıt okunamadı" gösterir): `TerminalView.tsx` + `strings.ts`e ayrı metin (bu dalın yazma kapsamı dışı).
8. Rust'a taşınan otomatik göndericiler (değnekçi `_send`, devir, compact, orkestrasyon) `RefuseMasked` seçince `MaskUnknown`u "send failed"ten ayrı göstermeli (T10/T4).
