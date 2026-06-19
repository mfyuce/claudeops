# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. `-n` display, `--remote-control` RC bridge; aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang). `--claude-only`: sadece aktif RC proc'larını tile'la.
- **claude 2.1.169** (`b8bad9e`): fresh `--new` session'lar `sessions/<pid>.json` YAZMIYOR → guard DUP. Fix: proc-scan. [[claude-2169-session-detection]]
- **1M context**: `[1m]` suffix → beta header. **Opus [1m] KAPALI** (Anthropic, 2026-06-16). **Sonnet [1m] bu hafta kapalı** (token kısıtı). [[model-1m-context]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Model (`~/.claude/claudeops/models.tsv`)

- **Coding 12** (hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc) → `claude-sonnet-4-6` plain
- **Paper 12** (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot) → `claude-opus-4-8` plain
- **co** (self) + **ulaksec** → models.tsv'de AKTİF (guard crash-recovery'de ayakta tutsun — istenen). AMA **handover YAPMAZ**: co self (filter_not_self), ulaksec base-name exclude. ⚠ guard die olunca onları fleet suffix'ine bumplar (co43→co50) → ho `--from-suffix=N` artık eşleşir → ho co+ulaksec'i base-name ile atlamalı (TODO-n). **EMEKLİ:** rr gedikvm gedikido kulturiot. **KAPALI:** mecdtfl, carla (`#` kaldır açmak için).

## Handover (3-fazlı)

```
# Faz 1
./claudeops handover --from-suffix=<FROM> [--model='claude-opus-4-8']

# Faz 2 — ⚠ Faz1 SAĞLIKLI? (RFH var, 503/529 yok) → değilse DUR; kullanıcı onayı şart.
# TEK-TEK; config doğrula: python3 -c "import json;json.load(open('$HOME/.claude.json'))"
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> evolvi<F> done<F> mamut<F> hof<F> iggy<F> vc<F> \
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

## READY FOR HANDOVER (2026-06-19)

**✅ DURUM:** co50 (self). Fleet **24 \*51** (+co50 +ulaksec50 = 26 guard-takipli) auto/max — coding 12 × sonnet-plain (hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc) + paper 12 × opus-plain (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot). suffix=51, dup yok, config VALID. **co50+ulaksec50 *50'de** (fleet *51) → handover dışı: `--from-suffix=51` doğal atlar; guard *51'e bumplarsa `--exclude=ulaksec51` / TODO-n. 4 EMEKLİ fleet dışı. **Opus [1m] KAPALI**; **Sonnet [1m] kapalı** → models.tsv plain. **carla/mecdtfl KAPALI** (`#`). `~/.cache/huggingface` 29G KORU.
**Bugün (2026-06-18→19):** makine **16:06 reboot** (ACPI EC donanım, fleet/oomd DEĞİL — [[reboot-no-handover]]) → recovery. **cron artefakt-skip fix** deploy+commit (TODO-o: `_latest_sid_for_cwd` boş post-boot artefaktı atlar, en son GERÇEK konuşmayı açar — `4f0543b`). mo50 gerçek konuşmaya repoint (1e6e54b7). **iggy+vc (coding) + trroot (paper, resume a8dd981b) eklendi** (`35ec745`). ho *50→*51 tam.
**Altyapı ✅:** guard cron `*/2`, cold-boot autostart, boot.list=co+mo. isim: hc=videogen hcr=hoca-reader vrk=varaka mo=machine_ops iggy=ng_sdn/iggy vc=virtual_court trroot=tr_root.

**Yeni session yapacaklar:**
1. MEMORY.md oku — [[reboot-no-handover]] + [[co-ulaksec-guard-yes-ho-no]] + [[config-corruption-resume-hang]] + [[handover-procedure]] + [[handover-edge-cases]] + [[add-session-to-fleet]].
2. **ho isteği gelince İLK `uptime -s`** — reboot yakınsa (≤~30dk) handover ÇALIŞTIRMA, cron toparlar [[reboot-no-handover]].
3. `claudeops needs-ho --from-suffix=51` → kapalıysa `claudeops guard`.
4. ho Faz 1 → kullanıcı onayı → **Faz 2** (2 rc, <F>=51 <TO>=52, `--one-by-one`, config doğrula) → **Faz 3** layout (26 session → `claudeops desktops 8`).

**Açık TODO bug'lar (kritik):** (a) rc virgül; (b) orphan terminal; (j) guard.lock kayıt-bekle; (k) bridge-verify name-only; (m) handover sid=- cwd fallback; (n) ho co+ulaksec base-name exclude. Tam: TODO.md.
**Açık kararlar:** (1) sonnet [1m] kapalı. (2) sase/marwan reboot-öncesi konuşma crash'te kayıp (post-boot yeni konuşmayla devam). (3) TOBEDECIDED #5 açık-kaynak, #6 web server.

READY FOR HANDOVER
