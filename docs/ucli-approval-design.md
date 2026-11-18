# ucli kalıcı onay (approval-dir / resume-approval) claudeops tasarımı

Durum: tasarım (19 Kas 2026, copsdev). Kaynak sözleşme: unified-cli `crates/ucli/src/approval.rs` ve README (`--ask-edit --approval-dir`).

## Sorun
Tek atımlık ucli işi (`chat --allow-edit --ask-edit`) dosya değiştirmeden önce soru sorar. Terminali olmayan yürütücülerde (panel "io ask", agents API `mode: edit`, ileride reviewer düzeltme koşusu) bu ya bayrağın reddine ya da sonsuz beklemeye gider. ucli çözümü: bekleme yok. İş durumu diske yazılır, süreç 75 koduyla çıkar, cevap gelince `--resume-approval ID` ile kaldığı çağrıdan sürer. `--ask-dir` (canlı REPL oturumları için, YAPILDI `0e132bb`/`ed12cd3`) bundan ayrı kanaldır: orada süreç yaşar ve bekler.

## ucli sözleşmesi (özet)
- `DIR/pending/<id>.json`: `{id, kind:"edit", tool, summary, created_at, expires_at, status}` (arayüzün göstereceği; transkript yok).
- `DIR/suspended/<id>.json`: tüm görev durumu. Claudeops OKUMAZ, yazmaz.
- `DIR/answers/<id>.json`: `{id, decision: approve|approve_session|reject|edit, edited_arguments?, note?}`.
- Süreç stdout'a `{"suspended":{id,state,resume}}` basıp 75 ile çıkar. Cevap yok / 7 gün geçti / hedef dosya değişti = ret (kapalı başarısız).

## Claudeops tarafı
1. **Dizin:** `<CLAUDEOPS_DIR>/ucli_approval/<run_key>` (0700, çalışma kökü DIŞINDA; modelin araçları erişemez). `run_key` = `^[a-z][a-z0-9_-]{0,63}$`, claudeops üretir.
2. **Başlatma seçeneği:** `cli_opts.approval_dir` (varsayılan KAPALI; `ucli_session_opts.validate_opts` yalnız `exec_write` + `ask_edit` açıkken kabul eder). REPL oturumunda anlamsız: orada `ask_dir` kullanılır, ikisi birlikte reddedilir.
3. **Kayıt defteri:** `ucli_approval/index.json` (atomik, 0600): `{run_key: {cwd, session, argv_resume (kök/sağlayıcı/izin bayrakları, gizli değer yok), owner, created_at, state: running|suspended|resuming|done|expired}}`. Sürdürme argv'sini İSTEKTEN değil kayıttan alır: cevap yazan biri kökü/izni değiştiremez.
4. **Çıkış kodu işleme:** yürütücü 75 + `suspended` satırı görürse sonucu hata saymaz; kayıtta `suspended` yapar, çağırana `{ok:true, status:"suspended", run_key, approval_id}` döner.
5. **API:** `GET /api/ucli/approvals` (kayıttaki `suspended` + `pending/*.json` özeti; `session.chat` yetkisi, çok kullanıcıda yalnız sahibinin kayıtları). `POST /api/ucli/approvals {run_key, id, decision, edited_arguments?, note?}`: kimlik bekleyen kayıtla eşleşmeli (bayat = 409), `decision` enum, `edited_arguments` en çok 64 KiB; `answers/<id>.json`'u atomik 0600 yazar, kaydı `resuming` yapar ve sürdürmeyi arka planda başlatır (`chat --approval-dir DIR --resume-approval ID` + kayıtlı argv). Zincirleme: sürdürülen koşu yine 75 ile çıkarsa yeni `suspended`.
6. **Arayüz:** `UcliAskBox` kalıbı: özet (`summary`), düğmeler "onayla / bu oturum için onayla / reddet / düzenle (JSON alanı) / not". Süresi dolanlar soluk, "süresi doldu". Bekleyen sayısı Ucli sekmesinde rozet.
7. **Yeniden başlatma dayanıklılığı:** her şey diskte; claudeops yeniden başlayınca `resuming` kayıtları `suspended`a geri alınır (sürdürme süreci öldüyse), süresi geçenler `expired`.
8. **Güvenlik duruşu:** varsayılan kapalı; sürdürme argv'si kayıttan; `edit` yalnız aynı araç (ucli zorlar); ucli hedef dosya değişmişse zaten reddeder; claudeops `suspended/` içeriğini sunmaz (transkript sızmasın).

## Dilimler
- **S1:** `ucli_approval.py` (yaprak: dizin, kayıt defteri, `list_pending`, `answer` doğrulaması) + birim testleri.
- **S2:** `approval_dir` seçeneği + `ucli_session_opts` doğrulaması + yürütücüde 75/`suspended` ayrıştırması (io ask yolu önce).
- **S3:** `/api/ucli/approvals` GET/POST + `authz` kaynak eşlemesi + sürdürme koşucusu (arka plan, zincirleme) + testler.
- **S4:** arayüz (kart + düğmeler + rozet), Chrome doğrulaması (izole 8790; sahte `pending/*.json`).
- **S5:** agents API `mode: edit` bağlama (ayrı tasarım: alt ajan çıktısı `suspended` ise üst ajana durum döner).

## Açık nokta (TBD değil, varsayım)
Cevap yazıldığında sürdürme OTOMATİK başlar (ayrı "sürdür" düğmesi yok): onay verilmiş bir iş beklemesin. Geri alınabilir, `auto_resume` ayarıyla kapatılabilir.
