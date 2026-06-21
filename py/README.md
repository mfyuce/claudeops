# claudeops — Python rewrite (TBD#8)

Bash `claudeops` (ROOT'taki, ~2270 satır) **CANLI fleet'i yönetiyor ve KALIYOR** (guard cron, handover hepsi ona bağlı). Bu Python sürümü **yanında** büyüyor ve komut-komut devralıyor — bitince root'a terfi eder.

## Neden (2026-06-21 gecesi somut yaşandı)
Bash >2200 satır kırılgan: proc-match anchor bug (hc53≠hcr53 trailing-space), cwd-türetme bug (yanlış dizinde spawn), dup yarışı, her yere serpili `python3 -c` inline, quoting cehennemi, tip/test yok. → [[mass-faz1-ratelimit-stuck]], DONE.md 2026-06-21.

## Çalıştır
```bash
py/cops list              # tüm session'lar + CPU + dup kontrol
py/cops ls --suffix 54    # sadece *54
py/cops ls --base hc      # sadece hc*
```
Bağımlılık: `psutil` (kurulu, 5.9). Python 3.10+.

## Yapı
```
py/claudeops/
  paths.py        # tüm sabit yollar (tek kaynak)
  session.py      # Session dataclass (name/base/suffix/cpu/active...)
  discovery.py    # find_sessions() — psutil ile proc keşfi (ps|grep'in yerine)
  cli.py          # argparse + komut dağıtımı (COMMANDS listesi)
  commands/ls.py  # ilk komut: list (read-only)
cops              # bash wrapper → python3 -m claudeops
```

## Tasarım ilkeleri (bash'in derslerinden)
- **psutil cmdline = LİSTE** → quoting/anchor/substring tuzağı yok (bash'in baş belası).
- **CPU birinci sınıf** → session.json status/bridge GECİKMELİ, ona güvenme; CPU gerçek.
- **cwd = `psutil.Process.cwd()`** → /proc readlink + encoding türetmesi yok.
- **incremental** → her komut bash'le aynı davranışı vermeli, canlıya karşı test edilmeli.

## Porting yol haritası (öncelik sırası)
- [x] **proc-discovery + `list`** (read-only, en sık + en kırılgan parça)
- [ ] **config doğrulama** (`~/.claude.json` json.load — bozuksa resume-hang; bash'in tek gerçek STOP sinyali)
- [ ] **roster/models/suffix okuma** (paths.py'den TSV parse)
- [ ] **kill (nazik)** — SIGTERM + ~8-10s grace + sadece canlıysa SIGKILL ([[claude-2183-conversation-truncation]] truncation fix'i; psutil `wait(timeout)` ile temiz)
- [ ] **guard** (eksik session'ları tespit + nazik respawn; guard.lock; dup-safe)
- [ ] **rc / spawn** (gnome-terminal subprocess; --new/--resume; **throttle/batch** built-in [[mass-faz1-ratelimit-stuck]], TODO-v)
- [ ] **handover** (Faz1 proc-presence başarı kriteri; guard.lock KESİNTİSİZ; gruplara böl)
- [ ] **stuck-detect + recovery** (jsonl son=user + düşük CPU; otomatik tek-tek retry)
- [ ] **layout** (xdotool; en son — Wayland'da çalışmaz zaten)

## Durum (2026-06-21)
İlk iskelet + `list` çalışıyor, canlı 27-session fleet'e karşı test edildi. Sonraki: config doğrulama + kill (nazik) → guard. Bash'e DOKUNMA.
