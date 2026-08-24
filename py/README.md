# claudeops — Python rewrite (TBD#8)

Bash `claudeops` (ROOT'taki, ~2270 satır) **CANLI fleet'i yönetiyor ve KALIYOR** (guard cron, handover hepsi ona bağlı). Bu Python sürümü **yanında** büyüyor ve komut-komut devralıyor — bitince root'a terfi eder.

## Neden (2026-06-21 gecesi somut yaşandı)
Bash >2200 satır kırılgan: proc-match anchor bug (hc53≠hcr53 trailing-space), cwd-türetme bug (yanlış dizinde spawn), dup yarışı, her yere serpili `python3 -c` inline, quoting cehennemi, tip/test yok. → [[mass-faz1-ratelimit-stuck]], DONE.md 2026-06-21.

## Kurulum
```bash
pip install -r py/requirements.txt   # sadece psutil
```
Python 3.10+. `web --tunnel` için `cloudflared` gerekir — kurulu değilse otomatik indirilir
(`~/.local/bin/cloudflared`, sadece Linux amd64/arm64; başka platformda elle kurun).
`layout` için `wmctrl` + `xdotool` gerekir (Ubuntu/Debian: `sudo apt install -y wmctrl xdotool`) —
eksikse `web` panelinde uyarı çıkar, komut da hata mesajıyla söyler.

## Çalıştır
```bash
py/cops list                       # tüm session'lar + CPU + dup kontrol
py/cops ls --base hc               # sadece hc*
py/cops web                        # yerel kontrol paneli, http://127.0.0.1:8765
py/cops web --tunnel               # + cloudflared quick-tunnel (uzaktan erişim)
```

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
- [x] **close** — session'ı kalıcı kapat (kill + models.tsv comment, guard tekrar açmaz)
- [x] **web** — yerel kontrol paneli (`--tunnel` ile cloudflared quick-tunnel): roster'ın tamamını
      (aktif/kapalı/emekli) gösterir, tek tek başlat (model/permission-mode/effort/fresh seçenekli)
      / durdur / emekli et / tekrar işe al / ayrı yeni chat aç / layout uygula — mass-start yok,
      token-gated. Bkz. `commands/web.py` docstring.

## Durum
Komutlar: `list`, `config`, `kill`, `close`, `guard`, `rc`, `handover`, `stuck`, `layout`, `web`.
Bash `claudeops` (ROOT) hâlâ ayakta ama artık sadece `layout` + eski komutlar için; canlı fleet
yönetimi (`guard` cron, `rc`, `handover`, `web`) tamamen bu Python sürümünde.
