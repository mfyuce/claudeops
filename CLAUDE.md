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

## READY FOR HANDOVER (2026-05-18)

**Nerede kaldık:**
- claudeops repo `tmp/claudeops/` altında, git'te 2 private remote ile (origin=github, gitlab=gitlab.com), tamamen sync. Son commit: `16a40aa TODO: model atama doğrulaması`. Working tree clean.
- 15 named CLI session açık (rustrino15, anomaly15, carla15, ..., vrk15) + bu konuşma (pid 1506400). Hepsi RC active.
- 2 repo'da uncommitted (rustrino, mbd_cp_carla) — 15-session'ların aktif çalışması, claudeops handover işi DEĞİL.

**Yeni session'ın yapması gerekenler:**
1. `MEMORY.md` oku, özellikle `feedback_opus_auto_mode.md` (yeni adı: `model-permission-mode-kural`) — opus→auto, sonnet→acceptEdits.
2. `feedback_busy_kill_protection.md` — busy session kill etme, idle bekle.
3. `TODO.md`'de açık kritik işler: (a) **model-spesifik default permission-mode** otomatik mapping eklenmeli; (b) **OCR + auto-respond** permission prompts; (c) **layout geometry** ekran kilidi/Mutter snap fix; (d) **history/launch** komutları; (e) Python UI; (f) `--models=name:model,...` config.

**Açık kararlar:**
- 15-session'lar şu an opus auto / sonnet (acceptEdits olmadan) çalışıyor — sonnet'lara `--permission-mode=acceptEdits` retroaktif uygulanmadı; mevcut session'lar yaşadığı sürece eski mode'da. Yeni round'da claudeops otomatik uygulayacak.
- Multi-monitor snap bug için ekran kilidi hipotezi henüz test edilmedi.
- Anomaly13 64 uncommitted incident dahil olmak üzere geçmiş bug'lar hep TODO'ya kaydedildi.

READY FOR HANDOVER
