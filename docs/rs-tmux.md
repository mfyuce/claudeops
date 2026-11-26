# İz W0-b: `cops-tmux` (dal `rs/tmux`)

Durum (26 Kas 2026): **birleştirmeye hazır DEĞİL.** Kod ve testler yeşil; eşleme tablosu, yeni işlevlerin Python paritesi ve ders listesinin açık maddeleri bekliyor ("Açık işler").

## Yapılan
`rust/crates/cops-tmux`, `py/claudeops/tmux_backend.py` karşılığı. `ast` listesindeki işlevlerin hepsinin Rust karşılığı yazıldı (satır satır tablo henüz yok).

| Rust dosyası | İçerik |
|---|---|
| `runner.rs` | `Tmux` (soket, zaman aşımlı alt süreç), `exact_target`, `escape_arg`, `base_argv` |
| `query.rs` | oturum/pane listesi (pid, cwd), capture, aralık, boyut, snapshot, maskeli giriş, istemciler, `set_ctx` |
| `keys.rs` | `send_text`, `send_raw`, özel tuş, boyut, `message`, `MaskGuard` |
| `mask.rs` | `tty_is_masked` (`O_NOCTTY`) |
| `text.rs` | `strip_ansi`, `typed_input_in_box`, `input_box`, `ctx_label` |
| `shell.rs` | `shlex.quote`, kabuk parçaları, `spawn_direct`, `kill_session`, `ghost_session` |
| `proc.rs` | `/proc` üstünden `is_tmux_backed`, `pid_childless`, `find_outer_bash_pids`, `CtxPusher` |

Testler: 24 birim, 19 argv (`tests/fake_tmux.sh`), 10 gerçek tmux, 6 yaşam döngüsü, 3 Python paritesi. `cargo test -p cops-tmux` ve `cargo clippy -p cops-tmux --all-targets -- -D warnings` temiz; 10 ardışık koşuda oynaklık görülmedi (son iki küçük test ekinden önce). Gerçek tmux testleri geçici `TMUX_TMPDIR` + rastgele soket + `-f /dev/null` (ya da paketli conf) kullanır; `-L cops` sunucusuna dokunmaz.

## Kararlar
- Çağrılar bloklayıcı (tokio yok); hata `TmuxError`, Python'daki `None`/`False` karşılığı.
- Her gönderim `MaskGuard` ister. `UserTyped` = Python'daki `tmux_send_*`; `RefuseMasked` = Python `_context`teki ön denetim (bilinmeyen durumda gönderir, bkz. TBD).
- `list_sessions` / `list_panes` / `session_panes` Python'da yok. Yalnız bunlar `tmux -u` kullanır (UTF-8 olmayan yerelde sekme `_` oluyor). `-u` sunucu başlatan komuta verilmez (`is_tmux_backed` sunucu argv'sine bakar).
- Pane kaydı `␞\n` ile biter (cwd satır sonu içerebilir).
- `kill_session` ilkel işlemdir; süreç/pencere temizliği ve devir kuralları kapatma modülünde (T4) kalır.
- `/proc` okuyucusu küçük ve özeldir; `cops-procscan` birleşince ortaklaştırılabilir.
- `rust/Cargo.lock` izin verilen yollar dışında olduğu için commit EDİLMEDİ; ilk `cargo` koşusu `libc`/`regex` girdileriyle günceller.

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

## Ders listesi (`docs/rust-lessons-from-python.md` 2.2)
| Madde | Durum |
|---|---|
| Hedef hep `=ad`, önek yok | `prefix_name_never_matches_another_session`; P1-P3 açık |
| `send-keys` tek kurucu, `-l --`, `;`, `-help`, `--- a/f` | `literal_text_raw_and_special_keys_arrive_unchanged`, `writes_match_python`, `raw_escapes_only_a_trailing_semicolon` |
| ANSI ayıklama + ayrı ANSI'li kopya, gri öneri | `capture`/`capture_plain`, `typed_vs_suggestion`, `pure_functions_match_python_on_random_screens` |
| Enjeksiyon öncesi maske; `Unknown` = gönderme | maske: `masked_pane_refuses_injection_but_accepts_user_typing`; `Unknown` kuralı Python ile çelişiyor (TBD); diyalog sınıflandırması bu modülde yok (`trust_dialog`/sağlayıcılar, T4) |
| Diyalog yalnız pane sonunda | kapsam dışı: `trust_dialog` (T4) |
| Teslim doğrulaması | kapsam dışı: `tmux_backend`de yok (T4/T10). `send_text` `Ok` = tmux kabul etti, teslim DEĞİL |
| Copy-mode yok, `O_NOCTTY` | `history_read_never_enters_copy_mode`; `O_NOCTTY` kodda (`mask.rs`), davranış testi AÇIK |
| `tmux.conf` sürüm sınırı | dosya değişmedi (Python `test_tmux_strip.py` korur); `spawn_direct_uses_conf_env_and_cwd_and_keeps_the_session_after_exit` yükler |
| Kill sırası, ölü ad sonrası kardeş yaşar | `prefix_name_never_matches_another_session` (`kill_session`); sıra kapatma modülünde (T4) |
| `display-menu`de oturum adı yok | dosya değişmedi (Python testi) |
| Gerçek tmux gidiş-dönüş | `tests/real_tmux.rs`, `tests/parity.rs` |

Genel liste (bölüm 3) **henüz madde madde karşılanmadı.** Bilinen açıklar: madde 5 (`let _ =` ile yutulan `delete-buffer`, istemci `kill`/`wait`, boru yazımı sayaçsız/logsuz), madde 9 (fd sızıntı testi yok; zaman aşımında boru okuyan iş parçacığı boru kapanana dek yaşar).

## Açık işler (birleştirmeden önce)
1. Eşleme tablosu (sahip EK 2): `tmux_backend.py`nin her `ast` tanımı (dosya:satır | Rust yol::ad | parite testi | durum) ve ilgili her `test_*` metodu. İlgili dosyalar: `test_tmux_*.py`, `test_tty_masked_input`, `test_input_box_typed`, `test_spawn_ghost_reclaim`, `test_outer_bash_list_clients`, `test_term_viewport`, `test_term_history`, `test_term_resize`, `test_kill_access_denied`, `test_proc08_model_switch_no_blind_enter`, `test_live_model_effort`, `test_watch_input` (çoğu başka ize ait: T2/T4/T10). Boş satır kalmayacak.
2. `tests/parity.py` + `parity.rs` genişlet: sabitler ve regex'ler (`patterns()`), `dim_fg`, `segment_typed`, kabuk parçaları, `tmux_conf_path`, `base_argv`, `spawn_direct`, `kill_session`, `ghost_session`, `pid_childless`, `is_tmux_backed`, `find_outer_bash_pids`, `set_ctx`/`push_ctx`, `message`, `client_session`, `release_size`; P1-P7 davranışlarının eşliği.
3. Ders listesi bölüm 3'ü (20 madde) karşıla; açık satırları test ya da gerekçe ile kapat.
4. TBD cevabına göre P1-P7 ve `Unknown` maske kuralı.
