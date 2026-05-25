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
- **VTE keystroke rejection**: synthetic key'leri reddediyor. xdotool `type` çoğunlukla geçer, permission dialog intermittent.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` display, `--remote-control` RC bridge.
- **Bridge cache (server-side)**: aynı sid resume → RC name cache'li. Değiştirmek için `--new`.
- **claude path encoding**: `~/.claude/projects/<cwd>` cwd `tr '/_' '-'`.

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

# Faz 3 — layout
./claudeops layout grid 4 --pin=anomaly<TO>,rustrino<TO>
```

⚠ Target listesi **SPACE-separated** (virgül parse bug — TODO).
⚠ rc orphan (mevcut olmayan target) → WARN + manuel `claudeops new` (memory: handover-edge-cases case 3).
Detay/why: memory `handover-procedure.md` + `handover-edge-cases.md`.

## Bilinen sınırlamalar

- **Wayland**: layout çalışmaz (wmctrl X11-only).
- **Terminal**: gnome-terminal hard-coded.
- **Rate-limit reset**: parse edilmiyor (TODO).
- **Permission prompt auto-submit**: VTE/Ink reject — keystroke intermittent.
- **Multi-monitor snap**: `--reopen` ile workaround.
- **`rc <a,b,c>` virgül**: parse yok; SPACE kullan (TODO).
- **Layout orphan terminal**: window-name validation eksik (TODO).

## Meta

- `DONE.md` = de facto CHANGELOG.
- `desktops.local.md` = layout snapshot (gitignored).
- Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.

## READY FOR HANDOVER (2026-05-24)

**Nerede kaldık:** co22 (bu konuşma, opus, claudeops repo). 21→22 transition tamam: 19 22-session + co22 = 20 idle. Faz 1: 18/19 wrap-up'd (emrgence21 idle-only skip — script artık otomatik). Faz 2: 18 rc fresh + emrgence22 manuel (orphan case). Faz 3: layout 6 ws, 20 pencere clean, orphan yok. 2 script fix push'landı bu round'da: idle-only auto-skip (`74a32d7`) + rc orphan WARN (`8976ec3`). HEAD `8976ec3` origin+gitlab sync (commit edilmemiş bu wrap-up dahil).

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[handover-procedure]] + yeni [[handover-edge-cases]] (3 case: idle-only, server bridge cache, orphan target).
2. **Açık TODO bug'lar:** (a) `rc <a,b,c>` virgül parse, (b) layout orphan terminal validation.
3. **Model→permission-mode auto-mapping** hâlâ TODO.

**Açık kararlar:** disk-temizlik aday listesi (2026-05-20) onay bekliyor (`~/.cache/huggingface` 29G KORU). Multi-monitor snap için ekran kilidi hipotezi henüz test edilmedi.

READY FOR HANDOVER
