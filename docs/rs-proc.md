# rs/proc: cops-procscan (Rust sprinti W1-pre, süreç taraması)

Durum (26 Kas 2026): kod ve testler var, **BİRLEŞTİRMEYE HAZIR DEĞİL** (aşağıdaki açık işler).

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

İkili (salt okur): `cops-procscan list|ls [--json] [--no-cpu] [--base AD]`, `scan [--no-cpu]`, `usage DOSYA`.

## Ölçüm
- `cargo test -p cops-procscan`: 29 birim + 9 sahte `/proc` + 1 git testi yeşil; `clippy --all-targets -D warnings` ve `fmt --check` temiz (`rustfmt.toml` 130 sütun).
- Canlı parite (26 Kas, `list --json --no-cpu`, aynı anda): Python 32, Rust 32 satır, `cpu` dışında fark 0. `scan`/usage/needs_ho/CPU paritesi ÖLÇÜLMEDİ.

## Kararlar
- Başka kullanıcının sürecinden yalnız `status` okunur (tip kapısı `OwnProc`); FIFO testi içerik okunmadığını sınar.
- Crate durum dosyası yazmaz; tek yazım `NeedsHo::repo_baseline_set` (çağıranın verdiği dizin).
- Yeni bağımlılıklar: `libc`, `regex`, `sha1`, `serde` (`rust/Cargo.lock` da değişti).

## Python'dan bilinen sapmalar
1. `jsonl_path_for`: "cwd'deki en yeni dosya" düşüşü YOK (iz görevi böyle istedi). Python `_usage_total` sid dosyası yoksa başka oturumun sayacını gösterebilir.
2. Ata zinciri (tmux, shell alt kabuğu) başka kullanıcının sürecinde durur (Python geçer): gizlilik kuralı.
3. agy sid öğrenme yazılmaz; `Scan::agy_learned` döner. Yazım `cops-state` ile (T1) yapılmadan `/api/status` Rust'a alınmamalı. `agy_sids` DB yerine dosya aynasından okunur.
4. serde farkları: `NaN`/`Infinity` ve 128'den derin JSON reddedilir; yinelenen anahtarlı transkript satırı atlanır.
5. `procStart`/pid gibi alanlarda dizi/nesne değerlerinin `str()` yazımı birebir değil (yalnız eşitlik denetimi).

## "Python hatası?" (Rust şimdilik Python gibi davranır; sahibe sorulacak)
- Nesne olmayan ya da `name`i dizgi olmayan `sessions/*.json` tüm taramayı düşürür (`ScanError`).
- Transkriptte nesne olmayan satır / dizgi olmayan `text` `needs_ho`yu istisnayla bitirir (`BadTranscript`).
- Dizgi olmayan `message.model` o çağrıda kullanım toplamını `None` yapar.
- `needs_ho` baseline yazımı atomik değil; `sid` içinde `/`/`..` süzülmüyor.
- Negatif `pid`li oturum dosyası Python'da `os.kill`den geçebilir; Rust atlar (bu madde Python gibi DEĞİL).

## Açık işler
- [ ] Ders listesinin aşağıda "AÇIK" kalan maddeleri; bölüm 1 (H1..H21 genel "Rust'ta önleme" satırları) tek tek karşılanmadı.
- [ ] Eşleme tablosu (sahip EK 2): kapsam modüllerindeki her `ast` tanımı (dosya:satır | Rust | parite testi | durum). Tam: discovery, session, session_usage, mirrors, needs_ho, commands/ls; kısmi (kapsam dışı satırlarıyla): providers/* (kalan T4), commands/usage (T6), model_usage ve orphan_watch (T7), paths (W0-a), web.py durum işlevleri (T1).
- [ ] Test eşlemesi: test_discovery_sid, _bg_fold, _subshell, test_ls_json, test_mirror_marker, test_mirror_window (yalnız mirrors kısmı), test_orphan_cli, test_proc_stat_parse, test_rfh_marker, test_triage_fixes_20261107 (needs_ho), test_review_fixes_2026_11_04 (committed_since), test_session_usage, test_usage_cli, test_proc07, ucli `extract_info/matches_proc` testleri. Eksik görünen Rust testleri: `UsageCache` (ilk None, sonra değer), `fmt_tokens`, gerçek alt kabuk ve gerçek görüntüleyici süreci.
- [ ] Parite koşucusu (`parity/`, henüz yok): `scan`, usage, needs_ho; Python tarafında `_remember_agy_sid` etkisizleştirilmeli.
- [ ] `UsageReader::update` `BadRow`da Python gibi offset ilerlemiş kalıyor: testle sabitle.

## Ders listesi karşılığı (`docs/rust-lessons-from-python.md`, 26 Kas)
T = `tests/fake_proc.rs`, birim testleri `modül::tests::ad`.

### 2.4 cops-procscan
| Madde | Durum | Test / gerekçe |
|---|---|---|
| `ProcId{pid,start_time}`, sinyalden önce doğrulama | AÇIK | Crate sinyal göndermez; ama `Session` `start_time` taşımıyor. T4 kill için eklenmeli. CPU örneklemesi pid yeniden kullanımını `starttime` ile eler (testi yok). |
| EPERM/ESRCH, yalnız kendi UID | karşılandı | `kill(pid,0)` yok; `ProcFs::own`; T `other_users_processes_are_never_read` |
| Tüm taramalar UID süzgeçli | karşılandı | aynı test; `mirrors::running_mirrors` de `own_processes` kullanır |
| `kill` tek modül, lint ile yasak | AÇIK | Oturum süreci öldürülmüyor (tek `Child::kill`: kendi git/wmctrl alt süreci, `proc_cmd`). `disallowed-methods` lint kurulu değil (workspace işi, T4). |
| Alt süreç kill+wait, zombi testi | KISMİ | `proc_cmd::run` kill+wait; `proc_cmd::tests::output_status_and_timeout`. Zombi sayımı testi ve `Drop` sahipliği yok; torun boruyu tutarsa okuyucu iş parçacığı onunla yaşar. |
| app-server ve alt kabuk ikinci satır üretmez | KISMİ | `providers::tests::detect`, `session::tests::subshells_fold_only_for_shell`. app-server ÇOCUĞU Python keşfinde de elenmez (`orphan_watch`, T7); gerçek alt kabuk testi yok. |
| Hayalet tmux oturumu | kapsam dışı | spawn/tmux işi: W0-b + T4 (`tmux_backend` hayalet denetimi). |
| Tarama maliyeti ölçülür | KISMİ | 636 süreç, release `list --no-cpu` 0,06-0,11 sn (3 koşu). Python CLI 4-5,5 sn içe aktarma dahil, karşılaştırılamaz. Tick içi maliyet T1'de ölçülmeli; CPU kipi +0,3 sn bekler. |
| %50/10 dk yanlış pozitif | karşılandı | T `tmux_terminal_and_orphans` (599/600 sn, kesinti sıfırlar, tmux'lu ve terminalli süreç yetim değil) |

### 3. Birleştirme öncesi 20 madde
| # | Durum | Test / gerekçe |
|---|---|---|
| 1 | karşılandı | yıkıcı eylem yok; transkript yalnız tam sid: T `transcript_requires_exact_sid`; `find_by_name` tam ad |
| 2 | KISMİ | tek yazım `repo_baseline_set`, Python gibi atomik DEĞİL (parite). Python hatası? sorulacak |
| 3 | AÇIK | okunamayan `/proc` ya da dizin boş liste olur ("yok"tan ayrılmıyor); git hatası "temiz" sayılır (Python aynı) |
| 4 | uygulanmaz | crate eylem yapmaz (`focus_window` sonucu döner, negatif test var) |
| 5 | AÇIK | `.ok()`/`unwrap_or_default` Python'un yutmalarını yansıtıyor; sayaç/log yok |
| 6 | karşılandı | ayar/sır önbelleği yok; `UsageCache` hata eski değeri ezmez (testi AÇIK); `AgyState` her taramada okunur |
| 7 | karşılandı | ata yürüyüşü 64/6 adım, git 15 sn, wmctrl 3 sn |
| 8 | KISMİ | argv fixture'ları birim testte; sürüm etiketli fixture dizini yok; ekran okuma yok |
| 9 | KISMİ | 2.4 alt süreç satırı; fd sızıntı testi yok |
| 10 | KISMİ | `py::tests::*`, `needs_ho::tests::broken_input_like_python`, T json/usage bozuk girdi; bozuk agy dosyası ve bozuk `/proc` alanı testi yok |
| 11 | AÇIK | RFH tek modülde (`needs_ho::rfh_marker_in`), Python altın vektörü yok |
| 12 | KISMİ | `Config::from_env` `$HOME` kullanır (Python `expanduser` gibi; `cops-state` birleşince oradan alınmalı); diferansiyel test yalnız elle `list` |
| 13 | karşılandı | sır okunmaz/yazılmaz; `environ`den yalnız `COPS_NAME` alınır, loglanmaz |
| 14 | KISMİ | `sid` argv'den yol parçası olur, `..` süzülmez (Python aynı; Python hatası? sorulacak) |
| 15 | uygulanmaz | vekil/WS yok |
| 16 | uygulanmaz | uç/route yok |
| 17 | karşılandı | testler yalnız geçici dizin; `Config::from_env` yalnız ikilide; git testinde hook kapalı (kullanıcının global git ayarı okunur) |
| 18 | uygulanmaz | uzak host kodu yok |
| 19 | uygulanmaz | canlı ikili değil; T1 bağlayınca `copsd` sürümü |
| 20 | karşılandı | ölçümler yukarıda; `--dry-run` yok; Python'a dokunulmadı |
