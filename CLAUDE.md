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
- **Compact doğrulaması**: `claude -p "/compact"` sessiz. Başarı: jsonl `"isCompactSummary":true` count +1.
- **Visible window**: `gnome-terminal -- bash -c "claude ...; exec bash"` (claude exit etse pencere bash'a düşer).
- **wmctrl -s vs xprop**: Sadece `wmctrl -s N` Mutter'da görsel switch tetikler.
- **VTE keystroke rejection**: synthetic key (`xdotool type`/`key Esc/Return`) çoğu zaman REDDEDİLİYOR. Güvenilir prompt enjeksiyonu: **CLI argümanı** — `claude ... -n NAME --remote-control NAME 'PROMPT'` başlangıçta otomatik çalışır (Enter'sız). Idle/stuck session'a iş yaptırmak → kill + bu şekilde fresh-spawn.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` display, `--remote-control` RC bridge.
- **Bridge cache (server-side)**: aynı sid resume → RC name cache'li. Değiştirmek için `--new`.
- **claude path encoding**: `~/.claude/projects/<cwd>` cwd `tr '/_' '-'`.
- **Layout in-place**: `xdotool windowmove` (**`--sync` YOK** — pencere zaten hedefteyse ConfigureNotify gelmez, ~15s hang) + desktop-grouped (`wmctrl -s` + `get_desktop` verify; pencere görünür değilse yanlış taşır) + read-back doğrula. Konum doğrulaması `xdotool getwindowgeometry` ile (wmctrl -G 2× raporluyor, güvenilmez).

## Model-permission konvansiyonu

- **Hepsi → `--permission-mode=auto`** (2026-05-25: sonnet'e de auto geldi; eskiden sonnet=acceptEdits idi).
- Model hâlâ ayrı: opus grubu `--model=opus`, sonnet grubu `--model=sonnet`. Permission uniform (auto).

## Komutlar

Detay: `./claudeops help`. Tipik akış aşağıda (Handover).

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2]

# Faz 2 — fresh respawn (--prompt opsiyonel; idle açılır)
./claudeops rc hms<F> hve<F> oa<F> qve<F> rve<F> carla<F> emrgence<F> rr<F> trroot<F> gedikvm<F> gedikido<F> kulturiot<F> \
  --suffix=<TO> --new --kill-first --model=opus --permission-mode=auto

./claudeops rc anomaly<F> rustrino<F> mecdtfl<F> vrk<F> hc<F> hcr<F> mo<F> \
  --suffix=<TO> --new --kill-first --model=sonnet --permission-mode=auto

# Faz 3 — layout (self/co otomatik ws0'a pinlenir)
./claudeops layout grid 4 --pin=anomaly<TO>,rustrino<TO>
```

**Flag'ler:** `handover --force` (skip [done/idle/dirty] baypas, hepsine; jsonl yoksa fresh-spawn) · `handover --layout [--pin=a,b]` (spawn'lar bitince oto-tile) · `claudeops cancel <names>` (stuck modal'a Esc; inmezse `rc <name> --kill-first`).
**Skip kriteri (done):** jsonl'de RFH var + son RFH'den sonra yeni istek yok + repo temiz. `repo_dirty` untracked saymaz (sadece tracked-modified + unpushed).
⚠ Target listesi **SPACE-separated** (virgül parse bug — TODO). rc orphan → WARN + `claudeops new`.
Detay/why: memory `handover-procedure.md` + `handover-edge-cases.md`.

## Bilinen sınırlamalar

- **Wayland**: layout çalışmaz (wmctrl X11-only).
- **Terminal**: gnome-terminal hard-coded.
- **Rate-limit reset**: parse edilmiyor (TODO).
- **Permission/modal prompt**: RC'yi bloklar; `cancel` Esc gönderir ama VTE reddedebilir → garantili iptal = `rc --kill-first` (respawn).
- **Multi-monitor**: in-place layout artık xdotool no-sync ile çalışıyor; `--reopen` (kill+respawn) opsiyonel alternatif.
- **`rc <a,b,c>` virgül**: parse yok; SPACE kullan (TODO).
- **Layout orphan terminal**: window-name validation eksik — orphan bir quad slot işgal ediyor (TODO).

## Meta

- `DONE.md` = de facto CHANGELOG.
- `desktops.local.md` = layout snapshot (gitignored).
- Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.

## READY FOR HANDOVER (2026-05-25)

**Nerede kaldık:** co22 (bu konuşma, opus, claudeops repo). **23→24 transition tamam**: 19 24-session + co22(self) = 20 idle, hepsi `--permission-mode=auto`. Layout temiz (xdotool, ~14s), co22 ws0'a auto-pinli. HEAD `d0e954c` origin+gitlab sync.

**Bu oturumda eklenenler (hepsi push'lu, DONE.md 2026-05-25 blokları):**
- **Sonnet → auto** (convention "hepsi auto"; model hâlâ opus/sonnet ayrı)
- **Layout güvenilir+hızlı**: `--sync` hang fix (321s→~14s) + desktop-grouped + read-back verify + **self ws0 auto-pin**
- **`handover --force`** (skip baypas) + **`--layout`** (oto-tile) + **`claudeops cancel`** (modal Esc)
- **Skip kriteri**: RFH+sonrası-istek-yok+repo-temiz; **`repo_dirty` untracked saymaz**
- dirty-check fix limbo iş kurtardı (emergence + carla/anomaly/vrk → iki remote'a push)

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[handover-procedure]] + [[handover-edge-cases]] (idle-only, bridge cache, orphan, skip kriteri, layout reçetesi) + [[feedback-calisma-tarzi]] (background bekleme, layout hız).
2. **Açık TODO bug'lar:** (a) `rc <a,b,c>` virgül parse (kill/compact/send'de de), (b) layout orphan terminal validation, (c) `cancel` Esc güvenilmez → respawn fallback.

**Açık kararlar:** disk-temizlik aday listesi (2026-05-20) onay bekliyor (`~/.cache/huggingface` 29G KORU).

READY FOR HANDOVER
