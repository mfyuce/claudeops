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

- **Hepsi tek model**: `claude-opus-4-8[1m]` (1M context) + `--permission-mode=auto` + `--effort=max`. (2026-05-30: opus/sonnet ayrımı kaldırıldı; eskiden 13 opus + 7 sonnet idi.)
- `rc` flag'leri model-agnostic pass-through: `--model`, `--permission-mode`, `--effort` (low/medium/high/xhigh/max).

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2]

# Faz 2 — fresh respawn (tek komut, hepsi aynı model; --prompt opsiyonel → idle açılır)
./claudeops rc hms<F> hve<F> oa<F> qve<F> rve<F> carla<F> emrgence<F> rr<F> araroot<F> aggroot<F> gedikvm<F> gedikido<F> kulturiot<F> anomaly<F> rustrino<F> mecdtfl<F> vrk<F> hc<F> hcr<F> mo<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max

# Faz 3 — layout (self/co ws0 pin; 2 grup: hc+hcr+mecdtfl→ws4, mo+kulturiot+gedikvm+gedikido→ws5)
./claudeops layout grid 4 --pin=anomaly<TO>,rustrino<TO> --group=hc,hcr,mecdtfl --group=mo,kulturiot,gedikvm,gedikido
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

## READY FOR HANDOVER (2026-05-31)

**Nerede kaldık:** co29 (claudeops repo, self). **REBOOT OLDU + fleet recover edildi** — 20 *30 session geri ayakta (**9 geçmişiyle resume, 11 fresh**), `claude-opus-4-8[1m]`/auto/max, RC'li, **tek temiz `gnome-terminal-server`** (reboot eski iki-server wedge'ini temizledi — artık `--app-id` derdi YOK), standart layout (ws0 pin co/anomaly/rustrino; grup1 hc/hcr/mecdtfl→ws4; grup2 mo/kulturiot/gedikvm/gedikido→ws5).

✅ **Cold-boot oto-açılış kuruldu** (DONE.md 2026-05-31): `claudeops boot [--lock] [--from-roster]` + `snapshot` + `recover` + `~/.config/autostart/claudeops.desktop`. boot.list=co+mo, suffix state=`~/.claude/claudeops/suffix` (`rc --suffix` oto-yazar). boot her session'ı **base+suffix** ile ve cwd'nin **en güncel jsonl'iyle `--resume`** açar (geçmiş korunur), `--lock` ile en son kilitler. **Reboot recovery reçetesi:** `recover` resume-tablosu verir; isim→cwd kesini handover-log *29 sid'lerinden çözülür (jsonl session adını saklamaz). İsim sürprizleri: **hc=videogen, hcr=hoca-reader, vrk=varaka, mo=machine_ops**.

⚠ **AÇIK: autologin** — `/etc/gdm3/custom.conf` AutomaticLogin henüz AÇIK DEĞİL (sudo gerek; Wayland zaten kapalı=X11 ✓). Açılınca reboot→`boot --lock` co30+mo30'u geçmişiyle açıp kilitler.

Bu oturumda ayrıca (önceki): `layout --group` (`a9867da`), `needs-ho` generic+commit-baseline (`53d4458`), app-id handover (`a45b188`).

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[handover-procedure]] + [[handover-edge-cases]] + [[feedback-calisma-tarzi]] + [[model-1m-context]].
2. **needs-ho generic:** `claudeops needs-ho --from-suffix=30`. **recover:** `claudeops recover` reboot sonrası resume adayları.
3. **Açık TODO bug'lar:** (a) `rc` virgül parse, (b) layout orphan terminal, (c) `cancel` Esc fallback, (d) `--model`→default `auto`, (e) handover `--layout` `--group` geçirmiyor.

**Açık kararlar:** anomaly30 `rumeysa.zip` + mecdtfl30 `main_1_page.pdf` untracked junk (sil/gitignore/bırak?). TOBEDECIDED #5 (açık-kaynak local config). disk-temizlik (2026-05-20, `~/.cache/huggingface` 29G KORU).

READY FOR HANDOVER
