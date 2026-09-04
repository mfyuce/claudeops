# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar (silinir mi: TOBEDECIDED.md #12).

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude KILL=TRUNCATE riski**: lazy-checkpoint storage → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sert kill = son mesajlar gider, iş git'te güvende). [[claude-2183-conversation-truncation]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA hata verir → resume'a mutlaka `--prompt` ver (`--new` OLMADAN). [[resume-deferred-tool-marker]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env filtrelenir (yoksa transcript kapanır). gnome-terminal flake → oto-retry+fallback, windowless'i **"pencere aç"**la düzelt. "restart hâlâ olmuyor" → **gt-restart** (Tanı sekmesi, web'den bağımsız). [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]]
- **`service.py`'nin `WEB_UNIT_TEMPLATE`'ini düzenlersen `bash -ic '...'` ExecStart'ı, `KillMode=process`, ve tunnel unit'inin `Wants=` (`Requires=` DEĞİL) satırını BOZMA** — üçü de canlı hasar fix'i (PATH kaybı / restart altındaki tmux'u öldürme / tunnel URL rotasyonu), tam gerekçe modülün docstring'inde. `run-tunnel.sh` paralel-deploy env override'ları destekler [[tunnel-flag-shares-live-log-file]]. Tunnel URL rastgele döner (named tunnel kurulu değil) + ntfy push bu telefona ulaşmıyor — biri "ulaşamadım" derse `tunnel_url.txt`'ten güncel URL'i doğrudan ver, ntfy'ye güvenme. [[tunnel-no-named-tunnel-autoupdate-rotates-url]]
- **oomd TÜM oturumu öldürebilir** (sadece fleet'in cgroup'unu değil) — kurtarma `py/cops service watchdog` (root-seviyeli, oturumdan bağımsız timer). [[oomd-cgroup-kill]]
- **`web.py`'nin `_serve_static()`'i `index.html`'i HER ZAMAN `Cache-Control: no-cache`, `/assets/*`'i (Vite hash'li) `immutable` göndermeli** — aksi halde bir redeploy sonrası tarayıcıda kalan eski `index.html`, artık silinmiş eski-hash'li JS/CSS'i 404'lar, sayfa hiç açılmaz (canlı bulundu 2026-09-02, kullanıcı: "ana sayfa açılırken hata var, tüm sayfa gizleniyor").
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`** (2026-08-24 Claude 5 geçişi; opus split geri alınmış durumda).
- **İsimler base-name** (suffix yok). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops`. Panel eşlemesi önce TAM isim, sonra base — tarih-isimli satırlar kendi satırında görünür, görünmez canlı proc imkansız.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-bazlı hariç tutma YOK, seçim panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al".
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`|`codex`|`shell`, yoksa/eskiyse `"claude"`). `shell` = düz interaktif bash (sudo/TTY işleri için — panel terminali gerçek PTY). Provider mimarisi `py/claudeops/providers/`: yeni backend = yeni dosya, dallanma yok (adaylar TODO.md'de).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]].
- **`py/cops service install|status|uninstall|notify|watchdog`** — web+tunnel artık systemd `--user` ile KALICI (logout/reboot'ta otomatik, `Restart=on-failure`); `notify` = tunnel URL değişince ntfy.sh push'u; `watchdog` = yukarıdaki oomd-tüm-oturum senaryosunu kurtarır (root, `sudo` ister). Detay: `py/README*.md`.
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `kill` / `rc --kill-first`: tmux-backed'de ad-bazlı `tmux kill-session` (PID-ancestry YASAK — paylaşımlı server riski) + `find_outer_bash_pids()` ile session ölmeden ÖNCE yakalanan outer-pencere PID'lerini de kapatır (2026-09-01 fix, DONE.md).

## Handover (Faz 1 ARTIK kill/respawn YAPMIYOR — 2026-09-04)

- **Faz 1 = CANLI mesaj gönderimi, pencere/proc'a hiç dokunmaz.** `py/cops handover [--dry-run]` wrap-up mesajını `tmux_send_keys` ile ÇALIŞAN session'a enjekte eder (kill/respawn/pencere kapat-aç YOK — canlı doğrulandı, [[handover-live-injection-no-kill]]). Batch'li throttle hâlâ geçerli (mass aynı anda = rate-limit [[mass-faz1-ratelimit-stuck]]); self otomatik atlanır; konuşması olmayan (`shell`) ve boş/idle (`needs_ho()`) session'lar otomatik skip. **Taze reboot (≤30dk) → DUR + uyar**, `--force` ile baypas ([[reboot-no-handover]]).
- **Faz 2/3 artık Faz 1'in otomatik/örtük devamı DEĞİL** — context'i ne zaman sıfırlayıp (fresh session) ne zaman pencere düzenleyeceğine (layout) kullanıcı kendisi, ayrı ayrı karar verir, [[handover-live-injection-no-kill]].
- **Faz 2 (istenirse, tek bir isim için):** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --permission-mode=auto --one-by-one` (bash rc DEĞİL; `--model`/`--effort` VERME — models.tsv/Ayarlar zincirine düşer, [[handover-effort-high-not-max]]). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3 (istenirse):** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` (bash, bkz. TOBEDECIDED.md #12) — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan).
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz (X11 gerekli). gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE, bash'e özel). Bulk handover nadir BrokenPipe izi bırakabilir (kök gedik kapatıldı + diag_log var) — tekrarlarsa Tanı sekmesine bak. Tam liste: TODO.md.

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE.

## READY FOR HANDOVER (2026-09-04)

Layout'un çoklu-monitor "HDMI sol alta yığılma" bug'ı (2026-08-28'den beri açık) GERÇEKTEN düzeldi + canlı 10-pencerelik fleet'te doğrulandı (b2dcfd7) — kök sebep `_get_screen`'in birleşik sanal-masaüstü boyutunu tek monitörün Y-offset'iyle karıştırması; ayrıca `apply_layout`'a bash'teki retry/read-back/un-maximize mantığı port edildi. TBD#12'nin bash-silme engellerinden biri buydu, artık kalktı (kalan: gerçek bir Faz 3 pin/group akışıyla canlı deneme). Detay: DONE.md "layout çoklu-monitor pile-up fix".

Kullanıcı iki yeni açık mimari soru sordu, TOBEDECIDED.md'ye #15/#16 olarak kaydedildi (henüz tasarıma geçilmedi): çoklu-CLI worker/checker/decider + MCP-backed paylaşımlı queue (literatür araştırıldı: blackboard mimarisi, MetaGPT, Anthropic evaluator-optimizer, AutoGen/CrewAI — hazır ürün yok), ve aynı web UI'ın birden fazla makinede kullanımı.

Fleet'e 4 yeni proje kaydedildi (repo-dışı roster.tsv/models.tsv): `hittite`/`egyptian`/`luwian`/`egycursive` (ancient-script-pipeline ailesi, `asp`/`line`/`urartian` ile aynı desen) — **BAŞLATILMADI**, kullanıcı onayı bekleniyor (manuel fleet kontrolü kuralı).

**Repo:** clean, github+gitlab senkron (bu commit dahil).

READY FOR HANDOVER
