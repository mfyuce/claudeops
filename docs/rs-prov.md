# İz rs/prov: `cops-providers` (W1-pre sağlayıcılar)

Durum (27 Kas 2026, `origin/main` `ec82eac5` birleşimi `bfdb55cc`):
**BİRLEŞTİRMEYE HAZIR DEĞİL.** G1-G11 taşındı; eşleme tablosu 711 satır (TAŞINDI 638, KAPSAM DIŞI 73) ve test tablosu
1523 satır (TAŞINDI 738, KAPSAM DIŞI 785), ikisinde de EKSİK ve TAŞINDI-TESTSİZ 0. Engel: ders tablosundaki AÇIK satırlar
("Birleştirme engelleri": kim kapatır) ve sahipteki dört soru (S1-S4).
Son ağaçta ölçülen: `cargo test --workspace` 1270 geçti, 0 kaldı, 1 atlandı; `clippy --workspace --all-targets -D
warnings` ve `cargo fmt --check -p cops-providers -p cops-tmux -p cops-review-core` temiz (Rust `bfdb55cc`, sonrasında Rust
kodu değişmedi); Python tam paket 6362 OK (23 atlanan, 524 sn, `2c2c89c3`); eşleme denetimleri çıkış 0 (hosts `--check`,
rs-proc `--check --strict`, steward `map.py --check`, rev parite raporu + `map_table.py --check`). rs-tmux tablosu bu turda
yeniden denetlenmedi. Önceki turlarda yük altında oynak görülenler: `parity_live` `live-codex-ctx-dev`,
`real_fs::concurrent_issue_keeps_file_and_digest_consistent`; bu turda ara koşuda bir kez
`test_review_io_history::test_real_pipes_stream_and_heartbeat` (yük ~31; tek dosya ve tam koşuda yeşil).
27 Kas ikinci tur: `726888f1` ve `ec82eac5` eşitlemesi, X gönderimi ve yabancı kilit testleri, G3 3 ve 5, G7 8 (`agy models`),
G9 5, TBD#401, TBD#411 kaydı, maliyet toplayıcısı eşlik testi (aşağıda ilgili bölümler).
27 Kas ilk düzeltme turu: G1 1-11 (2 ve 3 sonradan geri alındı), G7 (TODO 1-5, 7, 8), G5/G11 ayrıştırıcıları, G10 aday 5,
sid/ad yol parçası denetimi, yutulan model çekimi ve `agy_sids` hatalarının günlüğü.

## Parite (`tests/parity.rs`)
- Python tek alt süreçte (boş ortam, geçici HOME/CLAUDEOPS_DIR/PATH, eklentiler kapalı), süreç/ağ çağrıları sahte. Her vaka aynı
  başlangıç ağacından iki tarafta koşar; dönüş, hata metni, diag, argv ve dosya ağacı (izinlerle) karşılaştırılır.
- 9245 vaka (27 Kas, `ec82eac5` birleşim ağacı `bfdb55cc`): spawn yürütme 261 (G9; `parity_g9`, sahte tmux/`Popen`/saat çağrı günlüğü sırasıyla, kanca ve eklenti MCP'si iki tarafta gerçek kod), tek atımlık çağrı ve onay 216 (G10; `parity_oneshot`, iki tarafta gerçek alt süreç, yalnız sahte betikler), TUI 2843 (G4; `parity_tui`, sahte pane + sahte saat), maliyet defteri 370 ve SearXNG 72 (G8 ikinci parça; `parity_ledger`, `parity_searxng`), gerçek uygulayıcı 131
  (G8; `parity_real`), resume 341 (G1; her biri bir sorgu dizisi), model kaynakları 700 (G7; her biri sahte saatli bir adım dizisi), transcript 538 (G3), chat 1178 (G2), bg_work 73 ve live 654 (G6), model/effort 105, settings/pyfmt 89, build 364, ucli 355 + tırnaklama 5, spawn 402, misc 438, usage 16 (G5; 6 sağlayıcı
  x 94 metin x 10 yöntem + 10 ikili çözümü vakası), panel 94 (G11: `ucli_cost_config` 39, `ucli_metrics.get_config` 36,
  `instructions_check` 19).
- 30 "bilinen ayrışma" (1i G1, 3ü G7, 3ü G3, 2si G2, 5i G6, 2si G4, 4ü ayar/pyfmt, 8i misc, 2si model/effort; `url-nfkc`, `byok-sozluk`, `servis-models-ic-liste` rs/state okuyucularına devirle kapandı) testte
  gerekçesiyle kayıtlı (eşit çıkarsa test düşer). 27 Kas'ta 25'i iki tarafta düzeldi (vakalar `fixed(` ile kaldı: Python'a
  eşit + Rust `expect`). Türleri ve gerekçeleri testteki `known(`/`known_if(`/`diverges(` kayıtlarındadır.
- Tek vakanın Python çıktısı: `COPS_PARITY_DUMP=<vaka-id> cargo test -p cops-providers --test parity -- --nocapture`.
- Dosya, dizin, `stat`, SQLite, yol çözümü ve `Effect` uygulaması paritede GERÇEK uygulayıcıyla (`real`) koşar; yalnız
  süreç/ağ olguları sahtedir (`parity_real` ve `parity_oneshot` hariç: orada iki tarafta da gerçek alt süreç, yalnız geçici
  ağaçtaki betikler).
- Koşucu ağa çıkmaz: `harness.py` soket bağlantısını ve ad çözümünü kapatır; `/models` istekleri `_open_no_redirect`
  sahtesinden geçer; engelin tuttuğu ayrı vakayla sınanır (`arama-ag-engeli`: altı çıkış yolu). Docker yok: `searxng`
  ailesi iki tarafta vaka ağacındaki sahte `docker` betiğini çalıştırır (`PATH`teki `docker` ağaç dışındaysa vaka düşer).
- G10 ailesinde `repo_dir`/`OWN_UCLI` vaka ağacına çevrilir: depodaki gerçek `bin/ucli` seçilemez. Tek normalleştirme:
  "ucli çıktısı JSON değildi" metnindeki `JSONDecodeError` ayrıntısı atılır.
- Paritede sahte kalan: tmux ve süreç taraması (`parity_g9`); gerçek uygulayıcıları (`real/tmux.rs`, `real/scan.rs`) yalıtılmış tmux sunucusu ve sahte `/proc` ile ayrı sınanır (G9 bölümü).
- Belge deposu ayrı testte (`tests/parity_docs.rs`, `tests/parity/docs_driver.py`): gerçek `statedocs` + `agy_provider` ile `StateDocStore`, 20 senaryo x 3 kip (`files`, `dual`, `db`) = 60 karşılaştırma; dönüş, dosya, DB `docs` gövde + sürüm, `diag.log` ve DB `diag` akışı. Her taraf kendi geçici durum dizininde.
- `parity_misc` `sync*` vakaları gerçek `real::routing_sync::sync_one` ile koşar (G9). `ucli_web_searxng_error` diag'ı BİLEREK yok: Rust arama yöneticisi
  istisna üretemez (her hata kendi içinde `None` + `searxng_*` olayı).
- TBD#386, TBD#389 ve G2/G6 Python hataları (TBD#383 kalıcı kuralı) iki tarafta düzeltildi; ayrıntı ilgili grup bölümünde.
  Eklenen özel yardımcılar (Rust karşılığı): `claude_provider._row_model` (`claude_transcript::assistant_model`),
  `_row_content`, `codex_provider._codex_item` (`chat.rs`), `copilot_provider._cell_value` (`chat.rs::cell_or_empty`),
  `ucli_client._read_turns` (`chat.rs::ucli_turns`), `bg_work.{_result_text, _hashable}` (`bg_work.rs::{result_text, key}`),
  `base._ro_sqlite_uri` (Rust yolu URI diye ayrıştırmaz), `ucli_session_opts._open_no_redirect` (`real/http.rs`). Tablodaki
  Python satır numaraları bu düzeltmelerden önceki konumlardır.
- TBD#373 maddeleri 1, 3-8 iki tarafta düzeltildi (Python `fix:` commit'leri + Rust eşitlemesi). Madde 2 (bozuk UTF-8
  `settings.json`) rs/state'in işi. Kalan fark: var olan ama izin yüzünden okunamayan yönerge override dosyasında Python üzerine
  yazar, Rust dokunmaz (`Probe::read_text` iki durumu ayırmıyor); `trustedFolders`ta eşi olmayan vekil kod (`\ud800`) içeren
  girişte Rust yazmaz, Python yazar.
- API değişikliği: `plan_spawn(p, req, &mut BuildOutput)` (hata durumunda da biriken Effect/diag korunur).
- Kuru çalıştırma: `SpawnRequest.dry_run` / `BuildOutput.dry_run` (Effect ve diag eklenmez; `register_mcp` ve `issue_agent_token`
  çağrılmaz; `Probe::searxng_url(session, preview)`; `claude_cost_gate` yine çağrılır). `sync_plan` ham bayt alır
  (`SyncAction::SkippedBadUtf8`).

## Kapsam (ilk görev metni)
- Yazılabilir yollar: `rust/crates/cops-providers/**`, `rust/Cargo.toml` members satırı, `docs/rs-prov.md` (`rust/Cargo.lock` yeni bağımlılıklarla değişti).
  `py/` ve diğer crate'lere YAZMA. `docs/rust-*.md`, CLAUDE.md, TODO.md, TOBEDECIDED.md, DONE.md symlink: bu dalda git add etme.
- Saf mantık (G/Ç yok): `providers/` spawn argv + ortam, resolve_effort/default_effort_for/default_model_for/preferred_default_model,
  `_EFFORT_LIMITS`, agy `gemini-*-high` kademesi, `routing.py` yönerge bayrakları, spawn_nice, main_session_model_effort.
- Parite: Python'u alt süreçte (`PYTHONPATH=py`, geçici `CLAUDEOPS_DIR` ve geçici `HOME`) çağıran tablo testi; tüm sağlayıcılar ve effort/model kombinasyonları.
- Kurallar: önce `docs/rust-sprint-plan.md`, strangler planı 1-4 ve 10, CLAUDE.md. Kendi dalına commit, origin+gitlab'a push; main'e push/merge YOK.
  Testler canlı durum dizinine yazmaz. Ana oturum Sonnet; zor tasarım Opus alt ajan; Fable yok. Sahibe soru: cevabın sonunda `STEWARD-ASK:`.
  Cargo hedefi `~/.cargo-target`. Bitişte son satır: `BİRLEŞTİRMEYE HAZIR: <dal> <commit> <test özeti>`. Canlıya almayı cops yapar.

## EK (sahip 26 Kas): Python dersleri
`docs/rust-lessons-from-python.md` genel liste + bu izin kontrol listesi ZORUNLU; her madde burada test adı ya da gerekçeyle karşılanır.
Dosya 26 Kas akşamı worktree'ye geldi (takipsiz, git add edilmez). 27 Kas: crate'in tamamı için madde madde karşılandı,
tek tablo "Ders listesi: crate'in tamamı" bölümünde (AÇIK satırlar gerekçeli).

## EK 2 (sahip 26 Kas): işlevce eşlik
- Rust'ta Python'dan eksik hiçbir şey kalmayacak. Aşağıdaki EŞLEME TABLOSU: kapsamdaki modüllerin HER işlev/metot/sınıf/modül düzeyi
  ataması (ast) bir satır; HER `py/tests` `test_*` metodu bir satır (Rust test adı ya da neden gereksiz).
- Boş/"sonra"/AÇIK satır varken BİRLEŞTİRMEYE HAZIR yazılmaz. cops tabloyu ast çıktısıyla karşılaştırır.
- Boş girdi, bozuk JSON/dosya, Unicode, eksik alan, eşzamanlı yazım, zaman aşımı Python gibi davranır. Python davranışı hatalıysa
  sessizce düzeltme: tabloda `Python hatası?` + `STEWARD-ASK`.
- İlk görev metni yalnız komut kurulumu/effort/model/yönerge/nice istiyordu; EK 2'nin "izin kapsadığı modüller"i için ayrıştırıcılar, keşif
  (`matches_proc`/`extract_*`), transkript okuma, kullanım ayrıştırma satırları da tabloya girer: ya taşınır ya `kapsam dışı: neden + iz` yazılır.

## Tasarım (yazılan)
- `Probe` (dış olgular) + `Effect` listesi (dosya yazma/silme isteği, sırayla uygulanır) + `Diag` (diag_log olayları). Sır içeren `Effect`
  Debug'da maskeli. Durum değiştiren dört `Probe` yöntemi: `claude_cost_gate`, `issue_agent_token`, `register_mcp`, `apply_now`.
- Gerçek G/Ç yalnız `real` modülünde (G8); öteki modüller saf kalır.
- Modüller: `provider` (Cli enum, model/effort, build), `claude|agy|codex|copilot|shell|ucli`, `ucli_opts`, `routing`, `spawn`, `settings`, `effort`, `pyfmt`, `model_sources` (G7).
- `plan_spawn` `resume_id`yi girdi alır; çözümü `Live::resolve_resume_id` + `ids_held_by_others` (G1). İkisini bağlayan akış G9.

## Sıradaki
1. Birleştirme engelleri ("Birleştirme engelleri" bölümü): iz işleri ve bekleyen sorular S1-S4.
2. Bağlayan uç (copsd/panel `_start`, rc, devir) `SpawnRuntime` + `CopsTmux` + `ProcScan` + `TmuxPane` ile; o izlerin işi
   (async çağıranda `spawn_blocking`; bekçi `Watchdog` `join`; spawn'ı `guard.lock` altında tutmak `guard.py` taşımasının).
3. Ortaklaştırma yapıldı (27 Kas, üçüncü tur; "Üçüncü tur" bölümü). Kalan ikinci kopya: `pyjson::Py` ayrıştırıcısı ile
   `cops-state::json::Json`.
4. Kapandı (27 Kas): TAŞINDI-TESTSİZ satırlar; gerçek `Pane` (`real/pane.rs`); ders listesinin madde madde karşılanması;
   `cargo fmt`; effort, `with_block`, `validate_opts` birim testleri ve "sır argv'de yok" testi (`tests/secrets_argv.rs`);
   G1 1-11 (2 ve 3 bilerek uygulanmadı), G3 1-3, 5, 7, G5/G11, G7 (1-10), G9 aday 5, G10 aday 1 (TBD#401) ve 5, TBD#397,
   TBD#399, TBD#411 (kod değişmez).

## Birleştirme engelleri (27 Kas; kural: "AÇIK satır varken BİRLEŞTİRMEYE HAZIR yazılmaz")
Eşleme ve test tablolarında EKSİK / TAŞINDI-TESTSİZ satır YOK. Engel, ders tablosundaki AÇIK satırlardır:

| Ders satırı | Açık | Kim kapatabilir |
|---|---|---|
| §3.1 (a), §2.5.8 | sid'siz okuma cwd'deki en yeni transkripte düşer | sahip (S1), sonra iz |
| §3.1 (c), §2.5.8 | `ids_held_by_others` taraması ile spawn arasındaki yarış (`guard.lock`) | başka iz (`guard.py` taşıması / T4) |
| §3.5 | atlanan bozuk aday, `Effect::Remove` hatası ve günlüğün kendi yazım hatası günlüğe girmiyor (TBD#404: bilerek açık) | cops kabulü |
| §3.7 | maliyet günlüğü taramasının SÜRESİ dosya boyutuyla sınırsız (bellek sabit, ölçüldü) | sahip (S5), sonra iz |
| §3.8 | gerçek claude sürümünden yakalanmış ekran fixture'ı yok (TBD#399 için canlı deneme de yapılmadı) | cops/sahip (canlı claude) |
| §3.13, §2.5.7 | kanca ve `env_overrides` ortamı tmux komut satırında | sahip (S4), sonra iz |
| §3.14 | okuma yolları bağlantı izler, ayardaki uç noktaya iç ağ engeli yok (bilerek) | cops/sahip: kabul ya da değişiklik |
| §3.20, §2.5.6 | spawn kancası kuru koşuda da çağrılır | sahip (S3), sonra enterprise/iz |
| §2.5.2 | ikilinin sürümü günlüğe yazılmaz (ders maddesi istiyor; Python da yazmaz, eklemek Python'a yeni günlük olayı = özellik) | cops kabulü |

Ayrıca kuralın parçası olmayan ama canlıdan önce gerekenler: bağlayan uç (başka izler), uzak deploy ve web restart (cops).

## Bekleyen sorular (sahip)
- **S1 (sid'siz transkript okuma).** Claude oturumunun konuşma kimliği (sid) bilinmiyorsa (`--resume`suz taze açılış) devir
  kararı ve takılan oturumun yeniden açılışı, o dizindeki EN YENİ konuşma dosyasından model/effort okur; aynı dizinde iki
  oturum varsa kardeşinki alınabilir. (a) sid yoksa dosya okunmasın, açılıştaki `--model/--effort` kullanılsın: karışma
  biter, ama terminalden `/model` ile değiştirilmiş taze oturumda devir düşürmesi tetiklenmez ve yeniden açılış eski
  değerle olur. (b) önce `~/.claude/sessions/<pid>.json`dan sid çözülsün (kodda `session_file_sid` var), bulunamazsa açılış
  değeri: tahmin kalkar, taze oturumlar doğru kalır. (c) aynen. Öneri: (b).
- **S2 (eski satırdan effort).** Son yanıt satırında `effort` alanı yoksa (ör. effort desteklemeyen modele geçiş) daha eski
  satırın effort'u "canlı" sayılıp devir ve yeniden açılışta kullanılıyor. (a) yalnız son yanıt satırı sayılsın, yoksa
  açılış değeri: güncel claude'un her satıra effort yazdığı ölçülmedi, yazmıyorsa canlı effort sık sık açılış değerine
  döner. (b) effort yalnız son satırla AYNI modele ait satırlardan alınsın: model değişince eski effort taşınmaz, aynı
  modelde davranış değişmez. (c) aynen. Öneri: (b).
- **S3 (kuru koşuda spawn kancası).** `spawn_session(dry_run=True)` çok kullanıcı kancasını yine çağırıyor; TODO'daki kod
  okumasına göre enterprise kancası bu sırada dizin açıyor, ret denetim kaydı yazıyor ve bellekte kota ayırıyor (bu turda
  ölçülmedi). Panel, oturumu başka CLI ile devralırken eski oturumu kapatmadan önce reddi bu kuru koşuyla görüyor. (a)
  çağrı kalsın, enterprise kancası kuru koşuyu (`preview.active()`) görünce yazmasın: ön denetim korunur, çekirdek
  değişmez. (b) kuru koşuda kanca hiç çağrılmasın: yan etki biter, ama kota/yetki reddi ancak eski oturum kapandıktan sonra
  görünür. (c) aynen. Öneri: (a).
- **S4 (ortam değişkenleri komut satırında).** Oturum açılırken sağlayıcı ve kanca ortamı `AD=DEĞER` olarak komut satırına
  gömülüyor; kanca sır döndürürse makinedeki başka kullanıcılar süreç listesinden görebilir. Bugünkü sağlayıcı değerleri
  sır içermiyor; enterprise kancasının döndürdükleri bu turda incelenmedi. (a) adı `_KEY`/`_TOKEN`/`_SECRET` ile biten
  değerler 0600 dosyaya yazılıp oradan yüklensin (copilot anahtarındaki yöntem): açılış komutu değişir. (b) kanca böyle
  bir ad döndürürse oturum açılmasın. (c) aynen kalsın, kural olarak "kanca sır döndürmez" yazılsın. Öneri: (a).
- **S5 (maliyet günlüğü taramasının süresi).** Günlük USD tavanı açıkken Claude hizmetli ucli oturumu açılmadan önce
  harcama günlükleri iki dilde de baştan sona, açılış başına birden çok kez okunuyor; bellek sabit, süre dosya boyutuyla
  artıyor. Ölçüm (tek günlük dosyası, bütün satırlar bugüne ait, release derleme, yük ~10): 10 / 100 / 500 MB için tek
  tarama Rust 0,22 / 1,70 / 17,6 sn, Python 1,09 / 13,0 / 43,0 sn; Rust açılış denetimi 1,25 / 15,7 / 69,2 sn (Python
  açılış denetimi ölçülmedi). Rust tarama süresince tepe bellek 3,1-3,4 MB, Python 20 MB. (a) günlük dosyasına boyut
  sınırı; aşan dosya tavan açıkken "sayılamıyor" sayılıp açılış reddedilsin: süre sınırlanır, bugün açılan oturum
  reddedilebilir. (b) ret kuralı aynen; açılış denetimi her dosyayı tek geçişte okusun: sonuç aynı, süre düşer ama yine
  boyutla artar, iki dilde kod değişir. (c) aynen. Öneri: (b).
- Not (soru değil, açık kalan): TBD#401 `endpoint` alanını sınırlamadı; `/api/io/ask` izinli bir anahtar adını (ör.
  `ANTHROPIC_API_KEY`) çağıranın verdiği adrese hâlâ gönderebilir.

## Parite testinde bakılacak bilinen farklar / şüpheler
Parite testinde kayıtlı ayrışmalar yukarıdaki "Parite" bölümünde. Açık kalanlar:
- Gerçek tmux ile Python'a karşı (paritenin dışında, `tests/real_pane.rs`): bilinçli tek fark özel tuşta maske denetimi
  (Python `tmux_send_special_key` denetlemez, Rust `RefuseMasked`). Gizli girdi bekleyen pane'de iki tarafta da ekrana
  hiçbir şey ulaşmaz ve Enter basılmaz (`masked_pane_gets_no_command_and_no_enter`).
  `settle` NaN/inf: Python metni yapıştırıp düşer ya da boş metinde Enter gönderir, Rust hiçbir şey göndermez (çağıranlar
  yalnız sabit verir).
- G5/G11 Python hataları (27 Kas iki tarafta DÜZELDİ; `py/tests/test_rsprov_g5_fixes.py`, Rust `usage::tests::parser_corners_fixed_on_both_sides`, `python_classes`):
  - `normalize_ucli_services`: `models` sayı/`true` `TypeError`ı main'de (rs/state, TBD#374 S8) düzelmişti; bu dalda yeniden
    yazılmadı, testte korunuyor (parite `servis-models-sayi` artık kayıtlı ayrışma değil).
  - `ucli_metrics._num`: NaN varsayılana düşer (Rust `settings::metrics_num`; parite `metrics-nan` eşit).
  - copilot `_USAGE_PLAN_RE`: çubuk tembel (`\S*?`): `■■50%` 50 okunur.
  - claude `_USAGE_FRESH_RE`: `· resets` sonrası metin yoksa ayrıntı boş (`Resets resets` değil).
  - copilot `_USAGE_RESET_RE`: `resets in` sonrası yalnız boşluk ayrıntıya girmez.
  - Yüzde ve sayılar yalnız ASCII rakam: claude/copilot desenlerinde `\d` -> `[0-9]`, agy `isdigit()` -> ASCII rakam
    (`²`, `①`, `٣` yüzde sayılmaz). `/context` kategori adı bir harfin ortasından başlıyorsa (`Şey` -> `ey`) satır atlanır.
    Bilinen testsiz fark: önceki karakter harf mi sorusunda Python `isalpha()`, Rust `char::is_alphabetic` (Nl ve
    Other_Alphabetic birleşik işaretlerde ayrışır).
- G5 notu: ayrıştırıcılar ANSI ayıklamaz (Python gibi; çağıran `strip_ansi` uygular). ANSI'li girdiler paritede var, sonuç Python'la aynı.
- `Settings` yalnız ayrıştırılmış nesneyi yorumlar; Python `load_settings`in varsayılan birleştirmesi ve bilinmeyen anahtar süzmesi rs/state'te. Birleştirmede iki okuyucu aynı belgeyi görmeli.

## Ders listesi: crate'in tamamı (tek tablo, 27 Kas)
`docs/rust-lessons-from-python.md` §3 genel gözden geçirme listesi (20 madde), §2.5 bu izin kontrol listesi (11 madde) ve
"Rust'a özgü yeni riskler" (7 madde). Her test adı koddan doğrulandı (dosya::ad; `parity_*` = `tests/parity.rs` ailesi ve
vaka kimliği). Grup bölümlerindeki eski ders tabloları buraya taşındı ve yeniden doğrulandı; oralarda yalnız işaretçi kaldı.
Durum: TAMAM = madde crate için karşılandı; UYGULANMAZ = crate o işi yapmaz (gerekçe); AÇIK = karşılanmadı, neden yazılı.
Bu turda düzeltilenler: `SystemClock::sleep` `Duration`a sığmayan sürede panik atıyordu (`try_from_secs_f64`);
`TmuxPane` (G4 gerçek `Pane`) yazıldı; `py_re` çevirmenine rastgele desen testi; effort, `with_block`, `validate_opts`,
sır-argv birim testleri.

| Madde | Karşılama (test ya da gerekçe) | Durum |
|---|---|---|
| §3.1 hedef `Unique`; yıkıcı eylem ön ek / "en yeni" ile çalışmaz (H7) | tmux hedefi hep `=ad:` (`cops-tmux`), hedeflenemeyen ad hiçbir tmux komutu çalıştırmaz: `real_tmux::unaddressable_names_run_no_tmux_command_and_open_nothing`; ön ek kardeşe dokunulmaz: `real_tmux::spawn_direct_runs_inner_with_only_the_given_env_in_the_exact_session`, `real_pane::prefix_name_never_reaches_another_session`, `real_tmux::reclaim_kills_only_the_exact_old_childless_shell`, `open_window_attaches_to_the_exact_existing_session`; sid verilince tahmin yok: `resume::only_a_sidless_lookup_guesses_the_newest_transcript`, `claude_transcript::cache_candidates_are_exact_files_and_newest_wins` | TAMAM (yıkıcı yollar; 27 Kas: agy önbellek kimliği başka ada öğrenilmişse alınmaz, codex `sid` tam eşleşir, G1 5 ve 4). AÇIK: (a) sid'siz okumalar (`jsonl_path_for`, codex rollout, `live_or_spawn_*`) Python gibi cwd'deki en yeniye düşer (G3 şüphe 4; kaldırmak devir davranışını değiştirir: sahipte, "Bekleyen sorular" S1); (c) `ids_held_by_others` taraması ile spawn arasındaki yarış: kilit çağıranın (`guard.lock`, `guard.py` taşıması; G9 bölümü) |
| §3.2 atomik yazım; çok yazarlı belgede kilit sözleşmesi (H2) | `real_fs::atomic_write_keeps_the_private_mode_replaces_links_and_leaves_no_tmp`, `concurrent_atomic_writes_never_expose_a_partial_file` (dosya `sync_all`, aynı dizinde benzersiz tmp); Python'la aynı `flock`: `real_agy_store::rust_and_python_writers_across_processes_lose_nothing`, `the_lock_is_the_one_python_takes_and_waiting_is_bounded`, `real_oneshot::the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing`, `concurrent_registrations_lose_nothing_and_one_key_has_one_winner`, `real_searxng::the_state_write_waits_for_the_lock_python_takes_and_keeps_other_keys`; pay: `real_ledger::concurrent_starts_cannot_oversubscribe_the_cap`; token: `real_fs::concurrent_issue_keeps_file_and_digest_consistent`; `resume::value_is_checked_again_under_the_lock`, `concurrent_remembers_lose_nothing`; belge deposu `real/docs.rs::StateDocStore` (rs/state `StateDocs`): `parity_docs::state_docs_match_python_in_every_backend` (files, dual, db), `a_fifo_document_is_never_opened_or_replaced`, `the_backend_comes_from_settings_and_db_ignores_the_stale_mirror` | TAMAM |
| §3.3 belirsiz / okunamayan durum `Allow`, başarı ya da "yok" olmaz (H13, H10, H9) | pane maskesi bilinmiyor = hiçbir şey gönderilmez: `real_pane::hung_tmux_times_out_to_false_and_none`, `masked_pane_gets_no_command_and_no_enter`; okunamayan defter/ayar tavanı kapatır: `real_ledger::an_unreadable_or_invalid_ledger_closes_an_open_cap`, `settings_are_read_on_every_call_and_an_unreadable_document_refuses`; kanca hatası ret: `parity_g9` `kanca-hata`, `kanca-hata-uzun`; `/proc` okunamazsa tarama düşer: `real_scan::unreadable_process_list_drops_the_scan_and_writes_nothing`; okunamayan transkript "bilinmiyor": `claude_transcript::truncated_file_and_read_errors_mean_unknown`; okunamayan `--help` = bayrak yok: `real_process::empty_failed_slow_huge_or_non_utf8_help_is_not_cached` | TAMAM (27 Kas: açılamayan ucli anahtar dosyası ret, `real_oneshot::an_unreadable_key_file_is_refused_not_treated_as_missing`; bozuk `agy_sids` belgesi ezilmez, `parity_resume` `agy-yaz-bozuk`/`-liste`, `parity_real` `agy-belge1..3`; başarısız hizmet çekimi iyi listeyi ezmez). Uzak host (H10) UYGULANMAZ: crate uzak çağrı yapmaz |
| §3.4 eylem sonucu tipte; NEGATİF test (H9) | `#[must_use] SwitchOutcome`; `tui::a_failed_send_returns_without_waiting`, `permission_dialog_is_never_confirmed_even_with_switch_text_above_it`, `no_enter_unless_the_cursor_is_seen_on_no`; gerçek tmux: `real_pane::masked_pane_gets_no_command_and_no_enter` (`DialogOpen`, tuş reddi `LeftOpen`); `Effect` uygulaması `Result`: `real_fs::apply_all_stops_at_the_first_failure_and_reports_where`; `register_mcp` hata metni: `real_process::register_mcp_errors_carry_python_reprs`; spawn `SpawnFailure` + pay iadesi (`parity_g9` her vakada `release`) | TAMAM (27 Kas, TBD#399: eski sonuç satırı sayılmaz, onay Enter'ının sonucuna bakılır, `Done` yalnız yeni işaret + hazır giriş kutusu) |
| §3.5 hata yutma / panik yok; yutulana sayaç ya da günlük (H9, H20) | üretim kodunda `panic!`/`unreachable!` yok; `unwrap`/`expect` yalnız sabit desen derlemesi ve önceden denetlenmiş değişmez (`py_re` kaçışları sınır denetiminden sonra; `claude.rs::refresh_stored_model`, `ucli.rs` ön ayar, `ucli_opts.rs` elenmiş `None`). Rastgele girdi: `py_re::tests::random_patterns_never_panic`, `*::truncated_and_mutated_input_never_panics` (`claude_transcript`, `resume`, `chat`, `bg_work`), `model_sources::broken_and_mutated_model_answers_never_panic`. Bu turda bulunan panik: `SystemClock::sleep(1e300)` (`g9::system_clock_is_monotonic_and_ignores_bad_sleeps`), `TmuxPane` geçersiz `settle` (`real::pane::tests::settle_maps_python_values_and_never_panics`). `let _ =` olanlar Python'un `except: pass` dallarının karşılığı (çocuğu öldür+topla, tmp sil, dizin fsync, `kill-session`, iş parçacığı başlatma: `a_background_job_that_cannot_start_keeps_the_old_list`) | TAMAM (panik). 27 Kas: model kaynağı çekim hatası `models_fetch_failed`, okunamayan `agy_sids` `agy_sids_unreadable` olarak iki tarafta günlükte (`parity_model_sources`, `parity_misc` `live5`, `parity_resume`, `model_sources::service_models_keep_the_good_list_and_follow_the_key`). AÇIK (bilerek, TBD#404; cops kabulü bekliyor): (1) atlanan bozuk rollout/transkript adayı: panelin 4 sn'lik yoklamasında her turda yinelenir, tekilleştirmesiz günlük `diag.log`u şişirir ve 5 MiB döndürmesi öbür olayları atar; (2) `Effect::Remove` hatası: Python `except OSError: pass` (copilot ve ucli anahtar dosyası silme), TBD#404 "üç hata" kapsamında; bu hata yoklamada değil yalnız açılışta olur, istenirse iki tarafta küçük bir `fix:` ile günlüğe alınabilir; (3) `DiagLog`un kendi yazım hatası: yazılacak yer yok |
| §3.6 önbellek / ayar bayatlamaz; hata `last_good`u ezmez (H3) | `model_sources::repeated_errors_never_replace_the_last_good_list`, `a_background_job_that_cannot_start_keeps_the_old_list`, `codex_choices_are_cached_but_effort_levels_read_the_current_file`; ayar her çağrıda: `real_ledger::settings_are_read_on_every_call_and_an_unreadable_document_refuses`, `the_state_is_cached_until_ttl_or_invalidate`; dosya imzası: `resume::unchanged_files_are_not_reread_but_changed_ones_are`, `real_process::help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery`; canlı model/effort jsonl'den (G3): `claude_transcript::synthetic_and_unexpected_rows_do_not_hide_the_real_model` | TAMAM |
| §3.7 her bekleme sınırlı; bildirim durumu kalıcı (H8) | `tui::every_wait_ends_on_its_budget_even_when_the_pane_stops_being_readable`; gerçek tmux: `real_pane::no_dialog_means_no_keys_on_either_side` (6 sn), `hung_tmux_times_out_to_false_and_none` (5 sn); bekçi `g9::watchdog_retries_then_falls_back_to_headless_tmux`; süreç: `real_process::a_timeout_kills_the_whole_process_group_and_waits`, `a_grandchild_holding_the_pipe_hits_the_deadline_like_python` (`Spec.timeout` zorunlu alan); HTTP: `real_http::the_timeout_is_the_total_time_not_per_read`, `an_endless_body_stops_at_the_limit`; docker: `real_searxng::a_hanging_docker_is_killed_marked_down_and_not_asked_again` (kalıcı "down"); `flock` 30 sn: `real_agy_store::the_lock_is_the_one_python_takes_and_waiting_is_bounded`. Üretim `loop`ları okuma sınırı ya da son tarihle biter | TAMAM. AÇIK: maliyet günlüğü taramasının SÜRESİ dosya boyutuyla sınırsız (Python gibi). Bellek sınırlı: satır satır okunur, satır tavanı 16 MiB (`real_ledger`), ölçülen tepe 10-500 MB dosyada 3,1-3,4 MB; süre sınırı ret/harcama davranışını değiştirir ("Bekleyen sorular" S5). Nag/bildirim UYGULANMAZ |
| §3.8 dış TUI davranışı fixture ile; `Unknown` ekranda gönderim yok (H4) | kelime kelime ANSI'li diyalog basan sahte claude TUI'sine Python `ClaudeProvider` ve Rust `TmuxPane` aynı baytları gönderir: `real_pane::model_switch_confirms_the_dialog_like_python`, `model_switch_without_dialog_sends_no_extra_enter_like_python`, `effort_switch_confirms_the_dialog_like_python`, `stray_dialog_is_declined_with_down_enter_like_python`; `parity_tui` 1079 (sahte pane); diyalog görünmüyorsa Enter yok: `tui::applied_without_dialog_sends_no_key`, `an_old_result_line_does_not_count`; maske bilinmiyorsa metin ve tuş yok (yukarıda) | AÇIK: gerçek claude sürümünden yakalanmış ekran fixture'ı yok (canlı claude ister: cops/sahip; teslim doğrulaması ve mod tespiti çağıran izlerde, T4/T10). Diyalog artık yalnız ekranın SONUNDA tanınır (TBD#399) |
| §3.9 süreç / bağlantı sahipliği, fd sızıntısı (H1) | `real_fd::a_hundred_rounds_of_failures_leak_no_descriptor_and_no_child`; `real_process::a_timeout_kills_the_whole_process_group_and_waits`, `closed_pipes_with_a_running_child_still_time_out`, `bounded_capture_overflows_and_tail_capture_keeps_the_end` (akışlar boşaltılır); `real_oneshot::timeouts_kill_the_whole_group_and_return_promptly`; `g9::gnome_terminal_runs_with_only_the_given_env_and_is_reaped`; `real_searxng::a_hanging_docker_is_killed_marked_down_and_not_asked_again`. Sinyal yalnız kendi başlattığı çocuğun grubuna (`real/process.rs`, `process_group(0)`); oturum öldürme yok (`kill.py` kuralı); tmux istemcisi `cops-tmux`ta öldür+topla | TAMAM. Bekçi iş parçacığı: kısa ömürlü çağıran `Watchdog`u `join` etmeli (G9; bağlayan uç) |
| §3.10 girdi sınırları: boş, negatif, NaN/inf, bozuk UTF-8, tip (H5) | NaN/inf: `real::pane::tests::settle_maps_python_values_and_never_panics`, `g9::system_clock_is_monotonic_and_ignores_bad_sleeps`, `real_ledger::an_unreadable_or_invalid_ledger_closes_an_open_cap` (NaN, negatif, metin), `ucli_opts::tests::validate_opts_matches_python` (`nan`, `inf`, `-1`), `parity_panel` `metrics-nan`; UTF-8: `real_process::empty_failed_slow_huge_or_non_utf8_help_is_not_cached`, `real_ledger::a_log_with_a_non_utf8_name_still_counts`, `real_pane::capture_matches_python_and_keeps_ansi`; başlık olamayan anahtar: `model_sources::a_key_that_cannot_be_a_header_value_sends_nothing`; FIFO: `real_fs::reading_takes_only_regular_files_and_never_blocks_on_a_fifo`, `real_oneshot::a_fifo_key_file_or_index_is_refused_without_blocking`; bozuk/kesik girdi: §3.5 rastgele testleri | TAMAM (27 Kas, G1 7: bozuk `agy_sids` belgesi üzerine YAZILMAZ, `parity_resume` `agy-yaz-bozuk`; bozuk `ucli_agents` kopyalanır, `real_fs::a_corrupt_agent_registry_is_copied_aside_and_an_unreadable_one_is_not_overwritten`) |
| §3.11 işaret / ad ayrıştırma tek modül, corpus, Python vektörü (H6, H14) | crate STEWARD/RFH işareti ayrıştırmaz (UYGULANMAZ, değnekçi izi). Crate'in ayrıştırıcıları Python'a karşı: kota/bağlam `parity_usage`, transkript `parity_transcript`, protobuf/SQLite sohbet `parity_chat`, `exec_cmds` regex çevirmeni `parity_ucli` + `py_re::tests::random_patterns_never_panic`, oturum adı `ucli::is_child_name` `parity_ucli` | TAMAM |
| §3.12 Python ile paylaşılan kural / yol diferansiyel testle eşit; `$HOME` doğrudan yok (H14) | `tests/parity.rs` 20 aile (sayılar "Parite") + `tests/parity_docs.rs`; gerçek tmux/pane Python'a karşı: `real_tmux::fragments_match_python`, `real_pane::*_like_python`, `capture_matches_python_and_keeps_ansi`; durum yolları yalnız `Paths`ten (çağıran verir; `src/`de `HOME` okuması yok); `strip_ansi` tek kaynak `cops-tmux` ; ortak tek kaynak: `is_safe_env_name`, `valid_http_url`, ayar belgesi ve okuyucuları, `strip`/`isspace`/`repr`/`int`/`float`/ondalık rakam rs/state, `splitlines` rs/proc, `main_session_model_effort` rs/stew (kopya silindi) | TAMAM (27 Kas üçüncü tur). Not: `pyjson::Py` ayrıştırıcısı `cops-state::json`dan ayrı kalır (eşlenmemiş vekil ve 4300 basamak kuralı farklı); davranışı Python'a karşı parite aileleriyle sınanır |
| §3.13 sır tipte; log / argv / URL'de yok (H12, H13) | `Effect::WriteSecret` `Debug`ta `<redacted>`; `model_sources::SecretValue` + `the_key_stays_out_of_urls_argv_and_debug_output`; BYOK anahtarı yalnız 0600 dosyada: `secrets_argv::copilot_byok_key_goes_to_a_private_file_not_argv`, `ucli_evren_key_goes_to_a_private_file_not_argv`, `ucli_service_key_goes_to_a_private_file_not_argv`; çocuk ortamı: `real_oneshot::the_key_reaches_only_the_child_environment`; hata metni: `oneshot::tests::secrets_are_removed_from_every_error_text`; token yalnız özetiyle kayıtlı: `real_fs::agent_token_is_0600_and_only_its_hash_is_registered`; pane metni argv'de değil: `real_pane::text_never_appears_in_tmux_argv`; hayalet ekranı günlüğe girmez (`parity_g9` `hayalet-`) | TAMAM. AÇIK: kanca ve `env_overrides` ortamı tmux komut satırına `KEY=VAL` gömülür (Python gibi; kanca sır döndürürse `/proc/*/cmdline`da görünür; tmux 3.0a'da `new-session -e` yok, taşımak oturum açmayı değiştirir: "Bekleyen sorular" S4). Kimlik matrisi UYGULANMAZ (crate yetki vermez) |
| §3.14 yol / adres girdisi, symlink (H17) | `real_fs::secret_files_are_private_from_creation_and_links_are_not_followed`, `atomic_write_keeps_the_private_mode_replaces_links_and_leaves_no_tmp`, `realpath_handles_links_loops_and_missing_parts`; `real_agy_store::a_symlinked_lock_file_is_refused_and_nothing_is_written`; `g9::dangling_backup_link_writes_neither_backup_nor_target`; env beyaz liste: `parity_spawn` `filter`, `kanca` (`LD_PRELOAD`), `parity_g9` `ortam-supurme`; HTTP: `real_http::unusable_addresses_send_nothing`, `redirects_are_never_followed_and_the_key_does_not_leave` | TAMAM (27 Kas, iki tarafta): `/` ya da NUL taşıyan oturum adı / kimlik dosya yoluna eklenmez (`pyfmt::is_path_part`, Python `base._path_part_ok`; ek alan adlarda `.`/`..` kaçamaz): agy konuşma veritabanı, claude istek adayı, codex rollout, ucli durum/sohbet dosyası ve `--state-dir` denetimi; harf, rakam, `.`, `-`, `_`, ASCII dışı harf taşıyan adların hiçbiri reddedilmez (`test_rsprov_paths_keyfile.py::PathPartTest`, `UcliFilesTest`, `ClaudeRequestTest`; parite `chat-agy-mutlak-kimlik`, `transkript-istek-mutlak`, `chat-ucli-yol-disi`, `live-durum-yol-disi`). AÇIK (bilerek): okuma yolları bağlantı izler (agy/claude/codex dizinleri CLI'ların kendi bağlantılı kurulumlarında da çalışmalı); ayardaki uç noktaya iç ağ engeli yok (yerel/iç ağ servisleri meşru uç nokta) |
| §3.15 vekil / WS kullanıcı yolundan e2e (H15, H18, H21) | crate sunucu, vekil, WS değil: UYGULANMAZ. İstemci tarafı: `real_http::a_2xx_body_is_returned_for_every_framing`, `error_statuses_broken_and_truncated_answers_are_errors_without_details`, `https_is_tunnelled_with_connect_and_proxy_auth_stays_outside_the_tunnel`, `tls_verification_is_on_for_untrusted_roots_and_wrong_names` | UYGULANMAZ (bağlayan uç copsd'nin e2e'si) |
| §3.16 yeni uç / route tablo eşitliği (H10, H14) | crate uç eklemez | UYGULANMAZ |
| §3.17 test yalıtımı (H16) | her test `TempDir` (RAII); parite koşucusu boş ortam, geçici HOME/CLAUDEOPS_DIR, ağ kapalı (`parity_searxng` `arama-ag-engeli`); tmux yalnız özel sunucu (geçici `TMUX_TMPDIR` + rastgele soket; `real_tmux`, `real_pane`), kapanış o soketle; çalıştırılan betikler alt süreçle (`write_exe`, `spawn_guard`); `/proc` sahte ve sıralı (`real_scan`); HTTP `127.0.0.1:0`; üretim kodu durum yolunu kendisi türetmez (`Paths`) | TAMAM |
| §3.18 uzak host sürüm / devre kesici / deploy (H10, H11) | crate uzak host çağırmaz | UYGULANMAZ. Not: bu dalın `py/` `fix:` commit'leri (61) canlıya web restart ve uzak deploy ile ulaşır (cops) |
| §3.19 ikili sürümü, canlı = main, restart'ta yarım iş (H11) | kütüphane crate, ikili yok | UYGULANMAZ (copsd). Bekçi iş parçacığı süreçle ölür (G9, bağlayan uç `join`) |
| §3.20 ölçüm / kanıt; `--dry-run` yan etkisiz; Python'a özellik yok (H21) | kuru kip: `real_fs::a_dry_run_build_issues_no_token_and_writes_nothing`, `real_scan::preview_scan_writes_nothing`, `resume::preview_writes_nothing_and_save_errors_surface`, `parity_g9` `{cli}-kuru`; daldaki `py/` commit'leri yalnız `fix:` (commit-gate); performans iddiası yok | TAMAM. AÇIK: spawn kancası kuru koşuda da çağrılır (G9 aday 6, Python gibi; "Bekleyen sorular" S3) |
| §2.5.1 sağlayıcı başına tek modül, if-zinciri yok (H4) | `claude.rs`, `agy.rs`, `codex.rs`, `copilot.rs`, `shell.rs`, `ucli.rs`; dağıtım tek `match Cli` (`Providers::build_inner_command`, `tui.rs` `Cli` yöntemleri); `tui::only_claude_touches_the_pane`, `parity_build` | TAMAM |
| §2.5.2 bayrak desteği `--help`'ten; desteklenmeyen eklenmez (H4) | `real/help.rs` (anahtar yol + mtime + boyut): `real_process::help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery`, `empty_failed_slow_huge_or_non_utf8_help_is_not_cached`; tanınmayan bayrak eklenmez + `ucli_flag_unsupported` (`parity_g8`), güvenlik izni bayrağı tanınmazsa spawn reddi (`Ctx::require`, `parity_ucli`) | TAMAM. AÇIK (cops kabulü bekliyor): ikilinin SÜRÜMÜ günlüğe yazılmaz. Ders maddesi istiyor; Python yazmıyor, eşlik için Python'a yeni günlük olayı (özellik) gerekir ve eklenmedi |
| §2.5.3 effort / model tek geçit; agy kademesi (H4) | `resolve_effort` tek giriş; agy `-high` kademesi `effort::split_tier`; `parity_model_effort`, `effort::tests::tiers_sorting_and_nearest_match_python`; ana oturum Sonnet + medium: rs/stew `prompts.rs::main_session_model_effort` (`cops-steward-core` `main_session_model_effort_vectors`) | TAMAM |
| §2.5.4 gerçek model kanıtı sağlayıcının kendi logundan (agy `Propagating ... label=`) (H4, H21) | crate agy günlüğü okumaz; Python'da bu okuma yalnız `review.py`de (review izi) | UYGULANMAZ (rs/rev) |
| §2.5.5 canlı model / effort jsonl'den (H3) | G3 `claude_transcript.rs`; `parity_transcript`; `claude_transcript::synthetic_and_unexpected_rows_do_not_hide_the_real_model` | TAMAM (sid'siz düşüş §3.1 AÇIK) |
| §2.5.6 kuru çalıştırma yan etkisiz, pay iadesi (H9, H21) | §3.20 testleri; `release` kuru ve hatalı başlatmada tam bir kez (`parity_g9` her vaka) | TAMAM (§3.20 AÇIK aday 6) |
| §2.5.7 spawn env beyaz liste, sırlar argv'de değil (H12, H17) | `spawn::filter_env_overrides` (`parity_spawn` `filter`, `kanca`), çocuk ortamı CLI kimlik değişkeni süpürme (`parity_g9` `ortam-supurme`, `real_tmux::spawn_direct_runs_inner_with_only_the_given_env_in_the_exact_session`); sır testleri §3.13 | TAMAM (27 Kas, TBD#401: tek atımlık çağrıda `api_key_env` beyaz listesi, `real_oneshot::only_known_key_env_names_start_a_child`, `parity_oneshot` `tbd401-`; çocuk ortamı Python gibi miras). AÇIK: kanca ortamı argv'de (§3.13). `endpoint` serbestliği TBD#401 kararının dışında kaldı ("Bekleyen sorular" altında not) |
| §2.5.8 cwd başına tek konuşma kimliği; kardeş oturumlar (H4, H7) | `parity_resume` `tutulan`, `agy-sahipli-*`, `devam-claude-kardes`, `devam-agy-onbellek-tutulan`; `parity_transcript` `istek-` (`sibling`, `onek`) | TAMAM. AÇIK: §3.1 (a), (c) |
| §2.5.9 trust / izin diyaloğu sürüm fixture'ları (H4) | diyalog işleyicisi (`trust_dialog.py`) bu crate'te değil; crate yalnız copilot `trustedFolders` düzenlemesini yazar (`parity_build` copilot vakaları) | UYGULANMAZ (T4/T10) |
| §2.5.10 başarısız spawn'da kayıt temizliği (H9, H2) | pay iadesi `parity_g9` `release`; tavan reddi `real_ledger::a_claude_service_build_is_refused_over_the_cap`; instance kaydı çağıranın | TAMAM (crate payı) |
| §2.5.11 kota / maliyet: önbellek token sayımı, kaynak yoksa "bilinmiyor" (H3, H21) | defter önbellek alanlarını sayar (`parity_ledger` `cache_read_*`), okunamayan defter sıfır değil RED (`an_unreadable_or_invalid_ledger_closes_an_open_cap`); kota ayrıştırıcıları eşleşme yoksa `None` (`parity_usage`) | TAMAM |
| R1 async içinde bloke eden iş | crate API'leri eşzamanlı (`Pane`, `Probe`, `ModelIo`, `CostGate`): async çağıran `spawn_blocking` ister (belgeli: `tui::Pane`, `real/pane.rs`); HTTP kendi runtime'ını async içinden de kurabilir: `real_http::it_can_be_called_from_inside_an_async_runtime` | TAMAM (bağlayan uçta `spawn_blocking` zorunlu) |
| R2 sınırlı kuyruk `try_send` ile düşürme | crate kuyruk kullanmaz | UYGULANMAZ |
| R3 `OnceCell` kurulumu asılınca her istek bozulur | `real/http.rs` TLS kökleri ve `SystemClock` başlangıcı `OnceLock`; kurulum G/Ç beklemez (yerel sertifika okuma, `Instant::now`) | TAMAM |
| R4 sır dosyası izin / symlink çalışma zamanında | `real_fs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape`, `secret_files_are_private_from_creation_and_links_are_not_followed`, `real_oneshot::a_fifo_key_file_or_index_is_refused_without_blocking`, `real_agy_store::a_symlinked_lock_file_is_refused_and_nothing_is_written` | TAMAM |
| R5 panik sonrası zehirli `Mutex` | `real_ledger::a_panic_while_reserving_does_not_poison_later_starts`; kilitler `PoisonError::into_inner` ile | TAMAM |
| R6 `cargo deny` / `cargo audit`, rev eşitliği | çalışma alanı düzeyi; `rust/Cargo.lock` commit'li | UYGULANMAZ (cops, çalışma alanı) |
| R7 Python'a yeni özellik yazmamak (commit-gate) | daldaki `py/` commit'leri 61 `fix:` + 1 `test:` (+ birleştirmeler); her `fix:` testiyle | TAMAM |

## EKSİK taşıma grupları
Satır sayıları ilk taşıma turundaki gruplamadır (işlev/atama satırı + test satırı); sonraki eşitleme bölümlerinin
satırları gruplara dağıtılmadı. Güncel toplamlar iki tablonun başında.

| Grup | Kapsam | işlev/atama | test | zorluk notu |
|---|---|---|---|---|
| G1 oturum kimliği ve devam | resume çözümü (claude/codex/agy/copilot transkript taraması, `_ids_held_by_others`), durdurulmuş oturum sid'i, canlı sid anlık görüntüsü/keşfi, agy sid yazımı, transkript yolu düşüşü | 0 (39 TAŞINDI) | 0 (24 TAŞINDI, 11 kapsam dışı) | bitti: `resume.rs`, `claude_resume.rs`, `codex_resume.rs`, `agy_resume.rs`, `copilot.rs`; parite `parity_resume`, `tests/resume.rs` |
| G2 sohbet geçmişi okuma | `last_exchange`/`full_history`/`extra_file_roots` (claude, codex, agy protobuf, copilot SQLite, ucli jsonl) | 0 (38 TAŞINDI) | 0 (17 TAŞINDI, 8 kapsam dışı) | bitti: `chat.rs`, parite `parity_chat` |
| G3 transkriptten model/effort ve önbellek sıcaklığı | `last_assistant_*`, `live_or_spawn_*`, `last_real_request_epoch`, TTL ve effort-önbellek kuralı | 0 (18 TAŞINDI) | 0 (23 TAŞINDI, 31 kapsam dışı) | bitti: `claude_transcript.rs`, parite `parity_transcript` |
| G4 TUI girdisi, canlı geçiş, devir kancaları | canlı model/effort değiştirme, başıboş diyalog, `prepare_input`, mod kalıpları, `wants_*` | 0 (37 TAŞINDI) | 0 (16 TAŞINDI, 1 kapsam dışı) | bitti: `tui.rs`, `real/pane.rs`; parite `parity_tui`, `tests/{tui,real_pane}.rs` |
| G5 kota/bağlam komutları ve ayrıştırma | `usage_*`, `context_*`, `parse_*` ve regex'leri | 0 (36 TAŞINDI) | 0 (9 TAŞINDI) | bitti: `usage.rs`, parite `parity_usage` |
| G6 canlı durum okuyucuları | ucli durum dosyası (`live_*`, faz, hata kayıtları), `background_work` (`bg_work`), codex/copilot bağlamı, meşgul kalıpları | 0 (39 TAŞINDI) | 0 (48 TAŞINDI, 2 kapsam dışı, 1 G2ye) | bitti: `live.rs`, `ucli_status.rs`, `bg_work.rs`, `pyjson.rs`; parite `parity_live` + `parity_bg_work` |
| G7 model kaynakları | `agy models`, codex/claude belge okuma, ucli `/models` HTTP, `service_models`, TTL önbellekleri | 0 (17 TAŞINDI) | 0 (11 TAŞINDI) | bitti: `model_sources.rs`, parite `parity_model_sources`, `tests/model_sources.rs`; gerçek `ModelIo`: `real/modelio.rs` (G8) |
| G8 `Probe` ve `Effect` gerçek uygulayıcısı | `real/` (dosya, süreç, HTTP, belge, günlük, token, MCP, checks, `agy_sids`), maliyet defteri (`cost.rs`, `real/ledger.rs`), SearXNG spawn yolu (`real/searxng.rs`) | 0 (53 TAŞINDI) | 0 (47 TAŞINDI, 5 kapsam dışı) | bitti: parite `parity_real`, `parity_ledger`, `parity_searxng`; `tests/real_{fs,process,http,ledger,searxng,fd,agy_store}.rs` |
| G9 spawn yürütme ve küresel yönerge | `spawn_session` akışı, gnome/headless, hayalet temizliği, fallback bekçisi, pencere açma, kanca/eklenti çağrıları, `sync_global_files` | 0 (15 TAŞINDI) | 0 (15 TAŞINDI) | bitti: `spawn_exec.rs`, `hooks.rs`, `real/{launch,routing_sync,runtime,tmux,scan}.rs`; parite `parity_g9`, `tests/{g9,real_tmux,real_scan}.rs` |
| G10 tek atımlık çağrı ve onay | `oneshot`, `ucli_chat_once`, onay kaydı (`ucli_approval` yazılan kısım), bütçe notu | 0 (26 TAŞINDI, 18 kapsam dışı) | 0 (41 TAŞINDI, 8 kapsam dışı) | bitti: `oneshot.rs`, `approval.rs`, `real/{oneshot,approval}.rs`; parite `parity_oneshot`, `tests/real_oneshot.rs` |
| G11 ayar ve panel okuyucu artıkları | hizmet `label`/`models`, `ucli_cost_config` tavan/kredi, `ucli_metrics.get_config`, `instructions_check` | 0 (8 TAŞINDI) | 0 (12 TAŞINDI) | bitti: `settings.rs`, `ucli.rs::instructions_check`, parite `parity_panel` + `parity_settings_pyfmt` `servis-*` |

## G4: TUI girdisi, canlı geçiş, devir kancaları

### Sahiplik
- Taşınan: `has_conversation`, `wants_handover_wrapup`, `wants_stuck_recovery`, `handover_{model,effort}_downgrade`,
  `apply_live_{model,effort}_switch`, `dismiss_stray_dialog`, `input_settle_delay`, `prepare_input`, `compact_command`,
  `mode_status_patterns`, `cyclable_modes` ve sabitleri.
- Taşınmayan (çağıranlar): `handover.py` politikası (`apply_handover_downgrades`, önbellek sıcaklığı kararı, mesaj gönderimi)
  ve `web._handover` / `_compact` / `_term_set_mode` / `_detect_mode_in_text` (T4/T2), `web_steward._send` ve ucli kutu
  denetimi (T10).

### Tasarım
- `tui.rs`: sağlayıcı dağıtımı `Cli` yöntemleri (`if cli == ..` zinciri çağıranda yok); claude dışı CLI'da canlı geçiş
  `Unsupported`, diyalog taraması boş.
- Dış olgular `Pane` arkasında: `send_text`, `send_key` (yalnız `Key::{Enter, Down}`), `capture` (ham ANSI), `monotonic`,
  `sleep`, `diag`. ANSI temizliği çekirdekte (`strip_ansi`): uygulayıcı unutamaz.
- Canlı geçiş Python `_Switch` döner; Rust `#[must_use] SwitchOutcome` (`Unsupported` = Python None, `Done`, `Busy`, `Draft`,
  `DialogOpen`, `Unreadable`, `SendFailed`, `Unconfirmed`); `safe_to_type()` = Python `handover._SWITCH_SAFE`.
  `dismiss_stray_dialog` `DismissOutcome` (`NotSeen`, `Closed`, `LeftOpen`).
- Diag olayları: `live_switch_not_done` (name, command, result, stage), `stray_dialog_left_open` (name, stage). `TmuxPane`
  günlük için `with_diag` ister.

### `Pane` sözleşmesi (gerçek uygulayıcı `real/pane.rs::TmuxPane`, 27 Kas; `cops-tmux` üstüne, o crate'e dokunulmadı)
| `Pane` | `TmuxPane` (`cops-tmux` çağrısı) | Zorunlu anlam |
|---|---|---|
| `send_text(ad, metin, settle)` | `Tmux::send_text(ad, metin, Duration, MaskGuard::RefuseMasked)`; `Ok` = true; `settle` negatif = 0, NaN/inf/sığmayan = false (hiçbir şey gönderilmez) | hedef `exact_target` (ön ek eşleşmesi yok); metin argv'ye girmez; gizli girdi ya da durumu bilinmeyen pane'e hiçbir şey; metin + tek Enter; süre `max(5, 5 + karakter/1500)` sn; yarım kalan gönderim = false (metin kutuda kalmış olabilir, çağıran yeniden göndermez) |
| `send_key(ad, tuş)` | `Tmux::send_special_key(ad, tuş.name(), MaskGuard::RefuseMasked)` | TAM ad; tek tuş; 5 sn; her hata ve zaman aşımı false. Python özel tuşta maske denetlemez: Rust daha sıkı (kapalı yön) |
| `capture(ad, satır)` | `Tmux::capture(ad, satır)` (ANSI korunur, `capture_plain` DEĞİL) | `-e -p -S -satır` (geçmişten `satır` + görünür alan); 5 sn; hata, oturum yok, UTF-8 olmayan çıktı = None; Python `text=True` `\r\n`/`\r`yi `\n` yapar (işaretler tek satırda, sonucu etkilemez); pane copy-mode'a sokulmaz |
| `diag` | `DiagSink` (`TmuxPane::with_diag`) | en iyi çaba; verilmezse olay düşer, sonuç yine tipli döner |
| `monotonic` / `sleep` | `Instant` / `thread::sleep` | geri gitmez; `sleep(s)` saati en az `s` ilerletir (döngülerin bitişi buna bağlı). Yöntemler bloklayıcıdır (async'te `spawn_blocking`) |

- Hiçbir `Pane` yöntemi panik atmaz; hata değeri (false / None) döner.
- Süre sınırı çağrıların toplamı değil, döngü başındaki saattir (Python gibi): son yakalama ve son bakış sınırı en çok iki
  tmux zaman aşımı kadar aşabilir.
- `tui::strip_ansi` = `cops_tmux::strip_ansi` (tek kaynak; OSC `ESC \` bitişi dahil).
- Sınayan (yalıtılmış tmux sunucusu, `tests/real_pane.rs` 10): tam hedef ve ön ek (`prefix_name_never_reaches_another_session`),
  metin argv'de değil (araya konan sahte tmux argv'yi kaydeder: `text_never_appears_in_tmux_argv`), maske
  (`masked_pane_gets_no_command_and_no_enter`), 5 sn zaman aşımı (hiç dönmeyen sahte tmux:
  `hung_tmux_times_out_to_false_and_none`), ANSI korunan yakalama Python `tmux_capture` ile aynı ve copy-mode'a girilmez
  (`capture_matches_python_and_keeps_ansi`, her senaryoda `#{pane_in_mode}` = 0), Python `ClaudeProvider` ile aynı bayt
  (`*_like_python`, `no_dialog_means_no_keys_on_either_side`). Copy-mode kuralı: `TmuxPane` hiçbir zaman `copy-mode`
  çağırmaz (argv kaydında da yok).

### Mod kalıpları (tüketici notu, T2/T4)
`mode_status_patterns` Python `re` metnini ve sözlük sırasını verir; Python `IGNORECASE` ile ANSI'si temizlenmiş son 8 dolu
satırda ilk eşleşeni seçer. Rust'ta `(?i)` `İ`/`ı`yi `i` saymaz, `\s` U+001C..U+001F'i boşluk saymaz.

### Bilinen ayrışmalar (2; testte `g4-mod-sapma-`)
Yukarıdaki iki motor farkı (`g4-mod-sapma-noktali-i`, `g4-mod-sapma-bosluk`). Canlı geçiş ve girdi hazırlamada kayıtlı
ayrışma yok.

### Python hatası (27 Kas iki tarafta DÜZELDİ; `fix:` + `py/tests/test_rsprov_g4_dismiss.py`)
- `dismiss_stray_dialog`: `Down` gönderilemezse de Enter basılıyordu; seçili düğme "Yes, switch" olduğundan reddedilmek
  istenen model değişikliği onaylanıyordu. Artık `Down` başarısızsa tuş yok (diyalog zararsız kalıntı). Yalnız hata
  yolunda davranış değişir.

### TBD#399: canlı geçişte altı açık (sahip onayı (a), 27 Kas; iki tarafta DÜZELDİ). Kural: emin olunamayan ekranda tuş yok
Eski aday listesinin (1-6) tamamı. Python testleri `py/tests/test_tbd399_{live_switch,control_chars}.py`, Rust `tests/tui.rs`,
`tests/real_pane.rs`, parite `g4-pane-*` ve `g4-ekran-*`, `cops-tmux` parite (`writes`/sahte tmux).

| # | Açık | Davranış şimdi |
|---|---|---|
| 1 | eski sonuç satırı yeni isteğin sonucu sayılıyordu | komuttan önceki yakalamadaki (200 satır) işaret sayısı tabandır; yalnız sayı artarsa VE giriş kutusu hazırsa `Done` |
| 2 | diyalog başlığı ekranın her yerinde aranıyordu | yalnız ekranın SONUNDAKİ diyalog: ardışık `1. Yes, switch to X` / `2. No, go back`, tam birinde `❯`, altında en çok 2 yardım satırı, üstünde (15 satır içinde) tam başlık satırı; onay için ayrıca başlık = gönderilen komut, X = hedef, imleç "Yes"te |
| 3 | taslak varken `/model` `/effort` gidiyordu | komut yalnız boş (soluk öneri sayılmaz), altında menü/yardım satırı olmayan kutuya; taslak `Draft`, açık geçiş diyaloğu `DialogOpen`, kutu yok `Unreadable`, tur sürüyorsa (`esc to interrupt`) `Busy`: hiçbiri bir şey göndermez |
| 4 | geç açılan effort diyaloğu kapatılmıyordu | `dismiss_stray_dialog` iki başlığı da reddeder; güvenli bitmeyen geçişte çağıran da onu koşar |
| 5 | onay Enter'ının sonucuna bakılmıyordu | tuş başarısız = hemen `Unconfirmed`; ikinci Enter yok; `Down` sonrası ekran yeniden okunur (imleç "No"da değilse Enter yok); reddetme sonrası kapandı denetimi |
| 6 | denetim karakterleri aynen, satır sonu tek Enter | `tmux_send_keys` / `cops-tmux` `send_text`: sekme/satır sonu dışındaki C0, DEL, C1 atılır; boş olmayan metinden yalnız boşluk kalırsa hiçbir şey gönderilmez; `""` bilinçli Enter olarak kalır; ucli katlaması boş metne inmez |

- Çağıranlar: `handover.apply_handover_downgrades` `blocked` doldurur (model adımı güvenli değilse effort denenmez);
  `web._handover` `handover_switch_blocked` hatası, `handover_faz1` `failed-switch`; ikisi de mesaj göndermez. `Busy`de
  mesaj gider. Bu politika Python'da; Rust'ta çağıran henüz yok (T4): `safe_to_type()` şartı bağlayan uçta uygulanmalı.
- TBD#411 (sahip cevabı (a), 27 Kas): tur sürerken `/model` ve `/effort` gönderilmez, devir mesajı gider; kod değişmez.
- Doğrulanamayan varsayımlar (gerçek claude ekranı üretilmedi): diyalog metinleri 2.1.332 ikilisindeki bileşenden okundu,
  satır düzeni (numaralı iki seçenek, `❯`, alt yardım satırı "Enter to confirm / Esc to cancel", çerçeve) depodaki izin ve
  güven diyaloğu örneklerine benzetildi; hedef adının seçenek metninde geçtiği; yardım satırı başka ise diyalog TANINMAZ
  (kapalı yön: tuş yok, devir `unconfirmed` ile durur). Kutuda taslak varken açılan diyalog numarasızdır (ikili): tanınmaz.
  Giriş kutusunda imleç ters renkli bir yer tutucu harfi çizilirse taslak sayılır (mevcut `input_box` kuralı).
- Bilinen sınırlar: 200 satırlık pencerenin üstünden düşen eski işaret yenisini gizler (`Unconfirmed`); kutunun altında 12'den
  çok dolu satır `Unreadable`; yakalama ile tuş arasındaki yarış kapatılamaz.

### Test edilemeyenler
Gerçek claude diyaloğu (gerçek tmux artık `tests/real_pane.rs`te, sahte claude TUI'siyle; "Change effort level?" ve
`Down`+Enter'ın 2. seçeneği seçtiği Python'da da canlı doğrulanmamış).

### Ders listesi (`docs/rust-lessons-from-python.md`), G4 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G6: canlı durum okuyucuları

### Tasarım ve bağımlılıklar
- Modüller: `bg_work.rs` (saf), `live.rs` (`LiveProbe`, `Live`, sağlayıcı dağıtımı, codex/copilot bağlamı), `ucli_status.rs`,
  `pyjson.rs` (Python `json.loads`/`str`/`dumps` anlamında salt okur ayrıştırıcı). Crate G/Ç yapmaz; SQL metni crate'te
  (`COPILOT_CONTEXT_SQL`), sorguyu çağıran koşar. `rusqlite` yalnız dev bağımlılığı.
- `LiveProbe`un gerçek uygulaması `real/probe.rs` (G8). Sözleşme: yalnız normal dosya (FIFO/aygıt açılışta bloklamasın), `max` aşan dosya
  None, kuyruk okuması en çok `max` bayt, SQLite `mode=ro` + 2 sn meşgul beklemesi, bağlantı her sorguda kapanır.
- G1 bağımlılığı kapandı: transkript, rollout ve copilot resume çözümü crate içinde (`Live::{jsonl_path_for, codex_rollout_path,
  resolve_resume_id}`); `rs/proc` `transcript.rs::jsonl_path_for` yalnız tam sid eşler (düşüş yok), birleştirmede karıştırılmamalı.
- Birleştirmede tekleştirilecek: `pyjson.rs` ile `rs/state` `cops-state::json::Json`; `bg_work.rs::iso_epoch` ile `rs/state`
  `pytime.rs`. İkisi de bu dalda olmadığı için bağlanmadı.
- `Clock {now, utc_offset_secs}` çağırandan gelir. Saat dilimsiz damga sabit farkla yorumlanır (yaz saati geçişi yok;
  Claude ve codex damgaları `Z` taşır).
- Tablo dışında kalıp taşınanlar: `screen_bg_work`, `transcript_pending`, `_epoch` (`iso_epoch`), `chat_session_dir`
  (`chat_session_dirs()[0]`; ayrı işlev yok).
- Taşınmayan: `web_steward` durum dosyası kullanımı ve panel sarmalayıcıları (T1/T10); `quota_equivalent_tokens`,
  `usage_warn_level`, `archive_session_files`, `read_chat_history` (bu grupta değil).

### Bilinen ayrışmalar (5; testte `known(`)
- `live` 5: 512'den derin durum dosyası; u64/i64'e sığmayan sayaç ve zaman (doygun) (3); 8 MiB üstü durum dosyası.
- Testsiz farklar: 64 MiB üstü hata kaydı okunmaz; eşlenmemiş vekil kaçışı çıktıda U+FFFD olur (Python vekili taşır);
  UTF-8 olmayan dosya adları listelenmeyebilir (oturum adıyla eşleşemez); 2^53 mikro saniyeyi aşan yıllarda (~2255 sonrası)
  damga son bitte ayrışabilir; 512-1000 arası iç içe transkript satırını Python okur, Rust atlar.

### Python hataları (26 Kas gece iki tarafta DÜZELDİ; her biri ayrı `fix:` + `py/tests/test_rsprov_live_readers.py`)
1. `bg_work`: beklenmedik yapıdaki tek satır/blok yalnız atlanır (parite `bg-sekil-`).
2. `failed_turn_records`: `isdecimal`; üst simge rakamlı ad yalnız kendisi atlanır (`hata-ust-simge`).
3. `read_status_file` ve hata kaydı okuma: dev sayı ve aşırı derin yapı "okunamadı" (`durum-dev-sayi`).
4. codex `live_context`: `true` ve negatif sayaç taşıyan olay atlanır, aşırı derin satır da (`codex-ctx-bool`, `-negatif`).
5. copilot `live_context`: sayıya çevrilemeyen hücre None (`copilot-hucre-metin-harf`, `-sonsuz`).
6. `bg_work`: liste biçimli araç sonucunda yalnız metin blokları, gerçek satır sonlarıyla taranır (`bg-transkript-`).

### Ders listesi (`docs/rust-lessons-from-python.md`), G6 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G2: sohbet geçmişi okuma

### Sahiplik
26 Kas'ta bakıldı (`origin/rs/*` ve `main`): kod hiçbir dalda yoktu. `rs/proc` `docs/rs-proc.md` bu işlevleri "VARSAYIM, cops onayı bekler"
diye T1'e yazmıştı; burada taşındı. Birleştirmede `rs/proc` `parity/mapping.py` `CHAT` satırlarından `last_exchange`/`full_history`
tarafı bu ize yönlendirilmeli (`sid_for_stopped_session` G1'de taşındı).

### Tasarım ve bağımlılıklar
- Modül `chat.rs`; giriş `Live::{last_exchange, full_history, last_message_role, extra_file_roots, read_chat_history}`.
  Satır tipi `ChatTurn { role: Py, text: Py }`: ucli `role`/`content` değerini, copilot SQLite hücresini Python gibi olduğu gibi geçirir.
- `LiveProbe`a eklenenler (gerçek uygulama `real/`, G8): `sqlite_rows` (satır satır ziyaretçi; hata `false`, önceki satırlar verilmiş kalır;
  yol URI diye ayrıştırılmaz), `claude_project_dir` (`_encode_cwd`: `rs/proc` `transcript.rs::encode_cwd`), `agy_resume_id` (G1 ile crate içine alındı).
  Transkript, rollout ve resume çözümü crate içinde (G1); paritede gerçek dosyalardan sınanır.
- Transkript `read_bytes(path, u64::MAX)` ile BÜTÜN okunur (Python da sınırsız). Satırlar tek tek ayrıştırılıp atılır; son çift
  sondan tembel aranır. Boyut sınırı konmadı (konursa Python'dan sapma olur); bellek dosya boyutu kadar.
- Taşınmayan: `web._term_chat` bağlaması (T1), `io_providers`.

### Bilinen ayrışmalar (2; testte `chat-...sapma-vekil`, Rust sonucu `expect` ile ayrıca doğrulanır)
- claude 1 ve ucli 1: eşlenmemiş vekil (Python vekili taşır, Rust U+FFFD).
- Testsiz fark: 512-1000 arası iç içe JSON satırı Python'da okunur, Rust atlar (ucli'de okunamadı sayar).

### Python hataları (26 Kas gece iki tarafta DÜZELDİ; `py/tests/test_rsprov_{chat,sqlite}_readers.py`)
1. claude/codex'te bozuk bayt yalnız kendi satırını atlatır; ucli'de tamamlanmış satırdaki bozuk bayt dosyayı okunamaz yapar.
   Son dolu satır okunamıyorsa (bozuk bayt ya da nesne olmayan JSON) `last_message_role` None: takılma tespiti öncekine bakıp
   oturumu yeniden açmaz (parite `rol-`).
2. claude/codex: nesne olmayan satır, `message`/`payload`/`compactMetadata`, metin olmayan `text`, aşırı derin ya da dev sayılı
   satır yalnız atlanır. Son asistan satırının `message`i bozuksa yanıt "" (önceki yanıt güncel diye sunulmaz). ucli'de aşırı
   derin ya da dev sayılı satır None (`sekil-`).
3. agy ve copilot SQLite URI'sinde yol kaçışlanır (`base._ro_sqlite_uri`; parite `agy-uri-`, copilot yalnız Python testi).
4. agy: yalnız BLOB yük çekilir; bozuk metin hücresi ne önceki satırı ne tam geçmişi düşürür (`utf8-hucre`).
5. claude `last_exchange`: sıkıştırma özeti (`isCompactSummary`) kullanıcı mesajı sayılmaz (`ozet-`). KAPANDI (TBD#395
   soru 2, sahip adına cops 27 Kas: aynen kalsın): son asistan satırı yalnız `tool_use` ise yanıt "" döner (iki tarafta);
   önceki metne bakmak değnekçinin işaret okumasını ve devir teslimini değiştirirdi.
6. ucli: yarım yazılmış son satır (satır sonu yok, ayrışmıyor) atlanır; o sırada `last_message_role` eskisi gibi None
   (`yarim-son-`).
7. copilot BLOB hücre: geçerli UTF-8 ise metin, değilse "" (`blob`, `blob-bozuk`).

### Ders listesi (`docs/rust-lessons-from-python.md`), G2 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G3: transkriptten model/effort ve önbellek sıcaklığı

### Sahiplik
26 Kas'ta `git fetch` sonrası `origin/rs/*` ve `main` tarandı: bu işlevler hiçbir dalda yoktu. `rs/proc` `parity/mapping.py`
onları `oos` (T1/T4) diye işaretliyor, `rs/proc` `usage.rs` yalnız kullanım toplamı okuyor. Birleştirmede o `oos` satırları
bu ize yönlendirilmeli.

### Tasarım ve bağımlılıklar
- Modül `claude_transcript.rs`: `Cli::{prompt_cache_ttl_seconds, effort_switch_keeps_cache}`, `Live::{last_assistant_model,
  last_assistant_effort, last_real_request_epoch, live_or_spawn_model, live_or_spawn_effort, last_request_epoch}`.
  `_row_epoch` = `bg_work::iso_epoch` (ayrı kopya yok).
- Pencere Python'la aynı: 64 KiB, x4, en çok 4 MiB; boyut bir kez okunur (`Probe::file_size`), her adım `[boyut-pencere, boyut)`.
- `LiveProbe`a eklenen (gerçek uygulama `real/`, G8): `read_range(path, start, len)` (yalnız normal dosya; hata None).
- `live_or_spawn_*` transkript yolunu `Live::jsonl_path_for`dan alır (G1; "cwd'deki en yeni" düşüşü Python gibi).
  `last_request_epoch` düşüş kullanmaz, yalnız tam `<sid>.jsonl`; pid kimliği `Live::session_file_sid`.
- Saat dilimsiz damga `Clock::utc_offset_secs` ile yorumlanır (G6 ile aynı sınır).
- Taşınmayan: `web._live_model_effort` önbelleği ve
  `_live_model`/`_live_effort` uçları (T1: "yalnız tam `<sid>.jsonl`, yalnız süreç başlangıcından sonrası" kuralını T1
  uygulamalı); `handover` politikası (T4); `handover_*_downgrade` ve canlı geçiş (G4, `tui.rs`); `web_steward.context_tokens_for`
  (T10; `rs/stew` tablosunda EKSİK, henüz kimse taşımadı).

### Bilinen ayrışmalar (3; testte `known(`, Rust sonucu çoğunda `expect*` ile ayrıca doğrulanır)
- 512'den derin satır, eşlenmemiş vekil, 1. yılın ilk günü dilimsiz damga (1'er).
- Testsiz fark: i128'e sığmayan birbirini götüren token sayaçları (doygun toplam); yaz saati geçişli dilimsiz damga.

### Python hatası şüpheleri (1, 2, 3, 5, 7 DÜZELDİ; 4 ve 6 sahipte: "Bekleyen sorular" S1, S2)
1. DÜZELDİ (TBD#386): `last_assistant_model` `<synthetic>` yer tutucusunu atlar (`test_rsprov_model_reader.py`, parite
   `esit-sentetik-yalniz-yeni`, `canli-sentetik`).
2. DÜZELDİ (TBD#386): `_last_assistant_value` nesne olmayan satırı, model okuyucu nesne olmayan `message`i atlar (`esit-`).
3. DÜZELDİ (27 Kas, `fdfa1f91`): metin olmayan model okuyucuda atlanır (`test_rsprov_g3_fixes.py`, parite `esit-model-`).
4. SAHİPTE (S1). `live_or_spawn_*` sid yoksa (dosyası olmayan sid'de DÜŞMEZ, TBD#365) cwd'deki EN YENİ transkripti okur: ortak dizindeki kardeş oturumun
   modeli/effort'u devir kararına ve takılan oturumun yeniden açılışına girer (aynı modüldeki `last_request_epoch` bu
   düşüşü bilerek reddediyor). G1 birebir taşıdı (düşüş korundu).
5. DÜZELDİ (27 Kas, `fdfa1f91` + `37fd9676`): `last_assistant_model`/`_effort` alt ajan (`isSidechain`) satırını atlar
   (parite `esit-alt-ajan-`). Güncel claude'un ana dosyaya bu satırı yazıp yazmadığı ölçülmedi (canlı transkript
   okunmadı); yazmıyorsa davranış değişmez.
6. SAHİPTE (S2). Effort ayrı taranır: en son satır effort taşımıyorsa (ör. effort desteklemeyen modele geçiş) eski modelin effort'u
   döner. Rust aynı (parite `effort-eski-satirda`).
7. DÜZELDİ (27 Kas, G1 9. madde ile): `last_request_epoch`/`jsonl_path_for` aşırı uzun sid'i yok sayar (parite
   `transkript-sapma-uzun-sid` eşit); `/` ya da NUL taşıyan aday proje dizininin dışını açmaz (`istek-mutlak`).

### Ders listesi (`docs/rust-lessons-from-python.md`), G3 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G7: model kaynakları

### Sahiplik
26 Kas'ta `git fetch` sonrası `origin/rs/*` ve `main` bu işlev adlarıyla (`rust/**/*.rs`) tarandı: bu dal dışında kod yok.
`claude_models` belgesini DB'den okuma rs/state'in `statedocs`unda (bu dalda yok).

### Tasarım ve bağımlılıklar
- `model_sources.rs`: `ModelIo` (G/Ç sınırı: `monotonic_secs`, `wall_secs`, `claude_models_doc`, `read_file`, `run_stdout`,
  `http_get`, `spawn_background`), `RunRequest`, `HttpRequest`, `SecretValue`, `ModelSources` (dört önbelleğin sahibi,
  `catalog(cli, ..)` ile `ModelCatalog` doldurur). Süreç başına TEK `ModelSources` kurulmalı (Python önbellekleri modül/sağlayıcı
  tekilidir).
- Sağlayıcıya özgü kural kendi modülünde: `agy::ModelsCache` (TTL 300 sn; soğukta bloklayan, bayat ama doluysa eskiyi döndürüp
  `agy-models-refresh` arka plan işi), `codex::ModelsCache` (TTL 300 sn, eşzamanlı okuma, boş/bozuk belge eski listeyi bırakır),
  `ucli::{fetch_live_models, LiveCache}` (TTL 300 sn; liste yoksa süre beklemeden çeker; başarısızlık eski listeyi ve yetenekleri
  bırakır), `ucli_opts::ServiceModelsCache` (dolu 86400 sn, boş 60 sn, `wall_secs`; başarısızlık eski listeyi EZER, Python gibi).
- Kilit hiçbir G/Ç sırasında tutulmaz; deneme anı çekimden ÖNCE damgalanır (Python gibi).
- `ModelCatalog`a `codex_choices` eklendi: Python'da codex listesi önbellekli, `model_effort_levels` ise her çağrıda dosyayı okur.
- Anahtar yalnız `HttpRequest.headers`ta (`SecretValue`, `Debug` maskeli; URL'deki `kullanıcı:parola@` de maskelenir); hata metni
  yok (her hata `None`); argv, `Effect`, `Diag` yoluna girmez. Anahtarsız ya da başlık olamayan anahtarla istek yapılmaz.
- Zaman aşımı ve okuma üst sınırı istekte taşınır: agy 5 sn / 1 MiB, ucli 5 sn / 8 MiB, hizmet 8 sn / 8 MiB, codex belgesi 8 MiB.
  Boyutu aşan yanıtı crate ayrıca yok sayar.
- G7'de bağımlılık eklenmedi; gerçek `ModelIo` ve G8 sözleşmesi (TOPLAM süre, kill+wait, sınırlı boru, boş stdin, çıkış koduna
  bakmama, yalnız 2xx gövdesi, latin-1 başlık baytı, `*_proxy` ortamı, `CLOCK_MONOTONIC`, normal dosya) G8'de uygulandı.
- HTTP yönlendirmesi: iki tarafta da İZLENMEZ (TBD#389).

### Bilinen ayrışmalar (3; testte `diverges(`, Rust dönüşü `expect` ile ayrıca doğrulanır; 27 Kas'ta 4'ü iki tarafta düzeldi, `fixed(`)
- ucli: UTF-16 gövde (Rust yalnız UTF-8, BOM kabul; Rust'ta başarısız çekim + `models_fetch_failed`).
- hizmet: eşlenmemiş vekil (U+FFFD), 512'den derin gövde (Rust başarısız çekim: boş liste + günlük).
- Testsiz ya da yalnız birim testli farklar: okuma üst sınırları (Python sınırsız); süre toplam (Python soket işlemi başına);
  `catalog` effort'u kimliğinde taşıyan agy modeli ve ucli `reasoning_effort=off` için de listeyi ister; katlanmış başlık
  (`\r\n `) reddedilir; agy stderr'i UTF-8 değilse Python listeyi atar, Rust stderr'e bakmaz; arka plan işi başlatılamazsa Python
  `RuntimeError`, Rust eski liste; arka plan yenilemesi çok hızlı biterse Python aynı çağrıda yeni listeyi döndürebilir, Rust hep
  eskiyi; `/models` ve codex belgesinde `NaN`/`Infinity` değer `null` olur (NaN `priority` codex belgesini kullanılmaz kılabilir,
  NaN `id` atlanır), 64 bite sığmayan sayı yaklaşık float.

### Python hataları (27 Kas kalıcı kurala göre iki tarafta; `py/tests/test_rsprov_g7_fixes.py`, Rust `tests/model_sources.rs`, parite `parity_model_sources`)
Numara: bu listenin eski sırası (TODO'daki G7 1-8 karşılığı parantezde).
1. DÜZELDİ (TODO 1): agy ve codex `_cache_ts` başlangıcı `None` (Rust `Option<f64>`): açılıştan hemen sonra da çekilir
   (`models_are_fetched_right_after_boot`; parite `src-agy-acilis`, `src-codex-acilis` eşit).
2. DÜZELDİ (TODO 2): codex `model_choices`/`model_effort_levels` UTF-8 olmayan belgede eski listeyi tutar (parite
   `src-codex-sapma-utf8` artık eşit).
3. DÜZELDİ: ucli `/models` metin olmayan kimlik (sayı, liste) atlanır; liste kimlik + `capabilities` `TypeError` vermez
   (parite `src-ucli-sapma-liste-id`, `live-liste-id`).
4. DÜZELDİ (TODO 3): ucli `/models` çok derin gövde başarısız çekim (yedek liste; `src-ucli-sapma-derin` eşit).
5. DÜZELDİ (TBD#389): iki `/models` isteği 3xx'i izlemez (`test_rsprov_models_redirect.py`).
6. DÜZELDİ (TODO 4): `service_models` başarısız çekim eski DOLU listeyi ezmez (o döner, yeniden deneme 60 sn sonra); JSON
   olmayan gövde ya da dizi olmayan `data` artık boş liste değil başarısız çekim (`_parse_service_models`, Rust
   `parse_service_models -> Option`).
7. DÜZELDİ (TODO 5): `service_models` önbelleği hizmet + uç nokta + anahtar özetine (SHA-256) bağlı; anahtar saklanmaz
   (`service_models_keep_the_good_list_and_follow_the_key`).
8. DÜZELDİ (TODO 6; 27 Kas, `21f44eb6` + `066dd469`): sıfır olmayan çıkışlı `agy models` başarısız çekim (eski liste kalır,
   `models_fetch_failed`). ÖLÇÜLDÜ (agy 1.5.18, kopya ikili, ayrı ağ/süreç/bağlama ad uzayı, gizli ev dizini, oturumsuz, iki
   koşu): çıkış 1, stdout boş, stderr "Please sign in to view available models" (görünen davranış değişmiyor, yalnız günlük).
   Ölçülmedi: oturum açıkken başarılı koşunun çıkış kodu (0 varsayıldı; ağ ister).
9. DÜZELDİ (TODO 7): agy soğuk çekim sürerken ikinci çağıran boş liste almaz, çekimin bitmesini bekler (çekim kilidi durum
   kilidi altında alınır; `a_second_caller_waits_for_the_cold_agy_fetch`, `test_second_caller_waits_for_the_cold_fetch`).
10. DÜZELDİ (TODO 8): ucli sayı kimlik listeye girmez (3. madde ile aynı kural; Rust metne çevirmiyor artık).
- Yutulan çekim hatası artık günlükte: agy/ucli/hizmet çekimi başarısızsa `models_fetch_failed` (`source`: `agy`, `ucli`
  ya da hizmet kimliği; anahtar ve adres yok). Rust `ModelIo::diag` (gerçek: `RealModelIo::with_diag`). codex belgesinin
  yokluğu olağan olduğundan günlüğe yazılmaz.

### Ders listesi (`docs/rust-lessons-from-python.md`), G7 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G1: oturum kimliği ve devam

### Sahiplik
26 Kas'ta `git fetch` sonrası `origin/rs/*` ve `main` bu işlev adlarıyla (`rust/**/*.rs`) tarandı: yalnız `rs/proc`
`transcript.rs::jsonl_path_for` var (tam sid eşleşmesi, düşüş yok). `rs/proc` `extract_info` agy kimliğini yalnız döndürür
(`AgyState::learned`), yazmaz: `remember_agy_sid` + `sid_claimed_by_other` burada, çağrı birleştirmede bağlanacak.

### Tasarım ve bağımlılıklar
- Modüller: `resume.rs` (dağıtım, `ids_held_by_others`, `head_lines`, `same_path`, zaman sıralaması), `claude_resume.rs`,
  `codex_resume.rs`, `agy_resume.rs`, copilot `copilot.rs`te. Dağıtımda `_` kolu yok.
- `LiveProbe`tan beş sahte yöntem kalktı (`claude_session_sid`, `claude_transcript`, `codex_rollout`, `copilot_resume_id`,
  `agy_resume_id`); yerine `stat`, `proc_stat`, `current_dir`, `agy_sids_doc` geldi. `claude_project_dir` kaldı (rs/proc
  `encode_cwd`). Sohbet, canlı okuyucu ve transkript parite aileleri artık gerçek çözümü kullanır.
- `LiveProbe` sözleşmesi (uygulaması G8, `real/`): `list_dir` dizin okuma sırasını korur (eşit zamanda seçim sıraya bağlı); `stat` symlink izler,
  `mtime_ns`; `proc_stat` yalnız `/proc/<pid>/stat`; `read_range` yalnız normal dosya.
- Başlık önbelleği `MetaCache` (imza `(mtime_ns, boyut)`, 20000 girdi) çağıranındır; süreç başına TEK örnek. Kilit okuma
  sırasında tutulmaz.
- `agy_sids` yazımı `AgySidStore {load, locked, save}`: kilitsiz ucuz karşılaştırma, kilit altında yeniden okuma, aynı değer
  yazılmaz, `preview` yazmaz. Gerçek uygulama (claudeops.db + ayna, `flock`, atomik yazım) YOK: rs/state `statedocs`.
- `ids_held_by_others(name, live)`: süreç taraması girdidir (`None` = tarama patladı = boş küme). Yeni bağımlılık yok.
- Okuma sınırları: baş satırlar 8 MiB (64 KiB parçalarla, yarım satır atılır), stub taraması 8 MiB, `sessions/<pid>.json`
  1 MiB, agy cwd önbelleği 8 MiB.

### Bilinen ayrışmalar (1; testte `devam-sapma-meta-derin`)
- claude: 512'den derin başlık satırı (Python okur, Rust atlar). 27 Kas: eski 13 ayrışma (codex 7, agy 2, claude 3,
  copilot 1) iki tarafta düzeldi; vakalar `devam-sapma-*` adıyla `fixed(` (Python ile eşit + Rust `expect`) kaldı.
- Testsiz farklar: okuma sınırları (Python sınırsız); UTF-8 olmayan dosya adları listelenmeyebilir;
  `sid_for_stopped_session`/`session_file_sid` imzaları tipli (metin pid yok).

### Python hataları (27 Kas kalıcı kurala göre iki tarafta DÜZELDİ, 2 ve 3 hariç; `py/tests/test_rsprov_g1_fixes.py`, düzeltmeden önce 17 testin 15'i kırmızı; Rust parite `parity_resume`)
1. codex `_session_meta`: bozuk/UTF-8 olmayan/nesne olmayan ilk satır ya da `payload` o dosyayı atlatır, aramayı düşürmez.
   Yalnız İLK satır çözülür (`surrogateescape` + `encode`; metin kipi tamponun tamamını çözüp sonraki satırın bozuk baytında
   düşüyordu).
2. UYGULANMADI (geri alındı): codex `resolve_resume_id`te en yeni uyan dosyada kimlik yoksa tarama orada biter, sonuç
   yok (taze konuşma). Neden: eskiye bakmak hangi konuşmanın devam edeceğini değiştiriyor; belirsizlikte reddet.
3. UYGULANMADI (geri alındı): copilot `resolve_resume_id`te en yeni uyan satırın kimliği boş/NULL ise sonuç yok, eski
   oturuma bakılmaz. Neden: 2 ile aynı.
4. codex `_rollout_path`: `sid` dosya adının sonundaki kimlikle TAM eşleşmeli (`_rollout_sid_matches`; kimliksiz adda
   `{sid}.jsonl` ya da `-{sid}.jsonl`); kısmi kimlik, joker, `/` taşıyan `sid` başka konuşmanın dosyasını vermez (Rust da).
5. agy `resolve_resume_id`: cwd önbelleğindeki kimlik BAŞKA ada öğrenilmişse alınmaz (reddeden yön; Rust da).
6. agy `resolve_resume_id`: öğrenilen kimlik yalnız konuşma veritabanı duruyorsa döner; yoksa önbelleğe düşülür (5. madde
   süzgeciyle; Rust da).
7. agy `_remember_agy_sid`: var olan belge okunamıyor, UTF-8/JSON değil ya da nesne değilse HİÇ yazılmaz, `agy_sids_unreadable`
   (`name`) günlüğü (`_load_agy_sids_for_write`; Rust `AgySidStore::load_for_write`, `AGY_SIDS_UNREADABLE`, `ProcScan`
   günlüğü). db kipi: iki taraf da DB'den okuyup DB'ye yazar (`StateDocStore`, `parity_docs`).
8. agy cwd önbelleği UTF-8 değilse "önbellek yok" (`resolve_resume_id` ve `extract_info`).
9. claude `resolve_resume_id`/`find_latest_jsonl`: proje yolu dosya ya da okunamıyorsa "yok"; `jsonl_path_for` aşırı uzun
   `sid`de "yok".
10. `session_file_sid`: `pid: Infinity` "yok" (`OverflowError` yakalanır).
11. Metin olmayan kimlik (codex, copilot, agy öğrenilen) döndürülmez: codex/copilot'ta sonuç yok (eskiye düşme yok; 2,
    3), agy'de 6. maddenin süzgeciyle önbelleğe düşülür.

### Ders listesi (`docs/rust-lessons-from-python.md`), G1 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G8 (birinci parça): gerçek uygulayıcılar

### Sahiplik
26 Kas'ta `git fetch` sonrası `origin/rs/*` ve `main` bu işlev adlarıyla tarandı: `rs/state`te `atomic_write_*`, `FileLock`,
`StateDocs` var (bu dalda yok, kopyalanmadı); kalan işlevler hiçbir dalda yoktu.

### Tasarım ve bağımlılıklar
- `real/` modülleri: `probe` (`RealProbe`: `Probe` + `LiveProbe`), `effects` (`apply`, `apply_all`, `atomic_write_text`,
  `makedirs`), `fsio`, `pathexec` (`which`, `realpath`, `path_executables`, `rust_toolchain`), `process`, `help`, `sqlite`,
  `lock`, `docs` (`DocStore`, `StateDocStore`, `DocAgySidStore`), `diaglog`, `agents`, `checks`, `modelio`, `http`, `proxy`, `env`,
  `oserr`.
- Dışarıdan verilen sınırlar (`RealDeps`): `DocStore`, `ProjectDirs` (rs/proc `encode_cwd`), `CostGate`, `SearchUrl`, paylaşılan
  `HelpCache`, panel portu. Gerçek `CostGate` = `ledger::CostLedger`, gerçek `SearchUrl` = `searxng::ManagedSearch` (ikinci
  parça); yer tutucular (`FailClosedCostGate`, `NoSearch`) kaldırıldı.
- Yazım güvenliği: sır dosyası baştan 0600, `O_NOFOLLOW`, `O_NONBLOCK` + normal dosya denetimi; var olan dosyanın izni içerik
  yazılmadan 0600'e çekilir. Atomik yazım: benzersiz geçici dosya `O_EXCL|O_NOFOLLOW`, dosya + dizin fsync.
- Okuma: yalnız normal dosya (açılış `O_NONBLOCK`, tür tanıtıcı üzerinden). Sınırlar: metin 64 MiB, belge 16 MiB, yardım çıktısı
  akış başına 1 MiB, MCP çıktısı son 64 KiB, `settings.toml` 1 MiB. SQLite `READ_ONLY`, URI ayrıştırması yok, 2 sn bekleme.
- Süreç: stdin boş, ayrı süreç grubu, toplam süre (`Instant` = `CLOCK_MONOTONIC`), borular `poll` ile tek iş parçacığından,
  zaman aşımı/taşma/hata/panik yolunda grup `SIGKILL` + `wait` (yalnız bu koşucunun açtığı grup).
- HTTP: hyper HTTP/1.1 + `tokio-rustls` (ring) + `rustls-native-certs`; doğrulama hep açık; istek başına iş parçacığı ve
  çalışma zamanı (tokio içinden çağrı güvenli). Proxy: `urllib` kuralları (`*_proxy`, `no_proxy`, Basic kimlik, `https` için
  `CONNECT`); parite 2500 rastgele ortam x adres.
- `agy_sids`: Python ile aynı `agy_sids.json.lock` `flock`ı + atomik yazım. Belge deposu `StateDocStore` = rs/state
  `StateDocs` (`files`, `dual`, `db`); bağlayan uç süreç başına tek `StateDocs` kurar ve `diag_mirror`ı `DiagLog`a verir.
- Yeni bağımlılıklar: `libc` (open bayrakları, `poll`, `kill`, `access`, saat), `sha2` (token özeti), `base64` (proxy kimliği),
  `hyper`/`hyper-util`/`http-body-util`/`tokio`/`bytes` (workspace'te zaten var), `tokio-rustls` 0.26 ve `rustls-native-certs`
  0.8 (rs/hosts ile aynı seçim; ikinci bir HTTP yığını olmasın diye `ureq` eklenmedi). `rusqlite` dev'den normal bağımlılığa.
  Yalnız test: `rcgen`.
- G1-G7'den devralınan G8 maddeleri: `list_dir` sırası, `read_range`/okuma sözleşmesi, `proc_stat`, SQLite (kapanış, 2 sn, WAL),
  64 MiB üstü hata kaydı sınırı (`failed_turn_records_over_the_read_limit_*`; Python sınırsız, sınır korunuyor), `AgySidStore`,
  `ModelIo`, `Effect` ve `register_mcp` hata biçimi.

### Birleştirme notları
- rs/state: `DocStore` = `StateDocStore` (yapıldı; `FileDocs` kalktı). Kalan: `lock.rs` ->
  `fsutil::FileLock`, `effects::atomic_write_text` -> `fsutil`, `pyjson::dumps_pretty` -> `cops-state::json`,
  `DiagLog::with_mirror` bağlayıcısı `StateDocStore::diag_mirror`; `sha2` ile oradaki `sha256.rs`ten biri kalmalı. İki kilit modülü aynı anda
  aynı dosyayı İÇ İÇE almamalı (`flock` tanıtıcı başına: kendini kilitler).
- rs/proc: `ProjectDirs` = `transcript.rs::encode_cwd`; süreç sinyali lint'i gelirse `real/process.rs` istisna olmalı (yalnız
  kendi çocuk grubunu öldürür) ya da `ProcFs` yoluna alınmalı.
- rs/hosts: TLS yapılandırması ve sürümler ortaklaştırılabilir. `rust/Cargo.lock` bu dalda büyüdü: birleşimde yeniden çözülmeli.
- G9: `RealProbe` panel portuyla kurulur; süreç başına TEK `HelpCache`, `ModelSources` ve `MetaCache`; `BuildOutput::diags`
  `DiagLog::write_all`a, `effects` `apply_all`a verilir (hata = spawn düşer); süreç başına TEK `CostLedger` ve `ManagedSearch`;
  başarısız ya da kuru başlatmada `CostGate::release(ad)`; ayar kaydında `CostLedger::invalidate()`.

### Bilinen ayrışmalar (bilinçli; `parity_real`da kayıtlı ayrışma yok: bunlar ya yalnız Rust testinde ya da testsiz)
- HTTP: yönlendirme iki tarafta da izlenmez (TBD#389; `redirects_are_never_followed_*`). Fark:
  `User-Agent: claudeops` (Python `Python-urllib/3.10`); adreste `kullanıcı@` ve başlıkta denetim karakteri reddedilir; süre
  toplam; gövde sınırlı; kök sertifikalar `rustls-native-certs`; yalnız `http`/`https` (Python `file:`/`ftp:` de açar).
- Süreç: `ucli chat --help` stdin'i boş; çıktı sınırlı; `agy models` stderr'i atılır. Zaman aşımında grup sonlandırma, UTF-8
  olmayan yardım / `mcp add` çıktısı ve alınamayan kilit artık iki tarafta aynı (TBD#397 bölümü). Kalan fark: kuru kurulumda
  UTF-8 olmayan yardım Rust'ta günlüğe girer (`HelpCache` kuru kipi bilmez; Python yazmaz).
- Belge deposu (rs/state'ten miras, `parity_docs`): `db` kipinde DB kalıcı olarak yazılamıyorsa (DB dosyası yok, şema
  farklı, Postgres) Rust hiçbir yere yazmaz ve hata döner (Python DB'yi yaratır ya da dosyaya düşer); `dual` kipte Rust
  DB dosyası yaratmaz. `dual` kipte DB'ye aktarılamayan (eşlenmemiş vekil) belge için Python başarısız aktarımdan önce
  "statedocs import" yazar, Rust yazmaz. Yalnız bu crate'te: FIFO/aygıt ve 16 MiB üstü belge dosyası açılmaz (Python
  sınırsız; FIFO'da asılır).
- `realpath` 256 farklı bağlantıda durur (Python `RecursionError`); metin/belge okuma sınırları (16 MiB üstü ajan defteri
  Rust'ta üzerine yazılmaz).
- Eşlenmemiş vekil içeren belge yeniden yazılırsa U+FFFD olur (`pyjson`; Python vekili korur ya da yazımda düşer). `agy_sids` hariç: iki tarafta da yazılmaz (27 Kas `fix:`).
- Göreli yollar Python gibi sürecin dizinine göredir; `RealProbe::with_cwd` yalnız `realpath` ve `current_dir`i etkiler.

### Python hatası adayları (27 Kas: kalıcı kural uygulandı; her düzeltme ayrı `fix:` + `py/tests/test_rsprov_g8_*.py`)
| # | Aday | Sonuç |
|---|---|---|
| 1 | `ucli_agents` defteri yalnız süreç içi kilitli | DÜZELDİ (`file_lock`; iki dil aynı `ucli_agents.json.lock`) |
| 2 | nesne olmayan üst kayıtta istisna, token dosyası yazılmış kalıyor | DÜZELDİ: token yazılmadan `TypeError`; spawn Python'daki gibi düşer, Rust eşitlendi |
| 3 | bozuk defter boş sayılıp yedeksiz eziliyor | DÜZELDİ: `.corrupt-<özet>` kopyası (0600); okunamayan defter ezilmez (oturum ajansız açılır) |
| 4 | `check_shape`/`_OWNER` `Infinity`/`NaN` adı ve sondaki satır sonunu kabul ediyor | DÜZELDİ (tam eşleşme, ad dize olmalı) |
| 5 | `load_registry` derin JSON ve bağlantı yarışı | DÜZELDİ (`O_NOFOLLOW` + tanıtıcıdan tür/izin; `RecursionError` hata metni) |
| 6 | yardım yoklaması/`mcp add` UTF-8 olmayan çıktıda istisna | DÜZELDİ (TBD#397, sahip adına cops cevabı) |
| 7 | `ucli chat --help` stdin'i miras alıyor | DÜZELDİ (`DEVNULL`) |
| 8 | zaman aşımında torun süreç yetim | DÜZELDİ (TBD#397; yalnız yardımcı çocuğun kendi grubu) |
| 9 | UTF-8 olmayan rustup ayarı istisna | DÜZELDİ (varsayılan bilinmiyor; birden çok adayda "belirsiz" reddi) |
| 10 | `file_lock` kilit alamazsa kilitsiz yazıyor | DÜZELDİ (yazmama: TBD#374 main birleşimi; günlük: TBD#397) |
| 11 | anahtar/damga yolunda FIFO spawn'ı bloklar | DÜZELDİ (`base._open_private_target`: bloklamadan `OSError`, boruya sır yazılmaz) |
| 12 | `path_executables` satır sonlu dosya adını listeliyor | DÜZELDİ |

### Ders listesi (`docs/rust-lessons-from-python.md`), G8 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G8 (ikinci parça): maliyet defteri ve SearXNG

### Sahiplik
Fiyat tablosu, Haiku dilim sabitleri ve `anthropic_price` tek kaynaktan: `cops-review-core` (`targets.rs`, `report.rs`);
`cost.rs` ve `ucli.rs` oradan alır (`f4679f51` eşitlemesi). Toplayıcı İKİ kopya: `report.rs::usage_cost_usd` yalnız toplam,
`cost.rs::UsageScan` toplam + güvenilirlik (`problem`); kural değişirse ikisi de güncellenir.
- 27 Kas ölçümü (`tests/usage_two_copies.rs`: elle sınır satırları + 3000 rastgele günlük, 4 model x 3 `since`/çarpan):
  rastgele dosyalarda fark yoktu; sınır satırlarında üç tür fark. İkisi `cops-review-core`da düzeltildi (Python'a eşit):
  eşlenmemiş vekil taşıyan satır sayımdan düşüyordu (`parse_lossy`); metin damgada ASCII olmayan rakam 0 okunuyordu
  (`py::float_str` artık `cops_state::pycompat::parse_float`). Kalan, testte adıyla izinli tek fark: nesneyle birlikte 513
  katlı satırı review sayar (Python gibi), defter saymaz ve `problem` ile tavanı KAPATIR (yukarıdaki 512 sınırı).
- Tekleştirme YAPILMADI (açık iş, iz): iki ayrı JSON türü (`cops_state::json::Json`, `pyjson::Py`) üstünde para kapısının
  yeniden yazımı demek; eşlik testi sapmayı yakalıyor.

### Maliyet defteri (`cost.rs` saf, `real/ledger.rs` G/Ç)
- Defterin yazarı claudeops değil: `<durum>/ucli_usage/<oturum>.jsonl` dosyalarına yalnız `ucli` ekler; Python ve Rust yalnız
  okur. **Paylaşılan yazım yok, bu yüzden dosya kilidi ve atomik yazım da yok**; yarım yazılmış satır atlanır
  (`reading_while_another_process_appends_never_flags_or_loses_records`: ayrı süreç satırları iki parçada eklerken okuma).
- **Dil/süreç uyumu:** başlatma payı iki dilde de süreç belleğinde (`_RESERVED` / `CostLedger::reserved`). Aynı anda Python ve
  Rust süreci Claude oturumu açarsa birbirlerinin payını görmez (Python'da panel ile CLI arasında da böyle): tavan en çok
  eşzamanlı başlatma sayısı kadar aşılabilir. Birleşimde spawn tek süreçte kalmalı. Ortak pay dosyası Python'a yeni
  davranış olacağından eklenmedi (TBD#397 madde 4: şimdilik kalsın).
- Para sınırı kapalı yön (iki dilde): tavan açıkken okunamayan dizin/dosya, normal olmayan dosya, geçersiz sayaç ya da zaman
  damgası başlatmayı reddeder (`claude: günlük USD tavanı denetlenemiyor (...)`; `code` YOK). Geçersiz sayaç toplamaya girmez.
  Ayrıştırılamayan satır eskisi gibi atlanır (yarım yazım ile bozukluk ayrılamaz).
- Kapı: `CostGate::check_and_reserve` = `cap_exceeded` + `reserve`; ret `BuildOutput::cost_refusal`a yazılır,
  `cost::refusal` web sonucunu (`code`, tutarlar) kurar. `SpawnRefused` dalı G9/kanca katmanında.
- Ayar: `CostSettings` her çağrıda; `file_cost_settings` dosya yoksa varsayılan, var ama okunamıyor/ayrıştırılamıyorsa ret.

### SearXNG (`real/searxng.rs`; TBD#88 geçici, dar)
- Yalnız spawn yolu: kayıtlı portta `/healthz`; kuru çalıştırma; docker kapalı önbelleği 60 sn; `inspect`, gerekirse `start`;
  kurulum gerekiyorsa AYRIK süreç (`Provision`: `<python> -m claudeops searxng provision`, yeni oturum, çıktı `provision.log`).
  İmaj çekme, `run`, `rm`, `status`, `stop` Rust'ta YOK (Python'da kalır).
- Ortak dosyalar: `searxng/state.json` (yazım `state.json.lock` `flock`ı + atomik, 0600; iki dil aynı kilidi alır,
  `the_state_write_waits_for_the_lock_python_takes_*`), kurulum kilidi `searxng/.lock`.
- Sağlık yoklaması std soketle yalnız `127.0.0.1`: proxy yok, yönlendirme yok, toplam süre. Yeni bağımlılık yok.

### Bilinen ayrışmalar (testte kayıtlı olan yok: yalnız Rust testinde ya da testsiz)
- Defter: 512'den derin ya da 16 MiB'tan uzun satır Rust'ta "sayılamıyor" reddi (Python 1000'e dek okur / sınırsız); var ama
  ayrıştırılamayan `settings.json` ve geçersiz tavan iki tarafta reddedilir (TBD#397); `credit_window` sonlu olmayan
  girdiyi `null` yazar. 512'den derin `settings.json`da Rust "bozuk" reddi verir, Python daha derine dek okur, çok derinde
  `load_settings` `RecursionError` atar (başlatma yine olmaz; düzeltilmedi).
- SearXNG: docker çıktısı 4 MiB sınırlı; zaman aşımında docker süreç grubu öldürülür; sağlık yoklaması yalnız durum satırına
  bakar, `User-Agent: claudeops`; kilit alınamazsa durum yazılmaz; hata metinleri (`repr(OSError)`) testsiz köşelerde
  farklı olabilir; docker zaman aşımı metni yalnız Rust testinde.

### Python hataları (27 Kas iki tarafta DÜZELDİ; `py/tests/test_rsprov_{cost_ledger,searxng}.py`)
- Defter: tek bozuk bayt / dev sayı / derin satır `/api/status` ve spawn'ı düşürüyordu; NaN ya da negatif sayaç tavanı
  aşırıyordu; okunamayan günlük 0 harcama sayılıyor, FIFO blokluyordu; `invalidate()` yarışı harcamayı 0 gösterebiliyordu.
- SearXNG: yoklama yönlendirme izliyordu; HTTP olmayan dinleyici ve sonsuz port kurtarmayı kalıcı durduruyordu; durum
  dosyasında kayıp güncelleme; beklenmeyen `inspect` yapısı istisna veriyordu.

### Sahibe bırakılanlar (uygulanmadı)
2-4: TBD#397 cevabı (27 Kas): şimdilik kalsın, TODO'da açık.

1. DÜZELDİ (TBD#397 soru 1 a): bozuk/okunamayan `settings.json` ya da geçersiz `daily_cap_usd` artık Claude hizmetli
   başlatmayı reddettiriyor.
2. Başlatma payı süreçler arası paylaşılmıyor (panel + CLI; ileride Python + Rust).
3. Ayrıştırılamayan günlük satırı 0 harcama sayılıyor (yarım yazım ile kalıcı bozukluk ayrılmıyor).
4. SearXNG hızlı yolu kayıtlı portta `/healthz` 200 veren HERHANGİ bir süreci kabul ediyor (çok kullanıcılı makine).

### Ders listesi, ikinci parça koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## TBD#397: sahip onaylı dört düzeltme (27 Kas, iki tarafta)
| # | Konu | Davranış | Python testi | Rust testi / parite |
|---|---|---|---|---|
| A | günlük USD tavanı | var olan `settings.json` bozuk/okunamaz, `ucli_cost` sözlük değil ya da `daily_cap_usd` sayı değil/negatif/sonlu değil ise Claude hizmetli başlatma reddi; dosya/anahtar yok, boş, 0 = tavan yok; `state` ve öteki hizmetler değişmez | `test_rsprov_cap_settings.py` | `real_ledger::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity_ledger` `tavan-ayari*` |
| B | UTF-8 olmayan çıktı | yardım = "" (bayrak tanınmaz, güvenlik izni isteyen başlatma reddi), ikili sürümü başına bir kez `help_output_not_utf8`; `mcp add` sonucu çıkış kodundan, `ucli_mcp_output_not_utf8` | `test_rsprov_help_utf8.py` | `real_process::{non_utf8_help_gives_no_flags_and_is_logged_once_per_binary_version, register_mcp_with_non_utf8_output_follows_the_exit_code}`; `parity_real` `yardim` `mcp-bozuk-cikti*` |
| C | yetim torun | yardım yoklaması, `mcp add`, `claude -p`/ucli tek atımlık, onay sürdürme, `agy models`, docker CLI yeni grupta; zaman aşımında/kesilmede grup `SIGKILL`; çağıranın grubuna ve beklenmiş çocuğa sinyal yok | `test_rsprov_child_group.py` | `real_process::a_timeout_kills_the_whole_process_group_and_waits`, `real_oneshot::timeouts_kill_the_whole_group_and_return_promptly`, `real_searxng::a_hanging_docker_is_killed_marked_down_and_not_asked_again` (davranış Rust'ta vardı) |
| D | alınamayan kilit | yazım yok (önceden vardı) + `file_lock_refused` (`path`) | `test_state_lock_fail_closed.py` | `real_agy_store::a_symlinked_lock_file_is_refused_and_nothing_is_written`, `real_oneshot::the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing`; `parity_oneshot` `kayit-kok-*` |

- Bağlayan uç: `ApprovalStore::with_diag` ve `DocAgySidStore::with_diag` verilmeli (`RealProbe` ajan defterine kendi bağlar,
  `SpawnRuntime` `HelpCache`e ve arama yöneticisine bağlar). `rs/state` `cops-state::fsutil::FileLock` bu olayı yazmaz (o iz).
- TBD#397 maddeleri 4, 5, 6 (süreçler arası pay, ayrıştırılamayan günlük satırı, SearXNG port sahibi) DEĞİŞMEDİ.

## main `9e5bcf24` eşitlemesi: fiyatsız modelde USD tavanı (27 Kas)
claude hizmetinde claudeops tablosundan `--price` (dilimli modelde en pahalı dilim), tur tavanı `--price` verilen modelde de
eklenir, fiyatı bilinmeyen modele oturum tavanı `SpawnError`. Rust `ucli.rs` (`claudeops_price`, `has_price`), parite
`parity_ucli` `fiyat-*`. TBD#397 günlük tavan reddiyle çakışmaz (biri `settings.json`, öbürü argv fiyatı).

## main `f4679f51` eşitlemesi (27 Kas)
Tek çakışma `py/claudeops/review.py` `_scan_usage`: dalın "güvenilmez toplam" dönüşü (`problem`, `FileNotFoundError` ayrımı)
ile main'in `task_end` atlaması ve Haiku dilimi BİRLİKTE korundu. `task_end` satırı toplama ve sayaç denetimine girmez;
zaman damgası bozuksa dalın kuralıyla yine `problem` olur.

| Python davranışı (main) | Rust | Sınama |
|---|---|---|
| ucli `task_end` toplamı iki kez faturalanmaz; Haiku 5.5 100K üstü istem pahalı dilimden (`78b05780`) | `cops-review-core` `report.rs` payı main'de; defter toplayıcısı `cost.rs::UsageScan` bu turda | `parity_ledger` `dilim*` ve rastgele satırlar (`task_end`, eşik sayıları) |
| fiyat tek kaynak (`HAIKU_LONG_PRICE`) | `TOP_TIER_PRICES` ve `cost.rs::PRICES` silindi; `cops-review-core` | `parity_ucli` `fiyat-*` |
| yeni pencere hedef masaüstünde (`startup_desktop.py`, `796b3acb`) | `startup_desktop.rs`, `real/startup_desktop.rs`, `Terminal::startup_env` + `Launcher::launch_window` (dört pencere yolu), `SpawnRuntime::launcher` bağlar | `parity_g9` `masaustu-*` (iki tarafta gerçek mantık, sahte sayım/gönderim), `tests/g9.rs`, yapı düzeni birim testi |
| `settings.spawn_desktop` varsayılanı | `cops-state` `default_settings.json` (main'de eksikti) | `cops-state` parite |
| `tmux_capture(join=True)` (`6aee83bd`) | `cops-tmux` `Tmux::capture_joined` | `cops-tmux` parite (gerçek ve sahte tmux) |
| açılışta ölen ucli'nin hata satırı (`_with_ucli_error`) | taşınmadı: `web._start` bu crate'te yok (bağlayan uç) | |

- **TBD#399 canlı geçiş `-J`den ETKİLENMEZ:** `join` varsayılanı kapalı; Python'da tek `join=True` çağıranı
  `web._with_ucli_error`. `Pane::capture` (giriş kutusu, diyalog, sonuç satırı) iki dilde de sarılmış satırlarla okur.
- Parite koşucusu X sunucusuna ve `wmctrl`e dokunmaz (`harness.py` `startup_env`i varsayılan kapatır). Gerçek X gönderimi
  (`send_startup_x11`) sonradan özel `Xvfb`de Python'la olay olay sınandı (`tests/real_x11.rs`); gerçek masaüstünde
  (Mutter pencereyi hedefe taşıyor mu) Rust yolu CANLI DENENMEDİ.
- Bilinen ayrışma (yalnız bozuk `spawn_desktop`, testte vaka yok): `Infinity` Python'da `startup_desktop_error`, Rust'ta
  `settings.json` ayrıştırılamaz (varsayılanlar); `i64`a sığmayan eksi sayı METNİ Python'da kapalı, Rust'ta varsayılan.

## main `726888f1` eşitlemesi (27 Kas)

| Python davranışı (main) | Rust | Sınama |
|---|---|---|
| Bekçi, yeniden denemeden önce bu başlıkta pencere varsa (`wmctrl -l`, tam eşleşme) yenisini açmaz, bekler (`spawn_retry_window_exists`); okunamazsa eski davranış; denemeler bitince penceresiz yedek yine açılır | `spawn_exec.rs::fallback_watchdog` + `Terminal::window_list` (zorunlu yöntem; gerçek `GnomeTerminal`, 3 sn, 1 MiB) | `parity_g9` `bekci-pencere-` (iki tarafta gerçek ayrıştırma, sahte `wmctrl` baytları); `tests/g9.rs` üç test |
| Bu dalın düzeltmesi (`045cdcc6`): `wmctrl` çıktısı UTF-8 değilse (başka pencerenin başlığı) bekçi istisnayla bitiyordu | bozuk bayt yer tutucuyla okunur, `ValueError` "okunamadı" (`27b8254d`) | `UndecodableWindowListTest` (düzeltmeden önce 2 test kırmızı); `bekci-pencere-bozuk-bayt` `-valueerror` |

## G10: tek atımlık çağrı ve onay

### Sahiplik
Taşınan: `OneshotError`, `CliProvider.oneshot`, `UcliProvider.oneshot`, `ucli_chat_once`, `build_chat_argv`,
`_subprocess_env`, `mark_budget_exhausted`, onay kaydından `ucli_chat_once`un kullandığı kısım (`dir_for`, `register`,
`set_state`, `parse_suspended`, defter okuma). Cevap yazma, sürdürme, listeleme ve `UcliReplSession` KAPSAM DIŞI
(satırlar tabloda). Python'da bugün üretimde `approval_run_key` veren çağıran yok (yalnız testler).

### Tasarım ve bağımlılıklar
- Saf: `oneshot.rs` (argv, anahtar adı, çıktı yorumu, sır silme, bütçe notu), `approval.rs` (ad biçimleri, askı satırı,
  defter dönüşümleri). Gerçek: `real/oneshot.rs` (`OneShot`), `real/approval.rs` (`ApprovalStore`).
- Süreç: var olan `real/process.rs` (stdin boş, toplam süre, grup `SIGKILL` + `wait`, akış başına 16 MiB sınır).
- Sır: anahtar yalnız çocuğun ortamında (`Env::with_var`); `ApiKey` `Debug`da maskeli; çocuk çıktısı hata metnine
  `redact`ten geçerek girer; onay kaydındaki `argv_resume` anahtar taşımaz.
- Defter: Python ile aynı `index.json.lock` `flock`ı + atomik 0600 yazım. Belirsizlikte ret (aşağıdaki düzeltmeler).
- Yeni bağımlılık yok. `Paths::ucli_approval_root`, `Env::with_var` eklendi.

### Birleştirme notları
- T7: `answer`/`pending`/`list_runs`/sürdürme taşınırken `approval::valid_*` (tam eşleşme), `consumed` işareti,
  sürdürme hatasının kayda anahtarsız yazılması (`redact`) ve `slot_free` kuralı korunmalı; ikinci bir defter yazarı
  açılmamalı (`ApprovalStore` genişletilmeli).
- rs/state: `real/lock.rs` `fsutil::FileLock` ile tekleşince `ApprovalStore` de ona geçer.
- T10: `summarize_card` `OneShot::oneshot`u çağırır (`Ok(None)` = CLI desteklemiyor); nötr `cwd`yi çağıran verir.

### Bilinen ayrışmalar (`parity_oneshot`ta kayıtlı ayrışma yok: bunlar ya normalleştirilen ya yalnız Rust testinde ya da testsiz)
- JSON ayrıştırma ayrıntısı metne girmez (normalleştirilir). 512'den derin cevap Rust'ta "JSON değildi" (Python ~1000'e
  dek okur); eşlenmemiş vekil U+FFFD olur (cevap metni ve yeniden yazılan defter).
- Çıktı akış başına 16 MiB ile sınırlı; defter 16 MiB, anahtar dosyası 64 MiB üstünde ret (Python sınırsız).
- Zaman aşımında süreç grubu öldürülür (Python yalnız doğrudan çocuğu).
- Zaman aşımı `f64`: Python tamsayı verilirse metinde `90`, Rust `90.0` (üretim çağıranları kesirli verir).
- Nesne olmayan kayıtta `set_state`: iki tarafta `TypeError`, metni farklı (üretimde ulaşılamaz).

### Python hataları (27 Kas iki tarafta DÜZELDİ; `f87f482d`, `70a192ca`; `py/tests/test_rsprov_g10_{chat,oneshot,approval}.py`, düzeltmeden önce 30 testin 28'i kırmızı)
| # | Hata | Düzeltme |
|---|---|---|
| 1 | `-` ile başlayan prompt ucli'de bayrak sayılıyordu (`--allow-edit` izin enjeksiyonu; `chat` konumsal argümanı `allow_hyphen_values` taşımıyor, yani diğer `-...` metinleri zaten hata veriyordu) | tek `-` dışında ret, ikili başlatılmadan |
| 2 | `ucli chat` çağıranın stdin'ini miras alıyordu | `DEVNULL` |
| 3 | başlatılamayan ikili, UTF-8 olmayan / nesne olmayan / aşırı derin çıktı, açılamayan onay dizini `UcliError` dışı istisna | hepsi `UcliError` |
| 4 | `oneshot`: UTF-8 olmayan çıktı, NUL, açılamayan cwd `OneshotError` dışı istisna (kart özetleyici yakalamıyordu) | `OneshotError` |
| 5 | anahtar dosyası UTF-8 değilse istisna ham anahtar baytlarını taşıyordu; FIFO bloklatıyordu | ret, zincirsiz; FIFO/aygıt okunmaz |
| 6 | çocuk stderr/stdout'undaki anahtar hata metnine ve onay kaydına aynen giriyordu | `_redact` (8+ karakter) |
| 7 | `_SAFE_ENV_NAME_RE`, `_KEY`, `_ID` sondaki satır sonunu kabul ediyordu | tam eşleşme |
| 8 | aynı `run_key` bekleyen kaydın `argv_resume`/sahibini eziyordu (eski onay başka argv ile sürebilirdi) | yalnız yok/`done`/`expired` üzerine yazılır; ikili başlatılmadan ret |
| 9 | bozuk ya da okunamayan defter boş sayılıp eziliyordu; FIFO blokluyordu; aşırı derin JSON istisna | `.corrupt-<özet>` kopyası; okunamayan ezilmez; bloklamaz |
| 10 | sembolik bağ olan koşu dizinine yazılıyor ve hedefin izni değiştiriliyordu | ret |

### Python hatası adayları (1, 4, 5 DÜZELDİ)
| # | Aday | Sonuç / neden bekliyor |
|---|---|---|
| 1 | `api_key_env` yalnız `api_key` verilince denetleniyordu: `/api/io/ask` alanları `api_key_env` + `endpoint` serbest, ortamdaki herhangi bir değişken seçilen adrese "API anahtarı" olarak gönderilebiliyordu | DÜZELDİ (TBD#401 (a), sahip onayı; `99cd8ff4` + `f82c9b7b`): yalnız `UCLI_API_KEY` ve ayarlardaki ucli hizmetlerinin `env`i; ret alt süreç ve ortam okumasından ÖNCE, ad yankılanmaz; `settings.json` okunamıyor/bozuksa ya da `ucli_services` liste değilse yalnız `UCLI_API_KEY`. AÇIK KALAN (karar dışı): `endpoint` serbest, izinli bir anahtar adı seçilen adrese gönderilebilir |
| 2 | `done` anahtar yeniden kullanılınca eski `consumed` işareti ve `pending/`, `answers/` dosyaları kalır: yeni koşu sürdürülemez ya da eski onay kimliği yeni koşuda görünür | T7 (cevap/sürdürme) kapsamı; üretimde `run_key` veren yok |
| 3 | `register` ile `set_state` arasında çökme `running` kaydı bırakır; 8 numaralı ret yüzünden o anahtar elle temizlenene dek kullanılamaz | kapalı yön; kurtarma T7 `recover_resuming` ile |
| 4 | zaman aşımında torun süreç yetim (G8 adayı 8 ile aynı) | DÜZELDİ (TBD#397) |
| 5 | DÜZELDİ (27 Kas): açılamayan (izin) anahtar dosyası "yok" sayılmaz, `ucli: anahtar dosyası okunamadı (açılamadı)` (ikili başlatılmaz); yok, `ENOTDIR` ve dizin hâlâ anahtarsız | `test_rsprov_paths_keyfile.py`, `real_oneshot::an_unreadable_key_file_is_refused_not_treated_as_missing` |
| 6 | `claude -p <prompt>`: `-` ile başlayan prompt denetlenmiyor (bugün prompt yalnız iç kart metni) | dış girdi yolu yok |

### Test edilemeyenler
Gerçek `ucli`/`claude` ikilisi, gerçek API çağrısı ve ucli'nin kendi onay akışı (yasak: harcama); `-` kuralı ucli
kaynağındaki argüman tanımından çıkarıldı, ikiliyle denenmedi.

### Ders listesi (`docs/rust-lessons-from-python.md`), G10 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## G9: spawn yürütme ve küresel yönerge (27 Kas: TAŞINDI ve sınandı; gerçek tmux ve süreç taraması uygulayıcıları yazıldı)

### Sahiplik
Taşınan: `spawn_session` akışı, `_launch_gnome_terminal`, `_reclaim_ghost_session`, `_fallback_watchdog` (+ `FALLBACK_*`),
`open_window`, `open_mirror_window`, `authz.spawn_env` (çağrı anlamı), `extensions.session_mcp_spec` + `mcp_ext.default_spec`,
`routing._sync_one` dosya adımları + `sync_global_files` (+ `CODEX_AGENTS`, `AGY_GEMINI`), `paths.REPO_DIR`. Kanca ve
eklenti KAYITLARI (kim, ne zaman kaydeder) çağıranın: crate yalnız `Hooks` listesini okur.

### Tasarım
- `spawn.rs`: `plan_spawn_with` + `HookFn` (kanca ortamı Python sırasında: MCP argümanlarından sonra, komuttan önce);
  `plan_spawn` ona sarmalayıcı.
- `hooks.rs`: `spawn_env` (ret aynen; başka hata `authz_spawn_hook_failed` + `hook_error`, kapalı yön), `session_mcp_spec`,
  `default_spec`, `Hooks`/`SpawnHooks`.
- `spawn_exec.rs`: `spawn_session`, `reclaim_ghost_session`, `fallback_watchdog`, `open_window`, `open_mirror_window`;
  sınırlar `SpawnTmux` (gerçek: `cops-tmux`), `Terminal`, `Clock`, `DiagSink`, `SessionScan` (rs/proc `find_sessions`),
  `ResumeResolver` (`Live`), `CostRelease`. Kuru ya da hatalı başlatmada başlatma payı burada geri verilir (Python'da web
  çağıranları yapar). `SpawnFailure::web_refusal` = `cost::refusal`.
- Bekçi gerçek iş parçacığı, `Watchdog` tanıtıcısı döner: kısa ömürlü çağıran (CLI) çıkmadan önce `join` ETMELİ (Python
  `daemon=False` süreci kendiliğinden canlı tutar; Rust'ta ana iş parçacığı dönünce süreç biter).
- `real/launch.rs`: `GnomeTerminal` (ortam miras YOK, program `env`deki `PATH`te aranır, NUL ve `=` `ValueError`
  karşılığı, çocuk arka planda toplanır), `SystemClock`, `DiagLog: DiagSink`, `repo_dir_of`.
- `real/routing_sync.rs`: `sync_one`, `sync_global_files{,_at}`, `copy2`. `real/runtime.rs`: `SpawnRuntime` (süreç başına
  tek defter/arama yöneticisi/`--help` önbelleği; `launcher(tmux, env)`).

### Testler (ölçülen, 27 Kas)
- `parity_g9` 164 vaka, kayıtlı ayrışma 0: spawn 119 (7 CLI x 13 kip + ekran, ortam süpürme, bekçi 8, ilk başlatma 3,
  kanca 5, eklenti 6, tarama düştü, tırnak), pencere 5, ayna 4, hayalet 10, eşitleme 25, `REPO_DIR` 1. tmux, `Popen`,
  saat, süreç taraması ve devam çözümü iki tarafta aynı olgularla sahte; çağrı günlüğü (`calls`) sırasıyla, diag, dosya
  ağacı, `mcp add` argv'si karşılaştırılır. Kanca ve eklenti MCP'si iki tarafta GERÇEK kod. `release` her vakada ayrıca
  denetlenir (kuru ya da hatalı başlatmada tam bir kez).
- `parity_misc` `sync*` artık gerçek `sync_one` ile (önceden test koşucusunda yazılmış kopya).
- Kötü ad (27 Kas): `{cli}-kotu-ad` 7 + `pencere-kotu-ad` 1 (Python `bb26564e` `spawn_bad_name`; Rust önceden reddediyordu,
  `d1bf8ff5` ile düzeltildi). Paritede `parity_g9` artık 172 vaka (`f4679f51` birleşiminden sonra `masaustu-*` 71 vakayla
  243; `726888f1` sonrası `bekci-pencere-*` ve `nul-*` ile 261).
- `tests/real_tmux.rs` 8 (yalıtılmış sunucu: tam ad/ön ek, miras almayan ortam, kötü adlarda tmux çalışmaz, sunucusuz
  durum, `PATH` yoklaması, Python parça metniyle bayt eşitliği, gerçek hayalet temizliği, bekçinin gerçek penceresiz
  yedeği, `open_window` tam hedef); `tests/real_scan.rs` 6 (sahte `/proc`: satırlar, öğrenilen agy kaydı, kuru kip,
  kilit/yazım hatası, okunamayan `/proc`, gerçek `DocAgySidStore` dosyası; gerçek `/proc` yalnız okuma).
- `tests/g9.rs` 15 (+ hedefsiz ve döngülü `.bak-routing` bağlantısı): `ReclaimTest` x4 karşılığı, bekçi sahte saatle (4), `SystemClock`, `GnomeTerminal` sahte betikle (yalnız
  verilen ortam, argv, zombi kalmaz; `OSError`/`ValueError` yolları), `copy2` (içerik, izin, ns zaman, hedef bağlantı),
  `repo_dir_of` (bağlantılar), varsayılan yönerge yolları.
- Testin bulduğu Rust hatası: yok (ilk koşuda 161/161 ve 14/14).

### Gerçek uygulayıcılar (27 Kas, `origin/main` `c834dbbc` birleşiminden sonra)
- `real/tmux.rs::CopsTmux` (`SpawnTmux`): `cops-tmux` `Tmux` üstüne ince sarmalayıcı (`CopsTmux::live(repo_dir, env)` =
  `-L cops` + `<depo>/py/claudeops/data/tmux.conf`). Değişmezler `cops-tmux`ta: hedef `=ad:`, hedeflenemeyen ad hiçbir
  tmux komutu çalıştırmadan ret (parça kurucuları Python `ValueError` metnini döner: `BAD_NAME`), `;` kaçırma, `-c` biçim
  literali, 5 sn zaman aşımı. Sınır METİN GÖNDERMEZ; `spawn_direct` ortamı sürecin TÜM ortamı (miras yok).
  `available()` = `shutil.which("tmux")` (verilen ortamın `PATH`i, `pathexec::which`). Hayalet yaşı için saat
  `with_wall_clock` (yalnız testler).
- `real/scan.rs::ProcScan` (`SessionScan`): `cops-procscan::find_sessions(CpuMode::Skip)` -> (ad, sid). Python taramasının
  tek yan etkisi korunur: öğrenilen agy kimliği crate'in `AgySidStore` yolu (`remember_agy_sid`) ile yazılır; kuru
  çalıştırmada yazılmaz (`live_sessions(preview)`; spawn `req.dry_run` verir, parite `scan` çağrısını iki tarafta
  günlüğe yazar). "Tarama düştü" (None) = `/proc` listelenemedi ya da öğrenilen kimlik YAZILAMADI (Python'da
  `write_json` istisnası `find_sessions`i düşürür); kilit alınamazsa tarama sürer, `agy_sids_lock_busy` (metin 200
  karakter). `scan_config(paths)` kökleri `Paths`ten kurar (`HOME`suz süreçte de çalışır).
- Bağlayan uç (copsd/panel `_start`, rc, handover) `SpawnRuntime` + `CopsTmux` + `ProcScan` + `spawn_session` çağrısı: o
  izlerin işi. Gerçek `Pane` (G4) uygulayıcısı: `real/pane.rs::TmuxPane` (G4 bölümü).

### Gerçek uygulayıcıların Python'dan bilinen farkları (davranış `cops-procscan`/`cops-tmux`ta; o crate'lere dokunulmadı)
- Kuru çalıştırmada agy öğrenmesi: `cops-procscan` `AgyState` öğrenilen kimliği bellekteki `known`a ekler; Python kuru
  kipte diske yazmadığı için aynı cwd'deki İKİNCİ adsız agy süreci aynı önbellek kimliğini yine alır, Rust almaz (yalnız
  aynı turda iki agy süreci aynı cwd'de ve kimlik henüz kaydedilmemişse; yalnız `in_use` kümesini etkiler).
- `db` kipinde `agy_sids` doğruluk kaynağı DB'dir; `cops-procscan` dosya aynasını okur (`cops-cli` `agy_mirror_reason`
  bu yüzden Python'a devreder). Ayna DB'den geri kalmışsa "başkasına kayıtlı" kararı farklı olabilir. `DocAgySidStore`
  `db` kipinde yazımı zaten reddeder (rs/state bağlanınca kapanır).
- `NaN`/`Infinity` içeren `sessions/*.json` Rust'ta atlanır (`session_files_invalid`), Python okur: o kaydın sid'i Rust
  `in_use` kümesine girmez. `cops-cli` bu durumda da devreder; spawn yolunda devredilecek Python yok, satır yalnız atlanır.
- `cops-tmux::tmux_available` sürecin `PATH`ine bakar; `CopsTmux::available` verilen `Env`e (Python `shutil.which`
  `os.environ`a bakar: canlıda ikisi aynı). Kilit (`real/lock.rs`) Python'dan sıkı: alınamayan kilit (sembolik bağ,
  başkasının dosyası) iki tarafta da yazım yok, `file_lock_refused` + `agy_sids_lock_busy` (Rust'ta ilki için
  `DocAgySidStore::with_diag`).

### `ids_held_by_others` taraması ile spawn arasındaki yarış (27 Kas incelemesi; KOD YAZILMADI)
- Pencere: `spawn_session` taramayı (`find_sessions`) yapar, devam kimliğini çözer, terminali başlatır ve DÖNER; yeni CLI
  süreci `/proc`ta saniyeler sonra belirir. Bu aralıkta FARKLI adlı ikinci spawn aynı cwd için aynı kimliği "boşta" görür
  (iki oturum aynı konuşmaya yazar).
- Python bunu `spawn_session` İÇİNDE değil ÇAĞIRANDA kapatır: `web._start`/`_new_chat`/`_adopt`, `rc` ve guard
  `guard_lock()` (`~/.claude/claudeops/guard.lock` üzerinde `flock`) içinde `spawn_session` + `_wait_stable` (süreç
  belirip sabitlenene dek) yapar; kilit süreçler arasıdır. Kilitsiz çağıran: `stuck.recover` (kendi adıyla yeniden açar,
  `in_use` kendi adını zaten dışlar).
- Rust'ta `spawn_session` içinde kapatmak davranış DEĞİŞTİRİR: (a) süreç içi "rezerv" kümesi yarışta ikinci spawn'a başka/taze
  kimlik verir (Python aynı kimliği verirdi) ve Python süreçlerini görmez; (b) `spawn_session` içinde `guard.lock` almak,
  kilidi zaten tutan çağıranlarda kilitlenir (`flock` açık dosya başına: aynı süreçte ikinci açış bekler). Bu yüzden
  yazılmadı. Python ile birebir ve iki dili kapsayan yol: Rust çağıranı (copsd `_start` taşıması) Python'la AYNI
  `guard.lock` dosyasını aynı kuralla (`O_NOFOLLOW`, sahiplik denetimi, `LOCK_EX|LOCK_NB` + 0,5 sn yoklama) `spawn_session`
  + `_wait_stable` boyunca tutar. Bu, `guard.py` taşımasının (çağıran izi) işidir.

### Bilinen ayrışmalar (`parity_g9`ta kayıtlı ayrışma yok: bunlar ya yalnız Rust testinde ya da testsiz)
- `release` yalnız Rust'ta (Python web çağıranları yapar).
- `spawn_ghost_reclaim_error` dalı yok: tmux sınırı hata yükseltemez.
- Bekçi `join` edilmezse kısa ömürlü süreçte yedek yol çalışmaz (yukarıda).
- `sync_one` 16 MiB üstü dosyayı `skipped:OSError` sayar (Python sınırsız okur); yollar UTF-8 olmalı.
- Toplayıcı iş parçacığı başlatılamazsa Rust çocuğu eşzamanlı toplar, sonra `RuntimeError` döner.

### Python hataları (27 Kas iki tarafta DÜZELDİ; her biri ayrı `fix:` + `py/tests/test_rsprov_g9_fixes.py`)
| # | Hata (düzeltmeden önce ölçülen) | Şimdi (Python ve Rust) | Sınayan |
|---|---|---|---|
| 1 | Hedefsiz bağlantı `.bak-routing`: `copy2` bağlantıyı izleyip dizin dışında dosya oluşturuyordu | yedek gerekirken bağlantı hedefsizse (döngü dahil) ne yedek ne yönerge dosyası yazılır: `skipped:broken backup link` + `routing_guidance_backup_broken_link`. Hedefi olan bağlantı eskisi gibi "yedek var". Yalnız bizim bloktan ibaret agy dosyasının silinmesi yedek istemez, değişmedi | `BrokenBackupLinkTest`; `esitle-kirik-yedek` `esitle-kirik-yedek-agy` `esitle-dongu-yedek` `esitle-bagli-yedek`; `tests/g9.rs::dangling_backup_link_writes_neither_backup_nor_target` |
| 2 | Hayaletin son ekranı (son 1500 karakter) `spawn_ghost_reclaimed` ile `diag.log`a düz yazılıyordu | `tail` alanı kalktı; yalnız `screen_lines` (boş olmayan satır) ve `screen_chars`. Alanı okuyan başka kod yoktu (panel günlüğü ham satır gösterir) | `GhostScreenNotLoggedTest`, `ReclaimTest`; `hayalet-`; `tests/g9.rs` ReclaimTest karşılıkları |
| 3 | Gizli başlatma, gnome-terminal var, tmux yok: hiçbir şey açılmıyor, iz yok | `spawn_hidden_no_tmux` olayı; başka davranış aynı | `HiddenWithoutTmuxTest`; `{cli}-gizli-tmuxsuz` |
| 4 | Bekçideki `Popen` `ValueError`ı iş parçacığını iz bırakmadan bitiriyordu (üretimde ulaşılamaz görünüyor, OKUNDU) | `spawn_retry_launch_error` (yalnız sınıf adı, metin yok); bekçi yine biter, yedek açılmaz | `WatchdogValueErrorTest`; `bekci-valueerror`; `tests/g9.rs::watchdog_failed_relaunch_is_logged_and_a_value_error_ends_it` |

### Python hatası adayları (5 DÜZELDİ; 6 sahipte: "Bekleyen sorular" S3)
| # | Aday | Sonuç |
|---|---|---|
| 5 | Hayalet temizliği başlatmadan ÖNCE: ilk `Popen` `ValueError` ile reddedilse de eski oturum kapatılıyordu (argv/ortamda NUL) | DÜZELDİ (27 Kas): ad, cwd, iç komut ya da ekranda NUL varsa temizlik yapılmaz; ret/akış aynı. Yalnız başlayamayacak açılışta fark. `test_rsprov_g9_fixes.py::GhostKeptWhenLaunchCannotStartTest`, parite `nul-` |
| 6 | Kanca kuru çalıştırmada da çağrılır (TODO "spawn kancası kuru koşuda da yazıyor") | UYGULANMADI. ÖLÇÜLDÜ: `{cli}-kuru`, `kanca-red-kuru` |

### Ders listesi (`docs/rust-lessons-from-python.md`), G9 koduna düşen maddeler
Crate geneli tek tabloya taşındı ve yeniden doğrulandı: "Ders listesi: crate'in tamamı" bölümü.

## Sır / argv notları (Python'a dokunulmadı)
- `spawn.py`: `env_overrides` + kanca ortamı `KEY=VAL` olarak komut satırına gömülür (tmux argv). Kanca bir API anahtarı döndürürse argv'ye girer;
  yalnız dry-run satırı maskeliyor. Bugünkü sağlayıcı override'ları sır içermiyor. Soru: "Bekleyen sorular" S4.
- ucli anahtarı argv'de değil (`$(cat dosya)`); dosya yolu iki tarafta tırnaklı (TBD#373/7).
- copilot BYOK: dosya source edilir, argv temiz.

## Üçüncü tur (27 Kas): ders satırları ve `origin/main` `49def922`
- Gelen iki Python commit'i (`01b68607` sohbet yedeğine antigravity `brain/` dosyaları: `periodic.py`, `chat_index.py`;
  `49def922` reviewer `--status-path`: `web_review.py`) bu crate'in kapsamında değil (T7 periyodik, T8 reviewer); Rust
  davranışı ve eşleme satırı eklenmedi. `docs/rs-rev.md` çakışması `map_table.py` ile yeniden üretildi.
- §3.2: `FileDocs` kalktı, `StateDocStore` (rs/state `StateDocs`) bağlandı.
- §3.12: ortak yardımcılar ve ayar okuma tek kaynağa indi. Devirle Rust'ın Python'a eşitlendiği yerler: `float` repr
  (yarımı çifte), `str` repr (Unicode yazdırılabilirlik), NFKC ağ konumu denetimi, `byok` ve hizmet `models`
  içindeki sözlük/liste `str()` biçimi. Başka izlerde yapılan değişiklikler: `cops-state` `settings_read.rs`e `pub fn
  is_safe_env_name` eklendi; `cops-steward-core` `parity/hand_cases.py`ye 12 `main_session_model_effort` vakası ve
  yeniden üretilen `fixtures/hand/main_session_model_effort.jsonl.gz`.
- Python hatası (iki tarafta, `fix:` `38cdc662`): eşlenmemiş vekil taşıyan `agy_sids` belgesi yazımda
  `UnicodeEncodeError` ile keşif turunu düşürüyordu; artık yazılmaz, `agy_sids_unreadable` günlüğü düşer.
- Gözlem (sınanmadı, kod değişmedi): BYOK anahtarı ayardan kaldırılınca anahtar dosyası silinemez ama `.managed` damgası
  silinirse sonraki açılış dosyayı "elle bırakılmış" sayar (copilot ve ucli, iki dilde).

## EŞLEME TABLOSU

26 Kas 2026'da `564c4cf` koduna bakarak dolduruldu; G5, G11, G6, G2 ve G3 satırları taşımadan sonra güncellendi. TBD#373 düzeltmesinde `preview.py` ve `_TRUST_TOKEN_RE` satırları eklendi. G10 satırları ve yeni yardımcılar sonradan güncellendi. Güncel sayım (27 Kas, `ast` ile satır satır): 711 satır: TAŞINDI 637, TAŞINDI-TESTSİZ 0, KAPSAM DIŞI 74, EKSİK 0 (G9 satırları 27 Kas; 27 Kas düzeltme turunun 5 yardımcı satırı eklendi, Python satır numaraları düzeltme öncesi).
- Durumlar: `TAŞINDI` (Rust adı + onu sınayan parite vaka ailesi; vaka kimliğinde geçen parça yazıldı), `TAŞINDI-TESTSİZ`, `EKSİK(Gn)`, `KAPSAM DIŞI` (sahibi olan iz).
- `KAPSAM DIŞI` karşılıkları `origin/rs/{proc,tmux,state,stew}` dallarında görüldü; o dallar henüz birleşmedi (rs/tmux, rs/state, rs/stew kendi belgelerinde "birleştirmeye hazır değil" diyor). Sprint planındaki T1..T10 sahipleri için kod henüz yok.
- `rs/proc` kendi tablosunda sağlayıcıların çoğunu "rs/prov" diye bu ize bırakıyor; burada yalnız süreç tarama işlevleri ona bırakıldı.

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `_run_grouped` (py/claudeops/childgroup.py:25) | `real/process.rs::run` | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits` | TAŞINDI |
| `_kill_group` (py/claudeops/childgroup.py:13) | `real/process.rs::Guard` (`Drop`) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits` | TAŞINDI |
| `_ucli_cap_problem` (py/claudeops/settings.py:885) | `settings.rs::cap_problem` (ham belge), `real/ledger.rs::{file_cost_settings, non_finite_cap}` | `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `_log_lock_refused` (py/claudeops/atomic_json.py:236) | `real/lock.rs::{FileLock::acquire_logged, log_refused}` | `parity.rs::parity_oneshot` `kayit-kok-` | TAŞINDI |
| `DEFAULT_CLI` (py/claudeops/providers/__init__.py:14) | `provider.rs::Cli::parse` (bilinmeyen = claude) | `parity.rs::parity_spawn` `bogus-*` | TAŞINDI |
| `PROVIDERS` (py/claudeops/providers/__init__.py:16) | `provider.rs::Cli`, `Cli::ALL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `get_provider` (py/claudeops/providers/__init__.py:26) | `provider.rs::Cli::parse` | `parity.rs::parity_build` `bogus`; ayrıca `parity_spawn` `bogus-*` | TAŞINDI |
| `CONVERSATIONS_CACHE` (py/claudeops/providers/agy_provider.py:84) | `probe.rs::Paths::agy_conversations_cache` | `parity.rs::parity_resume` `devam-diger` `devam-agy-onbellek-` | TAŞINDI |
| `CONVERSATIONS_DIR` (py/claudeops/providers/agy_provider.py:85) | `probe.rs::Paths::agy_conversations_dir` | `parity.rs::parity_chat` `chat-agy-` (`roots`) | TAŞINDI |
| `AGY_SIDS_JSON` (py/claudeops/providers/agy_provider.py:94) | `rs/proc` `Config::agy_sids` | rs/proc: `fake_proc::broken_agy_files` (okuma); yazım yolu `agy_resume.rs::AgySidStore` (G1) | KAPSAM DIŞI |
| `_STEP_TYPE_USER` (py/claudeops/providers/agy_provider.py:98) | `chat.rs::AGY_STEP_USER` | `parity.rs::parity_chat` `agy-sikistirma` `agy-tur-tipi-` | TAŞINDI |
| `_STEP_TYPE_ASSISTANT` (py/claudeops/providers/agy_provider.py:99) | `chat.rs::AGY_STEP_ASSISTANT` | `parity.rs::parity_chat` `agy-sikistirma` `agy-tur-tipi-` | TAŞINDI |
| `_STEP_TYPE_CHECKPOINT` (py/claudeops/providers/agy_provider.py:101) | `chat.rs::AGY_STEP_CHECKPOINT` | `parity.rs::parity_chat` `agy-sikistirma` `agy-sinir-yarim` | TAŞINDI |
| `_read_varint` (py/claudeops/providers/agy_provider.py:104) | `chat.rs::read_varint` | `parity.rs::parity_chat` `agy-yuk-` `agy-rastgele-`; `chat::tests::varint_limits` | TAŞINDI |
| `_iter_fields` (py/claudeops/providers/agy_provider.py:116) | `chat.rs::bytes_field` (tek döngü) | `parity.rs::parity_chat` `agy-yuk-` `agy-rastgele-`; `huge_length_and_field_number_do_not_wrap` | TAŞINDI |
| `_get_bytes_field` (py/claudeops/providers/agy_provider.py:144) | `chat.rs::bytes_field` | `parity.rs::parity_chat` `agy-yuk-` `agy-rastgele-`; `truncated_and_mutated_protobuf_never_panics` | TAŞINDI |
| `_get_text_field` (py/claudeops/providers/agy_provider.py:160) | `chat.rs::nested_text` | `parity.rs::parity_chat` `agy-yuk-` `agy-rastgele-` | TAŞINDI |
| `_step_user_text` (py/claudeops/providers/agy_provider.py:165) | `chat.rs::agy_user_text` | `parity.rs::parity_chat` `agy-yuk-` `agy-rastgele-` | TAŞINDI |
| `_step_assistant_text` (py/claudeops/providers/agy_provider.py:172) | `chat.rs::agy_assistant_text` | `parity.rs::parity_chat` `agy-yuk-` `agy-rastgele-` | TAŞINDI |
| `_conversation_ids` (py/claudeops/providers/agy_provider.py:179) | `agy_resume.rs::Live::agy_conversation_ids` | `parity.rs::parity_resume` `devam-agy-konusmalar` `devam-agy-dizin-yok` | TAŞINDI |
| `PERMISSION_MODES` (py/claudeops/providers/agy_provider.py:187) | `agy.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/agy_provider.py:188) | `agy.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/agy_provider.py:195) | `agy.rs::BUSY_STATUS_PATTERN` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `_PERMISSION_FLAGS` (py/claudeops/providers/agy_provider.py:197) | `agy.rs::permission_flags` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/providers/agy_provider.py:203) | `agy.rs::MODELS_TTL` | `parity.rs::parity_model_sources` `src-agy-akis`; `tests/model_sources.rs::lifetimes_and_limits_match_python` | TAŞINDI |
| `_load_agy_sids` (py/claudeops/providers/agy_provider.py:206) | `rs/proc` `providers.rs::AgyState::load` | rs/proc: `providers.rs::agy_sid_rules`, `broken_agy_files`; DB yerine dosya aynası okur. Devam yolunda okuma `LiveProbe::agy_sids_doc` (G1, parite `devam-agy-ogrenilen-`) | KAPSAM DIŞI |
| `_remember_agy_sid` (py/claudeops/providers/agy_provider.py:215) | `agy_resume.rs::remember_agy_sid` + `AgySidStore` (`flock`: `real/docs.rs::DocAgySidStore`; belge `StateDocStore`, files/dual/db); `parity_docs`; `tests/real_agy_store.rs`, `parity_real` `agy-` | `parity.rs::parity_resume` `devam-agy-yaz-`; `tests/resume.rs::concurrent_remembers_lose_nothing`, `value_is_checked_again_under_the_lock`, `preview_writes_nothing_and_save_errors_surface` | TAŞINDI |
| `_ABSENT`, `_load_agy_sids_for_write` (py/claudeops/providers/agy_provider.py, 27 Kas `fix:`) | `agy_resume.rs::AgySidStore::load_for_write`, `real/docs.rs::DocStore::read_checked`, `AGY_SIDS_UNREADABLE` | `parity.rs::parity_resume` `devam-agy-yaz-bozuk` `-liste`, `parity_real` `agy-belge1..3`; `test_rsprov_g1_fixes.py::AgyTest.{test_broken_document_is_not_overwritten, test_document_that_cannot_be_written_back_does_not_drop_the_scan}`; `parity_docs` `bozuk-*` `vekil` | TAŞINDI |
| `_conversation_db_exists` (py/claudeops/providers/agy_provider.py, 27 Kas `fix:`) | `agy_resume.rs::Live::agy_db_exists` | `parity.rs::parity_resume` `devam-agy-ogrenilen-tam`; `test_rsprov_g1_fixes.py::AgyTest.test_learned_id_whose_database_is_gone_is_not_resumed` | TAŞINDI |
| `_sid_claimed_by_other` (py/claudeops/providers/agy_provider.py:230) | `agy_resume.rs::sid_claimed_by_other` | `parity.rs::parity_resume` `devam-agy-sahipli-` | TAŞINDI |
| `AgyProvider` (py/claudeops/providers/agy_provider.py:237) | `agy.rs` + `Cli::Agy` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `AgyProvider.name` (py/claudeops/providers/agy_provider.py:238) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.__init__` (py/claudeops/providers/agy_provider.py:240) | `agy.rs::ModelsCache` (`model_sources.rs::ModelSources::new`) | `parity.rs::parity_model_sources` `src-agy-acilis` (Python hatası? G7 şüphe 1) | TAŞINDI |
| `AgyProvider.resolve_resume_id` (py/claudeops/providers/agy_provider.py:244) | `agy_resume.rs::Live::agy_resume_id` | `parity.rs::parity_resume` `devam-agy-onbellek-` `devam-agy-ogrenilen-` `devam-agy-cwd-` | TAŞINDI |
| `AgyProvider.build_inner_command` (py/claudeops/providers/agy_provider.py:271) | `agy.rs::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra`; ve `parity_spawn` `agy-effort-ayar agy-effort-kardes` | TAŞINDI |
| `AgyProvider.env_overrides` (py/claudeops/providers/agy_provider.py:320) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.mcp_setup_command` (py/claudeops/providers/agy_provider.py:323) | `agy.rs::mcp_setup_command` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `AgyProvider.matches_proc` (py/claudeops/providers/agy_provider.py:333) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `AgyProvider.extract_name` (py/claudeops/providers/agy_provider.py:336) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `AgyProvider.extract_info` (py/claudeops/providers/agy_provider.py:343) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `AgyProvider._fetch_models` (py/claudeops/providers/agy_provider.py:380) | `agy.rs::{refresh, parse_models}` (`ModelIo::run_stdout`; gerçek süreç G8) | `parity.rs::parity_model_sources` `src-agy-bicim` `src-agy-cikis-kodu` `src-agy-rastgele-` (Python hatası? G7 şüphe 8) | TAŞINDI |
| `AgyProvider.model_choices` (py/claudeops/providers/agy_provider.py:394) | `provider.rs::Providers::model_choices` (`ModelCatalog::agy_models`) | `parity.rs::parity_model_effort` `agy-models`; canlı liste `parity_model_sources` `src-agy-` | TAŞINDI |
| `AgyProvider.permission_modes` (py/claudeops/providers/agy_provider.py:411) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.effort_levels` (py/claudeops/providers/agy_provider.py:414) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.model_effort_levels` (py/claudeops/providers/agy_provider.py:417) | `agy.rs::model_effort_levels` | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyProvider.busy_status_pattern` (py/claudeops/providers/agy_provider.py:430) | `live.rs::Cli::busy_status_pattern` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `AgyProvider.usage_command` (py/claudeops/providers/agy_provider.py:433) | `usage.rs::Cli::usage_command` | `parity.rs::parity_usage` `usage-agy` | TAŞINDI |
| `AgyProvider.usage_fresh_argv` (py/claudeops/providers/agy_provider.py:444) | `usage.rs::Providers::usage_fresh_argv` | `parity.rs::parity_usage` `usage-agy` `usage-bin-*-agy` | TAŞINDI |
| `AgyProvider.usage_auth_missing` (py/claudeops/providers/agy_provider.py:449) | `usage.rs::Cli::usage_auth_missing` | `parity.rs::parity_usage` `usage-agy` (giriş iletisi metinleri) | TAŞINDI |
| `AgyProvider.parse_fresh_usage` (py/claudeops/providers/agy_provider.py:454) | `usage.rs::Cli::parse_fresh_usage` (-> `agy_usage`) | `parity.rs::parity_usage` `usage-agy` | TAŞINDI |
| `AgyProvider.usage_needs_dismiss` (py/claudeops/providers/agy_provider.py:457) | `usage.rs::Cli::usage_needs_dismiss` | `parity.rs::parity_usage` `usage-agy` | TAŞINDI |
| `AgyProvider.parse_usage_text` (py/claudeops/providers/agy_provider.py:467) | `usage.rs::agy_usage` (`Cli::parse_usage_text`, `py_isdigit`) | `parity.rs::parity_usage` `usage-agy` | TAŞINDI |
| `AgyProvider._transcript_steps` (py/claudeops/providers/agy_provider.py:498) | `chat.rs::Live::agy_db`/`agy_steps` + `agy_step` | `parity.rs::parity_chat` `agy-` | TAŞINDI |
| `AgyProvider._steps_desc` (py/claudeops/providers/agy_provider.py:528) | `chat.rs::Live::agy_steps` (`AGY_STEPS_DESC_SQL`) | `parity.rs::parity_chat` `agy-son-cift` `agy-sapma-utf8-hucre` | TAŞINDI |
| `AgyProvider.last_exchange` (py/claudeops/providers/agy_provider.py:554) | `chat.rs::Live::agy_last` | `parity.rs::parity_chat` `agy-` | TAŞINDI |
| `AgyProvider.full_history` (py/claudeops/providers/agy_provider.py:573) | `chat.rs::Live::agy_history` | `parity.rs::parity_chat` `agy-` | TAŞINDI |
| `AgyProvider.sid_for_stopped_session` (py/claudeops/providers/agy_provider.py:591) | `agy_resume.rs::Live::agy_stopped_sid` | `parity.rs::parity_resume` `devam-agy-ogrenilen-` | TAŞINDI |
| `AgyProvider.snapshot_for_live_sid` (py/claudeops/providers/agy_provider.py:601) | `resume.rs::Live::snapshot_for_live_sid` | `parity.rs::parity_resume` `devam-agy-konusmalar` `devam-diger` | TAŞINDI |
| `AgyProvider.discover_live_sid` (py/claudeops/providers/agy_provider.py:611) | `agy_resume.rs::Live::agy_discover` | `parity.rs::parity_resume` `devam-agy-konusmalar` `devam-agy-dizin-yok` | TAŞINDI |
| `cmd_arg` (py/claudeops/providers/base.py:20) | `rs/proc` `providers.rs::arg` | rs/proc: `providers.rs::claude_info` | KAPSAM DIŞI |
| `OneshotError` (py/claudeops/providers/base.py:28) | `oneshot.rs::OneshotError` | `parity.rs::parity_oneshot` `argv-` `ucli-` | TAŞINDI |
| `McpServerSpec` (py/claudeops/providers/base.py:33) | `provider.rs::McpSpec` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.name` (py/claudeops/providers/base.py:44) | `provider.rs::McpSpec::name` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.command` (py/claudeops/providers/base.py:45) | `provider.rs::McpSpec::command` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.args` (py/claudeops/providers/base.py:46) | `provider.rs::McpSpec::args` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.allowed_tools` (py/claudeops/providers/base.py:49) | `provider.rs::McpSpec::allowed_tools` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `CliProvider` (py/claudeops/providers/base.py:52) | `provider.rs::{Cli, Providers}` (spawn tarafı) | `parity.rs::parity_model_effort` `bos-*` `ayar-*`; yalnız satırlarında TAŞINDI yazan yöntemler | TAŞINDI |
| `CliProvider.name` (py/claudeops/providers/base.py:53) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.accepts_cli_opts` (py/claudeops/providers/base.py:57) | `provider.rs::Cli::accepts_cli_opts` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.mcp_needs_cwd` (py/claudeops/providers/base.py:61) | `provider.rs::Cli::mcp_needs_cwd` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.validate_cli_opts` (py/claudeops/providers/base.py:63) | `provider.rs::Providers::validate_cli_opts` | `parity.rs::parity_ucli` `opts-*`; ucli dışı ret: `parity_spawn` `claude-opts`; ret metni için ayrı vaka yok | TAŞINDI |
| `CliProvider.resolve_resume_id` (py/claudeops/providers/base.py:70) | `resume.rs::Live::resolve_resume_id` (soyut yöntem: kapsayıcı `match`) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `CliProvider.build_inner_command` (py/claudeops/providers/base.py:92) | `provider.rs::Providers::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra` | TAŞINDI |
| `CliProvider.has_conversation` (py/claudeops/providers/base.py:113) | `tui.rs::Cli::has_conversation` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.wants_handover_wrapup` (py/claudeops/providers/base.py:121) | `tui.rs::Cli::wants_handover_wrapup` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.wants_stuck_recovery` (py/claudeops/providers/base.py:125) | `tui.rs::Cli::wants_stuck_recovery` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.last_exchange` (py/claudeops/providers/base.py:129) | `chat.rs::Live::last_exchange` (`Cli::Shell` None) | `parity.rs::parity_chat` `shell-` | TAŞINDI |
| `CliProvider.full_history` (py/claudeops/providers/base.py:138) | `chat.rs::Live::full_history` (`Cli::Shell` None) | `parity.rs::parity_chat` `shell-` | TAŞINDI |
| `CliProvider.sid_for_stopped_session` (py/claudeops/providers/base.py:147) | `resume.rs::Live::sid_for_stopped_session` (varsayılan None) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `CliProvider.last_message_role` (py/claudeops/providers/base.py:162) | `chat.rs::Live::last_message_role` | `parity.rs::parity_chat` `chat-` (her vakada) | TAŞINDI |
| `CliProvider.handover_model_downgrade` (py/claudeops/providers/base.py:175) | `tui.rs::Cli::handover_model_downgrade` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.apply_live_model_switch` (py/claudeops/providers/base.py:185) | `tui.rs::Cli::apply_live_model_switch` (`SwitchOutcome`) | `parity.rs::parity_tui` `g4-pane-model-` `g4-pane-rastgele-` | TAŞINDI |
| `CliProvider.handover_effort_downgrade` (py/claudeops/providers/base.py:193) | `tui.rs::Cli::handover_effort_downgrade` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.apply_live_effort_switch` (py/claudeops/providers/base.py:200) | `tui.rs::Cli::apply_live_effort_switch` (`SwitchOutcome`) | `parity.rs::parity_tui` `g4-pane-effort-` `g4-pane-rastgele-` | TAŞINDI |
| `CliProvider.prompt_cache_ttl_seconds` (py/claudeops/providers/base.py:206) | `claude_transcript.rs::Cli::prompt_cache_ttl_seconds` (claude dışı None) | `parity.rs::parity_transcript` `model-listesi` `istek-`; `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `CliProvider.last_request_epoch` (py/claudeops/providers/base.py:218) | `claude_transcript.rs::Live::last_request_epoch` (claude dışı None) | `parity.rs::parity_transcript` `istek-codex` `istek-ucli` | TAŞINDI |
| `CliProvider.effort_switch_keeps_cache` (py/claudeops/providers/base.py:226) | `claude_transcript.rs::Cli::effort_switch_keeps_cache` (claude dışı true) | `parity.rs::parity_transcript` `model-listesi` | TAŞINDI |
| `CliProvider.dismiss_stray_dialog` (py/claudeops/providers/base.py:233) | `tui.rs::Cli::dismiss_stray_dialog` | `parity.rs::parity_tui` `g4-pane-dialog-` `g4-pane-rastgele-` | TAŞINDI |
| `CliProvider.input_settle_delay` (py/claudeops/providers/base.py:252) | `tui.rs::Cli::input_settle_delay` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.prepare_input` (py/claudeops/providers/base.py:264) | `tui.rs::Cli::prepare_input` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.compact_command` (py/claudeops/providers/base.py:269) | `tui.rs::Cli::compact_command` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.usage_fresh_argv` (py/claudeops/providers/base.py:284) | `usage.rs::Providers::usage_fresh_argv` (varsayılan kol None) | `parity.rs::parity_usage` `usage-codex` `usage-shell` `usage-ucli` `usage-copilot` | TAŞINDI |
| `CliProvider.usage_fresh_tui_argv` (py/claudeops/providers/base.py:290) | `usage.rs::Providers::usage_fresh_tui_argv` (varsayılan kol None) | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.usage_auth_missing` (py/claudeops/providers/base.py:295) | `usage.rs::Cli::usage_auth_missing` (agy dışı false) | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.parse_fresh_usage` (py/claudeops/providers/base.py:299) | `usage.rs::Cli::parse_fresh_usage` (claude dışı `parse_usage_text`) | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.usage_command` (py/claudeops/providers/base.py:303) | `usage.rs::Cli::usage_command` (varsayılan kol None) | `parity.rs::parity_usage` `usage-codex` `usage-shell` `usage-ucli` | TAŞINDI |
| `CliProvider.parse_usage_text` (py/claudeops/providers/base.py:319) | `usage.rs::Cli::parse_usage_text` (varsayılan kol None) | `parity.rs::parity_usage` `usage-codex` `usage-shell` `usage-ucli` | TAŞINDI |
| `CliProvider.context_command` (py/claudeops/providers/base.py:330) | `usage.rs::Cli::context_command` (varsayılan kol None) | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.parse_context_text` (py/claudeops/providers/base.py:344) | `usage.rs::Cli::parse_context_text` (varsayılan kol None) | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.context_needs_dismiss` (py/claudeops/providers/base.py:356) | `usage.rs::Cli::context_needs_dismiss` | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.usage_needs_dismiss` (py/claudeops/providers/base.py:367) | `usage.rs::Cli::usage_needs_dismiss` (varsayılan kol false) | `parity.rs::parity_usage` `usage-*` | TAŞINDI |
| `CliProvider.extra_file_roots` (py/claudeops/providers/base.py:379) | `chat.rs::Live::extra_file_roots` | `parity.rs::parity_chat` `chat-kok-` | TAŞINDI |
| `CliProvider.env_overrides` (py/claudeops/providers/base.py:394) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.mcp_launch_args` (py/claudeops/providers/base.py:410) | `provider.rs::Providers::mcp_launch_args` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `CliProvider.mcp_setup_command` (py/claudeops/providers/base.py:421) | `provider.rs::Providers::mcp_setup_command` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `CliProvider.oneshot_argv` (py/claudeops/providers/base.py:433) | `provider.rs::Providers::oneshot_argv` | `parity.rs::parity_build` `oneshot` | TAŞINDI |
| `CliProvider.oneshot` (py/claudeops/providers/base.py:440) | `real/oneshot.rs::OneShot::{oneshot, run_argv}`, `oneshot.rs::argv_result` | `parity.rs::parity_oneshot` `argv-` `claude` `desteklemeyen`; `tests/real_oneshot.rs` | TAŞINDI |
| `CliProvider.matches_proc` (py/claudeops/providers/base.py:464) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` (taban sözleşmesi) | KAPSAM DIŞI |
| `CliProvider.extract_name` (py/claudeops/providers/base.py:468) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) (taban sözleşmesi) | KAPSAM DIŞI |
| `CliProvider.extract_info` (py/claudeops/providers/base.py:473) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` (taban sözleşmesi) | KAPSAM DIŞI |
| `CliProvider.model_choices` (py/claudeops/providers/base.py:485) | `provider.rs::Providers::model_choices` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.refresh_stored_model` (py/claudeops/providers/base.py:488) | `provider.rs::Providers::refresh_stored_model` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.permission_modes` (py/claudeops/providers/base.py:497) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.effort_levels` (py/claudeops/providers/base.py:501) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.model_effort_levels` (py/claudeops/providers/base.py:504) | `provider.rs::Providers::model_effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.effort_levels_for` (py/claudeops/providers/base.py:514) | `provider.rs::Providers::effort_levels_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.default_permission_mode` (py/claudeops/providers/base.py:520) | `provider.rs::Cli::default_permission_mode` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.preferred_default_model` (py/claudeops/providers/base.py:525) | `provider.rs::Providers::preferred_default_model` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.default_effort` (py/claudeops/providers/base.py:530) | `provider.rs::Cli::default_effort` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.resolve_effort` (py/claudeops/providers/base.py:536) | `provider.rs::Providers::resolve_effort` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.mode_status_patterns` (py/claudeops/providers/base.py:548) | `tui.rs::Cli::mode_status_patterns` | `parity.rs::parity_tui` `g4-sabit-`, `g4-mod-` | TAŞINDI |
| `CliProvider.busy_status_pattern` (py/claudeops/providers/base.py:555) | `live.rs::Cli::busy_status_pattern` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.background_work` (py/claudeops/providers/base.py:565) | `live.rs::Live::background_work` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.live_busy` (py/claudeops/providers/base.py:571) | `live.rs::Live::live_busy` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.live_tools` (py/claudeops/providers/base.py:584) | `live.rs::Live::live_tools` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.live_context` (py/claudeops/providers/base.py:589) | `live.rs::Live::live_context` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.live_usage` (py/claudeops/providers/base.py:596) | `live.rs::Live::live_usage` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.live_failed_turns` (py/claudeops/providers/base.py:606) | `live.rs::Live::live_failed_turns` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.live_phase` (py/claudeops/providers/base.py:611) | `live.rs::Live::live_phase` (varsayılan kol: None) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CliProvider.cyclable_modes` (py/claudeops/providers/base.py:620) | `tui.rs::Cli::cyclable_modes` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CliProvider.snapshot_for_live_sid` (py/claudeops/providers/base.py:629) | `resume.rs::Live::snapshot_for_live_sid` (varsayılan None) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `CliProvider.discover_live_sid` (py/claudeops/providers/base.py:650) | `resume.rs::Live::discover_live_sid` (varsayılan None) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `MODEL_CHOICES` (py/claudeops/providers/claude_provider.py:18) | `claude.rs::MODEL_CHOICES` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `PERMISSION_MODES` (py/claudeops/providers/claude_provider.py:24) | `claude.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/claude_provider.py:25) | `claude.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `_SONNET_PIN_RE` (py/claudeops/providers/claude_provider.py:29) | `claude.rs::SONNET_PIN` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `_sonnet_version` (py/claudeops/providers/claude_provider.py:32) | `claude.rs::sonnet_version` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `_USAGE_HEADER_RE` (py/claudeops/providers/claude_provider.py:39) | `usage.rs::USAGE_HEADER` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `_USAGE_PERCENT_RE` (py/claudeops/providers/claude_provider.py:40) | `usage.rs::USAGE_PERCENT` | `parity.rs::parity_usage` `usage-claude`; birim `usage.rs::tests::python_classes` | TAŞINDI |
| `_USAGE_RESETS_RE` (py/claudeops/providers/claude_provider.py:41) | `usage.rs::USAGE_RESETS` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `_USAGE_FRESH_RE` (py/claudeops/providers/claude_provider.py:43) | `usage.rs::USAGE_FRESH` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `_CONTEXT_TOTAL_RE` (py/claudeops/providers/claude_provider.py:48) | `usage.rs::CONTEXT_TOTAL` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `_CONTEXT_CATEGORY_RE` (py/claudeops/providers/claude_provider.py:49) | `usage.rs::CONTEXT_CATEGORY` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `MODE_STATUS_PATTERNS` (py/claudeops/providers/claude_provider.py:61) | `claude.rs::MODE_STATUS_PATTERNS` | `parity.rs::parity_tui` `g4-sabit-claude`, `g4-mod-claude` | TAŞINDI |
| `CYCLABLE_MODES` (py/claudeops/providers/claude_provider.py:73) | `claude.rs::CYCLABLE_MODES` | `parity.rs::parity_tui` `g4-sabit-claude` | TAŞINDI |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/claude_provider.py:80) | `claude.rs::BUSY_STATUS_PATTERN` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `_encode_cwd` (py/claudeops/providers/claude_provider.py:83) | `rs/proc` `transcript.rs::encode_cwd` | rs/proc: `transcript.rs::encodes_non_ascii_per_char`, altın ad+cwd kodlama | KAPSAM DIŞI |
| `_safe_mtime` (py/claudeops/providers/claude_provider.py:102) | `resume.rs::Live::safe_mtime` | `parity.rs::parity_resume` `devam-claude-zaman-` `devam-claude-adlar` | TAŞINDI |
| `jsonl_path_for` (py/claudeops/providers/claude_provider.py:110) | `claude_resume.rs::Live::jsonl_path_for` | `parity.rs::parity_resume` `devam-claude-`; `tests/resume.rs::sidless_or_missing_transcript_falls_back_to_the_newest` | TAŞINDI |
| `find_latest_jsonl` (py/claudeops/providers/claude_provider.py:125) | `claude_resume.rs::Live::find_latest_jsonl` | `parity.rs::parity_resume` `devam-claude-` | TAŞINDI |
| `_LAST_MODEL_CHUNK_BYTES` (py/claudeops/providers/claude_provider.py:143) | `claude_transcript.rs::FIRST_WINDOW_BYTES` | `parity.rs::parity_transcript` `pencere-` (`constants`) | TAŞINDI |
| `_LAST_MODEL_MAX_BYTES` (py/claudeops/providers/claude_provider.py:144) | `claude_transcript.rs::MAX_WINDOW_BYTES` | `parity.rs::parity_transcript` `pencere-` (`constants`) | TAŞINDI |
| `_row_epoch` (py/claudeops/providers/claude_provider.py:147) | `bg_work.rs::iso_epoch` | `parity.rs::parity_transcript` `damga-listesi-` `damga-` | TAŞINDI |
| `_last_assistant_value` (py/claudeops/providers/claude_provider.py:158) | `claude_transcript.rs::Live::last_assistant_value` | `parity.rs::parity_transcript` `pencere-` `satir-` `rastgele-` | TAŞINDI |
| `last_assistant_model` (py/claudeops/providers/claude_provider.py:208) | `claude_transcript.rs::Live::last_assistant_model` | `parity.rs::parity_transcript` `satir-` `rastgele-` `sapma-model-` | TAŞINDI |
| `last_assistant_effort` (py/claudeops/providers/claude_provider.py:214) | `claude_transcript.rs::Live::last_assistant_effort` | `parity.rs::parity_transcript` `satir-` `rastgele-` `pencere-effort-` | TAŞINDI |
| `PROMPT_CACHE_TTL_SECONDS` (py/claudeops/providers/claude_provider.py:228) | `claude_transcript.rs::PROMPT_CACHE_TTL_SECONDS` | `parity.rs::parity_transcript` `model-listesi` (`ttl`) | TAŞINDI |
| `_real_request_epoch` (py/claudeops/providers/claude_provider.py:231) | `claude_transcript.rs::real_request_epoch` | `parity.rs::parity_transcript` `kullanim-` `istek-model-` `damga-` | TAŞINDI |
| `last_real_request_epoch` (py/claudeops/providers/claude_provider.py:254) | `claude_transcript.rs::Live::last_real_request_epoch` | `parity.rs::parity_transcript` `son-istek` `alt-ajan` `pencere-` `yollar` | TAŞINDI |
| `session_file_sid` (py/claudeops/providers/claude_provider.py:260) | `claude_resume.rs::Live::session_file_sid` | `parity.rs::parity_resume` `devam-kayit-` `devam-stat-` | TAŞINDI |
| `_EFFORT_BUSTS_CACHE_RE` (py/claudeops/providers/claude_provider.py:293) | `claude_transcript.rs::EFFORT_BUSTS_CACHE` | `parity.rs::parity_transcript` `model-listesi` | TAŞINDI |
| `live_or_spawn_model` (py/claudeops/providers/claude_provider.py:296) | `claude_transcript.rs::Live::live_or_spawn_model` | `parity.rs::parity_transcript` `canli` | TAŞINDI |
| `live_or_spawn_effort` (py/claudeops/providers/claude_provider.py:315) | `claude_transcript.rs::Live::live_or_spawn_effort` | `parity.rs::parity_transcript` `canli` | TAŞINDI |
| `_META_HEAD_LINES` (py/claudeops/providers/claude_provider.py:331) | `claude_resume.rs::META_HEAD_LINES` | `parity.rs::parity_resume` `devam-diger` `devam-meta-` | TAŞINDI |
| `_RESUME_SCAN_LIMIT` (py/claudeops/providers/claude_provider.py:334) | `claude_resume.rs::RESUME_SCAN_LIMIT` | `parity.rs::parity_resume` `devam-diger` `devam-claude-sinir-` | TAŞINDI |
| `_jsonl_meta` (py/claudeops/providers/claude_provider.py:337) | `claude_resume.rs::Live::jsonl_meta` + `resume.rs::Live::head_lines` | `parity.rs::parity_resume` `devam-meta-`; `tests/resume.rs::head_reading_is_bounded_and_drops_the_unfinished_line` | TAŞINDI |
| `_same_path` (py/claudeops/providers/claude_provider.py:364) | `resume.rs::Live::same_path` + `pyfmt.rs::{abspath, normpath}` | `parity.rs::parity_resume` `devam-claude-cwd`; `pyfmt::tests::path_normalisation` | TAŞINDI |
| `_META_CACHE` (py/claudeops/providers/claude_provider.py:372) | `claude_resume.rs::MetaCache` | `tests/resume.rs::unchanged_files_are_not_reread_but_changed_ones_are` | TAŞINDI |
| `_META_CACHE_MAX` (py/claudeops/providers/claude_provider.py:373) | `claude_resume.rs::META_CACHE_MAX` | `parity.rs::parity_resume` `devam-diger`; `tests/resume.rs::meta_cache_is_bounded` | TAŞINDI |
| `_jsonl_meta_cached` (py/claudeops/providers/claude_provider.py:376) | `claude_resume.rs::MetaCache::get` | `tests/resume.rs::unchanged_files_are_not_reread_but_changed_ones_are` | TAŞINDI |
| `_STUB_MAX_BYTES` (py/claudeops/providers/claude_provider.py:391) | `claude_resume.rs::STUB_MAX_BYTES` | `parity.rs::parity_resume` `devam-diger` `devam-claude-stub-` | TAŞINDI |
| `_has_chat_rows` (py/claudeops/providers/claude_provider.py:394) | `claude_resume.rs::Live::has_chat_rows` | `parity.rs::parity_resume` `devam-meta-` | TAŞINDI |
| `MCP_CONFIG_PATH` (py/claudeops/providers/claude_provider.py:414) | `probe.rs::Paths::mcp_config` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `_mcp_config_path` (py/claudeops/providers/claude_provider.py:417) | `claude.rs::mcp_config_path` | `parity.rs::parity_spawn` `-mcp` `-eklenti-mcp`; beyin/eklenti dosya adı dalları | TAŞINDI |
| `_write_mcp_config_file` (py/claudeops/providers/claude_provider.py:431) | `claude.rs::{mcp_config_json, mcp_launch_args}` + `Effect::WriteAtomic` | `parity.rs::parity_build` `mcp-orchestration-dosya` `mcp-orchestration-engel`; dosya yazımı yalnız test uygulayıcısında (G8) | TAŞINDI |
| `_extract_text` (py/claudeops/providers/claude_provider.py:440) | `chat.rs::claude_text` | `parity.rs::parity_chat` `claude-icerik-` `claude-ozet-` | TAŞINDI |
| `_is_real_user_text` (py/claudeops/providers/claude_provider.py:452) | `chat.rs::claude_real_user` | `parity.rs::parity_chat` `claude-icerik-` | TAŞINDI |
| `_HELP_CACHE` (py/claudeops/providers/claude_provider.py:466) | `real/help.rs::{HelpCache, HELP_TIMEOUT}` (`RealProbe::claude_help`) | `parity.rs::parity_real` `yardim`; `tests/real_process.rs::empty_failed_slow_huge_or_non_utf8_help_is_not_cached` | TAŞINDI |
| `_HELP_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:467) | `real/help.rs::{HelpCache, HELP_TIMEOUT}` (`RealProbe::claude_help`) | `parity.rs::parity_real` `yardim`; `tests/real_process.rs::empty_failed_slow_huge_or_non_utf8_help_is_not_cached` | TAŞINDI |
| `claude_help_text` (py/claudeops/providers/claude_provider.py:470) | `real/help.rs::{HelpCache, HELP_TIMEOUT}` (`RealProbe::claude_help`) | `parity.rs::parity_real` `yardim`; `tests/real_process.rs::empty_failed_slow_huge_or_non_utf8_help_is_not_cached` | TAŞINDI |
| `claude_supports_flag` (py/claudeops/providers/claude_provider.py:492) | `claude.rs::supports_flag` (`ucli.rs::find_flag`) | `parity.rs::parity_build` `oneshot` | TAŞINDI |
| `ClaudeProvider` (py/claudeops/providers/claude_provider.py:498) | `claude.rs` + `provider.rs::Cli::Claude` | `parity.rs::parity_build` `claude-extra` `claude-routing-` | TAŞINDI |
| `ClaudeProvider.name` (py/claudeops/providers/claude_provider.py:499) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.resolve_resume_id` (py/claudeops/providers/claude_provider.py:501) | `claude_resume.rs::Live::claude_resume_id` | `parity.rs::parity_resume` `devam-claude-` | TAŞINDI |
| `ClaudeProvider.build_inner_command` (py/claudeops/providers/claude_provider.py:545) | `claude.rs::build_inner_command` | `parity.rs::parity_build` `claude-extra` `claude-routing-` `claude-bilinen` | TAŞINDI |
| `ClaudeProvider.oneshot_argv` (py/claudeops/providers/claude_provider.py:586) | `claude.rs::oneshot_argv` | `parity.rs::parity_build` `oneshot` | TAŞINDI |
| `ClaudeProvider.mcp_launch_args` (py/claudeops/providers/claude_provider.py:602) | `claude.rs::mcp_launch_args` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `ClaudeProvider.compact_command` (py/claudeops/providers/claude_provider.py:610) | `tui.rs::Cli::compact_command` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `ClaudeProvider.usage_command` (py/claudeops/providers/claude_provider.py:613) | `usage.rs::Cli::usage_command` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.usage_needs_dismiss` (py/claudeops/providers/claude_provider.py:616) | `usage.rs::Cli::usage_needs_dismiss` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.parse_usage_text` (py/claudeops/providers/claude_provider.py:624) | `usage.rs::claude_usage` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.usage_fresh_argv` (py/claudeops/providers/claude_provider.py:666) | `usage.rs::Providers::usage_fresh_argv` | `parity.rs::parity_usage` `usage-claude` `usage-bin-*-claude` | TAŞINDI |
| `ClaudeProvider.parse_fresh_usage` (py/claudeops/providers/claude_provider.py:669) | `usage.rs::claude_fresh_usage` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.context_command` (py/claudeops/providers/claude_provider.py:678) | `usage.rs::Cli::context_command` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.context_needs_dismiss` (py/claudeops/providers/claude_provider.py:681) | `usage.rs::Cli::context_needs_dismiss` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.parse_context_text` (py/claudeops/providers/claude_provider.py:687) | `usage.rs::claude_context` | `parity.rs::parity_usage` `usage-claude` | TAŞINDI |
| `ClaudeProvider.handover_model_downgrade` (py/claudeops/providers/claude_provider.py:744) | `tui.rs::Cli::handover_model_downgrade` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `ClaudeProvider._MODEL_SWITCH_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:761) | `tui.rs::MODEL_SWITCH_TIMEOUT_SECONDS` | `parity.rs::parity_tui` `g4-pane-model-` (`sinir-`) | TAŞINDI |
| `ClaudeProvider._MODEL_SWITCH_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:762) | `tui.rs::MODEL_SWITCH_POLL_SECONDS` | `parity.rs::parity_tui` `g4-pane-model-` (`sinir-`) | TAŞINDI |
| `ClaudeProvider.apply_live_model_switch` (py/claudeops/providers/claude_provider.py:764) | `tui.rs::Cli::apply_live_model_switch` (`SwitchOutcome`) | `parity.rs::parity_tui` `g4-pane-model-` `g4-pane-rastgele-` | TAŞINDI |
| `ClaudeProvider.handover_effort_downgrade` (py/claudeops/providers/claude_provider.py:824) | `tui.rs::Cli::handover_effort_downgrade` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `ClaudeProvider.prompt_cache_ttl_seconds` (py/claudeops/providers/claude_provider.py:837) | `claude_transcript.rs::Cli::prompt_cache_ttl_seconds` | `parity.rs::parity_transcript` `model-listesi` (`ttl`) | TAŞINDI |
| `ClaudeProvider.last_request_epoch` (py/claudeops/providers/claude_provider.py:840) | `claude_transcript.rs::Live::last_request_epoch` | `parity.rs::parity_transcript` `istek-claude` `istek-mutlak` `sapma-uzun-sid` | TAŞINDI |
| `ClaudeProvider.effort_switch_keeps_cache` (py/claudeops/providers/claude_provider.py:859) | `claude_transcript.rs::Cli::effort_switch_keeps_cache` | `parity.rs::parity_transcript` `model-listesi` | TAŞINDI |
| `ClaudeProvider._EFFORT_SWITCH_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:862) | `tui.rs::EFFORT_SWITCH_TIMEOUT_SECONDS` | `parity.rs::parity_tui` `g4-pane-effort-` (`sinir-`) | TAŞINDI |
| `ClaudeProvider._EFFORT_SWITCH_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:863) | `tui.rs::EFFORT_SWITCH_POLL_SECONDS` | `parity.rs::parity_tui` `g4-pane-effort-` (`sinir-`) | TAŞINDI |
| `ClaudeProvider._EFFORT_SWITCH_DONE_MARKERS` (py/claudeops/providers/claude_provider.py:864) | `tui.rs::EFFORT_SWITCH_DONE_MARKERS` | `parity.rs::parity_tui` `g4-pane-effort-` | TAŞINDI |
| `ClaudeProvider.apply_live_effort_switch` (py/claudeops/providers/claude_provider.py:867) | `tui.rs::Cli::apply_live_effort_switch` (`SwitchOutcome`) | `parity.rs::parity_tui` `g4-pane-effort-` `g4-pane-rastgele-` | TAŞINDI |
| `ClaudeProvider._STRAY_DIALOG_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:926) | `tui.rs::STRAY_DIALOG_TIMEOUT_SECONDS` | `parity.rs::parity_tui` `g4-pane-dialog-` (`sinir-`) | TAŞINDI |
| `ClaudeProvider._STRAY_DIALOG_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:927) | `tui.rs::STRAY_DIALOG_POLL_SECONDS` | `parity.rs::parity_tui` `g4-pane-dialog-` (`sinir-`) | TAŞINDI |
| `ClaudeProvider.dismiss_stray_dialog` (py/claudeops/providers/claude_provider.py:929) | `tui.rs::Cli::dismiss_stray_dialog` | `parity.rs::parity_tui` `g4-pane-dialog-` `g4-pane-rastgele-` | TAŞINDI |
| `_Switch` (py/claudeops/providers/base.py:25) | `tui.rs::{SwitchOutcome, DismissOutcome}` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SWITCH_CAPTURE_LINES` (py/claudeops/providers/claude_provider.py:89) | `tui.rs::SWITCH_CAPTURE_LINES` | `parity.rs::parity_tui` `g4-pane-model-` | TAŞINDI |
| `_SWITCH_TITLES` (py/claudeops/providers/claude_provider.py:90) | `tui.rs::{MODEL_SWITCH_DIALOG, EFFORT_SWITCH_DIALOG}` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SWITCH_YES_RE` (py/claudeops/providers/claude_provider.py:91) | `tui.rs::{SWITCH_YES_RE, open_switch_dialog}` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SWITCH_NO_RE` (py/claudeops/providers/claude_provider.py:92) | `tui.rs::{SWITCH_NO_RE, open_switch_dialog}` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SWITCH_GUIDE_RE` (py/claudeops/providers/claude_provider.py:93) | `tui.rs::{SWITCH_GUIDE_RE, open_switch_dialog}` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SWITCH_GUIDE_MAX` (py/claudeops/providers/claude_provider.py:94) | `tui.rs::SWITCH_GUIDE_MAX` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SWITCH_TITLE_WINDOW` (py/claudeops/providers/claude_provider.py:95) | `tui.rs::SWITCH_TITLE_WINDOW` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_SCREEN_FRAME` (py/claudeops/providers/claude_provider.py:96) | `tui.rs::screen_rows` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_BOX_FOOTER_MAX` (py/claudeops/providers/claude_provider.py:97) | `tui.rs::BOX_FOOTER_MAX` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_FOOTER_MENU_RE` (py/claudeops/providers/claude_provider.py:98) | `tui.rs::FOOTER_MENU_RE` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_BUSY_TAIL_LINES` (py/claudeops/providers/claude_provider.py:99) | `tui.rs::BUSY_TAIL_LINES` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_screen_rows` (py/claudeops/providers/claude_provider.py:102) | `tui.rs::screen_rows` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_open_switch_dialog` (py/claudeops/providers/claude_provider.py:108) | `tui.rs::open_switch_dialog` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_switch_label_matches` (py/claudeops/providers/claude_provider.py:130) | `tui.rs::label_matches` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_switch_pane_state` (py/claudeops/providers/claude_provider.py:137) | `tui.rs::pane_state` | `parity.rs::parity_tui` `g4-ekran-` | TAŞINDI |
| `_live_switch` (py/claudeops/providers/claude_provider.py:163) | `tui.rs::{run_switch, Run::look}` | `parity.rs::parity_tui` `g4-ekran-` `g4-pane-` | TAŞINDI |
| `_claudeops_price` (py/claudeops/providers/ucli_provider.py:614) | `ucli.rs::claudeops_price` (tablo `cops_review_core::targets`) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `_argv_model` (py/claudeops/providers/ucli_provider.py:627) | `ucli.rs::{value_after, Ctx::apply_cli_opts}` | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `_has_price` (py/claudeops/providers/ucli_provider.py:631) | `ucli.rs::has_price` | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `ClaudeProvider.matches_proc` (py/claudeops/providers/claude_provider.py:970) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `ClaudeProvider.extract_name` (py/claudeops/providers/claude_provider.py:975) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `ClaudeProvider.extract_info` (py/claudeops/providers/claude_provider.py:978) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `ClaudeProvider.preferred_default_model` (py/claudeops/providers/claude_provider.py:986) | `claude.rs::newest_sonnet` | `parity.rs::parity_model_effort` `claude-state` | TAŞINDI |
| `ClaudeProvider.default_effort` (py/claudeops/providers/claude_provider.py:992) | `provider.rs::Cli::default_effort` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.model_choices` (py/claudeops/providers/claude_provider.py:995) | `claude.rs::model_choices` | `parity.rs::parity_model_effort` `claude-state` `claude-state-bozuk`; belge `ModelIo::claude_models_doc` (G7) | TAŞINDI |
| `ClaudeProvider.refresh_stored_model` (py/claudeops/providers/claude_provider.py:1010) | `claude.rs::refresh_stored_model` | `parity.rs::parity_model_effort` `claude-state` | TAŞINDI |
| `ClaudeProvider.permission_modes` (py/claudeops/providers/claude_provider.py:1029) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.effort_levels` (py/claudeops/providers/claude_provider.py:1032) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.mode_status_patterns` (py/claudeops/providers/claude_provider.py:1035) | `tui.rs::Cli::mode_status_patterns` | `parity.rs::parity_tui` `g4-sabit-`, `g4-mod-` | TAŞINDI |
| `ClaudeProvider.background_work` (py/claudeops/providers/claude_provider.py:1038) | `live.rs::Live::background_work` | `parity.rs::parity_live` `claude-`, `ekran-claude-` (transkript yolu `claude_resume.rs::Live::jsonl_path_for`) | TAŞINDI |
| `ClaudeProvider.busy_status_pattern` (py/claudeops/providers/claude_provider.py:1048) | `live.rs::Cli::busy_status_pattern` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `ClaudeProvider.cyclable_modes` (py/claudeops/providers/claude_provider.py:1051) | `tui.rs::Cli::cyclable_modes` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `ClaudeProvider._transcript_lines` (py/claudeops/providers/claude_provider.py:1054) | `chat.rs::Live::transcript_bytes` + `raw_lines`/`object_line` (yol: `Live::jsonl_path_for`) | `parity.rs::parity_chat` `claude-satir-` `claude-kesik-` | TAŞINDI |
| `ClaudeProvider.last_exchange` (py/claudeops/providers/claude_provider.py:1080) | `chat.rs::claude_last` | `parity.rs::parity_chat` `chat-claude-` | TAŞINDI |
| `ClaudeProvider.extra_file_roots` (py/claudeops/providers/claude_provider.py:1110) | `chat.rs::Live::extra_file_roots` (dizin: `LiveProbe::claude_project_dir`, rs/proc) | `parity.rs::parity_chat` `chat-kok-claude-` | TAŞINDI |
| `ClaudeProvider.full_history` (py/claudeops/providers/claude_provider.py:1115) | `chat.rs::claude_history` | `parity.rs::parity_chat` `chat-claude-` | TAŞINDI |
| `ClaudeProvider.sid_for_stopped_session` (py/claudeops/providers/claude_provider.py:1144) | `claude_resume.rs::Live::claude_stopped_sid` | `parity.rs::parity_resume` `devam-claude-` | TAŞINDI |
| `CODEX_HOME` (py/claudeops/providers/codex_provider.py:42) | `probe.rs::Paths::codex_home` | `parity.rs::parity_model_sources` `src-codex-akis` | TAŞINDI |
| `SESSIONS_DIR` (py/claudeops/providers/codex_provider.py:43) | `probe.rs::Paths::codex_sessions_dir` (rollout taraması `codex_resume.rs`) | `parity.rs::parity_chat` `chat-codex-` (`roots`) | TAŞINDI |
| `MODELS_CACHE` (py/claudeops/providers/codex_provider.py:44) | `probe.rs::Paths::codex_models_cache`, `codex.rs::read_models_cache` | `parity.rs::parity_model_sources` `src-codex-akis` `src-codex-nan` (Python hatası? G7 şüphe 2) | TAŞINDI |
| `PERMISSION_MODES` (py/claudeops/providers/codex_provider.py:46) | `codex.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/codex_provider.py:47) | `codex.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/codex_provider.py:58) | `codex.rs::BUSY_STATUS_PATTERN` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `FALLBACK_MODELS` (py/claudeops/providers/codex_provider.py:62) | `codex.rs::FALLBACK_MODELS` | `parity.rs::parity_model_effort` `codex-cache-bozuk` `bos-*` | TAŞINDI |
| `_NON_SESSION_SUBCOMMANDS` (py/claudeops/providers/codex_provider.py:77) | `rs/proc` `providers.rs::CODEX_NON_SESSION` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `_PERMISSION_FLAGS` (py/claudeops/providers/codex_provider.py:84) | `codex.rs::permission_flags` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/providers/codex_provider.py:91) | `codex.rs::MODELS_TTL` | `parity.rs::parity_model_sources` `src-codex-akis` | TAŞINDI |
| `_ROLLOUT_UUID_RE` (py/claudeops/providers/codex_provider.py:92) | `codex_resume.rs::ROLLOUT_UUID` | `parity.rs::parity_resume` `devam-codex-temel` `devam-codex-adsiz-` | TAŞINDI |
| `_MAX_ROLLOUT_SCAN` (py/claudeops/providers/codex_provider.py:93) | `codex_resume.rs::MAX_ROLLOUT_SCAN` | `parity.rs::parity_resume` `devam-diger` `devam-codex-sinir-` | TAŞINDI |
| `_config_value` (py/claudeops/providers/codex_provider.py:96) | `rs/proc` `providers.rs::codex_config` | rs/proc: `providers.rs::codex_info` | KAPSAM DIŞI |
| `_safe_mtime` (py/claudeops/providers/codex_provider.py:104) | `resume.rs::Live::safe_mtime` | `parity.rs::parity_resume` `devam-codex-esit` `devam-codex-glob` | TAŞINDI |
| `_session_meta` (py/claudeops/providers/codex_provider.py:111) | `codex_resume.rs::Live::session_meta` | `parity.rs::parity_resume` `devam-codex-satir-` | TAŞINDI |
| `_rollout_sid_matches` (py/claudeops/providers/codex_provider.py, 27 Kas `fix:`) | `codex_resume.rs::Live::codex_rollout_path` (`exact`) | `parity.rs::parity_resume` `devam-codex-glob` `devam-sapma-codex-joker`; `test_rsprov_g1_fixes.py::CodexTest.test_rollout_path_needs_the_exact_id` | TAŞINDI |
| `_path_part_ok` (py/claudeops/providers/base.py, 27 Kas `fix:`) | `pyfmt.rs::is_path_part` | `parity.rs::parity_chat` `chat-agy-mutlak-kimlik` `chat-ucli-yol-disi`, `parity_live` `live-durum-yol-disi`, `parity_transcript` `transkript-istek-mutlak`; `test_rsprov_paths.py` | TAŞINDI |
| `_codex_text` (py/claudeops/providers/codex_provider.py:125) | `chat.rs::codex_text` | `parity.rs::parity_chat` `codex-icerik-` | TAŞINDI |
| `_is_real_codex_user_text` (py/claudeops/providers/codex_provider.py:139) | `chat.rs::codex_real_user` | `parity.rs::parity_chat` `codex-metin-` | TAŞINDI |
| `CodexProvider` (py/claudeops/providers/codex_provider.py:148) | `codex.rs` + `Cli::Codex` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `CodexProvider.name` (py/claudeops/providers/codex_provider.py:149) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.__init__` (py/claudeops/providers/codex_provider.py:151) | `codex.rs::ModelsCache` | `parity.rs::parity_model_sources` `src-codex-acilis` (Python hatası? G7 şüphe 1) | TAŞINDI |
| `CodexProvider.resolve_resume_id` (py/claudeops/providers/codex_provider.py:155) | `codex_resume.rs::Live::codex_resume_id` | `parity.rs::parity_resume` `devam-codex-` | TAŞINDI |
| `CodexProvider.build_inner_command` (py/claudeops/providers/codex_provider.py:178) | `codex.rs::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra` | TAŞINDI |
| `CodexProvider.mcp_launch_args` (py/claudeops/providers/codex_provider.py:196) | `codex.rs::mcp_launch_args` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `CodexProvider.env_overrides` (py/claudeops/providers/codex_provider.py:207) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.matches_proc` (py/claudeops/providers/codex_provider.py:210) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `CodexProvider.extract_name` (py/claudeops/providers/codex_provider.py:218) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `CodexProvider.extract_info` (py/claudeops/providers/codex_provider.py:225) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `CodexProvider.model_choices` (py/claudeops/providers/codex_provider.py:246) | `codex.rs::model_choices` | `parity.rs::parity_model_effort` `codex-cache`; TTL önbelleği `parity_model_sources` `src-codex-` | TAŞINDI |
| `CodexProvider.permission_modes` (py/claudeops/providers/codex_provider.py:265) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.effort_levels` (py/claudeops/providers/codex_provider.py:268) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.model_effort_levels` (py/claudeops/providers/codex_provider.py:271) | `codex.rs::model_effort_levels` | `parity.rs::parity_model_effort` `codex-cache`; ve `parity_spawn` `codex-effort` | TAŞINDI |
| `CodexProvider.busy_status_pattern` (py/claudeops/providers/codex_provider.py:292) | `live.rs::Cli::busy_status_pattern` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CodexProvider.input_settle_delay` (py/claudeops/providers/codex_provider.py:295) | `tui.rs::Cli::input_settle_delay` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `CodexProvider.background_work` (py/claudeops/providers/codex_provider.py:306) | `live.rs::Live::background_work` | `parity.rs::parity_live` `codex-ajan-`, `ekran-codex-` (rollout yolu `Live::codex_rollout_path`) | TAŞINDI |
| `CodexProvider._rollout_path` (py/claudeops/providers/codex_provider.py:317) | `codex_resume.rs::Live::codex_rollout_path` | `parity.rs::parity_resume` `devam-codex-` | TAŞINDI |
| `CodexProvider._transcript_lines` (py/claudeops/providers/codex_provider.py:336) | `chat.rs::Live::transcript_bytes` + `raw_lines`/`object_line` (yol: `Live::codex_rollout_path`) | `parity.rs::parity_chat` `codex-satir-` `codex-sid-yok` | TAŞINDI |
| `CodexProvider.live_context` (py/claudeops/providers/codex_provider.py:358) | `live.rs::Live::codex_context` | `parity.rs::parity_live` `codex-ctx-` | TAŞINDI |
| `CodexProvider.last_exchange` (py/claudeops/providers/codex_provider.py:385) | `chat.rs::codex_last` | `parity.rs::parity_chat` `chat-codex-` | TAŞINDI |
| `CodexProvider.full_history` (py/claudeops/providers/codex_provider.py:410) | `chat.rs::codex_history` | `parity.rs::parity_chat` `chat-codex-` | TAŞINDI |
| `SESSION_STORE_DB` (py/claudeops/providers/copilot_provider.py:107) | `probe.rs::Paths::copilot_session_db` | `parity.rs::parity_chat` `copilot-sohbet-` (`roots`) | TAŞINDI |
| `_BYOK_ENV_FILE` (py/claudeops/providers/copilot_provider.py:119) | `probe.rs::Paths::copilot_env_file` | `parity.rs::parity_build` `copilot-byok-` | TAŞINDI |
| `_BYOK_ENV_MANAGED_MARKER` (py/claudeops/providers/copilot_provider.py:120) | `copilot.rs::sync_byok_env_file` (`.managed`) | `parity.rs::parity_build` `byok-sil-yonetilen` `byok-elle` | TAŞINDI |
| `_sync_byok_env_file` (py/claudeops/providers/copilot_provider.py:123) | `copilot.rs::sync_byok_env_file` + `Effect` | `parity.rs::parity_build` `byok-`; yazım uygulayıcısı yalnız testte (G8) | TAŞINDI |
| `MODEL_CHOICES` (py/claudeops/providers/copilot_provider.py:157) | `copilot.rs::MODEL_CHOICES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `PERMISSION_MODES` (py/claudeops/providers/copilot_provider.py:176) | `copilot.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/copilot_provider.py:177) | `copilot.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `MODE_STATUS_PATTERNS` (py/claudeops/providers/copilot_provider.py:183) | `copilot.rs::MODE_STATUS_PATTERNS` | `parity.rs::parity_tui` `g4-sabit-copilot`, `g4-mod-copilot` | TAŞINDI |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/copilot_provider.py:187) | `copilot.rs::BUSY_STATUS_PATTERN` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `_PERMISSION_FLAGS` (py/claudeops/providers/copilot_provider.py:189) | `copilot.rs::permission_flags` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_RESUME_SCAN_LIMIT` (py/claudeops/providers/copilot_provider.py:196) | `copilot.rs::RESUME_SCAN_LIMIT`, `RESUME_SQL` | `parity.rs::parity_resume` `devam-diger` `devam-copilot-sinir-` | TAŞINDI |
| `_USAGE_PLAN_RE` (py/claudeops/providers/copilot_provider.py:205) | `usage.rs::PLAN` | `parity.rs::parity_usage` `usage-copilot` | TAŞINDI |
| `_USAGE_FRACTION_RE` (py/claudeops/providers/copilot_provider.py:206) | `usage.rs::FRACTION` | `parity.rs::parity_usage` `usage-copilot` | TAŞINDI |
| `_USAGE_RESET_RE` (py/claudeops/providers/copilot_provider.py:207) | `usage.rs::RESET_IN` (`$` -> `\z`, gerekçe kodda) | `parity.rs::parity_usage` `usage-copilot` | TAŞINDI |
| `trust_folder` (py/claudeops/providers/copilot_provider.py:210) | `copilot.rs::{trust_folder, trust_folder_edit}` + `Effect` | `parity.rs::parity_build` `trust-` (`trust-ayrac`); `config_path` parametresi yok | TAŞINDI |
| `_TRUST_TOKEN_RE` (py/claudeops/providers/copilot_provider.py) | `copilot.rs::TRUST_TOKEN` | `parity.rs::parity_build` `trust-ayrac` | TAŞINDI |
| `_connect_ro` (py/claudeops/providers/copilot_provider.py:232) | `live.rs::LiveProbe::sqlite_rows` sözleşmesi (gerçek uygulama G8) | `parity.rs::parity_chat` `copilot-sohbet-db-` | TAŞINDI |
| `CopilotProvider` (py/claudeops/providers/copilot_provider.py:239) | `copilot.rs` + `Cli::Copilot` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `CopilotProvider.name` (py/claudeops/providers/copilot_provider.py:240) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.resolve_resume_id` (py/claudeops/providers/copilot_provider.py:242) | `copilot.rs::Live::copilot_resume_id` | `parity.rs::parity_resume` `devam-copilot-` | TAŞINDI |
| `CopilotProvider.build_inner_command` (py/claudeops/providers/copilot_provider.py:270) | `copilot.rs::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra` `byok-` `trust-` | TAŞINDI |
| `CopilotProvider.env_overrides` (py/claudeops/providers/copilot_provider.py:297) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.matches_proc` (py/claudeops/providers/copilot_provider.py:303) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `CopilotProvider.extract_name` (py/claudeops/providers/copilot_provider.py:322) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `CopilotProvider.extract_info` (py/claudeops/providers/copilot_provider.py:329) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `CopilotProvider.model_choices` (py/claudeops/providers/copilot_provider.py:345) | `provider.rs` `model_choices` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.permission_modes` (py/claudeops/providers/copilot_provider.py:348) | `provider.rs` `permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.effort_levels` (py/claudeops/providers/copilot_provider.py:351) | `provider.rs` `effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.mode_status_patterns` (py/claudeops/providers/copilot_provider.py:354) | `tui.rs::Cli::mode_status_patterns` | `parity.rs::parity_tui` `g4-sabit-`, `g4-mod-` | TAŞINDI |
| `CopilotProvider.busy_status_pattern` (py/claudeops/providers/copilot_provider.py:357) | `live.rs::Cli::busy_status_pattern` | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `CopilotProvider.usage_command` (py/claudeops/providers/copilot_provider.py:360) | `usage.rs::Cli::usage_command` | `parity.rs::parity_usage` `usage-copilot` | TAŞINDI |
| `CopilotProvider.parse_usage_text` (py/claudeops/providers/copilot_provider.py:369) | `usage.rs::copilot_usage` | `parity.rs::parity_usage` `usage-copilot` | TAŞINDI |
| `CopilotProvider.usage_fresh_tui_argv` (py/claudeops/providers/copilot_provider.py:380) | `usage.rs::Providers::usage_fresh_tui_argv` | `parity.rs::parity_usage` `usage-copilot` `usage-bin-*-copilot` | TAŞINDI |
| `CopilotProvider._turns` (py/claudeops/providers/copilot_provider.py:384) | `chat.rs::Live::copilot_turns` | `parity.rs::parity_chat` `copilot-sohbet-` | TAŞINDI |
| `CopilotProvider.live_context` (py/claudeops/providers/copilot_provider.py:407) | `live.rs::Live::copilot_context`, `COPILOT_CONTEXT_SQL` | `parity.rs::parity_live` `copilot-` | TAŞINDI |
| `CopilotProvider.last_exchange` (py/claudeops/providers/copilot_provider.py:425) | `chat.rs::Live::last_exchange` | `parity.rs::parity_chat` `copilot-sohbet-` | TAŞINDI |
| `CopilotProvider.full_history` (py/claudeops/providers/copilot_provider.py:434) | `chat.rs::Live::full_history` | `parity.rs::parity_chat` `copilot-sohbet-` | TAŞINDI |
| `PROC_TAG` (py/claudeops/providers/shell_provider.py:31) | `shell.rs::PROC_TAG` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_SENTINEL` (py/claudeops/providers/shell_provider.py:38) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider` (py/claudeops/providers/shell_provider.py:41) | `shell.rs` + `Cli::Shell` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.name` (py/claudeops/providers/shell_provider.py:42) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.has_conversation` (py/claudeops/providers/shell_provider.py:44) | `tui.rs::Cli::has_conversation` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `ShellProvider.resolve_resume_id` (py/claudeops/providers/shell_provider.py:47) | `resume.rs::Live::resolve_resume_id` (`Cli::Shell` = None) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `ShellProvider.build_inner_command` (py/claudeops/providers/shell_provider.py:51) | `shell.rs::build_inner_command` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `ShellProvider.env_overrides` (py/claudeops/providers/shell_provider.py:58) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.matches_proc` (py/claudeops/providers/shell_provider.py:61) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `ShellProvider.extract_name` (py/claudeops/providers/shell_provider.py:64) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `ShellProvider.extract_info` (py/claudeops/providers/shell_provider.py:70) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `ShellProvider.model_choices` (py/claudeops/providers/shell_provider.py:73) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.permission_modes` (py/claudeops/providers/shell_provider.py:76) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.effort_levels` (py/claudeops/providers/shell_provider.py:79) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `_EFFORT_LIMITS` (py/claudeops/providers/ucli_provider.py:153) | `ucli.rs::{EFFORT_LIMITS, EFFORT_LEVELS}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` | TAŞINDI |
| `_EFFORT_LEVELS` (py/claudeops/providers/ucli_provider.py:157) | `ucli.rs::{EFFORT_LIMITS, EFFORT_LEVELS}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` | TAŞINDI |
| `_REQUEST_TIMEOUT_SECS` (py/claudeops/providers/ucli_provider.py:167) | `ucli.rs::{REQUEST_TIMEOUT_SECS, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_MAX_HISTORY_KIB` (py/claudeops/providers/ucli_provider.py:173) | `ucli.rs::{MAX_HISTORY_KIB, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_USAGE_FIELDS` (py/claudeops/providers/ucli_provider.py:178) | `ucli_status.rs::USAGE_FIELDS` | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `_PHASE_INT_FIELDS` (py/claudeops/providers/ucli_provider.py:182) | `ucli_status.rs::PHASE_INT_FIELDS` | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `_READ_ONLY` (py/claudeops/providers/ucli_provider.py:187) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_ALLOW_EDIT` (py/claudeops/providers/ucli_provider.py:188) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_ALLOW_CREATE` (py/claudeops/providers/ucli_provider.py:192) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_PERMISSION_MODES` (py/claudeops/providers/ucli_provider.py:193) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_MODEL_CHOICES` (py/claudeops/providers/ucli_provider.py:201) | `ucli.rs::{FALLBACK_MODEL, LiveModels::choices}` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `DEFAULT_ENDPOINT` (py/claudeops/providers/ucli_provider.py:202) | `ucli.rs::DEFAULT_ENDPOINT` | `parity.rs::parity_ucli` `temel-` `ayar-endpoint` | TAŞINDI |
| `_ENDPOINT` (py/claudeops/providers/ucli_provider.py:203) | `ucli.rs::DEFAULT_ENDPOINT` | `parity.rs::parity_ucli` `temel-` `ayar-endpoint` | TAŞINDI |
| `endpoint` (py/claudeops/providers/ucli_provider.py:206) | `ucli.rs::build_inner_command` (`Settings::ucli_endpoint` yoksa varsayılan) | `parity.rs::parity_ucli` `ayar-endpoint` `endpoint-gecersiz`; ayrı public işlev yok | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/providers/ucli_provider.py:221) | `ucli.rs::MODELS_TTL` | `parity.rs::parity_model_sources` `src-ucli-akis` | TAŞINDI |
| `_LIVE_MODEL_CACHE` (py/claudeops/providers/ucli_provider.py:222) | `ucli.rs::LiveCache` (`live.ids`) | `parity.rs::parity_model_sources` `src-ucli-akis` | TAŞINDI |
| `_LIVE_MODEL_CACHE_TS` (py/claudeops/providers/ucli_provider.py:223) | `ucli.rs::LiveCache` (`ts`) | `parity.rs::parity_model_sources` `src-ucli-akis` `src-ucli-anahtarsiz` | TAŞINDI |
| `_LIVE_CAPS` (py/claudeops/providers/ucli_provider.py:226) | `ucli.rs::LiveCache` (`live.caps`) | `parity.rs::parity_model_sources` `src-ucli-yetenek` (ret + caps) | TAŞINDI |
| `_fetch_live_models` (py/claudeops/providers/ucli_provider.py:229) | `ucli.rs::{fetch_live_models, parse_live_models}` (`ModelIo::http_get`; gerçek HTTP G8) | `parity.rs::parity_model_sources` `src-ucli-*` (Python hatası? G7 şüphe 3-5, 10) | TAŞINDI |
| `_live_models` (py/claudeops/providers/ucli_provider.py:266) | `ucli.rs::LiveCache::get` (`ModelSources::ucli_live`) | `parity.rs::parity_model_sources` `src-ucli-akis` `src-ucli-anahtarsiz` | TAŞINDI |
| `reasoning_effort_for` (py/claudeops/providers/ucli_provider.py:283) | `ucli.rs::reasoning_effort_for` | `parity.rs::parity_misc` `ucli-misc`; ve `parity_ucli` `temel-` | TAŞINDI |
| `_API_KEY_FILE` (py/claudeops/providers/ucli_provider.py:307) | `probe.rs::Paths::ucli_key_file` | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `_API_KEY_MANAGED_MARKER` (py/claudeops/providers/ucli_provider.py:313) | `ucli.rs::Ctx::sync_api_key_file` + `Effect` | `parity.rs::parity_ucli` `anahtar-`; yazım uygulayıcısı yalnız testte (G8) | TAŞINDI |
| `_sync_api_key_file` (py/claudeops/providers/ucli_provider.py:316) | `ucli.rs::Ctx::sync_api_key_file` + `Effect` | `parity.rs::parity_ucli` `anahtar-`; yazım uygulayıcısı yalnız testte (G8) | TAŞINDI |
| `_web_args` (py/claudeops/providers/ucli_provider.py:345) | `ucli.rs::Ctx::web_args` | `parity.rs::parity_ucli` `web-` `eksik`; `ucli_web_searxng_error` diag bilerek yok (Rust yöneticisi istisna üretmez) | TAŞINDI |
| `_script_args` (py/claudeops/providers/ucli_provider.py:383) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_stream_args` (py/claudeops/providers/ucli_provider.py:397) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_reasoning_display_args` (py/claudeops/providers/ucli_provider.py:409) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_metrics_file_args` (py/claudeops/providers/ucli_provider.py:420) | `ucli.rs::Ctx::tuning_args` + `Effect::MkdirPrivate` | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-`; Python mkdir hatasında bayrağı düşürür; Rust'ta çağıran sözleşmesi (G8) | TAŞINDI |
| `_interactive_args` (py/claudeops/providers/ucli_provider.py:442) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `eksik` `temel-` | TAŞINDI |
| `_state_dir_args` (py/claudeops/providers/ucli_provider.py:451) | `ucli.rs::Ctx::state_dir_args` | `parity.rs::parity_ucli` `statedir-` | TAŞINDI |
| `_timeout_args` (py/claudeops/providers/ucli_provider.py:468) | `ucli.rs::{REQUEST_TIMEOUT_SECS, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_history_args` (py/claudeops/providers/ucli_provider.py:478) | `ucli.rs::{MAX_HISTORY_KIB, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_effort_args` (py/claudeops/providers/ucli_provider.py:495) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_set_flag_value` (py/claudeops/providers/ucli_provider.py:513) | `ucli.rs::set_flag_value` | `parity.rs::parity_ucli` `hizmet-claude` `opts-` | TAŞINDI |
| `_service_key_file` (py/claudeops/providers/ucli_provider.py:525) | `probe.rs::Paths::ucli_key_file` | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `_INSTRUCTIONS_MAX_BYTES` (py/claudeops/providers/ucli_provider.py:529) | `ucli.rs::Ctx::claude_service_flags` | `parity.rs::parity_ucli` `hizmet-claude-buyuk-talimat` `hizmet-claude-sinir-talimat` | TAŞINDI |
| `_instructions_too_big` (py/claudeops/providers/ucli_provider.py:532) | `ucli.rs::Ctx::claude_service_flags` | `parity.rs::parity_ucli` `hizmet-claude-buyuk-talimat` `hizmet-claude-sinir-talimat` | TAŞINDI |
| `instructions_check` (py/claudeops/providers/ucli_provider.py:543) | `ucli.rs::instructions_check` (`InstructionsCheck`) | `parity.rs::parity_panel` `instr-*` | TAŞINDI |
| `_claude_service_flags` (py/claudeops/providers/ucli_provider.py:564) | `ucli.rs::Ctx::claude_service_flags` | `parity.rs::parity_ucli` `hizmet-claude`; günlük tavan `Probe::claude_cost_gate` sahte (G8); `ucli_usage_log_dir_failed` diag yok (G8) | TAŞINDI |
| `_PRICED_MODELS` (py/claudeops/providers/ucli_provider.py:597) | `ucli.rs::{PRICED_MODELS, Ctx::apply_cli_opts}` | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` `opts-cost-modelsiz` | TAŞINDI |
| `_default_session_cap` (py/claudeops/providers/ucli_provider.py:600) | `ucli.rs::Ctx::apply_cli_opts` + `Settings::default_max_session_usd` | `parity.rs::parity_ucli` `hizmet-grok-tavan-ayar` `ham-service-evren` | TAŞINDI |
| `_max_cost_args` (py/claudeops/providers/ucli_provider.py:609) | `ucli.rs::{PRICED_MODELS, Ctx::apply_cli_opts}` | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` `opts-cost-modelsiz` | TAŞINDI |
| `_MCP_NAME_BAD` (py/claudeops/providers/ucli_provider.py:624) | `ucli.rs::mcp_server_name` | `parity.rs::parity_misc` `ucli-misc`; ve `parity_ucli` `ucli-mcp-ad` | TAŞINDI |
| `_MCP_TOOL_RE` (py/claudeops/providers/ucli_provider.py:625) | `ucli.rs::valid_tool_name` | `parity.rs::parity_ucli` `ucli-mcp-` (satır sonlu ad: `spec` içindeki `ok\n`) | TAŞINDI |
| `_MCP_ADD_TIMEOUT` (py/claudeops/providers/ucli_provider.py:626) | `real/probe.rs::{MCP_ADD_TIMEOUT, RealProbe::register_mcp}` + `ucli.rs::mcp_launch_args` | `parity.rs::parity_real` `mcp-`; `tests/real_process.rs::register_mcp_errors_carry_python_reprs` | TAŞINDI |
| `mcp_server_name` (py/claudeops/providers/ucli_provider.py:629) | `ucli.rs::mcp_server_name` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `mcp_add_argv` (py/claudeops/providers/ucli_provider.py:633) | `ucli.rs::mcp_add_argv` | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `register_mcp` (py/claudeops/providers/ucli_provider.py:642) | `real/probe.rs::{MCP_ADD_TIMEOUT, RealProbe::register_mcp}` + `ucli.rs::mcp_launch_args` | `parity.rs::parity_real` `mcp-`; `tests/real_process.rs::register_mcp_errors_carry_python_reprs` | TAŞINDI |
| `_apply_cli_opts` (py/claudeops/providers/ucli_provider.py:672) | `ucli.rs::Ctx::apply_cli_opts` | `parity.rs::parity_ucli` `opts-` `ham-` | TAŞINDI |
| `_agent_setup` (py/claudeops/providers/ucli_provider.py:845) | `ucli.rs::Ctx::agent_setup` | `parity.rs::parity_ucli` `ajan-`; token üretimi `Probe` sahte (G8) | TAŞINDI |
| `UcliProvider` (py/claudeops/providers/ucli_provider.py:867) | `ucli.rs::build_inner_command` | `parity.rs::parity_ucli` `temel-` `anahtar-` `opts-` | TAŞINDI |
| `UcliProvider.name` (py/claudeops/providers/ucli_provider.py:868) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.prepare_input` (py/claudeops/providers/ucli_provider.py:870) | `tui.rs::Cli::prepare_input` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `UcliProvider.has_conversation` (py/claudeops/providers/ucli_provider.py:878) | `tui.rs::Cli::has_conversation` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `UcliProvider.wants_handover_wrapup` (py/claudeops/providers/ucli_provider.py:881) | `tui.rs::Cli::wants_handover_wrapup` | `parity.rs::parity_tui` `g4-sabit-` | TAŞINDI |
| `UcliProvider.resolve_resume_id` (py/claudeops/providers/ucli_provider.py:884) | `resume.rs::Live::resolve_resume_id` (`Cli::Ucli` = None) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `UcliProvider.accepts_cli_opts` (py/claudeops/providers/ucli_provider.py:888) | `provider.rs::Cli::accepts_cli_opts` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.mcp_needs_cwd` (py/claudeops/providers/ucli_provider.py:889) | `provider.rs::Cli::mcp_needs_cwd` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.validate_cli_opts` (py/claudeops/providers/ucli_provider.py:891) | `ucli_opts.rs::validate_opts` | `parity.rs::parity_ucli` `opts-` | TAŞINDI |
| `UcliProvider.mcp_launch_args` (py/claudeops/providers/ucli_provider.py:894) | `ucli.rs::mcp_launch_args` | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `UcliProvider.build_inner_command` (py/claudeops/providers/ucli_provider.py:917) | `ucli.rs::build_inner_command` | `parity.rs::parity_ucli` `temel-` `anahtar-` `opts-` | TAŞINDI |
| `UcliProvider.oneshot` (py/claudeops/providers/ucli_provider.py:997) | `real/oneshot.rs::OneShot::{ucli_oneshot, oneshot_key}`, `oneshot.rs::ucli_answer` | `parity.rs::parity_oneshot` `ucli-`; `tests/real_oneshot.rs::the_configured_key_goes_into_the_child_only_for_the_ucli_oneshot` | TAŞINDI |
| `UcliProvider.env_overrides` (py/claudeops/providers/ucli_provider.py:1017) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.matches_proc` (py/claudeops/providers/ucli_provider.py:1022) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `UcliProvider._parse_session` (py/claudeops/providers/ucli_provider.py:1027) | `rs/proc` `providers.rs::arg` (`Cli::extract_name`, `ucli_info`) | rs/proc: `providers.rs::ucli_effort_presets`, altın `detect_info` | KAPSAM DIŞI |
| `UcliProvider.extract_name` (py/claudeops/providers/ucli_provider.py:1033) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `UcliProvider.extract_info` (py/claudeops/providers/ucli_provider.py:1036) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `UcliProvider.model_choices` (py/claudeops/providers/ucli_provider.py:1072) | `ucli.rs::LiveModels::choices` | `parity.rs::parity_model_effort` `ucli-live`; canlı liste `parity_model_sources` `src-ucli-` | TAŞINDI |
| `UcliProvider.default_permission_mode` (py/claudeops/providers/ucli_provider.py:1075) | `provider.rs::Cli::default_permission_mode` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.permission_modes` (py/claudeops/providers/ucli_provider.py:1080) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.effort_levels` (py/claudeops/providers/ucli_provider.py:1083) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.full_history` (py/claudeops/providers/ucli_provider.py:1086) | `chat.rs::Live::full_history` | `parity.rs::parity_chat` `chat-ucli-` | TAŞINDI |
| `UcliProvider.sid_for_stopped_session` (py/claudeops/providers/ucli_provider.py:1091) | `resume.rs::Live::sid_for_stopped_session` (`Cli::Ucli` = ad) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `UcliProvider.live_busy` (py/claudeops/providers/ucli_provider.py:1097) | `ucli_status.rs::Live::ucli_busy` (`Live::live_busy`) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `UcliProvider.background_work` (py/claudeops/providers/ucli_provider.py:1112) | `live.rs::Live::background_work` | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `UcliProvider.live_tools` (py/claudeops/providers/ucli_provider.py:1127) | `ucli_status.rs::Live::ucli_tools` (`Live::live_tools`) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `UcliProvider.live_context` (py/claudeops/providers/ucli_provider.py:1141) | `ucli_status.rs::Live::ucli_context` (`Live::live_context`) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `UcliProvider.live_usage` (py/claudeops/providers/ucli_provider.py:1156) | `ucli_status.rs::Live::ucli_usage` (`Live::live_usage`) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `UcliProvider.live_failed_turns` (py/claudeops/providers/ucli_provider.py:1173) | `ucli_status.rs::Live::ucli_failed_turns` (`Live::live_failed_turns`) | `parity.rs::parity_live` `hata-` | TAŞINDI |
| `UcliProvider.live_phase` (py/claudeops/providers/ucli_provider.py:1196) | `ucli_status.rs::Live::ucli_phase` (`Live::live_phase`) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `UcliProvider.last_exchange` (py/claudeops/providers/ucli_provider.py:1226) | `chat.rs::ucli_last` | `parity.rs::parity_chat` `chat-ucli-` | TAŞINDI |
| `BUNDLED_PATH` (py/claudeops/routing.py:21) | `probe.rs::Paths::routing_bundled` | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `OVERRIDE_PATH` (py/claudeops/routing.py:22) | `probe.rs::Paths::routing_override` | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `BLOCK_BEGIN` (py/claudeops/routing.py:23) | `routing.rs::BLOCK_BEGIN` | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `BLOCK_END` (py/claudeops/routing.py:24) | `routing.rs::BLOCK_END` | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `CODEX_AGENTS` (py/claudeops/routing.py:25) | `probe.rs::Paths::codex_agents_md` | `tests/g9.rs::default_sync_paths_are_under_home` | TAŞINDI |
| `AGY_GEMINI` (py/claudeops/routing.py:26) | `probe.rs::Paths::agy_gemini_md` | `tests/g9.rs::default_sync_paths_are_under_home` | TAŞINDI |
| `routing_text` (py/claudeops/routing.py:29) | `routing.rs::routing_text` | `parity.rs::parity_misc` `sync`; ve `parity_build` `claude-routing-` | TAŞINDI |
| `claude_guidance_path` (py/claudeops/routing.py:41) | `routing.rs::claude_guidance_path` | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `_with_block` (py/claudeops/routing.py:66) | `routing.rs::with_block` | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `_sync_one` (py/claudeops/routing.py:81) | `real/routing_sync.rs::sync_one` (karar `routing.rs::sync_plan`; yedek `copy2`, silme, realpath'e atomik yazım, `skipped:<OSError sınıfı>`) | `parity.rs::parity_misc` `sync` (gerçek uygulayıcı); `parity.rs::parity_g9` `esitle-` | TAŞINDI |
| `sync_global_files` (py/claudeops/routing.py:109) | `real/routing_sync.rs::{sync_global_files, sync_global_files_at}` | `parity.rs::parity_g9` `esitle-`; `tests/g9.rs::default_sync_paths_are_under_home` | TAŞINDI |
| `_DANGEROUS_ENV_NAMES` (py/claudeops/spawn.py:36) | `spawn.rs::DANGEROUS_ENV` | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `FALLBACK_ATTEMPT_WAIT_SECONDS` (py/claudeops/spawn.py:50) | `spawn_exec.rs::FALLBACK_ATTEMPT_WAIT_SECONDS` (+ `FALLBACK_POLL_SECONDS`) | `parity.rs::parity_g9` `bekci-`; `tests/g9.rs::watchdog_retries_then_falls_back_to_headless_tmux` | TAŞINDI |
| `FALLBACK_RETRY_COUNT` (py/claudeops/spawn.py:51) | `spawn_exec.rs::FALLBACK_RETRY_COUNT` | `parity.rs::parity_g9` `bekci-`; `tests/g9.rs::watchdog_retries_then_falls_back_to_headless_tmux` | TAŞINDI |
| `_filter_env_overrides` (py/claudeops/spawn.py:54) | `spawn.rs::filter_env_overrides` | `parity.rs::parity_spawn` `filter` `-kanca` | TAŞINDI |
| `DRY_RUN_PREVIEW_MAX` (py/claudeops/spawn.py:59) | `spawn.rs::DRY_RUN_PREVIEW_MAX` | `parity.rs::parity_spawn` `preview-sinir` `preview-sinir2` | TAŞINDI |
| `_SECRET_ENV_RE` (py/claudeops/spawn.py:60) | `spawn.rs::{SECRET_WORDS, fold_char}` | `parity.rs::parity_spawn` `preview` | TAŞINDI |
| `_dry_run_preview` (py/claudeops/spawn.py:63) | `spawn.rs::{dry_run_preview, SpawnPlan::dry_run_line}` | `parity.rs::parity_spawn` `preview` `-dry` | TAŞINDI |
| `detect_display` (py/claudeops/spawn.py:71) | `spawn.rs::detect_display` | `parity.rs::parity_spawn` `display-env` `display-bos` `display-yok`; soket/kilit dosyası senaryoları denetimli değil | TAŞINDI |
| `_ids_held_by_others` (py/claudeops/spawn.py:83) | `resume.rs::ids_held_by_others` (süreç taraması girdi: rs/proc) | `parity.rs::parity_resume` `devam-tutulan` | TAŞINDI |
| `SESSION_USD_CAP_KEY` (py/claudeops/spawn.py:110) | `spawn.rs::SESSION_USD_CAP_KEY` | `parity.rs::parity_spawn` `kanca-` | TAŞINDI |
| `_apply_hook_session_cap` (py/claudeops/spawn.py:113) | `spawn.rs::apply_hook_session_cap` | `parity.rs::parity_spawn` `kanca-` | TAŞINDI |
| `BRAIN_NAME_PREFIXES` (py/claudeops/spawn.py:138) | `spawn.rs::BRAIN_NAME_PREFIX` | `parity.rs::parity_spawn` `prefix-` | TAŞINDI |
| `spawn_priority_prefix` (py/claudeops/spawn.py:141) | `spawn.rs::priority_prefix` + `Settings::spawn_nice` | `parity.rs::parity_spawn` `prefix-` | TAŞINDI |
| `spawn_session` (py/claudeops/spawn.py:163) | `spawn_exec.rs::spawn_session` (komut kurma `spawn.rs::plan_spawn_with`; sınırlar `SpawnTmux`/`Terminal`/`Clock`/`DiagSink`/`SessionScan`/`ResumeResolver`/`SpawnHooks`/`CostRelease`; kuru ya da hatalı başlatmada `release` burada). Gerçek `SpawnTmux` uygulayıcısı `cops-tmux` birleşimini, `SessionScan` rs/proc'u bekler. Python hatası? dry_run yan etkisi (TBD#373) | `parity.rs::parity_g9` `{cli}-gt|gizli|gizli-tmuxsuz|gtsiz|gtsiz-tmuxsuz|tmuxsuz|kuru|hayalet|devam|yeni-zorla|eklenti|kanca|kanca-red`, `ekran-`, `ortam-supurme`, `bekci-`, `ilk-`, `kanca-`, `eklenti-`, `tarama-dustu`, `ad-tirnak`; `release` her vakada ayrıca | TAŞINDI |
| `_launch_gnome_terminal` (py/claudeops/spawn.py:325) | `real/launch.rs::GnomeTerminal` (`Terminal::launch`; argv `spawn.rs::gnome_terminal_argv`) | `tests/g9.rs::{gnome_terminal_runs_with_only_the_given_env_and_is_reaped, gnome_terminal_popen_failures}`; `parity.rs::parity_g9` `ilk-oserror` `ilk-valueerror` `bekci-baslatilamadi` | TAŞINDI |
| `_reclaim_ghost_session` (py/claudeops/spawn.py:366) | `spawn_exec.rs::reclaim_ghost_session` (hata dalı yok: tmux sınırı yükseltmez) | `parity.rs::parity_g9` `hayalet-`, `{cli}-hayalet`; `tests/g9.rs` ReclaimTest karşılıkları | TAŞINDI |
| `_fallback_watchdog` (py/claudeops/spawn.py:384) | `spawn_exec.rs::fallback_watchdog` (+ `Watchdog` join tanıtıcısı) | `parity.rs::parity_g9` `bekci-`; `tests/g9.rs::watchdog_*` | TAŞINDI |
| `open_window` (py/claudeops/spawn.py:409) | `spawn_exec.rs::open_window` | `parity.rs::parity_g9` `pencere-` | TAŞINDI |
| `open_mirror_window` (py/claudeops/spawn.py:425) | `spawn_exec.rs::open_mirror_window` (argv/ortam `spawn.rs::{mirror_window_command, mirror_child_env}`) | `parity.rs::parity_g9` `ayna-`; `parity_spawn` `ayna ayna-tirnak` | TAŞINDI |
| `EFFORT_LADDER` (py/claudeops/effort.py:19) | `effort.rs::EFFORT_LADDER` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `_RANK` (py/claudeops/effort.py:20) | `effort.rs::effort_rank` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `_ID_TIERS` (py/claudeops/effort.py:25) | `effort.rs::ID_TIERS` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `effort_rank` (py/claudeops/effort.py:28) | `effort.rs::effort_rank` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `split_tier` (py/claudeops/effort.py:33) | `effort.rs::split_tier` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `sort_levels` (py/claudeops/effort.py:45) | `effort.rs::sort_levels` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `nearest_effort` (py/claudeops/effort.py:56) | `effort.rs::nearest_effort` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `ENV_NAME_RE` (py/claudeops/envnames.py:7) | rs/state `settings_read.rs::is_safe_env_name` (`settings.rs` yeniden dışa açar) | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `is_safe_env_name` (py/claudeops/envnames.py:10) | rs/state `settings_read.rs::is_safe_env_name` (`settings.rs` yeniden dışa açar) | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `services` (py/claudeops/ucli_session_opts.py:21) | `settings.rs::Settings::ucli_services` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `effort_levels_for` (py/claudeops/ucli_session_opts.py:27) | `settings.rs::Settings::ucli_effort_levels_for` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `FORBIDDEN_CMDS` (py/claudeops/ucli_session_opts.py:40) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_FORBIDDEN_RE` (py/claudeops/ucli_session_opts.py:54) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `is_forbidden_cmd` (py/claudeops/ucli_session_opts.py:57) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_FORBIDDEN_LOWER` (py/claudeops/ucli_session_opts.py:62) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_CMD_RE` (py/claudeops/ucli_session_opts.py:64) | `ucli_opts.rs::CMD` | `parity.rs::parity_ucli` `opts-`; `path_executables` kullanımı `real/pathexec.rs::CMD_NAME` (`parity_real` `yol-`) | TAŞINDI |
| `_GLOB_RE` (py/claudeops/ucli_session_opts.py:65) | `ucli_opts.rs::{GLOB, MAX_GLOBS, BROAD_GLOBS}` | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `MAX_CMDS` (py/claudeops/ucli_session_opts.py:66) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `MAX_EXPANDED` (py/claudeops/ucli_session_opts.py:67) | `ucli_opts.rs::{MAX_EXPANDED, expand_exec_cmds}` | `parity.rs::parity_misc` `expand` `re-exp` | TAŞINDI |
| `_PATTERN_CHARS` (py/claudeops/ucli_session_opts.py:68) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `MAX_GLOBS` (py/claudeops/ucli_session_opts.py:69) | `ucli_opts.rs::{GLOB, MAX_GLOBS, BROAD_GLOBS}` | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `MAX_BINDS` (py/claudeops/ucli_session_opts.py:70) | `ucli_opts.rs::{MAX_BINDS, BIND}` | `parity.rs::parity_ucli` `bind-` | TAŞINDI |
| `_BIND_RE` (py/claudeops/ucli_session_opts.py:71) | `ucli_opts.rs::{MAX_BINDS, BIND}` | `parity.rs::parity_ucli` `bind-` | TAŞINDI |
| `TIMEOUT_RANGE` (py/claudeops/ucli_session_opts.py:72) | `ucli_opts.rs::TIMEOUT_RANGE` | `parity.rs::parity_ucli` `timeout-` | TAŞINDI |
| `MAX_COST_USD` (py/claudeops/ucli_session_opts.py:73) | `ucli_opts.rs::MAX_COST_USD` | `parity.rs::parity_ucli` `cost-` `session-sinir` | TAŞINDI |
| `INT_LIMITS` (py/claudeops/ucli_session_opts.py:75) | `ucli_opts.rs::INT_LIMITS` | `parity.rs::parity_ucli` `int-` | TAŞINDI |
| `PRICE_MAX` (py/claudeops/ucli_session_opts.py:83) | `ucli_opts.rs::PRICE_MAX` | `parity.rs::parity_ucli` `price-` | TAŞINDI |
| `BROAD_GLOBS` (py/claudeops/ucli_session_opts.py:86) | `ucli_opts.rs::{GLOB, MAX_GLOBS, BROAD_GLOBS}` | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `_is_glob` (py/claudeops/ucli_session_opts.py:89) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `_items` (py/claudeops/ucli_session_opts.py:93) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `validate_opts` (py/claudeops/ucli_session_opts.py:101) | `ucli_opts.rs::validate_opts` | `parity.rs::parity_ucli` `opts-`; ve `parity_misc` `val re-val` | TAŞINDI |
| `DEFAULT_MAX_SESSION_USD` (py/claudeops/ucli_session_opts.py:305) | `settings.rs::{DEFAULT_MAX_SESSION_USD, Settings::default_max_session_usd}` | `parity.rs::parity_settings_pyfmt` `usd` | TAŞINDI |
| `default_max_session_usd` (py/claudeops/ucli_session_opts.py:308) | `settings.rs::{DEFAULT_MAX_SESSION_USD, Settings::default_max_session_usd}` | `parity.rs::parity_settings_pyfmt` `usd` | TAŞINDI |
| `path_executables` (py/claudeops/ucli_session_opts.py:323) | `real/pathexec.rs::path_executables` | `parity.rs::parity_real` `yol-` | TAŞINDI |
| `expand_exec_cmds` (py/claudeops/ucli_session_opts.py:343) | `ucli_opts.rs::{MAX_EXPANDED, expand_exec_cmds}` | `parity.rs::parity_misc` `expand` `re-exp` | TAŞINDI |
| `_rustup_default_toolchain` (py/claudeops/ucli_session_opts.py:368) | `real/pathexec.rs::{rustup_default_toolchain, rust_toolchain}` | `parity.rs::parity_real` `zincir-`; `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one` | TAŞINDI |
| `rust_toolchain` (py/claudeops/ucli_session_opts.py:381) | `real/pathexec.rs::{rustup_default_toolchain, rust_toolchain}` | `parity.rs::parity_real` `zincir-`; `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one` | TAŞINDI |
| `exec_flags` (py/claudeops/ucli_session_opts.py:410) | `ucli_opts.rs::exec_flags` | `parity.rs::parity_misc` `exec` | TAŞINDI |
| `_MODELS_CACHE` (py/claudeops/ucli_session_opts.py:446) | `ucli_opts.rs::ServiceModelsCache` | `parity.rs::parity_model_sources` `src-svc-ttl` `src-svc-ayri` (Python hatası? G7 şüphe 7) | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/ucli_session_opts.py:447) | `ucli_opts.rs::{SERVICE_MODELS_TTL, SERVICE_MODELS_RETRY}` | `parity.rs::parity_model_sources` `src-svc-ttl`; `tests/model_sources.rs::lifetimes_and_limits_match_python` | TAŞINDI |
| `service_models` (py/claudeops/ucli_session_opts.py:450) | `ucli_opts.rs::{ServiceModelsCache::get, parse_service_models}` (`ModelSources::service_models`) | `parity.rs::parity_model_sources` `src-svc-*` (Python hatası? G7 şüphe 6) | TAŞINDI |
| `_MODELS_RETRY`, `_models_cache_key`, `_parse_service_models` (py/claudeops/ucli_session_opts.py, 27 Kas `fix:`) | `ucli_opts.rs::{SERVICE_MODELS_RETRY, models_cache_key, parse_service_models}` | `tests/model_sources.rs::service_models_keep_the_good_list_and_follow_the_key`; `parity_model_sources` `src-svc-`; `test_rsprov_g7_fixes.py::ServiceModelsTest` | TAŞINDI |

### Kapsam dosyalarının çağırdığı dış adlar (`ucli_session_opts` dışındaki ayar/ucli/paths/steward modülleri; yalnız kullanılanlar ve onların bağımlılıkları)

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `HOME` (py/claudeops/paths.py:5) | `rs/state` `paths.rs` / `probe.rs::Paths::home` girdisi | rs/state (yol çözümü); crate girdi alır | KAPSAM DIŞI |
| `CLAUDE_DIR` (py/claudeops/paths.py:6) | `rs/proc` `Config::claude_dir` | rs/proc | KAPSAM DIŞI |
| `CLAUDEOPS_DIR` (py/claudeops/paths.py:45) | `rs/state` `paths.rs::StateDir::resolve` | rs/state; crate `Paths::claudeops_dir` girdisi alır | KAPSAM DIŞI |
| `REPO_DIR` (py/claudeops/paths.py:50) | `real/launch.rs::repo_dir_of` (`Paths::repo_dir` değeri) | `parity.rs::parity_g9` `depo-dizini`; `tests/g9.rs::repo_dir_resolves_links_and_two_parents` | TAŞINDI |
| `CLAUDE_MODELS_JSON` (py/claudeops/paths.py:54) | `probe.rs::Paths::claude_models_json`; okuma `ModelIo::claude_models_doc` sözleşmesi (DB/dosya kipi rs/state `statedocs`, gerçek uygulama G8) | `tests/model_sources.rs::catalog_touches_only_its_own_source` | TAŞINDI |
| `SESSIONS_DIR` (py/claudeops/paths.py:56) | `rs/proc` `Config::claude_dir` | rs/proc (`sessions/`, `projects/`) | KAPSAM DIŞI |
| `PROJECTS_DIR` (py/claudeops/paths.py:57) | `rs/proc` `Config::claude_dir` | rs/proc (`sessions/`, `projects/`) | KAPSAM DIŞI |
| `parse_proc_stat` (py/claudeops/paths.py:60) | `rs/proc` `procfs.rs::parse_stat` | rs/proc: `procfs::tests::stat_with_parens_in_comm` | KAPSAM DIŞI |
| `proc_stat_fields` (py/claudeops/paths.py:66) | `rs/proc` `procfs.rs::OwnProc::stat` | rs/proc: `fake_proc::own_ppid_from_real_proc` | KAPSAM DIŞI |
| `ucli_key_file` (py/claudeops/paths.py:76) | `probe.rs::Paths::ucli_key_file` | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `SETTINGS_JSON` (py/claudeops/settings.py:28) | `rs/state` `paths.rs::StateDir::settings_json` | rs/state (durum dizini ve dosya okuma) | KAPSAM DIŞI |
| `DEFAULT_SETTINGS` (py/claudeops/settings.py:38) | `rs/state` `settings.rs::defaults` (`default_settings.json`) | rs/state; bu crate okuduğu anahtarların varsayılanını kendi içinde verir (`dosya-yok`) | KAPSAM DIŞI |
| `_LOAD_CACHE` (py/claudeops/settings.py:239) | `rs/state` `settings.rs::SettingsReader` | rs/state (önbellek) | KAPSAM DIŞI |
| `load_settings` (py/claudeops/settings.py:242) | `settings.rs::Settings::from_json` (ayrıştırma toleransı) | `parity.rs::parity_settings_pyfmt` `bozuk-json` `json-liste` `dosya-yok`; dosya okuma, varsayılan birleştirme, önbellek rs/state `SettingsReader`; Python hatası? bozuk UTF-8 (TBD#373) | TAŞINDI |
| `_load_settings_uncached` (py/claudeops/settings.py:268) | `settings.rs::Settings::from_json` (ayrıştırma toleransı) | `parity.rs::parity_settings_pyfmt` `bozuk-json` `json-liste` `dosya-yok`; dosya okuma, varsayılan birleştirme, önbellek rs/state `SettingsReader`; Python hatası? bozuk UTF-8 (TBD#373) | TAŞINDI |
| `resolved_binary` (py/claudeops/settings.py:442) | `provider.rs::Providers::resolved_binary` | `parity.rs::parity_build` `-override` `-path-` `rb-` | TAŞINDI |
| `_KNOWN_BINARY_PATHS` (py/claudeops/settings.py:466) | `provider.rs::CLAUDE_KNOWN_PATHS` | `parity.rs::parity_build` `claude-bilinen` | TAŞINDI |
| `default_model_for` (py/claudeops/settings.py:478) | `provider.rs::Providers::default_model_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `default_effort_for` (py/claudeops/settings.py:504) | `provider.rs::Providers::default_effort_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `resolved_model_for` (py/claudeops/settings.py:513) | `provider.rs::Providers::resolved_model_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `byok_env_for` (py/claudeops/settings.py:532) | `settings.rs::Settings::byok_env` | `parity.rs::parity_settings_pyfmt` `byok` | TAŞINDI |
| `ucli_limit_overrides` (py/claudeops/settings.py:555) | `settings.rs::Settings::ucli_limit_overrides` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `routing_guidance_enabled` (py/claudeops/settings.py:601) | `settings.rs::Settings::routing_guidance_enabled` | `parity.rs::parity_settings_pyfmt` `metrics` | TAŞINDI |
| `_REASONING_LEVELS` (py/claudeops/settings.py:615) | rs/state `settings_read.rs` `Settings::ucli_reasoning_mode` (`settings.rs` devreder) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_reasoning_mode` (py/claudeops/settings.py:618) | rs/state `settings_read.rs` `Settings::ucli_reasoning_mode` (`settings.rs` devreder) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `_ON_WORDS` (py/claudeops/settings.py:632) | rs/state `settings_read.rs` `ON_WORDS`, `OFF_WORDS` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `UCLI_STREAM_DEFAULT` (py/claudeops/settings.py:637) | `settings.rs::Settings::ucli_stream` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_stream_enabled` (py/claudeops/settings.py:640) | `settings.rs::Settings::ucli_stream` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `UCLI_SHOW_REASONING_DEFAULT` (py/claudeops/settings.py:655) | `settings.rs::Settings::ucli_show_reasoning` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_show_reasoning_enabled` (py/claudeops/settings.py:658) | `settings.rs::Settings::ucli_show_reasoning` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `UCLI_STATE_DIR_DEFAULT` (py/claudeops/settings.py:674) | `settings.rs::Settings::ucli_state_dir` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_state_dir_enabled` (py/claudeops/settings.py:677) | `settings.rs::Settings::ucli_state_dir` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `_HOST_RE` (py/claudeops/settings.py:696) | rs/state `settings_read.rs` `Settings::ucli_web_config` (`settings.rs::ucli_web` devreder) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `_MAX_FETCH_DOMAINS` (py/claudeops/settings.py:697) | rs/state `settings_read.rs` `MAX_FETCH_DOMAINS` | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `_valid_http_url` (py/claudeops/settings.py:700) | rs/state `settings_read.rs` `valid_http_url` (`settings.rs` yeniden dışa açar) | `parity.rs::parity_settings_pyfmt` `url` `url-nfkc` (NFKC denetimi dahil, Python'a eşit) | TAŞINDI |
| `_OFF_WORDS` (py/claudeops/settings.py:713) | rs/state `settings_read.rs` `OFF_WORDS` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `DEFAULT_UCLI_SERVICES` (py/claudeops/settings.py:769) | rs/state `settings_read.rs` `default_ucli_services` (`default_ucli_services.json`) | `parity.rs::parity_settings_pyfmt` `servisler*` `servis-*` `bos` | TAŞINDI |
| `UCLI_REASONING_LEVELS` (py/claudeops/settings.py:784) | rs/state `settings_read.rs` `normalize_ucli_services`, `UCLI_REASONING_LEVELS` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `_SVC_ID_RE` (py/claudeops/settings.py:785) | rs/state `settings_read.rs` `normalize_ucli_services`, `UCLI_REASONING_LEVELS` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `_SVC_ENV_RE` (py/claudeops/settings.py:786) | rs/state `settings_read.rs` `normalize_ucli_services`, `UCLI_REASONING_LEVELS` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `normalize_ucli_services` (py/claudeops/settings.py:789) | rs/state `settings_read.rs` `normalize_ucli_services` (`settings.rs::ucli_services` devreder) | `parity.rs::parity_settings_pyfmt` `servisler*` `servis-label-models` `servis-models2` `servis-evren-label` | TAŞINDI |
| `ucli_services` (py/claudeops/settings.py:828) | `settings.rs::Settings::ucli_services` | `parity.rs::parity_settings_pyfmt` `servisler*` `servis-*` | TAŞINDI |
| `ucli_cost_config` (py/claudeops/settings.py:832) | rs/state `settings_read.rs` `Settings::ucli_cost_config` (`settings.rs` devreder; `cap_problem` ham belgeden `settings.rs::cap_problem`) | `parity.rs::parity_panel` `cost*` | TAŞINDI |
| `ucli_script_mode` (py/claudeops/settings.py:858) | `settings.rs::Settings::ucli_script_mode` | `parity.rs::parity_settings_pyfmt` `script` | TAŞINDI |
| `ucli_endpoint` (py/claudeops/settings.py:868) | `settings.rs::Settings::ucli_endpoint` | `parity.rs::parity_settings_pyfmt` `endpoint` | TAŞINDI |
| `ucli_web_config` (py/claudeops/settings.py:875) | rs/state `settings_read.rs` `Settings::ucli_web_config` (`settings.rs::ucli_web` devreder) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `main_session_model_effort` (py/claudeops/steward.py:2920) | rs/stew `prompts.rs::main_session_model_effort` (tek kopya; bu izdeki kopya 27 Kas'ta silindi) | rs/stew `main_session_model_effort_vectors` | KAPSAM DIŞI |
| `STATE_FILE` (py/claudeops/ucli_agents.py:26) | `probe.rs::Paths::{ucli_agents_json, ucli_agent_token_dir}` | `parity.rs::parity_real` `ajan-` | TAŞINDI |
| `TOKEN_DIR` (py/claudeops/ucli_agents.py:27) | `probe.rs::Paths::{ucli_agents_json, ucli_agent_token_dir}` | `parity.rs::parity_real` `ajan-` | TAŞINDI |
| `_CHILD_RE` (py/claudeops/ucli_agents.py:35) | `ucli.rs::is_child_name` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_SAFE_NAME_RE` (py/claudeops/ucli_agents.py:36) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `_LOCK` (py/claudeops/ucli_agents.py:38) | `real/agents.rs::AgentRegistry::lock` (`flock`, süreçler arası; Python yalnız süreç içi) | `tests/real_fs.rs::concurrent_issue_keeps_file_and_digest_consistent` | TAŞINDI |
| `_STATE` (py/claudeops/preview.py) | `probe.rs::BuildOutput::dry_run` (iş parçacığı durumu yerine açık alan) | `parity.rs::parity_spawn` `yan-` | TAŞINDI |
| `preview_only` (py/claudeops/preview.py) | `spawn.rs::plan_spawn` (`SpawnRequest::dry_run`) | `parity.rs::parity_spawn` `yan-` `-dry` | TAŞINDI |
| `preview_only.__enter__` (py/claudeops/preview.py) | `spawn.rs::plan_spawn` | `parity.rs::parity_spawn` `yan-` | TAŞINDI |
| `preview_only.__exit__` (py/claudeops/preview.py) | `spawn.rs::plan_spawn` (önceki değeri geri koyar) | `parity.rs::parity_spawn` `yan-` | TAŞINDI |
| `active` (py/claudeops/preview.py) | `probe.rs::BuildOutput::dry_run` | `parity.rs::parity_spawn` `yan-` | TAŞINDI |
| `_PANEL_PORT` (py/claudeops/ucli_agents.py:49) | `real/probe.rs::RealDeps::panel_port` | `parity.rs::parity_ucli` `ajan-port`; `real_fs.rs::a_dry_run_build_issues_no_token_and_writes_nothing` | TAŞINDI |
| `_OFF_WORDS` (py/claudeops/ucli_agents.py:54) | `settings.rs::AGENTS_OFF_WORDS` | `parity.rs::parity_settings_pyfmt` `metrics` | TAŞINDI |
| `enabled` (py/claudeops/ucli_agents.py:57) | `settings.rs::Settings::ucli_agents_enabled` | `parity.rs::parity_settings_pyfmt` `metrics` | TAŞINDI |
| `panel_url` (py/claudeops/ucli_agents.py:96) | `ucli.rs::Ctx::agent_setup` (port -> URL) | `parity.rs::parity_ucli` `ajan-acik` `ajan-port` | TAŞINDI |
| `is_child_name` (py/claudeops/ucli_agents.py:102) | `ucli.rs::is_child_name` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_empty` (py/claudeops/ucli_agents.py:127) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `_load` (py/claudeops/ucli_agents.py:131) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `_save` (py/claudeops/ucli_agents.py:145) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `_digest` (py/claudeops/ucli_agents.py:150) | `real/agents.rs::digest` | `parity.rs::parity_real` `ajan-` | TAŞINDI |
| `token_file` (py/claudeops/ucli_agents.py:154) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `_write_token_file` (py/claudeops/ucli_agents.py:158) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `issue_token` (py/claudeops/ucli_agents.py:168) | `real/agents.rs::{SAFE_NAME, AgentRegistry::{load, save, token_file, write_token_file, issue_token}}` | `parity.rs::parity_real` `ajan-`; `tests/real_fs.rs::agent_*` | TAŞINDI |
| `ROOT` (py/claudeops/ucli_approval.py:21) | `probe.rs::Paths::ucli_approval_root` | `parity.rs::parity_oneshot` `kayit-` `sohbet-onay-` | TAŞINDI |
| `STATES` (py/claudeops/ucli_approval.py:25) | `approval.rs::STATES` | `parity.rs::parity_oneshot` `kayit-akis` | TAŞINDI |
| `_KEY` (py/claudeops/ucli_approval.py:26) | `approval.rs::valid_run_key` | `parity.rs::parity_oneshot` `saf` `onay-ad`; `approval::tests::names_are_full_matches` | TAŞINDI |
| `_ID` (py/claudeops/ucli_approval.py:27) | `approval.rs::valid_approval_id` | `parity.rs::parity_oneshot` `saf` `onay-kotu-kimlik`; `approval::tests::names_are_full_matches` | TAŞINDI |
| `_index_path` (py/claudeops/ucli_approval.py:30) | `real/approval.rs::ApprovalStore::index_path` | `parity.rs::parity_oneshot` `kayit-` | TAŞINDI |
| `dir_for` (py/claudeops/ucli_approval.py:34) | `real/approval.rs::ApprovalStore::dir_for` | `parity.rs::parity_oneshot` `kayit-akis` `kayit-baglanti` `kayit-kok-` | TAŞINDI |
| `_load_index` (py/claudeops/ucli_approval.py:47) | `real/approval.rs::ApprovalStore::load_index`, `approval.rs::parse_index` | `parity.rs::parity_oneshot` `kayit-belge` `kayit-utf8` `kayit-derin` `kayit-okunamaz` `kayit-dizin` | TAŞINDI |
| `register` (py/claudeops/ucli_approval.py:56) | `real/approval.rs::ApprovalStore::register`, `approval.rs::insert_run` | `parity.rs::parity_oneshot` `kayit-` `sohbet-onay-`; `tests/real_oneshot.rs::concurrent_registrations_lose_nothing_and_one_key_has_one_winner` | TAŞINDI |
| `set_state` (py/claudeops/ucli_approval.py:72) | `real/approval.rs::ApprovalStore::set_state`, `approval.rs::change_state` | `parity.rs::parity_oneshot` `kayit-akis` `kayit-belge`; `the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing` | TAŞINDI |
| `parse_suspended` (py/claudeops/ucli_approval.py:144) | `approval.rs::parse_suspended` | `parity.rs::parity_oneshot` `saf` (1500+ rastgele metin) `sohbet-onay-` | TAŞINDI |
| `_read_index` (py/claudeops/ucli_approval.py:52) | `real/approval.rs::ApprovalStore::read_index` | `parity.rs::parity_oneshot` `kayit-dizin` `kayit-okunamaz` | TAŞINDI |
| `_parse_index` (py/claudeops/ucli_approval.py:68) | `approval.rs::parse_index` | `parity.rs::parity_oneshot` `kayit-belge` | TAŞINDI |
| `_load_index_for_overwrite` (py/claudeops/ucli_approval.py:85) | `real/approval.rs::ApprovalStore::load_index_for_overwrite` | `parity.rs::parity_oneshot` `onay-defter-bozuk` `kayit-kopya-var` | TAŞINDI |
| `_slot_free` (py/claudeops/ucli_approval.py:104) | `approval.rs::slot_free`, `ApprovalStore::slot_free` | `parity.rs::parity_oneshot` `kayit-akis` `onay-defter-canli` | TAŞINDI |
| `MAX_EDITED_BYTES` (py/claudeops/ucli_approval.py:25) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `MAX_NOTE_BYTES` (py/claudeops/ucli_approval.py:26) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `DECISIONS` (py/claudeops/ucli_approval.py:27) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `get` (py/claudeops/ucli_approval.py:126) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `set_result` (py/claudeops/ucli_approval.py:143) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `list_runs` (py/claudeops/ucli_approval.py:157) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `_consumed_path` (py/claudeops/ucli_approval.py:171) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `_consumed` (py/claudeops/ucli_approval.py:175) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `_mark_consumed` (py/claudeops/ucli_approval.py:183) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `begin_resume` (py/claudeops/ucli_approval.py:193) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `recover_resuming` (py/claudeops/ucli_approval.py:205) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `pending` (py/claudeops/ucli_approval.py:244) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `answer` (py/claudeops/ucli_approval.py:271) | T7: onay cevabı, sürdürme ve listeleme (`/api/ucli/approvals`; çağıran yalnız `web.py`/`authz.py`/`_resume_approval`) | - | KAPSAM DIŞI |
| `ROOT` (py/claudeops/ucli_ask.py:22) | `probe.rs::Paths::ucli_ask_root` | `parity.rs::parity_ucli` `askdir` | TAŞINDI |
| `_SAFE` (py/claudeops/ucli_ask.py:24) | `ucli.rs::valid_ask_name` | `parity.rs::parity_ucli` `askdir-gecersiz-ad` `askdir-satir-sonu` `askdir-uzun` | TAŞINDI |
| `dir_for` (py/claudeops/ucli_ask.py:27) | `ucli.rs::Ctx::apply_cli_opts` (ask_dir) + `Effect` | `parity.rs::parity_ucli` `askdir`; dizin açma yalnız test uygulayıcısında (G8) | TAŞINDI |
| `ROOT` (py/claudeops/ucli_checks.py:18) | `probe.rs::Paths::ucli_checks_root` | `parity.rs::parity_ucli` `checks-uygula` | TAŞINDI |
| `MAX_BYTES` (py/claudeops/ucli_checks.py:20) | `real/checks.rs::{MAX_BYTES, MAX_CHECKS, OWNER, NAME, registry_path, check_shape, load_registry}` | `parity.rs::parity_real` `kayit-`; `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `MAX_CHECKS` (py/claudeops/ucli_checks.py:21) | `real/checks.rs::{MAX_BYTES, MAX_CHECKS, OWNER, NAME, registry_path, check_shape, load_registry}` | `parity.rs::parity_real` `kayit-`; `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `_OWNER` (py/claudeops/ucli_checks.py:22) | `real/checks.rs::{MAX_BYTES, MAX_CHECKS, OWNER, NAME, registry_path, check_shape, load_registry}` | `parity.rs::parity_real` `kayit-`; `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `_NAME` (py/claudeops/ucli_checks.py:23) | `real/checks.rs::{MAX_BYTES, MAX_CHECKS, OWNER, NAME, registry_path, check_shape, load_registry}` | `parity.rs::parity_real` `kayit-`; `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `registry_path` (py/claudeops/ucli_checks.py:26) | `ucli.rs::Ctx::apply_cli_opts` (`owner.json`) | `parity.rs::parity_ucli` `checks-uygula`; yalnız varsayılan sahip | TAŞINDI |
| `check_shape` (py/claudeops/ucli_checks.py:33) | `real/checks.rs::{MAX_BYTES, MAX_CHECKS, OWNER, NAME, registry_path, check_shape, load_registry}` | `parity.rs::parity_real` `kayit-`; `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `load_registry` (py/claudeops/ucli_checks.py:53) | `real/checks.rs::{MAX_BYTES, MAX_CHECKS, OWNER, NAME, registry_path, check_shape, load_registry}` | `parity.rs::parity_real` `kayit-`; `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `OWN_UCLI` (py/claudeops/ucli_client.py:57) | `ucli.rs::resolve_binary` (`<repo>/bin/ucli`) | `parity.rs::parity_build` `ru-`; depo içi kopya senaryosu denetimli değil | TAŞINDI |
| `_SAFE_ENV_NAME_RE` (py/claudeops/ucli_client.py:72) | `oneshot.rs::is_api_key_env_name` | `parity.rs::parity_oneshot` `saf` `anahtar-adi` | TAŞINDI |
| `UcliError` (py/claudeops/ucli_client.py:75) | `probe.rs::SpawnError` | `parity.rs::parity_build` `ru-hic` | TAŞINDI |
| `resolve_binary` (py/claudeops/ucli_client.py:79) | `ucli.rs::resolve_binary` | `parity.rs::parity_build` `ru-`; `binary` parametresi yok | TAŞINDI |
| `_HELP_CACHE` (py/claudeops/ucli_client.py:149) | `real/help.rs::HelpCache` (`RealProbe::ucli_chat_help`) | `parity.rs::parity_real` `yardim`; `tests/real_process.rs::help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` | TAŞINDI |
| `_HELP_TIMEOUT_SECONDS` (py/claudeops/ucli_client.py:150) | `real/help.rs::HelpCache` (`RealProbe::ucli_chat_help`) | `parity.rs::parity_real` `yardim`; `tests/real_process.rs::help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` | TAŞINDI |
| `chat_help_text` (py/claudeops/ucli_client.py:153) | `real/help.rs::HelpCache` (`RealProbe::ucli_chat_help`) | `parity.rs::parity_real` `yardim`; `tests/real_process.rs::help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` | TAŞINDI |
| `binary_supports_flag` (py/claudeops/ucli_client.py:177) | `ucli.rs::supports_flag` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `binary_flag_values` (py/claudeops/ucli_client.py:185) | `ucli.rs::flag_values` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_DERIVES_CONTEXT_MARK` (py/claudeops/ucli_client.py:195) | `ucli.rs::DERIVES_CONTEXT_MARK` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `binary_derives_context` (py/claudeops/ucli_client.py:198) | `ucli.rs::derives_context` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `build_chat_argv` (py/claudeops/ucli_client.py:203) | `oneshot.rs::{ChatArgv, build_chat_argv}` | `parity.rs::parity_oneshot` `saf` (200 rastgele) `sohbet-tum-bayraklar` `bos-degerler` | TAŞINDI |
| `_subprocess_env` (py/claudeops/ucli_client.py:235) | `real/oneshot.rs::OneShot::chat_once` (`is_api_key_env_name` + `real/env.rs::Env::with_var`) | `parity.rs::parity_oneshot` `anahtar-`; `tests/real_oneshot.rs::the_key_reaches_only_the_child_environment` | TAŞINDI |
| `STATE_ROOT` (py/claudeops/ucli_client.py:249) | `probe.rs::Paths::ucli_state_root` | `parity.rs::parity_ucli` `statedir-` | TAŞINDI |
| `state_dir_for` (py/claudeops/ucli_client.py:252) | `ucli.rs::state_dir_for` | `parity.rs::parity_misc` `ucli-misc`; ve `parity_ucli` `statedir-` | TAŞINDI |
| `legacy_chat_dir` (py/claudeops/ucli_client.py:260) | `ucli.rs::Ctx::state_dir_args` (satır içi yol) | `parity.rs::parity_ucli` `statedir-eski-gecmis`; okuyucular `ucli_status.rs::Live::chat_session_dirs` (`parity_live` `dizin-`) | TAŞINDI |
| `chat_session_dirs` (py/claudeops/ucli_client.py:264) | `ucli_status.rs::Live::chat_session_dirs` | `parity.rs::parity_live` `dizin-` | TAŞINDI |
| `find_chat_file` (py/claudeops/ucli_client.py:273) | `ucli_status.rs::Live::find_chat_file` | `parity.rs::parity_live` `dizin-`, `durum-` | TAŞINDI |
| `failed_turn_records` (py/claudeops/ucli_client.py:292) | `ucli_status.rs::Live::failed_turn_records` | `parity.rs::parity_live` `hata-`, `dizin-` | TAŞINDI |
| `status_is_busy` (py/claudeops/ucli_client.py:348) | `ucli_status.rs::status_is_busy` | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `read_status_file` (py/claudeops/ucli_client.py:354) | `ucli_status.rs::Live::read_status_file` | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `read_chat_history` (py/claudeops/ucli_client.py:402) | `chat.rs::Live::read_chat_history` | `parity.rs::parity_chat` `chat-ucli-` | TAŞINDI |
| `_BUDGET_NOTES` (py/claudeops/ucli_client.py:429) | `oneshot.rs::BUDGET_NOTES` | `parity.rs::parity_oneshot` `saf` `butce` | TAŞINDI |
| `mark_budget_exhausted` (py/claudeops/ucli_client.py:434) | `oneshot.rs::mark_budget_exhausted` | `parity.rs::parity_oneshot` `saf` `butce`; `oneshot::tests::*budget*` | TAŞINDI |
| `ucli_chat_once` (py/claudeops/ucli_client.py:460) | `real/oneshot.rs::{ChatRequest, OneShot::chat_once}`, `oneshot.rs::{check_prompt, chat_result}` | `parity.rs::parity_oneshot` `sohbet-` `ikili-` `coz-` `durum-dizini-`; `tests/real_oneshot.rs` | TAŞINDI |
| `_redact` (py/claudeops/ucli_client.py:251) | `oneshot.rs::redact` | `parity.rs::parity_oneshot` `saf` `sir-`; `oneshot::tests::secrets_are_removed_from_every_error_text` | TAŞINDI |
| `_effective_key` (py/claudeops/ucli_client.py:257) | `real/oneshot.rs::OneShot::chat_once` (`secret`) | `parity.rs::parity_oneshot` `sir-miras` | TAŞINDI |
| `_diag_approval` (py/claudeops/ucli_client.py:715) | `real/oneshot.rs::OneShot::chat_once` (`DiagLog`) | `parity.rs::parity_oneshot` `onay-kayit-yazilamadi` `onay-yaris` `onay-kilit-baglanti` | TAŞINDI |
| `_parse_turn` (py/claudeops/ucli_client.py:471) | üretimde çağıran yok (`UcliReplSession`ı yalnız testler kurar; `_parse_turn` onun parçası) | - | KAPSAM DIŞI |
| `UcliReplSession` (py/claudeops/ucli_client.py:578) | üretimde çağıran yok (`UcliReplSession`ı yalnız testler kurar; `_parse_turn` onun parçası) | - | KAPSAM DIŞI |
| `ucli_resume_approval` (py/claudeops/ucli_client.py:704) | T7: onay sürdürme (çağıran yalnız `web.py`) | - | KAPSAM DIŞI |
| `_resume_approval` (py/claudeops/ucli_client.py:720) | T7: onay sürdürme (çağıran yalnız `web.py`) | - | KAPSAM DIŞI |
| `_run_resume` (py/claudeops/ucli_client.py:732) | T7: onay sürdürme (çağıran yalnız `web.py`) | - | KAPSAM DIŞI |
| `USAGE_DIR` (py/claudeops/ucli_cost.py:16) | `probe.rs::Paths::ucli_usage_dir` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_CACHE` (py/claudeops/ucli_cost.py:17) | `real/ledger.rs::{CostLedger::cache, Snapshot}` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `_TTL` (py/claudeops/ucli_cost.py:18) | `cost.rs::TTL` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `DailyCapExceeded` (py/claudeops/ucli_cost.py:22) | `cost.rs::CostRefusal::CapExceeded` (+ `cost::refusal`, `CAP_CODE`) | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `DailyCapExceeded.__init__` (py/claudeops/ucli_cost.py:25) | `cost.rs::CostRefusal` `Display` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `log_path` (py/claudeops/ucli_cost.py:42) | `ucli.rs::usage_log_path` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `OTHER_DIR` (py/claudeops/ucli_cost.py:47) | `ucli.rs::Ctx::apply_cli_opts` (`<usage>/other`) | `parity.rs::parity_ucli` `hizmet-` | TAŞINDI |
| `other_log_path` (py/claudeops/ucli_cost.py:50) | `ucli.rs::usage_log_path` + `/other` | `parity.rs::parity_ucli` `hizmet-grok` `opts-` | TAŞINDI |
| `CACHE_1H_WRITE_MULT` (py/claudeops/ucli_cost.py:57) | `cost.rs::CACHE_1H_WRITE_MULT` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `write_mult` (py/claudeops/ucli_cost.py:60) | `cost.rs::write_mult` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `_day_start_ms` (py/claudeops/ucli_cost.py:66) | `real/ledger.rs::day_start_ms` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `per_session_usd` (py/claudeops/ucli_cost.py:71) | `real/ledger.rs::per_session_usd` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `rate_by_session` (py/claudeops/ucli_cost.py:91) | `real/ledger.rs::{rate_by_session, rate_usd_per_hour}` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `total_usd` (py/claudeops/ucli_cost.py:127) | `real/ledger.rs::total_usd` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `_date_ms` (py/claudeops/ucli_cost.py:147) | `real/ledger.rs::date_ms` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `credit_window` (py/claudeops/ucli_cost.py:157) | `cost.rs::credit_window` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `today_usd` (py/claudeops/ucli_cost.py:174) | `real/ledger.rs::today_usd` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `BY_SESSION_TOP` (py/claudeops/ucli_cost.py:179) | `cost.rs::BY_SESSION_TOP` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `state` (py/claudeops/ucli_cost.py:182) | `real/ledger.rs::CostLedger::{state, invalidate}` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `cap_exceeded` (py/claudeops/ucli_cost.py:215) | `real/ledger.rs::CostLedger::cap_exceeded` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `RESERVE_USD` (py/claudeops/ucli_cost.py:223) | `cost.rs::RESERVE_USD` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `RESERVE_TTL` (py/claudeops/ucli_cost.py:224) | `cost.rs::RESERVE_TTL` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `_RESERVE_LOCK` (py/claudeops/ucli_cost.py:225) | `real/ledger.rs::CostLedger::reserved` (`Mutex`) | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `_RESERVED` (py/claudeops/ucli_cost.py:226) | `real/ledger.rs::CostLedger::{reserved, reserved_sessions}` | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `reserve` (py/claudeops/ucli_cost.py:229) | `real/ledger.rs::CostLedger::{reserve, release, check_and_reserve_at}` (`_ledger_problem` = `ledger_problem`) | `parity.rs::parity_ledger`; `tests/real_ledger.rs` | TAŞINDI |
| `DEFAULTS` (py/claudeops/ucli_metrics.py:26) | `settings.rs::METRICS_DEFAULTS` | `parity.rs::parity_panel` `metrics-*` | TAŞINDI |
| `_num` (py/claudeops/ucli_metrics.py:41) | `settings.rs::metrics_num` (NaN sınırlanmaz, Python gibi) | `parity.rs::parity_panel` `metrics-*` `metrics-nan` | TAŞINDI |
| `get_config` (py/claudeops/ucli_metrics.py:49) | `settings.rs::{metrics_config, Settings::ucli_metrics_config}` | `parity.rs::parity_panel` `metrics-raw*` `metrics-ayar*` | TAŞINDI |

### Diğer dış bağımlılıklar (görevdeki satır kümesinin dışında, bilgi için)

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `atomic_write_json` (py/claudeops/atomic_json.py:71) | `rs/state` `fsutil.rs::atomic_write_json` | rs/state | KAPSAM DIŞI |
| `atomic_write_text` (py/claudeops/atomic_json.py:101) | `real/effects.rs::atomic_write_text` (birleştirmede rs/state `fsutil`) | `parity.rs` (tüm `Effect` aileleri gerçek uygulayıcıyla); `tests/real_fs.rs::atomic_write_keeps_the_private_mode_replaces_links_and_leaves_no_tmp` | TAŞINDI |
| `file_lock` (py/claudeops/atomic_json.py:132) | `rs/state` `fsutil.rs::FileLock` | rs/state | KAPSAM DIŞI |
| `spawn_env` (py/claudeops/authz.py:493) | `hooks.rs::spawn_env` (`Hooks`/`SpawnHooks`; kanca kaydı çağıranın) | `parity.rs::parity_g9` `{cli}-kanca` `{cli}-kanca-red` `kanca-` | TAŞINDI |
| `codex_screen_count` (py/claudeops/bg_work.py:130) | `bg_work.rs::codex_screen_count` | `parity.rs::parity_bg_work` `bg-ekran` (rastgele metinler dahil) | TAŞINDI |
| `codex_subagents_pending` (py/claudeops/bg_work.py:136) | `bg_work.rs::codex_subagents_pending` | `parity.rs::parity_bg_work` `bg-transkript-`, `bg-sekil-rollout-` | TAŞINDI |
| `screen_bg_count` (py/claudeops/bg_work.py:32) | `bg_work.rs::screen_bg_count` | `parity.rs::parity_bg_work` `bg-ekran` (rastgele metinler dahil) | TAŞINDI |
| `tail_lines` (py/claudeops/bg_work.py:160) | `live.rs::Live::tail_lines` | `parity.rs::parity_bg_work` `bg-dosya`, `bg-kuyruk-` | TAŞINDI |
| `transcript_pending_path` (py/claudeops/bg_work.py:112) | `live.rs::Live::transcript_pending_path` | `parity.rs::parity_bg_work` `bg-dosya`, `bg-kuyruk-` | TAŞINDI |
| `diag_log` (py/claudeops/diaglog.py:39) | `real/diaglog.rs::DiagLog` (DB aynası `Mirror` kancası; bağlama rs/state) | `parity.rs::parity_real` `gunluk-`; `tests/real_fs.rs::diag_log_appends_ordered_json_lines_rotates_and_never_fails_the_caller` | TAŞINDI |
| `find_sessions` (py/claudeops/discovery.py:200) | `cops-procscan` `discovery.rs::find_sessions` (rs/proc, birleşti); spawn sınırı `real/scan.rs::ProcScan` (`SessionScan`) | rs/proc: `fake_proc::discovers_each_cli_and_names`; sınır `tests/real_scan.rs` | KAPSAM DIŞI |
| `session_mcp_spec` (py/claudeops/extensions.py:440) | `hooks.rs::{session_mcp_spec, default_spec}` (kayıt `SessionMcpEntry` listesi çağıranın) | `parity.rs::parity_g9` `eklenti-` `{cli}-eklenti` `eklenti-acik-mcp` | TAŞINDI |
| `ensure_search_url` (py/claudeops/searxng.py:526) | `real/searxng.rs::ManagedSearch::search_url` (yalnız spawn yolu bağımlılıklarıyla) | `parity.rs::parity_searxng`; `tests/real_searxng.rs` | TAŞINDI |
| `read_json` (py/claudeops/statedocs.py:130) | `rs/state` `statedocs.rs::StateDocs::read` | rs/state; bu crate'te `StateDocStore::read`/`read_checked` ile bağlı (`parity_docs`) | KAPSAM DIŞI |
| `write_json` (py/claudeops/statedocs.py:175) | `rs/state` `statedocs.rs::StateDocs::write` | rs/state; bu crate'te `StateDocStore::write` ile bağlı (`parity_docs`) | KAPSAM DIŞI |
| `strip_ansi` (py/claudeops/tmux_backend.py:156) | `cops-tmux` `text.rs::strip_ansi` (tek kaynak; `tui.rs` yeniden dışa verir) | rs/tmux; `parity.rs::parity_tui` `g4-strip` | KAPSAM DIŞI |
| `tmux_attach_shell_fragment` (py/claudeops/tmux_backend.py:73) | `cops-tmux` `shell.rs::attach_shell_fragment` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_available` (py/claudeops/tmux_backend.py:27) | `cops-tmux` `shell.rs::tmux_available` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_capture` (py/claudeops/tmux_backend.py:113) | `cops-tmux` `query.rs::capture` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_ghost_session` (py/claudeops/tmux_backend.py:642) | `cops-tmux` `shell.rs::ghost_session` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_has_session` (py/claudeops/tmux_backend.py:104) | `cops-tmux` `query.rs::has_session` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_kill_session` (py/claudeops/tmux_backend.py:677) | `cops-tmux` `shell.rs::kill_session` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_new_session_shell_fragment` (py/claudeops/tmux_backend.py:58) | `cops-tmux` `shell.rs::new_session_shell_fragment` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |
| `tmux_send_keys` (py/claudeops/tmux_backend.py:160) | `rs/tmux` `keys.rs::send_text` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_send_special_key` (py/claudeops/tmux_backend.py:284) | `rs/tmux` `keys.rs::send_special_key` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_spawn_direct` (py/claudeops/tmux_backend.py:81) | `cops-tmux` `shell.rs::spawn_direct` (rs/tmux, birleşti); spawn sınırı `real/tmux.rs::CopsTmux` | rs/tmux; sınır `tests/real_tmux.rs`, `parity.rs::parity_g9` (sahte) | KAPSAM DIŞI |

### main `f4679f51` eşitlemesinin satırları (27 Kas)

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `DEFAULT_DESKTOP` (py/claudeops/startup_desktop.py:21) | `startup_desktop.rs::DEFAULT_DESKTOP` | `parity.rs::parity_g9` `masaustu-` `yok-` | TAŞINDI |
| `resolve_desktop` (py/claudeops/startup_desktop.py:24) | `startup_desktop.rs::resolve_desktop` | `parity.rs::parity_g9` `masaustu-`; `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `wanted_desktop` (py/claudeops/startup_desktop.py:39) | `startup_desktop.rs::wanted_desktop` (`pyfmt::py_int`) | `parity.rs::parity_g9` `masaustu-` | TAŞINDI |
| `desktop_count` (py/claudeops/startup_desktop.py:50) | `real/startup_desktop.rs::X11Desktop::desktop_count` | `tests/g9.rs::desktop_count_reads_wmctrl_and_unopenable_display_sends_nothing` (parite sahte sayım kullanır) | TAŞINDI |
| `_quote` (py/claudeops/startup_desktop.py:63) | `startup_desktop.rs::quote` | `parity.rs::parity_g9` `masaustu-`; `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `build_message` (py/claudeops/startup_desktop.py:67) | `startup_desktop.rs::build_message` | `parity.rs::parity_g9` `masaustu-`; `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `chunks` (py/claudeops/startup_desktop.py:71) | `startup_desktop.rs::chunks` | `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `new_startup_id` (py/claudeops/startup_desktop.py:76) | `startup_desktop.rs::startup_id` + `X11Desktop::new_startup_id` | `tests/g9.rs::desktop_resolution_message_and_chunks` (paritede iki tarafta sabit kimlik) | TAŞINDI |
| `_XClientData` (py/claudeops/startup_desktop.py:81) | `real/startup_desktop.rs::ClientData` | `real::startup_desktop::tests::client_message_layout_matches_xlib` | TAŞINDI |
| `_XClientMessageEvent` (py/claudeops/startup_desktop.py:87) | `real/startup_desktop.rs::ClientMessageEvent` | `real::startup_desktop::tests::client_message_layout_matches_xlib` | TAŞINDI |
| `_XEvent` (py/claudeops/startup_desktop.py:93) | `real/startup_desktop.rs::Event` | `real::startup_desktop::tests::client_message_layout_matches_xlib` | TAŞINDI |
| `_CLIENT_MESSAGE` (py/claudeops/startup_desktop.py:97) | `real/startup_desktop.rs::CLIENT_MESSAGE` | `tests/real_x11.rs::startup_message_reaches_a_private_x_server_like_python` (özel `Xvfb`; dinleyici yalnız `PropertyChangeMask`, Python gönderimiyle olay olay eşit) | TAŞINDI |
| `_PROPERTY_CHANGE_MASK` (py/claudeops/startup_desktop.py:98) | `real/startup_desktop.rs::PROPERTY_CHANGE_MASK` | `tests/real_x11.rs::startup_message_reaches_a_private_x_server_like_python` (özel `Xvfb`; dinleyici yalnız `PropertyChangeMask`, Python gönderimiyle olay olay eşit) | TAŞINDI |
| `send_startup_x11` (py/claudeops/startup_desktop.py:101) | `real/startup_desktop.rs::send_startup_x11` (`dlopen` libX11) | `tests/real_x11.rs::startup_message_reaches_a_private_x_server_like_python` (özel `Xvfb`; dinleyici yalnız `PropertyChangeMask`, Python gönderimiyle olay olay eşit); açılamayan ekran `tests/g9.rs::desktop_count_reads_wmctrl_and_unopenable_display_sends_nothing`; yapı düzeni `real::startup_desktop::tests::client_message_layout_matches_xlib`. `Xvfb` yoksa test atlanır; pencere yöneticisinin iletiye göre taşıması sınanamaz | TAŞINDI |
| `startup_env` (py/claudeops/startup_desktop.py:146) | `startup_desktop.rs::startup_env`; çağrı `spawn_exec.rs::Launcher::launch_window` (`Terminal::startup_env`, gerçek `GnomeTerminal::with_desktop`) | `parity.rs::parity_g9` `masaustu-`; `tests/g9.rs::gnome_terminal_desktop_is_off_by_default_and_reads_settings_each_time` | TAŞINDI |
| `HAIKU_LONG_PRICE` (py/claudeops/review.py:111) | `cops-review-core` `targets.rs::HAIKU_LONG_PRICE` (`cost.rs`, `ucli.rs` oradan) | `parity.rs::parity_ledger` `dilim`; `parity_ucli` `fiyat-` | TAŞINDI |
| `HAIKU_LONG_PROMPT` (py/claudeops/review.py:112) | `cops-review-core` `targets.rs::HAIKU_LONG_PROMPT` | `parity.rs::parity_ledger` `dilim` | TAŞINDI |
| `_scan_usage` (py/claudeops/review.py:1864) | `cost.rs::UsageScan` (`task_end` atlanır, Haiku dilimi istek başına); toplam yarısı `cops-review-core` `report.rs::usage_cost_usd` | `parity.rs::parity_ledger` `dilim` `satir`; iki kopya birbirine karşı `tests/usage_two_copies.rs` | TAŞINDI |
| `_with_ucli_error` (py/claudeops/commands/web.py:2116) | bağlayan uç (copsd/panel `_start`); pane okuması için `cops-tmux` `query.rs::Tmux::capture_joined` hazır | rs/tmux `reads_match_python` (`-J`) | KAPSAM DIŞI |

### 27 Kas ikinci turunun satırları (`726888f1` eşitlemesi, G3 3/5, TBD#401)

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `_window_titled` (py/claudeops/spawn.py:406) | `spawn_exec.rs::{Launcher::window_titled, window_listed}`; okuma `Terminal::window_list` (gerçek `real/launch.rs::GnomeTerminal`) | `parity.rs::parity_g9` `bekci-pencere-`; `tests/g9.rs::{watchdog_waits_instead_of_opening_a_second_window, watchdog_relaunches_unless_the_exact_title_is_listed, gnome_terminal_window_list_runs_wmctrl_on_the_given_display}` | TAŞINDI |
| `_row_effort` (py/claudeops/providers/claude_provider.py:368) | `claude_transcript.rs::assistant_effort` | `parity.rs::parity_transcript` `esit-alt-ajan-` `effort-` | TAŞINDI |
| `_key_env_refusal` (py/claudeops/ucli_client.py:260) | `oneshot.rs::check_key_env` + `real/oneshot.rs::OneShot::check_key_env` (`DEFAULT_KEY_ENV`, `Paths::settings_json`) | `parity.rs::parity_oneshot` `tbd401-`; `tests/real_oneshot.rs::only_known_key_env_names_start_a_child` | TAŞINDI |

## TEST EŞLEME TABLOSU

Güncel sayım (27 Kas): 1524 satır: TAŞINDI 739, TAŞINDI-TESTSİZ 0, KAPSAM DIŞI 785, EKSİK 0 (27 Kas: 19 TAŞINDI-TESTSİZ satır parite vakası ya da birim testiyle kapandı; `test_spawn_bad_tmux_name` eklendi).
- Vaka ailesi, `tests/parity/fam_*.rs` içindeki vaka kimliğinin bir parçasıdır. `TAŞINDI` = aynı davranış parite vakasıyla sınanıyor (Python testinin birebir kopyası değil).
- `steward_*` testlerinde `rs/stew` notu `origin/rs/stew:docs/rs-stew.md` satırından alındı.

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `AgyBinaryTest.test_inner_command_quotes_a_path_with_spaces` (py/tests/test_agy_binary_resolution.py:14) | `parity.rs::parity_build` `-override-bosluklu` | TAŞINDI |
| `AgyBinaryTest.test_model_choices_uses_the_resolved_binary` (py/tests/test_agy_binary_resolution.py:19) | `tests/model_sources.rs::agy_catalog_runs_the_resolved_binary_without_a_shell` | TAŞINDI |
| `AgyCompactionViewTests.test_checkpoint_becomes_boundary_and_plain_type23_is_ignored` (py/tests/test_agy_compaction_view.py:21) | `parity.rs::parity_chat` `agy-sikistirma` | TAŞINDI |
| `AgyLastExchange.test_last_pair_skips_empty_assistant_steps` (py/tests/test_agy_last_exchange.py:33) | `parity.rs::parity_chat` `agy-son-cift` | TAŞINDI |
| `AgyLastExchange.test_empty_conversation_and_no_assistant` (py/tests/test_agy_last_exchange.py:37) | `parity.rs::parity_chat` `agy-bos` `agy-yalniz-kullanici` | TAŞINDI |
| `AgyLastExchange.test_checkpoint_between_does_not_break_pairing` (py/tests/test_agy_last_exchange.py:41) | `parity.rs::parity_chat` `agy-arada-sinir` | TAŞINDI |
| `AgyLastExchange.test_missing_db_is_empty` (py/tests/test_agy_last_exchange.py:45) | `parity.rs::parity_chat` `agy-sid-yok-dosya` `agy-resume-dosyasiz` | TAŞINDI |
| `AgyModelsSwr.test_cold_blocks_then_stale_returns_old_immediately_and_refreshes_in_background` (py/tests/test_agy_models_swr.py:19) | `tests/model_sources.rs::agy_stale_list_is_returned_at_once_while_a_real_thread_refreshes`; `parity.rs::parity_model_sources` `src-agy-akis` | TAŞINDI |
| `AgySidsStoreTest.test_db_ready` (py/tests/test_agy_sids_store.py:31) | rs/state: `statedocs.rs::DB_READY` `agy_sids` | KAPSAM DIŞI |
| `AgySidsStoreTest.test_remember_writes_db_and_mirror` (py/tests/test_agy_sids_store.py:34) | DB + ayna yazımı `AgySidStore` gerçek uygulamasının işi (rs/state `statedocs`; uygulama henüz yazılmadı). Crate yalnız `save` çağırır: `tests/resume.rs::remember_saves_through_the_store_once` | KAPSAM DIŞI |
| `AgySidsStoreTest.test_unchanged_value_does_not_rewrite` (py/tests/test_agy_sids_store.py:42) | `tests/resume.rs::unchanged_value_does_not_rewrite_or_lock` | TAŞINDI |
| `AgySidsStoreTest.test_concurrent_remembers_lose_nothing` (py/tests/test_agy_sids_store.py:48) | `tests/resume.rs::concurrent_remembers_lose_nothing` (oku-değiştir-yaz kilit içinde; süreçler arası `flock` gerçek `AgySidStore`ta sınanmalı) | TAŞINDI |
| `RoutingSymlink.test_symlink_kept_and_target_written_with_mode` (py/tests/test_atomic_users_symlink.py:13) | `parity.rs::parity_misc` `sync-symlink` (gerçek `sync_one`); `parity.rs::parity_g9` `esitle-*-5` | TAŞINDI |
| `TokenFile.test_token_file_0600_atomic` (py/tests/test_atomic_users_symlink.py:30) | `tests/real_fs.rs::agent_token_is_0600_and_only_its_hash_is_registered` | TAŞINDI |
| `OrphanMarker.test_orphan_begin_does_not_eat_user_text` (py/tests/test_atomic_users_symlink.py:41) | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `OrphanMarker.test_normal_block_replaced_and_removed` (py/tests/test_atomic_users_symlink.py:50) | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `DefaultsTest.test_no_hooks_is_noop` (py/tests/test_authz.py:27) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_every_web_path_has_an_action` (py/tests/test_authz.py:34) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_uzakgoz_freshness_is_read_only_mapped` (py/tests/test_authz.py:40) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_unknown_path_unmapped` (py/tests/test_authz.py:43) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_fail_closed` (py/tests/test_authz.py:48) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_public_route_only_auth_prefix` (py/tests/test_authz.py:60) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_legacy_token_unchanged_without_hooks` (py/tests/test_authz.py:87) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_authenticator_replaces_token_and_401` (py/tests/test_authz.py:91) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_agents_cookie_human_gated_on_get_and_post` (py/tests/test_authz.py:96) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_agent_bearer_token_works_in_multi_user_mode` (py/tests/test_authz.py:110) | T9: çok kullanıcı kimliği; token doğrulama T7 | KAPSAM DIŞI |
| `HttpTest.test_authorizer_denies_403_and_audits` (py/tests/test_authz.py:130) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_resource_from_body_name` (py/tests/test_authz.py:141) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_post_gate_sees_body_resource_once` (py/tests/test_authz.py:149) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ticket_gives_panel_cookie_only_to_admin_in_multi_user` (py/tests/test_authz.py:169) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ticket_keeps_panel_cookie_in_single_user` (py/tests/test_authz.py:177) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_orch_get_names_query_denied_if_any_name_denied` (py/tests/test_authz.py:180) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_files_without_name_is_400_even_when_global_allowed` (py/tests/test_authz.py:187) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ws_handshake_filters_status_for_principal` (py/tests/test_authz.py:199) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_status_filter_applied` (py/tests/test_authz.py:218) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_public_route_skips_auth_but_other_ext_routes_need_admin` (py/tests/test_authz.py:224) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ui_extension_list_and_files` (py/tests/test_authz.py:236) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_session_event_emitted_on_success` (py/tests/test_authz.py:253) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_new_chat_and_adopt_event_use_real_instance_name` (py/tests/test_authz.py:264) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_session_event_emitted_before_response` (py/tests/test_authz.py:279) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `SpawnHookTest.test_no_hook_empty_and_threadlocal` (py/tests/test_authz.py:296) | T9: `authz` kancası ve ret biçimi | KAPSAM DIŞI |
| `SpawnHookTest.test_hook_env_refusal_and_fail_closed` (py/tests/test_authz.py:307) | T9: `authz` kancası ve ret biçimi | KAPSAM DIŞI |
| `SpawnHookTest.test_spawn_session_dry_run_gets_env` (py/tests/test_authz.py:320) | `parity.rs::parity_spawn` `-kanca`; kanca ortamı girdi | TAŞINDI |
| `SpawnHookTest.test_hook_session_usd_cap_min_with_default_and_popped_from_env` (py/tests/test_authz.py:330) | `parity.rs::parity_spawn` `kanca-` | TAŞINDI |
| `SpawnHookTest.test_refusal_formatting` (py/tests/test_authz.py:351) | T9: `authz` kancası ve ret biçimi | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_ws_ticket_bound_to_principal` (py/tests/test_authz.py:358) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_ticket_replaces_cookie_for_ws_only` (py/tests/test_authz.py:368) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_steward_resource_uses_sid_not_project_name` (py/tests/test_authz.py:382) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_question_page_access_check` (py/tests/test_authz.py:388) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_multi_resources` (py/tests/test_authz.py:405) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_names_query_and_body_each_a_resource` (py/tests/test_authz.py:413) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_files_path_never_becomes_a_resource` (py/tests/test_authz.py:420) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_event_sink_error_swallowed` (py/tests/test_authz.py:428) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_doc_prefix` (py/tests/test_authz.py:436) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_ws_client_view` (py/tests/test_authz.py:445) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtensionCommandTest.test_register_and_dispatch` (py/tests/test_authz.py:470) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtensionCommandTest.test_core_name_not_overridden_and_no_load_for_core` (py/tests/test_authz.py:479) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtensionCommandTest.test_bad_name` (py/tests/test_authz.py:488) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtActionTableTest.test_action_for_reads_ext_table_longest_first` (py/tests/test_authz.py:498) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtActionTableTest.test_register_action_prefix_restricted` (py/tests/test_authz.py:508) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtActionTableTest.test_ui_extension_title_en` (py/tests/test_authz.py:512) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ScreenFixture.test_busy_screens` (py/tests/test_bg_work.py:39) | `parity.rs::parity_bg_work` `bg-ekran` | TAŞINDI |
| `ScreenFixture.test_idle_screen_with_prose_numbers` (py/tests/test_bg_work.py:43) | `parity.rs::parity_bg_work` `bg-ekran` | TAŞINDI |
| `TranscriptFixture.test_pending_without_notification` (py/tests/test_bg_work.py:69) | `parity.rs::parity_bg_work` `bg-transkript-` | TAŞINDI |
| `TranscriptFixture.test_completed_by_tool_use_id_or_task_id` (py/tests/test_bg_work.py:72) | `parity.rs::parity_bg_work` `bg-transkript-` | TAŞINDI |
| `TranscriptFixture.test_foreground_and_stale` (py/tests/test_bg_work.py:77) | `parity.rs::parity_bg_work` `bg-transkript-` | TAŞINDI |
| `TranscriptFixture.test_errored_call_is_not_pending` (py/tests/test_bg_work.py:81) | `parity.rs::parity_bg_work` `bg-transkript-` | TAŞINDI |
| `TranscriptFixture.test_one_of_two_pending` (py/tests/test_bg_work.py:87) | `parity.rs::parity_bg_work` `bg-transkript-` | TAŞINDI |
| `SubagentActiveForUsesBoth.test_screen_makes_active_even_without_subagent_files` (py/tests/test_bg_work.py:92) | T10: `web_steward` alt ajan etkinliği; `bg_work` okuyucusu G6 | KAPSAM DIŞI |
| `SubagentActiveForUsesBoth.test_transcript_pending_makes_active` (py/tests/test_bg_work.py:98) | T10: `web_steward` alt ajan etkinliği; `bg_work` okuyucusu G6 | KAPSAM DIŞI |
| `ProviderBackgroundWork.test_base_unknown_and_claude_counts` (py/tests/test_bg_work.py:113) | `parity.rs::parity_live` `varsayilan-`, `ekran-claude-` | TAŞINDI |
| `UcliBackgroundWork.test_reads_status_field_never_guesses` (py/tests/test_bg_work.py:126) | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `CodexBackgroundWork.test_screen_and_rollout` (py/tests/test_bg_work.py:150) | `parity.rs::parity_bg_work` `bg-ekran`, `bg-transkript-` | TAŞINDI |
| `CodexBackgroundWork.test_provider_sums_screen_and_missing_rollout` (py/tests/test_bg_work.py:157) | `parity.rs::parity_live` `ekran-codex-`, `codex-ajan-` | TAŞINDI |
| `BrainPermission.test_default_allow_edit_is_a_valid_ucli_mode` (py/tests/test_brain_permission_ucli.py:11) | rs/stew: `brain_permission`; mod listesi `parity_model_effort` `bos-*` | KAPSAM DIŞI |
| `BrainPermission.test_applied_only_for_ucli` (py/tests/test_brain_permission_ucli.py:15) | rs/stew | KAPSAM DIŞI |
| `CompactionViewTests.test_boundary_and_summary_roles_keep_pre_compaction_messages` (py/tests/test_chat_compaction_view.py:21) | `parity.rs::parity_chat` `claude-temel` `claude-sinir-` | TAŞINDI |
| `CompactionViewTests.test_no_boundary_unchanged` (py/tests/test_chat_compaction_view.py:34) | `parity.rs::parity_chat` `claude-onek-` | TAŞINDI |
| `CompactionViewTests.test_sidechain_summary_ignored` (py/tests/test_chat_compaction_view.py:38) | `parity.rs::parity_chat` `claude-bayrak-isSidechain-` | TAŞINDI |
| `ClaudeModelsStoreTest.test_is_db_ready` (py/tests/test_claude_models_store.py:32) | rs/state: `statedocs.rs::DB_READY` `claude_models`; liste kuralı `parity_model_effort` `claude-state` | KAPSAM DIŞI |
| `ClaudeModelsStoreTest.test_write_goes_to_db_and_mirror_and_reads_from_db` (py/tests/test_claude_models_store.py:35) | rs/state: `statedocs.rs::DB_READY` `claude_models`; liste kuralı `parity_model_effort` `claude-state` | KAPSAM DIŞI |
| `ClaudeModelsStoreTest.test_db_wins_over_corrupt_or_missing_file` (py/tests/test_claude_models_store.py:42) | `tests/model_sources.rs::catalog_touches_only_its_own_source` (crate dosyayı okumaz, belge `ModelIo`dan); DB önceliği rs/state `statedocs` | TAŞINDI |
| `ClaudeModelsStoreTest.test_fallback_to_hardcoded_when_empty` (py/tests/test_claude_models_store.py:50) | `parity.rs::parity_model_effort` `claude-state` | TAŞINDI |
| `TrustFolder.test_adds_and_keeps_comments` (py/tests/test_copilot_trust.py:14) | `parity.rs::parity_build` `trust-dolu` | TAŞINDI |
| `TrustFolder.test_empty_list` (py/tests/test_copilot_trust.py:21) | `parity.rs::parity_build` `trust-bos` | TAŞINDI |
| `TrustFolder.test_keeps_private_mode` (py/tests/test_copilot_trust.py:26) | `tests/real_fs.rs::atomic_write_keeps_the_private_mode_replaces_links_and_leaves_no_tmp` | TAŞINDI |
| `TrustFolder.test_idempotent_and_missing` (py/tests/test_copilot_trust.py:34) | `parity.rs::parity_build` `trust-var` `trust-anahtar-yok` | TAŞINDI |
| `FindSessionsSidTests.test_a_fresh_session_gets_the_live_sid_from_the_json_entry` (py/tests/test_discovery_sid.py:77) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_resumed_session_keeps_its_sid_and_stays_resumed` (py/tests/test_discovery_sid.py:85) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_the_live_json_sid_wins_over_a_stale_cmdline_sid` (py/tests/test_discovery_sid.py:92) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_without_a_json_entry_the_cmdline_value_is_used_exactly_as_before` (py/tests/test_discovery_sid.py:101) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_json_entry_without_a_sid_never_blanks_the_cmdline_sid` (py/tests/test_discovery_sid.py:106) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_tui_renamed_session_is_listed_once_under_its_spawn_name` (py/tests/test_discovery_sid.py:110) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_each_session_gets_its_own_sid_by_pid` (py/tests/test_discovery_sid.py:116) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_json_entry_of_another_cli_never_donates_its_sid` (py/tests/test_discovery_sid.py:121) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_non_claude_cli_keeps_its_cmdline_sid_and_its_old_is_fresh` (py/tests/test_discovery_sid.py:129) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `IsFreshTests.test_flag_unknown_falls_back_to_the_sid` (py/tests/test_discovery_sid.py:138) | rs/proc: `session.rs::Session::is_fresh` | KAPSAM DIŞI |
| `IsFreshTests.test_flag_known_wins_over_the_sid` (py/tests/test_discovery_sid.py:143) | rs/proc: `session.rs::Session::is_fresh` | KAPSAM DIŞI |
| `SplitTierTests.test_tiered_ids` (py/tests/test_effort_by_model.py:56) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SplitTierTests.test_untiered_ids_are_untouched` (py/tests/test_effort_by_model.py:62) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SplitTierTests.test_non_string` (py/tests/test_effort_by_model.py:66) | rs/prov: gereksiz: Rust imzası yalnız dize alır | KAPSAM DIŞI |
| `SortAndNearestTests.test_sort_levels_orders_dedupes_keeps_unknown_last` (py/tests/test_effort_by_model.py:71) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_requested_in_levels_is_returned_as_is` (py/tests/test_effort_by_model.py:75) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_too_high_goes_to_the_top_supported` (py/tests/test_effort_by_model.py:78) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_prefers_below_over_equally_near_above` (py/tests/test_effort_by_model.py:81) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_nothing_below_takes_lowest_above` (py/tests/test_effort_by_model.py:85) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_empty_request_uses_default` (py/tests/test_effort_by_model.py:88) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_unknown_request_falls_back_via_default_rank` (py/tests/test_effort_by_model.py:92) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_empty_levels` (py/tests/test_effort_by_model.py:95) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_all_unknown_level_names` (py/tests/test_effort_by_model.py:98) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `AgyEffortTests.test_tier_in_id_fixes_the_levels` (py/tests/test_effort_by_model.py:103) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_untiered_non_gemini_has_no_info` (py/tests/test_effort_by_model.py:109) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_base_name_uses_live_siblings` (py/tests/test_effort_by_model.py:114) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_base_name_without_siblings_is_unknown` (py/tests/test_effort_by_model.py:118) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_empty_model` (py/tests/test_effort_by_model.py:122) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_panel_default_max_no_longer_conflicts_with_tiered_id` (py/tests/test_effort_by_model.py:127) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_empty_effort_no_longer_defaults_to_medium_against_a_high_id` (py/tests/test_effort_by_model.py:134) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_requested_effort_follows_the_id_not_the_other_way` (py/tests/test_effort_by_model.py:140) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_matching_effort_is_unchanged` (py/tests/test_effort_by_model.py:145) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_non_gemini_still_gets_no_effort_flag` (py/tests/test_effort_by_model.py:151) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_argon_ids_are_consistent_with_their_tier` (py/tests/test_effort_by_model.py:159) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_gemini_base_name_clamps_to_live_tiers` (py/tests/test_effort_by_model.py:166) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_gemini_base_name_without_info_keeps_old_behaviour` (py/tests/test_effort_by_model.py:171) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `CodexEffortTests.test_reads_per_model_levels` (py/tests/test_effort_by_model.py:195) | `parity.rs::parity_model_effort` `codex-cache` | TAŞINDI |
| `CodexEffortTests.test_unknown_model_or_empty_list_is_no_info` (py/tests/test_effort_by_model.py:199) | `parity.rs::parity_model_effort` `codex-cache` | TAŞINDI |
| `CodexEffortTests.test_missing_or_corrupt_cache_is_no_info` (py/tests/test_effort_by_model.py:204) | `parity.rs::parity_model_effort` `codex-cache-bozuk` `bos-` | TAŞINDI |
| `CodexEffortTests.test_unsupported_effort_is_clamped_supported_is_untouched` (py/tests/test_effort_by_model.py:211) | `parity.rs::parity_model_effort` `codex-cache` ; `parity.rs::parity_spawn` `codex-effort` | TAŞINDI |
| `CodexEffortTests.test_model_missing_from_cache_passes_through` (py/tests/test_effort_by_model.py:216) | `parity.rs::parity_model_effort` `codex-cache` ; `parity.rs::parity_spawn` `codex-effort` | TAŞINDI |
| `OtherProvidersPassThroughTests.test_fleet_values_pass_through_unchanged` (py/tests/test_effort_by_model.py:237) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `OtherProvidersPassThroughTests.test_unknown_values_are_not_rewritten_either` (py/tests/test_effort_by_model.py:244) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `OtherProvidersPassThroughTests.test_only_agy_and_codex_override_model_levels` (py/tests/test_effort_by_model.py:249) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `SpawnWiringTests.test_adjusted_effort_reaches_the_command_and_is_logged` (py/tests/test_effort_by_model.py:268) | `parity.rs::parity_spawn` `agy-effort-ayar` `codex-effort` | TAŞINDI |
| `SpawnWiringTests.test_unchanged_effort_is_not_logged` (py/tests/test_effort_by_model.py:275) | `parity.rs::parity_spawn` `-dry` | TAŞINDI |
| `SpawnWiringTests.test_resolver_failure_never_blocks_the_spawn` (py/tests/test_effort_by_model.py:280) | rs/prov: gereksiz: `Providers::resolve_effort` hata veremez | KAPSAM DIŞI |
| `EnvNames.test_valid_and_invalid` (py/tests/test_envnames.py:9) | `parity.rs::parity_spawn` `filter`; dize olmayan girdi tiple engelli | TAŞINDI |
| `EnvNames.test_spawn_filters_newline_and_dangerous` (py/tests/test_envnames.py:15) | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `McpHook.test_validation` (py/tests/test_extensions_mcp.py:22) | T9: `extensions` MCP kancası ve stdio sunucusu | KAPSAM DIŞI |
| `McpHook.test_stdio_roundtrip` (py/tests/test_extensions_mcp.py:34) | T9: `extensions` MCP kancası ve stdio sunucusu | KAPSAM DIŞI |
| `McpHook.test_unknown_server_exit_2` (py/tests/test_extensions_mcp.py:51) | T9: `extensions` MCP kancası ve stdio sunucusu | KAPSAM DIŞI |
| `SessionAttach.test_attach_predicate_and_spec` (py/tests/test_extensions_mcp.py:68) | `parity.rs::parity_g9` `eklenti-0` (eşleşmeyen + eşleşen, araç adları), `eklenti-1` (koşul hatası yutulur), `eklenti-3`; kayıt API'si (`attach_mcp_to_sessions` kayıtsız kimlik reddi) çağıranın (eklenti katmanı) | TAŞINDI |
| `SessionAttach.test_claude_config_path_per_ext_and_spawn_wiring` (py/tests/test_extensions_mcp.py:82) | `parity.rs::parity_spawn` `-eklenti-mcp` `-mcp` | TAŞINDI |
| `SessionAttach.test_spawn_attaches_only_matching_cwd_and_claude` (py/tests/test_extensions_mcp.py:89) | `parity.rs::parity_g9` `{cli}-eklenti` (yalnız `claude` koşulu sorar), `eklenti-0`, `eklenti-acik-mcp`, `{cli}-kuru` | TAŞINDI |
| `LastRealRequestEpochTests.test_returns_the_time_of_the_latest_real_request` (py/tests/test_handover_cache_policy.py:76) | `parity_transcript` `son-istek` | TAŞINDI |
| `LastRealRequestEpochTests.test_synthetic_placeholder_after_a_real_request_does_not_refresh_the_cache` (py/tests/test_handover_cache_policy.py:80) | `parity_transcript` `sentetik-sifir-effortlu` `istek-model-sentetik` | TAŞINDI |
| `LastRealRequestEpochTests.test_subagent_rows_are_a_separate_context_and_do_not_count` (py/tests/test_handover_cache_policy.py:86) | `parity_transcript` `alt-ajan` `kullanim-sidechain-` | TAŞINDI |
| `LastRealRequestEpochTests.test_rows_without_any_usage_tokens_do_not_count` (py/tests/test_handover_cache_policy.py:90) | `parity_transcript` `kullanimsiz` `kullanim-` | TAŞINDI |
| `LastRealRequestEpochTests.test_user_rows_are_ignored_and_no_assistant_means_unknown` (py/tests/test_handover_cache_policy.py:96) | `parity_transcript` `yalniz-kullanici` | TAŞINDI |
| `LastRealRequestEpochTests.test_missing_file_is_unknown` (py/tests/test_handover_cache_policy.py:100) | `parity_transcript` `yollar` | TAŞINDI |
| `LastRealRequestEpochTests.test_large_file_is_read_from_the_tail` (py/tests/test_handover_cache_policy.py:103) | `parity_transcript` `pencere-` | TAŞINDI |
| `ClaudeProviderCacheHookTests.test_ttl_is_one_hour` (py/tests/test_handover_cache_policy.py:110) | `parity_transcript` `model-listesi` | TAŞINDI |
| `ClaudeProviderCacheHookTests.test_last_request_epoch_reads_only_the_exact_sid_file` (py/tests/test_handover_cache_policy.py:113) | `parity_transcript` `istek-claude`; `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `ClaudeProviderCacheHookTests.test_no_sid_or_no_matching_file_is_unknown_never_the_newest_sibling` (py/tests/test_handover_cache_policy.py:123) | `parity_transcript` `istek-claude`; `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `ClaudeProviderCacheHookTests.test_effort_switch_keeps_cache_by_model` (py/tests/test_handover_cache_policy.py:135) | `parity_transcript` `model-listesi` | TAŞINDI |
| `ClaudeProviderCacheHookTests.test_other_providers_keep_the_old_behaviour` (py/tests/test_handover_cache_policy.py:148) | `parity_transcript` `istek-codex` `istek-ucli` `model-listesi`; `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `SessionFileSidTests.test_verified_file_gives_the_session_id` (py/tests/test_handover_cache_policy.py:177) | `parity.rs::parity_resume` `devam-kayit-tamam` (Rust imzası `i64`: metin pid tip düzeyinde yok) | TAŞINDI |
| `SessionFileSidTests.test_a_reused_pid_is_rejected_by_proc_start` (py/tests/test_handover_cache_policy.py:182) | `parity.rs::parity_resume` `devam-stat-baska` `devam-kayit-start-` | TAŞINDI |
| `SessionFileSidTests.test_unverifiable_or_inconsistent_files_are_not_trusted` (py/tests/test_handover_cache_policy.py:186) | `parity.rs::parity_resume` `devam-kayit-` | TAŞINDI |
| `SessionFileSidTests.test_dead_process_and_missing_file_and_no_pid` (py/tests/test_handover_cache_policy.py:202) | `parity.rs::parity_resume` `devam-stat-yok` `devam-kayit-dosya-yok` (metin pid `"abc"` tip düzeyinde yok) | TAŞINDI |
| `LastRequestEpochByPidTests.test_fresh_session_without_cmdline_sid_is_found_through_its_pid` (py/tests/test_handover_cache_policy.py:234) | `parity_transcript` `istek-claude` (`session_file_sid` gerçek; kayıt dosyası + sahte `/proc`); `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `LastRequestEpochByPidTests.test_without_a_pid_the_sidless_session_stays_unknown` (py/tests/test_handover_cache_policy.py:239) | `parity_transcript` `istek-claude` (`session_file_sid` gerçek; kayıt dosyası + sahte `/proc`); `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `LastRequestEpochByPidTests.test_the_newest_request_of_the_two_candidate_files_wins` (py/tests/test_handover_cache_policy.py:245) | `parity_transcript` `istek-claude` (`session_file_sid` gerçek; kayıt dosyası + sahte `/proc`); `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `LastRequestEpochByPidTests.test_a_missing_candidate_file_falls_back_to_the_other_one` (py/tests/test_handover_cache_policy.py:255) | `parity_transcript` `istek-claude` (`session_file_sid` gerçek; kayıt dosyası + sahte `/proc`); `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `LastRequestEpochByPidTests.test_a_sibling_session_in_the_same_directory_is_never_picked_up` (py/tests/test_handover_cache_policy.py:260) | `parity_transcript` `istek-claude` (`session_file_sid` gerçek; kayıt dosyası + sahte `/proc`); `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `LastRequestEpochByPidTests.test_empty_conversation_file_is_unknown` (py/tests/test_handover_cache_policy.py:266) | `parity_transcript` `istek-claude` (`session_file_sid` gerçek; kayıt dosyası + sahte `/proc`); `cache_candidates_are_exact_files_and_newest_wins` | TAŞINDI |
| `PromptCacheIsWarmTests.test_margin_is_five_minutes` (py/tests/test_handover_cache_policy.py:288) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_fresh_request_is_warm` (py/tests/test_handover_cache_policy.py:291) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_boundary_and_older_is_cold` (py/tests/test_handover_cache_policy.py:296) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_future_timestamp_from_clock_skew_counts_as_warm` (py/tests/test_handover_cache_policy.py:301) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_unknown_when_provider_has_no_ttl_or_no_transcript` (py/tests/test_handover_cache_policy.py:304) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_now_defaults_to_the_wall_clock` (py/tests/test_handover_cache_policy.py:309) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_the_process_id_reaches_the_provider` (py/tests/test_handover_cache_policy.py:314) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_warm_opus_keeps_its_model_but_still_lowers_effort` (py/tests/test_handover_cache_policy.py:373) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_cold_opus_goes_down_to_sonnet_then_effort_in_that_order` (py/tests/test_handover_cache_policy.py:385) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_fable_follows_the_same_rule` (py/tests/test_handover_cache_policy.py:395) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_boundary_is_the_ttl_minus_margin` (py/tests/test_handover_cache_policy.py:403) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_models_that_are_not_downgrade_candidates_never_get_a_model_command` (py/tests/test_handover_cache_policy.py:411) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_unknown_warmth_keeps_the_old_always_downgrade_behaviour` (py/tests/test_handover_cache_policy.py:420) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_a_failing_cache_probe_never_blocks_the_wrap_up` (py/tests/test_handover_cache_policy.py:427) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_escape_hatch_restores_the_old_behaviour_and_never_probes` (py/tests/test_handover_cache_policy.py:434) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_missing_setting_defaults_to_cache_aware` (py/tests/test_handover_cache_policy.py:442) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_provider_without_a_cache_ttl_keeps_the_old_behaviour` (py/tests/test_handover_cache_policy.py:448) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_warm_sonnet_55_gets_the_cache_safe_effort_drop` (py/tests/test_handover_cache_policy.py:459) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_warm_sonnet_5_skips_the_effort_drop_that_would_rewrite_the_cache` (py/tests/test_handover_cache_policy.py:466) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_cold_sonnet_5_gets_the_effort_drop_because_the_cache_is_gone_anyway` (py/tests/test_handover_cache_policy.py:476) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_unknown_warmth_on_sonnet_5_keeps_the_old_behaviour` (py/tests/test_handover_cache_policy.py:482) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_effort_already_at_or_below_the_target_is_left_alone` (py/tests/test_handover_cache_policy.py:487) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_effort_command_failure_is_swallowed` (py/tests/test_handover_cache_policy.py:493) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `EffortDowngradeTests.test_public_wrapper_keeps_its_old_positional_signature` (py/tests/test_handover_cache_policy.py:500) | T4: `handover` devir politikası; transkript ve önbellek girdileri taşındı (G3), `handover_*_downgrade`/canlı geçiş G4 | KAPSAM DIŞI |
| `CallSiteWiringTests.test_cli_path_calls_the_shared_policy_once_per_target` (py/tests/test_handover_cache_policy.py:520) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `CallSiteWiringTests.test_web_path_calls_the_shared_policy_with_the_spawn_time_values` (py/tests/test_handover_cache_policy.py:534) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `CallSiteWiringTests.test_web_path_targets_the_resolved_session_for_unique_base` (py/tests/test_handover_cache_policy.py:547) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `CallSiteWiringTests.test_real_policy_runs_end_to_end_through_the_web_path` (py/tests/test_handover_cache_policy.py:564) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `LastAssistantSinceTests.test_since_returns_only_rows_written_after_the_process_started` (py/tests/test_live_model_effort.py:62) | `parity_transcript` `surec-sonrasi` | TAŞINDI |
| `LastAssistantSinceTests.test_only_previous_incarnation_rows_means_unknown` (py/tests/test_live_model_effort.py:68) | `parity_transcript` `onceki-surec` | TAŞINDI |
| `LastAssistantSinceTests.test_without_since_behaviour_is_unchanged` (py/tests/test_live_model_effort.py:74) | `parity_transcript` `onceki-surec` (`since`siz okuma) | TAŞINDI |
| `LastAssistantSinceTests.test_row_without_timestamp_is_not_treated_as_old` (py/tests/test_live_model_effort.py:79) | `parity_transcript` `damgasiz`; `damga-yok-` | TAŞINDI |
| `LastAssistantSinceTests.test_scan_stops_at_the_first_older_row` (py/tests/test_live_model_effort.py:84) | `parity_transcript` `ilk-eskide-dur`; `since_stops_the_scan_without_reading_further` | TAŞINDI |
| `LiveModelEffortTests.test_live_values_written_by_this_process_replace_cmdline_values` (py/tests/test_live_model_effort.py:107) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_fresh_resume_without_a_turn_keeps_cmdline_values` (py/tests/test_live_model_effort.py:111) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_effort_missing_in_live_rows_falls_back_per_field` (py/tests/test_live_model_effort.py:115) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_another_sessions_file_is_ignored` (py/tests/test_live_model_effort.py:119) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_non_claude_and_sidless_sessions_never_touch_the_file` (py/tests/test_live_model_effort.py:123) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_unknown_process_start_falls_back` (py/tests/test_live_model_effort.py:129) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_unchanged_file_is_not_reread_and_changed_file_is_` (py/tests/test_live_model_effort.py:133) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEffortTests.test_read_error_falls_back_and_does_not_raise` (py/tests/test_live_model_effort.py:151) | T1: `web._live_model_effort` (önbellek, tam ad kuralı); `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEndpointTests.test_live_model_ignores_previous_incarnation` (py/tests/test_live_model_effort.py:168) | T1: `web._live_model`/`_live_effort` uçları; `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEndpointTests.test_live_effort_ignores_previous_incarnation` (py/tests/test_live_model_effort.py:175) | T1: `web._live_model`/`_live_effort` uçları; `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `LiveModelEndpointTests.test_neighbour_transcript_is_not_reported` (py/tests/test_live_model_effort.py:183) | T1: `web._live_model`/`_live_effort` uçları; `since` okuması taşındı (G3) | KAPSAM DIŞI |
| `EffortSwitchNoBlindEnter.test_no_dialog_no_enter` (py/tests/test_live_model_effort.py:215) | `tests/tui.rs::an_old_result_line_does_not_count`; parite `g4-pane-effort-yaziyor` | TAŞINDI |
| `NoteMirrorTests.test_records_the_pid_under_the_spec` (py/tests/test_mirror_marker.py:47) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `NoteMirrorTests.test_same_spec_accumulates_pids` (py/tests/test_mirror_marker.py:52) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `NoteMirrorTests.test_anything_else_leaves_the_dict_alone` (py/tests/test_mirror_marker.py:58) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_viewers_are_collected_in_the_same_pass` (py/tests/test_mirror_marker.py:91) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_viewers_are_not_sessions_and_fleet_result_is_unchanged` (py/tests/test_mirror_marker.py:97) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_default_does_not_collect_anything` (py/tests/test_mirror_marker.py:104) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_a_real_viewer_process_is_seen_by_the_real_scan` (py/tests/test_mirror_marker.py:110) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_open_and_closed_are_stamped_per_remote_row` (py/tests/test_mirror_marker.py:148) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_same_name_on_two_hosts_is_told_apart` (py/tests/test_mirror_marker.py:155) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_match_is_exact_not_a_prefix` (py/tests/test_mirror_marker.py:162) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_cached_rows_are_copied_not_mutated` (py/tests/test_mirror_marker.py:169) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_stale_value_from_upstream_is_overwritten` (py/tests/test_mirror_marker.py:177) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_no_marker_at_all_when_the_state_is_unknown` (py/tests/test_mirror_marker.py:182) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_empty_set_means_known_and_closed` (py/tests/test_mirror_marker.py:187) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_local_closed_and_retired_rows_are_not_stamped` (py/tests/test_mirror_marker.py:192) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_a_dict_works_as_the_container_like_find_sessions_hands_it_over` (py/tests/test_mirror_marker.py:201) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_unpolled_host_adds_no_rows_and_no_crash` (py/tests/test_mirror_marker.py:206) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `StatusPayloadWiringTests.test_remote_rows_carry_the_marker_from_the_fleet_scan` (py/tests/test_mirror_marker.py:243) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `StatusPayloadWiringTests.test_exactly_one_scan_carries_the_collector` (py/tests/test_mirror_marker.py:249) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `StatusPayloadWiringTests.test_a_closed_window_flips_the_marker_on_the_next_tick` (py/tests/test_mirror_marker.py:259) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_host_and_name` (py/tests/test_mirror_window.py:33) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_bare_name_is_local` (py/tests/test_mirror_window.py:36) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_flags_before_or_after_the_target` (py/tests/test_mirror_window.py:39) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_value_of_a_flag_is_not_mistaken_for_the_target` (py/tests/test_mirror_window.py:44) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_once_is_not_a_window` (py/tests/test_mirror_window.py:47) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_other_commands_do_not_match` (py/tests/test_mirror_window.py:50) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_watch_without_a_target` (py/tests/test_mirror_window.py:56) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_empty_parts` (py/tests/test_mirror_window.py:60) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_collects_pids_per_spec` (py/tests/test_mirror_window.py:78) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_other_users_processes_are_ignored` (py/tests/test_mirror_window.py:83) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_unreadable_processes_are_skipped` (py/tests/test_mirror_window.py:86) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_default_uid_is_the_current_user` (py/tests/test_mirror_window.py:89) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_a_process_vanishing_mid_scan_is_skipped` (py/tests/test_mirror_window.py:94) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `FocusWindowTests.test_uses_exact_title_matching_and_the_given_display` (py/tests/test_mirror_window.py:104) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `FocusWindowTests.test_failures_are_false_not_exceptions` (py/tests/test_mirror_window.py:117) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `OpenMirrorWindowSpawnTests.test_gnome_terminal_argv` (py/tests/test_mirror_window.py:138) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_the_command_runs_cops_watch_against_this_panels_port` (py/tests/test_mirror_window.py:145) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it` (py/tests/test_mirror_window.py:151) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_arguments_are_shell_quoted` (py/tests/test_mirror_window.py:158) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_environment` (py/tests/test_mirror_window.py:162) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_popen_failure_is_false` (py/tests/test_mirror_window.py:170) | `parity.rs::parity_g9` `ayna-1`; `tests/g9.rs::gnome_terminal_popen_failures` | TAŞINDI |
| `OpenMirrorWindowBackendTests.test_success_spawns_once_with_the_panels_port` (py/tests/test_mirror_window.py:211) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_local_sessions_are_rejected` (py/tests/test_mirror_window.py:215) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_bad_characters_never_reach_the_command_line` (py/tests/test_mirror_window.py:222) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_unknown_host` (py/tests/test_mirror_window.py:229) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_session_must_be_in_the_hosts_last_known_state` (py/tests/test_mirror_window.py:234) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_a_session_without_tmux_has_no_terminal_to_mirror` (py/tests/test_mirror_window.py:245) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_no_x11_display` (py/tests/test_mirror_window.py:250) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_an_open_mirror_is_focused_not_duplicated` (py/tests/test_mirror_window.py:257) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_force_opens_a_second_one` (py/tests/test_mirror_window.py:263) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_another_sessions_mirror_does_not_count` (py/tests/test_mirror_window.py:269) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_launch_failure` (py/tests/test_mirror_window.py:274) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_messages_follow_the_language` (py/tests/test_mirror_window.py:280) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_route_is_declared_local_only` (py/tests/test_mirror_window.py:323) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_post_with_a_remote_host_field_is_handled_locally` (py/tests/test_mirror_window.py:326) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_force_flag_is_passed_through` (py/tests/test_mirror_window.py:331) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_name_is_required` (py/tests/test_mirror_window.py:335) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_token_is_required` (py/tests/test_mirror_window.py:340) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `LayoutRecognisesMirrorWindowsTests.test_a_mirror_window_is_tiled_once_its_spec_is_known` (py/tests/test_mirror_window.py:355) | T7: pencere yerleşimi | KAPSAM DIŞI |
| `LayoutRecognisesMirrorWindowsTests.test_without_the_spec_it_is_skipped_as_before` (py/tests/test_mirror_window.py:360) | T7: pencere yerleşimi | KAPSAM DIŞI |
| `LayoutRecognisesMirrorWindowsTests.test_title_from_the_viewer_survives_list_windows_cleaning` (py/tests/test_mirror_window.py:365) | T7: pencere yerleşimi | KAPSAM DIŞI |
| `WebNeedsHoCachedTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` (py/tests/test_needs_ho_transcript.py:64) | T1: web önbelleği; `needs_ho` rs/proc | KAPSAM DIŞI |
| `WebNeedsHoCachedTests.test_only_without_a_sid_it_falls_back_to_the_newest_file` (py/tests/test_needs_ho_transcript.py:68) | `tests/resume.rs::sidless_or_missing_transcript_falls_back_to_the_newest`; `parity.rs::parity_resume` `devam-claude-` (`jsonl`). `web._needs_ho_cached` bağlaması T1 | TAŞINDI |
| `HandoverBatchTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` (py/tests/test_needs_ho_transcript.py:89) | T4: devir toplu akışı; `needs_ho` rs/proc | KAPSAM DIŞI |
| `HandoverBatchTests.test_without_a_sid_it_falls_back_to_the_newest_file` (py/tests/test_needs_ho_transcript.py:93) | `tests/resume.rs::sidless_or_missing_transcript_falls_back_to_the_newest`; `parity.rs::parity_resume` `devam-claude-` (`jsonl`). `handover_faz1` bağlaması T4 | TAŞINDI |
| `MatchesProcTest.test_repl_is_fleet` (py/tests/test_proc07_io_ucli_not_fleet.py:15) | rs/proc: `providers.rs::detect` | KAPSAM DIŞI |
| `MatchesProcTest.test_oneshot_and_reviewer_are_not_fleet` (py/tests/test_proc07_io_ucli_not_fleet.py:18) | rs/proc: `providers.rs::detect` | KAPSAM DIŞI |
| `IoAskLiveNameTest.test_rejects_live_same_name` (py/tests/test_proc07_io_ucli_not_fleet.py:28) | T7: `/api/io` ucu | KAPSAM DIŞI |
| `IoAskLiveNameTest.test_other_name_goes_through` (py/tests/test_proc07_io_ucli_not_fleet.py:36) | T7: `/api/io` ucu | KAPSAM DIŞI |
| `NoBlindEnterTest.test_permission_dialog_is_not_confirmed` (py/tests/test_proc08_model_switch_no_blind_enter.py:33) | `tests/tui.rs::permission_dialog_is_never_confirmed_even_with_switch_text_above_it`; parite `g4-pane-model-izin` | TAŞINDI |
| `NoBlindEnterTest.test_switch_dialog_confirmed_once` (py/tests/test_proc08_model_switch_no_blind_enter.py:36) | `tests/tui.rs::switch_dialog_is_confirmed_once_and_waits_for_a_new_result`; parite `g4-pane-model-model-diyalog` | TAŞINDI |
| `NoBlindEnterTest.test_applied_without_dialog` (py/tests/test_proc08_model_switch_no_blind_enter.py:39) | `tests/tui.rs::applied_without_dialog_sends_no_key`; parite `g4-pane-model-model-uygulandi` | TAŞINDI |
| `TestBase.test_default_and_unsupported_are_none` (py/tests/test_provider_live_context.py:23) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `TestCodex.test_last_token_count_input_tokens` (py/tests/test_provider_live_context.py:43) | `parity.rs::parity_live` `codex-ctx-` | TAŞINDI |
| `TestCodex.test_no_token_event_or_no_file_is_none` (py/tests/test_provider_live_context.py:47) | `parity.rs::parity_live` `codex-ctx-` | TAŞINDI |
| `TestCodex.test_null_info_is_none` (py/tests/test_provider_live_context.py:52) | `parity.rs::parity_live` `codex-ctx-` | TAŞINDI |
| `TestCopilot.test_latest_main_agent_row` (py/tests/test_provider_live_context.py:75) | `parity.rs::parity_live` `copilot-` | TAŞINDI |
| `TestCopilot.test_unknown_session_or_no_db_is_none` (py/tests/test_provider_live_context.py:78) | `parity.rs::parity_live` `copilot-` | TAŞINDI |
| `TestStatusRow.test_context_info_uses_provider_hook_and_hides_unknown` (py/tests/test_provider_live_context.py:89) | T1: panel `web._context_info_cached` önbelleği; sağlayıcı kancası `parity.rs::parity_live` `codex-ctx-` | KAPSAM DIŞI |
| `WantsSplitTests.test_ucli_no_wrapup_but_has_conversation_and_stuck` (py/tests/test_provider_wants_split.py:15) | `tests/tui.rs::ucli_has_a_conversation_and_stuck_recovery_but_no_wrapup`; parite `g4-sabit-ucli` | TAŞINDI |
| `WantsSplitTests.test_claude_defaults_follow_has_conversation` (py/tests/test_provider_wants_split.py:21) | `tests/tui.rs::claude_wants_follow_has_conversation`; parite `g4-sabit-claude` | TAŞINDI |
| `WantsSplitTests.test_shell_wants_nothing` (py/tests/test_provider_wants_split.py:26) | `tests/tui.rs::shell_wants_nothing`; parite `g4-sabit-shell` | TAŞINDI |
| `DefaultsTest.test_claude_defaults_to_newest_sonnet_medium` (py/tests/test_routing_guidance.py:32) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultsTest.test_provider_without_model_choices_gives_empty_default` (py/tests/test_routing_guidance.py:38) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultsTest.test_override_wins_and_invalid_override_falls_back` (py/tests/test_routing_guidance.py:44) | `parity.rs::parity_model_effort` `ayar-` | TAŞINDI |
| `DefaultsTest.test_other_providers_keep_old_top_level_effort` (py/tests/test_routing_guidance.py:53) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `GuidanceTest.test_enabled_by_default_and_bundled_path_used` (py/tests/test_routing_guidance.py:60) | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `GuidanceTest.test_off_disables_flag` (py/tests/test_routing_guidance.py:65) | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `GuidanceTest.test_override_text_is_written_and_used` (py/tests/test_routing_guidance.py:71) | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `GuidanceTest.test_guidance_failure_never_breaks_spawn` (py/tests/test_routing_guidance.py:80) | `tests/py_rows.rs::guidance_failure_never_breaks_spawn` (paketli yönerge yok, dizin, UTF-8 değil, boş: bayraksız, yazım/günlük yok) | TAŞINDI |
| `CodexSyncTest.test_agy_file_is_created_with_only_the_block_and_removed_with_it` (py/tests/test_routing_guidance.py:90) | `parity.rs::parity_g9` `esitle-0-0` (oluşturulur), `esitle-1-3` (kalkınca silinir) | TAŞINDI |
| `CodexSyncTest.test_existing_agy_file_keeps_user_text` (py/tests/test_routing_guidance.py:98) | `parity.rs::parity_g9` `esitle-0-2` `esitle-1-2`; `parity_misc` `sync1-3-true` | TAŞINDI |
| `CodexSyncTest.test_missing_file_is_not_created` (py/tests/test_routing_guidance.py:117) | `parity.rs::parity_g9` `esitle-0-0` `esitle-0-2`; `tests/g9.rs::default_sync_paths_are_under_home` | TAŞINDI |
| `CodexSyncTest.test_write_is_idempotent_keeps_rest_and_backs_up` (py/tests/test_routing_guidance.py:122) | `parity.rs::parity_g9` `esitle-0-1` (yedek), `esitle-yedek-var`; `parity_misc` `sync2-6-false` (değişmedi) | TAŞINDI |
| `CodexSyncTest.test_text_change_replaces_block_and_off_removes_it` (py/tests/test_routing_guidance.py:131) | `parity.rs::parity_g9` `esitle-2-3`, `esitle-1-3`; `parity_misc` `sync1-3-false` | TAŞINDI |
| `RustToolchainPickTest.test_single_toolchain_without_env` (py/tests/test_rust_toolchain_pick.py:30) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `RustToolchainPickTest.test_prefix_match` (py/tests/test_rust_toolchain_pick.py:35) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `RustToolchainPickTest.test_mismatch_is_error_not_fallback` (py/tests/test_rust_toolchain_pick.py:40) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `RustToolchainDefaultTest.test_single_toolchain_without_env` (py/tests/test_rust_toolchain_pick.py:59) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `RustToolchainDefaultTest.test_default_toolchain_picks_one` (py/tests/test_rust_toolchain_pick.py:64) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `RustToolchainDefaultTest.test_short_default_name` (py/tests/test_rust_toolchain_pick.py:70) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `RustToolchainDefaultTest.test_env_still_wins` (py/tests/test_rust_toolchain_pick.py:76) | `tests/real_fs.rs::rust_toolchain_never_silently_picks_another_one`; `parity.rs::parity_real` `zincir-` | TAŞINDI |
| `ServiceModelsCache.test_ttl_is_24h` (py/tests/test_service_models_cache.py:28) | `tests/model_sources.rs::lifetimes_and_limits_match_python` | TAŞINDI |
| `ServiceModelsCache.test_success_cached_for_a_day` (py/tests/test_service_models_cache.py:31) | `parity.rs::parity_model_sources` `src-svc-ttl` | TAŞINDI |
| `ServiceModelsCache.test_failure_returns_empty_and_retries_after_60s` (py/tests/test_service_models_cache.py:48) | `parity.rs::parity_model_sources` `src-svc-ttl` `src-svc-bos-sonuc` | TAŞINDI |
| `DetectDisplayTest.test_socket_only_x0` (py/tests/test_spawn_detect_display_socket.py:25) | `tests/py_rows.rs::detect_display_socket_only_x0` (denetimli yol varlığı) | TAŞINDI |
| `DetectDisplayTest.test_lock_still_works` (py/tests/test_spawn_detect_display_socket.py:28) | `tests/py_rows.rs::detect_display_lock_still_works` | TAŞINDI |
| `DetectDisplayTest.test_prefers_1_over_0` (py/tests/test_spawn_detect_display_socket.py:31) | `tests/py_rows.rs::detect_display_prefers_1_over_0` | TAŞINDI |
| `DetectDisplayTest.test_nothing_defaults_1` (py/tests/test_spawn_detect_display_socket.py:34) | `tests/py_rows.rs::detect_display_nothing_defaults_1_and_env_wins` | TAŞINDI |
| `DetectDisplayTest.test_env_wins` (py/tests/test_spawn_detect_display_socket.py:37) | `parity.rs::parity_spawn` `display-env` | TAŞINDI |
| `EnvFilter.test_filters` (py/tests/test_spawn_env_filter.py:11) | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `GhostDetectTest.test_old_bare_bash_is_ghost` (py/tests/test_spawn_ghost_reclaim.py:25) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_live_cli_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:28) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_young_session_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:31) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_bash_with_child_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:34) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_no_session_or_garbage` (py/tests/test_spawn_ghost_reclaim.py:37) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_mixed_panes` (py/tests/test_spawn_ghost_reclaim.py:42) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `ReclaimTest.test_ghost_killed_and_tail_logged` (py/tests/test_spawn_ghost_reclaim.py:57) | `tests/g9.rs::ghost_is_killed_and_only_screen_counts_are_logged` (ekran metni günlükte yok, yalnız sayılar); `parity.rs::parity_g9` `hayalet-` | TAŞINDI |
| `ReclaimTest.test_shell_provider_untouched` (py/tests/test_spawn_ghost_reclaim.py:63) | `tests/g9.rs::shell_provider_is_untouched`; `parity.rs::parity_g9` `hayalet-shell` | TAŞINDI |
| `ReclaimTest.test_not_ghost_untouched` (py/tests/test_spawn_ghost_reclaim.py:66) | `tests/g9.rs::non_ghost_and_missing_tmux_are_untouched`; `parity.rs::parity_g9` `hayalet-degil` `hayalet-tmuxsuz` | TAŞINDI |
| `ReclaimTest.test_error_never_raises` (py/tests/test_spawn_ghost_reclaim.py:69) | `tests/g9.rs::reclaim_never_panics_and_never_logs_the_screen` (Rust'ta tmux sınırı hata yükseltemez; `spawn_ghost_reclaim_error` dalı gereksiz) | TAŞINDI |
| `SpawnPriority.test_default_and_exempt_and_off` (py/tests/test_spawn_priority.py:17) | `parity.rs::parity_spawn` `prefix-` | TAŞINDI |
| `SpawnPriority.test_child_inherits_nice` (py/tests/test_spawn_priority.py:27) | `tests/py_rows.rs::priority_prefix_child_inherits_nice` (gerçek `sh`/`bash`, `/proc/$$/stat` 19. alan) | TAŞINDI |
| `TestDefaultClaudeMdGolden.test_default_output_is_byte_identical_to_pre_p5` (py/tests/test_steward_brain.py:62) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `TestDefaultClaudeMdGolden.test_identity_section_only_for_non_default` (py/tests/test_steward_brain.py:71) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `TestWorkspace.test_default_workspace_claude_md_is_unchanged_and_not_rewritten` (py/tests/test_steward_brain.py:144) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors ... | KAPSAM DIŞI |
| `TestWorkspace.test_default_persona_override_still_applies` (py/tests/test_steward_brain.py:157) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors ... | KAPSAM DIŞI |
| `TestWorkspace.test_identity_workspace_is_separate_with_identity_and_model_rule` (py/tests/test_steward_brain.py:163) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp ... | KAPSAM DIŞI |
| `TestWorkspace.test_identity_persona_falls_back_to_shared` (py/tests/test_steward_brain.py:180) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp ... | KAPSAM DIŞI |
| `TestBrainMcp.test_verify_uses_connect_heartbeat` (py/tests/test_steward_brain.py:193) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_start_without_mcp_restarts_once_then_gives_up` (py/tests/test_steward_brain.py:201) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_start_defaults_to_new_conversation` (py/tests/test_steward_brain.py:216) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_close_note_written_without_model_turn` (py/tests/test_steward_brain.py:223) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp ... | KAPSAM DIŞI |
| `TestBrainMcp.test_notools_verdict_pure` (py/tests/test_steward_brain.py:231) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_recover_restarts_once_with_cooldown` (py/tests/test_steward_brain.py:249) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_mcp_server_heartbeat_hook` (py/tests/test_steward_brain.py:265) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_touch_records_call_and_connect` (py/tests/test_steward_brain.py:274) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_brain_spec_default_is_the_old_command_line` (py/tests/test_steward_brain.py:282) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_disabled_identity_never_starts_a_brain` (py/tests/test_steward_brain.py:289) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_enabled_identity_starts_its_own_brain` (py/tests/test_steward_brain.py:306) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_default_brain_start_is_unchanged` (py/tests/test_steward_brain.py:324) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_running_brain_is_not_started_twice` (py/tests/test_steward_brain.py:338) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges ... | KAPSAM DIŞI |
| `TestBrainStart.test_brain_stop_uses_only_the_act_stop_path_with_the_exact_name` (py/tests/test_steward_brain.py:345) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestClaudeMcpConfigFile.test_identity_gets_its_own_config_file` (py/tests/test_steward_brain.py:353) | `parity.rs::parity_spawn` `-mcp`; `--steward <kimlik>` dosya adı | TAŞINDI |
| `TestMcpIdentity.test_default_server_adds_nothing` (py/tests/test_steward_brain.py:379) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestMcpIdentity.test_identity_server_adds_it_to_every_call_and_the_brain_cannot_change_it` (py/tests/test_steward_brain.py:390) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestMcpIdentity.test_run_validates_the_identity_and_sets_it` (py/tests/test_steward_brain.py:420) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::valid_custom_id_vectors ... | KAPSAM DIŞI |
| `TestMcpIdentity.test_cli_parses_the_flag` (py/tests/test_steward_brain.py:433) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestCtxFor.test_resolution` (py/tests/test_steward_brain.py:445) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::valid_custom_id_vectors ... | KAPSAM DIŞI |
| `TestCtxFor.test_unknown_identity_is_an_explicit_error_and_writes_nothing` (py/tests/test_steward_brain.py:456) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors ... | KAPSAM DIŞI |
| `TestCtxFor.test_no_param_means_default_and_old_callers_work` (py/tests/test_steward_brain.py:467) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestCtxFor.test_requests_reach_the_right_store` (py/tests/test_steward_brain.py:475) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestCtxFor.test_manual_tick_and_note_and_skip_use_the_identity` (py/tests/test_steward_brain.py:501) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_human_in_default_context_is_unrestricted` (py/tests/test_steward_brain.py:532) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_human_in_other_context_only_own_projects_and_brain` (py/tests/test_steward_brain.py:542) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_brain_in_identity_context` (py/tests/test_steward_brain.py:554) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_reads_are_limited_to_own_projects_outside_default` (py/tests/test_steward_brain.py:563) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_project_roundtrip_and_validation` (py/tests/test_steward_core_a.py:56) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::build_ownership_index_vectors ... | KAPSAM DIŞI |
| `StoreTest.test_defer_answer_keeps_question_open` (py/tests/test_steward_core_a.py:67) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_questions_dedup_answer_deliver` (py/tests/test_steward_core_a.py:76) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_ideas_and_log` (py/tests/test_steward_core_a.py:88) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_persona_override_and_bundled` (py/tests/test_steward_core_a.py:99) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_ask_ending_with_colon_takes_following_lines` (py/tests/test_steward_core_a.py:105) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_ignores_writing_examples` (py/tests/test_steward_core_a.py:117) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_ignores_inline_code_mention_in_prose` (py/tests/test_steward_core_a.py:126) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_job_line` (py/tests/test_steward_core_a.py:135) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers` (py/tests/test_steward_core_a.py:152) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `PromptTest.test_directive_by_phase_and_answer` (py/tests/test_steward_core_a.py:167) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors ... | KAPSAM DIŞI |
| `PromptTest.test_tour_prompt_lists_items_and_end_marker` (py/tests/test_steward_core_a.py:182) | rs/stew: rs-stew.md: prompts::build_tour_prompt_vectors, prompts::p_clip | KAPSAM DIŞI |
| `PromptTest.test_workspace_claude_md` (py/tests/test_steward_core_a.py:192) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `RulesTest.test_handover_then_respawn` (py/tests/test_steward_core_a.py:206) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_handover_grace_expiry_and_gone_session` (py/tests/test_steward_core_a.py:222) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_markers_once_per_reply` (py/tests/test_steward_core_a.py:230) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_done_marker_stops_session` (py/tests/test_steward_core_a.py:240) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_done_confirmed_with_open_owner_question_pauses_not_done` (py/tests/test_steward_core_a.py:244) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_done_marker_ignored_when_project_notes_have_no_done_tag` (py/tests/test_steward_core_a.py:255) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_due_projects_respect_slots_priority_and_cadence` (py/tests/test_steward_core_a.py:261) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_todo_change_opens_active_project_without_waiting_cadence` (py/tests/test_steward_core_a.py:274) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_todo_change_reopens_done_project_to_planned` (py/tests/test_steward_core_a.py:292) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_todo_change_paused_project_asks_owner_once_per_day` (py/tests/test_steward_core_a.py:303) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_first_observation_done_project_with_open_work_goes_planned` (py/tests/test_steward_core_a.py:318) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_daily_sweep_done_project_with_unchanged_sha` (py/tests/test_steward_core_a.py:327) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_daily_sweep_paused_asks_once` (py/tests/test_steward_core_a.py:339) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_only_fable_cila_open_work_does_not_trigger` (py/tests/test_steward_core_a.py:347) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_drain_starts_nothing_but_keeps_answers_and_running` (py/tests/test_steward_core_a.py:354) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_slot_pressure_stops_idle_session` (py/tests/test_steward_core_a.py:361) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_answer_delivery_running_busy_or_stopped` (py/tests/test_steward_core_a.py:372) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_adhoc_session_answer_goes_to_asking_session_only_if_running` (py/tests/test_steward_core_a.py:382) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_instance_sessions_map_to_blueprint_project` (py/tests/test_steward_core_a.py:394) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_tour_only_when_brain_idle_and_due` (py/tests/test_steward_core_a.py:400) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_phase_model_effort` (py/tests/test_steward_core_a.py:416) | rs/stew: rs-stew.md: prompts::phase_model_effort_vectors | KAPSAM DIŞI |
| `CardCoreTest.test_build_raw_card_reads_doc_heads_and_git` (py/tests/test_steward_core_a.py:424) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `CardCoreTest.test_raw_card_without_git_or_docs` (py/tests/test_steward_core_a.py:440) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `CardCoreTest.test_parse_card_json_variants` (py/tests/test_steward_core_a.py:452) | rs/stew: rs-stew.md: cards::p_short, cards::p_str_list, cards::parse_card_json_vectors, prompts::p_clip | KAPSAM DIŞI |
| `CardCoreTest.test_make_card_falls_back_to_raw_fields` (py/tests/test_steward_core_a.py:465) | rs/stew: rs-stew.md: cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines ... | KAPSAM DIŞI |
| `CardCoreTest.test_refresh_reason_matrix_and_failure_backoff` (py/tests/test_steward_core_a.py:483) | rs/stew: rs-stew.md: cards::card_path_vectors, cards::card_refresh_reason_vectors, cards::p_short ... | KAPSAM DIŞI |
| `CardCoreTest.test_store_stale_and_listing` (py/tests/test_steward_core_a.py:506) | rs/stew: rs-stew.md: cards::card_one_liner_vectors, cards::card_path_vectors, identity::name_rules_edges ... | KAPSAM DIŞI |
| `CardCoreTest.test_model_pick_prompt_and_tour_rendering` (py/tests/test_steward_core_a.py:517) | rs/stew: rs-stew.md: cards::build_card_prompt_vectors, cards::p_short, cards::pick_card_model_vectors ... | KAPSAM DIŞI |
| `OneshotProviderTest.test_claude_argv_shape_and_unsupported_default` (py/tests/test_steward_core_a.py:534) | `parity.rs::parity_build` `oneshot`; varsayılan "desteklenmiyor" dahil | TAŞINDI |
| `OneshotProviderTest.test_ucli_oneshot_uses_chat_once_without_key_in_argv` (py/tests/test_steward_core_a.py:560) | `parity.rs::parity_oneshot` `ucli-ayar-anahtari`; `tests/real_oneshot.rs::the_configured_key_goes_into_the_child_only_for_the_ucli_oneshot` | TAŞINDI |
| `OneshotProviderTest.test_oneshot_runs_argv_and_reports_failures` (py/tests/test_steward_core_a.py:579) | `parity.rs::parity_oneshot` `argv-` | TAŞINDI |
| `SimilarAnswersTest.test_ranks_by_similarity_and_excludes_self` (py/tests/test_steward_core_a.py:604) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SimilarAnswersTest.test_open_or_unanswered_ignored_and_prompt_renders` (py/tests/test_steward_core_a.py:613) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RosterGateTest.test_active_phase_needs_roster_but_idea_does_not` (py/tests/test_steward_core_a.py:622) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ScanCacheTest.test_scan_is_cached_inside_a_scope_and_invalidated_by_start` (py/tests/test_steward_core_a.py:636) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EngineSmallsTest.test_fail_logged_is_pruned_and_thread_safe` (py/tests/test_steward_core_a.py:663) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EngineSmallsTest.test_shutdown_blockers_survive_corrupt_jobs_file` (py/tests/test_steward_core_a.py:673) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownOnlyLeavesPausedTest.test_done_records_left_paused_and_warns` (py/tests/test_steward_core_a.py:685) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainCannotPauseTest.test_brain_cannot_pause_or_done_but_owner_can` (py/tests/test_steward_core_a.py:705) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownPlanTest.test_waits_for_quiet_then_handover_then_stop_then_brain` (py/tests/test_steward_core_a.py:721) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownPlanTest.test_subagent_blocks_and_timeouts_leave_session_open` (py/tests/test_steward_core_a.py:749) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownPlanTest.test_stale_ready_text_before_handover_does_not_count` (py/tests/test_steward_core_a.py:762) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReviewFindings20261029Test.test_job_requests_for_different_files_are_not_merged` (py/tests/test_steward_core_a.py:773) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReviewFindings20261029Test.test_done_and_plan_ready_in_prose_are_ignored` (py/tests/test_steward_core_a.py:779) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `ReviewFindings20261029Test.test_owner_only_false_positives` (py/tests/test_steward_core_a.py:787) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_paraphrased_open_question_is_merged` (py/tests/test_steward_core_a.py:798) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_other_project_or_topic_not_merged` (py/tests/test_steward_core_a.py:808) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_short_distinct_questions_not_merged` (py/tests/test_steward_core_a.py:814) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_routine_question_promoted_when_asked_to_owner` (py/tests/test_steward_core_a.py:819) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_answered_question_not_merged_into_open_path` (py/tests/test_steward_core_a.py:834) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_topic_tokens` (py/tests/test_steward_core_a.py:851) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_generic_names_alone_do_not_match` (py/tests/test_steward_core_a.py:856) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_open_question_rephrased_is_merged_and_keeps_old_text` (py/tests/test_steward_core_a.py:861) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_hold_answer_suppresses_same_topic` (py/tests/test_steward_core_a.py:873) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_non_hold_answer_lets_new_decision_open` (py/tests/test_steward_core_a.py:880) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_old_open_question_outside_window_not_merged` (py/tests/test_steward_core_a.py:887) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_other_project_not_merged` (py/tests/test_steward_core_a.py:895) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SalientReaskTest.test_paraphrased_same_topic_is_duplicate` (py/tests/test_steward_core_a.py:905) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SalientReaskTest.test_different_topic_not_duplicate` (py/tests/test_steward_core_a.py:910) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneDeferralTest.test_done_deferred_while_subagent_then_applied` (py/tests/test_steward_core_a.py:916) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneDeferralTest.test_deferred_done_dropped_when_no_done_tag_added_later` (py/tests/test_steward_core_a.py:927) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneDeferralTest.test_done_immediate_without_subagent` (py/tests/test_steward_core_a.py:938) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AnswerStartPhaseTest.test_active_phase_starts` (py/tests/test_steward_core_a.py:952) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AnswerStartPhaseTest.test_owner_answer_reopens_paused_and_done_project` (py/tests/test_steward_core_a.py:955) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_is_negative_answer` (py/tests/test_steward_core_a.py:963) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_negative_answer_does_not_reopen` (py/tests/test_steward_core_a.py:975) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_hold_answers_real_texts_do_not_reopen` (py/tests/test_steward_core_a.py:980) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_sweep_question_has_options` (py/tests/test_steward_core_a.py:991) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_long_owner_instruction_reaches_brain` (py/tests/test_steward_core_a.py:1018) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_second_held_instruction_gets_its_own_item` (py/tests/test_steward_core_a.py:1027) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_later_question_does_not_overwrite_held_item` (py/tests/test_steward_core_a.py:1032) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_short_hold_brain_and_routine_answers_stay_silent` (py/tests/test_steward_core_a.py:1039) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_done_hands_over_then_stops_never_respawns` (py/tests/test_steward_core_a.py:1063) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_session_gone_during_done_handover_is_not_respawned` (py/tests/test_steward_core_a.py:1074) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_grace_expiry_still_stops` (py/tests/test_steward_core_a.py:1080) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_small_context_skips_handover` (py/tests/test_steward_core_a.py:1087) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_switch_off_is_old_direct_stop` (py/tests/test_steward_core_a.py:1095) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_owner_answer_stops_reasking_and_bitti_closes` (py/tests/test_steward_core_a.py:1101) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_unknown_open_work_symlinked_worktree_accepts_proof` (py/tests/test_steward_core_a.py:1115) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_unanswered_conflict_still_asks` (py/tests/test_steward_core_a.py:1122) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_plain_done_asks_for_confirmation_and_keeps_phase` (py/tests/test_steward_core_a.py:1139) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_second_plain_done_does_not_spam_but_ttl_reasks` (py/tests/test_steward_core_a.py:1147) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirmed_with_evidence_sets_done_and_stops` (py/tests/test_steward_core_a.py:1155) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirmed_without_evidence_is_not_done` (py/tests/test_steward_core_a.py:1160) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirmed_but_local_open_work_asks_owner_not_done` (py/tests/test_steward_core_a.py:1166) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_no_steward_done_tag_ignores_both_markers` (py/tests/test_steward_core_a.py:1178) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirm_marker_is_not_plain_done_and_placeholder_ignored` (py/tests/test_steward_core_a.py:1184) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `DoneConfirmTest.test_subagent_active_defers_confirmed` (py/tests/test_steward_core_a.py:1192) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_open_work_of_counts_local_todo` (py/tests/test_steward_core_a.py:1197) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_open_tbd_of_falls_back_to_main_worktree` (py/tests/test_steward_core_a.py:1212) | rs/stew: rs-stew.md: markers::count_open_tbd_edges, markers::count_open_tbd_vectors | KAPSAM DIŞI |
| `TourQuietTest.test_skipped_unchanged_item_stays_out_until_state_changes_or_ttl` (py/tests/test_steward_core_a.py:1242) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_plan_tick_records_tour_sig_and_honors_skip_seen` (py/tests/test_steward_core_a.py:1256) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_stale_undelivered_answer_closed_not_toured` (py/tests/test_steward_core_a.py:1270) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_projectless_answer_closes_when_brain_never_runs` (py/tests/test_steward_core_a.py:1285) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_brain_question_answer_goes_to_live_session_named_by_project` (py/tests/test_steward_core_a.py:1299) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_keepwarm_ok_does_not_change_the_item_signature_and_routine_carries_age` (py/tests/test_steward_core_a.py:1309) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_observe_tour_does_not_burn_blocked_tour_budget` (py/tests/test_steward_core_a.py:1323) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_pending_count_is_the_full_list_even_when_a_tour_is_sent` (py/tests/test_steward_core_a.py:1339) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_count_open_tbd_new_format_needs_an_AÇIK_heading` (py/tests/test_steward_core_a.py:1350) | rs/stew: rs-stew.md: markers::count_open_tbd_edges, markers::count_open_tbd_vectors | KAPSAM DIŞI |
| `TourQuietTest.test_shutdown_unknown_activity_waits_unless_idle` (py/tests/test_steward_core_a.py:1356) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_blocked_item_closed_after_max_tours_not_urgent_again` (py/tests/test_steward_core_a.py:1364) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `IdleSkipTest.test_no_idle_item_for_waiting_or_done_projects` (py/tests/test_steward_core_a.py:1389) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MergedAnswersTest.test_planner_merges_same_session_answers_in_one_action` (py/tests/test_steward_core_a.py:1405) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MergedAnswersTest.test_answer_waits_while_subagent_active` (py/tests/test_steward_core_a.py:1413) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MergedAnswersTest.test_subagent_active_for_reads_mtime` (py/tests/test_steward_core_a.py:1421) | `web_steward.subagent_active_for` (T10, rs/stew); crate yalnız transkript yolunu verir: `parity.rs::parity_resume` `devam-claude-` (`jsonl`) | KAPSAM DIŞI |
| `MergedAnswersTest.test_compact_answer_directive_drops_preamble` (py/tests/test_steward_core_a.py:1438) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors ... | KAPSAM DIŞI |
| `MergedAnswersTest.test_directive_contains_all_answers` (py/tests/test_steward_core_a.py:1454) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors ... | KAPSAM DIŞI |
| `ScanTicksTest.test_leading_code_tick_in_question_kept` (py/tests/test_steward_core_b.py:56) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `ScanTicksTest.test_wrapped_marker_and_wrapped_body` (py/tests/test_steward_core_b.py:60) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `PlanMarkersTest.test_records_asks_and_ideas_only` (py/tests/test_steward_core_b.py:71) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PlanMarkersTest.test_same_reply_not_rescanned_and_routine_needs_question_mark` (py/tests/test_steward_core_b.py:77) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PlanMarkersTest.test_matches_plan_tick_marker_actions` (py/tests/test_steward_core_b.py:84) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ObserveCoreTest.test_filter_act_passes_everything_and_clears_traces` (py/tests/test_steward_core_b.py:93) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ObserveCoreTest.test_filter_observe_splits_dedups_and_prunes` (py/tests/test_steward_core_b.py:100) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ObserveCoreTest.test_observed_visit_paces_due_projects_across_ticks` (py/tests/test_steward_core_b.py:117) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_daily_summary_counts_and_filters_by_date` (py/tests/test_steward_core_b.py:138) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_summary_due` (py/tests/test_steward_core_b.py:171) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_log_reader_and_summary_text` (py/tests/test_steward_core_b.py:179) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_compact_log_folds_ticks_and_keeps_summary_identical` (py/tests/test_steward_core_b.py:195) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_missed_summary_dates_and_catch_up` (py/tests/test_steward_core_b.py:236) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RoutineQuestionTest.test_marker_scan_and_session_reply_opens_routine_ask` (py/tests/test_steward_core_b.py:277) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RoutineQuestionTest.test_routine_goes_to_brain_tour_not_phone_and_escalates_late` (py/tests/test_steward_core_b.py:288) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RoutineQuestionTest.test_brain_answer_is_delivered_like_any_answer` (py/tests/test_steward_core_b.py:313) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_finished_handover_of_second_session_stops_it_instead_of_respawn` (py/tests/test_steward_core_b.py:320) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_economy_rules_only_touch_managed_sessions` (py/tests/test_steward_core_b.py:333) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_brain_respawn_after_handover_is_a_new_conversation` (py/tests/test_steward_core_b.py:346) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_context_tokens_trigger_handover` (py/tests/test_steward_core_b.py:354) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_line_count_is_only_a_fallback_and_ignores_young_sessions` (py/tests/test_steward_core_b.py:369) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_workspace_claude_md_carries_the_permanent_model_rule` (py/tests/test_steward_core_b.py:392) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_fable_sessions_use_the_lower_context_threshold` (py/tests/test_steward_core_b.py:401) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_context_tokens_from_transcript_tail` (py/tests/test_steward_core_b.py:417) | T10: `web_steward.context_tokens_for` (model/effort/sıcaklık değil); `rs-stew.md`de EKSİK | KAPSAM DIŞI |
| `StuckBrainTest.test_status_sentence_is_not_a_routine_question_and_tour_is_capped` (py/tests/test_steward_core_b.py:436) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StuckBrainTest.test_two_failed_tours_restart_the_brain` (py/tests/test_steward_core_b.py:449) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StuckBrainTest.test_undeliverable_adhoc_answer_is_given_up` (py/tests/test_steward_core_b.py:464) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DeliveryTargetTest.test_prefers_asking_session_then_main_over_experiment_sessions` (py/tests/test_steward_core_b.py:477) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_similar_answered_question_is_redelivered_not_reopened` (py/tests/test_steward_core_b.py:500) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_repeat_cap_other_project_old_and_clarification_open_new` (py/tests/test_steward_core_b.py:510) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_answered_routine_question_asked_to_owner_opens_new` (py/tests/test_steward_core_b.py:521) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_directive_lists_earlier_answers` (py/tests/test_steward_core_b.py:531) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `QuestionOptionsTest.test_options_normalize_resolve_and_key` (py/tests/test_steward_core_b.py:542) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `QuestionOptionsTest.test_notification_text_and_page_html` (py/tests/test_steward_core_b.py:571) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SettingsTest.test_defaults_parse_and_clamp` (py/tests/test_steward_core_b.py:596) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::valid_steward_id_vectors | KAPSAM DIŞI |
| `McpTest.test_tools_list_and_dispatch_cover_each_other` (py/tests/test_steward_core_b.py:619) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `McpTest.test_tool_calls_hit_expected_endpoints` (py/tests/test_steward_core_b.py:631) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobMarkerParseTest.test_hyphenated_kind_and_malformed_body_are_not_dropped` (py/tests/test_steward_core_b.py:653) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `JobMarkerParseTest.test_prose_mentions_and_placeholders_still_ignored` (py/tests/test_steward_core_b.py:659) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `QuestionPageHttpTest.test_question_page_round_trip` (py/tests/test_steward_core_b.py:693) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `QuestionPageHttpTest.test_notify_phone_sets_click_header` (py/tests/test_steward_core_b.py:716) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_non_routine_question_is_owner_only` (py/tests/test_steward_core_b.py:743) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_routine_owner_only_topics` (py/tests/test_steward_core_b.py:749) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_commit_push_merge_build_deploy_are_not_owner_only` (py/tests/test_steward_core_b.py:756) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_blocked_marker_goes_to_brain_not_owner` (py/tests/test_steward_core_b.py:763) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_rules_text_no_longer_reserves_commit_push_for_owner` (py/tests/test_steward_core_b.py:768) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_readonly_job_request_not_owner_only` (py/tests/test_steward_core_b.py:773) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_plain_routine_is_answerable` (py/tests/test_steward_core_b.py:784) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_defer_reason` (py/tests/test_steward_core_b.py:788) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_tour_retry_gap_after_deferral` (py/tests/test_steward_core_b.py:794) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourDeliveryTest.test_short_tour_inline` (py/tests/test_steward_core_b.py:799) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourDeliveryTest.test_long_tour_goes_to_file_and_old_files_pruned` (py/tests/test_steward_core_b.py:805) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownKeepModeTest.test_keep_does_not_stop` (py/tests/test_steward_core_b.py:831) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownKeepModeTest.test_default_stops` (py/tests/test_steward_core_b.py:836) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownOnlyTest.test_only_closes_selected_project_and_leaves_rest` (py/tests/test_steward_core_b.py:845) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownBlockersTest.test_quiet_session_without_blocker_gets_handover` (py/tests/test_steward_core_b.py:868) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownBlockersTest.test_blocked_session_waits_and_records_reason` (py/tests/test_steward_core_b.py:872) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownBlockersTest.test_blocked_session_left_open_after_wait_max` (py/tests/test_steward_core_b.py:879) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_count_open_tbd` (py/tests/test_steward_core_b.py:893) | rs/stew: rs-stew.md: markers::count_open_tbd_edges, markers::count_open_tbd_vectors | KAPSAM DIŞI |
| `SmartTickTest.test_routine_question_skips_tour_interval` (py/tests/test_steward_core_b.py:898) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_done_confirmed_with_open_tbd_asks_owner` (py/tests/test_steward_core_b.py:913) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_tbd_only_project_not_started_owner_asked_once` (py/tests/test_steward_core_b.py:925) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_brain_stopped_project_not_restarted_by_cadence_until_cooldown` (py/tests/test_steward_core_b.py:935) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_idle_session_without_open_todo_not_nudged` (py/tests/test_steward_core_b.py:947) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AskStatusLineTests.test_status_lines_do_not_open_records` (py/tests/test_steward_core_b.py:960) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AskBaseTests.test_dated_session_name_collapses_to_base` (py/tests/test_steward_core_b.py:970) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DeferAnswerTests.test_is_defer_answer` (py/tests/test_steward_core_b.py:981) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DeferAnswerTests.test_digest_hides_deferred_until_expiry` (py/tests/test_steward_core_b.py:987) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StartDecisionEventTests.test_event_shape` (py/tests/test_steward_core_b.py:995) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ExpiredHandoverNoteTest.test_note_helper` (py/tests/test_steward_core_b.py:1007) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ExpiredHandoverNoteTest.test_expired_without_marker_carries_note` (py/tests/test_steward_core_b.py:1021) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ExpiredHandoverNoteTest.test_ready_marker_has_no_card_note` (py/tests/test_steward_core_b.py:1026) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliStuckLadderTest.test_shorten_helper` (py/tests/test_steward_core_b.py:1040) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliStuckLadderTest.test_ladder` (py/tests/test_steward_core_b.py:1047) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RemoteRespawnNoteTest.test_note_reaches_directive` (py/tests/test_steward_core_b.py:1074) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `RemoteRespawnNoteTest.test_no_note_keeps_empty_directive` (py/tests/test_steward_core_b.py:1079) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `ContextQuestionTest.test_classifier` (py/tests/test_steward_ctx.py:71) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_low_context_continues_without_handover` (py/tests/test_steward_ctx.py:76) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_high_context_hands_over` (py/tests/test_steward_ctx.py:86) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_unknown_context_or_disabled_leaves_question` (py/tests/test_steward_ctx.py:95) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_over_threshold_single_handover` (py/tests/test_steward_ctx.py:101) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_paused_over_threshold_sends_no_handover_on_any_tick` (py/tests/test_steward_ctx.py:119) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_done_project_also_gets_no_threshold_handover` (py/tests/test_steward_ctx.py:127) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_planned_project_still_hands_over_at_threshold` (py/tests/test_steward_ctx.py:131) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_context_question_on_paused_project_does_not_start_a_handover` (py/tests/test_steward_ctx.py:136) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_pure_decision` (py/tests/test_steward_ctx.py:158) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_subagent_active_defers_then_hands_over_when_quiet` (py/tests/test_steward_ctx.py:172) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_busy_and_unknown_defer` (py/tests/test_steward_ctx.py:195) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_history_fallback_defers_too` (py/tests/test_steward_ctx.py:206) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_force_by_ratio` (py/tests/test_steward_ctx.py:212) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_force_by_time` (py/tests/test_steward_ctx.py:222) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_defer_disabled_keeps_old_behaviour` (py/tests/test_steward_ctx.py:234) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_below_threshold_drops_deferral` (py/tests/test_steward_ctx.py:240) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_brain_same_rule` (py/tests/test_steward_ctx.py:246) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_no_second_action_while_deferred` (py/tests/test_steward_ctx.py:257) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_context_question_path_defers` (py/tests/test_steward_ctx.py:267) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_engine_logs_deferral` (py/tests/test_steward_ctx.py:282) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `HttpTest.test_idea_export_project_todo_hides_idea_and_keeps_record` (py/tests/test_steward_http.py:99) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_idea_export_all_tbd_and_idempotent` (py/tests/test_steward_http.py:113) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_idea_export_appends_under_existing_heading_and_validates` (py/tests/test_steward_http.py:123) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_running_names_resolve_digit_in_project_name` (py/tests/test_steward_http.py:143) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_project_ask_answer_idea_note` (py/tests/test_steward_http.py:156) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_ask_with_options_notifies_with_link_once` (py/tests/test_steward_http.py:177) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_question_page_auth_and_answer_flow` (py/tests/test_steward_http.py:201) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_register_creates_folder_goal_and_roster` (py/tests/test_steward_http.py:229) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_tick_applies_actions_with_mocked_views` (py/tests/test_steward_http.py:252) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_refresh_card_writes_summary_and_logs` (py/tests/test_steward_http.py:290) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_refresh_card_failure_keeps_old_card_or_writes_raw` (py/tests/test_steward_http.py:303) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_refresh_due_cards_rules` (py/tests/test_steward_http.py:326) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_tick_runs_card_step_unless_disabled` (py/tests/test_steward_http.py:349) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_respawn_marks_card_stale` (py/tests/test_steward_http.py:365) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_cards_in_context_projects_and_api` (py/tests/test_steward_http.py:378) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_observe_tick_records_would_and_touches_nothing` (py/tests/test_steward_http.py:421) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_observe_still_runs_questions_ideas_and_phase_changes` (py/tests/test_steward_http.py:443) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_act_mode_applies_and_logs_actions` (py/tests/test_steward_http.py:461) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_brain_calls_are_dry_in_observe_but_cli_calls_apply` (py/tests/test_steward_http.py:470) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_brain_cannot_touch_unregistered_session` (py/tests/test_steward_http.py:502) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_brain_may_touch_brain_and_registered_projects` (py/tests/test_steward_http.py:529) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_apply_gate_denies_engine_actions_on_unregistered_sessions` (py/tests/test_steward_http.py:545) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_daily_summary_runs_once_after_hour_and_notifies` (py/tests/test_steward_http.py:558) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_summary_api_and_cli` (py/tests/test_steward_http.py:584) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_handover_route_marks_pending` (py/tests/test_steward_http.py:609) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_gate_pure` (py/tests/test_steward_http.py:622) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_brain_bare_devam_rejected_owner_allowed` (py/tests/test_steward_http.py:634) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_brain_red_closes_and_opens_owner_question` (py/tests/test_steward_http.py:642) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_red_feedback_to_project_session_and_no_repeat_owner_question` (py/tests/test_steward_http.py:654) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_job_kinds_list_shapes` (py/tests/test_steward_http.py:678) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_brain_answer_after_submit_ok` (py/tests/test_steward_http.py:686) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SkipMemoryHttpTest.test_skip_records_signature_from_last_tour` (py/tests/test_steward_http.py:693) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SkipMemoryHttpTest.test_close_stale_answer_action_marks_delivered` (py/tests/test_steward_http.py:701) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ActionJournalTest.test_crash_between_state_save_and_apply_replays_once` (py/tests/test_steward_http.py:716) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ActionJournalTest.test_normal_tick_leaves_no_journal_and_no_duplicates` (py/tests/test_steward_http.py:734) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ActionJournalTest.test_replay_skips_duplicate_idea` (py/tests/test_steward_http.py:743) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_report_counts_and_window` (py/tests/test_steward_http.py:765) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_ask_due_only_known_kip_after_72h_once` (py/tests/test_steward_http.py:777) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_maybe_dry_ask_opens_one_question_and_not_again` (py/tests/test_steward_http.py:788) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_no_ask_when_kip_already_act` (py/tests/test_steward_http.py:798) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainWakeGateTest.test_brain_directive_capped_per_day_separately_from_due` (py/tests/test_steward_http.py:808) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainWakeGateTest.test_brain_gate_dry_logs_would_and_sends` (py/tests/test_steward_http.py:820) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeGateTest.test_first_send_never_gated_then_repeat_dry_logs_but_sends_act_skips` (py/tests/test_steward_http.py:836) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeGateTest.test_gate_is_skipped_when_the_directive_just_opened_the_session` (py/tests/test_steward_http.py:847) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeGateTest.test_other_text_other_reason_answer_off_and_window` (py/tests/test_steward_http.py:869) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `BigResumeTest.test_oversized_detection` (py/tests/test_steward_http.py:904) | `web_steward._oversized_resume`/`_ensure_running` politikası (T10, karar rs/stew); kullandığı `resolve_resume_id`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `BigResumeTest.test_small_unknown_other_cli_and_off_keep_resume` (py/tests/test_steward_http.py:908) | `web_steward._oversized_resume`/`_ensure_running` politikası (T10, karar rs/stew); kullandığı `resolve_resume_id`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `BigResumeTest.test_ensure_running_starts_fresh_for_big_context` (py/tests/test_steward_http.py:919) | `web_steward._oversized_resume`/`_ensure_running` politikası (T10, karar rs/stew); kullandığı `resolve_resume_id`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `WakeCapPanicTest.test_daily_cap_dry_and_act_and_reset_on_answer` (py/tests/test_steward_http.py:935) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeCapPanicTest.test_panic_flag_forces_observe_and_blocks_brain_directive` (py/tests/test_steward_http.py:952) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_blocked_waits_four_hours_routine_thirty_minutes` (py/tests/test_steward_http.py:982) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_owner_only_denial_escalates_routine_immediately` (py/tests/test_steward_http.py:989) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_owner_only_denial_blocks_brain_directive_until_answered` (py/tests/test_steward_http.py:997) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_owner_pending_block_pure` (py/tests/test_steward_http.py:1016) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_protocol_and_guide_derive_from_owner_topics` (py/tests/test_steward_http.py:1023) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `UcliSendTest.test_ucli_text_folded_not_truncated` (py/tests/test_steward_ucli_send.py:31) | `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation` (yalnız katlama; `_send` ve kutu denetimi T10) | TAŞINDI |
| `UcliSendTest.test_non_ucli_untouched_and_no_recheck` (py/tests/test_steward_ucli_send.py:41) | `tests/tui.rs::other_providers_keep_the_input` (yalnız dokunmama; kutu denetimi T10) | TAŞINDI |
| `UcliSendTest.test_claude_trust_dialog_blocks_send` (py/tests/test_steward_ucli_send.py:48) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::build_ownership_index_vectors ... | KAPSAM DIŞI |
| `UcliSendTest.test_text_left_in_box_sends_one_more_enter` (py/tests/test_steward_ucli_send.py:56) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_still_stuck_logs_error` (py/tests/test_steward_ucli_send.py:66) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `UcliSendTest.test_stuck_event_uses_caller_sid` (py/tests/test_steward_ucli_send.py:74) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_every_steward_send_call_passes_sid` (py/tests/test_steward_ucli_send.py:82) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_late_drawn_text_gets_enter` (py/tests/test_steward_ucli_send.py:92) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_empty_box_no_extra_enter` (py/tests/test_steward_ucli_send.py:103) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_prefixed_empty_prompt` (py/tests/test_steward_ucli_send.py:118) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_prefixed_with_text` (py/tests/test_steward_ucli_send.py:121) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_text_wrapped_over_two_lines` (py/tests/test_steward_ucli_send.py:124) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_waiting_for_response_is_empty` (py/tests/test_steward_ucli_send.py:128) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_turn_output_after_prompt_is_empty` (py/tests/test_steward_ucli_send.py:131) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_last_prompt_line_wins` (py/tests/test_steward_ucli_send.py:134) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_no_prompt` (py/tests/test_steward_ucli_send.py:137) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ClaudeSidForStoppedSessionTests.test_own_conversation_wins_over_a_newer_sibling_stub` (py/tests/test_stopped_session_chat.py:80) | `parity.rs::parity_resume` `devam-claude-kardes` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_each_sibling_resolves_to_its_own_file` (py/tests/test_stopped_session_chat.py:86) | `parity.rs::parity_resume` `devam-claude-kardes` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_same_title_prefers_the_real_conversation_over_a_newer_stub` (py/tests/test_stopped_session_chat.py:95) | `parity.rs::parity_resume` `devam-claude-kardes` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_same_title_picks_the_newest_real_conversation_even_when_it_is_the_smaller_one` (py/tests/test_stopped_session_chat.py:101) | `parity.rs::parity_resume` `devam-claude-yeni-gercek` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_all_stubs_returns_the_newest_one` (py/tests/test_stopped_session_chat.py:107) | `parity.rs::parity_resume` `devam-claude-kardes` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_a_large_file_counts_as_real_without_being_scanned` (py/tests/test_stopped_session_chat.py:112) | `tests/resume.rs::a_large_file_counts_as_real_without_being_scanned`; `parity.rs::parity_resume` `devam-claude-stub-` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_no_title_match_returns_none` (py/tests/test_stopped_session_chat.py:119) | `parity.rs::parity_resume` `devam-claude-kardes` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_title_is_an_exact_match_not_a_prefix` (py/tests/test_stopped_session_chat.py:123) | `parity.rs::parity_resume` `devam-claude-yeni-gercek` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_untitled_files_never_match` (py/tests/test_stopped_session_chat.py:127) | `parity.rs::parity_resume` `devam-claude-kardes` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_missing_project_dir_and_empty_name_return_none` (py/tests/test_stopped_session_chat.py:131) | `parity.rs::parity_resume` `devam-claude-dizin-yok` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_file_recording_a_different_cwd_is_ignored` (py/tests/test_stopped_session_chat.py:136) | `parity.rs::parity_resume` `devam-claude-cwd` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_finds_a_file_older_than_the_resume_scan_limit` (py/tests/test_stopped_session_chat.py:141) | `parity.rs::parity_resume` `devam-claude-sinir-` | TAŞINDI |
| `ClaudeSidForStoppedSessionTests.test_unchanged_files_are_not_reread_but_changed_ones_are` (py/tests/test_stopped_session_chat.py:149) | `tests/resume.rs::unchanged_files_are_not_reread_but_changed_ones_are` | TAŞINDI |
| `TermChatWiringTests.test_stopped_session_shows_its_own_full_history_not_the_newest_stub` (py/tests/test_stopped_session_chat.py:177) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `TermChatWiringTests.test_stopped_session_last_exchange_is_its_own` (py/tests/test_stopped_session_chat.py:182) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `TermChatWiringTests.test_incremental_since_still_works_on_the_resolved_conversation` (py/tests/test_stopped_session_chat.py:186) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `TermChatWiringTests.test_unmatched_stopped_session_keeps_the_old_newest_in_cwd_behavior` (py/tests/test_stopped_session_chat.py:192) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `TermChatWiringTests.test_live_session_never_consults_the_name_lookup` (py/tests/test_stopped_session_chat.py:200) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `TermChatWiringTests.test_live_session_without_sid_is_left_alone_too` (py/tests/test_stopped_session_chat.py:207) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `TermChatWiringTests.test_unsupported_cli_still_reports_supported_false` (py/tests/test_stopped_session_chat.py:214) | `web._term_chat` bağlaması (T1): `pid=0` için `sid_for_stopped_session` (G1), `since` sayfalaması, `supported` alanı. Altındaki okuyucular `parity_chat` `chat-claude-`, `shell-` | KAPSAM DIŞI |
| `OtherProvidersTests.test_default_providers_do_not_guess` (py/tests/test_stopped_session_chat.py:220) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `OtherProvidersTests.test_agy_uses_the_learned_name_to_sid_map_when_the_db_exists` (py/tests/test_stopped_session_chat.py:224) | `parity.rs::parity_resume` `devam-agy-ogrenilen-` (metin olmayan değer: `devam-sapma-agy-kimlik-sayi` resume tarafı) | TAŞINDI |
| `OtherProvidersTests.test_ucli_sid_is_the_session_name` (py/tests/test_stopped_session_chat.py:237) | `parity.rs::parity_resume` `devam-diger` | TAŞINDI |
| `UcliChatTests.test_schema_header_row_is_skipped` (py/tests/test_stopped_session_chat.py:258) | `parity.rs::parity_chat` `ucli-baslik` | TAŞINDI |
| `UcliChatTests.test_header_only_file_means_no_messages_yet_not_unsupported` (py/tests/test_stopped_session_chat.py:263) | `parity.rs::parity_chat` `ucli-yalniz-baslik` | TAŞINDI |
| `UcliChatTests.test_old_files_without_a_header_still_parse` (py/tests/test_stopped_session_chat.py:267) | `parity.rs::parity_chat` `ucli-basliksiz` | TAŞINDI |
| `UcliChatTests.test_corrupt_files_are_still_reported_as_unreadable` (py/tests/test_stopped_session_chat.py:271) | `parity.rs::parity_chat` `ucli-bozuk-` | TAŞINDI |
| `UcliChatTests.test_missing_file_is_an_empty_history` (py/tests/test_stopped_session_chat.py:277) | `parity.rs::parity_chat` `ucli-dosya-yok` | TAŞINDI |
| `UcliChatTests.test_stopped_ucli_instance_chat_is_served_through_term_chat` (py/tests/test_stopped_session_chat.py:280) | `web._term_chat` bağlaması (T1); okuyucu `parity_chat` `chat-ucli-` | KAPSAM DIŞI |
| `RecoverStuckTest.test_uses_parent_aware_kill` (py/tests/test_stuck_kills_parent.py:13) | T4: `stuck.py` kurtarma akışı | KAPSAM DIŞI |
| `RecoverStuckTest.test_unknown_permission_uses_provider_default` (py/tests/test_stuck_kills_parent.py:28) | T4: `stuck.py` kurtarma akışı | KAPSAM DIŞI |
| `RecoverStuckTest.test_dry_run_kills_nothing` (py/tests/test_stuck_kills_parent.py:40) | T4: `stuck.py` kurtarma akışı | KAPSAM DIŞI |
| `RecoverStuckTest.test_recovery_uses_live_model_and_effort_not_spawn_argv` (py/tests/test_stuck_kills_parent.py:46) | T4: `stuck.py` kurtarma akışı; `live_or_spawn_*` taşındı (G3) | KAPSAM DIŞI |
| `TokenTests.test_concurrent_issue_keeps_file_and_digest_consistent` (py/tests/test_ucli_agents.py:29) | `tests/real_fs.rs::concurrent_issue_keeps_file_and_digest_consistent` | TAŞINDI |
| `TokenTests.test_issue_writes_0600_file_and_only_hash_in_registry` (py/tests/test_ucli_agents.py:48) | `tests/real_fs.rs::agent_token_is_0600_and_only_its_hash_is_registered` | TAŞINDI |
| `TokenTests.test_reissue_invalidates_old_token_and_revoke_clears` (py/tests/test_ucli_agents.py:56) | `tests/real_fs.rs::agent_reissue_invalidates_and_revoke_clears` | TAŞINDI |
| `TokenTests.test_children_get_no_token_and_garbage_rejected` (py/tests/test_ucli_agents.py:65) | `tests/real_fs.rs::agent_children_get_no_token_and_garbage_is_rejected` | TAŞINDI |
| `TokenTests.test_revoke_unsafe_name_does_not_touch_files` (py/tests/test_ucli_agents.py:71) | `tests/real_fs.rs::agent_children_get_no_token_and_garbage_is_rejected` | TAŞINDI |
| `ReserveTests.test_limit_two_live_and_names_sequential` (py/tests/test_ucli_agents.py:80) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ReserveTests.test_taken_names_skipped_and_depth_one` (py/tests/test_ucli_agents.py:91) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ReserveTests.test_fold_text` (py/tests/test_ucli_agents.py:97) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `SettingsTests.test_defaults` (py/tests/test_ucli_agents.py:108) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `SettingsTests.test_off_and_cost` (py/tests/test_ucli_agents.py:113) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ProviderSetupTests.test_no_port_or_child_or_off_gives_nothing` (py/tests/test_ucli_agents.py:136) | `parity.rs::parity_ucli` `ajan-port-yok` `ajan-cocuk` `ajan-kapali` | TAŞINDI |
| `ProviderSetupTests.test_unsupported_binary_gives_nothing` (py/tests/test_ucli_agents.py:145) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `ProviderSetupTests.test_enabled_returns_flag_and_env_without_token_value` (py/tests/test_ucli_agents.py:151) | `parity.rs::parity_ucli` `ajan-acik` `ajan-anahtarli` | TAŞINDI |
| `ProviderSetupTests.test_build_inner_command_keeps_token_out_of_argv` (py/tests/test_ucli_agents.py:161) | `parity.rs::parity_ucli` `ajan-acik` `ajan-anahtarli` | TAŞINDI |
| `ApprovalExecTest.test_suspended_registered` (py/tests/test_ucli_approval_exec.py:34) | `parity.rs::parity_oneshot` `onay-askida` | TAŞINDI |
| `ApprovalExecTest.test_75_without_suspended_line_is_error` (py/tests/test_ucli_approval_exec.py:45) | `parity.rs::parity_oneshot` `onay-satirsiz` | TAŞINDI |
| `ApprovalExecTest.test_bad_run_key` (py/tests/test_ucli_approval_exec.py:49) | `parity.rs::parity_oneshot` `onay-ad` | TAŞINDI |
| `ApprovalExecTest.test_opts_validation` (py/tests/test_ucli_approval_exec.py:53) | `parity.rs::parity_ucli` `approval` `askdir` | TAŞINDI |
| `ResumeTest.test_resume_done_and_argv_from_record` (py/tests/test_ucli_approval_exec.py:71) | T7: onay sürdürme/listeleme (`ucli_resume_approval`, `list_runs`, `recover_resuming`) | KAPSAM DIŞI |
| `ResumeTest.test_resume_chain_and_double_resume` (py/tests/test_ucli_approval_exec.py:83) | T7: onay sürdürme/listeleme (`ucli_resume_approval`, `list_runs`, `recover_resuming`) | KAPSAM DIŞI |
| `ResumeTest.test_resume_error_recorded` (py/tests/test_ucli_approval_exec.py:93) | T7: onay sürdürme/listeleme (`ucli_resume_approval`, `list_runs`, `recover_resuming`) | KAPSAM DIŞI |
| `ResumeTest.test_list_runs_owner_filter_hides_argv` (py/tests/test_ucli_approval_exec.py:100) | T7: onay sürdürme/listeleme (`ucli_resume_approval`, `list_runs`, `recover_resuming`) | KAPSAM DIŞI |
| `ResumeTest.test_recover_resuming` (py/tests/test_ucli_approval_exec.py:106) | T7: onay sürdürme/listeleme (`ucli_resume_approval`, `list_runs`, `recover_resuming`) | KAPSAM DIŞI |
| `ResumeTest.test_authz_resource_and_action` (py/tests/test_ucli_approval_exec.py:114) | T7 + `cops-auth::authz` (eylem tablosu ve `resources_from`; bu crate'te yetki yok) | KAPSAM DIŞI |
| `AskDirTest.test_opts_default_off_and_ambiguous` (py/tests/test_ucli_ask_dir.py:27) | `parity.rs::parity_ucli` `approval-askdir` `askdir` | TAŞINDI |
| `AskDirTest.test_argv_has_private_dir_outside_workspace` (py/tests/test_ucli_ask_dir.py:33) | `parity.rs::parity_ucli` `askdir-var` | TAŞINDI |
| `AskDirTest.test_unsupported_binary_or_no_name_is_error` (py/tests/test_ucli_ask_dir.py:40) | `parity.rs::parity_ucli` `eksik-checks` `askdir-adsiz2` | TAŞINDI |
| `AskDirTest.test_pending_and_answer_roundtrip_and_stale_id` (py/tests/test_ucli_ask_dir.py:46) | T7: `/api/ucli/ask` soru/cevap okuyucusu | KAPSAM DIŞI |
| `AskDirTest.test_bad_names_rejected` (py/tests/test_ucli_ask_dir.py:58) | `parity.rs::parity_ucli` `askdir-gecersiz-ad` `askdir-uzun` | TAŞINDI |
| `AskDirTest.test_broken_question_file_is_none` (py/tests/test_ucli_ask_dir.py:63) | T7: `/api/ucli/ask` soru/cevap okuyucusu | KAPSAM DIŞI |
| `ValidateMaxCostTests.test_valid_values` (py/tests/test_ucli_brain_mcp.py:53) | `parity.rs::parity_ucli` `cost` | TAŞINDI |
| `ValidateMaxCostTests.test_zero_or_empty_drops_the_key` (py/tests/test_ucli_brain_mcp.py:59) | `parity.rs::parity_ucli` `cost` | TAŞINDI |
| `ValidateMaxCostTests.test_invalid_values_rejected` (py/tests/test_ucli_brain_mcp.py:63) | `parity.rs::parity_ucli` `cost` | TAŞINDI |
| `MaxCostArgsTests.test_priced_model_gets_the_flag_once` (py/tests/test_ucli_brain_mcp.py:89) | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` | TAŞINDI |
| `MaxCostArgsTests.test_unpriced_model_is_skipped_and_logged` (py/tests/test_ucli_brain_mcp.py:95) | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` | TAŞINDI |
| `MaxCostArgsTests.test_binary_without_flag_is_skipped` (py/tests/test_ucli_brain_mcp.py:100) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `McpRegisterTests.test_server_name_follows_ucli_rule` (py/tests/test_ucli_brain_mcp.py:113) | `parity.rs::parity_misc` `ucli-misc` ; `parity.rs::parity_ucli` `ucli-mcp-ad` | TAŞINDI |
| `McpRegisterTests.test_add_argv_shape` (py/tests/test_ucli_brain_mcp.py:118) | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `McpRegisterTests.test_launch_args_register_then_with_mcp` (py/tests/test_ucli_brain_mcp.py:124) | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `McpRegisterTests.test_failed_add_means_no_with_mcp` (py/tests/test_ucli_brain_mcp.py:144) | `parity.rs::parity_ucli` `ucli-mcp-`; `Probe::register_mcp` sahte (G8) | TAŞINDI |
| `McpRegisterTests.test_nothing_runs_without_tools_workspace_or_flag` (py/tests/test_ucli_brain_mcp.py:152) | `parity.rs::parity_ucli` `ucli-mcp-aracsiz` `ucli-mcp-` | TAŞINDI |
| `McpRegisterTests.test_symlinked_state_dir_is_refused` (py/tests/test_ucli_brain_mcp.py:165) | `parity.rs::parity_ucli` `ucli-symlink` | TAŞINDI |
| `McpRegisterTests.test_steward_spec_allowlists_exactly_the_steward_tools` (py/tests/test_ucli_brain_mcp.py:176) | T10: `mcp_steward` araç listesi | KAPSAM DIŞI |
| `BuildWithMcpTests.test_only_with_mcp_is_taken_from_extra_args` (py/tests/test_ucli_brain_mcp.py:204) | `parity.rs::parity_ucli` `with-mcp` `with-mcp-yok` | TAŞINDI |
| `BuildWithMcpTests.test_claude_service_with_cost_cap_and_mcp` (py/tests/test_ucli_brain_mcp.py:210) | `parity.rs::parity_ucli` `hizmet-claude`; günlük tavan sahte (G8) | TAŞINDI |
| `SpawnCwdWiringTests.test_cwd_only_for_providers_that_ask` (py/tests/test_ucli_brain_mcp.py:245) | `parity.rs::parity_spawn` `-mcp` ; `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `SpawnCwdWiringTests.test_dry_run_preview_shows_env_and_command_not_priority_prefix` (py/tests/test_ucli_brain_mcp.py:265) | `parity.rs::parity_spawn` `-dry` | TAŞINDI |
| `SpawnCwdWiringTests.test_dry_run_preview_masks_secret_env_values` (py/tests/test_ucli_brain_mcp.py:271) | `parity.rs::parity_spawn` `preview` | TAŞINDI |
| `SpawnCwdWiringTests.test_dry_run_preview_caps_very_long_command` (py/tests/test_ucli_brain_mcp.py:277) | `parity.rs::parity_spawn` `preview-uzun` | TAŞINDI |
| `BrainUcliTests.test_default_claude_brain_passes_no_cli_opts` (py/tests/test_ucli_brain_mcp.py:284) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_ucli_brain_uses_claude_service_and_cost_cap` (py/tests/test_ucli_brain_mcp.py:291) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_settings_override_service_model_and_cap` (py/tests/test_ucli_brain_mcp.py:303) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_defaults` (py/tests/test_ucli_brain_mcp.py:312) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_unknown_service_refuses_without_spawn` (py/tests/test_ucli_brain_mcp.py:319) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_spawn_refusal_is_reported_not_raised` (py/tests/test_ucli_brain_mcp.py:326) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_claude_brain_value_error_still_raises` (py/tests/test_ucli_brain_mcp.py:332) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BroadGlobTests.test_broad_rejected_without_accept` (py/tests/test_ucli_broad_glob_and_instr_check.py:19) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_broad_accepted_with_accept` (py/tests/test_ucli_broad_glob_and_instr_check.py:26) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_narrow_glob_has_no_accept_flag` (py/tests/test_ucli_broad_glob_and_instr_check.py:33) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_always_rejected_even_when_accepted` (py/tests/test_ucli_broad_glob_and_instr_check.py:38) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_forbidden_cmds_never_open` (py/tests/test_ucli_broad_glob_and_instr_check.py:42) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_grant_logged_in_apply` (py/tests/test_ucli_broad_glob_and_instr_check.py:46) | `parity.rs::parity_ucli` `glob-genis-kabul` | TAŞINDI |
| `InstructionsCheckTests.test_sizes` (py/tests/test_ucli_broad_glob_and_instr_check.py:62) | `parity.rs::parity_panel` `instr-boyut` | TAŞINDI |
| `InstructionsCheckTests.test_exact_limit_not_over` (py/tests/test_ucli_broad_glob_and_instr_check.py:71) | `parity.rs::parity_panel` `instr-sinir` `instr-sinir-ustu` | TAŞINDI |
| `InstructionsCheckTests.test_no_files_and_bad_cwd` (py/tests/test_ucli_broad_glob_and_instr_check.py:76) | `parity.rs::parity_panel` `instr-dosyasiz` `instr-bos` `instr-goreli` `instr-yok` `instr-dosya-cwd` `instr-nul` | TAŞINDI |
| `InstructionsCheckTests.test_symlink_escape_ignored` (py/tests/test_ucli_broad_glob_and_instr_check.py:82) | `parity.rs::parity_panel` `instr-symlink-kacis` (ve `instr-symlink-ici`, `instr-symlink-kirik`) | TAŞINDI |
| `InstructionsCheckTests.test_no_content_returned` (py/tests/test_ucli_broad_glob_and_instr_check.py:88) | `parity.rs::parity_panel` `instr-icerik` (dönüş yalnız ad/boyut/sınır) | TAŞINDI |
| `CapabilityFlagsTest.test_default_off` (py/tests/test_ucli_capability_flags.py:27) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `CapabilityFlagsTest.test_image_scholar_independent_of_exec` (py/tests/test_ucli_capability_flags.py:36) | `parity.rs::parity_ucli` `yetenek` | TAŞINDI |
| `CapabilityFlagsTest.test_false_values_dropped` (py/tests/test_ucli_capability_flags.py:43) | `parity.rs::parity_ucli` `opts-yetenek-hayir` `opts-yetenek-hayir-2` | TAŞINDI |
| `CapabilityFlagsTest.test_invalid_value_is_error` (py/tests/test_ucli_capability_flags.py:48) | `parity.rs::parity_ucli` `bayrak-gecersiz` | TAŞINDI |
| `CapabilityFlagsTest.test_net_and_unbounded_exec_own_not_offered` (py/tests/test_ucli_capability_flags.py:54) | `parity.rs::parity_misc` `val` | TAŞINDI |
| `CapabilityFlagsTest.test_ask_edit_needs_write` (py/tests/test_ucli_capability_flags.py:62) | `parity.rs::parity_ucli` `ask-edit-yazmasiz` `ask-edit` | TAŞINDI |
| `CapabilityFlagsTest.test_exec_argv` (py/tests/test_ucli_capability_flags.py:69) | `parity.rs::parity_ucli` `toolchain-uygula` | TAŞINDI |
| `CapabilityFlagsTest.test_unsupported_binary_refuses` (py/tests/test_ucli_capability_flags.py:76) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `CapabilityFlagsTest.test_unsupported_but_off_no_error` (py/tests/test_ucli_capability_flags.py:84) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `AskEditWithoutExecTest.test_ask_edit_added_only_with_allow_edit` (py/tests/test_ucli_capability_flags.py:96) | `parity.rs::parity_ucli` `opts-ask-edit-exec-yok` | TAŞINDI |
| `CheckpointFlagTest.test_default_off` (py/tests/test_ucli_checkpoint_flag.py:21) | `parity.rs::parity_ucli` `opts-bos` (doğrulama + uygulama: `--checkpoint` yok), `opts-checkpoint-evet` | TAŞINDI |
| `CheckpointFlagTest.test_false_values_dropped` (py/tests/test_ucli_checkpoint_flag.py:27) | `parity.rs::parity_ucli` `opts-checkpoint-hayir-` (false, "false", "0", "", null) | TAŞINDI |
| `CheckpointFlagTest.test_true_accepted` (py/tests/test_ucli_checkpoint_flag.py:33) | `parity.rs::parity_ucli` `bayraklar` `bayrak-gecersiz` | TAŞINDI |
| `CheckpointFlagTest.test_ambiguous_is_error` (py/tests/test_ucli_checkpoint_flag.py:38) | `parity.rs::parity_ucli` `bayraklar` `bayrak-gecersiz` | TAŞINDI |
| `CheckpointFlagTest.test_argv_added_once` (py/tests/test_ucli_checkpoint_flag.py:42) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `CheckpointFlagTest.test_unsupported_binary_skipped_not_rejected` (py/tests/test_ucli_checkpoint_flag.py:46) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `Validate.test_off_by_default_and_dropped` (py/tests/test_ucli_checks_opts.py:19) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Validate.test_restricted_ok_max_defaults_to_mode` (py/tests/test_ucli_checks_opts.py:24) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Validate.test_errors` (py/tests/test_ucli_checks_opts.py:29) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Validate.test_full_needs_accept_risk` (py/tests/test_ucli_checks_opts.py:33) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Registry.test_missing_loose_mode_and_shape` (py/tests/test_ucli_checks_opts.py:55) | `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `Registry.test_symlink_rejected` (py/tests/test_ucli_checks_opts.py:66) | `tests/real_fs.rs::checks_registry_rejects_missing_loose_mode_links_and_bad_shape` | TAŞINDI |
| `Apply.test_flags_added` (py/tests/test_ucli_checks_opts.py:90) | `parity.rs::parity_ucli` `checks-uygula` | TAŞINDI |
| `Apply.test_full_adds_accept_risk` (py/tests/test_ucli_checks_opts.py:97) | `parity.rs::parity_ucli` `checks-uygula` | TAŞINDI |
| `Apply.test_full_refused_when_binary_only_knows_restricted` (py/tests/test_ucli_checks_opts.py:101) | `parity.rs::parity_ucli` `checks-deger-tanimsiz` | TAŞINDI |
| `Apply.test_unsupported_binary_refused` (py/tests/test_ucli_checks_opts.py:111) | `parity.rs::parity_ucli` `eksik-checks` | TAŞINDI |
| `Apply.test_needs_state_dir_and_registry` (py/tests/test_ucli_checks_opts.py:115) | `parity.rs::parity_ucli` `checks-statedir-yok` `checks-kayit-hata` | TAŞINDI |
| `RefusalTests.test_cap_refusal_has_code_and_amounts` (py/tests/test_ucli_cost_cap_refusal.py:13) | `real_ledger.rs::a_cap_refusal_carries_code_and_amounts_and_other_errors_do_not` | TAŞINDI |
| `RefusalTests.test_plain_value_error_has_no_code` (py/tests/test_ucli_cost_cap_refusal.py:18) | `real_ledger.rs::a_cap_refusal_carries_code_and_amounts_and_other_errors_do_not` | TAŞINDI |
| `ProviderRaisesTests.test_claude_service_flags_raises_over_cap` (py/tests/test_ucli_cost_cap_refusal.py:25) | `real_ledger.rs::a_claude_service_build_is_refused_over_the_cap` | TAŞINDI |
| `DefaultPermissionMode.test_ucli_panel_default_is_allow_edit_and_listed` (py/tests/test_ucli_default_permission_mode.py:12) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultPermissionMode.test_ucli_server_internal_default_stays_read_only` (py/tests/test_ucli_default_permission_mode.py:17) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultPermissionMode.test_other_providers_keep_auto` (py/tests/test_ucli_default_permission_mode.py:21) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `ReasoningModeTests.test_unset_empty_and_unknown_values_mean_auto` (py/tests/test_ucli_effort.py:105) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_off_words_switch_it_off` (py/tests/test_ucli_effort.py:111) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_a_named_level_forces_that_level_case_insensitively` (py/tests/test_ucli_effort.py:116) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_a_non_dict_ucli_limits_is_tolerated` (py/tests/test_ucli_effort.py:121) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_it_does_not_leak_into_the_numeric_overrides` (py/tests/test_ucli_effort.py:125) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `CatalogTests.test_only_chat_models_are_listed_and_their_capabilities_kept` (py/tests/test_ucli_effort.py:147) | `parity.rs::parity_misc` `live` | TAŞINDI |
| `CatalogTests.test_a_failed_or_empty_fetch_keeps_the_previous_map` (py/tests/test_ucli_effort.py:155) | `parity.rs::parity_model_sources` `src-ucli-akis`; `tests/model_sources.rs::repeated_errors_never_replace_the_last_good_list` | TAŞINDI |
| `CatalogTests.test_without_a_key_nothing_is_fetched` (py/tests/test_ucli_effort.py:164) | `parity.rs::parity_model_sources` `src-ucli-anahtarsiz`; `tests/model_sources.rs::no_request_without_a_key` | TAŞINDI |
| `CatalogTests.test_model_choices_and_the_effort_gate_share_one_fetch` (py/tests/test_ucli_effort.py:170) | `tests/model_sources.rs::model_list_and_effort_gate_share_one_fetch` | TAŞINDI |
| `ReasoningEffortForTests.test_a_model_that_declares_support_gets_the_level` (py/tests/test_ucli_effort.py:186) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_gemma_which_rejects_the_field_gets_nothing` (py/tests/test_ucli_effort.py:190) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_an_unknown_model_or_an_empty_catalog_gets_nothing` (py/tests/test_ucli_effort.py:195) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_a_malformed_capabilities_entry_is_tolerated` (py/tests/test_ucli_effort.py:200) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_an_allowed_values_list_restricts_the_level_unless_aliased` (py/tests/test_ucli_effort.py:208) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `EffortArgsTests.test_a_capable_model_and_a_new_binary_get_the_session_preset` (py/tests/test_ucli_effort.py:219) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `EffortArgsTests.test_off_is_silent_and_sends_nothing` (py/tests/test_ucli_effort.py:225) | `parity.rs::parity_ucli` `ayar-reasoning-` | TAŞINDI |
| `EffortArgsTests.test_a_named_level_overrides_the_preset_but_not_the_model_gate` (py/tests/test_ucli_effort.py:231) | `parity.rs::parity_ucli` `ayar-reasoning-` | TAŞINDI |
| `EffortArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` (py/tests/test_ucli_effort.py:237) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `EffortArgsTests.test_a_model_that_rejects_the_field_is_skipped_and_logged` (py/tests/test_ucli_effort.py:243) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `EffortArgsTests.test_no_model_and_a_missing_binary_give_nothing_instead_of_raising` (py/tests/test_ucli_effort.py:249) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_the_preset_name_rides_along_as_the_last_flag` (py/tests/test_ucli_effort.py:280) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_an_unknown_or_empty_effort_falls_back_to_medium_for_the_flag_too` (py/tests/test_ucli_effort.py:284) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_gemma_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:290) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:294) | `parity.rs::parity_ucli` `eski-ikili` | TAŞINDI |
| `BuildInnerCommandTests.test_off_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:298) | `parity.rs::parity_ucli` `ayar-reasoning-` | TAŞINDI |
| `BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` (py/tests/test_ucli_effort.py:302) | `parity.rs::parity_ucli` `anahtar-yaz` | TAŞINDI |
| `BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` (py/tests/test_ucli_effort.py:308) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` (py/tests/test_ucli_effort.py:318) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` (py/tests/test_ucli_effort.py:325) | rs/prov: gereksiz: teslim edilen gerçek ucli ikilisini sınar | KAPSAM DIŞI |
| `UcliEndpointTest.test_default_is_evren` (py/tests/test_ucli_endpoint.py:23) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `UcliEndpointTest.test_custom_valid_endpoint_wins_and_trailing_slash_dropped` (py/tests/test_ucli_endpoint.py:27) | `parity.rs::parity_ucli` `ayar-endpoint` `endpoint-gecersiz` ; `parity.rs::parity_settings_pyfmt` `endpoint` | TAŞINDI |
| `UcliEndpointTest.test_invalid_endpoint_falls_back_and_empty_clears` (py/tests/test_ucli_endpoint.py:31) | `parity.rs::parity_ucli` `ayar-endpoint` `endpoint-gecersiz` ; `parity.rs::parity_settings_pyfmt` `endpoint` | TAŞINDI |
| `UcliEndpointTest.test_model_list_fetch_uses_configured_endpoint` (py/tests/test_ucli_endpoint.py:40) | `parity.rs::parity_model_sources` `src-ucli-uc-nokta` | TAŞINDI |
| `EvrenNoDefaultCapTest.test_evren_has_no_default_cap` (py/tests/test_ucli_evren_no_default_cap.py:18) | `parity.rs::parity_ucli` `hizmet-evren` | TAŞINDI |
| `EvrenNoDefaultCapTest.test_explicit_cap_on_evren_still_passes` (py/tests/test_ucli_evren_no_default_cap.py:22) | `parity.rs::parity_ucli` `ham-service-evren` | TAŞINDI |
| `ExecToolchainTests.test_only_rust_is_accepted` (py/tests/test_ucli_exec_toolchain.py:17) | `parity.rs::parity_ucli` `toolchain-baska` `toolchain` | TAŞINDI |
| `ExecToolchainTests.test_missing_toolchain_is_an_error_not_a_silent_skip` (py/tests/test_ucli_exec_toolchain.py:22) | `parity.rs::parity_ucli` `toolchain-yok` | TAŞINDI |
| `ExecToolchainTests.test_flags_use_real_binaries_and_only_allowed_env` (py/tests/test_ucli_exec_toolchain.py:28) | `tests/real_fs.rs::exec_flags_use_the_discovered_binaries_and_only_allowed_env` | TAŞINDI |
| `ExecToolchainTests.test_no_toolchain_means_old_flags_unchanged` (py/tests/test_ucli_exec_toolchain.py:46) | `parity.rs::parity_misc` `exec` | TAŞINDI |
| `ExecToolchainTests.test_path_in_exec_cmds_is_still_rejected` (py/tests/test_ucli_exec_toolchain.py:53) | `parity.rs::parity_ucli` `cmds-yol` | TAŞINDI |
| `FailedTurnsTests.test_no_directory_or_no_record_is_none_not_zero` (py/tests/test_ucli_failed_turns.py:28) | `parity.rs::parity_live` `hata-` | TAŞINDI |
| `FailedTurnsTests.test_counts_this_session_only_and_reports_the_newest_error` (py/tests/test_ucli_failed_turns.py:33) | `parity.rs::parity_live` `hata-` | TAŞINDI |
| `FailedTurnsTests.test_a_broken_or_errorless_record_still_counts` (py/tests/test_ucli_failed_turns.py:42) | `parity.rs::parity_live` `hata-` | TAŞINDI |
| `FailedTurnsTests.test_dict_error_uses_its_message` (py/tests/test_ucli_failed_turns.py:46) | `parity.rs::parity_live` `hata-` | TAŞINDI |
| `FailedTurnsTests.test_no_sid_is_none` (py/tests/test_ucli_failed_turns.py:50) | `parity.rs::parity_live` `durum-yok-sid` `durum-bos-sid` | TAŞINDI |
| `FailedTurnsTests.test_web_wrapper_never_raises` (py/tests/test_ucli_failed_turns.py:53) | T1: panel `web._live_failed_turns` sarmalayıcısı | KAPSAM DIŞI |
| `FailedTurnsTests.test_other_cli_has_no_failed_turns` (py/tests/test_ucli_failed_turns.py:58) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `ForbiddenCmds.test_interpreters_rejected_by_name` (py/tests/test_ucli_forbidden_cmds.py:10) | `parity.rs::parity_misc` `ucli-misc` ; `parity.rs::parity_ucli` `cmds-kabuk` `cmds-python3` | TAŞINDI |
| `ForbiddenCmds.test_is_forbidden_cmd` (py/tests/test_ucli_forbidden_cmds.py:16) | `parity.rs::parity_misc` `ucli-misc` ; `parity.rs::parity_ucli` `cmds-kabuk` `cmds-python3` | TAŞINDI |
| `ArchiveTest.test_moves_history_and_status_keeps_others` (py/tests/test_ucli_fresh_handover.py:31) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `ArchiveTest.test_second_archive_does_not_overwrite` (py/tests/test_ucli_fresh_handover.py:43) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `ArchiveTest.test_nothing_to_move_and_bad_names` (py/tests/test_ucli_fresh_handover.py:50) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `StartFreshTest.test_fresh_ucli_archives` (py/tests/test_ucli_fresh_handover.py:72) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `StartFreshTest.test_not_fresh_or_not_ucli_or_running_does_not` (py/tests/test_ucli_fresh_handover.py:75) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `HandoverGateTest.test_ucli_handover_sends_message` (py/tests/test_ucli_fresh_handover.py:82) | `tests/tui.rs::ucli_handover_message_is_one_line_and_the_dialog_scan_is_a_noop` (web kapısı `_handover` T4) | TAŞINDI |
| `ValidateTests.test_default_off` (py/tests/test_ucli_git_flags.py:21) | `parity.rs::parity_ucli` `git` | TAŞINDI |
| `ValidateTests.test_on_independent_of_each_other_and_exec` (py/tests/test_ucli_git_flags.py:26) | `parity.rs::parity_ucli` `git` | TAŞINDI |
| `ValidateTests.test_garbage_is_error` (py/tests/test_ucli_git_flags.py:32) | `parity.rs::parity_ucli` `git` | TAŞINDI |
| `ArgvTests.test_no_flags_by_default` (py/tests/test_ucli_git_flags.py:39) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `ArgvTests.test_only_requested_flag` (py/tests/test_ucli_git_flags.py:44) | `parity.rs::parity_ucli` `eksik` `git` | TAŞINDI |
| `ArgvTests.test_both_no_duplicates` (py/tests/test_ucli_git_flags.py:52) | `parity.rs::parity_ucli` `eksik` `git` | TAŞINDI |
| `ArgvTests.test_unsupported_binary_refuses` (py/tests/test_ucli_git_flags.py:57) | `parity.rs::parity_ucli` `eksik` `git` | TAŞINDI |
| `ArgvTests.test_unsupported_irrelevant_when_off` (py/tests/test_ucli_git_flags.py:61) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `InstructionsFlagsTest.test_default_off` (py/tests/test_ucli_instructions_flags.py:21) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `InstructionsFlagsTest.test_valid` (py/tests/test_ucli_instructions_flags.py:30) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_zero_and_empty_dropped` (py/tests/test_ucli_instructions_flags.py:36) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_invalid` (py/tests/test_ucli_instructions_flags.py:42) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_argv` (py/tests/test_ucli_instructions_flags.py:49) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_unsupported_binary_skips` (py/tests/test_ucli_instructions_flags.py:54) | `parity.rs::parity_ucli` `opts-talimat-desteksiz` (bayrakları tanımayan `--help`), `opts-talimat` | TAŞINDI |
| `InteractiveArgsTest.test_supported_adds_flag` (py/tests/test_ucli_interactive_flag.py:12) | `parity.rs::parity_ucli` `eksik` `temel-` | TAŞINDI |
| `InteractiveArgsTest.test_unsupported_skips_and_logs` (py/tests/test_ucli_interactive_flag.py:16) | `parity.rs::parity_ucli` `eksik` `temel-` | TAŞINDI |
| `UcliKeyPathTest.test_default_and_service` (py/tests/test_ucli_key_path.py:14) | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `UcliKeyPathTest.test_callers_share_helper` (py/tests/test_ucli_key_path.py:19) | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `LastExchangePairingTest.test_pending_user_turn_has_empty_assistant` (py/tests/test_ucli_last_exchange_pairing.py:17) | `parity.rs::parity_chat` `ucli-bekleyen` | TAŞINDI |
| `LastExchangePairingTest.test_answered_turn_pairs_normally` (py/tests/test_ucli_last_exchange_pairing.py:22) | `parity.rs::parity_chat` `ucli-cevapli` | TAŞINDI |
| `LastExchangePairingTest.test_assistant_only_and_empty` (py/tests/test_ucli_last_exchange_pairing.py:26) | `parity.rs::parity_chat` `ucli-yalniz-asistan` `ucli-satir-bos` `ucli-sid-yok` | TAŞINDI |
| `ValidateTests.test_empty_and_zero_drop_key` (py/tests/test_ucli_limit_flags.py:30) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_ints_accepted` (py/tests/test_ucli_limit_flags.py:36) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_ints_invalid_are_errors` (py/tests/test_ucli_limit_flags.py:41) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_bools` (py/tests/test_ucli_limit_flags.py:48) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_price_two_and_four` (py/tests/test_ucli_limit_flags.py:55) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_price_invalid` (py/tests/test_ucli_limit_flags.py:59) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ArgvTests.test_nothing_by_default` (py/tests/test_ucli_limit_flags.py:67) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `ArgvTests.test_int_flags_with_values` (py/tests/test_ucli_limit_flags.py:74) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ArgvTests.test_price_and_bools` (py/tests/test_ucli_limit_flags.py:80) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ArgvTests.test_unsupported_flag_is_skipped_not_fatal` (py/tests/test_ucli_limit_flags.py:86) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `ArgvTests.test_only_supported_ones_added` (py/tests/test_ucli_limit_flags.py:90) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `LiveContext.test_bytes_over_four` (py/tests/test_ucli_live_context.py:16) | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `LiveContext.test_zero_is_zero` (py/tests/test_ucli_live_context.py:19) | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `LiveContext.test_unknown_cases_are_none` (py/tests/test_ucli_live_context.py:22) | `parity.rs::parity_live` `durum-` | TAŞINDI |
| `LiveContext.test_reader_error_is_none` (py/tests/test_ucli_live_context.py:30) | `parity.rs::parity_live` `durum-dizin` (okunamayan dosya = None) | TAŞINDI |
| `MaxSessionUsd.test_valid_kept_as_float` (py/tests/test_ucli_max_session_usd.py:10) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `MaxSessionUsd.test_zero_and_empty_dropped` (py/tests/test_ucli_max_session_usd.py:14) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `MaxSessionUsd.test_invalid_rejected` (py/tests/test_ucli_max_session_usd.py:18) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `MaxSessionUsd.test_independent_of_per_turn_cap` (py/tests/test_ucli_max_session_usd.py:24) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `DefaultCap.test_default_is_8_and_configurable` (py/tests/test_ucli_max_session_usd.py:35) | `parity.rs::parity_settings_pyfmt` `usd` | TAŞINDI |
| `DefaultCap.test_provider_uses_default_when_record_has_none` (py/tests/test_ucli_max_session_usd.py:43) | `parity.rs::parity_ucli` `hizmet-grok-tavan-ayar` `hizmet-grok` | TAŞINDI |
| `MetricsFileArgs.test_on_and_supported` (py/tests/test_ucli_metrics_file_arg.py:22) | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-` | TAŞINDI |
| `MetricsFileArgs.test_off_unsupported_nameless` (py/tests/test_ucli_metrics_file_arg.py:27) | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-` | TAŞINDI |
| `MetricsFileArgs.test_name_sanitised` (py/tests/test_ucli_metrics_file_arg.py:32) | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-` | TAŞINDI |
| `FlattenTest.test_ucli_flattens` (py/tests/test_ucli_multiline_flatten.py:15) | `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation`; parite `g4-sabit-ucli` | TAŞINDI |
| `FlattenTest.test_ucli_single_line_unchanged` (py/tests/test_ucli_multiline_flatten.py:19) | `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation`; parite `g4-sabit-ucli` | TAŞINDI |
| `FlattenTest.test_ucli_trailing_newline` (py/tests/test_ucli_multiline_flatten.py:23) | `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation`; parite `g4-sabit-ucli` | TAŞINDI |
| `FlattenTest.test_ucli_tab_single_line` (py/tests/test_ucli_multiline_flatten.py:26) | `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation`; parite `g4-sabit-ucli` | TAŞINDI |
| `FlattenTest.test_ucli_long_text_not_truncated` (py/tests/test_ucli_multiline_flatten.py:29) | `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation`; parite `g4-sabit-ucli` | TAŞINDI |
| `FlattenTest.test_single_fold_point_in_callers` (py/tests/test_ucli_multiline_flatten.py:37) | T4/T10: Python çağıran kaynağının taraması (`handover.py` kendisi katlamaz); Rust çağıranı henüz yok | KAPSAM DIŞI |
| `FlattenTest.test_other_providers_untouched` (py/tests/test_ucli_multiline_flatten.py:44) | `tests/tui.rs::other_providers_keep_the_input`; parite `g4-sabit-` | TAŞINDI |
| `LivePhaseTests.test_a_streaming_phase_comes_through` (py/tests/test_ucli_phase.py:36) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_the_last_write_time_of_the_file_comes_through_as_last_unix` (py/tests/test_ucli_phase.py:41) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_a_missing_or_garbage_last_activity_is_left_out_not_zeroed` (py/tests/test_ucli_phase.py:46) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_a_retry_phase_keeps_its_reason` (py/tests/test_ucli_phase.py:54) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_no_phase_a_null_phase_or_an_older_binary_mean_none` (py/tests/test_ucli_phase.py:60) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_a_phase_without_a_usable_name_is_ignored` (py/tests/test_ucli_phase.py:67) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_bad_numbers_are_dropped_never_turned_into_an_invented_zero` (py/tests/test_ucli_phase.py:73) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_text_is_trimmed_and_capped` (py/tests/test_ucli_phase.py:79) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_a_future_phase_name_passes_through_so_the_badge_does_not_go_silent` (py/tests/test_ucli_phase.py:85) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_only_the_known_fields_are_returned` (py/tests/test_ucli_phase.py:89) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_no_status_file_no_sid_or_a_broken_file_mean_none` (py/tests/test_ucli_phase.py:93) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LivePhaseTests.test_every_other_provider_has_no_phase` (py/tests/test_ucli_phase.py:101) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `LivePhaseHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` (py/tests/test_ucli_phase.py:122) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_waiting_for_the_response_turns_amber_then_red_on_the_thresholds` (py/tests/test_ucli_phase.py:127) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_retries_and_rate_limits_are_always_amber` (py/tests/test_ucli_phase.py:133) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_model_that_is_thinking_or_writing_is_progress_not_a_warning` (py/tests/test_ucli_phase.py:139) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_stream_that_goes_quiet_turns_amber_then_red_and_progress_stays_green` (py/tests/test_ucli_phase.py:145) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_long_running_stream_that_keeps_writing_is_not_a_warning` (py/tests/test_ucli_phase.py:154) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_idle_is_reported_but_does_not_decide_the_waiting_colour` (py/tests/test_ucli_phase.py:159) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_without_a_last_write_time_a_stream_has_no_idle_and_no_warning` (py/tests/test_ucli_phase.py:163) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_the_internal_last_unix_is_not_leaked_to_the_wire` (py/tests/test_ucli_phase.py:167) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_the_providers_dict_is_not_mutated` (py/tests/test_ucli_phase.py:171) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_missing_since_unix_means_no_elapsed_and_no_warning` (py/tests/test_ucli_phase.py:176) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_since_in_the_future_never_gives_a_negative_elapsed` (py/tests/test_ucli_phase.py:180) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_no_phase_means_none` (py/tests/test_ucli_phase.py:184) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_failing_provider_never_breaks_the_panel` (py/tests/test_ucli_phase.py:188) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_a_registered_running_ucli_row_carries_its_phase` (py/tests/test_ucli_phase.py:226) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait` (py/tests/test_ucli_phase.py:231) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_a_frozen_stream_row_goes_amber_from_the_file_write_time` (py/tests/test_ucli_phase.py:235) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_a_stopped_row_and_a_phaseless_provider_have_no_phase` (py/tests/test_ucli_phase.py:242) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LimitOverridesTests.test_the_timeout_is_a_valid_override_as_a_string_or_a_number` (py/tests/test_ucli_request_timeout.py:62) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `LimitOverridesTests.test_unset_empty_and_invalid_values_fall_back_to_the_default` (py/tests/test_ucli_request_timeout.py:66) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `LimitOverridesTests.test_the_other_overrides_are_unaffected` (py/tests/test_ucli_request_timeout.py:72) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `TimeoutArgsTests.test_a_binary_that_knows_the_flag_gets_the_600_second_default` (py/tests/test_ucli_request_timeout.py:78) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `TimeoutArgsTests.test_the_settings_override_replaces_the_default` (py/tests/test_ucli_request_timeout.py:84) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `TimeoutArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` (py/tests/test_ucli_request_timeout.py:88) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `TimeoutArgsTests.test_a_missing_binary_gets_nothing_instead_of_raising` (py/tests/test_ucli_request_timeout.py:94) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `BuildInnerCommandTests.test_the_default_command_ends_with_the_600_second_timeout` (py/tests/test_ucli_request_timeout.py:123) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_the_settings_override_reaches_the_command` (py/tests/test_ucli_request_timeout.py:126) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_request_timeout.py:132) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` (py/tests/test_ucli_request_timeout.py:136) | `parity.rs::parity_ucli` `anahtar-yaz` | TAŞINDI |
| `BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` (py/tests/test_ucli_request_timeout.py:142) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` (py/tests/test_ucli_request_timeout.py:152) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` (py/tests/test_ucli_request_timeout.py:159) | rs/prov: gereksiz: teslim edilen gerçek ucli ikilisini sınar | KAPSAM DIŞI |
| `OwnCopyLocationTests.test_own_copy_lives_in_the_repo_bin_directory_and_is_named_ucli` (py/tests/test_ucli_resolve_binary.py:32) | `parity.rs::parity_build` `ru-kendi-` (kendi kopya `<repo>/bin/ucli` yolu ve adıyla seçilir); depo kökü `real/launch.rs::repo_dir_of`, `parity_g9` `REPO_DIR` | TAŞINDI |
| `OwnCopyLocationTests.test_a_session_started_from_the_own_copy_is_still_recognised_as_ucli` (py/tests/test_ucli_resolve_binary.py:38) | rs/proc: `providers.rs::detect` | KAPSAM DIŞI |
| `ResolveBinaryTests.test_own_copy_beats_path_and_the_sibling_builds` (py/tests/test_ucli_resolve_binary.py:79) | `parity.rs::parity_build` `ru-kendi-path-ve-kardesleri-yener`, `ru-kendi-calistirilamaz-da-sayilir`, `ru-kendi-dizin-sayilmaz` | TAŞINDI |
| `ResolveBinaryTests.test_path_beats_the_sibling_builds_when_there_is_no_own_copy` (py/tests/test_ucli_resolve_binary.py:85) | `parity.rs::parity_build` `ru-kendi-yoksa-path-kardesleri-yener`, `ru-kendi-yoksa-pathsiz-release` | TAŞINDI |
| `ResolveBinaryTests.test_sibling_release_is_preferred_over_sibling_debug` (py/tests/test_ucli_resolve_binary.py:90) | `parity.rs::parity_build` `ru-kardes-release` `ru-kardes-debug` | TAŞINDI |
| `ResolveBinaryTests.test_sibling_debug_is_the_fallback_when_there_is_no_sibling_release` (py/tests/test_ucli_resolve_binary.py:94) | `parity.rs::parity_build` `ru-kardes-release` `ru-kardes-debug` | TAŞINDI |
| `ResolveBinaryTests.test_sibling_release_alone_is_used` (py/tests/test_ucli_resolve_binary.py:98) | `parity.rs::parity_build` `ru-kardes-release` `ru-kardes-debug` | TAŞINDI |
| `ResolveBinaryTests.test_no_build_raises_a_clear_error_that_names_the_installer` (py/tests/test_ucli_resolve_binary.py:102) | `parity.rs::parity_build` `ru-hic` | TAŞINDI |
| `ResolveBinaryTests.test_overrides_beat_the_own_copy_so_debug_can_be_forced` (py/tests/test_ucli_resolve_binary.py:109) | `parity.rs::parity_build` `ru-kendi-ayar-debuga-zorlar`, `ru-kendi-env-debuga-zorlar`; açık argüman `real/oneshot.rs` (`ChatRequest.binary`), `parity_oneshot` `ikili-` | TAŞINDI |
| `ResolveBinaryTests.test_settings_override_beats_env_and_env_beats_the_own_copy` (py/tests/test_ucli_resolve_binary.py:123) | `parity.rs::parity_build` `ru-kendi-ayar-env-yener`, `ru-kendi-env-yener` | TAŞINDI |
| `ScriptModeSettingTests.test_default_and_garbage_mean_off` (py/tests/test_ucli_script.py:42) | `parity.rs::parity_settings_pyfmt` `script` | TAŞINDI |
| `ScriptModeSettingTests.test_read_and_full_in_any_spelling` (py/tests/test_ucli_script.py:47) | `parity.rs::parity_settings_pyfmt` `script` | TAŞINDI |
| `ScriptModeSettingTests.test_default_settings_carry_the_key` (py/tests/test_ucli_script.py:52) | rs/state: `default_settings.json` | KAPSAM DIŞI |
| `BuildCommandTests.test_off_leaves_the_command_exactly_as_before` (py/tests/test_ucli_script.py:75) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildCommandTests.test_read_and_full_append_one_equals_form_flag` (py/tests/test_ucli_script.py:79) | `parity.rs::parity_ucli` `ayar-script-full` `eksik` | TAŞINDI |
| `BuildCommandTests.test_old_binary_without_the_flag_is_not_given_it` (py/tests/test_ucli_script.py:84) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `BuildCommandTests.test_allow_create_mode_passes_only_that_flag` (py/tests/test_ucli_script.py:90) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildCommandTests.test_allow_create_on_a_binary_that_lacks_it_opens_read_only` (py/tests/test_ucli_script.py:95) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `BuildCommandTests.test_permission_modes_list_and_round_trip_from_the_running_command` (py/tests/test_ucli_script.py:102) | `parity.rs::parity_model_effort` `bos-`; çalışan komuttan geri okuma rs/proc `providers.rs::ucli_info` | TAŞINDI |
| `SaveScriptSettingTests.test_mode_round_trips_and_an_empty_one_switches_the_layer_off` (py/tests/test_ucli_script.py:122) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveScriptSettingTests.test_saving_the_mode_leaves_the_other_ucli_panels_alone` (py/tests/test_ucli_script.py:131) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveScriptSettingTests.test_a_hand_edited_non_dict_value_degrades_to_off` (py/tests/test_ucli_script.py:139) | `parity.rs::parity_settings_pyfmt` `limitler-tip` | TAŞINDI |
| `SaveScriptSettingTests.test_the_panel_endpoint_returns_the_field_on_the_wire` (py/tests/test_ucli_script.py:144) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SearchTokenEnvTest.test_default_absent` (py/tests/test_ucli_search_token_env.py:21) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `SearchTokenEnvTest.test_valid_name` (py/tests/test_ucli_search_token_env.py:27) | `parity.rs::parity_ucli` `ste` `ste-deger` `ste-uzun` | TAŞINDI |
| `SearchTokenEnvTest.test_empty_means_not_sent` (py/tests/test_ucli_search_token_env.py:32) | `parity.rs::parity_ucli` `opts-ste-bos`, `opts-ste-bosluk` | TAŞINDI |
| `SearchTokenEnvTest.test_invalid_names_error` (py/tests/test_ucli_search_token_env.py:36) | `parity.rs::parity_ucli` `ste` `ste-deger` `ste-uzun` | TAŞINDI |
| `SearchTokenEnvTest.test_argv_with_search_url` (py/tests/test_ucli_search_token_env.py:42) | `parity.rs::parity_ucli` `ste-arama` | TAŞINDI |
| `SearchTokenEnvTest.test_skipped_without_search_url` (py/tests/test_ucli_search_token_env.py:47) | `parity.rs::parity_ucli` `ste` | TAŞINDI |
| `SearchTokenEnvTest.test_unsupported_binary_skips` (py/tests/test_ucli_search_token_env.py:50) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `ServicesTests.test_defaults_when_empty` (py/tests/test_ucli_services_settings.py:18) | `parity.rs::parity_settings_pyfmt` `bos` `servisler` | TAŞINDI |
| `ServicesTests.test_groq_label` (py/tests/test_ucli_services_settings.py:23) | `parity.rs::parity_settings_pyfmt` `bos` `dosya-yok` (`label` alanı) | TAŞINDI |
| `ServicesTests.test_invalid_dropped_evren_always_present` (py/tests/test_ucli_services_settings.py:27) | `parity.rs::parity_settings_pyfmt` `servis-label-models` | TAŞINDI |
| `ServicesTests.test_services_map_follows_settings` (py/tests/test_ucli_services_settings.py:39) | `parity.rs::parity_settings_pyfmt` `servisler` ; `parity.rs::parity_ucli` `hizmet-ozel` | TAŞINDI |
| `ServicesTests.test_effort_follows_model` (py/tests/test_ucli_services_settings.py:46) | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `SettingTests.test_default_off_and_words` (py/tests/test_ucli_show_reasoning.py:24) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `BuildTests.test_flag_added_only_when_enabled_and_supported` (py/tests/test_ucli_show_reasoning.py:43) | `parity.rs::parity_ucli` `ayar-stream-off` `eksik` | TAŞINDI |
| `BuildTests.test_old_binary_never_gets_the_flag_and_it_is_logged` (py/tests/test_ucli_show_reasoning.py:47) | `parity.rs::parity_ucli` `ayar-stream-off` `eksik` | TAŞINDI |
| `ValidateTests.test_empty_is_ok_and_empty` (py/tests/test_ucli_start_opts.py:29) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_unknown_service_rejected` (py/tests/test_ucli_start_opts.py:33) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_shells_and_wrappers_rejected` (py/tests/test_ucli_start_opts.py:36) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_glob_needs_cmds_and_must_be_narrow` (py/tests/test_ucli_start_opts.py:40) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_timeout_range_and_requires_cmds` (py/tests/test_ucli_start_opts.py:48) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `BuildTests.test_no_opts_is_identical_to_before` (py/tests/test_ucli_start_opts.py:80) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `BuildTests.test_max_history_kib_is_passed_only_when_the_binary_knows_it_and_the_setting_wins` (py/tests/test_ucli_start_opts.py:84) | `parity.rs::parity_ucli` `ayar-limit` `eksik` | TAŞINDI |
| `BuildTests.test_claude_service_swaps_endpoint_once_and_key_stays_out_of_argv` (py/tests/test_ucli_start_opts.py:98) | `parity.rs::parity_ucli` `hizmet-claude` | TAŞINDI |
| `BuildTests.test_claude_service_gets_team_flags_and_is_refused_over_the_daily_cap` (py/tests/test_ucli_start_opts.py:116) | `real_ledger.rs::a_claude_service_build_is_refused_over_the_cap`; bayraklar `parity.rs::parity_ucli` `hizmet-claude` | TAŞINDI |
| `BuildTests.test_groq_service_uses_groq_endpoint_and_key_env` (py/tests/test_ucli_start_opts.py:145) | `parity.rs::parity_ucli` `hizmet-grok`; aynı hizmet yolu | TAŞINDI |
| `BuildTests.test_service_models_fetches_live_list_with_correct_auth` (py/tests/test_ucli_start_opts.py:153) | `parity.rs::parity_model_sources` `src-svc-ttl` `src-svc-ayri` `src-svc-istek-yok` (URL ve başlık karşılaştırılır) | TAŞINDI |
| `BuildTests.test_claude_service_skips_instructions_auto_when_file_over_16kib` (py/tests/test_ucli_start_opts.py:177) | `parity.rs::parity_ucli` `hizmet-claude-buyuk-talimat` | TAŞINDI |
| `BuildTests.test_missing_service_key_refuses_spawn` (py/tests/test_ucli_start_opts.py:202) | `parity.rs::parity_ucli` `hizmet-claude-anahtarsiz` | TAŞINDI |
| `BuildTests.test_evren_service_changes_nothing` (py/tests/test_ucli_start_opts.py:206) | `parity.rs::parity_ucli` `hizmet-evren` | TAŞINDI |
| `BuildTests.test_exec_flags_appended_and_gated_by_binary` (py/tests/test_ucli_start_opts.py:209) | `parity.rs::parity_ucli` `toolchain-uygula` `eksik` | TAŞINDI |
| `BuildTests.test_exec_bind_ro` (py/tests/test_ucli_start_opts.py:219) | `parity.rs::parity_ucli` `bind-temel` ; `parity.rs::parity_misc` `exec` | TAŞINDI |
| `BuildTests.test_star_expands_on_path_and_write_adds_allow_edit` (py/tests/test_ucli_start_opts.py:227) | `parity.rs::parity_ucli` `exec-write-create` ; `parity.rs::parity_misc` `expand` | TAŞINDI |
| `BuildTests.test_patterns_validate` (py/tests/test_ucli_start_opts.py:241) | `parity.rs::parity_ucli` `cmds-glob` `cmds-re` | TAŞINDI |
| `BuildTests.test_star_never_opens_forbidden` (py/tests/test_ucli_start_opts.py:249) | `parity.rs::parity_ucli` `cmds-glob-yasak` ; `parity.rs::parity_misc` `expand` | TAŞINDI |
| `BuildTests.test_write_permission_default_off` (py/tests/test_ucli_start_opts.py:259) | `parity.rs::parity_ucli` `write` | TAŞINDI |
| `WiringTests.test_only_ucli_accepts_cli_opts` (py/tests/test_ucli_start_opts.py:267) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `WiringTests.test_spawn_never_passes_cli_opts_to_other_providers` (py/tests/test_ucli_start_opts.py:273) | `parity.rs::parity_spawn` `claude-opts` | TAŞINDI |
| `WiringTests.test_start_rejects_opts_for_non_ucli_and_invalid_opts` (py/tests/test_ucli_start_opts.py:280) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_rejects_before_recording_an_instance` (py/tests/test_ucli_start_opts.py:293) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_lock_timeout_forgets_instance` (py/tests/test_ucli_start_opts.py:328) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_timeout_after_spawn_keeps_instance` (py/tests/test_ucli_start_opts.py:334) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_unexpected_error_before_spawn_forgets_instance` (py/tests/test_ucli_start_opts.py:340) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `CostCapTests.test_today_sums_only_today_and_uses_the_task_model` (py/tests/test_ucli_start_opts.py:370) | `real_ledger.rs::today_sums_only_todays_logs_and_uses_the_task_model` | TAŞINDI |
| `CostCapTests.test_cap_zero_means_off_and_cap_blocks_when_reached` (py/tests/test_ucli_start_opts.py:380) | `real_ledger.rs::cap_zero_is_off_and_a_reached_cap_blocks` | TAŞINDI |
| `CostCapTests.test_config_parsing_is_safe` (py/tests/test_ucli_start_opts.py:391) | `parity.rs::parity_panel` `cost0`..`cost7` | TAŞINDI |
| `CostCapTests.test_credit_total_parsing_is_safe` (py/tests/test_ucli_start_opts.py:403) | `parity.rs::parity_panel` `cost8`..`cost15` | TAŞINDI |
| `TokioThreadsEnvTests.test_env_overrides_limits_tokio_workers` (py/tests/test_ucli_start_opts.py:414) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `TestSetting.test_default_off_and_words` (py/tests/test_ucli_state_dir.py:42) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `TestChatOnce.test_state_dir_passed_only_when_on_supported_and_session` (py/tests/test_ucli_state_dir.py:67) | `parity.rs::parity_oneshot` `durum-dizini-` | TAŞINDI |
| `TestPaths.test_dir_is_per_root_and_stable_and_outside_the_repo` (py/tests/test_ucli_state_dir.py:79) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `TestPaths.test_off_reads_only_legacy_until_the_new_dir_exists` (py/tests/test_ucli_state_dir.py:88) | `parity.rs::parity_live` `dizin-kapali-` | TAŞINDI |
| `TestPaths.test_on_prefers_new_then_falls_back_to_legacy_for_files` (py/tests/test_ucli_state_dir.py:95) | `parity.rs::parity_chat` `ucli-dizin-acik-`; durum dosyası `parity_live` `dizin-acik-`. `UcliIoProvider.list_sessions` iddiası kapsam dışı (`io_providers`, tmux'suz iz) | TAŞINDI |
| `TestSpawnArgv.test_off_by_default_adds_nothing` (py/tests/test_ucli_state_dir.py:118) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `TestSpawnArgv.test_on_adds_flag_for_new_session_only_when_binary_knows_it` (py/tests/test_ucli_state_dir.py:122) | `parity.rs::parity_ucli` `statedir-acik` `eksik` | TAŞINDI |
| `TestSpawnArgv.test_session_with_legacy_history_keeps_the_legacy_dir` (py/tests/test_ucli_state_dir.py:127) | `parity.rs::parity_ucli` `statedir-eski-gecmis` | TAŞINDI |
| `TestSpawnArgv.test_session_already_in_new_dir_keeps_it_even_if_setting_turned_off` (py/tests/test_ucli_state_dir.py:133) | `parity.rs::parity_ucli` `statedir-yeni-gecmis` | TAŞINDI |
| `StreamSettingTests.test_the_shipped_default_is_on` (py/tests/test_ucli_stream.py:38) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_an_untouched_install_asks_for_the_stream_and_off_still_wins` (py/tests/test_ucli_stream.py:43) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_missing_empty_and_garbage_fall_back_to_the_default` (py/tests/test_ucli_stream.py:49) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_on_words_enable_in_any_spelling` (py/tests/test_ucli_stream.py:56) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_off_words_disable_even_when_the_default_is_on` (py/tests/test_ucli_stream.py:61) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_the_stream_key_is_not_mistaken_for_a_numeric_limit` (py/tests/test_ucli_stream.py:67) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `SaveStreamSettingTests.test_it_round_trips_and_an_empty_value_goes_back_to_the_default` (py/tests/test_ucli_stream.py:82) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `SaveStreamSettingTests.test_it_does_not_disturb_the_other_limit_fields` (py/tests/test_ucli_stream.py:90) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `SaveStreamSettingTests.test_a_hand_edited_non_dict_value_degrades_to_the_default` (py/tests/test_ucli_stream.py:98) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `BuildCommandTests.test_off_leaves_the_command_without_the_flag` (py/tests/test_ucli_stream.py:124) | `parity.rs::parity_ucli` `ayar-stream-off` | TAŞINDI |
| `BuildCommandTests.test_on_adds_exactly_one_bare_flag` (py/tests/test_ucli_stream.py:129) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildCommandTests.test_an_old_binary_without_the_flag_is_not_given_it_and_the_skip_is_logged` (py/tests/test_ucli_stream.py:134) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `LiveUsageTests.test_the_counters_come_through_as_written` (py/tests/test_ucli_usage.py:50) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_a_binary_without_usage_means_unknown_not_zero` (py/tests/test_ucli_usage.py:54) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_a_usage_that_is_not_an_object_means_unknown` (py/tests/test_ucli_usage.py:58) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_no_status_file_no_sid_or_a_broken_file_mean_unknown` (py/tests/test_ucli_usage.py:64) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_the_unmetered_fields_of_an_older_binary_count_as_zero` (py/tests/test_ucli_usage.py:72) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_garbage_values_become_zero_never_an_invented_number` (py/tests/test_ucli_usage.py:78) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_only_the_known_counters_are_returned` (py/tests/test_ucli_usage.py:86) | `parity.rs::parity_live` `durum-`, `rastgele-` | TAŞINDI |
| `LiveUsageTests.test_every_other_provider_has_no_counter` (py/tests/test_ucli_usage.py:92) | `parity.rs::parity_live` `varsayilan-` | TAŞINDI |
| `LiveUsageHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` (py/tests/test_ucli_usage.py:104) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LiveUsageHelperTests.test_a_failing_provider_never_breaks_the_panel` (py/tests/test_ucli_usage.py:112) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadUsageTests.test_a_registered_running_ucli_row_carries_its_counters` (py/tests/test_ucli_usage.py:148) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadUsageTests.test_an_unregistered_running_ucli_row_carries_its_counters` (py/tests/test_ucli_usage.py:153) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadUsageTests.test_a_stopped_row_and_a_counterless_provider_have_no_usage` (py/tests/test_ucli_usage.py:157) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `UcliWebConfigTests.test_empty_unset_and_garbage_mean_the_defaults_search_via_the_managed_searxng` (py/tests/test_ucli_web.py:75) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_search_docker_can_be_turned_off_in_every_spelling` (py/tests/test_ucli_web.py:80) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_search_docker_stays_on_for_on_values_and_for_empty_or_null` (py/tests/test_ucli_web.py:86) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_an_explicit_address_wins_and_switches_the_managed_one_off` (py/tests/test_ucli_web.py:91) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_a_filled_but_invalid_address_does_not_fall_back_to_the_managed_searxng` (py/tests/test_ucli_web.py:96) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_valid_searxng_address_defaults_the_flavor` (py/tests/test_ucli_web.py:104) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_https_and_explicit_flavor_in_any_case` (py/tests/test_ucli_web.py:109) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_brave_is_not_supported_yet_and_fails_closed` (py/tests/test_ucli_web.py:113) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_invalid_addresses_keep_search_off` (py/tests/test_ucli_web.py:118) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_whitespace_around_the_address_is_trimmed_not_rejected` (py/tests/test_ucli_web.py:125) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_domains_are_split_lowercased_and_deduplicated_in_order` (py/tests/test_ucli_web.py:129) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_domains_accept_a_list_too` (py/tests/test_ucli_web.py:134) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_invalid_domains_are_dropped_not_fixed` (py/tests/test_ucli_web.py:138) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_whitespace_is_a_separator_not_part_of_a_name` (py/tests/test_ucli_web.py:144) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_single_label_hosts_are_valid` (py/tests/test_ucli_web.py:148) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_domain_count_is_capped` (py/tests/test_ucli_web.py:152) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_fetch_domains_do_not_need_a_search_address` (py/tests/test_ucli_web.py:157) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `SaveSettingsTests.test_defaults_are_off_and_cache_aware` (py/tests/test_ucli_web.py:172) | rs/state: varsayılan ayar belgesi | KAPSAM DIŞI |
| `SaveSettingsTests.test_ucli_web_merges_per_field_and_empty_removes_the_field` (py/tests/test_ucli_web.py:177) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_a_boolean_search_docker_round_trips_and_false_does_not_mean_remove` (py/tests/test_ucli_web.py:185) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_the_off_switch_does_not_disturb_the_other_fields` (py/tests/test_ucli_web.py:196) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_a_list_value_is_stored_as_a_comma_separated_string` (py/tests/test_ucli_web.py:201) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_other_dict_settings_are_unaffected_by_the_list_handling` (py/tests/test_ucli_web.py:206) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_a_non_dict_stored_value_degrades_to_empty` (py/tests/test_ucli_web.py:212) | `parity.rs::parity_settings_pyfmt` `limitler-tip` | TAŞINDI |
| `SaveSettingsTests.test_the_escape_hatch_persists` (py/tests/test_ucli_web.py:218) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `BinaryFlagProbeTests.test_exact_flag_matching` (py/tests/test_ucli_web.py:225) | `parity.rs::parity_ucli` `benzer-bayrak` ; `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `BinaryFlagProbeTests.test_a_longer_flag_does_not_count_as_its_prefix` (py/tests/test_ucli_web.py:232) | `parity.rs::parity_ucli` `benzer-bayrak` ; `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `BinaryFlagProbeTests.test_old_binary_supports_neither` (py/tests/test_ucli_web.py:237) | `parity.rs::parity_ucli` `eski-ikili` | TAŞINDI |
| `BinaryFlagProbeTests.test_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` (py/tests/test_ucli_web.py:242) | `tests/real_process.rs::help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` | TAŞINDI |
| `BinaryFlagProbeTests.test_missing_or_non_executable_binary_is_false_and_not_cached` (py/tests/test_ucli_web.py:252) | `tests/real_process.rs::a_missing_or_non_executable_binary_is_empty_and_not_cached` | TAŞINDI |
| `BinaryFlagProbeTests.test_empty_help_output_is_not_cached` (py/tests/test_ucli_web.py:262) | `tests/real_process.rs::empty_failed_slow_huge_or_non_utf8_help_is_not_cached` | TAŞINDI |
| `BinaryFlagProbeTests.test_the_real_delivered_binary_knows_the_web_flags_when_it_is_new_enough` (py/tests/test_ucli_web.py:267) | rs/prov: gereksiz: teslim edilen gerçek ucli ikilisini sınar | KAPSAM DIŞI |
| `WebArgsTests.test_everything_switched_off_adds_nothing_and_never_probes` (py/tests/test_ucli_web.py:292) | `parity.rs::parity_ucli` `web-docker-kapali` | TAŞINDI |
| `WebArgsTests.test_auto_search_uses_the_managed_searxng_address_and_names_the_session` (py/tests/test_ucli_web.py:300) | `real_searxng.rs::a_build_asks_for_the_managed_address_only_when_it_should_use_it` | TAŞINDI |
| `WebArgsTests.test_auto_search_not_ready_opens_the_session_without_search_and_without_error` (py/tests/test_ucli_web.py:307) | `parity.rs::parity_ucli` `web-docker-bos-url` `temel-` | TAŞINDI |
| `WebArgsTests.test_auto_search_with_an_old_binary_never_touches_docker` (py/tests/test_ucli_web.py:313) | `real_searxng.rs::a_build_asks_for_the_managed_address_only_when_it_should_use_it` | TAŞINDI |
| `WebArgsTests.test_an_explicit_address_never_starts_the_managed_one` (py/tests/test_ucli_web.py:321) | `real_searxng.rs::a_build_asks_for_the_managed_address_only_when_it_should_use_it` | TAŞINDI |
| `WebArgsTests.test_a_filled_invalid_address_neither_searches_nor_starts_docker` (py/tests/test_ucli_web.py:325) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `WebArgsTests.test_a_crash_in_the_managed_searxng_never_breaks_the_spawn` (py/tests/test_ucli_web.py:329) | `real_searxng.rs::a_provision_command_that_cannot_start_is_logged_and_never_reaches_the_caller`; Rust yöneticisi istisna üretemez (`parity_searxng` `durum-dizini-dosya`) | TAŞINDI |
| `WebArgsTests.test_auto_search_and_fetch_domains_combine` (py/tests/test_ucli_web.py:335) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `WebArgsTests.test_both_capabilities_on_a_new_binary` (py/tests/test_ucli_web.py:341) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `WebArgsTests.test_search_only_adds_no_fetch_flags` (py/tests/test_ucli_web.py:348) | `parity.rs::parity_ucli` `web-docker-hazir` `web-url` | TAŞINDI |
| `WebArgsTests.test_fetch_only_adds_no_search_flags` (py/tests/test_ucli_web.py:352) | `parity.rs::parity_ucli` `web-docker-kapali` `web-url` `eksik` | TAŞINDI |
| `WebArgsTests.test_a_binary_that_only_has_fetch_drops_search_and_says_so` (py/tests/test_ucli_web.py:356) | `parity.rs::parity_ucli` `web-eksik-bayrak-url` `eksik` | TAŞINDI |
| `WebArgsTests.test_an_old_binary_gets_no_web_flags_at_all_so_spawn_cannot_crash` (py/tests/test_ucli_web.py:362) | `parity.rs::parity_ucli` `eski-ikili` | TAŞINDI |
| `BuildInnerCommandTests.test_default_command_is_byte_identical_to_before_when_no_search_backend_is_ready` (py/tests/test_ucli_web.py:394) | `parity.rs::parity_ucli` `temel-` `web-docker-hazir` | TAŞINDI |
| `BuildInnerCommandTests.test_default_command_gets_the_managed_search_flags_when_the_backend_is_ready` (py/tests/test_ucli_web.py:398) | `parity.rs::parity_ucli` `temel-` `web-docker-hazir` | TAŞINDI |
| `BuildInnerCommandTests.test_web_flags_are_appended_after_everything_else` (py/tests/test_ucli_web.py:405) | `parity.rs::parity_ucli` `web-url` | TAŞINDI |
| `BuildInnerCommandTests.test_url_metacharacters_survive_shell_quoting` (py/tests/test_ucli_web.py:415) | `parity.rs::parity_ucli` `web-metakarakter` | TAŞINDI |
| `BuildInnerCommandTests.test_read_only_sessions_get_web_too_and_no_allow_edit` (py/tests/test_ucli_web.py:420) | `parity.rs::parity_ucli` `web-salt-okunur` | TAŞINDI |
| `BuildInnerCommandTests.test_api_key_wrapper_keeps_the_flags_and_no_secret_enters_argv` (py/tests/test_ucli_web.py:425) | `parity.rs::parity_ucli` `web-anahtar-sarmal` (anahtar değeri komutta yok: `$(cat dosya)`) | TAŞINDI |
| `BuildInnerCommandTests.test_running_command_parsing_is_unaffected_by_the_new_flags` (py/tests/test_ucli_web.py:433) | rs/proc: `providers.rs::ucli_info`; rs-proc-mapping.md bir kenar durumu KISMİ diyor | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_every_effort_preset_round_trips_through_the_running_command` (py/tests/test_ucli_web.py:445) | rs/proc: `providers.rs::ucli_info`; rs-proc-mapping.md bir kenar durumu KISMİ diyor | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_effort_stays_unknown_when_a_limit_was_changed_by_hand_or_is_missing` (py/tests/test_ucli_web.py:458) | rs/proc: `providers.rs::ucli_info`; rs-proc-mapping.md bir kenar durumu KISMİ diyor | KAPSAM DIŞI |
| `AutoContextTests.test_deriving_binary_gets_no_context_flag_and_effort_round_trips` (py/tests/test_ucli_web.py:495) | `parity.rs::parity_ucli` `turetir` | TAŞINDI |
| `AutoContextTests.test_old_binary_keeps_preset_context` (py/tests/test_ucli_web.py:502) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `AutoContextTests.test_explicit_setting_still_wins` (py/tests/test_ucli_web.py:506) | `parity.rs::parity_ucli` `turetir-ayar` | TAŞINDI |
| `AutoContextTests.test_legacy_session_with_other_context_value_is_unknown` (py/tests/test_ucli_web.py:511) | rs/proc: `providers.rs::ucli_info` | KAPSAM DIŞI |
| `FreshParse.test_parse_one_line_format` (py/tests/test_usage_fresh.py:21) | `parity.rs::parity_usage` `usage-claude` (metin `CLAUDE_FRESH`) | TAŞINDI |
| `FreshParse.test_parse_falls_back_to_tui_format` (py/tests/test_usage_fresh.py:27) | `parity.rs::parity_usage` `usage-claude` (TUI yedeği metni) | TAŞINDI |
| `FreshParse.test_other_providers_have_no_fresh_path` (py/tests/test_usage_fresh.py:32) | `parity.rs::parity_usage` `usage-codex` `usage-copilot` `usage-shell` `usage-ucli` (`usage_fresh_argv` None) | TAŞINDI |
| `FreshParse.test_agy_fresh_argv_and_tsv_parse` (py/tests/test_usage_fresh.py:37) | `parity.rs::parity_usage` `usage-agy` (metin `AGY_TSV2`) | TAŞINDI |
| `FreshRun.test_fresh_ok_without_any_session` (py/tests/test_usage_fresh.py:52) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_fresh_failure_returns_none` (py/tests/test_usage_fresh.py:60) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_signed_out_agy_is_auth_required_not_read_failed` (py/tests/test_usage_fresh.py:66) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_missing_binary_is_not_installed` (py/tests/test_usage_fresh.py:77) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_usage_all_prefers_fresh_and_skips_sessions` (py/tests/test_usage_fresh.py:84) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_usage_never_injects_into_live_sessions` (py/tests/test_usage_fresh.py:94) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_api_balance_failure_does_not_break_usage` (py/tests/test_usage_fresh.py:110) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `NoUsageRows.test_codex_and_ucli_explain_instead_of_unsupported` (py/tests/test_usage_fresh.py:123) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `NoUsageRows.test_note_follows_request_language_without_mutating_state` (py/tests/test_usage_fresh.py:131) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `PruneTranscripts.test_only_pure_usage_command_files_after_since_are_removed` (py/tests/test_usage_fresh.py:144) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `ResolvedBinaryFallback.test_claude_found_outside_path` (py/tests/test_usage_fresh.py:162) | `parity.rs::parity_usage` `usage-bin-yok-claude` | TAŞINDI |
| `ResolvedBinaryFallback.test_provider_bin_override_used_by_usage_fresh_argv` (py/tests/test_usage_fresh.py:175) | `parity.rs::parity_usage` `usage-bin-override-claude` `usage-bin-tilde-claude` | TAŞINDI |
| `P.test_parse_percent_fraction_reset` (py/tests/test_usage_fresh_tui.py:21) | `parity.rs::parity_usage` `usage-copilot` (metin `COPILOT_SCREEN`) | TAŞINDI |
| `P.test_parse_without_reset_unchanged` (py/tests/test_usage_fresh_tui.py:25) | `parity.rs::parity_usage` `usage-copilot` (metin `COPILOT_NORESET`) | TAŞINDI |
| `P.test_argv_and_no_print_mode` (py/tests/test_usage_fresh_tui.py:29) | `parity.rs::parity_usage` `usage-copilot` `usage-bin-*-copilot` | TAŞINDI |
| `Ttl.test_ttl_cache_and_stale` (py/tests/test_usage_fresh_tui.py:40) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `IsolatedNoRealRead.test_isolated_panel_does_not_launch_real_cli` (py/tests/test_usage_fresh_tui.py:52) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `IsolatedNoRealRead.test_default_dir_is_not_isolated` (py/tests/test_usage_fresh_tui.py:57) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `RealTmuxTrustDialog.test_dialog_accepted_before_command_in_private_cwd` (py/tests/test_usage_fresh_tui.py:78) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_dead_pid_socket_closed_and_unlinked` (py/tests/test_usage_fresh_tui.py:125) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_own_fresh_socket_untouched_but_own_old_one_closed` (py/tests/test_usage_fresh_tui.py:131) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_live_other_pid_fresh_untouched_old_closed` (py/tests/test_usage_fresh_tui.py:140) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_other_sockets_ignored_and_missing_dir_ok` (py/tests/test_usage_fresh_tui.py:147) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `TestEvren.test_argv_safe_and_key_in_env_only` (py/tests/test_web_review_runner.py:118) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_no_io_flag_when_unsupported` (py/tests/test_web_review_runner.py:133) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_claude_env_filtered` (py/tests/test_web_review_runner.py:137) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_redact_applied_and_answer_extracted` (py/tests/test_web_review_runner.py:145) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_timeout_writes_partial` (py/tests/test_web_review_runner.py:153) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_effort_always_sent_unless_model_rejects_it` (py/tests/test_web_review_runner.py:172) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_file_flag_added_only_when_supported` (py/tests/test_web_review_runner.py:187) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_file_path_is_symlink_free` (py/tests/test_web_review_runner.py:196) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_killed_run_is_recovered_from_partial_file_masked` (py/tests/test_web_review_runner.py:208) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_without_report_heading_is_not_a_report` (py/tests/test_web_review_runner.py:223) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_turn_in_error_json_is_recovered` (py/tests/test_web_review_runner.py:231) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_failed_run_keeps_error_log_masked_0600` (py/tests/test_web_review_runner.py:240) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_successful_run_has_no_error_log` (py/tests/test_web_review_runner.py:253) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_nonzero_no_output_is_error` (py/tests/test_web_review_runner.py:257) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_busy_lock` (py/tests/test_web_review_runner.py:261) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_missing_key_errors_and_releases_lock` (py/tests/test_web_review_runner.py:267) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestCancel.test_cancel_kills_own_group_and_marks_partial` (py/tests/test_web_review_runner.py:276) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestCancel.test_cancel_before_process_exists_is_not_swallowed` (py/tests/test_web_review_runner.py:300) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestCancel.test_cancelled_before_spawn_kills_new_process` (py/tests/test_web_review_runner.py:312) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_isolated_home_with_readonly_allow_list` (py/tests/test_web_review_runner.py:345) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_bwrap_jail_wraps_argv_when_available` (py/tests/test_web_review_runner.py:361) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_no_bwrap_or_jail_off_falls_back_to_allow_list` (py/tests/test_web_review_runner.py:376) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_agy_model_quota_blocks_only_that_model_until_reset` (py/tests/test_web_review_runner.py:394) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_tmpdir_is_writable_home_tmp_and_stale_entries_pruned` (py/tests/test_web_review_runner.py:413) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_allow_override_and_off` (py/tests/test_web_review_runner.py:427) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_ok_done_and_argv` (py/tests/test_web_review_runner.py:458) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_label_mismatch_is_model_fallback_but_file_kept` (py/tests/test_web_review_runner.py:470) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_no_log_is_model_fallback` (py/tests/test_web_review_runner.py:476) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_old_log_not_taken_for_new_run` (py/tests/test_web_review_runner.py:480) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_no_effort_for_non_gemini` (py/tests/test_web_review_runner.py:489) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_model_not_in_agy_list` (py/tests/test_web_review_runner.py:493) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBannerLimit.test_monthly_quota_banner_with_rc0_is_limit_not_done` (py/tests/test_web_review_runner.py:508) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBannerLimit.test_real_report_mentioning_quota_stays_done` (py/tests/test_web_review_runner.py:516) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBannerLimit.test_month_start_helper` (py/tests/test_web_review_runner.py:526) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBodyless.test_failed_run_with_junk_body_is_error` (py/tests/test_web_review_runner.py:551) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBodyless.test_successful_exit_with_junk_body_is_error` (py/tests/test_web_review_runner.py:555) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBodyless.test_report_bodyless_rule` (py/tests/test_web_review_runner.py:559) | rs/rev: `cops-review-core` parite (rs-rev.md) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start` (py/tests/test_web_review_runner.py:570) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start_salvages_draft_report` (py/tests/test_web_review_runner.py:578) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start_salvages_report_from_io_log` (py/tests/test_web_review_runner.py:590) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start_no_report_head_keeps_file_empty` (py/tests/test_web_review_runner.py:608) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_findings_are_saved_before_pair_turns_done` (py/tests/test_web_review_runner.py:647) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_detached_run_writes_files_and_finishes` (py/tests/test_web_review_runner.py:664) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_restart_adopts_live_run_and_finishes_it` (py/tests/test_web_review_runner.py:689) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_run_finished_while_service_down_is_processed` (py/tests/test_web_review_runner.py:704) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_pid_reuse_is_not_adopted_as_alive` (py/tests/test_web_review_runner.py:712) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_adopt_keeps_pre_restart_io_log` (py/tests/test_web_review_runner.py:717) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_adopt_failure_marks_partial_not_stuck_running` (py/tests/test_web_review_runner.py:728) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_without_cfg_old_behavior_partial` (py/tests/test_web_review_runner.py:739) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |

### İlk aday listesinde olmayan test dosyaları (kapsam ya da kullanılan dış adları sınıyor)

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `BadNameSpawnTests.test_bad_name_returns_without_launching_anything` (py/tests/test_spawn_bad_tmux_name.py:11) | `parity.rs::parity_g9` `{cli}-kotu-ad` (`spawn_bad_name`, pencere/bekçi yok), `pencere-kotu-ad`; gerçek tmux `tests/real_tmux.rs::unaddressable_names_run_no_tmux_command_and_open_nothing` | TAŞINDI |
| `ProcStatTest.test_plain` (py/tests/test_proc_stat_parse.py:13) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_comm_with_space_and_paren` (py/tests/test_proc_stat_parse.py:18) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_starttime_index` (py/tests/test_proc_stat_parse.py:22) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_no_paren_raises` (py/tests/test_proc_stat_parse.py:26) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_own_ppid` (py/tests/test_proc_stat_parse.py:30) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_no_inline_copies` (py/tests/test_proc_stat_parse.py:33) | rs/proc: gereksiz: Python kaynak taraması | KAPSAM DIŞI |
| `TestPlanTickQuotaHeld.test_quota_held_project_is_not_started_others_are` (py/tests/test_quota_scoped_api_credit.py:20) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestPlanTickQuotaHeld.test_answer_does_not_start_held_project` (py/tests/test_quota_scoped_api_credit.py:31) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestQuotaScopeHelpers.test_held_projects_only_metered_cli` (py/tests/test_quota_scoped_api_credit.py:43) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestQuotaScopeHelpers.test_blocks_target_depends_on_brain_cli` (py/tests/test_quota_scoped_api_credit.py:47) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestBrainCliConfig.test_set_brain_cli_service_cost` (py/tests/test_quota_scoped_api_credit.py:64) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestBrainCliConfig.test_rejects_bad` (py/tests/test_quota_scoped_api_credit.py:71) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestCreditWindow.test_config_dates_validated` (py/tests/test_quota_scoped_api_credit.py:84) | `parity.rs::parity_panel` `cost16` (ve `cost29`..`cost36`) | TAŞINDI |
| `TestCreditWindow.test_spent_counts_only_since` (py/tests/test_quota_scoped_api_credit.py:89) | `real_ledger.rs::credit_is_hidden_when_empty_counts_old_days_and_never_goes_negative` | TAŞINDI |
| `TestCreditWindow.test_window_days_and_budget` (py/tests/test_quota_scoped_api_credit.py:102) | `real_ledger.rs::the_credit_window_gives_days_left_and_a_daily_budget` | TAŞINDI |
| `ResolvedBinaryOverrideTest.test_valid_executable_override_wins` (py/tests/test_resolved_binary_override.py:16) | `parity.rs::parity_build` `-override` `-override-calismaz` `-override-tilde-kullanici` | TAŞINDI |
| `ResolvedBinaryOverrideTest.test_tilde_expanded` (py/tests/test_resolved_binary_override.py:23) | `parity.rs::parity_build` `-override` `-override-calismaz` `-override-tilde-kullanici` | TAŞINDI |
| `ResolvedBinaryOverrideTest.test_missing_or_non_executable_falls_back_to_path` (py/tests/test_resolved_binary_override.py:30) | `parity.rs::parity_build` `-override` `-override-calismaz` `-override-tilde-kullanici` | TAŞINDI |
| `SelfVerifyTest.test_verdicts_applied_session_not_woken` (py/tests/test_review_self_verify.py:54) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_failure_returns_to_new_then_unclear_after_max_tries` (py/tests/test_review_self_verify.py:69) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_apply_verdicts_exception_requeues_not_stuck` (py/tests/test_review_self_verify.py:78) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_timeout_kills_and_requeues` (py/tests/test_review_self_verify.py:90) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_concurrent_calls_same_project_only_one_starts` (py/tests/test_review_self_verify.py:98) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_missing_verdict_line_requeues_only_that_finding` (py/tests/test_review_self_verify.py:131) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_recover_returns_orphaned_self_verify_to_new` (py/tests/test_review_self_verify.py:138) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_recover_also_returns_orphaned_remote_verify_to_new` (py/tests/test_review_self_verify.py:145) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_recover_leaves_live_remote_verify_alone` (py/tests/test_review_self_verify.py:153) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_process_verdicts_ignores_self_sessions` (py/tests/test_review_self_verify.py:165) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_http_verify_and_auto_verify_use_self_mode` (py/tests/test_review_self_verify.py:174) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_bulk_approve_only_verified_filtered` (py/tests/test_review_self_verify.py:183) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_bulk_endpoint_is_human_only` (py/tests/test_review_self_verify.py:198) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_default_verifier_is_claude_sonnet` (py/tests/test_review_self_verify.py:204) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_codex_verifier_read_only_argv` (py/tests/test_review_self_verify.py:207) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_evren_verifier_waits_for_running_evren_review_and_has_no_allow_flags` (py/tests/test_review_self_verify.py:220) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_missing_model_is_busy_not_marked` (py/tests/test_review_self_verify.py:240) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_config_accepts_provider_and_single_model` (py/tests/test_review_self_verify.py:246) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_work_without_ho_is_detected` (py/tests/test_steward_ho_on_open.py:51) | `web_steward._resume_lacks_ho` + `needs_ho` (T10); kullandığı `resolve_resume_id`/`jsonl_path_for`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_ho_done_is_clean` (py/tests/test_steward_ho_on_open.py:55) | `web_steward._resume_lacks_ho` + `needs_ho` (T10); kullandığı `resolve_resume_id`/`jsonl_path_for`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_new_request_after_ho_needs_ho_again` (py/tests/test_steward_ho_on_open.py:58) | `web_steward._resume_lacks_ho` + `needs_ho` (T10); kullandığı `resolve_resume_id`/`jsonl_path_for`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_empty_conversation_is_clean` (py/tests/test_steward_ho_on_open.py:62) | `web_steward._resume_lacks_ho` + `needs_ho` (T10); kullandığı `resolve_resume_id`/`jsonl_path_for`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_off_and_non_claude_and_ucli_record` (py/tests/test_steward_ho_on_open.py:65) | `web_steward._resume_lacks_ho` + `needs_ho` (T10); kullandığı `resolve_resume_id`/`jsonl_path_for`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_missing_jsonl` (py/tests/test_steward_ho_on_open.py:71) | `web_steward._resume_lacks_ho` + `needs_ho` (T10); kullandığı `resolve_resume_id`/`jsonl_path_for`: `parity.rs::parity_resume` `devam-claude-` | KAPSAM DIŞI |
| `EnsureRunningHoOnOpenTest.test_lacking_ho_resumes_then_hands_over` (py/tests/test_steward_ho_on_open.py:102) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EnsureRunningHoOnOpenTest.test_clean_open_no_handover` (py/tests/test_steward_ho_on_open.py:110) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EnsureRunningHoOnOpenTest.test_handover_failure_no_pending` (py/tests/test_steward_ho_on_open.py:116) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MainSessionModel.test_registered_fable_becomes_sonnet_medium` (py/tests/test_steward_main_model.py:13) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_opus_and_empty_on_claude` (py/tests/test_steward_main_model.py:16) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_non_claude_cli_untouched` (py/tests/test_steward_main_model.py:20) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_remote_unknown_cli_only_claude_models` (py/tests/test_steward_main_model.py:24) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_non_claude_model_on_claude_cli_untouched` (py/tests/test_steward_main_model.py:29) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_no_sonnet_known_is_noop` (py/tests/test_steward_main_model.py:32) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `PreviewOnlyTest.test_preview_does_not_issue_token` (py/tests/test_ucli_agents_preview.py:12) | `tests/real_fs.rs::a_dry_run_build_issues_no_token_and_writes_nothing` | TAŞINDI |
| `ApprovalTest.test_register_dirs_private_and_state` (py/tests/test_ucli_approval.py:30) | `parity.rs::parity_oneshot` `kayit-akis` (izinler ağaç görüntüsünde) | TAŞINDI |
| `ApprovalTest.test_bad_run_key` (py/tests/test_ucli_approval.py:40) | `approval::tests::names_are_full_matches`; `parity.rs::parity_oneshot` `kayit-akis` | TAŞINDI |
| `ApprovalTest.test_parse_suspended` (py/tests/test_ucli_approval.py:45) | `approval::tests::suspended_line_is_searched_from_the_end`; `parity.rs::parity_oneshot` `saf` | TAŞINDI |
| `ApprovalTest.test_pending_lists_and_skips_bad_and_never_reads_suspended` (py/tests/test_ucli_approval.py:52) | T7: onay panel uçları (`/api/ucli/approvals`) | KAPSAM DIŞI |
| `ApprovalTest.test_answer_ok_and_modes` (py/tests/test_ucli_approval.py:65) | T7: onay panel uçları (`/api/ucli/approvals`) | KAPSAM DIŞI |
| `ApprovalTest.test_answer_rejections` (py/tests/test_ucli_approval.py:76) | T7: onay panel uçları (`/api/ucli/approvals`) | KAPSAM DIŞI |
| `BudgetExhaustedTest.test_failures_prefixes_answer_once` (py/tests/test_ucli_budget_exhausted.py:12) | `oneshot::tests::budget_note_prefixes_the_answer_once`; `parity.rs::parity_oneshot` `saf` | TAŞINDI |
| `BudgetExhaustedTest.test_unknown_reason_still_marked` (py/tests/test_ucli_budget_exhausted.py:19) | `oneshot::tests::unknown_budget_reason_is_still_marked`; `parity.rs::parity_oneshot` `saf` | TAŞINDI |
| `BudgetExhaustedTest.test_no_field_unchanged` (py/tests/test_ucli_budget_exhausted.py:23) | `oneshot::tests::absent_or_empty_budget_field_leaves_the_value_unchanged`; `parity.rs::parity_oneshot` `saf` | TAŞINDI |
| `BudgetExhaustedTest.test_parse_turn_marks` (py/tests/test_ucli_budget_exhausted.py:30) | `_parse_turn` üretimde çağrılmayan `UcliReplSession`ın parçası; işaretleme `mark_budget_exhausted` satırlarında sınanır | KAPSAM DIŞI |
| `Registry.test_save_load_0600_and_dir_0700` (py/tests/test_ucli_checks_api.py:28) | T7: yazım ucu (`save_registry`/`replace_checks`/`delete_check`); okuma ve biçim yarısı `real/checks.rs`, `parity.rs::parity_real` `kayit-` | KAPSAM DIŞI |
| `Registry.test_bad_shape_not_written` (py/tests/test_ucli_checks_api.py:35) | T7: yazım ucu (`save_registry`/`replace_checks`/`delete_check`); okuma ve biçim yarısı `real/checks.rs`, `parity.rs::parity_real` `kayit-` | KAPSAM DIŞI |
| `Registry.test_symlink_target_refused` (py/tests/test_ucli_checks_api.py:40) | T7: yazım ucu (`save_registry`/`replace_checks`/`delete_check`); okuma ve biçim yarısı `real/checks.rs`, `parity.rs::parity_real` `kayit-` | KAPSAM DIŞI |
| `Registry.test_delete` (py/tests/test_ucli_checks_api.py:47) | T7: yazım ucu (`save_registry`/`replace_checks`/`delete_check`); okuma ve biçim yarısı `real/checks.rs`, `parity.rs::parity_real` `kayit-` | KAPSAM DIŞI |
| `ReplaceKeepsDoc.test_other_top_level_keys_kept` (py/tests/test_ucli_checks_api.py:55) | T7: yazım ucu (`save_registry`/`replace_checks`/`delete_check`); okuma ve biçim yarısı `real/checks.rs`, `parity.rs::parity_real` `kayit-` | KAPSAM DIŞI |
| `Mode.test_narrow_without_confirm_and_seq_increments` (py/tests/test_ucli_checks_api.py:68) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_widen_needs_confirm` (py/tests/test_ucli_checks_api.py:77) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_above_cap_409` (py/tests/test_ucli_checks_api.py:83) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_audit_written` (py/tests/test_ucli_checks_api.py:87) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_bad_inputs` (py/tests/test_ucli_checks_api.py:94) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_get_mode_reads_file_default_off` (py/tests/test_ucli_checks_api.py:99) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Authz.test_actions` (py/tests/test_ucli_checks_api.py:107) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `RealBinary.test_every_template_validates` (py/tests/test_ucli_checks_real_binary.py:24) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `RealBinary.test_save_adds_version_and_real_validation_rejects_bad` (py/tests/test_ucli_checks_real_binary.py:29) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `Unit.test_version_defaults_to_1_without_binary` (py/tests/test_ucli_checks_real_binary.py:38) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `Unit.test_validation_failure_blocks_write` (py/tests/test_ucli_checks_real_binary.py:42) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `TestBySession.test_breakdown_sorted_and_total_matches` (py/tests/test_ucli_cost_by_session.py:18) | `real_ledger.rs::state_lists_the_top_sessions_by_spend_and_totals_all` | TAŞINDI |
| `TestBySession.test_top_n_limit` (py/tests/test_ucli_cost_by_session.py:29) | `real_ledger.rs::state_lists_the_top_sessions_by_spend_and_totals_all` | TAŞINDI |
| `TestBySession.test_per_session_reads_files` (py/tests/test_ucli_cost_by_session.py:39) | `real_ledger.rs::today_sums_only_todays_logs_and_uses_the_task_model` | TAŞINDI |
| `CreditTest.test_config_parse` (py/tests/test_ucli_cost_credit.py:25) | `parity.rs::parity_panel` `cost8`..`cost13` | TAŞINDI |
| `CreditTest.test_hidden_when_empty` (py/tests/test_ucli_cost_credit.py:32) | `real_ledger.rs::credit_is_hidden_when_empty_counts_old_days_and_never_goes_negative` | TAŞINDI |
| `CreditTest.test_left_counts_old_days_too` (py/tests/test_ucli_cost_credit.py:37) | `real_ledger.rs::credit_is_hidden_when_empty_counts_old_days_and_never_goes_negative` | TAŞINDI |
| `CreditTest.test_left_never_negative` (py/tests/test_ucli_cost_credit.py:48) | `real_ledger.rs::credit_is_hidden_when_empty_counts_old_days_and_never_goes_negative` | TAŞINDI |
| `TestInvalidate.test_invalidate_forces_rescan` (py/tests/test_ucli_cost_invalidate.py:17) | `real_ledger.rs::the_state_is_cached_until_ttl_or_invalidate` | TAŞINDI |
| `RateTest.test_window_scales_rate` (py/tests/test_ucli_cost_rate.py:27) | `real_ledger.rs::the_rate_scales_with_the_window_and_skips_corrupt_lines_and_bad_windows` | TAŞINDI |
| `RateTest.test_per_session_sums_to_total` (py/tests/test_ucli_cost_rate.py:33) | `real_ledger.rs::the_rate_scales_with_the_window_and_skips_corrupt_lines_and_bad_windows` | TAŞINDI |
| `RateTest.test_corrupt_lines_are_skipped` (py/tests/test_ucli_cost_rate.py:40) | `real_ledger.rs::the_rate_scales_with_the_window_and_skips_corrupt_lines_and_bad_windows` | TAŞINDI |
| `RateTest.test_missing_dir_and_bad_window` (py/tests/test_ucli_cost_rate.py:47) | `real_ledger.rs::the_rate_scales_with_the_window_and_skips_corrupt_lines_and_bad_windows` | TAŞINDI |
| `ReleaseOnFailedStart.test_release_returns_the_reserved_share_immediately` (py/tests/test_ucli_cost_release.py:12) | `real_ledger.rs::reservations_share_the_cap_replace_release_and_expire` | TAŞINDI |
| `ReserveTests.test_two_sessions_cap_two` (py/tests/test_ucli_cost_reserve.py:25) | `real_ledger.rs::reservations_share_the_cap_replace_release_and_expire` | TAŞINDI |
| `ReserveTests.test_same_name_replaces` (py/tests/test_ucli_cost_reserve.py:32) | `real_ledger.rs::reservations_share_the_cap_replace_release_and_expire` | TAŞINDI |
| `ReserveTests.test_release_frees_slot` (py/tests/test_ucli_cost_reserve.py:38) | `real_ledger.rs::reservations_share_the_cap_replace_release_and_expire` | TAŞINDI |
| `ReserveTests.test_ttl_expiry` (py/tests/test_ucli_cost_reserve.py:46) | `real_ledger.rs::reservations_share_the_cap_replace_release_and_expire` | TAŞINDI |
| `ReserveTests.test_no_cap_keeps_nothing` (py/tests/test_ucli_cost_reserve.py:51) | `real_ledger.rs::reservations_share_the_cap_replace_release_and_expire` | TAŞINDI |
| `Compute.test_rss_io_children_cpu` (py/tests/test_ucli_metrics.py:44) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Compute.test_stat_comm_with_parens` (py/tests/test_ucli_metrics.py:67) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Compute.test_disk_limits` (py/tests/test_ucli_metrics.py:70) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Compute.test_disk_every_5min` (py/tests/test_ucli_metrics.py:81) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_no_sessions_no_work` (py/tests/test_ucli_metrics.py:93) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_discover_throttled` (py/tests/test_ucli_metrics.py:104) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_disabled_never_starts` (py/tests/test_ucli_metrics.py:112) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_config_parsing` (py/tests/test_ucli_metrics.py:117) | `parity.rs::parity_panel` `metrics-raw0`..`metrics-raw3` | TAŞINDI |
| `Idle.test_settings_default_key` (py/tests/test_ucli_metrics.py:124) | rs/state: `default_settings.json` | KAPSAM DIŞI |
| `Store.test_retention` (py/tests/test_ucli_metrics.py:130) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Store.test_daily_prune_in_sampler` (py/tests/test_ucli_metrics.py:136) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Store.test_wal_and_index` (py/tests/test_ucli_metrics.py:143) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_shape_and_summary` (py/tests/test_ucli_metrics.py:160) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_since_limit` (py/tests/test_ucli_metrics.py:167) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_errors_and_empty` (py/tests/test_ucli_metrics.py:172) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_sessions` (py/tests/test_ucli_metrics.py:178) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_authz` (py/tests/test_ucli_metrics.py:182) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Cost.test_measure_cost_10_children` (py/tests/test_ucli_metrics.py:189) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `LateSessionTest.test_new_session_found_while_another_runs` (py/tests/test_ucli_metrics.py:214) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Routing.test_routed_but_whole_settings_stays_local` (py/tests/test_usage_byok_host_routed.py:15) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Routing.test_byok_needs_admin_config` (py/tests/test_usage_byok_host_routed.py:20) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Routing.test_secret_not_sent_over_plain_http` (py/tests/test_usage_byok_host_routed.py:29) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Routing.test_https_loopback_and_status_read_pass` (py/tests/test_usage_byok_host_routed.py:34) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Endpoint.test_set_read_clear_never_echoes_value` (py/tests/test_usage_byok_host_routed.py:51) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `Endpoint.test_rejects_bad_input_without_writing` (py/tests/test_usage_byok_host_routed.py:61) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `StartTests.test_start_ok_folds_task_and_passes_limits` (py/tests/test_web_agents.py:87) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_ask_setting_starts_child_with_ask_dir` (py/tests/test_web_agents.py:96) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_ask_edit_setting_only_for_edit_mode` (py/tests/test_web_agents.py:102) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_child_sink_called_before_register` (py/tests/test_web_agents.py:111) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_child_sink_error_does_not_block_start` (py/tests/test_web_agents.py:120) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_third_live_child_refused` (py/tests/test_web_agents.py:128) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_edit_needs_allow_edit_parent` (py/tests/test_web_agents.py:135) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_validation` (py/tests/test_web_agents.py:144) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_child_cannot_start_and_parent_must_run` (py/tests/test_web_agents.py:150) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_human_needs_parent` (py/tests/test_web_agents.py:157) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_start_failure_releases_and_forgets` (py/tests/test_web_agents.py:161) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_task_not_delivered_stops_child` (py/tests/test_web_agents.py:169) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_disabled` (py/tests/test_web_agents.py:175) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_models` (py/tests/test_web_agents.py:189) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_status_states` (py/tests/test_web_agents.py:193) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_waiting_input_when_child_has_pending_owner_question` (py/tests/test_web_agents.py:205) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_result_is_last_assistant_after_last_user` (py/tests/test_web_agents.py:216) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_result_readable_after_stop` (py/tests/test_web_agents.py:226) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_other_parent_cannot_see_or_touch` (py/tests/test_web_agents.py:232) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_send_folds_and_refuses_stopped` (py/tests/test_web_agents.py:240) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_parent_closed_stops_children_and_revokes` (py/tests/test_web_agents.py:249) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_reap_debounces_then_closes_orphans` (py/tests/test_web_agents.py:259) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_reap_keeps_children_when_discovery_fails` (py/tests/test_web_agents.py:267) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_reap_enforces_cost_cap` (py/tests/test_web_agents.py:274) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_agent_token_maps_to_parent` (py/tests/test_web_agents_glue.py:31) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_panel_token_is_human` (py/tests/test_web_agents_glue.py:34) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_bad_or_missing_token_rejected` (py/tests/test_web_agents_glue.py:37) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_agent_token_is_not_a_panel_token` (py/tests/test_web_agents_glue.py:41) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_agents_paths_are_local_only` (py/tests/test_web_agents_glue.py:46) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StopHookTests.test_stop_notifies_agents_for_each_killed_session` (py/tests/test_web_agents_glue.py:52) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ProviderBinTypeTest.test_resolved_binary_ignores_non_string_override` (py/tests/test_provider_bin_type.py) | `parity.rs::parity_build` `-override-tip` `override-tip-sayi` | TAŞINDI |
| `ProviderBinTypeTest.test_ucli_resolve_binary_ignores_non_string_override` (py/tests/test_provider_bin_type.py) | `parity.rs::parity_build` `-override-tip` `override-tip-sayi` | TAŞINDI |
| `BadUtf8Test.test_claude_override_unreadable_is_logged_and_left_untouched` (py/tests/test_guidance_bad_utf8.py) | `parity.rs::parity_build` `claude-routing-override-bozuk-utf8` | TAŞINDI |
| `BadUtf8Test.test_sync_skips_bad_file_and_still_syncs_the_other` (py/tests/test_guidance_bad_utf8.py) | `parity.rs::parity_g9` `esitle-*-4`; `parity_misc` `sync-bozuk-utf8` | TAŞINDI |
| `BadUtf8Test.test_sync_bad_agy_file_is_not_removed` (py/tests/test_guidance_bad_utf8.py) | `parity.rs::parity_misc` `sync-bozuk-utf8-kapali` | TAŞINDI |
| `ModelsPayloadTest.test_non_object_or_non_list_payload_returns_none` (py/tests/test_ucli_models_payload.py) | `parity.rs::parity_misc` `live-bicim` `live0` | TAŞINDI |
| `ModelsPayloadTest.test_valid_payload_still_works` (py/tests/test_ucli_models_payload.py) | `parity.rs::parity_misc` `live-bicim` `live0` | TAŞINDI |
| `McpToolNameTest.test_trailing_newline_name_is_dropped` (py/tests/test_ucli_mcp_tool_name.py) | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `McpToolNameTest.test_only_bad_names_means_no_mcp` (py/tests/test_ucli_mcp_tool_name.py) | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `KeyPathQuotingTest.test_key_is_read_from_home_with_space_and_quote` (py/tests/test_ucli_key_path_quoting.py) | `parity.rs::parity_ucli` `tirnak-` | TAŞINDI |
| `TrustFolder.test_bracket_in_registered_path_does_not_duplicate` (py/tests/test_copilot_trust.py) | `parity.rs::parity_build` `trust-ayrac` `trust-unicode-ham` | TAŞINDI |
| `TrustFolder.test_bracket_cwd_is_added_once_and_rest_is_kept` (py/tests/test_copilot_trust.py) | `parity.rs::parity_build` `trust-ayrac` `trust-unicode-ham` | TAŞINDI |
| `TrustFolder.test_comments_inside_list_and_escaped_quote` (py/tests/test_copilot_trust.py) | `parity.rs::parity_build` `trust-ayrac` `trust-unicode-ham` | TAŞINDI |
| `TrustFolder.test_non_ascii_entry_stored_raw_is_not_duplicated` (py/tests/test_copilot_trust.py) | `parity.rs::parity_build` `trust-ayrac` `trust-unicode-ham` | TAŞINDI |
| `TrustFolder.test_unterminated_list_is_left_alone` (py/tests/test_copilot_trust.py) | `parity.rs::parity_build` `trust-ayrac` `trust-unicode-ham` | TAŞINDI |
| `DryRunPureTest.test_claude` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `yan-claude-` | TAŞINDI |
| `DryRunPureTest.test_copilot` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `yan-copilot-` | TAŞINDI |
| `DryRunPureTest.test_agy_and_codex` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `-dry` | TAŞINDI |
| `DryRunPureTest.test_ucli_default_service` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `yan-ucli-dry` | TAŞINDI |
| `DryRunPureTest.test_ucli_unsafe_name_gets_no_agent_flags_in_either_run` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `yan-ucli-dry-1` | TAŞINDI |
| `DryRunPureTest.test_ucli_claude_service_with_ask_dir` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `yan-ucli-hizmet-` | TAŞINDI |
| `DryRunPureTest.test_ucli_removed_key_is_not_deleted_by_dry_run` (py/tests/test_spawn_dry_run_pure.py) | `parity.rs::parity_spawn` `yan-ucli-dry` | TAŞINDI |
| `DismissStrayDialogTest.test_failed_down_sends_no_enter` (py/tests/test_rsprov_g4_dismiss.py:32) | `tests/tui.rs::no_enter_unless_the_cursor_is_seen_on_no`; parite `g4-pane-dialog-tus-basarisiz` | TAŞINDI |
| `DismissStrayDialogTest.test_successful_down_is_followed_by_enter` (py/tests/test_rsprov_g4_dismiss.py:35) | `tests/tui.rs::no_enter_unless_the_cursor_is_seen_on_no`; parite `g4-pane-dialog-model-diyalog` | TAŞINDI |
| `StaleResultText.test_old_marker_does_not_end_the_wait_and_the_late_dialog_is_confirmed` (py/tests/test_tbd399_live_switch.py:88) | `tests/tui.rs::an_old_result_line_does_not_count`; parite `g4-ekran-` | TAŞINDI |
| `StaleResultText.test_old_effort_marker_alone_is_unconfirmed` (py/tests/test_tbd399_live_switch.py:95) | `tests/tui.rs::an_old_result_line_does_not_count`; parite `g4-ekran-` | TAŞINDI |
| `StaleResultText.test_new_marker_is_done` (py/tests/test_tbd399_live_switch.py:101) | `tests/tui.rs::an_old_result_line_does_not_count`; parite `g4-ekran-` | TAŞINDI |
| `StaleResultText.test_claude_refusal_is_a_finished_command` (py/tests/test_tbd399_live_switch.py:106) | `tests/tui.rs::an_old_result_line_does_not_count`; parite `g4-ekran-` | TAŞINDI |
| `OnlyTheOpenExpectedDialog.test_dialog_text_in_conversation_does_not_confirm_a_permission_prompt` (py/tests/test_tbd399_live_switch.py:114) | `tests/tui.rs::only_the_expected_dialog_with_the_cursor_on_yes_is_confirmed`; parite `g4-ekran-` | TAŞINDI |
| `OnlyTheOpenExpectedDialog.test_stray_scan_never_touches_a_permission_prompt` (py/tests/test_tbd399_live_switch.py:121) | `tests/tui.rs::only_the_expected_dialog_with_the_cursor_on_yes_is_confirmed`; parite `g4-ekran-` | TAŞINDI |
| `OnlyTheOpenExpectedDialog.test_quoted_dialog_above_the_input_box_is_not_open` (py/tests/test_tbd399_live_switch.py:126) | `tests/tui.rs::only_the_expected_dialog_with_the_cursor_on_yes_is_confirmed`; parite `g4-ekran-` | TAŞINDI |
| `OnlyTheOpenExpectedDialog.test_wrong_kind_wrong_label_or_cursor_on_no_is_not_confirmed` (py/tests/test_tbd399_live_switch.py:131) | `tests/tui.rs::only_the_expected_dialog_with_the_cursor_on_yes_is_confirmed`; parite `g4-ekran-` | TAŞINDI |
| `OnlyTheOpenExpectedDialog.test_precondition_refuses_when_any_dialog_is_open_or_screen_unknown` (py/tests/test_tbd399_live_switch.py:138) | `tests/tui.rs::only_the_expected_dialog_with_the_cursor_on_yes_is_confirmed`; parite `g4-ekran-` | TAŞINDI |
| `Draft.test_typed_draft_blocks_both_commands` (py/tests/test_tbd399_live_switch.py:149) | `tests/tui.rs::draft_dialog_busy_and_unknown_screens_get_no_command`, `a_dim_suggestion_is_not_a_draft` | TAŞINDI |
| `Draft.test_dim_suggestion_is_not_a_draft` (py/tests/test_tbd399_live_switch.py:155) | `tests/tui.rs::draft_dialog_busy_and_unknown_screens_get_no_command`, `a_dim_suggestion_is_not_a_draft` | TAŞINDI |
| `Draft.test_busy_session_gets_no_command_and_is_safe_to_message` (py/tests/test_tbd399_live_switch.py:160) | `tests/tui.rs::draft_dialog_busy_and_unknown_screens_get_no_command`, `a_dim_suggestion_is_not_a_draft` | TAŞINDI |
| `LateDialog.test_late_effort_dialog_is_refused` (py/tests/test_tbd399_live_switch.py:169) | `tests/tui.rs::late_model_and_effort_dialogs_are_refused_after_rereading_the_screen` | TAŞINDI |
| `LateDialog.test_late_model_dialog_is_refused` (py/tests/test_tbd399_live_switch.py:174) | `tests/tui.rs::late_model_and_effort_dialogs_are_refused_after_rereading_the_screen` | TAŞINDI |
| `KeyResultsAreChecked.test_failed_confirm_enter_is_reported` (py/tests/test_tbd399_live_switch.py:183) | `tests/tui.rs::a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated`, `no_enter_unless_the_cursor_is_seen_on_no` | TAŞINDI |
| `KeyResultsAreChecked.test_ignored_confirm_enter_is_not_repeated` (py/tests/test_tbd399_live_switch.py:189) | `tests/tui.rs::a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated`, `no_enter_unless_the_cursor_is_seen_on_no` | TAŞINDI |
| `KeyResultsAreChecked.test_failed_command_send_is_reported` (py/tests/test_tbd399_live_switch.py:194) | `tests/tui.rs::a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated`, `no_enter_unless_the_cursor_is_seen_on_no` | TAŞINDI |
| `KeyResultsAreChecked.test_down_that_did_not_move_the_cursor_gets_no_enter` (py/tests/test_tbd399_live_switch.py:199) | `tests/tui.rs::a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated`, `no_enter_unless_the_cursor_is_seen_on_no` | TAŞINDI |
| `KeyResultsAreChecked.test_dialog_still_open_after_refusing_is_reported` (py/tests/test_tbd399_live_switch.py:205) | `tests/tui.rs::a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated`, `no_enter_unless_the_cursor_is_seen_on_no` | TAŞINDI |
| `KeyResultsAreChecked.test_dialog_in_the_last_look_is_confirmed_and_verified` (py/tests/test_tbd399_live_switch.py:211) | `tests/tui.rs::a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated`, `no_enter_unless_the_cursor_is_seen_on_no` | TAŞINDI |
| `CallersDoNotType.test_blocked_model_step_stops_before_effort` (py/tests/test_tbd399_live_switch.py:250) | Rust'ta çağıran yok (`handover` politikası ve `web._handover`, T4) | KAPSAM DIŞI |
| `CallersDoNotType.test_blocked_effort_step` (py/tests/test_tbd399_live_switch.py:256) | Rust'ta çağıran yok (`handover` politikası ve `web._handover`, T4) | KAPSAM DIŞI |
| `CallersDoNotType.test_done_and_busy_do_not_block` (py/tests/test_tbd399_live_switch.py:262) | Rust'ta çağıran yok (`handover` politikası ve `web._handover`, T4) | KAPSAM DIŞI |
| `CallersDoNotType.test_web_handover_sends_nothing_and_says_why` (py/tests/test_tbd399_live_switch.py:269) | Rust'ta çağıran yok (`handover` politikası ve `web._handover`, T4) | KAPSAM DIŞI |
| `CallersDoNotType.test_batch_handover_sends_nothing_and_counts_a_failure` (py/tests/test_tbd399_live_switch.py:286) | Rust'ta çağıran yok (`handover` politikası ve `web._handover`, T4) | KAPSAM DIŞI |
| `SendText.test_control_characters_are_removed_but_newline_tab_cr_stay` (py/tests/test_tbd399_control_chars.py:28) | `cops-tmux` `parity.rs` (sahte tmux `tmux_send_keys` ve yazma vakaları); ucli: `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation` | TAŞINDI |
| `SendText.test_every_other_control_character_is_removed` (py/tests/test_tbd399_control_chars.py:33) | `cops-tmux` `parity.rs` (sahte tmux `tmux_send_keys` ve yazma vakaları); ucli: `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation` | TAŞINDI |
| `SendText.test_text_with_nothing_but_blanks_and_controls_sends_nothing` (py/tests/test_tbd399_control_chars.py:39) | `cops-tmux` `parity.rs` (sahte tmux `tmux_send_keys` ve yazma vakaları); ucli: `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation` | TAŞINDI |
| `SendText.test_empty_text_is_still_a_deliberate_enter` (py/tests/test_tbd399_control_chars.py:43) | `cops-tmux` `parity.rs` (sahte tmux `tmux_send_keys` ve yazma vakaları); ucli: `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation` | TAŞINDI |
| `SendText.test_ucli_folding_never_turns_newlines_into_an_empty_enter` (py/tests/test_tbd399_control_chars.py:48) | `cops-tmux` `parity.rs` (sahte tmux `tmux_send_keys` ve yazma vakaları); ucli: `tests/tui.rs::ucli_input_is_folded_to_one_line_without_truncation` | TAŞINDI |
| `UnpricedModelCapTest.test_haiku_gets_highest_tier_price_and_both_caps` (py/tests/test_ucli_unpriced_model_cap.py:31) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `UnpricedModelCapTest.test_fable_gets_table_price` (py/tests/test_ucli_unpriced_model_cap.py:37) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `UnpricedModelCapTest.test_builtin_priced_model_gets_no_price_flag` (py/tests/test_ucli_unpriced_model_cap.py:41) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `UnpricedModelCapTest.test_explicit_price_wins_and_enables_per_turn_cap` (py/tests/test_ucli_unpriced_model_cap.py:46) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `UnpricedModelCapTest.test_unknown_price_with_cap_is_refused_with_reason` (py/tests/test_ucli_unpriced_model_cap.py:51) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `UnpricedModelCapTest.test_binary_without_price_flag_is_refused` (py/tests/test_ucli_unpriced_model_cap.py:57) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `UnpricedModelCapTest.test_no_cap_no_refusal` (py/tests/test_ucli_unpriced_model_cap.py:61) | `parity.rs::parity_ucli` `fiyat-` | TAŞINDI |
| `Names.test_trailing_newline_run_key_refused` (py/tests/test_rsprov_g10_approval.py:37) | `approval::tests::names_are_full_matches`; `parity.rs::parity_oneshot` `kayit-akis` | TAŞINDI |
| `Names.test_trailing_newline_approval_id_ignored` (py/tests/test_rsprov_g10_approval.py:41) | `approval::tests::suspended_line_is_searched_from_the_end` | TAŞINDI |
| `Names.test_deep_line_is_skipped` (py/tests/test_rsprov_g10_approval.py:44) | `approval::tests::suspended_line_is_searched_from_the_end` | TAŞINDI |
| `Index.test_corrupt_index_is_copied_before_overwrite` (py/tests/test_rsprov_g10_approval.py:50) | `parity.rs::parity_oneshot` `onay-defter-bozuk` `kayit-belge` `kayit-derin` | TAŞINDI |
| `Index.test_deep_index_reads_as_empty` (py/tests/test_rsprov_g10_approval.py:65) | `parity.rs::parity_oneshot` `kayit-derin` | TAŞINDI |
| `Index.test_unreadable_index_is_not_overwritten` (py/tests/test_rsprov_g10_approval.py:71) | `parity.rs::parity_oneshot` `kayit-okunamaz` | TAŞINDI |
| `Index.test_fifo_index_does_not_block` (py/tests/test_rsprov_g10_approval.py:80) | `tests/real_oneshot.rs::a_fifo_key_file_or_index_is_refused_without_blocking` | TAŞINDI |
| `Index.test_live_run_key_is_not_replaced` (py/tests/test_rsprov_g10_approval.py:101) | `parity.rs::parity_oneshot` `kayit-akis` `onay-defter-canli` | TAŞINDI |
| `BrokenBackupLinkTest.test_dangling_link_writes_neither_backup_nor_target` (py/tests/test_rsprov_g9_fixes.py:51) | `tests/g9.rs::dangling_backup_link_writes_neither_backup_nor_target`; `parity.rs::parity_g9` `esitle-kirik-yedek` | TAŞINDI |
| `BrokenBackupLinkTest.test_link_loop_is_refused_too` (py/tests/test_rsprov_g9_fixes.py:55) | `tests/g9.rs::dangling_backup_link_writes_neither_backup_nor_target`; `parity.rs::parity_g9` `esitle-dongu-yedek` | TAŞINDI |
| `BrokenBackupLinkTest.test_existing_agy_file_with_dangling_backup_link_is_untouched` (py/tests/test_rsprov_g9_fixes.py:58) | `parity.rs::parity_g9` `esitle-kirik-yedek-agy` | TAŞINDI |
| `BrokenBackupLinkTest.test_link_to_an_existing_file_still_counts_as_a_backup` (py/tests/test_rsprov_g9_fixes.py:66) | `parity.rs::parity_g9` `esitle-bagli-yedek` | TAŞINDI |
| `GhostScreenNotLoggedTest.test_only_counts_reach_the_log` (py/tests/test_rsprov_g9_fixes.py:90) | `tests/g9.rs::reclaim_never_panics_and_never_logs_the_screen`; `parity.rs::parity_g9` `hayalet-` | TAŞINDI |
| `GhostScreenNotLoggedTest.test_unreadable_screen_counts_zero` (py/tests/test_rsprov_g9_fixes.py:96) | `tests/g9.rs::reclaim_never_panics_and_never_logs_the_screen`; `parity.rs::parity_g9` `hayalet-0` | TAŞINDI |
| `HiddenWithoutTmuxTest.test_is_logged_and_nothing_is_opened` (py/tests/test_rsprov_g9_fixes.py:124) | `parity.rs::parity_g9` `{cli}-gizli-tmuxsuz` | TAŞINDI |
| `HiddenWithoutTmuxTest.test_hidden_with_tmux_is_unchanged` (py/tests/test_rsprov_g9_fixes.py:129) | `parity.rs::parity_g9` `{cli}-gizli` | TAŞINDI |
| `HiddenWithoutTmuxTest.test_missing_terminal_keeps_its_single_event` (py/tests/test_rsprov_g9_fixes.py:134) | `parity.rs::parity_g9` `{cli}-gtsiz-tmuxsuz` | TAŞINDI |
| `WatchdogValueErrorTest.test_is_logged_without_the_message_and_ends_the_watchdog` (py/tests/test_rsprov_g9_fixes.py:144) | `tests/g9.rs::watchdog_failed_relaunch_is_logged_and_a_value_error_ends_it`; `parity.rs::parity_g9` `bekci-valueerror` | TAŞINDI |
| `Index.test_unrecognised_record_is_not_replaced` (py/tests/test_rsprov_g10_approval.py:113) | `parity.rs::parity_oneshot` `onay-defter-taninmayan` `durumsuz` | TAŞINDI |
| `Index.test_chat_once_refuses_live_key_before_spawn` (py/tests/test_rsprov_g10_approval.py:119) | `tests/real_oneshot.rs::a_live_run_key_is_refused_before_the_binary_starts` | TAŞINDI |
| `Dirs.test_symlinked_run_dir_or_sub_dir_refused` (py/tests/test_rsprov_g10_approval.py:134) | `parity.rs::parity_oneshot` `kayit-baglanti` `onay-kosu-baglanti` | TAŞINDI |
| `ProcessErrors.test_missing_binary_is_ucli_error` (py/tests/test_rsprov_g10_chat.py:43) | `parity.rs::parity_oneshot` `ikili-yok` | TAŞINDI |
| `ProcessErrors.test_non_utf8_output_is_ucli_error` (py/tests/test_rsprov_g10_chat.py:47) | `parity.rs::parity_oneshot` `sohbet-utf8` | TAŞINDI |
| `ProcessErrors.test_nul_in_prompt_is_ucli_error` (py/tests/test_rsprov_g10_chat.py:50) | `parity.rs::parity_oneshot` `prompt-nul` | TAŞINDI |
| `ProcessErrors.test_non_object_output_is_ucli_error` (py/tests/test_rsprov_g10_chat.py:53) | `parity.rs::parity_oneshot` `sohbet-sayi` `liste` `dize` `null` | TAŞINDI |
| `ProcessErrors.test_deeply_nested_output_is_ucli_error` (py/tests/test_rsprov_g10_chat.py:57) | `parity.rs::parity_oneshot` `sohbet-derin`; `approval::tests::suspended_line_is_searched_from_the_end` | TAŞINDI |
| `ProcessErrors.test_child_does_not_inherit_stdin` (py/tests/test_rsprov_g10_chat.py:60) | `parity.rs::parity_oneshot` `sohbet-stdin` | TAŞINDI |
| `ProcessErrors.test_unopenable_approval_dir_is_ucli_error` (py/tests/test_rsprov_g10_chat.py:74) | `parity.rs::parity_oneshot` `onay-kok-dosya` | TAŞINDI |
| `PromptFlagInjection.test_hyphen_prompt_is_refused_before_spawn` (py/tests/test_rsprov_g10_chat.py:81) | `parity.rs::parity_oneshot` `prompt`; `tests/real_oneshot.rs::a_live_run_key_is_refused_before_the_binary_starts` | TAŞINDI |
| `PromptFlagInjection.test_lone_hyphen_and_inner_hyphen_still_pass` (py/tests/test_rsprov_g10_chat.py:87) | `parity.rs::parity_oneshot` `prompt0` `prompt4` | TAŞINDI |
| `SecretRedaction.test_explicit_key_never_reaches_error_text` (py/tests/test_rsprov_g10_chat.py:93) | `parity.rs::parity_oneshot` `sir-acik` | TAŞINDI |
| `SecretRedaction.test_inherited_key_never_reaches_error_text` (py/tests/test_rsprov_g10_chat.py:100) | `parity.rs::parity_oneshot` `sir-miras` | TAŞINDI |
| `SecretRedaction.test_env_name_with_trailing_newline_is_refused` (py/tests/test_rsprov_g10_chat.py:104) | `parity.rs::parity_oneshot` `anahtar-adi-ret2` | TAŞINDI |
| `SecretRedaction.test_resume_error_is_redacted_in_record` (py/tests/test_rsprov_g10_chat.py:108) | T7: onay sürdürme/listeleme (`ucli_resume_approval`, `list_runs`, `recover_resuming`) | KAPSAM DIŞI |
| `BaseOneshot.test_non_utf8_output` (py/tests/test_rsprov_g10_oneshot.py:27) | `parity.rs::parity_oneshot` `argv-utf8` | TAŞINDI |
| `BaseOneshot.test_nul_argument` (py/tests/test_rsprov_g10_oneshot.py:31) | `parity.rs::parity_oneshot` `argv-nul` | TAŞINDI |
| `UcliOneshot.test_non_utf8_key_file_is_refused_without_leaking_bytes` (py/tests/test_rsprov_g10_oneshot.py:54) | `parity.rs::parity_oneshot` `ucli-dosya-utf8` | TAŞINDI |
| `UcliOneshot.test_fifo_key_file_does_not_block` (py/tests/test_rsprov_g10_oneshot.py:63) | `parity.rs::parity_oneshot` `ucli-dosya-aygit` (aygıt; FIFO dalı aynı `is_file/is_dir` denetimi, `tests/real_oneshot.rs::a_fifo_key_file_or_index_is_refused_without_blocking`) | TAŞINDI |
| `UcliOneshot.test_missing_key_file_and_directory_mean_no_key` (py/tests/test_rsprov_g10_oneshot.py:82) | `parity.rs::parity_oneshot` `ucli-anahtarsiz` `ucli-dosya-dizin` | TAŞINDI |
| `UcliOneshot.test_unopenable_cwd` (py/tests/test_rsprov_g10_oneshot.py:88) | `parity.rs::parity_oneshot` `ucli-cwd-dosya` | TAŞINDI |
| `BrokenDocumentRefuses.test_unparsable_or_non_object_documents` (py/tests/test_rsprov_cap_settings.py:58) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `BrokenDocumentRefuses.test_directory_and_fifo` (py/tests/test_rsprov_cap_settings.py:63) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `BrokenDocumentRefuses.test_unreadable_file` (py/tests/test_rsprov_cap_settings.py:73) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `InvalidCapRefuses.test_invalid_values` (py/tests/test_rsprov_cap_settings.py:80) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `InvalidCapRefuses.test_invalid_block` (py/tests/test_rsprov_cap_settings.py:85) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `NoCapStaysOpen.test_missing_file` (py/tests/test_rsprov_cap_settings.py:92) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `NoCapStaysOpen.test_dangling_link_is_a_missing_file` (py/tests/test_rsprov_cap_settings.py:95) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `NoCapStaysOpen.test_absent_or_zero_or_empty` (py/tests/test_rsprov_cap_settings.py:99) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `NoCapStaysOpen.test_valid_cap_still_applies` (py/tests/test_rsprov_cap_settings.py:106) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `OnlyTheClaudeServiceIsAffected.test_broken_settings_refuse_claude_only` (py/tests/test_rsprov_cap_settings.py:134) | `real_ledger.rs::a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open`; `parity.rs::parity_ledger` `tavan-ayari` | TAŞINDI |
| `HelpProbe.test_non_utf8_help_means_no_flags_and_is_logged_once` (py/tests/test_rsprov_help_utf8.py:47) | `tests/real_process.rs::non_utf8_help_gives_no_flags_and_is_logged_once_per_binary_version`; `parity.rs::parity_real` `yardim` | TAŞINDI |
| `HelpProbe.test_a_fixed_binary_is_probed_again` (py/tests/test_rsprov_help_utf8.py:56) | `tests/real_process.rs::non_utf8_help_gives_no_flags_and_is_logged_once_per_binary_version`; `parity.rs::parity_real` `yardim` | TAŞINDI |
| `HelpProbe.test_the_security_permission_flag_is_still_refused` (py/tests/test_rsprov_help_utf8.py:62) | `tests/real_process.rs::non_utf8_help_gives_no_flags_and_is_logged_once_per_binary_version`; `parity.rs::parity_real` `yardim` | TAŞINDI |
| `McpAdd.test_success_follows_the_exit_code` (py/tests/test_rsprov_help_utf8.py:81) | `tests/real_process.rs::register_mcp_with_non_utf8_output_follows_the_exit_code`; `parity.rs::parity_real` `mcp-bozuk-cikti` | TAŞINDI |
| `McpAdd.test_failure_is_reported_not_raised` (py/tests/test_rsprov_help_utf8.py:86) | `tests/real_process.rs::register_mcp_with_non_utf8_output_follows_the_exit_code`; `parity.rs::parity_real` `mcp-bozuk-cikti` | TAŞINDI |
| `McpAdd.test_clean_output_logs_nothing_extra` (py/tests/test_rsprov_help_utf8.py:91) | `tests/real_process.rs::register_mcp_with_non_utf8_output_follows_the_exit_code`; `parity.rs::parity_real` `mcp-bozuk-cikti` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_claude_help` (py/tests/test_rsprov_child_group.py:60) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_ucli_help_when_only_the_grandchild_is_left_holding_the_pipe` (py/tests/test_rsprov_child_group.py:65) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_mcp_add` (py/tests/test_rsprov_child_group.py:70) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_oneshot` (py/tests/test_rsprov_child_group.py:76) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_ucli_chat_once` (py/tests/test_rsprov_child_group.py:87) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_resume` (py/tests/test_rsprov_child_group.py:94) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_agy_models` (py/tests/test_rsprov_child_group.py:103) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `EveryHelperKillsItsOwnGroup.test_docker_cli` (py/tests/test_rsprov_child_group.py:109) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `NeverSignalsAForeignGroup.test_child_in_the_callers_group_gets_no_group_signal` (py/tests/test_rsprov_child_group.py:126) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `NeverSignalsAForeignGroup.test_own_new_group_is_signalled` (py/tests/test_rsprov_child_group.py:130) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `NeverSignalsAForeignGroup.test_group_equal_to_the_callers_is_never_signalled` (py/tests/test_rsprov_child_group.py:134) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `NeverSignalsAForeignGroup.test_a_reaped_child_is_never_signalled` (py/tests/test_rsprov_child_group.py:142) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `NeverSignalsAForeignGroup.test_normal_run_matches_subprocess_run` (py/tests/test_rsprov_child_group.py:150) | `tests/real_process.rs::a_timeout_kills_the_whole_process_group_and_waits`; `tests/real_oneshot.rs::timeouts_kill_the_whole_group_and_return_promptly`; `tests/real_searxng.rs::a_hanging_docker_is_killed_marked_down_and_not_asked_again` | TAŞINDI |
| `FileLockFailsClosed.test_unusable_directory_is_logged_too` (py/tests/test_state_lock_fail_closed.py:59) | `tests/real_agy_store.rs::a_symlinked_lock_file_is_refused_and_nothing_is_written`; `tests/real_oneshot.rs::the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing` | TAŞINDI |
| `FileLockFailsClosed.test_refusal_reaches_the_real_diag_log_even_for_the_settings_file` (py/tests/test_state_lock_fail_closed.py:64) | `tests/real_agy_store.rs::a_symlinked_lock_file_is_refused_and_nothing_is_written`; `tests/real_oneshot.rs::the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing` | TAŞINDI |
| `FileLockFailsClosed.test_success_logs_nothing` (py/tests/test_state_lock_fail_closed.py:75) | `tests/real_agy_store.rs::a_symlinked_lock_file_is_refused_and_nothing_is_written`; `tests/real_oneshot.rs::the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing` | TAŞINDI |

### main `f4679f51` eşitlemesinin testleri (27 Kas)

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `ResolveTest.test_target_exists` (py/tests/test_startup_desktop.py:14) | `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `ResolveTest.test_missing_falls_to_1_then_0` (py/tests/test_startup_desktop.py:19) | `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `ResolveTest.test_off_or_unknown` (py/tests/test_startup_desktop.py:24) | `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `ResolveTest.test_wanted_desktop` (py/tests/test_startup_desktop.py:31) | `parity.rs::parity_g9` `masaustu-` | TAŞINDI |
| `MessageTest.test_message_and_chunks` (py/tests/test_startup_desktop.py:41) | `tests/g9.rs::desktop_resolution_message_and_chunks` | TAŞINDI |
| `MessageTest.test_client_message_layout_matches_xlib` (py/tests/test_startup_desktop.py:49) | `real::startup_desktop::tests::client_message_layout_matches_xlib` | TAŞINDI |
| `MessageTest.test_desktop_count` (py/tests/test_startup_desktop.py:56) | `tests/g9.rs::desktop_count_reads_wmctrl_and_unopenable_display_sends_nothing` | TAŞINDI |
| `StartupEnvTest.test_sets_startup_id_and_desktop` (py/tests/test_startup_desktop.py:78) | `parity.rs::parity_g9` `masaustu-` | TAŞINDI |
| `StartupEnvTest.test_fallback_desktop` (py/tests/test_startup_desktop.py:85) | `parity.rs::parity_g9` `masaustu-tasan-` | TAŞINDI |
| `StartupEnvTest.test_disabled_no_display_send_fail` (py/tests/test_startup_desktop.py:89) | `parity.rs::parity_g9` `masaustu-kapali-` `masaustu-gonderilemedi` (ekransız ortam: `child_env` hep `DISPLAY` yazar, ayrı vaka yok) | TAŞINDI |
| `StartupEnvTest.test_never_raises` (py/tests/test_startup_desktop.py:95) | `parity.rs::parity_g9` `masaustu-gonderim-hata` `masaustu-sayim-hata` | TAŞINDI |
| `StartupEnvTest.test_real_x_untouched_under_tests` (py/tests/test_startup_desktop.py:101) | `tests/g9.rs::gnome_terminal_desktop_is_off_by_default_and_reads_settings_each_time` (Rust'ta açıkça `with_desktop` ister) | TAŞINDI |
| `LaunchTest.test_launch_passes_startup_env` (py/tests/test_startup_desktop.py:109) | `parity.rs::parity_g9` `masaustu-` (`launch` ortamı) | TAŞINDI |
| `StartErrorLineTests.test_died_early_carries_last_error_line` (py/tests/test_ucli_start_error_line.py:34) | bağlayan uç: `web._start` yanıtı (`_with_ucli_error`) bu crate'te yok | KAPSAM DIŞI |
| `StartErrorLineTests.test_no_proc_carries_last_error_line` (py/tests/test_ucli_start_error_line.py:42) | bağlayan uç: `web._start` yanıtı (`_with_ucli_error`) bu crate'te yok | KAPSAM DIŞI |
| `StartErrorLineTests.test_secret_is_masked` (py/tests/test_ucli_start_error_line.py:47) | bağlayan uç: `web._start` yanıtı (`_with_ucli_error`) bu crate'te yok | KAPSAM DIŞI |
| `StartErrorLineTests.test_pane_without_error_line_adds_nothing` (py/tests/test_ucli_start_error_line.py:53) | bağlayan uç: `web._start` yanıtı (`_with_ucli_error`) bu crate'te yok | KAPSAM DIŞI |
| `StartErrorLineTests.test_capture_failure_never_breaks_start_answer` (py/tests/test_ucli_start_error_line.py:58) | bağlayan uç: `web._start` yanıtı (`_with_ucli_error`) bu crate'te yok | KAPSAM DIŞI |
| `StartErrorLineTests.test_other_cli_pane_is_not_read` (py/tests/test_ucli_start_error_line.py:63) | bağlayan uç: `web._start` yanıtı (`_with_ucli_error`) bu crate'te yok | KAPSAM DIŞI |
| `StartErrorLineTests.test_capture_joins_wrapped_lines` (py/tests/test_ucli_start_error_line.py:68) | `cops-tmux` `tests/parity.rs::reads_match_python` (`capture_joined`) | TAŞINDI |
| `TaskEndNotCountedTest.test_task_end_total_is_not_billed_again` (py/tests/test_usage_cost_task_end.py:38) | `parity.rs::parity_ledger` `dilim` | TAŞINDI |
| `TaskEndNotCountedTest.test_one_hour_write` (py/tests/test_usage_cost_task_end.py:41) | `parity.rs::parity_ledger` `dilim` | TAŞINDI |
| `HaikuTierTest.test_up_to_100k_is_the_cheap_tier` (py/tests/test_usage_cost_task_end.py:46) | `parity.rs::parity_ledger` `dilim` | TAŞINDI |
| `HaikuTierTest.test_above_100k_is_the_expensive_tier` (py/tests/test_usage_cost_task_end.py:49) | `parity.rs::parity_ledger` `dilim` | TAŞINDI |
| `HaikuTierTest.test_cached_tokens_count_toward_the_threshold` (py/tests/test_usage_cost_task_end.py:52) | `parity.rs::parity_ledger` `dilim` | TAŞINDI |
| `HaikuTierTest.test_tier_is_per_request_not_summed` (py/tests/test_usage_cost_task_end.py:57) | `parity.rs::parity_ledger` `dilim` | TAŞINDI |

### Önceki turlardan eksik kalan test satırları (27 Kas taramasında bulundu)

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `HttpTest.test_new_chat_resource_is_base_not_name` (py/tests/test_authz.py:279) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `FileLockFailsClosed.test_s1_timeout_raises` (py/tests/test_state_lock_fail_closed.py:43) | `tests/real_oneshot.rs::the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing` | TAŞINDI |
| `FileLockFailsClosed.test_s5_symlink_lock_raises_and_target_untouched` (py/tests/test_state_lock_fail_closed.py:49) | `tests/real_agy_store.rs::a_symlinked_lock_file_is_refused_and_nothing_is_written` | TAŞINDI |
| `FileLockFailsClosed.test_s5_foreign_owner_raises` (py/tests/test_state_lock_fail_closed.py:55) | `real::lock::tests::a_lock_file_owned_by_someone_else_is_refused` (beklenen kullanıcı kimliği testte değiştirilir, Python testi gibi) | TAŞINDI |
| `FileLockFailsClosed.test_error_inside_body_is_not_converted` (py/tests/test_state_lock_fail_closed.py:82) | gereksiz: Rust kilidi bekçi değeri döner, gövde hatası tür olarak ayrıdır | KAPSAM DIŞI |
| `ReadModifyWrite.test_set_mode_seq_counts_every_write` (py/tests/test_ucli_checks_opts.py:105) | T7: yazım uçları (`set_mode`) | KAPSAM DIŞI |
| `ReadModifyWrite.test_two_deletes_both_stick` (py/tests/test_ucli_checks_opts.py:109) | T7: yazım uçları (`delete_check`) | KAPSAM DIŞI |
| `StartTests.test_unsupported_effort_is_ignored_not_rejected` (py/tests/test_web_agents.py:157) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_ignored_effort_is_reported_to_the_client` (py/tests/test_web_agents.py:166) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_omitted_effort_is_medium_only_when_supported` (py/tests/test_web_agents.py:179) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |

### 27 Kas ikinci turunun testleri

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `NonTextModelTest.test_non_text_model_is_skipped` (py/tests/test_rsprov_g3_fixes.py:28) | `parity.rs::parity_transcript` `esit-model-` | TAŞINDI |
| `NonTextModelTest.test_only_non_text_model_means_unknown` (py/tests/test_rsprov_g3_fixes.py:34) | `parity.rs::parity_transcript` `esit-istek-model-sayi` `effort-` | TAŞINDI |
| `SidechainTest.test_sub_agent_rows_do_not_set_model_or_effort` (py/tests/test_rsprov_g3_fixes.py:39) | `parity.rs::parity_transcript` `esit-alt-ajan-model` | TAŞINDI |
| `SidechainTest.test_only_sub_agent_rows_mean_unknown` (py/tests/test_rsprov_g3_fixes.py:45) | `parity.rs::parity_transcript` `alt-ajan` `rastgele-` | TAŞINDI |
| `SidechainTest.test_false_flag_counts` (py/tests/test_rsprov_g3_fixes.py:50) | `parity.rs::parity_transcript` `kullanim-sidechain-sifir` | TAŞINDI |
| `AgyColdTest.test_non_zero_exit_keeps_the_old_list_and_is_logged` (py/tests/test_rsprov_g7_fixes.py:167) | `parity.rs::parity_model_sources` `src-agy-cikis-kodu`; `tests/real_http.rs` (gerçek süreç, `exit 9`) | TAŞINDI |
| `GhostKeptWhenLaunchCannotStartTest.test_nul_anywhere_in_the_launch_leaves_the_old_session` (py/tests/test_rsprov_g9_fixes.py:145) | `parity.rs::parity_g9` `nul-` | TAŞINDI |
| `GhostKeptWhenLaunchCannotStartTest.test_normal_launch_still_reclaims` (py/tests/test_rsprov_g9_fixes.py:153) | `parity.rs::parity_g9` `hayalet-` `ilk-valueerror` | TAŞINDI |
| `WindowTitledTest.test_exact_title_only` (py/tests/test_spawn_retry_no_dup_window.py:21) | `tests/g9.rs::watchdog_relaunches_unless_the_exact_title_is_listed`; `parity.rs::parity_g9` `bekci-pencere-` | TAŞINDI |
| `WindowTitledTest.test_unreadable_is_false` (py/tests/test_spawn_retry_no_dup_window.py:28) | aynı `tests/g9.rs` testi (okunamayan, ekransız); `parity.rs::parity_g9` `bekci-pencere-cikis-1` `-oserror` `-zaman-asimi` | TAŞINDI |
| `UndecodableWindowListTest.test_bad_bytes_in_another_title_still_finds_the_window` (py/tests/test_spawn_retry_no_dup_window.py:48) | `parity.rs::parity_g9` `bekci-pencere-bozuk-bayt`; `tests/g9.rs::watchdog_waits_instead_of_opening_a_second_window` | TAŞINDI |
| `UndecodableWindowListTest.test_value_error_is_unreadable` (py/tests/test_spawn_retry_no_dup_window.py:53) | `parity.rs::parity_g9` `bekci-pencere-valueerror`; `tests/g9.rs::gnome_terminal_window_list_runs_wmctrl_on_the_given_display` (NUL) | TAŞINDI |
| `WatchdogTest.test_existing_window_no_second_launch` (py/tests/test_spawn_retry_no_dup_window.py:75) | `tests/g9.rs::watchdog_waits_instead_of_opening_a_second_window`; `parity.rs::parity_g9` `bekci-pencere-var` | TAŞINDI |
| `WatchdogTest.test_no_window_retries_as_before` (py/tests/test_spawn_retry_no_dup_window.py:79) | `tests/g9.rs::watchdog_retries_then_falls_back_to_headless_tmux`; `parity.rs::parity_g9` `bekci-hic` | TAŞINDI |
| `AllowedNamesTest.test_default_and_builtin_service_names_without_a_settings_file` (py/tests/test_tbd401_api_key_env.py:70) | `tests/real_oneshot.rs::only_known_key_env_names_start_a_child`; `parity.rs::parity_oneshot` `tbd401-` | TAŞINDI |
| `AllowedNamesTest.test_any_other_name_is_refused` (py/tests/test_tbd401_api_key_env.py:74) | `tests/real_oneshot.rs::only_known_key_env_names_start_a_child`; `parity.rs::parity_oneshot` `tbd401-` | TAŞINDI |
| `AllowedNamesTest.test_service_defined_in_settings_is_accepted_and_replaces_the_builtin_list` (py/tests/test_tbd401_api_key_env.py:82) | `tests/real_oneshot.rs::only_known_key_env_names_start_a_child`; `parity.rs::parity_oneshot` `tbd401-` | TAŞINDI |
| `AllowedNamesTest.test_invalid_service_entry_does_not_allow_its_name` (py/tests/test_tbd401_api_key_env.py:88) | `tests/real_oneshot.rs::only_known_key_env_names_start_a_child`; `parity.rs::parity_oneshot` `tbd401-` | TAŞINDI |
| `UnsureSettingsTest.test_broken_settings_allow_only_the_default_name` (py/tests/test_tbd401_api_key_env.py:94) | `tests/real_oneshot.rs::only_known_key_env_names_start_a_child`; `parity.rs::parity_oneshot` `tbd401-` | TAŞINDI |
| `UnsureSettingsTest.test_non_utf8_and_non_regular_settings_allow_only_the_default_name` (py/tests/test_tbd401_api_key_env.py:101) | `tests/real_oneshot.rs::only_known_key_env_names_start_a_child` (UTF-8 olmayan, FIFO) | TAŞINDI |
| `IoAskTest.test_panel_request_is_refused_before_anything_runs` (py/tests/test_tbd401_api_key_env.py:110) | T7: `/api/io/ask` ve `io_providers` bu crate'te yok; kuralın kendisi `ucli_chat_once` satırında sınanır | KAPSAM DIŞI |
| `IoAskTest.test_panel_request_without_a_name_uses_the_default` (py/tests/test_tbd401_api_key_env.py:120) | T7: `/api/io/ask` alan varsayılanı (`io_providers`) bu crate'te yok | KAPSAM DIŞI |

### main `ec82eac5` eşitlemesinin testleri (27 Kas)

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `CostCacheRace.test_invalidate_between_scan_and_read_keeps_cap_closed` (py/tests/test_uzops_review_fixes.py:16) | `tests/real_ledger.rs::the_state_is_cached_until_ttl_or_invalidate`; yarış Rust'ta yapısal olarak yok (`CostLedger::state_with` yanıtı yerel `Snapshot` kopyasından kurar) | TAŞINDI |
| `CorruptDraft.test_corrupt_draft_is_copied_before_next_save_overwrites_it` (py/tests/test_uzops_review_fixes.py:31) | rs/state / T7: `orch_store` taslak dosyası; bu iz kapsamı değil | KAPSAM DIŞI |
| `ModelCheckBinary.test_uses_resolved_claude_binary` (py/tests/test_uzops_review_fixes.py:49) | T7: `model_freshness` periyodik yoklaması bu crate'te yok | KAPSAM DIŞI |
| `OneStartPerProject.test_two_answers_one_start_and_slot_left_for_other_project` (py/tests/test_steward_one_start_per_project.py:20) | rs/stew: `cops-steward-core` `tick/slots.rs` (main `ec82eac5` ile aynı commit) | KAPSAM DIŞI |
| `AgyTest.test_document_that_cannot_be_written_back_does_not_drop_the_scan` (py/tests/test_rsprov_g1_fixes.py) | `parity_docs::state_docs_match_python_in_every_backend` `vekil` | TAŞINDI |
