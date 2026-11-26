# Taşıma kuralları (her grup için ZORUNLU)

Kaynak: `py/claudeops/steward.py` (yalnız OKU; `py/` altına yazma). Hedef: `src/<grup>.rs` + `tests/parity/<grup>.rs`.

1. Davranış BİREBİR. Python'da hatalı görünen davranışı düzeltme; aynen taşı, `docs/rs-stew.md` "Python hatası?" listesine yaz.
2. Her taşınan işlev/metot/sınıfın üstüne `/// py: <python_adı>` (metot: `Sınıf.metot`; birden çok ad virgülle). Bu satır
   `fn`/`struct`/`enum`/`const` bildiriminin doc bloğunun SON satırı olmalı, arada `#[...]` öznitelik OLMAMALI (`parity/map.py` böyle bulur).
   İç içe (closure) Python işlevleri ayrıca işaretlenmez.
3. Sabitler ve regex'ler `crate::consts_gen`'de HAZIR (ad: `MARK_ASK`; alt çizgiyle başlayan `_X` -> `P_X`). Yeniden yazma.
   İşlev gövdesi içindeki satır içi regex'ler `LazyLock` ile modülde; Python'daki bayraklar aynen (`re.I` -> `(?i)`), lookaround -> `fancy_regex`.
4. Veri tipleri `crate::types` (üretilmiş; alan ekleme/silme yok). Yöntemler `impl` ile kendi modülünde.
5. Python dizge davranışı `crate::pyc` ile: `strip/lstrip/rstrip`, `splitlines`, `split_ws`, `len/head/skip/tail` (kod noktası), `round`,
   `localtime`. `str::trim`, `str::lines`, bayt dilimi KULLANMA. Eksik yardımcı varsa `pyc`ye testle ekle.
6. `time.time()`/`_now()` -> `now: f64` parametresi. Python'da `now=None` alan işlevler de zorunlu `now` alır. Geri çağrılar `&dyn Fn`.
7. `state` sözlüğü `serde_json::Map<String, Value>` (preserve_order açık: ekleme sırası Python dict gibi). `Value` okurken Python'un
   truthiness'ini (`x or default`: None, 0, "", [], {} düşer) ve `float(...)`/`int(...)` dönüşümlerini koru. Bozuk tipte Python istisna
   fırlatıyorsa panik YOK: `Result` döndür ya da (yalnız Python da yutuyorsa) varsayılan; farkı `docs/rs-stew.md`'ye yaz.
8. Kütüphanede `unwrap/expect/panic` yasak (clippy deny); dilim indekslemede taşma olamayacağını koruma ile garanti et.
9. Parite testi: `tests/parity/<grup>.rs` içinde her taşınan ve vektörü olan işlev için
   `parity!("<python_adı>", <rust_test_adı>, |c| <ifade>);` (`c.arg::<T>("py_param_adı")`, `c.opt`, `c.or`, `c.str`, `c.callback`, `c.now`).
   Tuple dönen işlevde ifade de tuple. Yerinde değiştirme yapan işlevde `c.after` karşılaştır (ayrı assert, kapanış içinde).
   Vektörü OLMAYAN taşınan işlev için `/// py: <ad>` işaretli elle `#[test]` (beklenen değerler Python'u çalıştırıp alınır:
   `parity/env.py` `isolate()` ile geçici dizin; `python3 -I` ile `~/.claude/claudeops`'a ASLA dokunma).
   Kenar durumları (boş girdi, Unicode, eksik alan, None) vektörde yoksa elle ekle.
10. `parity!` test adı Rust tanımlayıcısı; Python adı alt çizgiyle başlıyorsa `p_` öneki.
11. Kapsam dışı (G/Ç) listesi `parity/out_of_scope.json`; oradakileri taşıma. Saf olup listede olan bir şey fark edersen bildir.
12. Bitince: `cargo test -p cops-steward-core` ve `cargo clippy -p cops-steward-core --all-targets -- -D warnings` temiz
    (`CARGO_TARGET_DIR=~/.cargo-target`), `python3 parity/map.py` çalıştır (kendi satırlarında EKSİK kalmasın), commit.
