# ucli vs rakip AI CLI'lar: küçük görev seti (plan, 2026-10-24)

Rakipler: claude (Claude Code), agy, codex (kota 2026-11-08'e kadar bitik olabilir: dene, olmazsa atla ve raporla), gemini-cli (kuruluysa ve girişliyse).
ucli: yerel build (`unified-cli/target/release/ucli`, sha256 014e2600110f; steward notundaki 7c1a570da2ab yerelde yok, rapora yazılır) + Evren modeli, anahtar yalnız ortam değişkeninde.

Görevler (deterministik, her koşuda taze kopyalanan küçük fixture repo; doğrulama betikle):
1. oku: bir sabitin değerini söyle (tam eşleşme)  2. grep: TODO içeren dosya sayısı (tam eşleşme)
3. düzenle: tek dosyada sabit değiştir  4. çok dosyalı yeniden adlandırma  5. testi çalıştır, kalan testin adını söyle (kabuk gerekir: ucli'de kabuk aracı yoksa "yetenek yok" diye raporlanır)
6. hatayı düzelt, pytest geçsin  7. (opsiyonel) loc/özet sorusu.

Ölçümler: başlangıç süresi (`--version` ve boş görev), tepe RSS (süreç ağacı, 50 ms örnekleme), alt süreç sayısı (ağaçtaki en çok eşzamanlı + toplam doğan), görev başına token (CLI'ın kendi JSON/usage çıktısı; yoksa "ölçülemedi") ve süre, doğruluk (geçti/kaldı). Her koşu 2 tekrar; yük altı makine notu (loadavg, 49 oturum) rapora girer.

Tahmini harcama (görev başına düşük effort, ucuz model): görev ~5-15k token; 6 görev x 2 tekrar x ~10k = ~120k token/CLI, 4-5 CLI = en çok ~0,6M token. Evren günlük 10M sınırının ~%2'si (ucli koşuları). Claude: haiku-5-5 low. agy: flash düşük. codex: gpt-6-luna low (kota yoksa atlanır). Anahtarlar ekrana/rapora yazılmaz. Commit/push YOK.

---
DURDURULDU (sahip, 2026-10-24): benchmark iptal; hiçbir API/agy/codex/claude/ucli çağrısı yapılmadı (harness yazımı sırasında en çok `--help`/`--version` düzeyi olabilir, smoke koşusu doğrulanmadı). Yarım dosyalar silinmedi; yeni görev gelene kadar bekleniyor.

DEVAM (sahip, 2026-10-24 22:2x): benchmark yeniden başlatıldı; plan ve harcama sınırı aynı.
