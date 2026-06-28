# claudeops — Claude Context

Açık Claude CLI session'larını toplu yönet. **`py/cops`** = canlı Python tool (guard cron + handover bunu kullanır); **`./claudeops`** (bash) = layout + eski komutlar.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. `-n` display, `--remote-control` RC bridge; aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang). `--claude-only`: sadece aktif RC proc'larını tile'la.
- **claude 2.1.169**: fresh `--new` session'lar `sessions/<pid>.json` YAZMIYOR → guard DUP. Fix: proc-scan. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE**: yeni storage **lazy-checkpoint** (ara ara yazar). Kill'de flush için ~2s gerek → `SIGTERM`→`SIGKILL` **<2s = konuşma TRUNCATE**. **Kural: hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL** (sweep 8s grace). Temiz reboot/shutdown 90s grace verir → flush eder (güvenli); **ani kapanma/sert-OOM = son mesajlar gider** (iş git'te güvende, sadece transkript). [[claude-2183-conversation-truncation]] [[reboot-recovery]]
- **1M context**: `[1m]` suffix → beta header. **Opus + Sonnet [1m] KAPALI** (token kısıtı). [[model-1m-context]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Model (`~/.claude/claudeops/models.tsv`)

- **Coding 13** (hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc asp) → `claude-sonnet-4-6`
- **Paper 12** (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot) → `claude-opus-4-8`
- **co**(self) + **ulaksec** models.tsv'de AKTİF (guard ayakta tutsun — istenen) ama **handover YAPMAZ** (HO_EXCLUDE_BASES={co,ulaksec}; py+bash handover ikisini base-name ile exclude eder). Suffix kalktığı için eski "guard die → suffix bump" sorunu YOK. [[co-ulaksec-guard-yes-ho-no]]
- **EMEKLİ:** rr gedikvm gedikido kulturiot. **KAPALI:** mecdtfl carla. **`py/cops close <name>`** = kill (proc+terminal) + models.tsv yorumla → guard AÇMAZ (guard çıktısı `⊘ kapalı: ...`). Açmak: models.tsv'de `#` elle kaldır.

## Handover (3-fazlı)

**İsimler base-name (suffix YOK, 2026-06-26):** hc, co, mo... Handover = aynı isimle kill+respawn (bump yok).

```
# Faz 1  (⚠ TÜM fleet'e AYNI ANDA = sunucu rate-limit → blank-TUI hang; py/cops batch'ler [[mass-faz1-ratelimit-stuck]])
py/cops handover [--dry-run]   # tüm fleet (co/ulaksec otomatik hariç), aynı isimle wrap-up

# Faz 2 — ⚠ Faz1 SAĞLIKLI? (RFH var, 503/529 yok) → değilse DUR, kullanıcı onayı şart.
# ⚠ py/cops rc KULLAN (bash ./claudeops rc cwd'yi CANLI session'dan alır → yanlış cwd; py roster'dan alır [[bridge-batch-spawn-ratelimit]]).
# TEK-TEK; config doğrula: python3 -c "import json;json.load(open('$HOME/.claude.json'))"
# İsimler base-name (suffix yok); --new → fresh, aynı isimle açılır (remote'da kaymaz):
py/cops rc hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc asp \
  --new --kill-first --model='claude-sonnet-4-6' --permission-mode=auto --effort=max --one-by-one
py/cops rc aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot \
  --new --kill-first --model='claude-opus-4-8' --permission-mode=auto --effort=max --one-by-one
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

## READY FOR HANDOVER (2026-06-25)

**DURUM:** co56 (self; guard co'yu resume edip harness beni taşıdı, çakışma yok — istenen [[co-ulaksec-guard-yes-ho-no]]). Fleet **27 \*56** (coding sonnet / paper opus + co + ulaksec), suffix=56, config VALID, **DUP yok**, layout TAMAM (ws0-pin co56/rustrino56/anomaly56/iggy56, eDP-1). carla/mecdtfl KAPALI. `~/.cache/huggingface` 29G KORU.

**Bu session:** OOM (Haz 23, oomd 2×) → fleet **2 gün DOWN** çünkü guard cron bozuktu (`--roster` arg Python'da yok + log dizini yok → her dakika sessiz çökme). Elle recover (27/27) + cron absolute-path'e düzeltildi, şimdi sağlıklı. [[guard-cron-relative-path]], detay DONE.md.

**Yeni session yapacaklar:**
1. MEMORY.md oku — [[guard-cron-relative-path]] + [[oomd-cgroup-kill]] + [[claude-2183-conversation-truncation]] + [[mass-faz1-ratelimit-stuck]] + [[layout-needs-unlocked-screen]].
2. **AÇIK KARAR (TBD#7): fleet ÇOK BÜYÜK** — 27 session → OOM tekrar riski (3. kez); küçült (≤15) / co→sonnet? Ana karar.
3. **TODO (yeni):** autostart `~/.config/autostart/claudeops.desktop` hâlâ **bash** `claudeops guard --boot` kullanıyor; cron `py/cops`'a geçti → ikilik (boot.log son reboot reopened=27, çalışıyor ama tutarsız).
4. ho gerekirse: İLK `uptime -s` + Faz1 `--kill-settle=5` + batch-throttle + Faz2 `--new` (boş başlar). Faz3 2× çalıştır + `LockedHint=no` + `xwininfo` doğrula.

READY FOR HANDOVER
