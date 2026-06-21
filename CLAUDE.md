# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. `-n` display, `--remote-control` RC bridge; aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang). `--claude-only`: sadece aktif RC proc'larını tile'la.
- **claude 2.1.169** (`b8bad9e`): fresh `--new` session'lar `sessions/<pid>.json` YAZMIYOR → guard DUP. Fix: proc-scan. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE riski**: yeni storage **lazy-checkpoint** (her mesaj değil, ara ara diske yazar). Kill'de claude'a **flush için ~2s** gerekir → `SIGTERM`'den `SIGKILL`'e **<2s = konuşma eski checkpoint'e TRUNCATE**. proc-scan sweep 0.3s'ydi → **8s grace** (`adad34f`). **Kural: kill ederken hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL.** Fresh session.json yazmaz → ana-kill PID'le bulamaz → sweep'e düşer. [[claude-2183-conversation-truncation]] [[handover-hold-guardlock]]
- **1M context**: `[1m]` suffix → beta header. **Opus [1m] KAPALI** (Anthropic, 2026-06-16). **Sonnet [1m] bu hafta kapalı** (token kısıtı). [[model-1m-context]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Model (`~/.claude/claudeops/models.tsv`)

- **Coding 13** (hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc asp) → `claude-sonnet-4-6` plain
- **Paper 12** (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot) → `claude-opus-4-8` plain
- **co** (self) + **ulaksec** → models.tsv'de AKTİF (guard crash-recovery'de ayakta tutsun — istenen). AMA **handover YAPMAZ**: co self (filter_not_self), ulaksec base-name exclude. ⚠ guard die olunca onları fleet suffix'ine bumplar (co43→co50) → ho `--from-suffix=N` artık eşleşir → ho co+ulaksec'i base-name ile atlamalı (TODO-n). **EMEKLİ:** rr gedikvm gedikido kulturiot. **KAPALI:** mecdtfl, carla (`#` kaldır açmak için).

## Handover (3-fazlı)

```
# Faz 1  (⚠ TÜM fleet'e AYNI ANDA = sunucu rate-limit → blank-TUI hang [3/24 oldu]; gruplara böl/throttle, [[mass-faz1-ratelimit-stuck]])
./claudeops handover --from-suffix=<FROM> [--model='claude-opus-4-8']

# Faz 2 — ⚠ Faz1 SAĞLIKLI? (RFH var, 503/529 yok) → değilse DUR; kullanıcı onayı şart.
# TEK-TEK; config doğrula: python3 -c "import json;json.load(open('$HOME/.claude.json'))"
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> evolvi<F> done<F> mamut<F> hof<F> iggy<F> vc<F> asp<F> \
  --suffix=<TO> --new --kill-first --model='claude-sonnet-4-6' --permission-mode=auto --effort=max --one-by-one
./claudeops rc aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> gencmuh<F> marwan<F> sase<F> trroot<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8' --permission-mode=auto --effort=max --one-by-one

# Faz 3 — ws0 pin: co(self)+rustrino+anomaly+iggy (anomaly+iggy yan yana); ulaksec pin'siz → ws1
# --group tekrarlanabilir. 26 session → önce `claudeops desktops 8` gerekebilir.
./claudeops layout grid 4 --claude-only --pin=co<SELF>,rustrino<TO>,anomaly<TO>,iggy<TO> --group=hc,hcr,evolvi --group=vc,vrk
```
⚠ `[1m]` **tek tırnak ŞART** (shell glob). Target **SPACE-separated** (virgül parse bug). `--group=` base-name (suffix'siz).
**Skip kriteri:** RFH var + son RFH'den sonra yeni istek yok + repo temiz+pushed (github+gitlab).
Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. Terminal: gnome-terminal hard-coded. `rc --kill-first` permission modal keser.
Target virgül parse yok (SPACE kullan, TODO-a). Layout orphan terminal slot işgal (TODO-b). Tam: TODO.md.

## Meta

`DONE.md` = CHANGELOG. Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE; TOBEDECIDED karar → TODO.

## READY FOR HANDOVER (2026-06-21 gece)

**✅ DURUM:** co53 (self). Fleet **25 \*53** (+co53 +ulaksec53 = 27 guard-takipli), **GEÇİCİ hepsi opus/auto/max** (models.tsv split KORUNDU: coding 13 sonnet / paper 12 opus). anomaly→**anomaly54**. suffix=53, config VALID, **guard cron AÇIK**. **Opus/Sonnet [1m] KAPALI**. carla/mecdtfl KAPALI. `~/.cache/huggingface` 29G KORU.

**Bu session kazanımları (commit'li):** (1) **truncation kök-sebep+fix** `adad34f` (proc-scan sweep 0.3s→8s grace, anomaly testiyle kanıtlı — haftalarca veri kaybının sebebiydi, iş git'te güvende); (2) **handover başarı=proc-varlığı** `420fc4d` (bridge-field gecikmeli → false-"failed" düzeltildi); (3) full-fleet Faz1: 21/24 wrap-up OK. Kill kuralı: hep SIGTERM + ~8-10s grace. Detay: DONE.md.

**⚠ AÇIK İŞ (kullanıcı ELLE yapıyor — dokunma):** **emrgence53 + anomaly54 STUCK** — full-fleet Faz1'de 24 session aynı anda → **sunucu rate-limit** ("temporarily limiting requests", usage-limit DEĞİL) → blank-TUI hang. qve53 recovery'de dup yaşandı+temizlendi. Kullanıcı "böyle olmaz, elle yaparım" → DURDUM. [[mass-faz1-ratelimit-stuck]]

**Yeni session yapacaklar:**
1. MEMORY.md oku — özellikle [[claude-2183-conversation-truncation]] + [[mass-faz1-ratelimit-stuck]] + [[handover-hold-guardlock]] + [[faz2-new-session-devam]].
2. **EN ÖNEMLİ → TOBEDECIDED #8: claudeops'u Python/Rust'a taşı.** >2000 satır bash sürdürülemez; bu gece kırılganlık somut yaşandı (truncation kill-timing, quoting/pattern bug, dup yarışı). Kullanıcı "yeni claudeops'a başlarız" dedi → muhtemel ilk iş. Lean: Python + incremental (canlı 27-session fleet bozulmamalı).
3. ho gerekirse: İLK `uptime -s` + guard.lock'la sar (kesintisiz) + **Faz 1'i gruplara böl** (rate-limit, TODO-v) + Faz2 `--new --prompt='devam'`.

**Açık kararlar:** **#8 yeni claudeops (öncelikli)** + **#7 fleet ÇOK BÜYÜK** (27 opus = pahalı [20x→5x] + OOM + remote ~10-limit → küçült/co→sonnet/split). Tam: TOBEDECIDED.md / TODO.md.

READY FOR HANDOVER
