# Proje notları DB'de: aşamalı göç + çok yazıcılı eşzamanlılık (taslak, 16 Kas 2026)

Kapsam: TODO.md, TOBEDECIDED.md, DONE.md, CHANGELOG.md (tüm projeler). Sahip kararları (14 + 16 Kas) değişmedi:
ayrı SQLite dosyası, .md şimdilik DB'den üretilen ayna, uzak hostlar çekme-yalnız, çekirdekte yalnız kanca, kod
`claudeops-enterprise`'ta. Bu belge yalnız EK maddenin (a)(b)(c) tasarımıdır. Kod yazılmadı.

## 1) Şema (ayrı dosya `notes.db`, WAL, `PRAGMA user_version` göçleri `store.py` kalıbıyla)

- `items(id TEXT PK, project, kind, status, text, owner_wait INT, source_file, src_hash, src_line, created, updated, version INT, closed_at, commit_sha)`
  - `kind`: todo | tbd | done | changelog. `status`: open | closed | moved. Taşıma (TODO->DONE, TODO->TBD) = aynı
    satırda `kind` değişir + `moved_from` alanı; satır silinmez.
  - `id`: ULID (DB'de üretilir). İçe aktarmadan gelen satırın kimliği ayrı tabloda (aşağıda).
- `imports(project, source_file, src_hash, item_id, PRIMARY KEY(project, source_file, src_hash))`: **idempotans anahtarı.**
- `mirror(project, file, last_hash, last_mtime, last_written)`: ayna durumu (çakışma tespiti).
- `audit(id, ts, actor, project, item_id, op, before, after)`: kim ne yaptı (MCP aracı, CLI, host, insan).

## 2) Aşamalı, idempotent içe aktarma (b)

- Birim = proje. `notes import <proje>` ya da MCP açılışta o projenin klasöründe `TODO.md` vb. görünce. Proje başına bayrak
  `notes_migrated=0|1`; 0 iken .md AYNA DEĞİL KAYNAKTIR (şu anki davranış korunur), 1 olunca DB kaynak, .md ayna.
- Satır kimliği = `sha256(normalize(satır metni))` (boşluk daraltılır, `[ ]`/`[x]` işareti ve sondaki `YAPILDI ...` eki HARİÇ:
  satır sonradan kapatılınca aynı kimlik kalsın, yoksa kapatılan satır "yeni" sayılır). Aynı metin iki kez varsa `#2` soneki.
- `imports` satırı varsa atla; yoksa ekle. Yani: bir kez alınan tekrar alınmaz; sonradan eklenen yalnız yeni gelir; kapatılmış
  satır .md'de `[x]` ise DB'deki öğe `closed` yapılır (durum eşitleme, yeni kayıt değil).
- .md'den silinen satır DB'den SİLİNMEZ (uyarı + `status=orphaned`); yanlışlıkla silme geri alınabilir.
- Ayna .md'den geri okuma yalnız "elle düzenleme" yolunda (3.3) olur ve aynı `imports` kapısından geçer; bu yüzden ayna
  yazıldıktan sonra geri okunması çift kayıt üretmez (satırın `src_hash`'i zaten kayıtlı).
- Doğrulama: göçten sonra `mirror`dan üretilen .md ile eski .md'nin (yorum/başlık hariç) satır kümesi eşit olmalı; fark = göç iptal, proje 0'da kalır.
- Sıra: önce küçük/sessiz projeler (claudeops dahil değil), sonra claudeops; proje başına el ile `notes migrate <proje>`, otomatik toplu geçiş YOK.

## 3) Eşzamanlılık (c)

1. **Tek yazıcı kapısı.** Tüm yazım (MCP araçları, `cops notes`, panel) tek `NotesService.apply(op)` üstünden; farklı süreç aynı
   `notes.db`'ye doğrudan yazmaz. Süreç içi kilit + `BEGIN IMMEDIATE` (store.py'nin `_Tx` kalıbı); `busy_timeout` 5 sn.
2. **Satır başına sürüm (optimistic).** Her yazma `expected_version` taşır: `UPDATE items SET ..., version=version+1 WHERE id=? AND version=?`;
   0 satır etkilenirse `conflict` döner (güncel satırla birlikte), istemci yeniden okuyup yeniden dener. Ekleme çakışmaz (ULID).
   Taşıma tek işlemde: `kind` güncelle + `audit` yaz; yarıda kalmaz.
3. **Ayna yazımı.** Ayna yalnız servis süreci üretir: `tmp` + `fsync` + `os.replace` (atomik), ardından `mirror.last_hash` güncellenir;
   proje başına tek yazıcı kilidi. Çok sayıda değişiklik tek seferde birleştirilir (debounce ~2 sn), her işlemde yeniden yazılmaz.
   **Elle .md düzenleme tespiti:** ayna yazmadan önce diskteki özet `mirror.last_hash` ile karşılaştırılır; farklıysa elle düzenlenmiş:
   önce fark `imports` kapısından içe alınır (yeni satır = yeni öğe, değişen satır = sürüm artışlı güncelleme, silinen = orphaned),
   sonra ayna yeniden üretilir. İçe alınamayan çatışma (aynı satır hem DB'de hem elle değişmiş) = ayna YAZILMAZ, `conflict` olayı +
   panelde uyarı, .md'ye dokunulmaz.
4. **Uzak hostlar çekme-yalnız (karar 4).** Merkez, federasyon API'siyle uzak `notes.db`'nin `updated > cursor` satırlarını çeker;
   çakışmada kaynak = projenin sahibi host. Uzak host'a merkezden yazma yok. İmleç `sync_cursor(host)` tablosunda.
5. **Çok yazıcılı yarış testi (şart).** N=8 iş parçacığı + 2 süreç aynı projede 200 işlem karışık: ekle / kapat / TODO->DONE taşı /
   aynı satırı eşzamanlı kapat (tam olarak biri kazanır, diğeri `conflict`). Beklenen: satır kaybı 0, çift kayıt 0, `version`
   monoton, `audit` satır sayısı = başarılı işlem sayısı, ayna son durumla eşit, süreç ortasında öldürülen yazıcıdan sonra DB tutarlı
   (WAL kurtarma). Ek test: elle düzenleme + eşzamanlı DB yazımı (yukarıdaki 3. madde), aynı .md'nin iki kez içe alınması (idempotans).

## 4) Çekirdek kancası ve açık noktalar

- Çekirdekte yalnız: `notes` eklenti kancası (`register_notes_backend`) + .md okuma yolunun (`_scan_todo`, değnekçi TODO taraması)
  "proje göç etmişse ayna dosyayı oku" olarak kalması (ayna olduğu için değişiklik gerekmez; en güvenli yol).
- Değnekçi/okuma listesi kodları .md okumaya devam eder; DB yalnız yazma tarafı kaynağı. Ayna gecikirse (debounce) değnekçi en çok 2 sn eski görür.
- MCP araçları: `notes_list/add/close/move/changelog_add`, hepsi `actor` + `expected_version` ister.

## 5) Sahibe tek soru (TBD olarak açıldı)

Göç sırası ve ilk proje: (A) önce küçük bir deneme projesi, sonra claudeops (öneri); (B) doğrudan claudeops; (C) hepsi bir seferde.
Gerekçe: idempotans ve ayna çakışma tespiti gerçek veriyle ilk kez sınanacak, geri dönüşü proje başına bayrakla kolay olan küçük
projede denemek riski azaltır.
