# claudeops

*[English](README.md) · Türkçe*

Birden fazla proje klasöründe açık Claude Code oturumlarını tek yerden yönetir: kimin çalıştığını gör,
tek tıkla başlat/durdur, isterse telefondan bile.

![claudeops web paneli](docs/web-panel.png)

```bash
git clone https://github.com/mfyuce/claudeops.git && cd claudeops
pip install -r py/requirements.txt
py/cops web            # → http://127.0.0.1:8765
```

Detaylı kurulum, `web` panelinin tüm özellikleri ve komut listesi: **[`py/README_TR.md`](py/README_TR.md)**.

MIT lisanslı — bkz. [`LICENSE`](LICENSE).

## Neler yapabilir

**Fleet yönetimi**
- Her proje klasöründeki her açık Claude Code session'ını tek yerden takip et
- Session başına birden fazla CLI backend'i — Claude Code, Google'ın Antigravity/Gemini CLI'ı,
  ya da düz interaktif bir shell (`sudo` ve gerçek bir TTY isteyen her şey için) — pluggable, backend
  başına bir dosya, yeni bir tane eklemek küçük/izole bir değişiklik
- Herhangi bir session'ı başlat / durdur / öldür / kalıcı devre dışı bırak / emekli et / tekrar işe al
- Duplicate-session tespiti
- Crash recovery: roster'da olup çalışmayan session'ları tespit edip aç (opsiyonel, varsayılan kapalı —
  bu proje varsayılan olarak elle, tek tek kontrolü tercih ediyor)
- Takılı kalmış (idle ama meşgul görünmesi gereken) session tespiti + tek tıkla kurtarma
- 3 fazlı handover: wrap-up mesajı → kill & taze respawn → pencereleri masaüstlerine dağıt
- Git-farkında "bu session'ın handover'a ihtiyacı var mı" kontrolü (kirli ağaç, untracked dosyalar,
  push'lanmamış commit'ler, eksik özet)

**Web kontrol paneli** (`py/cops web`)
- Sadece Python standart kütüphanesiyle çalışır — ekstra bağımlılık kurmaya gerek yok
- Token korumalı, Cloudflare tunnel ile telefonundan erişilebilir (rastgele quick-tunnel ya da kendi
  domain'inde sabit bir URL)
- Çalışanlar / Kayıtlı / Devre dışı / Emekli sekmeleri, checkbox'larla toplu işlemler
- Herhangi bir session'ı model / permission-mode / effort / resume-veya-fresh seçenekleriyle başlat
- Yeni projeleri doğrudan tarayıcıdan kaydet
- **Herhangi bir session için canlı, gömülü terminal** — gerçek çıktıyı gör, gerçek girdi yaz, `sudo`
  parola sorması dahil (**work in progress**: çalışıyor ama mobilde birkaç pürüz var — resize/scroll
  henüz tam pürüzsüz değil)
- Mobil-uyumlu tasarım
- Tanı sekmesi: tek-tıkla spawn sağlık testi, terminal-server restart, son loglar hakkında "LLM'e sor"

**Kendi kendine ayakta kalır**
- `py/cops service install` — systemd kalıcılığı: panel ve tunnel logout/reboot'ta hayatta kalır,
  çökerse kendini toplar
- `py/cops service notify` — tunnel URL'i GERÇEKTEN değiştiğinde ([ntfy.sh](https://ntfy.sh) üzerinden,
  hesap gerekmez) telefonuna push bildirimi, ör. `claudeops tunnel: https://random-words.trycloudflare.com`
  — ulaşması garanti değil (Android arka-plan kısıtlamaları, ntfy.sh'nin kısa sunucu-taraflı saklama
  süresi), detay/kısıtlar için `py/README_TR.md`
- `py/cops service watchdog` — işletim sisteminin kendi bellek-baskısı katili (`oomd`) TÜM oturumunu
  (sadece claudeops'u değil) alaşağı ederse onu geri getiren root-seviyeli bir timer

**Komut satırı** (`py/cops <komut>`, her birinin kendi `--help`'i var)
`list · kill · close · config · guard · rc · handover · stuck · layout · web · service`

---

Repoda ayrıca `claudeops` adında eski bir **bash** script var (aşağıda anlatılıyor) — ilk sürüm buydu,
artık sadece birkaç legacy komut için tutuluyor. Canlı fleet yönetiminin tamamı (`guard`/`rc`/`handover`/`web`)
Python sürümünde; yeni başlıyorsanız yukarıdaki `py/cops`'u kullanın.

## Kurulum (bash `claudeops`, legacy)

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

- `py/` — aktif geliştirilen Python sürümü (`py/cops`), bkz. [`py/README_TR.md`](py/README_TR.md)
- `claudeops` — eski/legacy tek dosya bash script
- `LICENSE` — MIT
- `README.md` / `README_TR.md` — İngilizce / Türkçe
- `CLAUDE.md` — proje context (gelecek Claude session'ları için)
- `TODO.md` — açık iş kalemleri
- `DONE.md` — tamamlananlar log'u
- `TOBEDECIDED.md` — kullanıcı kararı bekleyen sorular

## Geri dönüş

Yedek almak için: `claudeops compact ... --backup` veya `claudeops batch ...` (batch zaten backup yapar). Her jsonl yanına `.bak.YYYYMMDD-HHMMSS` yazılır. Geri dönmek: `mv <sid>.jsonl.bak.X <sid>.jsonl`.
