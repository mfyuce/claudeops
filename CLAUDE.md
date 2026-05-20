# claudeops — Claude Context

## Bu Repo

Açık Claude CLI session'larını toplu yönetmek için tek-dosya bash CLI. 2026-05-16/17 gecesi 14 paralel session'ı compact + RC + visible-window olarak yeniden açma operasyonundan doğdu. Yaşanan tüm bug'lar script'te fix'li.

## Self Protection Mekanizması

`find_self_claude_pid` iki mekanizma kullanır (sırayla):
1. **`$CLAUDE_CODE_SESSION_ID` env var** — Claude TUI'nin çocuk process'lere geçirdiği env var. SessionId match ile pid bulunur. **Nohup-detached script'lerde tek güvenilir yöntem** (ata zinciri kopuk olur).
2. **Fallback: `$$` ata zinciri** — interactive shell'lerde, env yoksa.

**Yaşanan incident (2026-05-17):** ilk versiyon sadece ata zinciri kullanıyordu. nohup ile launch edilen script'te ata zinciri claude bulamıyor → filter_not_self no-op → SELF KILL. pid 78492 öldü, harness yeni claude (1506400) ile rebirth oldu. Fix sonrası env-based protection çalışıyor.

`all-but-self` hedef syntax'ı bu protection'a bağlıdır.

## Önemli teknik kararlar

- **Tek dosya bash**: Python wrapper yok; bağımlılığı minimum tutmak için. python3 sadece JSON parse için kullanılıyor (zaten Ubuntu default).
- **stdin redirect** (`< /dev/null`): `claude -p` her çağrısında zorunlu. Aksi halde caller loop'un stdin'i prompt'a sızar (gerçek olay — 14 session ilk denemede TSV içeriğini /compact'in arkasına ekledi → compact tanınmadı).
- **`script -qfc` ile detached pty**: `nohup &` tek başına yetmez çünkü Claude TUI gerçek terminal ister. `script` sahte pty doğurur, içinde claude çalışır.
- **Compact başarı doğrulaması**: `claude -p "/compact"` output vermez (sessiz exit). Başarı kanıtı, ilgili jsonl içinde `"isCompactSummary":true` flag'li entry sayısının +1 artmasıdır. Script bunu kullanır.
- **Visible window'lar bash exec ile**: `gnome-terminal -- bash -c "claude ...; exec bash"` claude exit etse bile pencereyi bash prompt olarak açık bırakır. Olası `--remote-control` bağlantı hatası kaybolmaz.
- **Workspace count gsettings**: `gsettings set org.gnome.mutter dynamic-workspaces false` + `num-workspaces N`. Install gerektirmez.
- **Workspace placement wmctrl**: layout sadece wmctrl varsa çalışır. Yoksa açıklayıcı hata.
- **wmctrl -s vs xprop _NET_CURRENT_DESKTOP**: Sadece `wmctrl -s N` Mutter'da görsel desktop switch tetikler (ClientMessage). `xprop -root -set _NET_CURRENT_DESKTOP N` sadece property set eder, Mutter görsel uygulamaz. Layout için wmctrl -s gerekli.
- **Mutter multi-monitor snap bug**: in-place `wmctrl -e` koordinatları çoklu-monitor'da yanlış snap'liyor (örn eDP'de y=1080 → root y=2160 off-screen). Çözüm: `--reopen` modu (kill + wmctrl -s switch + gnome-terminal spawn on current → window doğru desktop'a doğar).
- **VTE keystroke rejection**: gnome-terminal VTE/Ink synthetic XSendEvent key'leri reddediyor. xdotool `type` çoğunlukla geçiyor, `key Return` permission dialog'lara intermittent. windowactivate --sync + delay genelde yardım eder.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` session display name (session.json + title), `--remote-control` RC bridge name (claude.ai mobil). İkisi ayrı; doğru kullanım `claude -n NAME --remote-control NAME 'prompt'`. `--remote-control devam` "devam"ı RC name yapar — yaygın hata.
- **Bridge cache (server-side)**: aynı sessionId resume edilince claude.ai server-side aynı bridge'i kullanır, ilk açılışta verilen RC name'i save eder, sonraki `--remote-control NEW_NAME` server'ı değiştirmez. RC name'i değiştirmek için `--new` (fresh sessionId) gerekli.
- **claude path encoding**: ~/.claude/projects/ altında cwd encoding'i hem `/` hem `_` → `-` yapıyor. tr '/_' '-'.

## Önemli komut kalıpları

```bash
# Self-aware operations
claudeops self                          # mevcut konuşmayı tanı
claudeops kill all-but-self             # her şey güvenli kalır

# Compact pipeline öğrendiğimiz şekilde
claudeops compact all-but-self --backup
# Per-session ~1-3 dk, 14 session × ~2dk = ~25-30 dk
# Rate limit'te otomatik durur; kalanlar token reset'inden sonra

# RC + visible: her session kendi gnome-terminal penceresinde
claudeops rc all-but-self                            # default visible
claudeops rc all-but-self --detached                 # arkaplan headless
claudeops rc all-but-self --kill-first               # mevcut pid'i önce kapat (busy ise idle bekler)
claudeops rc all-but-self --suffix=14 --new          # toplu rename + fresh sessionId
claudeops rc rustrino15,anomaly15 --model=opus --permission-mode=auto --prompt=devam
claudeops rc carla15 --model=sonnet --permission-mode=acceptEdits --kill-first

# Handover (visible wrap-up + auto-Enter, sonra manuel transition)
claudeops handover                                    # --from-suffix=13 (default), 14 üret
claudeops handover --headless                         # -p ile sessiz (tool onay verilemez!)

# Layout (wmctrl + xdotool gerekli)
claudeops desktops 5                                  # 5 workspace fixe
claudeops layout grid 4 --pin=rustrino15,anomaly15   # ws=0'a pin, kalan 4'erli
claudeops layout grid 4 --reopen --pin=...           # multi-monitor snap bug için kill+reopen mod
```

## Model-permission mode kuralı (otomatik default planlanıyor, TODO)

- **Opus → `--permission-mode=auto`**: classifier-based, esnek karar
- **Sonnet → `--permission-mode=acceptEdits`**: Edit/Write otomatik, Bash hâlâ onay ister
- Şu an manuel verilmesi gerekiyor; gelecek versiyonda `--model=X` verince otomatik permission-mode default'u eklenecek

## Mevcut session konvensiyon (2026-05-17)

- 14 session'ın hepsi `<short>13` formatında: carla13, hcr13, rve13, sqli13, vrk13, ...
- Her session bir konu/proje: yeterlilik2 backup'ları (academic), maya3/sqli (sqli13), monitoring (rustrino13), tmp/* (hcr/hc/vrk), mutasyon serisi (oa/qve/rve/hve/emrgence)
- `home13` (eski pid 23814, orphan) bu konuşma ile karıştırılıyor; user'a göre = "kendisi". Skip.

## Geliştirme notları

- Script bağımsız test edilebilir; yan etkilerden kaçınmak için kill/compact/rc komutları default olarak self'i ASLA hedef almaz.
- `cmd_send` shell argümanlarını "<targets> -- <prompt>" formatında parse eder.
- Token harcamasını izlemek için `/context` slash command'ı `claudeops send <name> -- "/context"` ile alınabilir.

## Bilinen sınırlamalar

- Workspace placement Wayland'da çalışmaz (wmctrl X11-only). GNOME on Wayland kullanıcısı için layout komutu işe yaramaz.
- gnome-terminal yerine başka terminal emülatör (kitty, alacritty) kullanılırsa visible mode kırılır. Switch için `cmd_rc` içindeki `gnome-terminal` çağrısı parametrize edilmeli (TODO).
- Rate-limit reset zamanı parse edilmiyor; sadece pattern tespit edip durdurma yapıyor (TODO: parse + auto-resume).
- Permission prompt'lara xdotool keystroke landing'i intermittent (VTE/Ink synthetic event reject). Mobile RC URL üzerinden manuel onay fallback.
- Multi-monitor'da `wmctrl -e` snap-bug; in-place layout off-screen yapabiliyor. `--reopen` mod ile çözülüyor (kill+spawn-on-target).
- Ekran kilidi sırasında spawn yapılınca windows HDMI'da yan yana (eDP 2×2 grid değil) — hipotez (TODO).

## READY FOR HANDOVER (2026-05-20)

**Nerede kaldık:**
- claudeops repo `tmp/claudeops/` altında, git'te 2 private remote ile (origin=github, gitlab=gitlab.com), tamamen sync. Son commit: `48442ee TODO: rc virgül-separated isim parse bug + layout orphan terminal bug`. Working tree clean.
- **15→16 transition tamamlandı (2026-05-19)**. 15 named 16-session aktif (anomaly16, carla16, emrgence16, hc16, hcr16, hms16, hve16, mecdtfl16, oa16, qve16, rustrino16, rve16, sqli16, trroot16, vrk16) + bu konuşma (self pid 1525711). Hepsi RC active, idle.
- **Model dağılımı (9 opus auto / 6 sonnet acceptEdits):**
  - opus auto: hms16, emrgence16, oa16, hve16, rve16, qve16, carla16, sqli16, trroot16
  - sonnet acceptEdits: anomaly16, hc16, hcr16, mecdtfl16, vrk16, rustrino16
- **Layout:** anomaly16 + rustrino16 ws0 (pin değil, sadece ilk desktop yerleşimi); diğerleri ws1-4'e 2×2 grid olarak dağıtıldı.
- **AnyDesk DNS sistem-tarafı fix (2026-05-19):** wifi değişimi sonrası `/etc/resolv.conf` bozuktu (typo "name server", >3 nameserver, foreign mode). Temizlik: sadece `8.8.8.8 + 1.1.1.1`. Relay bağlantısı `ESTABLISHED 169.150.215.50:443`. "Client offline" mesajları **karşı taraf** (1812750856) içindi; kendi makine (235187453) online. `crl.anydesk.com` resolve fail kalıcı ama kozmetik.

**Yeni session'ın yapması gerekenler:**
1. `MEMORY.md` oku — özellikle [[opus-auto-mode]] (opus→auto, sonnet→acceptEdits) ve [[busy-kill-protection]] (busy session kill etme, idle bekle).
2. `TODO.md`'de yeni eklenen 2 kritik bug (en üst): **`rc <a,b,c>` virgül-separated parse'lanmıyor** (resolve_targets SPACE-only; CLAUDE.md örnekleri yanıltıcı, kill+respawn sessizce no-op olur) + **`layout` orphan terminal'i ws slotuna alıyor** (window-name session.json validation eksik). Bu ikisi de bu transition'da real-world fark edildi.
3. Diğer açık kritik işler: (a) **model-spesifik default permission-mode** otomatik mapping (`--model=opus` → `auto`, `--model=sonnet` → `acceptEdits`); (b) **OCR + auto-respond** permission prompts (OCR çalışıyor, keystroke landing intermittent); (c) **layout geometry** ekran kilidi hipotezi; (d) **history/launch** komutları; (e) Python UI; (f) `--models=name:model,...` config.

**Açık kararlar / pending:**
- Hızlı disk temizlik (2026-05-20): ~5G güvenli aday belirlendi (stanza, JetBrains, puppeteer, ms-playwright-go, BraveSoftware, /tmp/ray, /tmp/tr_root_weights tar, /tmp/orkhon_models). Kullanıcı "bugün dokunulanlara karışma" dedi — aktif olanlar (pip/chrome/ms-playwright/cargo-target) skip. Onay bekliyor, henüz silinmedi. `~/.cache/huggingface` 29G memory kuralı gereği KORU.
- Sonnet acceptEdits retroaktif uygulanmadı; mevcut 6 sonnet session yaşadığı sürece eski mode'da. Yeni round'da claudeops otomatik default ekleyecek (TODO).
- Multi-monitor snap bug için ekran kilidi hipotezi henüz test edilmedi.
- `rc` comma-parse bug fix'i hâlâ yapılmadı; mevcut workaround = SPACE-separated kullan.

READY FOR HANDOVER
