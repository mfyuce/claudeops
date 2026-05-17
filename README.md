# claudeops

Açık Claude CLI session'larını toplu yönetir. Bu konuşmayı (`$$` ata zincirinden bulduğu kendi claude pid'i) **her zaman korur, dokunmaz**.

## Kurulum

```bash
chmod +x ./claudeops
# opsiyonel: PATH'e ekle
ln -s "$(pwd)/claudeops" ~/.local/bin/claudeops
```

Gereksinimler:
- `bash`, `python3` (her zaman)
- `claude` (her zaman — `~/.local/bin/claude` veya `npm` global)
- `gnome-terminal` (sadece visible mode)
- `wmctrl` (sadece `layout` komutu için)
- `gsettings` (sadece `desktops` komutu için)
- `xdotool` (Mutter snap workaround + initial prompt auto-submit için)

Kurulum (Ubuntu):
```
sudo apt install -y wmctrl xdotool
```

**Neden xdotool gerekli?**
- Mutter X11 `wmctrl -t` ve `xprop _NET_WM_DESKTOP` ClientMessage'larını bazen yoksayıyor → pencere taşıma flakey
- Interactive `claude --remote-control NAME prompt` positional prompt'u input box'a pre-fill ediyor ama submit ETMİYOR → Enter manuel gerek
- xdotool ile `windowactivate + type + key Return` ile bu iki sorun da çözülür

## Hızlı başlangıç

```bash
claudeops self                       # bu konuşmanın pid, sid, bridge URL'i
claudeops list                       # tüm session'lar
claudeops list all-but-self          # self hariç (recommended)

claudeops desktops 5                 # 5 workspace sabit
claudeops layout grid 4 --pin=rustrino13,sqli13  # pin'liler ws=0'a, 4'erli grid

claudeops kill all-but-self          # hepsini SIGTERM
claudeops compact all-but-self --backup
claudeops rc all-but-self            # gnome-terminal'de RC ile aç
claudeops rc rve13 --rename=rve14    # aynı sessionId ama yeni isim
claudeops rc all-but-self --suffix=14  # toplu suffix değişimi
claudeops rc emrgence13 --new        # yeni boş session
claudeops send all-but-self -- "/clear"   # slash command
claudeops send hms13 -- "yarın paper'a dönelim mi?"

claudeops batch all-but-self         # full pipeline
claudeops new myname /home/fatihyuce/work/projects/xyz
```

## Hedef syntax

| Form | Anlamı |
|---|---|
| `all` | **Tüm** session'lar (self DAHİL — dikkat!) |
| `all-but-self` / `notself` | Self hariç hepsi (varsayılan & güvenli) |
| `<name1> <name2> ...` | TSV `name` alanında eşleşenler (self otomatik hariç) |

## Önemli notlar (yaşanmış bug ve fix'ler)

1. **stdin leak**: `while read ... do ... done < file` döngüsünde `claude -p` çağrıları stdin'i miras alır ve TSV içeriği prompt'a sızar. Çözüm: `claude ... < /dev/null` (zaten script içinde).
2. **Slash command'lar `-p` mode'da çalışır**: `claude -p "/compact"` gerçekten compact yapar. Disk boyutu kısalmaz, **token kullanımı azalır** çünkü resume sırasında `"isCompactSummary":true` markerlı entry'den ileri sayılır.
3. **Self protection**: `find_self_claude_pid` `$$`'tan ata zincirini yürüyüp ilk `claude` binary'sini bulur. Hardcoded pid yok.
4. **Detached vs Visible**: detached için `nohup setsid script -qfc 'claude ...' /tmp/log </dev/null >/dev/null 2>&1 &`. Görünür için `gnome-terminal --window --title=... -- bash -c "claude ...; exec bash"` (bash exec ile pencere claude exit etse de kapanmaz).
5. **Rate limit**: 5-saatlik usage limit; assistant yanıtında `"You've hit your limit · resets ..."` görürsün. compact döngüsü bu pattern'de durur.
6. **Bridge URL session'a sabit**: kill+resume sonrası aynı URL geçerli (bridgeSessionId).

## Klasör içeriği

- `claudeops` — tek dosya bash script
- `README.md` — bu dosya
- `CLAUDE.md` — proje context (gelecek Claude session'ları için)
- `TODO.md` — açık iş kalemleri
- `DONE.md` — tamamlananlar log'u
- `TOBEDECIDED.md` — kullanıcı kararı bekleyen sorular

## Geri dönüş

Yedek almak için: `claudeops compact ... --backup` veya `claudeops batch ...` (batch zaten backup yapar). Her jsonl yanına `.bak.YYYYMMDD-HHMMSS` yazılır. Geri dönmek: `mv <sid>.jsonl.bak.X <sid>.jsonl`.
