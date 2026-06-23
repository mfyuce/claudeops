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

## READY FOR HANDOVER (2026-06-23)

**✅ DURUM:** co55 (self). Fleet **25 \*56** + co55 + ulaksec55 (27 guard-takipli), **SPLIT** (coding 13 sonnet / paper 12 opus). suffix=56, config VALID, **guard cron AÇIK + ABSOLUTE-PATH'li** (fix bu session), **DUP yok, 0 stuck**, uptime 5 gün (reboot yok). **Opus/Sonnet [1m] KAPALI**. carla/mecdtfl KAPALI. `~/.cache/huggingface` 29G KORU. **Faz3 (layout) YAPILMADI** — yeni *56 pencereleri dizilmeyi bekliyor.

**Bu session (commit'li):** (1) **guard-cron absolute-path fix** [[guard-cron-relative-path]] — relatif `py/cops` → cron `$HOME`'dan "not found" → OOM'da fleet HİÇ recover etmiyordu, log donup "çalışıyor" yanıltıyordu; (2) **OOM #2 recovery → *55**; (3) **Faz1 `--kill-settle`** `8fd620a` (kill→settle→respawn = aynı-isim RC bridge çakışma/flicker önlemi) + **Faz1 *55 production: 15 opened / 0 failed / 10 needs_ho-skip** (`--kill-settle=5`, sıfır rate-limit/stuck — ilk gerçek validasyon); (4) **discovery two-source port** (sessions/json + proc-scan merge); (5) **Faz2 *55→*56** throttle'lı cutover (guard-disable + sonnet/opus split + `--one-by-one`) — **25/25 clean kill+respawn, dup yok, config valid, 0 rate-limit**. Detay: DONE.md.

**stale-title (Faz2 ÇÖZDÜ + kalıcı TODO):** rustrino/sase *53-jsonl resume → TUI başlığı *53'te takılı → layout onları atlamıştı (fleet TEMİZ). **Faz2 cutover fresh *56 terminallerle çözdü.** Kalıcı fix TODO: layout pencere↔session PID-eşleşme + cross-suffix resume'da title re-emit. [[stale-tui-title-cross-suffix-resume]]

**TBD#8 Python rewrite TAMAM** (2026-06-22, 8 komut): `py/cops` CANLI tool — guard cron + handover bunu kullanıyor. Bash `claudeops` ROOT'ta layout/eski komutlar için duruyor.

**Yeni session yapacaklar:**
1. **Faz3 layout** (*56 pencereleri henüz dizilmedi): `py/cops layout --pin=co55,rustrino56,anomaly56,iggy56 --group=hc,hcr,evolvi --group=vc,vrk`.
2. MEMORY.md oku — [[claude-2183-conversation-truncation]] + [[guard-cron-relative-path]] + [[mass-faz1-ratelimit-stuck]] + [[handover-hold-guardlock]].
3. **#7 fleet ÇOK BÜYÜK** — 27 session → **OOM bugün 2×**; küçült (≤15) / co→sonnet? Gecenin ana açık kararı.
4. ho gerekirse (Faz1+Faz2 bu session yapıldı): İLK `uptime -s` + Faz1 `--kill-settle=5` + batch-throttle + Faz2 `--new --prompt='devam'`.

READY FOR HANDOVER
