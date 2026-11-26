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
- Negatif `pid`li oturum dosyası Python'da `os.kill`den geçebilir; Rust atlar (bu madde Python gibi DEĞİL).

## Açık işler
- [ ] `docs/rust-lessons-from-python.md` (17:25 sonrası geldi): bölüm 1, 2.4 (cops-procscan) ve 3'ün her maddesi test adı ya da gerekçe. İlk bakış: `ProcId{pid,start_time}`, kill modülü, hayalet tmux, tarama maliyeti ölçümü henüz karşılanmadı.
- [ ] Eşleme tablosu (sahip EK 2): kapsam modüllerindeki her `ast` tanımı (dosya:satır | Rust | parite testi | durum). Tam: discovery, session, session_usage, mirrors, needs_ho, commands/ls; kısmi (kapsam dışı satırlarıyla): providers/* (kalan T4), commands/usage (T6), model_usage ve orphan_watch (T7), paths (W0-a), web.py durum işlevleri (T1).
- [ ] Test eşlemesi: test_discovery_sid, _bg_fold, _subshell, test_ls_json, test_mirror_marker, test_mirror_window (yalnız mirrors kısmı), test_orphan_cli, test_proc_stat_parse, test_rfh_marker, test_triage_fixes_20261107 (needs_ho), test_review_fixes_2026_11_04 (committed_since), test_session_usage, test_usage_cli, test_proc07, ucli `extract_info/matches_proc` testleri. Eksik görünen Rust testleri: `UsageCache` (ilk None, sonra değer), `fmt_tokens`, gerçek alt kabuk ve gerçek görüntüleyici süreci.
- [ ] Parite koşucusu (`parity/`, henüz yok): `scan`, usage, needs_ho; Python tarafında `_remember_agy_sid` etkisizleştirilmeli.
- [ ] `UsageReader::update` `BadRow`da Python gibi offset ilerlemiş kalıyor: testle sabitle.
