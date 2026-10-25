# ucli vs rakip CLI'lar: küçük görev seti (2026-10-24)

Ham veri: `bench/results.jsonl`, koşu çıktıları scratchpad `bench_runs/`. Harness: `run.py`, `tasks.py`, `fixture/`. Sahibin kalıcı onayıyla commit'lendi.

## Kapsam ve sınırlar
- Koşan CLI'lar: ucli, codex, gemini, claude, agy (son ikisi sahibin açık onayıyla ikinci turda). Gemini t4 tekrarı günlük kota yüzünden ölçülemedi.
- Modeller FARKLI (karşılaştırma model + CLI birlikte): ucli = Evren deepseek-v4-flash; codex = gpt-5.6-luna low (PLAN'daki gpt-6-luna değil, repo yedek listesinden); gemini = gemini-2.5-flash; claude = claude-haiku-5-5 low; agy = gemini-3.8-flash-low. Doğruluk farkı CLI'dan çok modelden gelebilir.
- Makine yük altında: 49 oturum, loadavg koşular sırasında 0,8 ile 8,1 arası; süreler gürültülü, her koşu 2 tekrar. RSS/süreç sayısı ~50 ms örneklemeyle; `--version` koşularının RSS'i çoğu zaman ölçülemedi. Ayrılan (detach) alt süreçler sayılmadı.
- Görev 5 (testi çalıştır) ve 6 (hata düzelt) kabuk ister: ucli (kabuk aracı yok) ve gemini (`auto_edit`te kabuk onaysız; `yolo` otomatik mod sınıflandırıcısınca reddedilmişti) için "yetenek yok", başarısız sayılmadı.
- claude adaptörü `--strict-mcp-config --disable-slash-commands` kullanır (kullanıcı MCP/connector/skill bağlamı hariç); ilk smoke bunsuz 220k token tuttu.

## Sonuçlar (görev: 1 oku, 2 grep, 3 düzenle, 4 çok dosyalı yeniden adlandır, 5 test çalıştır, 6 hata düzelt; her biri 2 tekrar)
| CLI | geçti | tepe RSS | eşzamanlı / toplam süreç | süre (görev 1) | toplam token (13 koşu) |
|---|---|---|---|---|---|
| ucli | 9/9 (t5, t6 yetenek yok) | ~15-17 MiB | 1 / 1 | 2,3-4,8 s | ~122k |
| codex | 13/13 (t0 dahil) | ~310-460 MiB | 6-10 / 10-29 | 4,7-5,2 s | ~771k |
| gemini | 7/9 sayılan (t4 iki tekrar kaldı: ücretsiz katman kota hatası "429, 11 sa sonra", yetenek değil; t5, t6 yetenek yok) | ~410-425 MiB | 5-6 / 8-12 | 7,1-9,0 s | ~175k (t4 ölçülemedi) |

Görev süreleri: ucli en uzun t4'te (76-91 s, 23-46k token, çok dosyalı düzenleme); codex t4 10-15 s; gemini t3 14-84 s (yük). Başlangıç (`--version`): ucli 0,00 s, codex 0,01-0,02 s, gemini 2,1 s (RSS 351 MiB).

## Okuma
- ucli bellek ve süreç ayak izi rakiplerden ~20-25 kat küçük (tek süreç, ~16 MiB); ama bu model farkına değil CLI'a ait olan kısım. Çok dosyalı düzenlemede (t4) yavaş: 19-26 model isteği, 76-91 s.
- codex en doğru ve en hızlı, ama en çok token (özellikle t4/t6: 75-122k) ve en çok süreç.
- Token sayıları CLI'ların kendi raporu; önbellek payı farklı raporlanıyor (ucli 3.136 önbellekli dahil), doğrudan kıyaslanamaz.
- Harcama (ilk tur): ucli 122k (Evren günlük 10M sınırının ~%1,2'si), codex ~771k (ChatGPT girişi kotası), gemini ~175k (ücretsiz katman, kota doldu). Genel toplam aşağıdaki güncellemede.
- Anahtar hiçbir yerde yazdırılmadı.

## Açık
- gemini t4'ün kota sonrası tekrarı; codex modelini PLAN'daki gpt-6-luna ile yeniden koşmak; ucli için kabuk gerektiren görevlerin (t5, t6) ucli'ye bir kabuk aracı eklenince ölçülmesi.

## Ek (2026-10-24, sahip "yap" sonrası)
- gemini t4 yeniden koşusu: günlük kota tükendi ("exhausted your daily quota on this model"), sonuç alınamadı; bu kayıtlar `results.jsonl`de "fail" ama yetenek değil kota (t0 ve t4 son satırlar).
- claude ve agy bu ekten sonra sahibin açık onayıyla koşuldu (aşağıdaki güncelleme).

## Güncelleme: claude ve agy tam koşusu (sahip onayı sonrası)
Yük bu koşularda daha yüksekti (loadavg 1,1 ile 8,1). Modeller: claude = claude-haiku-5-5 low, agy = gemini-3.8-flash-low.

| CLI | geçti | tepe RSS | eşzamanlı / toplam süreç | süre (görev 1) | toplam token (13 koşu) |
|---|---|---|---|---|---|
| claude | 13/13 | ~245-330 MiB | 2-4 / 2-10 | 4,0 s | ~298k |
| agy | 13/13 | ~280-390 MiB | 1-3 / 1-9 | 7-9 s | ~707k |

- claude'un ilk smoke'u 220k token'dı; `--strict-mcp-config --disable-slash-commands` ile görev başı ~16k'ya indi (MCP/connector/skill bağlamı tahmini doğrulandı: kapatınca düştü). Böylece tam koşu ~2,6M yerine ~0,3M token tuttu.
- t4 (çok dosyalı yeniden adlandırma) herkesin en pahalı görevi (agy r1 104 s ve 141k token; ucli 76-91 s). Gemini t4 kota yüzünden ölçülemedi.
- agy ve claude kabuk görevlerini (t5, t6) geçti; ucli ve gemini bu iki görevde "yetenek yok".
- Genel toplam token (tüm koşular, ilk claude smoke dahil): ~2,3M (ucli ~122k, codex ~771k, gemini ~175k, claude ~298k + 221k smoke, agy ~707k). Anahtar yazdırılmadı.
- Süreç tek-süreç ayak izi hâlâ ucli'de en küçük (~16 MiB); agy ve claude 250-390 MiB, codex ve gemini 310-460 MiB.

## Düzeltme (2026-10-25): t4 doğrulayıcı hatası
t4 doğrulayıcısı `compute_total` alt dizgisini her yerde aradığı için `test_compute_total` test adını "kalan eski ad" sayıyordu; ucli r2 ve agy r2 bu yüzden "kaldı" görünüyordu, ama fonksiyon, içe aktarmalar ve çağrı yerleri doğru yeniden adlandırılmıştı. Doğrulayıcı kelime sınırına (`\bcompute_total\b`) çekildi ve eldeki çalışma dizinleri yeniden puanlandı: ucli 9/9, agy 13/13 (yukarıdaki tablo güncel). Gemini t4 hâlâ kota hatası. Böylece gerçek yanlış sayısı: tüm çalıştırılan koşularda 0 (gemini kota hariç).

## Güncelleme (2026-10-25): ucli `replace_in_files` (unified-cli 12d11a9) sonrası t4
- t4 (çok dosyalı yeniden adlandırma), ucli, 2 tekrar, ikisi geçti: **15,8 s / 26,5k token** ve **22,2 s / 22,7k token** (önce 76-91 s, 23-46k token). Süre ~4 kat düştü; token benzer ya da biraz az. Yük yüksekti (loadavg 8,5-10), codex t4 10-15 s'nin hâlâ biraz üstünde. Tepe RSS ~16 MiB, 1 süreç.
- Tek ölçüm kümesi (n=2); model ve istek sayısı ayrıca çözümlenmedi.
