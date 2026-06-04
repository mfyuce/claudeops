# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Self Protection

`find_self_claude_pid`: (1) `$CLAUDE_CODE_SESSION_ID` env var (Claude TUI çocuklara geçirir — nohup-detached'te tek güvenilir yol), (2) fallback `$$` ata zinciri. `all-but-self` buna bağlı; self'i ASLA hedef almaz.

## Önemli teknik kararlar (kod-okumakla anlaşılmaz)

- **stdin redirect** `< /dev/null`: `claude -p` her çağrıda zorunlu (stdin leak fix).
- **`script -qfc` detached pty**: `nohup &` yetmez, Claude TUI gerçek terminal ister.
- **Visible window**: `gnome-terminal -- bash -c "claude ...; exec bash"` (claude exit etse pencere bash'a düşer).
- **wmctrl -s vs xprop**: sadece `wmctrl -s N` Mutter'da görsel switch tetikler.
- **VTE keystroke rejection**: synthetic key (`xdotool type`/`key`) çoğu zaman REDDEDİLİR. Güvenilir prompt enjeksiyonu = **CLI argümanı**: `claude ... -n NAME --remote-control NAME 'PROMPT'` (Enter'sız otomatik). Idle/stuck session'a iş → kill + fresh-spawn böyle.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` display, `--remote-control` RC bridge. Server-side bridge cache: aynı sid resume → RC name cache'li, değiştirmek için `--new`.
- **Layout in-place**: `xdotool windowmove` (**`--sync` YOK** — pencere hedefteyse hang) + `wmctrl -s` desktop-switch + `get_desktop` verify (pencere görünür değilse yanlış taşır) + read-back. Konum doğrulaması `xdotool getwindowgeometry` (wmctrl -G 2× raporluyor).
- **1M context**: model ID'ye `[1m]` suffix → CLI `context-1m-2025-08-07` beta header ekler + context=1e6. Örn `claude-opus-4-8[1m]`. Detay: memory [[model-1m-context]].

## Model konvansiyonu

- **İki-grup model** (2026-06-01 revize): **coding→sonnet, paper→opus**, hepsi `[1m]` (1M ctx) + `--permission-mode=auto` + `--effort=max` + RC. Harita: **`~/.claude/claudeops/models.tsv`** (name→model). **Sonnet (coding, 10):** hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido evolvi (+co). **Opus (paper, 11):** rr aggroot oa hms hve qve rve emrgence araroot mecdtfl carla. (Tarihçe: 2026-05-30 tek-model'e indirilmişti → 2026-06-01 tekrar split'e dönüldü; eskiden 13 opus + 7 sonnet idi.)
- `rc` flag'leri model-agnostic pass-through: `--model`, `--permission-mode`, `--effort` (low/medium/high/xhigh/max).

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2]

# Faz 2 — fresh respawn (model-split: 2 grup; models.tsv'e bak; --prompt opsiyonel → idle açılır)
#   SONNET (coding):
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> kulturiot<F> gedikvm<F> gedikido<F> \
  --suffix=<TO> --new --kill-first --model='claude-sonnet-4-6[1m]' --permission-mode=auto --effort=max
#   OPUS (paper):
./claudeops rc rr<F> aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> mecdtfl<F> carla<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max
#   (Straggler — unpushed/uncommitted iş olan'lara ekle: --prompt='...commit + TÜM remote'lara push...')

# Faz 3 — layout (self/co ws0 pin; 2 grup: hc+hcr+mecdtfl→ws4, mo+kulturiot+gedikvm+gedikido→ws5)
./claudeops layout grid 4 --pin=co<TO>,anomaly<TO>,rustrino<TO> --group=hc,hcr,mecdtfl,evolvi --group=mo,kulturiot,gedikvm,gedikido
```

⚠ `[1m]` köşeli parantez için **tek tırnak ŞART** (shell glob). Target listesi **SPACE-separated** (virgül parse bug — TODO).
⚠ `--group=` **base-name** alır (suffix'siz) → handover'da `<TO>` bump GEREKMEZ, sabit kalır. Tekrarlanabilir; her grup serbest-others'tan sonra kendi taze desktop'una blok yerleşir, asla bölünmez. 2 grup → ilk yazılan önce (düşük ws). 12 serbest-other ws1-3 → grup1 ws4, grup2 ws5.
**Flag'ler:** `handover --force` (skip baypas; jsonl yoksa fresh-spawn) · `--layout [--pin=a,b]` (spawn bitince oto-tile) · `cancel <names>` (stuck modal'a Esc; inmezse `rc --kill-first`).
**Skip kriteri (done):** jsonl'de RFH var + son RFH'den sonra yeni istek yok + repo temiz. `repo_dirty`: untracked saymaz; dirty = tracked-modified **veya** TÜM remote'lara push edilmemiş (çift remote github+gitlab, `@{u}` değil) **veya** behind. Pre-check 1× `git fetch --all` (20s).
Detay: memory [[handover-procedure]] + [[handover-edge-cases]].

## Bilinen sınırlamalar / açık bug'lar

- **Wayland**: layout çalışmaz (wmctrl X11-only). **Terminal**: gnome-terminal hard-coded.
- **Permission modal**: RC'yi bloklar; garantili iptal = `rc --kill-first`.
- **`rc <a,b,c>` virgül**: parse yok, SPACE kullan (TODO). **Layout orphan terminal**: window-name validation eksik, orphan quad slot işgal eder (TODO).

## Meta

- `DONE.md` = de facto CHANGELOG. `desktops.local.md` = layout snapshot (gitignored).
- Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
- **Handover-prep MD sync** (her ho'da): (1) TODO'da tamamlanmış → DONE'a taşı+TODO'dan sil; (2) TOBEDECIDED'da karar verilmiş → TODO'ya taşı+sil.

## READY FOR HANDOVER (2026-06-04)

**Nerede kaldık:** co33 (claudeops repo, self). **HANDOVER *33→*34 TAMAM.** Faz1 opened=17/skip=4, Faz2 sonnet-10+opus-11 respawn tamamlandı, suffix state=34. **İki-grup model** (2026-06-01 karar): coding→sonnet (10), paper→opus (11), harita `~/.claude/claudeops/models.tsv`. Hepsi `[1m]`/auto/max/RC. Standart layout (ws0 pin co/anomaly34/rustrino34; grup1 hc/hcr/mecdtfl/evolvi→ws4; grup2 mo/kulturiot/gedikvm/gedikido→ws5).

**Bu ho'da (*33→*34):** Guard OOM-recovery **5 kök bug fix** (`f4d949f`): PATH(SPAWN_ENV) + stale-json(liveness) + resume-semantics(always-resume) + agent-sid(UUID-only) + flock(concurrent-lock). Gerçek cron env testinde doğrulandı (hms33 resume=d9565347, `claude --model opus...` process görüldü). Straggler'lar: mo+vrk(unpush=2), anomaly(mod=7/unt=3), mecdtfl(unt=2), evolvi(unt=1) → Faz2 fresh+çalışan session'lar kendileri temizler.

✅ **Cold-boot oto-açılış** (DONE.md 2026-05-31): `claudeops boot [--lock] [--from-roster]` + `snapshot` + `recover` + `~/.config/autostart/claudeops.desktop`. boot.list=co+mo, suffix state=`~/.claude/claudeops/suffix`. İsim sürprizleri: **hc=videogen, hcr=hoca-reader, vrk=varaka, mo=machine_ops**.

✅ **guard watchdog + oomd kurtarma** (DONE 2026-06-03, sertleştirme 2026-06-04 `f4d949f`): OOM → `claudeops guard` idempotent geri açar (**HER ZAMAN en güncel jsonl resume**). Cron `*/2` + autostart `guard --boot --lock`; `_detect_display` DISPLAY oto-tespit. 5 bug fix: PATH/liveness/resume/agent-sid/flock. Detay [[oomd-cgroup-kill]]. **Kullanıcı kararı: oomd'ye dokunma, guard kurtarsın.**

⚠ **AÇIK: autologin** — `/etc/gdm3/custom.conf` AutomaticLogin henüz AÇIK DEĞİL (sudo gerek; Wayland kapalı=X11 ✓).

⚠ **boot/recover models.tsv lookup eksik** — `cmd_boot` hâlâ `BOOT_MODEL_DEFAULT` tek opus; `guard` models.tsv okuyor ✓.

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[handover-procedure]] + [[handover-edge-cases]] + [[feedback-calisma-tarzi]] + [[model-1m-context]] + [[oomd-cgroup-kill]].
2. **needs-ho:** `claudeops needs-ho --from-suffix=34`. **fleet kapandıysa:** `claudeops guard`.
3. **Açık TODO bug'lar:** (a) `rc` virgül parse, (b) layout orphan terminal, (c) `cancel` Esc fallback, (d) `--model`→default `auto`, (e) handover `--layout --group` passthrough, (f) `deep-ho` yeni cmd, (g) boot models.tsv lookup.

**Açık kararlar:** anomaly `rumeysa.zip` + mecdtfl `main_1_page.pdf` untracked junk. TOBEDECIDED #5 (açık-kaynak local config). `~/.cache/huggingface` 29G KORU.

READY FOR HANDOVER
