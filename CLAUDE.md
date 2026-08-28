# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool; **`./claudeops`** (bash) = layout + eski komutlar.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. Aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang).
- **claude 2.1.169**: fresh `--new` session'lar `sessions/<pid>.json` yazmıyor → keşif proc-scan'le. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE**: lazy-checkpoint storage; kill'de flush için zaman gerek → **hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL**. Ani kapanma/sert-OOM = son mesajlar gider (iş git'te güvende, sadece transkript). [[claude-2183-conversation-truncation]] [[reboot-recovery]]
- **claude resume "deferred tool marker"**: promptsuz `--resume` bazen ANINDA "No deferred tool marker found" ile çıkar → resume'a mutlaka `--prompt` ver (`py/cops rc <name> --prompt='devam'`, `--new` OLMADAN). [[resume-deferred-tool-marker]]
- **1M context**: `[1m]` suffix → beta header; şu an KAPALI (token kısıtı). [[model-1m-context]]
- **spawn güvenilirliği**: CLAUDE*/GEMINI*/ANTIGRAVITY* env filtrelenir (yoksa transcript kapanır). gnome-terminal ara-sıra flake → spawn.py retry+oto-fallback (windowless'i **"pencere aç"** ile düzelt — GİZLER, ÇÖZMEZ). **15dk'da 2+ fallback / "web restart ettim hâlâ oluyor"** → bozuk taraf gnome-terminal-server'ın KENDİSİ (web'den bağımsız) → Tanı'daki **gt-restart** gerekli+yeterli (2026-08-28 iki ayrı canlı vakayla ayrım netleşti). [[spawn-env-leak-disables-transcript]] [[spawn-zombie-child-degrades-web-server]] [[diag-tab-feature]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Roster / model (`~/.claude/claudeops/{roster,models}.tsv` — repo DIŞI, kaynak-of-truth)

- Tüm isimler **`claude-sonnet-5`** (2026-08-24 Claude 5 geçişi; opus split geri alındı — istenirse `sed -i 's/claude-sonnet-5/claude-opus-5/'` ile grup bazında geri, önce tek isimle test).
- **İsimler base-name** (suffix yok). `Session.base` tarih+`_N` suffix'lerini indirger: `cops20260824_1`→`cops`. Panel eşlemesi önce TAM isim, sonra base — tarih-isimli satırlar kendi satırında görünür, görünmez canlı proc imkansız.
- **co + cops** (self) + **ulaksec** aktif (guard ayakta tutsun). İsim-listesiyle hariç tutma YOK — toplu işlem hedefi panel checkbox'larıyla; tek koruma process-bazlı self-koruma (`ancestor_pids()` py handover+rc; bash `filter_not_self`). [[co-ulaksec-guard-yes-ho-no]]
- Kapalı/emekli satırlar `#`'lı. `py/cops close <name>` = kill + models.tsv yorumla; geri: panel "tekrar işe al". **Temizlik bekliyor:** tarih-isimli çöp satırlar (rustrino*/line*/trino*/sase* tarihli, TODO.md'de detay) — kullanıcıya sorup birleştir/sil.
- roster.tsv'nin opsiyonel **4. kolonu = `cli`** (`claude`|`agy`, yoksa/eskiyse `"claude"`).

## Fleet kontrolü — MANUEL (2026-08-24 karar)

- **Guard cron KASITLI kapalı.** Kullanıcı `py/cops web`'den tek tek başlatıyor — **sen açma**, sormadan toplu spawn YAPMA. [[feedback-manual-fleet-control]]
- **`py/cops web [--port 8765] [--tunnel]`** — kontrol paneli; tam sekme/özellik listesi `py/README*.md` + [[diag-tab-feature]]. CLI seçici çoklu-backend (claude/agy, `providers/` registry — 3. backend eklemek yeni dosya, kod dallanması değil).
- **Repo PUBLIC** (MIT, github + gitlab mirror) — roster/models/token repo dışında. Kullanıcı: "dünyaya açığız, DONE/TODO/changelog önemli" → kayıtları özenli tut.
- Web Stop / `kill` / `rc --kill-first`: tmux-backed'de ad-bazlı `tmux kill-session` (PID-ancestry YASAK — paylaşımlı server riski). Pencere kapatmama açık bug'ı: TODO.md.

## Handover (3-fazlı)

- **Faz 1:** `py/cops handover [--dry-run]` — batch'li (mass aynı anda = rate-limit → blank-TUI [[mass-faz1-ratelimit-stuck]]); self (komutun atası) otomatik atlanır.
- **Faz 2:** Faz1 sağlıksızsa (503/529) DUR, kullanıcı onayı şart. `py/cops rc <isimler SPACE'li> --new --kill-first --model='claude-sonnet-5' --permission-mode=auto --effort=max --one-by-one` (bash rc DEĞİL — py cwd'yi roster'dan alır). `--prompt` VERME (boş başlasınlar [[faz2-new-session-devam]]). Config doğrula: `python3 -c "import json;json.load(open('$HOME/.claude.json'))"`. Bridge rate-limit: 4'er batch + 20s [[bridge-batch-spawn-ratelimit]].
- **Faz 3:** ÖNCE `loginctl show-session <id> -p LockedHint`=no doğrula [[layout-needs-unlocked-screen]]. `./claudeops layout grid 4 --claude-only --pin=... --group=...` — 2× çalıştır, `xwininfo` ile doğrula (wmctrl 2× yalan). `[1m]` tek tırnak; target SPACE-separated.
- **Skip kriteri:** RFH var + sonrasında yeni istek yok + repo temiz+pushed (github+gitlab).
- Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. gnome-terminal hard-coded. `rc --kill-first` permission modal keser. Target virgül parse yok (SPACE). Tam liste: TODO.md (öne çıkanlar: tmux-backed "stop" penceresi kapatmıyor; terminal görünümünde kozmetik taşma).

## Meta

`DONE.md` = CHANGELOG. `TOBEDECIDED.md` = açık mimari sorular (karar verildikçe "Kapatılmış"a taşınır, silinmez). Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE.

## READY FOR HANDOVER (2026-08-28 akşam)

Repo temiz, HEAD öncesi=`b47e26e`, github+gitlab senkron. Kod değişikliği yok bu session'da — canlı teşhis: "web'i restart ettim hâlâ windowless" şikayetinin kök sebebi gnome-terminal-server'ın kalıcı D-Bus bozulmasıydı (web'den bağımsız); kullanıcı gt-restart yaptı, canlı doğrulandı, cloudflared etkilenmedi (detay DONE.md "2026-08-28 (3)"; yukarıdaki spawn-güvenilirliği notu bu ayrımla düzeltildi).

Fleet şu an windowless (gt-restart yan etkisi, tmux'ta sağlam) — yeni session'ın ilk işi panelden "pencere aç". Yeni açık iş kalemi yok (TODO.md güncel). Ayrıca: MEMORY.md oku, guard cron'u açma, roster'daki tarih-isimli çöp satırlar hâlâ temizlik bekliyor.

READY FOR HANDOVER
