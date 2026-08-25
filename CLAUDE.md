# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool (guard cron + handover bunu kullanır); **`./claudeops`** (bash) = layout + eski komutlar.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. `-n` display, `--remote-control` RC bridge; aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang). `--claude-only`: sadece aktif RC proc'larını tile'la.
- **claude 2.1.169**: fresh `--new` session'lar `sessions/<pid>.json` YAZMIYOR → guard DUP. Fix: proc-scan. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE**: yeni storage **lazy-checkpoint** (ara ara yazar). Kill'de flush için ~2s gerek → `SIGTERM`→`SIGKILL` **<2s = konuşma TRUNCATE**. **Kural: hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sweep 8s grace). Temiz reboot/shutdown 90s grace verir → flush eder (güvenli); **ani kapanma/sert-OOM = son mesajlar gider** (iş git'te güvende, sadece transkript). [[claude-2183-conversation-truncation]] [[reboot-recovery]]
- **1M context**: `[1m]` suffix → beta header. **Opus + Sonnet [1m] KAPALI** (token kısıtı). [[model-1m-context]]
- **spawn env-leak → transcript kapanır**: `co` (ya da herhangi bir claude session) kendi Bash tool'undan `rc`/`guard`/`handover`/`web` çalıştırırsa, spawn edilen YENİ session `CLAUDE_CODE_CHILD_SESSION` vb. miras alır → kendini "child" sanıp **transcript kaydını sessizce kapatır** (TUI uyarısı: "Transcript saving is off"). `spawn.py` artık `CLAUDE*` env'i filtreliyor (2026-08-24 fix, tüm spawn-yolları kapsar). [[spawn-env-leak-disables-transcript]]
- **spawn zombie-child → uzun yaşayan `py/cops web`'de spawn sessizce başarısız olmaya başlar**: `spawn_session()`'ın açtığı `gnome-terminal` client'ı `.wait()` edilmezse zombie kalır; saatlerce ayakta kalan web server process'inde biriktikçe yeni pencere açma güvenilirliği düşer (taze restart hep düzeltir — 2026-08-25'te "sase gelmedi"/"rustrino handover kapattı ama açmadı" gibi tuhaflıkların KÖK SEBEBİ buydu, kilitli-ekran DEĞİLDİ). Fix: spawn sonrası proc'u ayrı bir daemon thread'de `.wait()` ile reap et (global SIGCHLD=SIG_IGN YAPMA — `layout`'un `subprocess.run` çağrılarını bozar). [[spawn-zombie-child-degrades-web-server]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Model (`~/.claude/claudeops/models.tsv`)

- **2026-08-24: Claude 5 ailesine geçildi + split GERİ alındı (kullanıcı kararı).** Tüm 27 aktif isim şu an **`claude-sonnet-5`** (opus-5 migration anında 529/Overloaded veriyordu + kullanıcı "şimdilik sonnet olsun" dedi — basit+ucuz tutuldu). Coding/Paper ayrımı isim-gruplaması olarak hâlâ anlamlı (ne iş yaptığını gösterir), model kolonunda artık FARK YOK:
  - **Coding 15** (hc hcr mo vrk oiso rustrino trino anomaly evolvi done mamut hof iggy vc asp) — **trino+oiso** 2026-08-24'te eklendi. trino: cwd `.../monitoring/ulak-presto-connectors` (Presto/Trino Quickwit connector — rustrino'dan AYRI proje, isim benzerliği tesadüf); kullanıcı elle açmıştı (`trino20260823`), roster'a temiz base-isimle kaydedildi, proc canlıyken kill/respawn EDİLMEDİ (Session.base regex tarih-suffix'i otomatik indirger, hc58→hc gibi). oiso: cwd `tmp/offlinek8siso` (offline k8s ISO tool), o an çalışmıyordu → sadece register edildi, spawn edilmedi.
  - **Paper 13** (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot line) — **line** 2026-08-24 eklendi: cwd `.../backups/llm/NN_lineart_cuneiform_vlm` (asp'la aynı `llm/` klasörü altında), o an çalışmıyordu → sadece register edildi.
  - İstenirse tekrar split (paper→opus-5): `sed -i 's/claude-sonnet-5/claude-opus-5/' ~/.claude/claudeops/{models,roster}.tsv` ile paper isimlerini elle geri çevir (opus-5 tekrar dolu/overloaded olabilir — önce tek isimle test et).
- **co**(self) + **cops**(self, 2026-08-25 roster'a kaydedildi) + **ulaksec** models.tsv'de AKTİF (guard ayakta tutsun — istenen). **HO_EXCLUDE isim-listesi 2026-08-25'te KALDIRILDI** (kullanıcı kararı: "hariç tutulma kısımlarını silelim, UI'ye checkbox") — toplu handover/rc'de hedef seçimi artık web panel checkbox'larıyla; tek kalan koruma **process-bazlı self-koruma** (`ancestor_pids()`: komutun içinden çalıştığı claude session'ı isimle bile hedeflense atlanır, py handover+rc; bash'te `filter_not_self`). ulaksec'e yine elle dokunma (güvenlik kuralı) — artık kod değil, dikkat koruyor. [[co-ulaksec-guard-yes-ho-no]]
- **EMEKLİ:** rr gedikvm gedikido kulturiot. **KAPALI:** mecdtfl carla. **`py/cops close <name>`** = kill (proc+terminal) + models.tsv yorumla → guard AÇMAZ (guard çıktısı `⊘ kapalı: ...`). Açmak: models.tsv'de `#` elle kaldır.

## Fleet kontrolü — artık MANUEL (2026-08-24 karar)

**Guard cron ŞU AN DEVRE DIŞI** (crontab'da 3 satır da `#`'lı — bilerek, OOM'dan değil, kullanıcı tercihinden: "hepsini açmam, gerektiğinde web'den başlatırım"). Cron açık olsaydı her dakika TÜM roster'ı (27 isim) eksik görüp hepsini spawn ederdi — bu artık istenmiyor. **Tekrar açma:** `crontab -e`, ilgili 3 satırın başındaki `#`'ları kaldır (yorum satırları hariç, sadece komut satırı: `* * * * * .../py/cops guard ...`).

**`py/cops web [--port 8765] [--tunnel]`** — yerel kontrol paneli. **2026-08-25 UI revizyonu:** TAB'lı yapı (Çalışanlar / Kayıtlı / Devre dışı / Emekli / Layout) + satır **checkbox'ları** + tablo üstünde **toplu işlem** butonları (handover / durdur / devre dışı bırak / emekli et — seçililere sırayla uygulanır, legend'la açıklamalı; "close" adı kafa karıştırdığı için UI'de "devre dışı bırak" oldu, API/CLI adı `close` kaldı). Çalışanlar tablosunda **ho? kolonu** (needs_ho, 30s cache) + "needs-ho seç" butonu. Başlat seçenekleri (devam/sıfırla/yeni chat, model/permission-mode/effort) satır-içi "seçenekler ▾"de; "devral" kayıtsız satırlarda. Ayrıca **layout** (`/api/layout`, pin/group/claude-only/dry-run) panelde — kilitli-ekran pre-flight OTOMATİK (`_screen_locked`, TODO kapandı), wmctrl/xdotool eksikse apt komutu önerir (sudo istediği için oto kurulmaz). Token-gated (`~/.claude/claudeops/web.token`) — `--tunnel` ile `cloudflared` quick-tunnel (eksikse `~/.local/bin`'e OTO indirilir, Linux only). Foreground — Ctrl-C ile server+tünel kapanır; arka planda: `nohup ... & disown`.
**2026-08-24: repo PUBLIC (MIT LICENSE) — `github.com/mfyuce/claudeops`.** Açık-kaynak öncesi içerik taraması yapıldı (TOBEDECIDED Kapatılmış #5): secret/IP yok, roster/models/token zaten repo dışında (`~/.claude/claudeops/`).
⚠ Web'in Stop'u ve `py/cops kill`/`rc --kill-first` artık **parent bash'i de öldürür** (`kill_session_and_parent`, TODO-b kök-sebep fix, 2026-08-24) — eskiden sadece claude proc'u ölür, `exec bash`'e düşen terminal orphan kalırdı.

## Handover (3-fazlı)

**İsimler base-name (suffix YOK, 2026-06-26):** hc, co, mo... Handover = aynı isimle kill+respawn (bump yok).

```
# Faz 1  (⚠ TÜM fleet'e AYNI ANDA = sunucu rate-limit → blank-TUI hang; py/cops batch'ler [[mass-faz1-ratelimit-stuck]])
py/cops handover [--dry-run]   # tüm fleet (self otomatik korunur; isim-bazlı hariç-tutma kalktı), aynı isimle wrap-up

# Faz 2 — ⚠ Faz1 SAĞLIKLI? (RFH var, 503/529 yok) → değilse DUR, kullanıcı onayı şart.
# ⚠ py/cops rc KULLAN (bash ./claudeops rc cwd'yi CANLI session'dan alır → yanlış cwd; py roster'dan alır [[bridge-batch-spawn-ratelimit]]).
# TEK-TEK; config doğrula: python3 -c "import json;json.load(open('$HOME/.claude.json'))"
# İsimler base-name (suffix yok); --new → fresh, aynı isimle açılır (remote'da kaymaz):
py/cops rc hc hcr mo vrk oiso rustrino trino anomaly evolvi done mamut hof iggy vc asp \
  --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one
py/cops rc aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot line \
  --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one
# ⚠ 2026-08-24: split kalktı, ikisi de sonnet-5 (opus-5 o an overloaded'dı) — opus'a dönmek
# istersen ikinci komutta --model='claude-opus-5' yaz (önce tek isimle test et, TOBEDECIDED Kapatılmış #7).
# ⚠ Bridge rate-limit: 25 session aynı anda → 0 TCP. 4'er batch + 20s ara, TCP doğrula [[bridge-batch-spawn-ratelimit]].

# Faz 3 — 27 session → önce `claudeops desktops 8`. Faz1-respawn sonrası 2× çalıştır (1. pass settle olmaz). Doğrula `xwininfo` (wmctrl 2× YALAN).
./claudeops layout grid 4 --claude-only --pin=co,rustrino,anomaly,iggy --group=hc,hcr,evolvi --group=vc,vrk
```
⚠ `[1m]` **tek tırnak ŞART** (shell glob). Target **SPACE-separated** (virgül parse bug). `--group=` base-name.
⚠ **Faz2 `--prompt` VERME → session'lar boş/idle başlar** (2026-06-24, [[faz2-new-session-devam]]).
⚠ **Faz3 ÖNCESİ** `loginctl show-session <id> -p LockedHint`=no doğrula — kilitliyse layout BOZUK, DUR [[layout-needs-unlocked-screen]].
**Skip kriteri:** RFH var + son RFH'den sonra yeni istek yok + repo temiz+pushed (github+gitlab).
Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. Terminal: gnome-terminal hard-coded. `rc --kill-first` permission modal keser.
Target virgül parse yok (SPACE kullan). Layout orphan terminal slot işgal. Tam liste: TODO.md.

## Meta

`DONE.md` = CHANGELOG. Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE; TOBEDECIDED karar → TODO.

## READY FOR HANDOVER (2026-08-25, güncellenmiş — aynı gün ikinci tur)

**DURUM:** Fleet küçük, manuel kontrol altında (guard cron kasıtlı devre dışı). Şu an çalışanlar: `line`, `sase`, `trino`, `rustrino20260825_1`, `cops20260824` (bu session, roster dışı/kayıtsız). Config VALID, DUP yok. Web paneli (`py/cops web`, port 8765) + cloudflared tüneli ayakta ve doğrulandı. **Roster'da rustrino için 4 satır birikti** (`rustrino`, `#rustrino20260824` emekli, `rustrino20260825` durmuş, `rustrino20260825_1` çalışıyor) — bu session'daki test döngülerinden çöp, kullanıcıya sorup temizlenebilir.

**Bu session'da olan (çok uzun, yoğun bir debug + özellik turu — hepsi commit+push'lu, DONE.md'de detay):**
1. **KÖK SEBEP bulundu+düzeltildi:** `spawn_session()` açtığı gnome-terminal client'ını hiç reap etmiyordu → uzun yaşayan `py/cops web` process'inde zombie birikip yeni pencere açmayı SESSİZCE bozuyordu (kilitli-ekran teorisi kovalandı, YANLIŞ çıktı, geri alındı). Fix: arka plan thread'de `.wait()`.
2. `_start`/`_new_chat`/`_handover`/`_adopt` artık spawn sonrası proc gerçekten göründü mü diye doğruluyor (önceden sessizce "başarılı" yalanı söylüyordu).
3. Yeni **"devral" (adopt)** özelliği: claudeops'un açmadığı (bare/kayıtsız) session'ları remote-control ekleyip kaydetme.
4. **"cops" bulmacası çözüldü:** uzun-yaşayan daemon'dan spawn ara sıra tutmuyordu, ama BU Bash tool'dan (kısa-ömürlü CLI çağrısı) yapılan spawn HEP güvenilirdi — kullanıcı önerisiyle ("başka bir CLI başka bir CLI açabiliyor") pratik desen: güvenilmez uzun-yaşayan daemon yerine kısa-ömürlü CLI'dan tetikle. Bu arada kilit-ekran teorisi bir kez daha (kesin olarak) yanlışlandı: kilitliyken yapılan bir CLI-spawn sorunsuz çalıştı.
5. Kilit-ekran ön-kontrolü `_start`/`_new_chat`/`_handover`/`_adopt`'tan kaldırıldı (sadece `_run_layout`'ta kaldı, orada hâlâ geçerli — Mutter pencere-TAŞIMA sorunu, pencere-AÇMA değil).
6. **`layout.py`'de gerçek, muhtemelen aylardır var olan bir bug bulundu+düzeltildi:** pencere-eşleme regex'i (`[a-z]+\d+$`) çıplak isimleri (trino, co, hc...) ve alt-çizgili isimleri (`rustrino20260825_1`) HİÇ yakalamıyordu (suffix sistemi 2026-06-28'de kaldırıldığından beri roster'ın ÇOĞU böyle) — artık `known_names` ile TAM eşleşme yapıyor.
7. **Backend API hata mesajları artık gerçekten iki dilli:** 37 hata mesajı hardcoded Türkçe idi, panel EN'e çevrilse bile hep TR dönüyordu — `ERR` sözlüğü + `lang` parametresi ile düzeltildi.
8. README'ler (EN+TR, root+py/) güncellendi: devral/adopt, cwd tıkla-genişlet, kilit-ekranın ARTIK engel olmadığı bilgisi.

**AÇIK (küçük, acil değil):** TODO.md'de not edildi — uzun-yaşayan web daemon zombie-fix'ten sonra bile teorik olarak zamanla tekrar güvenilmezleşebilir (garantisi yok, sadece azaltıldı); kalıcı çözüm (periyodik oto-restart ya da fork-per-spawn) düşünülebilir ama acil değil, pratik fallback (kısa-ömürlü CLI'dan spawn) yeterli.

**Yeni session yapacaklar:**
1. MEMORY.md oku — özellikle [[spawn-zombie-child-degrades-web-server]] + [[layout-needs-unlocked-screen]] (hâlâ geçerli ama SADECE `layout` için, genel spawn için değil — karıştırma).
2. Roster'daki rustrino çöp satırlarını kullanıcıya sorup temizle (hangisi kalıcı isim olsun).
3. Guard cron'u hâlâ sen açma — kullanıcı açıkça istemedikçe.
4. Bu session (`cops20260824`) kullanıcı tarafından kapatılıp yeni bir session'la devam edilecek — bu normal, panik yok, kill'i BEN tetiklemedim (self-kill riski, kullanıcı elle yapacak).

READY FOR HANDOVER
