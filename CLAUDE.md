# claudeops — Claude Context

## Bu Repo

Açık Claude CLI session'larını toplu yönetmek için tek-dosya bash CLI. 2026-05-16/17 gecesi 14 paralel session'ı compact + RC + visible-window olarak yeniden açma operasyonundan doğdu. Yaşanan tüm bug'lar script'te fix'li.

## Self Protection

`find_self_claude_pid` sırayla:
1. **`$CLAUDE_CODE_SESSION_ID` env var** — Claude TUI çocuk process'lere geçirir. Nohup-detached script'lerde tek güvenilir yöntem.
2. **Fallback: `$$` ata zinciri** — interactive shell'lerde.

`all-but-self` syntax'ı buna bağlı. Self'i ASLA hedef almaz default'ta.

## Önemli teknik kararlar

- **Tek dosya bash**: Python wrapper yok. python3 sadece JSON parse için.
- **stdin redirect** (`< /dev/null`): `claude -p` her çağrıda zorunlu (stdin leak fix).
- **`script -qfc` ile detached pty**: `nohup &` yetmez, Claude TUI gerçek terminal ister.
- **Compact doğrulaması**: `claude -p "/compact"` sessizdir. Başarı kanıtı: jsonl'de `"isCompactSummary":true` entry count +1.
- **Visible window**: `gnome-terminal -- bash -c "claude ...; exec bash"` (claude exit etse bile pencere bash'a düşer).
- **wmctrl -s vs xprop**: Sadece `wmctrl -s N` Mutter'da görsel switch tetikler (ClientMessage). xprop sadece property set eder.
- **Mutter multi-monitor snap bug**: in-place `wmctrl -e` çoklu-monitor'da yanlış snap'liyor. Çözüm: `--reopen` modu (kill + switch + spawn-on-current).
- **VTE keystroke rejection**: gnome-terminal synthetic XSendEvent key'leri reddediyor. xdotool `type` çoğunlukla geçer, permission dialog'lara intermittent.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` session display, `--remote-control` RC bridge name. Doğru: `claude -n NAME --remote-control NAME 'prompt'`.
- **Bridge cache (server-side)**: aynı sessionId resume edilince RC name değişmez. Değiştirmek için `--new` (fresh sessionId).
- **claude path encoding**: `~/.claude/projects/` altında cwd `tr '/_' '-'`.

## Model-permission mode (manuel — otomatik mapping TODO)

- **Opus → `--permission-mode=auto`**: classifier-based, esnek karar
- **Sonnet → `--permission-mode=acceptEdits`**: Edit/Write otomatik, Bash hâlâ onay ister

`--model=X` verince otomatik default eklemek TODO.

## Komut kalıpları

```bash
# Self-aware
claudeops self                            # bu konuşmayı tanı
claudeops list                            # tüm session'lar
claudeops kill all-but-self               # güvenli

# Compact (sequential, jsonl backup)
claudeops compact all-but-self --backup

# RC + visible: her session kendi gnome-terminal'inde
claudeops rc all-but-self                 # default visible
claudeops rc all-but-self --kill-first    # mevcut'u kapat (busy → idle bekler)
claudeops rc <names> --suffix=21 --new    # toplu rename + fresh sid
claudeops rc <names> --model=opus --permission-mode=auto [--prompt=devam]
# --prompt opsiyonel; verilmezse session idle açılır

# Handover (visible wrap-up + RC + reopen)
claudeops handover --from-suffix=20                       # tüm 20'leri wrap-up
claudeops handover --from-suffix=20 --exclude=name1,name2 # bazılarını skip

# Migrate (cwd taşıma + remote create + path rewrite)
claudeops migrate <name> --to=<new-cwd> --gh --glab

# Layout
claudeops desktops 6
claudeops layout grid 4 --pin=anomaly21,rustrino21
claudeops layout grid 4 --reopen --pin=...  # multi-monitor snap için
```

## Handover (3-fazlı zincir, "ho" istek)

```
# Faz 1 — wrap-up (visible, prefilled, idle pre-check, sıralı)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2,...]

# Faz 2 — fresh respawn (--prompt opsiyonel; verilmezse idle)
./claudeops rc hms<FROM> hve<FROM> oa<FROM> qve<FROM> rve<FROM> carla<FROM> emrgence<FROM> rr<FROM> trroot<FROM> \
  --suffix=<TO> --new --kill-first --model=opus --permission-mode=auto

./claudeops rc anomaly<FROM> rustrino<FROM> mecdtfl<FROM> vrk<FROM> hc<FROM> hcr<FROM> mo<FROM> \
  --suffix=<TO> --new --kill-first --model=sonnet --permission-mode=acceptEdits

# Faz 3 — layout
./claudeops layout grid 4 --pin=anomaly<TO>,rustrino<TO>
```

Detay/why: `~/.claude/projects/-home-.../memory/handover-procedure.md`.

## Geliştirme notları

- Script bağımsız test edilebilir; kill/compact/rc default'ta self'i ASLA hedef almaz.
- `cmd_send` `<targets> -- <prompt>` formatında parse eder.
- `/context` için: `claudeops send <name> -- "/context"`.

## Bilinen sınırlamalar

- **Wayland**: layout çalışmaz (wmctrl X11-only).
- **Terminal emülatör**: gnome-terminal hard-coded; kitty/alacritty için `cmd_rc` parametrize edilmeli (TODO).
- **Rate-limit reset**: parse edilmiyor, sadece tespit edip durduruyor (TODO).
- **Permission prompt auto-submit**: VTE/Ink synthetic event reject — keystroke landing intermittent. Mobile RC URL fallback.
- **Multi-monitor snap**: `--reopen` mod ile workaround (in-place buggy).
- **`rc <a,b,c>` virgül-separated**: parse edilmiyor; SPACE-separated kullan (TODO).
- **Layout orphan terminal**: window-name validation eksik, orphan terminal slot tüketebilir (TODO).

## READY FOR HANDOVER (2026-05-23 16:45)

**Nerede kaldık:**
- claudeops repo working tree (post-handover): `claudeops` (--exclude flag eklendi), `.gitignore` (*.local.md), `CLAUDE.md` (slim + bu handover bloğu), `TODO.md`, `DONE.md` modify. Commit edilecek.
- **20→21 transition tamamlandı (2026-05-23):** 16 active 21-session (9 opus auto: hms,hve,oa,qve,rve,carla,emrgence,rr,trroot + 7 sonnet acceptEdits: anomaly,rustrino,mecdtfl,vrk,hc,hcr,mo) + bu konuşma (co17/co21, claudeops repo, opus). sqli SKIP (kullanıcı isteği), sqli20 kill'lendi. Faz 2 respawn `--prompt` YOK ile yapıldı, hepsi idle açıldı.
- **Layout state:** ws0 pin=anomaly21+rustrino21, ws1=co17(self)+orphan+hms21+hve21, ws2=oa21+qve21+rve21+trroot21, ws3=carla21+emrgence21+rr21+mecdtfl21, ws4=vrk21+hc21+hcr21+mo21. num-workspaces=6. desktops.local.md güncel (gitignored).
- **mo session migrate edildi (2026-05-23):** /home/fatihyuce → /home/fatihyuce/work/projects/tmp/machine_ops, gh+glab private remote (https://github.com/mfyuce/machine_ops, https://gitlab.com/mfyuce/machine_ops). claudeops'a `migrate` komutu eklendi.

**Yeni session'ın (co21) yapması gerekenler:**
1. **MEMORY.md oku** — özellikle [[handover-procedure]] (3-fazlı zincir, --exclude flag dahil edilmeli), [[opus-auto-mode]], [[busy-kill-protection]].
2. **handover-procedure.md memory'sini güncelle** — `--exclude=` flag ve `--prompt` opsiyonel kullanım not edilmeli.
3. **Bu repodaki commit'i push'la** (henüz pushlanmadı; commit yapıldıktan sonra origin + gitlab).
4. **TODO.md kritik bug'lar hâlâ açık:** (a) rc virgül-separated parse, (b) layout orphan terminal. İkisi de 2026-05-23 transition'ında tekrar gözlemlendi.

**Açık kararlar / pending:**
- Model-spesifik default permission-mode otomatik mapping hâlâ TODO.
- Disk-temizlik aday listesi (2026-05-20) onay bekliyor; hâlâ silinmedi. `~/.cache/huggingface` 29G KORU.
- Multi-monitor snap bug için ekran kilidi hipotezi henüz test edilmedi.

READY FOR HANDOVER
