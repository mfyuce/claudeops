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
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Model (`~/.claude/claudeops/models.tsv`)

- **2026-08-24: Claude 5 ailesine geçildi + split GERİ alındı (kullanıcı kararı).** Tüm 27 aktif isim şu an **`claude-sonnet-5`** (opus-5 migration anında 529/Overloaded veriyordu + kullanıcı "şimdilik sonnet olsun" dedi — basit+ucuz tutuldu). Coding/Paper ayrımı isim-gruplaması olarak hâlâ anlamlı (ne iş yaptığını gösterir), model kolonunda artık FARK YOK:
  - **Coding 15** (hc hcr mo vrk oiso rustrino trino anomaly evolvi done mamut hof iggy vc asp) — **trino+oiso** 2026-08-24'te eklendi. trino: cwd `.../monitoring/ulak-presto-connectors` (Presto/Trino Quickwit connector — rustrino'dan AYRI proje, isim benzerliği tesadüf); kullanıcı elle açmıştı (`trino20260823`), roster'a temiz base-isimle kaydedildi, proc canlıyken kill/respawn EDİLMEDİ (Session.base regex tarih-suffix'i otomatik indirger, hc58→hc gibi). oiso: cwd `tmp/offlinek8siso` (offline k8s ISO tool), o an çalışmıyordu → sadece register edildi, spawn edilmedi.
  - **Paper 13** (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot line) — **line** 2026-08-24 eklendi: cwd `.../backups/llm/NN_lineart_cuneiform_vlm` (asp'la aynı `llm/` klasörü altında), o an çalışmıyordu → sadece register edildi.
  - İstenirse tekrar split (paper→opus-5): `sed -i 's/claude-sonnet-5/claude-opus-5/' ~/.claude/claudeops/{models,roster}.tsv` ile paper isimlerini elle geri çevir (opus-5 tekrar dolu/overloaded olabilir — önce tek isimle test et).
- **co**(self) + **ulaksec** models.tsv'de AKTİF (guard ayakta tutsun — istenen) ama **handover YAPMAZ** (HO_EXCLUDE_BASES={co,ulaksec}; py+bash handover ikisini base-name ile exclude eder). Suffix kalktığı için eski "guard die → suffix bump" sorunu YOK. [[co-ulaksec-guard-yes-ho-no]]
- **EMEKLİ:** rr gedikvm gedikido kulturiot. **KAPALI:** mecdtfl carla. **`py/cops close <name>`** = kill (proc+terminal) + models.tsv yorumla → guard AÇMAZ (guard çıktısı `⊘ kapalı: ...`). Açmak: models.tsv'de `#` elle kaldır.

## Fleet kontrolü — artık MANUEL (2026-08-24 karar)

**Guard cron ŞU AN DEVRE DIŞI** (crontab'da 3 satır da `#`'lı — bilerek, OOM'dan değil, kullanıcı tercihinden: "hepsini açmam, gerektiğinde web'den başlatırım"). Cron açık olsaydı her dakika TÜM roster'ı (27 isim) eksik görüp hepsini spawn ederdi — bu artık istenmiyor. **Tekrar açma:** `crontab -e`, ilgili 3 satırın başındaki `#`'ları kaldır (yorum satırları hariç, sadece komut satırı: `* * * * * .../py/cops guard ...`).

**`py/cops web [--port 8765] [--tunnel]`** — yerel kontrol paneli. Roster'ın TAMAMINI (aktif/kapalı/emekli) tablo halinde gösterir, mass-start YOK, her isim için TEK panel: devam ettir (varsayılan) / sıfırla (--new) / ayrı yeni chat aç (oto tarih-isimli, model/permission-mode/effort seçenekli) — artı "emekli et"/"tekrar işe al". Ayrıca **layout** (`/api/layout`, pin/group/claude-only/dry-run) panelde — kilitli-ekran pre-flight OTOMATİK (`_screen_locked`, TODO kapandı), wmctrl/xdotool eksikse apt komutu önerir (sudo istediği için oto kurulmaz). Token-gated (`~/.claude/claudeops/web.token`) — `--tunnel` ile `cloudflared` quick-tunnel (eksikse `~/.local/bin`'e OTO indirilir, Linux only). Foreground — Ctrl-C ile server+tünel kapanır; arka planda: `nohup ... & disown`.
**2026-08-24: repo PUBLIC (MIT LICENSE) — `github.com/mfyuce/claudeops`.** Açık-kaynak öncesi içerik taraması yapıldı (TOBEDECIDED Kapatılmış #5): secret/IP yok, roster/models/token zaten repo dışında (`~/.claude/claudeops/`).
⚠ Web'in Stop'u ve `py/cops kill`/`rc --kill-first` artık **parent bash'i de öldürür** (`kill_session_and_parent`, TODO-b kök-sebep fix, 2026-08-24) — eskiden sadece claude proc'u ölür, `exec bash`'e düşen terminal orphan kalırdı.

## Handover (3-fazlı)

**İsimler base-name (suffix YOK, 2026-06-26):** hc, co, mo... Handover = aynı isimle kill+respawn (bump yok).

```
# Faz 1  (⚠ TÜM fleet'e AYNI ANDA = sunucu rate-limit → blank-TUI hang; py/cops batch'ler [[mass-faz1-ratelimit-stuck]])
py/cops handover [--dry-run]   # tüm fleet (co/ulaksec otomatik hariç), aynı isimle wrap-up

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

## READY FOR HANDOVER (2026-08-24)

**DURUM:** Fleet **1/30 çalışıyor — KASITLI** (guard cron devre dışı, mass-auto-start artık istenmiyor; tek çalışan **trino**). Bu session (`cops20260824`) kendisi fleet'in parçası DEĞİL — kullanıcı ad-hoc/manuel açmıştı ("claude kullanmıyordum ne zamandir"). Config VALID, DUP yok. Model: **tüm 30 isim `claude-sonnet-5`** (split kalktı). `~/.cache/huggingface` 29G KORU (dokunulmadı).

**Bu session (2 aylık boşluktan sonra ilk dönüş):** kullanıcı "remote connection'lar açık kalıyordu, proje güncellensin mi" diye sordu → CLI 2.1.169→**2.1.241** atlamış. Bulgular + yapılanlar DONE.md'nin en üst girişinde (2026-08-24). Özet: RC-bridge "açık kalma" bug'ı **upstream'de düzeldi** (kanıtlı); asıl "dert" OOM değil **guard cron'un sessizce devre dışı kalmasıydı**. Kullanıcı fleet'i **web panelden manuel** kontrol etmek istedi → `py/cops web [--tunnel]` yazıldı (bkz. "Fleet kontrolü — artık MANUEL" bölümü yukarıda). Claude 5'e geçildi (sonnet-5, opus-5 migration anında overloaded'dı → ertelendi). `kill_session_and_parent` ile TODO-b (orphan terminal) kök-sebepten kapatıldı.

**Yeni session yapacaklar:**
1. MEMORY.md oku — özellikle [[fleet-manual-control-2026-08]] + [[cli-2241-rc-bridge-fixed]] + eski [[claude-2183-conversation-truncation]] + [[mass-faz1-ratelimit-stuck]] + [[layout-needs-unlocked-screen]] (hâlâ geçerli, CLI değişikliğiyle test edilmedi).
2. **Guard cron'u sen açma** — kullanıcı açıkça istemedikçe (`crontab -e`, 3 satırdan `#` kaldır). Fleet'i toplu başlatma isteği gelmedikçe hiçbir session spawn etme; `py/cops web` zaten var, kullanıcıya URL'i hatırlat (`py/cops web --print-token` + `--tunnel`).
3. Handover ("ho") istenirse: **eski 3-fazlı prosedür artık muhtemelen gereksiz ölçüde ağır** — fleet zaten 0'dan başlıyor, "Faz 2 respawn" ile "web'den tek tek başlat" aynı şeyi yapıyor. Kullanıcıya sor: klasik toplu-ho mu, yoksa web-panelden kademeli mi?
4. opus-5 tekrar denenebilir mi diye kullanıcıya sormadan **models.tsv'yi opus'a çevirme** — 529 o an geçiciydi ama tekrar dolabilir, önce tek isimle test et.

READY FOR HANDOVER
