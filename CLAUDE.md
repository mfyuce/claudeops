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

- **İki-grup model** (2026-06-01 revize): **coding→sonnet, paper→opus**, hepsi `[1m]` (1M ctx) + `--permission-mode=auto` + `--effort=max` + RC. Harita: **`~/.claude/claudeops/models.tsv`** (name→model). **Sonnet (coding, 12):** hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido evolvi done mamut (+co). **Opus (paper, 11):** rr aggroot oa hms hve qve rve emrgence araroot mecdtfl carla. (Tarihçe: 2026-05-30 tek-model'e indirilmişti → 2026-06-01 tekrar split'e dönüldü; eskiden 13 opus + 7 sonnet idi.)
- `rc` flag'leri model-agnostic pass-through: `--model`, `--permission-mode`, `--effort` (low/medium/high/xhigh/max).

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2] [--model='claude-opus-4-8[1m]']
#   ⚠ --model (2026-06-05): wrap-up resume'unu bu modelde aç. SONNET LİMİT dolunca sonnet
#   session'larını opus'a resume edip wrap-up yaptır (konuşma geçmişi model-agnostik → limit bypass,
#   bağlam korunur). vrk35 ho'sunda doğrulandı. ho_model boşsa eski davranış (session'ın kendi modeli).

# Faz 2 — fresh respawn (model-split: 2 grup; models.tsv'e bak; --prompt opsiyonel → idle açılır)
#   SONNET (coding):
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> kulturiot<F> gedikvm<F> gedikido<F> evolvi<F> done<F> mamut<F> \
  --suffix=<TO> --new --kill-first --model='claude-sonnet-4-6[1m]' --permission-mode=auto --effort=max
#   OPUS (paper):
./claudeops rc rr<F> aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> mecdtfl<F> carla<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max
#   (Straggler — unpushed/uncommitted iş olan'lara ekle: --prompt='...commit + TÜM remote'lara push...')
#   ⚠ ALL-OPUS dönemde (sonnet limit dolu = ŞU AN): Faz 2 = TEK komut, 2-grup split ATLA:
#     ./claudeops rc all-but-self --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max
#     (self skip; kapalı session [mecdtfl] zaten dahil değil; --suffix suffix dosyasını oto-yazar → guard *<TO> arar)

# Faz 3 — layout (self/co ws0 pin; mecdtfl KAPALI → grup1=hc,hcr,evolvi; grup2=mo,kulturiot,gedikvm,gedikido)
./claudeops layout grid 4 --pin=co<SELF>,anomaly<TO>,rustrino<TO> --group=hc,hcr,evolvi --group=mo,kulturiot,gedikvm,gedikido
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

## READY FOR HANDOVER (2026-06-08)

**Nerede kaldık:** co36 (claudeops repo, self). **HANDOVER *36→*37 TAMAM** — yine ALL-OPUS (sonnet limit hâlâ dolu). 22 session *37 = `claude-opus-4-8[1m]`/auto/max/RC + co36 (self; **all-but-self self'i bump etmez → co36 kalır**; guard cwd-match ile co37 duplicate açmaz). suffix=37, **duplicate YOK**, *36 kalıntı 0. **mecdtfl KAPALI** (review'a kadar; models.tsv comment-out → guard respawn ETMEZ. Aç: `#` kaldır + `claudeops guard`). models.tsv = all-opus (revert list aşağıda). Layout (7 ws): ws0 pin co36/anomaly37/rustrino37; serbest ws1-3 + **rr37 ws4** (tek); grup1 hc/hcr/evolvi ws5; grup2 mo/kulturiot/gedikvm/gedikido ws6.

**Bu ho TEMİZDİ (*36→*37):** Faz1 10 wrap-up (hc hcr mo rustrino anomaly kulturiot gedikvm gedikido rr evolvi; hepsi *36 zaten opus → --model gerekmedi) → **rescan straggler 0** (hepsi mod=0/unpush=0, commit+push tam; gedikido `ODEV_INCELEME_BULGULARI.md` + evolvi `CHANGELOG.md` commit'lendi; rustrino `bench/results/` + anomaly `rumeysa.zip` junk untracked kaldı). 12 skip. Faz2 = **ALL-OPUS tek komut** `rc all-but-self --suffix=37 --new --kill-first --model='claude-opus-4-8[1m]' ...`. **Faz1+Faz2 elle `guard.lock` flock** → guard-race duplicate önlendi (edge-case-8 mitigation; iki ho üst üste doğrulandı). ⚠ `handover --exclude=anomaly` (base-name) TUTMADI → suffix'li ister/buggy (TODO-i).

**Kalıcı altyapı (✅ detay DONE.md):** (1) **Cold-boot:** `boot`/`snapshot`/`recover` + `~/.config/autostart/claudeops.desktop`; boot.list=co+mo, suffix=`~/.claude/claudeops/suffix`. İsim sürprizleri: **hc=videogen, hcr=hoca-reader, vrk=varaka, mo=machine_ops**. (2) **guard watchdog:** OOM → `claudeops guard` idempotent (HER ZAMAN en güncel jsonl resume), cron `*/2` + autostart `guard --boot --lock`, `_detect_display` oto. **oomd'ye dokunma, guard kurtarsın.** ⚠ AÇIK: autologin `/etc/gdm3/custom.conf` henüz kapalı (sudo gerek). ⚠ boot models.tsv lookup eksik (cmd_boot tek `BOOT_MODEL_DEFAULT`; guard models.tsv okuyor ✓).

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[handover-procedure]] + [[handover-edge-cases]] + [[add-session-to-fleet]] + [[feedback-calisma-tarzi]] + [[model-1m-context]] + [[oomd-cgroup-kill]].
2. **needs-ho:** `claudeops needs-ho --from-suffix=37`. **fleet kapandıysa:** `claudeops guard`.
3. **Açık TODO bug'lar:** (a) `rc` virgül parse, (b) layout orphan terminal (`cleanup`), (c) `cancel` Esc fallback, (d) `--model`→default `auto`, (e) handover `--layout --group` passthrough, (f) `deep-ho` yeni cmd, (g) boot models.tsv lookup, **(h) rc/handover `guard.lock` almıyor → guard-race (her ho'da elle flock'luyoruz; KALICI FİX gerek)**, (i) `handover --exclude=<base-name>` filtrelemiyor.

**Açık kararlar:** (1) ⚠ **sonnet limit hâlâ dolu** → models.tsv all-opus. Limit AÇILINCA split'e revert (list: **hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido evolvi done mamut co**). (2) **mamut coding mi paper mı?** (şimdilik coding/sonnet-canonical varsayımı). (3) **mecdtfl KAPALI** — review gelince aç (models.tsv `#` kaldır + guard). (4) anomaly `rumeysa.zip` + rustrino `bench/results/` untracked junk. (5) TOBEDECIDED #5 (açık-kaynak local config). `~/.cache/huggingface` 29G KORU.

READY FOR HANDOVER
