# claudeops — Claude Context

## Bu Repo

Açık Claude CLI session'larını toplu yönetmek için tek-dosya bash CLI. 2026-05-16/17 gecesi 14 paralel session compact + RC + visible-window operasyonundan doğdu. Yaşanan bug'lar script'te fix'li.

## Self Protection

`find_self_claude_pid` sırayla:
1. **`$CLAUDE_CODE_SESSION_ID` env var** — Claude TUI çocuk process'lere geçirir. Nohup-detached script'lerde tek güvenilir yol.
2. **Fallback: `$$` ata zinciri** — interactive shell'lerde.

`all-but-self` syntax buna bağlı. Self'i ASLA hedef almaz default'ta.

## Önemli teknik kararlar

- **Tek dosya bash**: Python wrapper yok. python3 sadece JSON parse.
- **stdin redirect** (`< /dev/null`): `claude -p` her çağrıda zorunlu (stdin leak fix).
- **`script -qfc` ile detached pty**: `nohup &` yetmez, Claude TUI gerçek terminal ister.
- **Compact doğrulaması**: `claude -p "/compact"` sessizdir. Başarı kanıtı: jsonl'de `"isCompactSummary":true` count +1.
- **Visible window**: `gnome-terminal -- bash -c "claude ...; exec bash"` (claude exit etse bile pencere bash'a düşer).
- **wmctrl -s vs xprop**: Sadece `wmctrl -s N` Mutter'da görsel switch tetikler. xprop sadece property set.
- **Mutter multi-monitor snap bug**: in-place `wmctrl -e` çoklu-monitor'da yanlış snap'liyor. Çözüm: `--reopen` (kill + switch + spawn-on-current).
- **VTE keystroke rejection**: gnome-terminal synthetic key'leri reddediyor. xdotool `type` çoğunlukla geçer, permission dialog intermittent.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` session display, `--remote-control` RC bridge. Doğru: `claude -n NAME --remote-control NAME 'prompt'`.
- **Bridge cache (server-side)**: aynı sessionId resume edilince RC name değişmez. Değiştirmek için `--new`.
- **claude path encoding**: `~/.claude/projects/` altında cwd `tr '/_' '-'`.

## Model-permission mode (manuel — otomatik mapping TODO)

- **Opus → `--permission-mode=auto`** (classifier-based)
- **Sonnet → `--permission-mode=acceptEdits`** (Edit/Write auto, Bash hâlâ onay)

## Komut özeti

```bash
claudeops self | list | kill all-but-self
claudeops compact all-but-self --backup
claudeops rc <names> --suffix=N --new --kill-first --model=opus --permission-mode=auto [--prompt=devam]
claudeops handover --from-suffix=N [--exclude=name1,name2]
claudeops send <name> -- <prompt>       # /context: send <name> -- "/context"
claudeops migrate <name> --to=<cwd> --gh --glab
claudeops layout grid 4 --pin=anomaly,rustrino [--reopen]
claudeops desktops N
```

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, prefilled, idle pre-check, sıralı)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2,...]

# Faz 2 — fresh respawn (--prompt opsiyonel; verilmezse idle)
./claudeops rc hms<F> hve<F> oa<F> qve<F> rve<F> carla<F> emrgence<F> rr<F> trroot<F> \
  --suffix=<TO> --new --kill-first --model=opus --permission-mode=auto

./claudeops rc anomaly<F> rustrino<F> mecdtfl<F> vrk<F> hc<F> hcr<F> mo<F> \
  --suffix=<TO> --new --kill-first --model=sonnet --permission-mode=acceptEdits

# Faz 3 — layout
./claudeops layout grid 4 --pin=anomaly<TO>,rustrino<TO>
```

⚠ Hedef listesinde **SPACE-separated** (virgül parse bug — TODO).
Detay/why: `~/.claude/projects/-home-.../memory/handover-procedure.md`.

## Geliştirme notları

- Script bağımsız test edilebilir; kill/compact/rc default'ta self'i ASLA hedef almaz.
- `cmd_send` `<targets> -- <prompt>` formatında parse eder.
- Bu repo "CHANGELOG.md" kullanmıyor — `DONE.md` o rolü oynuyor.

## Bilinen sınırlamalar

- **Wayland**: layout çalışmaz (wmctrl X11-only).
- **Terminal emülatör**: gnome-terminal hard-coded; kitty/alacritty için parametrize TODO.
- **Rate-limit reset**: parse edilmiyor, sadece tespit edip durdurur (TODO).
- **Permission prompt auto-submit**: VTE/Ink synthetic event reject — keystroke landing intermittent.
- **Multi-monitor snap**: `--reopen` ile workaround (in-place buggy).
- **`rc <a,b,c>` virgül-separated**: parse edilmiyor; SPACE kullan (TODO).
- **Layout orphan terminal**: window-name validation eksik (TODO).

## READY FOR HANDOVER (2026-05-24)

**Nerede kaldık:** co22 (bu konuşma, opus, claudeops repo). Working tree clean, HEAD `476e506` origin+gitlab sync. 16 aktif 21-session canlı (sqli SKIP). Layout state: `desktops.local.md` güncel — ws0 pin=anomaly21+rustrino21, ws1=co22(self)+orphan+hms21+hve21, ws2=oa21+qve21+rve21+trroot21, ws3=carla21+emrgence21+rr21+mecdtfl21, ws4=vrk21+hc21+hcr21+mo21. Bu session'da net iş yok — sadece /rename co21→co22 ve CLAUDE.md slim. 20→21 transition tarihçesi `DONE.md` (2026-05-23 bloğu).

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — özellikle [[handover-procedure]] (3-fazlı zincir, `--exclude` flag + `--prompt` opsiyonel notları).
2. **TODO.md kritik bug'lar hâlâ açık:** (a) `rc` virgül-separated parse, (b) layout orphan terminal. İkisi de 20→21'de tekrar gözlendi.
3. **Model→permission-mode otomatik mapping** hâlâ TODO.

**Açık kararlar:** disk-temizlik aday listesi (2026-05-20) onay bekliyor (`~/.cache/huggingface` 29G KORU). Multi-monitor snap için ekran kilidi hipotezi henüz test edilmedi.

READY FOR HANDOVER
