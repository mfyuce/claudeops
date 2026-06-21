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
# Faz 1
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

## READY FOR HANDOVER (2026-06-21)

**⚠⚠ ASIL OLAY: KONUŞMA TRUNCATION KÖK SEBEBİ BULUNDU + FIX** (`adad34f`, [[claude-2183-conversation-truncation]]): proc-scan sweep `SIGTERM→0.3s→SIGKILL` yapıyordu → claude flush edemeden (2.1.183 lazy-checkpoint ~2s ister) ölüyor → jsonl eski checkpoint'e truncate. **Fix: 8s grace.** anomaly testiyle KANITLANDI (519→528 korundu). **Haftalardır süren veri kaybının (iggy/asp/hc transkript) sebebi buydu** — iş git'te güvende, sadece transkript gitti. **KURAL: kill ederken hep SIGTERM + ~8-10s grace, sadece canlıysa SIGKILL.**

**✅ DURUM:** co53 (self; OOM'da co50→co53 bumplandı). Fleet **25 \*53** (+co53 +ulaksec53 = 27 guard-takipli), **şu an GEÇİCİ HEPSİ opus/auto/max** (kullanıcı "şimdilik hepsi opus, döneriz"; models.tsv split KORUNDU — coding 13 sonnet / paper 12 opus). anomaly→**anomaly54** (RC bridge sorunu için yeniden isimlendi, konuşma korundu). suffix=53, dup yok, config VALID, **guard cron AÇIK** (fix devrede → nazik kill). **Opus/Sonnet [1m] KAPALI** → plain. **carla/mecdtfl KAPALI**. `~/.cache/huggingface` 29G KORU.
**Bugün (2026-06-18→21):** 16:06 ACPI EC **donanım** reboot → recovery. cron artefakt-skip (`4f0543b`). iggy/vc/asp/trroot eklendi (`35ec745`,`941347c`). ho *49→50→51→52→53, Faz2 **`--new --prompt='devam'`** [[faz2-new-session-devam]]. OOM olayı. claude.ai export çekildi (`~/.claude/claudeai-export-recovery/`, AMA Code session'ları yok). Detay: DONE.md.
**Altyapı:** guard cron `*/2` (açık), cold-boot autostart. isim: hc=videogen hcr=hoca-reader vrk=varaka mo=machine_ops iggy=ng_sdn/iggy vc=virtual_court asp=llm/T_ancient_script_pipeline trroot=tr_root.

**Yeni session yapacaklar:**
1. MEMORY.md oku — özellikle [[claude-2183-conversation-truncation]] + [[handover-hold-guardlock]] + [[reboot-no-handover]] + [[faz2-new-session-devam]] + [[co-ulaksec-guard-yes-ho-no]].
2. **ho isteğinde İLK `uptime -s`** (reboot yakınsa ho YAPMA). **Handover'ı guard.lock'la sar** (dup önle, [[handover-hold-guardlock]]).
3. `needs-ho --from-suffix=53`. ho: Faz1 → onay → **Faz2 `--new --prompt='devam'`** (<F>=53 <TO>=54) → Faz3 layout. ⚠ 27 opus = OOM riski.

**Açık kararlar (ÖNEMLİ):** **TOBEDECIDED #7 — fleet ÇOK BÜYÜK** (27 opus = pahalı [20x→5x] + OOM + remote ~10-bağlantı-limiti) → küçült / co→sonnet / split'e dön? + sonnet[1m] kapalı + #5 açık-kaynak #6 web.
**Açık TODO (kritik):** (j/r) handover guard.lock+cron-disable; (m) sid=- cwd fallback; (n) ho co+ulaksec exclude; (t/u) RC bridge lag + claude.ai stale bridge. Tam: TODO.md.

READY FOR HANDOVER
