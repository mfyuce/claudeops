# claudeops — Claude Context

## Bu Repo

Açık Claude CLI session'larını toplu yönetmek için tek-dosya bash CLI. 2026-05-16/17 gecesi 14 paralel session'ı compact + RC + visible-window olarak yeniden açma operasyonundan doğdu. Yaşanan tüm bug'lar script'te fix'li.

## Self Protection Mekanizması

`find_self_claude_pid` fonksiyonu bash'in `$$` değerinden ata zincirini yürüyüp ilk `claude` binary'sini tespit eder. **Bu pid'i ve karşılık gelen sessionId'yi hiçbir kill/kompakt/RC işleminden geçmez.** Hardcoded pid kullanılmaz; her session/cron çalıştırmasında dinamik bulunur.

`all-but-self` hedef syntax'ı bu protection'a bağlıdır.

## Önemli teknik kararlar

- **Tek dosya bash**: Python wrapper yok; bağımlılığı minimum tutmak için. python3 sadece JSON parse için kullanılıyor (zaten Ubuntu default).
- **stdin redirect** (`< /dev/null`): `claude -p` her çağrısında zorunlu. Aksi halde caller loop'un stdin'i prompt'a sızar (gerçek olay — 14 session ilk denemede TSV içeriğini /compact'in arkasına ekledi → compact tanınmadı).
- **`script -qfc` ile detached pty**: `nohup &` tek başına yetmez çünkü Claude TUI gerçek terminal ister. `script` sahte pty doğurur, içinde claude çalışır.
- **Compact başarı doğrulaması**: `claude -p "/compact"` output vermez (sessiz exit). Başarı kanıtı, ilgili jsonl içinde `"isCompactSummary":true` flag'li entry sayısının +1 artmasıdır. Script bunu kullanır.
- **Visible window'lar bash exec ile**: `gnome-terminal -- bash -c "claude ...; exec bash"` claude exit etse bile pencereyi bash prompt olarak açık bırakır. Olası `--remote-control` bağlantı hatası kaybolmaz.
- **Workspace count gsettings**: `gsettings set org.gnome.mutter dynamic-workspaces false` + `num-workspaces N`. Install gerektirmez.
- **Workspace placement wmctrl**: layout sadece wmctrl varsa çalışır. Yoksa açıklayıcı hata.

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
claudeops rc all-but-self --kill-first               # mevcut pid'i önce kapat
claudeops rc all-but-self --suffix=14                # toplu rename: <name>13→<name>14

# Layout (wmctrl gerekli)
claudeops desktops 5                                  # 5 workspace fixe
claudeops layout grid 4 --pin=rustrino13              # ws=0'a pin, geri kalan 4'erli
```

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
