# claudeops — TODO

> Açık iş kalemleri. Tamamlananlar `DONE.md`'ye taşınır.

## Şu anda (2026-05-17)

- [ ] **Test: `claudeops layout grid 4 --pin=rustrino13,sqli13,hcr13,vrk13`** — wmctrl şimdi kurulu, ilk gerçek çalıştırma
- [ ] **Test: `claudeops desktops 5`** — workspace sayısı sabitleme (henüz mevcut konfig kontrol edilmedi)
- [ ] **Test: `claudeops rc <name> --rename=<new>`** — kullanıcının istediği `<...>13 → <...>14` pattern'i
- [ ] **Test: `claudeops send <name> -- "/context"`** — token kullanım rapor alma

## Geliştirme

- [ ] **Python UI (büyük)** — claudeops için GUI: session listesini göster, tıkla → compact/RC/kill/send butonları, layout görsel önizleme. `send` ileride eklensin (önce list/compact/kill/layout). Stack önerisi: PySide6 ya da Textual (TUI). Headless çalıştığı için server-side de bir option. _Bu işin ana motivasyonu: CLI yerine UI'den kontrol._
- [ ] **`claudeops history` + `claudeops launch <name|sid>`** — geçmişte (veya halen) açık olan TÜM session'ları kayıt altına al (`~/.claude/projects/*/sessionId.jsonl` zaten var; bu dosyalardan name+cwd+lastModified+isLive bilgisi ile registry üret). `history` listeler, `launch` belirtilenle yeni gnome-terminal'de RC açar. "Daha önce açık olan CLI'leri kolayca geri getir" amacı.
- [ ] **`--model=<name>` parametresi** — `rc`, `new`, `handover`, `layout --reopen` komutlarında her session için model seçimi. Örn: `rc rustrino13,anomaly13 --suffix=14 --new --kill-first --model=sonnet` (yeni rustrino14/anomaly14 sonnet ile açılır), diğerleri default opus. Per-name model map (`--models=rustrino14:sonnet,anomaly14:sonnet,*:opus`) ya da CSV.
- [ ] **Layout in-place (kill'siz)** — şu an `--reopen` flag kill+reopen yapıyor (kullanıcıya az miktarda kesinti). Mutter'in `wmctrl -e` ve `xprop _NET_WM_DESKTOP` in-place taşıma'larını multi-monitor'da yanlış snap'liyor (y=1080+ → (88, 2160) off-screen). Olası çözümler:
    1. `xdotool windowmove/windowsize --sync` — Mutter snap'i bypass eder, install gerek
    2. python-xlib ile EWMH ClientMessage doğrudan — install gerek
    3. Mutter konfig veya gsettings ile snap-disable
    4. wmctrl source patch
  En kolay 1 (xdotool). Şu an --reopen ile çalışıyor, hayat-kalitesi item, blocker değil.
- [ ] **Auto-respond permission prompts** — `claudeops` waiting state'inde Claude TUI permission dialog gösteriyor (örn "1. Yes, 2. Yes don't ask, 3. No"). Şu an `xdotool windowactivate + key Return` veya `type 1 + Return` çalışmıyor (VTE/Ink synthetic keypress'i yiyiyor olabilir; click+Enter de geçmedi). Kullanıcı telefondan RC URL açıp manuel onaylıyor. Çözüm seçenekleri:
    1. **OCR + RC API** — screenshot al, prompt'u tesseract'la oku, claude.ai RC backend API'ı ile inject (REST POST). RC API spec'i öğrenilmeli. Kanıtlanmış: OCR çalışıyor (tesseract 4.1, ImageMagick mevcut).
    2. **ydotool** — Wayland-uyumlu, /dev/uinput kullanır (root gerek veya `input` group). xdotool'un X11-only sınırını aşar.
    3. **VTE-spesifik keysend** — gnome-terminal extension veya D-Bus üzerinden direkt yazı geç.
    4. **claude TUI patch** — `--auto-accept` veya benzeri flag (claude tarafında değişiklik).
  Ayrıca: OCR ile prompt'u oku → 3+ seçenek varsa kullanıcıya bildir, default Yes değilse atma. Şu an proven: ws=waiting filter + OCR ile prompt tespiti ✓, sadece keystroke gönderimi ✗.
- [ ] Wayland desteği için layout fallback (gdbus + Mutter extension veya hint mesajı)
- [ ] Terminal emülatör parametrize (gnome-terminal yerine kitty/alacritty seçilebilsin) — config dosyası ya da env var
- [ ] Rate-limit reset zamanını output'tan parse edip auto-resume zamanla (örn. `compact --auto-resume`)
- [ ] `claudeops batch` için dry-run mode (`--dry-run`) — ne yapacağını listeler, uygulamaz
- [ ] `claudeops list --json` machine-readable output (jq pipeline'lar için)
- [ ] `claudeops send` için stdin'den prompt okuma seçeneği (büyük metinler için)
- [ ] `claudeops layout` için "BR köşede her zaman boş bırak" benzeri kural (önemli pencereyi gizlemek için)

## Dokümantasyon

- [ ] README'ye actual workflow örnekleri (gerçek session isimleriyle)
- [ ] CLAUDE.md'ye "ne zaman compact yapılır" rehberi
- [ ] Demo gif/video — visible mode reopen sırasının görseli

## Test/Quality

- [ ] Unit test: `find_self_claude_pid` — claude değil bash'tan çağrılınca davranış
- [ ] Smoke test script: tek session aç, kill, compact, RC, doğrula
- [ ] Edge case: 0 session açık olduğunda komutların davranışı

## Açık sorular

- [ ] gnome-terminal `--title` flag'i, claude TUI başlatınca tarafından override mı ediliyor? (`✳ name` prefix zaten claude'dan)
- [ ] `--remote-control` flag'i `--name` ile çakışıyor mu? RC name argümanı session name'i de set ediyor görünüyor; netleştir.
