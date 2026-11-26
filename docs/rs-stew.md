# İz rs/stew: değnekçi saf çekirdeği (`rust/crates/cops-steward-core`)

## Kapsam ve ayrım

`py/claudeops/steward.py` (6.253 satır). Saf kararlar ve prompt üreticileri bu crate'e taşınır; dosya deposu, kilit,
olay günlüğü, alt süreç ve saat okuyan işlevler taşınmaz (gerekçe ve ait olduğu iz: `parity/out_of_scope.json`, aşağıdaki
tabloda satır satır). `web_steward.py` bu izde yok. İşlev haritası (saf / G/Ç) = alttaki eşleme tablosu.

## Parite düzeni

- `parity/gen.py`: tüm modül sabitleri/regex'leri ve veri sınıfları Python'dan ÜRETİLİR (`generated` testi bayatlığı yakalar).
- `parity/record.py`: Python steward testleri (2.531 test, yalıtılmış geçici dizin) koşarken saf işlevlerin girdi/çıktısı
  `fixtures/vectors/*.jsonl.gz`'ye kaydedilir; `tests/parity` Rust'ta tekrar oynatır. İşlev başına en çok 250
  (`plan_tick` 600, `scan_markers` 500) tekil çağrı, özet sırasıyla seçilir (her test çağrısı değil).
- `parity/map.py`: aşağıdaki tabloyu `ast` ile üretir; EKSİK satır varsa `--check` kırmızı.
- Altın tick: `py/tests/steward_golden_tick.json`.

## Eşleme tablosu

<!-- MAP:BEGIN (parity/map.py üretir) -->
<!-- MAP:END -->
