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
- [x] **config doğrulama** (`~/.claude.json` json.load — bozuksa resume-hang; `py/cops config`)
- [x] **roster/models/suffix okuma** (paths.py'den TSV parse — `roster.py`)
- [x] **kill (nazik)** — SIGTERM + ~8-10s grace + sadece canlıysa SIGKILL (`kill.py` + `py/cops kill --dry-run`)
- [x] **guard** — eksik session tespit + spawn (base-name bazlı, models.tsv aktif filtre, guard.lock, dry-run)
- [x] **rc / spawn** — kill-first + respawn (--new/--resume, --one-by-one throttle, --prompt, dry-run)
- [x] **handover** — Faz 1 (kill+reopen+msg, batch throttle, proc-presence başarı kriteri, co+ulaksec exclude)
- [x] **stuck-detect + recovery** — jsonl son=user + CPU<2% tespiti; --recover ile kill+resume
- [x] **layout** — xdotool tile (pin/group/desktop dağıtımı; X11 only, Wayland çalışmaz)

## Durum (2026-06-22)
**TÜM komutlar implement edildi**: `list`, `config`, `kill`, `guard`, `rc`, `handover`, `stuck`, `layout`. Roadmap tamamlandı. Bash'e DOKUNMA — canlı fleet hâlâ bash kullanıyor; Python testi dry-run ile yapılacak.
