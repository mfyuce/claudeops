# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Self Protection

`find_self_claude_pid` sırayla:
1. **`$CLAUDE_CODE_SESSION_ID` env var** — Claude TUI çocuklara geçirir. Nohup-detached'te tek güvenilir yol.
2. **Fallback: `$$` ata zinciri** — interactive shell'lerde.

`all-but-self` buna bağlı. Self'i ASLA hedef almaz default'ta.

## Önemli teknik kararlar (kod-okumakla anlaşılmaz)

- **stdin redirect** `< /dev/null`: `claude -p` her çağrıda zorunlu (stdin leak fix).
- **`script -qfc` ile detached pty**: `nohup &` yetmez, Claude TUI gerçek terminal ister.
- **Visible window**: `gnome-terminal -- bash -c "claude ...; exec bash"` (claude exit etse pencere bash'a düşer).
- **wmctrl -s vs xprop**: Sadece `wmctrl -s N` Mutter'da görsel switch tetikler.
- **VTE keystroke rejection**: synthetic key (`xdotool type`/`key Esc/Return`) çoğu zaman REDDEDİLİYOR. Güvenilir prompt enjeksiyonu: **CLI argümanı** — `claude ... -n NAME --remote-control NAME 'PROMPT'` başlangıçta otomatik çalışır (Enter'sız). Idle/stuck session'a iş yaptırmak → kill + bu şekilde fresh-spawn.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` display, `--remote-control` RC bridge.
- **Bridge cache (server-side)**: aynı sid resume → RC name cache'li. Değiştirmek için `--new`.
- **Layout in-place**: `xdotool windowmove` (**`--sync` YOK** — pencere zaten hedefteyse ConfigureNotify gelmez, ~15s hang) + desktop-grouped (`wmctrl -s` + `get_desktop` verify; pencere görünür değilse yanlış taşır) + read-back doğrula. Konum doğrulaması `xdotool getwindowgeometry` ile (wmctrl -G 2× raporluyor, güvenilmez).

## Model-permission konvansiyonu

- **Hepsi → `--permission-mode=auto`** (2026-05-25: sonnet'e de auto geldi; eskiden sonnet=acceptEdits idi).
- Model hâlâ ayrı: opus grubu `--model=opus`, sonnet grubu `--model=sonnet`. Permission uniform (auto).

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2]

# Faz 2 — fresh respawn (--prompt opsiyonel; idle açılır)
./claudeops rc hms<F> hve<F> oa<F> qve<F> rve<F> carla<F> emrgence<F> rr<F> araroot<F> aggroot<F> gedikvm<F> gedikido<F> kulturiot<F> \
  --suffix=<TO> --new --kill-first --model=opus --permission-mode=auto

./claudeops rc anomaly<F> rustrino<F> mecdtfl<F> vrk<F> hc<F> hcr<F> mo<F> \
  --suffix=<TO> --new --kill-first --model=sonnet --permission-mode=auto

# Faz 3 — layout (self/co otomatik ws0'a pinlenir)
./claudeops layout grid 4 --pin=anomaly<TO>,rustrino<TO>
```

**Flag'ler:** `handover --force` (skip [done/idle/dirty] baypas, hepsine; jsonl yoksa fresh-spawn) · `handover --layout [--pin=a,b]` (spawn'lar bitince oto-tile) · `claudeops cancel <names>` (stuck modal'a Esc; inmezse `rc <name> --kill-first`).
**Skip kriteri (done):** jsonl'de RFH var + son RFH'den sonra yeni istek yok + repo temiz. `repo_dirty` untracked saymaz; dirty = tracked-modified **veya** TÜM remote'lardan birine unpushed (sadece `@{u}` değil — çift remote github+gitlab) **veya** behind (remote ileride = başkası push etmiş). Pre-check session başına 1× `git fetch --all` (timeout 20s) → ref'ler taze.
⚠ Target listesi **SPACE-separated** (virgül parse bug — TODO). rc orphan → WARN + `claudeops new`.
Detay/why: memory `handover-procedure.md` + `handover-edge-cases.md`.

## Bilinen sınırlamalar

- **Wayland**: layout çalışmaz (wmctrl X11-only).
- **Terminal**: gnome-terminal hard-coded.
- **Permission/modal prompt**: RC'yi bloklar; `cancel` Esc gönderir ama VTE reddedebilir → garantili iptal = `rc --kill-first` (respawn).
- **Multi-monitor**: in-place layout artık xdotool no-sync ile çalışıyor; `--reopen` (kill+respawn) opsiyonel alternatif.
- **`rc <a,b,c>` virgül**: parse yok; SPACE kullan (TODO).
- **Layout orphan terminal**: window-name validation eksik — orphan bir quad slot işgal ediyor (TODO).

## Meta

- `DONE.md` = de facto CHANGELOG.
- `desktops.local.md` = layout snapshot (gitignored).
- Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.

### Handover-prep MD sync (her "yeni session hazirlik"/ho'da yap)
- **(1) TODO→DONE:** TODO.md'de olup gerçekte tamamlanmış maddeleri DONE.md'ye taşı + TODO.md'den **sil** (tek kaynak, çift kayıt yok).
- **(2) TOBEDECIDED→TODO:** TOBEDECIDED.md'de olup artık karar verilip TODO'ya geçmiş kalemleri TODO.md'ye taşı + TOBEDECIDED.md'den **sil**.

## READY FOR HANDOVER (2026-05-28)

**Nerede kaldık:** co22 (claudeops repo). **27→28 transition tamam**: opus 13 (hms, hve, oa, qve, rve, carla, emrgence, rr, araroot, aggroot, gedikvm, gedikido, kulturiot) + sonnet 7 = 20 28-session + co22(self), hepsi idle `--permission-mode=auto`. trroot28 kapalı. Layout temiz, co22 ws0'a pinli. HEAD origin+gitlab sync.

Bu oturumda (detay: DONE.md 2026-05-28): 26→27 TODO-loop handover + 27→28 standard handover; araroot28 + aggroot28 opus grubuna eklendi; trroot28 simdilik kapatıldı.

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[handover-procedure]] + [[handover-edge-cases]] + [[feedback-calisma-tarzi]].
2. **Açık TODO bug'lar:** (a) `rc <a,b,c>` virgül parse, (b) layout orphan terminal, (c) `cancel` Esc → respawn fallback.
3. **TOBEDECIDED #5** karar bekliyor (açık-kaynak local config seçimi).

**Açık kararlar:** disk-temizlik (2026-05-20) onay bekliyor (`~/.cache/huggingface` 29G KORU).

READY FOR HANDOVER
