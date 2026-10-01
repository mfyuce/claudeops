# EVREN — Yapay Zeka Platformu (kullanıcı kılavuzu özeti)

`https://evren.ssyz.org.tr/` — "Savunma Sanayiinin Yapay Zeka EVREN'i". İki bağımsız hizmeti var,
karıştırılmamalı:

1. **LLM chat/inference API** (`evren-llmapi.ssyz.org.tr/v1`, OpenAI-uyumlu) — claudeops'un
   `ucli` provider'ı zaten bunu kullanıyor (bkz. `TOBEDECIDED.md` #46, `~/.claude/claudeops/
   settings.json`'daki `UCLI_API_KEY`). Bu dosyanın konusu DEĞİL.
2. **CV veri etiketleme + GPU eğitim platformu** (`evren.ssyz.org.tr`, bu dosyanın konusu) — e-Devlet
   girişli, kredi (CR) bazlı, web dashboard üzerinden.

Giriş, 2026-10-01'de `NN_lineart_cuneiform_vlm` paper session'ında, kullanıcının ekran görüntüleri +
kendi kullanım kılavuzundan yapıştırdığı 10 bölümün (15 bölümden) özetlenmesiyle derlendi. Kılavuzun
geri kalanı (Gösterge Paneli, Organizasyon, İletişim, Araçlar, Profil ve Ayarlar) henüz görülmedi.

## 🔴 Kritik sonuç: genel amaçlı LLM/VLM fine-tuning için KULLANILAMAZ

Platform **sabit mimari ailesiyle** çalışan bir CV (computer vision) etiketleme+eğitim SaaS'ı
(Roboflow benzeri), serbest bir "kendi modelini/script'ini getir" ortamı DEĞİL:

- **Desteklenen mimariler (Eğitim ekranında, tam liste):** YOLO26 (en yeni), YOLO11, YOLOv10,
  YOLOv9, YOLOv8, RT-DETR — her biri boyut varyantlarıyla (nano/small/medium/large/xlarge).
- **Desteklenen görev tipleri:** Detection (nesne tespiti), Segmentation, OBB (yönlendirilmiş
  kutu), Pose (poz tahmini), Classification.
- **"Modeller yalnızca eğitim sonucu otomatik oluşturulur... Manuel model oluşturma
  desteklenmez."** — kendi HuggingFace checkpoint'ini (ör. Qwen3.6-35B-A3B, Qwen3-VL) yükleyip
  kendi eval/training script'ini çalıştırmanın bir yolu yok.
- Hiper-parametreler (epochs, batch size, image size, lr0/lrf/momentum/weight_decay, augmentation
  presetleri) ve metrikler (mAP50, mAP50-95, precision/recall, confusion matrix) hepsi klasik
  nesne-tespiti/sınıflandırma sözlüğü — serbest-metin üretimi (text generation) kavramı yok.

**Pratik sonuç:** herhangi bir projede "image→free-text" (OCR/transliterasyon/captioning gibi
VLM fine-tuning) ihtiyacı doğarsa EVREN'in GPU eğitim tarafı **değerlendirmeye bile alınmamalı** —
GPU sayısı/fiyatı uygun olsa da iş tipi uyuşmuyor. Bu platformun gerçek kullanım alanı: standart
nesne tespiti/segmentasyon/sınıflandırma/poz/OBB gerektiren bir CV projesi varsa (ör. ekipman/
hasar/nesne tespiti).

GPU tier fiyatları (Eğitim ekranı, "Eğitim Başlat" sihirbazı, 2026-10-01 canlı ekran görüntüsü;
kılavuz metni de "14 tier: 1 GPU (15 CR/h) — 48 GPU (1680 CR/h)" diyor, ekrandaki Tek GPU
10 CR/h ile hafif tutarsız, muhtemelen kılavuz güncel değil):

| Tier | CR/saat |
|---|---|
| Tek GPU (1 GPU) | 10.00 |
| Çift GPU (2 GPU) | 22.00 |
| 4 GPU | 48.00 |
| 6 GPU | 78.00 |
| 2 Node (16 GPU) | 288.00 |
| 18 GPU (3N) | 342.00 |
| 20 GPU (3N) | 420.00 |
| Çoklu Node (24 GPU, 3N) | 576.00 |
| 28 GPU (4N) | 728.00 |
| 4 Node (32 GPU) | 928.00 |
| 36 GPU (5N) | 1116.00 |
| 40 GPU (5 nodes) | 1400.00 |
| 6 Node (48 GPU) | 1680.00 |

Öncelikli Eğitim (queue'da öne alır): 1.5× maliyet.

## MiMo-V2.6-Pro — LLM filosuna eklendi (duyuru, 2026-10-01 civarı görüldü)

Bu, yukarıdaki GPU-eğitim platformuyla DEĞİL, EVREN'in LLM chat API'siyle ilgili — Xiaomi'nin
1.02T parametreli (42B aktif, MoE) multimodal modeli, filonun en büyüğü. 8× H200 GPU'lu ayrı bir
sunucuda. Metin+görsel+video (64 kare)+ses girdisi, 1M token bağlam, tool-calling, structured
output (JSON schema), thinking mode (`"thinking": false` ile kapatılabilir), ~250 tok/s.
API model adı `mimo-v2.6-pro`, `/v1/chat/completions`+`/v1/responses`+`/v1/completions`.
**1 Kasım 2026'ya kadar ücretsiz** (tanıtım dönemi). İstek boyutu üst sınırı 20 MB.

## Temel kavramlar

- **3 bağımsız varlık:** Veri Seti, Model, Proje. Veri seti ve model projeye bağlanmadan da
  kullanılabilir.
- **Versiyon → Eğitim → Model akışı:** eğitim başlatmak için veri setinde **dondurulmuş bir
  versiyon** şart. Versiyon oluşturma = mevcut verinin anlık görüntüsü, otomatik donar.
  Eğitim bitince model/versiyon **otomatik** oluşur.
- **Slug:** her veri seti/model `kullanici-adi/ad` şeklinde benzersiz slug taşır; public/private
  görünürlük ayrı ayarlanır.
- İlk giriş: e-Devlet ile giriş (TCKN doğrulama, hesap otomatik "doğrulanmış"), KVKK+üyelik
  sözleşmesi onayı, **1000 CR hoş geldin bonusu**.
- Uçtan uca akış: Kayıt → Veri Seti oluştur → Görsel yükle → Sınıf etiketleri ekle → Etiketle →
  Versiyon oluştur → Proje aç + veri setini bağla → Eğitim başlat (mimari+tier) → Sonuçları
  izle → Model detayına bak → Çıkarım yap.

## Veri Setleri

- **Oluşturma (2 adım):** modalite seçimi (VISION/AUDIO/NLP/MULTIMODAL) → isim, açıklama,
  görünürlük, lisans (CC-BY-4.0/MIT/Apache-2.0 vb.), etiketler (max 10). Public paylaşım +5 CR.
- **Yükleme:** sürükle-bırak, presigned URL ile MinIO'ya direkt; format modaliteye göre
  (VISION: jpg/png/webp/bmp/tiff/gif/mp4/avi/mov/webm/mkv; AUDIO: wav/mp3/flac/ogg/aac; NLP:
  txt/json/csv/pdf; MULTIMODAL: hepsi). Dosya başı max 500 MB, eş zamanlı 4 paralel yükleme.
  Opsiyonel SHA-256 duplikat kontrolü.
- **İçe aktarım:** etiketli ZIP, 11 format (YOLO Detection/Segmentation/OBB, COCO JSON,
  Pascal VOC XML, CreateML JSON, Label Studio JSON, CSV BBox/Classification, Classification
  klasör yapısı, Flat). Max ZIP 30 GB.
- **Sınıflar:** isim+renk, sürükle-bırak sıralama (= YOLO export indeksi, dikkat: eğitimden
  önce sıralama sabitlenmeli).
- **Split yönetimi:** train/val/test, manuel veya "Otomatik Split" (varsayılan %70/20/10).
- **Sağlık skoru (A-F):** tamamlanma oranı (%40) + etiket dengesi (%30) + kalite/onay-ret oranı
  (%30).
- **Duplikat tespiti:** SHA-256 (birebir) + perceptual hash (benzer görüntü).
- **Versiyonlama:** dondurma, versiyon karşılaştırma, rollback (dikkat: mevcut etiketlemeleri
  geçersiz kılabilir).
- **Dışa aktarım:** 10 format (YOLO TXT/Segmentation/OBB/Pose/PyTorch, COCO JSON, Pascal VOC
  XML, Darknet TXT, CreateML JSON, CSV), versiyon bazlı, 0.50 CR/çağrı.
- **İşbirliği:** üye rolleri (Viewer/Labeler/Editor/Admin), fork (public veri setini kopyala),
  merge request (fork'tan orijinale katkı, onaylanırsa +2.00 CR).

## Etiketleme

Tam ekran çalışma alanı: sol panel (sınıf seçici + öğe listesi), orta tuval, sağ panel
(Outliner — etiket listesi, görünürlük/kilit). Araçlar: **B**box, **P**oligon (segmentasyon),
**R** OBB (döndürülmüş kutu, ilk 2 tık taban kenarı + 3. tık yükseklik), **K** keypoint/iskelet
(poz), **F** fırça (piksel-düzeyi, otomatik poligona çevrilir). Otomatik kayıt 30 sn'de bir,
Ctrl+S manuel. Undo sadece ekleme işlemlerini destekler (silme/düzenleme geri alınamaz).

- **Otomatik ön etiketleme:** YOLO veya SAM-2 ile toplu (Celery arka plan görevi), sonra elle
  inceleme/onay.
- **Negatif örnek:** nesne içermeyen görselleri bilinçli arka-plan örneği işaretleme
  (önerilen oran veri setinin %5-15'i).
- **Sınıflandırmada toplu atama:** galeri seçimi + "Sınıf Ata", ya da ZIP içinde klasör adı =
  sınıf adı ile etiketsiz yükleme.
- **İş akışı:** UNASSIGNED → LABELING → IN_REVIEW → APPROVED/REJECTED (red sebepli, LABELING'e
  geri döner). İncelemeci kendi etiketini onaylayamaz. Onay +0.10 CR.
- Kısayollar: ArrowLeft/Right (öğe geçişi), Ctrl+Enter (kaydet+sonraki), Ctrl+Space (atla),
  Delete, 1-9 (sınıf hızlı seçim), H (pan), Escape, Ctrl+K (komut paleti).

## Projeler

Proje = veri seti(ler)i + eğitim konfigürasyonlarını birleştiren çalışma alanı. Organizasyon
seçimi proje maliyetinin hangi kredi havuzundan düşüleceğini belirler (seçilmezse kişisel
bakiye). Bir projeye birden fazla veri seti bağlanabilir. Roller: Yönetici/Mühendis/Gözden
Geçiren/Etiketçi.

**Not:** "Eğitim Başlat" sihirbazının Proje dropdown'ında 2026-10-01'de zaten **"ASP"** adlı bir
proje görüldü — kime/neye ait olduğu doğrulanmadı, alakasız olabilir, ama kayda değer.

## Eğitim

- **Yeni eğitim:** proje + veri seti versiyonu (dondurulmuş olmalı) seç, opsiyonel deney bağla.
- **Mimari:** yukarıdaki "kritik sonuç" bölümüne bakın — YOLO26/11/v10/v9/v8 + RT-DETR, 5 boyut
  varyantı. Görev tipi etiket türüyle uyumlu olmalı.
- **GPU tier:** 14 kademe, yukarıdaki tablo. Yetersiz kredi ile başlatılamaz.
- **Hiper-parametreler:** epochs (varsayılan 100, max 1000), batch size (varsayılan 16, -1=
  otomatik), image size (varsayılan 640, 32'nin katı, max 2048), patience (varsayılan 50),
  lr0/lrf/momentum/weight_decay.
- **Augmentation:** 4 preset (Dengeli/Hızlı/Hassas/Özel) + tekil parametreler (HSV, translate,
  scale, fliplr/flipud, mosaic, mixup, erasing, degrees).
- **Durum akışı:** PENDING → EXPORTING → RUNNING → COMPLETED/FAILED/CANCELLED. Slurm üzerinde
  çalışıyor.
- **Canlı izleme:** WebSocket ile loss/mAP50/mAP50-95/precision/recall (epoch bazlı), GPU
  VRAM/sıcaklık/güç, Slurm log'u, eğitim sonrası confusion matrix + PR/ROC eğrisi + sınıf bazlı
  tablo.
- **İşlemler:** Durdur (kredi iade), FAILED → "Tekrar Dene" (son checkpoint'ten), Öncelikli
  kuyruk (%50 ek ücret).
- **Kredi akışı:** HOLD (tahmini maliyet bloke) → SETTLE (gerçek maliyet, tamamlanınca) /
  RELEASE (iptal/başarısızlıkta iade).

## Deneyler

Proje altında: deney adı/açıklama/hipotez(opsiyonel)/etiket. Eğitim başlatırken bir deneye
bağlanabilir, bir deneye birden fazla eğitim (run) bağlanabilir. **Karşılaştırma** (2-5 run):
hiper-parametre fark tablosu + epoch bazlı mAP50 grafik üst üste bindirme + final metrik
tablosu + radar grafiği. En yüksek mAP50'li run otomatik "En İyi" işaretlenir.

## Modeller

Sadece eğitim sonucu otomatik oluşur (manuel oluşturma yok). Her run → yeni versiyon. Stage
sistemi: EXPERIMENTAL (varsayılan) → STAGING → PRODUCTION → ARCHIVED. Versiyon karşılaştırma
(metrik+parametre+grafik yan yana). Ağırlık indirme (.pt) + format dışa aktarım (PyTorch/ONNX/
TensorRT/TFLite). API sekmesinde hazır Python/cURL/JS snippet'leri. Pipeline görünümü: Kaynak
Veri Seti → Eğitim Konfigürasyonu → Sonuç Metrikleri. Fork + yıldızlama (+0.50 CR sahibine).

## Görüntü Çıkarımı

5 sekme: Görsel (tekli/toplu), Video (frame-skip + adaptif kalite), Kamera (webcam canlı),
Karşılaştır (2-6 model slotu paralel), API (snippet). Fiyatlandırma: her çıkarım çağrısı
**0.001 CR** (toplu = görüntü sayısı × 0.001, karşılaştırma = slot sayısı × 0.001).

## Kredi Sistemi (CR)

- **4 sekme:** Kazanım, Bakiye, Hesaplayıcı, Talep.
- **Kazanım yolları (seçili):** ilk giriş 1000 CR; veri seti public paylaşma +5; 1000 yükleme
  milestone +15; kendi etiketin +0.05/kayıt; etiket onayı +0.10; inceleme +0.25; model public
  +10; yıldız alma +0.50; yararlı yorum +0.20; model indirme milestone +1.00; merge request
  kabul +2.00; günlük giriş serisi +10.
- **Seviye çarpanı:** NOVICE(1x)→APPRENTICE(1.2x)→CONTRIBUTOR(1.5x)→SPECIALIST(1.8x)→
  EXPERT(2.0x)→MASTER(2.2x)→GRANDMASTER(2.5x).
- **Adil kullanım:** günlük kazanım tavanı 100 CR (giriş serisi ödülü hariç), azalan getiri,
  kalite kapısı, hız kontrolü.
- **Talep:** admin onayıyla ek kredi istenebilir.
- Dışa aktarım 0.50 CR/çağrı, çıkarım 0.001 CR/çağrı (yukarıya bakın).

## Keşfet ve Platform

Keşif Merkezi: public veri seti/model arama+filtre(mimari/görev/modalite/etiket)+sıralama.
Liderlik tablosu: Veri Setleri/Modeller/Kullanıcılar (tüm-zamanlar). Koleksiyonlar: birden
fazla veri seti/modeli gruplama.

## Görülmemiş bölümler (kılavuzun geri kalanı)

Gösterge Paneli (3 konu), Organizasyon (1), İletişim (2), Araçlar (4), Profil ve Ayarlar (3) —
henüz paylaşılmadı/okunmadı, bu dosyaya girmedi.
