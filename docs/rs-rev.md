# İz rs/rev: review çekirdeği (`py/claudeops/review.py` -> `rust/crates/cops-review-core`)

## Durum (26 Kas 2026 akşam): BİRLEŞTİRMEYE HAZIR DEĞİL

Yapılan:
- Crate yazıldı: `targets`, `planner`, `limits`, `prompts` (`LensRegistry` = `register_lens` karşılığı), `parse`, `redact`,
  `agy`, `paths`, `flow`, `store`, `report`, `export`, `py` (Python dil davranışları), `clock`, `error`.
- `cargo clippy -p cops-review-core --all-targets -- -D warnings` temiz.
- Parite düzeneği: `cargo test -p cops-review-core --test parity`. Python `review.py` işlevleri sarılır
  (`tests/py/parity_hook.py`); Python'un review testleri ve `tests/py/parity_edges.py` koşarken her çağrı Rust'a da sorulur
  (unix soket, `tests/support/mod.rs`); depo işlevlerinde dosyalar da karşılaştırılır. `HOME` ve `CLAUDEOPS_DIR` geçicidir.

Son ölçüm: 68.792 çağrı, 103 işlev (karşılaştırılmayan sarılı işlev yok), **81 fark**, test KIRMIZI.

## Açık işler (sırayla)

1. Parite farkları:
   - `finding_key` 74: kenar testinde Python 3.10'un Unicode 13'ünden yeni birleşik işaretler (ör. U+05C8, U+0897,
     U+08CA..U+08D0). `unicode-normalization` siliyor, Python boşluğa çeviriyor. Karar: sürüm eşitle ya da Unicode 13 üstü
     için ccc=0 say. Gerçek veride etkisi ölçülmedi.
   - `effort_for` 3: düzenek hatası. Sahte `cfg`de olmayan alanı kanca göndermiyor, dağıtıcı varsayılan `low` koyuyor;
     Python `getattr(..., "")`.
   - `export_root` 3: düzenek hatası. `resolved` haritası istek çağrıdan ÖNCE kodlandığı için boş gidiyor.
   - `counts_as_attempt` 1: gerçek Rust farkı. Nesne olmayan dolu kayıtta Python `AttributeError`, Rust `true`.
     İmza `Result<bool>` olmalı.
2. Python testleri parite koşusunda 16 hata veriyor. Görülen nedenler: `websockets` bulunamıyor (olası neden: geçici
   `HOME` kullanıcı site-packages'ını gizliyor, `PYTHONUSERBASE` verilmeli; doğrulanmadı) ve `test_planner_random`
   (yukarıdaki `AttributeError`, kenar testi yakalamalı). Düzenek `p.returncode`u da hata sayar. `run_parity.py` yalnız
   stderr'in son 1500 karakterini basıyor: tümünü rapora yazdır.
3. Gerçek veri paritesi HİÇ koşmadı: reviewer deposunun geçici KOPYASI (`findings.json`, `review_history.json`,
   `review_pool.json`, `reviews/`) ile `COPS_REV_PARITY_DATA=<kopya>`. Canlı dosyaya yazma. Canlı dosyalarda Python
   `json.dumps(indent=2)` gidiş-dönüşü bayt düzeyinde aynı ölçüldü (Rust tarafı henüz ölçülmedi).
4. **Eşleme tablosu (sahip EK 2, zorunlu):** `ast` ile `review.py`deki her işlev/sınıf/sabit/regex (modül düzeyi ~188 ad)
   ve ilgili `py/tests` dosyalarındaki her `test_*` (~495, 39 dosya) için satır: Python adı (dosya:satır) | Rust karşılığı |
   parite testi | durum. Kancanın raporundaki `by_test` test -> karşılaştırılan işlev eşlemesini veriyor; tablo ondan
   üretilebilir. Boş ya da "sonra" satırı kalmayacak.
5. **Python dersleri** (`docs/rust-lessons-from-python.md`, bölüm 2.7 ve bölüm 3'ün 20 maddesi): her madde burada test adı
   ya da gerekçeyle karşılanacak. Çoğu 2.7 maddesi koşucuya ait (T8); çekirdeğe düşenler: kota taramasında model metni,
   tekilleştirme anahtarı, durum zincirinde bilgi kaybı, redaksiyon corpus'u, `export_root`, `git` çağrısı, bozuk girdi.
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
