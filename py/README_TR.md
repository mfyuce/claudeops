# claudeops — Python (`py/cops`)

*[English](README.md) · Türkçe*

Birden fazla proje klasöründe, birden fazla Claude Code oturumunu tek yerden yönetmek için
küçük bir CLI + yerel web paneli. Her proje bir "roster" satırı (isim → klasör → model);
`py/cops web` bu roster'ı gösterip tek tek başlatma/durdurma sağlar.

Linux + X11 gerekir (`gnome-terminal`'e bağımlı) — WSL/headless/macOS/Windows desteklenmiyor.

## Kurulum

```bash
git clone https://github.com/mfyuce/claudeops.git
cd claudeops
pip install -r py/requirements.txt   # tek bağımlılık: psutil
```

Python 3.10+. `claude` CLI kurulu ve PATH'te olmalı.

## Hızlı başlangıç

```bash
py/cops list          # şu an çalışan session'ları göster
py/cops web            # kontrol paneli → http://127.0.0.1:8765
py/cops web --tunnel   # + telefondan/uzaktan erişim (cloudflared, ilk seferde otomatik kurulur)
```

## `py/cops web` — kontrol paneli

En kolay kullanım yolu; her şey tarayıcıdan:

![claudeops web paneli](../docs/web-panel.png)

- **Sekmeler** — **Çalışanlar / Kayıtlı / Devre dışı / Emekli / Layout / Tanı / Uzak Masaüstü** (aktif
  sekme sayfa yenilense de hatırlanır). Hiçbir şey otomatik açılmaz — Uzak Masaüstü sekmesinin daemon'ı
  da dahil, aşağıya bakın.
- **Çalışanlar** — tüm canlı session'lar, her satırda **checkbox**, tablonun üstünde **toplu işlem
  butonları**: *handover* / *durdur* / *devre dışı bırak* / *emekli et* seçili satırlara sırayla
  uygulanır — onay diyaloğu isimleri listeler, ilerleme ve hatalar satır satır raporlanır. Butonların
  altındaki kısa açıklama (legend) her işlemin ne yaptığını söyler. **ho? kolonu** session'ın
  *handover'a ihtiyacı var mı* gösterir (repo kirli / untracked dosya / baseline'dan beri commit /
  wrap-up yok), **needs-ho seç** butonu hepsini tek tıkla seçer.
- **durdur vs devre dışı vs emekli** — *durdur* sadece process/pencereyi kapatır (proje kayıtlı kalır —
  Kayıtlı sekmesinden devam ettirilir); *devre dışı bırak* ek olarak otomasyonun (guard) yeniden
  açmasını engeller (Devre dışı sekmesine taşınır, geri alınabilir); *emekli et* arşive kaldırır
  (Emekli sekmesi, "tekrar işe al" ile döner).
- **Terminal** — `tmux` ile açılmış (`-L cops`, ayrı bir socket) satırlarda **Terminal** butonu belirir:
  tarayıcıdan canlı çıktıyı izle + komut gönder (xterm.js render, ~200ms poll, artı Ctrl-C/Esc/ok tuşu
  butonları). `tmux` gerekir (`sudo apt install tmux`) — kurulu değilse session'lar yine sorunsuz açılır,
  sadece buton görünmez. Sadece tmux desteği eklendikten SONRA (yeniden) açılan session'lar bu butonu
  kazanır; hâlâ çalışan düz bir session bir sonraki respawn'da (handover/devral/durdur+başlat) kazanır.
  Gördüğünüz tmux'un kendi scrollback'i, CLI'ın kendi ekran çizimi değil — gerçek bir terminal
  penceresinde kaydırmaya göre biraz kayma normal (bilinen ince kusur, iyileştiriliyor), ama session her
  iki durumda da tamamen ulaşılabilir ve yönlendirilebilir kalır. Bu aynı zamanda bu butonu **her**
  CLI backend için çalıştıran şey — kendi uzaktan-erişim özelliği olmayan biri (agy'de yok) için bile —
  session'ı ulaşılabilir kılan claudeops'un kendi tmux katmanı, alttaki CLI'nın bunu desteklemesi gerekmiyor.
- **Kayıtlı** — kayıtlı-ama-durmuş projeler; **devam ettir** / **sıfırla (--new)** / **ayrı yeni chat
  aç** (otomatik tarih-isimli, model/permission-mode/effort seçenekli) ile başlatırsınız. **Yeni proje
  kaydet** formu (isim + klasör + model) bu sekmenin altında — elle dosya düzenlemeden roster'a ekler.
- **CLI seçimi (claude / agy)** — her başlat/kaydet/yeni-chat seçenek satırında bir **CLI** seçici var:
  session başına `claude` ya da `agy` (Google'ın Antigravity CLI'ı, `~/.local/bin/agy`'de kuruluysa)
  seçilebilir. Model/permission-mode/effort seçenekleri seçili CLI'ya göre otomatik değişir (agy'nin
  model listesi `agy models`'tan CANLI çekilir, sabit kodlanmaz). Bir session'ın CLI'ı çalışırken
  SABİTTİR — küçük bir rozet olarak gösterilir, değiştirilemez (yabancı bir proc'u devralmak onun
  zaten hangi CLI olduğunu korur — "bir claude proc'unu agy olarak devral" diye bir şey yok). claudeops'un
  isim vermediği bare `agy` proc'u `agy-<pid>` olarak görünür, diğer kayıtsız session'lar gibi devralınabilir.
  Şu anki seçenekler `claude` ve `agy`; arkasındaki provider mimarisi (aşağıda "Nasıl çalışır") gelecekte
  bir backend daha eklemeyi — mesela GitHub Copilot CLI, ya da başka herhangi bir CLI-tabanlı kodlama
  ajanı — bir provider dosyası daha yazmak haline getiriyor, yeniden yazım değil.
- **Devre dışı / Emekli** — geçici durdurulmuş / tamamen bırakılmış projeler; "tekrar işe al"la geri gelir.
- **Handover** — seçili çalışan session'lara wrap-up mesajı gönderir (dokümanları güncelle, commit+push
  et), her birini aynı geçmişle (`--resume`) + bu mesaj ilk mesaj olarak yeniden başlatır. Panel o an
  hangi dildeyse mesaj da o dilde gider, model de o proje için roster'da tanımlı model (session'ın o an
  interaktif olarak `/model` ile geçmiş olabileceği model değil). Kodda gömülü bir hariç-tutma listesi
  YOK — ne seçtiyseniz o çalışır; tek yerleşik koruma, bir session'ın kendisini yöneten CLI'ı asla
  öldürememesi.
- **Roster dışındaki session'lar da görünür** — claudeops'un AÇMADIĞI ama çalışan her şey (ör. bir
  proje klasöründe elle açtığınız çıplak `claude`) "kayıtsız" etiketiyle listede belirir, **devral**
  aksiyonuyla (seçtiğiniz isimle `--remote-control` ekleyip kaydet — bu pencereyi kapatıp aynı geçmişle
  yenisini açar, çünkü claudeops zaten bu pencereyi kendisi açmamıştı). Durdur/handover checkbox'larla
  diğer satırlar gibi çalışır.
- **Layout** — kendi sekmesinde; pencereleri masaüstlerine dağıtır (`wmctrl`+`xdotool`, X11 only).
  Kilitli ekranda veya Wayland'da bozuk çalıştığı bilindiği için **otomatik pre-flight kontrol** var —
  kilitliyse reddeder. Eksik bağımlılık varsa (Ubuntu/Debian: `sudo apt install -y wmctrl xdotool`)
  uyarır, kurmaz (sudo gerektirir). Kilitli ekran gerektiren TEK işlem bu — başlat/durdur/handover/
  devral/yeni-chat kilitli ekranda da sorunsuz çalışır (telefondan panele bağlanırken masaüstün kilitli
  olması sorun değil).
- **Tanı** — web-paneli/terminal-server uptime'ı, *pencereSİZ* açılmış session'ların listesi (yukarıdaki
  Terminal notundaki spawn-fallback durumu), tek-tıkla spawn sağlık testi, bir **gt-restart** butonu
  (sadece terminal-server process'ini yeniden başlatır — düz bir panel restart'ı bozuk olanı düzeltmez),
  bir `diag.log`, ve son loglara bakan gerçek/taze bir session açan (desteklenen herhangi bir CLI
  backend'i) + Terminal görünümlü bir **"LLM'e sor"** aksiyonu — gerçek bir sohbet, kayıtlı-dışı bir
  rapor değil.
- **Uzak Masaüstü** — kendi sekmesinde, talebe bağlı **Başlat**/**Durdur**'lu bir uzak masaüstü görünümü.
  Arka planda küçük bir Rust daemon'ı var (`rust/screenshare/`, ilk kullanımda derlenir — PATH'te Rust
  toolchain'i, `cargo`, gerektirir; kurulu değilse panelin geri kalanı sorunsuz çalışır, sadece bu sekme
  çalışmaz) — X11 ekranını yakalar (~2 fps JPEG) ve panelin geri kalanıyla AYNI token-korumalı bağlantı
  üzerinden akıtır; Durdur'a basınca arka planda hiçbir şey çalışmaya devam etmez. Bir **"Kontrolü Al"**
  anahtarı (**varsayılan KAPALI**, panel içi uyarı metniyle) fare/klavye/scroll/dokunmatik'i gerçek
  makineye yönlendirmeyi açar — telefonun ekran klavyesinin tetiklenmesi + Unicode metnin (Türkçe dahil)
  doğru gelmesi dahil. **Açmadan önce okuyun:** bu, makinenin GERÇEK fare ve klavyesini o an fiziksel
  olarak başında olan kişiyle paylaşır — X11 click/scroll'u imleç KONUMUNA göre yönlendirir, focus'a göre
  değil, yani eşzamanlı fiziksel kullanım uzak kontrolle çakışabilir (her click/scroll'dan önce taze bir
  `move` göndermek bunu azaltır, ortadan kaldırmaz). Görüntüleme kilitli ekranda bile çalışır; kilitli
  bir ekranda kontrolü açmak fiilen onu uzaktan açabilmek demektir — bu kasıtlı, bug değil. Modifier
  tuşları (Ctrl/Alt/Shift/Cmd) henüz iletilmiyor, bilerek (kaçan bir key-up gerçek makinede tuşu
  "takılı basılı" bırakabilir).
- **TR/EN** — tarayıcı diline göre otomatik seçilir (`navigator.language`), sağ üstteki butonlarla elle
  değiştirilip kalıcı hale getirilebilir (localStorage).
- **Token korumalı** (`~/.claude/claudeops/web.token`, ilk çalıştırmada rastgele üretilir) — sayfa da
  API de token olmadan 401 döner. `--tunnel` ile `cloudflared` quick-tunnel açılır (PATH'te yoksa
  `~/.local/bin`'e otomatik indirilir, Linux amd64/arm64).

### Telefondan erişim

<img src="../docs/web-panel-mobile.png" alt="claudeops web paneli mobilde" width="320">

Tablo dar ekranlarda uyum sağlıyor (model/tür sütunları gizlenir, action butonları kaydırmadan
erişilebilir kalır).

```bash
py/cops web --tunnel
```

Bu iki URL yazdırır:

```
claudeops web  →  http://127.0.0.1:8765/?token=<token>
  tünel  →  https://random-words-here.trycloudflare.com/?token=<token>
```

**İkinci URL** (`trycloudflare.com`) internet olan her yerden çalışır — VPN gerekmez, telefonun
bilgisayarla aynı Wi-Fi'de olmasına gerek yok. O URL'i (aynen) telefonunuza ulaştırın (kendinize
not/mesaj olarak gönderin, ya da [`qrencode`](https://packages.debian.org/search?keywords=qrencode)
kuruluysa `qrencode -t ansiutf8 "<url>"` ile terminalde taranabilir bir QR kod bastırın — Ubuntu/Debian:
`sudo apt install -y qrencode`; her şey lokalde kalır, URL üçüncü bir servise gitmez) ve telefonun
tarayıcısında açın.

Bilinmesi gerekenler:
- **Token** her yeniden başlatmada aynı kalır (aynı `~/.claude/claudeops/web.token` dosyası), ama
  **tünel URL'i her `--tunnel` çalıştırmasında değişir** — Cloudflare'in "quick tunnel"ı bu, hesap ya da
  domain gerektirmez ama sabit adresi de yoktur.
- Token'lı tam URL'i ("?token=..." dahil) şifre gibi düşünün — kimde bu varsa session'larınızı
  başlatıp durdurabilir. Herkese açık paylaşmayın, ekran paylaşımında görünür bırakmayın.

### Kalıcı çalıştırma (logout/reboot'ta hayatta kalır) + güncel URL'i bulma

```bash
py/cops service install     # systemd --user unit'lerini yazar, linger açar, ikisini de başlatır
py/cops service status      # ayakta mı? + güncel tunnel URL'i, tek bir yerden
py/cops service uninstall   # durdur + devre dışı bırak + unit'leri sil (linger'a dokunmaz)
```

Bu, iki `systemctl --user` unit'i kurar (`claudeops-web.service`, `claudeops-tunnel.service`,
`Restart=on-failure`) + `loginctl enable-linger $USER` (kimse login olmasa da çalışmaya devam etsinler
diye — hem "logout'ta durmasın" hem "boot'ta kendiliğinden başlasın" için şart). Unit'ler
`paths.REPO_DIR` + `sys.executable`'dan üretilir, yani `install` HERHANGİ bir checkout'ta/kullanıcıda
çalışır, sadece orijinal makinede değil. Güncel URL her zaman `~/.claude/claudeops/tunnel_url.txt`'te —
her restart'ta terminal çıktısını yeniden okumak yerine bakılacak tek, sabit yer burası.

Quick-tunnel URL'i her restart'ta değiştiği için, `py/cops service notify` URL GERÇEKTEN
değiştiğinde ([ntfy.sh](https://ntfy.sh) üzerinden, hesap gerekmez) telefonuna push bildirimi
atabilir — değişmediyse sessiz kalır:

```bash
py/cops service notify        # özel bir topic üretir, kurulum adımlarını yazdırır (ntfy app'i bir kere kur)
py/cops service notify --off  # kapat
```

Bir bildirim şöyle görünür: `claudeops tunnel: https://random-words-here.trycloudflare.com` —
`notify`'ın yazdırdığı topic adı (`claudeops-xxxxxxxx` gibi) ntfy app'inde aratıp ekleyeceğiniz şey.
**Zor yoldan öğrenilen bilinen kısıt:** telefona ulaşması garanti değil — Android'in kendi arka-plan
kısıtlamaları (pil optimizasyonu, ya da ntfy app'inin "Instant Delivery" ayarı kapalıysa) bir push'u
sessizce yutabilir, üstüne ntfy.sh sunucu tarafında mesajı sadece birkaç saat tutuyor — kaçırılan bir
bildirim app'i sonradan açarak da geri getirilemez. Bildirimi bir kolaylık olarak görün, güvenilir tek
kaynak olarak değil — bir push hiç ulaşmadıysa gerçek güncel URL yukarıda bahsedilen
`~/.claude/claudeops/tunnel_url.txt`'te.

Değinilmesi gereken bir başka arıza türü: Linux'ta `systemd-oomd`, bellek baskısı altında (sadece
claudeops'u değil) **tüm login oturumunuzu** (`user@<uid>.service`) öldürebilir — bu olunca hiçbir
`Restart=` politikası kurtaramaz, çünkü sizi kurtaracak olan şey zaten ölmüştür. `py/cops service
watchdog`, birkaç dakikada bir kontrol edip gerekirse oturumu yeniden başlatan küçük, **root-
seviyeli** bir systemd timer'ı kurar (bilerek kullanıcı oturumunuzun DIŞINDA — böylece bu senaryoya
hayatta kalır); bir kere sudo şifrenizi soracak:

```bash
py/cops service watchdog             # kurar (sudo şifresi ister)
py/cops service watchdog --uninstall # kaldırır
```

Hiç değişmeyen bir URL mü istiyorsunuz? Bunun için kendi domain'inizde bir Cloudflare **named tunnel**
gerekir — sadece sizin yapabileceğiniz, tek seferlik, tarayıcı gerektiren bir kurulum:

```bash
cloudflared tunnel login                        # tarayıcı açar, bir Cloudflare hesabı gerekir
cloudflared tunnel create claudeops             # ya da --tunnel-name'e ne verdiyseniz
cloudflared tunnel route dns claudeops panel.domaininiz.com
echo https://panel.domaininiz.com > ~/.claude/claudeops/tunnel_fixed_hostname.txt
```

`run-tunnel.sh` (tunnel unit'inin çalıştırdığı script) her başlangıçta `--tunnel-name` (varsayılan
`claudeops`) ile eşleşen bir named tunnel olup olmadığına bakar, varsa OTOMATİK kullanır — öncesinde de
sonrasında da servis/kod değişikliği gerekmez. Kurana kadar sessizce rastgele quick-tunnel URL'ini
kullanmaya devam eder.

**Telefondan bir session'a ulaşmanın ikinci, bağımsız bir yolu daha var:** claudeops'un açtığı her
session `--remote-control` kullanıyor — bu Claude Code'un kendi yerleşik özelliği, dolayısıyla resmi
**Claude mobil uygulamasında** da **Code** sekmesi altında canlı bir bağlantı olarak görünür, direkt
dokunup konuşabilirsiniz (claudeops yok, tünel yok — bu tamamen Anthropic'in kendi altyapısı). claudeops
web paneli *hangi session'ların var olduğunu* yönetmek içindir (başlat/durdur/kaydet/layout); Claude
uygulamasının Code sekmesi ise *zaten çalışan biriyle konuşmak* içindir. Birlikte kullanmak pratik.

## CLI komutları

```
py/cops list      # çalışan session'ları listele
py/cops kill      # bir/birkaç session'ı nazikçe kapat (SIGTERM + grace + gerekirse SIGKILL)
py/cops close     # kalıcı kapat (kill + guard bir daha açmasın diye işaretle)
py/cops guard     # roster'daki eksik session'ları tespit edip aç (crash-recovery; cron'a konabilir)
py/cops rc        # kill + yeniden aç (tek tek ya da toplu; handover/respawn için)
py/cops handover  # session'ı wrap-up mesajıyla kapatıp aynı adla yeniden aç
                   #   isimsiz = tüm fleet (batch, co/ulaksec hariç); İSİM verilirse
                   #   tek session, roster gerekmez, co/ulaksec dahil; --lang=en
py/cops stuck     # takılı kalmış (idle ama "busy" görünen) session'ları tespit et
py/cops layout    # pencereleri masaüstlerine dağıt (X11)
py/cops web       # kontrol paneli (yukarıda)
py/cops service   # `web`+tunnel için systemd --user kalıcılığı (install/status/uninstall)
```

Her komutun kendi `--help`'i var.

## Nasıl çalışır

- **Roster** iki TSV dosyası, repo dışında (`~/.claude/claudeops/`, kişiye özel, hiçbir zaman commit
  edilmez): `roster.tsv` (`isim<TAB>klasör<TAB>model`, artı opsiyonel 4. kolon `cli` — `claude` ya da
  `agy`, yoksa/eski-formatsa varsayılan `claude`) ve `models.tsv` (`isim<TAB>model` — satır `#` ile
  başlıyorsa o isim kapalı/emekli, guard onu açmaz).
- Session'lar `gnome-terminal` içinde açılır, `tmux` kuruluysa ayrı bir `tmux` session'ına sarılır
  (kurulu değilse düz, sarmalanmamış `gnome-terminal`'e düşer — `tmux` eksikliği spawn'ı hiçbir zaman
  başarısız kılmaz). Bir `claude` session'ı `claude -n İSİM --remote-control İSİM` çalıştırır — Claude
  Code'un kendi Remote Control özelliği (claude.ai/code veya mobil uygulamadan da erişilebilir). `agy`
  session'ının muadil bir isimlendirme flag'i yok, bu yüzden ismi `COPS_NAME` ortam değişkeniyle taşınır.
- Birden fazla CLI backend'i (`agy`, Google'ın Antigravity CLI'ı; `shell`, düz interaktif bash — sohbet
  şeklindeki bir CLI'ın yapamadığı şeyler için, ör. `sudo` ya da gerçek bir TTY isteyen herhangi bir
  program) her biri bir **provider** olarak uygulandı: küçük bir `CliProvider` arayüzü
  (`py/claudeops/providers/base.py`) — `claude_provider.py`/`agy_provider.py`/`shell_provider.py` bunu
  kendi içinde doldurur; kodun geri kalanı (spawn/discovery/web paneli) sadece bu arayüz üzerinden
  çağırır, hangi CLI kullanıldığına göre hiç dallanmaz — bir backend daha eklemek bir provider dosyası
  daha yazmak demektir, mevcut koda dokunmak değil.
- Kill her zaman **SIGTERM + ~10 saniye bekleme + hâlâ canlıysa SIGKILL** — Claude Code'un transkript
  kaydı ara ara diske yazıldığı için (lazy-checkpoint), çok hızlı `SIGKILL` konuşma geçmişini kesebiliyor.
- `guard` opsiyonel — istemiyorsanız hiç kurmayın, tamamen `py/cops web`'den elle yönetin.

## Klasör yapısı

```
py/claudeops/
  paths.py, session.py, discovery.py   # temel: yollar, veri modeli, proc keşfi (psutil)
  spawn.py, kill.py, guard.py, layout.py, roster.py, handover.py, needs_ho.py, config.py, stuck.py,
  remote_desktop.py
  tmux_backend.py                       # tmux yardımcıları (ayrı -L cops socket'i), tmux yoksa fail-soft
  providers/                            # CliProvider ABC + backend başına bir dosya + registry
    base.py, claude_provider.py, agy_provider.py, shell_provider.py, __init__.py
  data/                                  # gömülü statik dosyalar: tmux.conf, run-tunnel.sh
  commands/                             # her CLI komutu kendi dosyasında (web.py/web_ws.py en büyükleri)
py/webui/                               # panelin tarayıcı istemcisi (React+TS+Vite) — kendi README.md'sine bak
  src/, dist/                           # dist/ commit'lenir (build çıktısı, sourcemap dahil) — deploy'da build adımı YOK
cops                                    # giriş noktası → python3 -m claudeops
```

## Tasarım notları

- **psutil, `ps|grep` değil** — cmdline liste olarak geliyor, quoting/anchor tuzağı yok.
- **CPU birinci sınıf aktiflik sinyali** — Claude Code'un kendi `status`/bridge alanları gecikmeli
  güncelleniyor, CPU%>2 daha güvenilir "gerçekten çalışıyor" göstergesi.
- **Bash `claudeops`** (repo kökünde) hâlâ duruyor ama artık sadece eski/legacy komutlar için —
  canlı fleet yönetiminin (guard, rc, handover, web) tamamı bu Python sürümünde.
