# ucli koderine istek: `--metrics-file` (21 Kas 2026, copsdevderbent -> `cli` oturumu)

Bağlam: claudeops tarafı ucli kaynak metriklerini zaten dışarıdan örnekliyor (`py/claudeops/ucli_metrics.py`, main f634f4e+; /proc'tan RSS/CPU/G-Ç/süreç/çalışma dizini boyutu, SQLite). Panelde Araçlar > ucli > Metrikler görünüyor. Dışarıdan göremediğimiz, yalnız ucli'nin bildiği ölçümler için bayrak gerekiyor.

İstek (unified-cli, Rust): `--metrics-file <yol>` bayrağı.
- Çalışırken periyodik (varsayılan 15 sn, `--metrics-interval <sn>` ile ayarlı) ve her tur sonunda JSONL satırı EKLE (`O_APPEND`, 0600): `{"ts": <unix>, "rss_kib", "cpu_pct", "io_read_bytes", "io_write_bytes", "tool_calls_total", "tool_wait_ms_total", "model_wait_ms_total", "turn": <n>, "step": <n>}`. Sayaçlar kümülatif (oturum başından); `ts` saniye cinsinden gerçek sayı.
- Bayrak yoksa hiçbir şey yapma (mevcut davranış değişmez). Yazma hatası oturumu düşürmesin (bir kez stderr uyarısı).
- Dosya büyümesi: 16 MiB'ı aşınca `<yol>.1`e döndür (tek yedek).
- Kaynak okuma maliyeti ucli'nin kendi sürecinden `/proc/self` + sayaçlarla; ek alt süreç yok. Test: birim (biçim, ekleme, döndürme, bayraksız = sıfır yazım).
- Teslim: `bin/ucli` kopyasını cops yapar (kural: teslimde koder kopyalamaz).

Claudeops tarafı (cops yapar, ucli teslim edince): `ucli_provider` oturum başlatırken `--metrics-file ~/.claude/claudeops/ucli_metrics/<oturum>.jsonl` bayrağını `binary_supports_flag` kapısıyla otomatik verir (ayar `ucli_metrics.enabled`), `ucli_metrics.py` dosyadan ek alanları (araç/model bekleme) SQLite'a işler, panel grafiklerine ekler.
