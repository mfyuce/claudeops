# claudeops — TODO

> Açık iş kalemleri. Tamamlananlar `DONE.md`'ye taşınır.

## Kritik bug'lar (devam)

- [ ] **BUG: `rc <a,b,c>` virgül-separated isim listesi parse edilmiyor** — 2026-05-19'da 15→16, 2026-05-23'te 20→21 transition'larında doğrulandı. `cmd_rc`/`resolve_targets` SPACE-separated bekliyor. CLAUDE.md eski örnekler virgüllü idi → güncellendi. Fix: cmd_rc başında target ve "$@" içindeki virgüllü string'leri split et (IFS=','). Aynı bug `cmd_kill`, `cmd_compact`, `cmd_send` için de var.
- [ ] **`claudeops layout` orphan terminal kaldırmıyor** — 2026-05-19/05-23/05-25 transition'larında doğrulandı (ws1'de "fatihyuce@483-LNX: ~" bir quad slot işgal ediyor). Fix: layout iterasyonunda window-name'in geçerli session.json'da olup olmadığını kontrol et + yoksa skip (oth_wins'e ekleme).
- [ ] **`cancel` Esc güvenilmez (VTE reject)** — 2026-05-25 kulturiot23 "waiting" modal'da Esc inmedi. Garantili iptal = respawn. Fix: cancel Esc dene → 2s sonra hâlâ takılıysa otomatik `rc <name> --kill-first` öner/yap (flag ile).

## Geliştirme

- [ ] **`--model` verince default `--permission-mode=auto`** — 2026-05-25: artık HEPSİ auto (sonnet de). Yani mapping basitleşti: `--model=opus|sonnet` verilince permission-mode otomatik `auto` olsun (explicit verilirse override). Şu an her çağrıda elle `--permission-mode=auto` yazılıyor.
- [ ] **Python UI (büyük)** — claudeops için GUI: session listesini göster, tıkla → compact/RC/kill/send butonları, layout görsel önizleme. Stack TBD (PySide6 / Textual / Web). Ana motivasyon: CLI yerine UI.
- [ ] **`claudeops history` + `claudeops launch <name|sid>`** — geçmişte açık olan TÜM session'ları registry'le, `launch` ile yeni gnome-terminal'de RC açar.
- [ ] **`--models=name:model,...` per-name config** — manuel name→model map. Şu an model PLAN array'de gömülü, hatalara açık.
- [ ] **Spawn geometry: ekran kilidi hipotezi** — 2026-05-17 spawn'da pencereler HDMI'da rows olarak yerleşti (eDP 2×2 değil). Hipotez: ekran kilitliyse Mutter farklı davranıyor. Pre-flight lock check + defer placement.
- [ ] **Auto-respond permission prompts** — OCR çalışıyor (tesseract), keystroke landing intermittent. Seçenekler: OCR + RC API inject, ydotool (Wayland), claude TUI `--auto-accept` flag.
- [ ] Wayland desteği için layout fallback (gdbus + Mutter extension veya hint)
- [ ] Terminal emülatör parametrize (gnome-terminal yerine kitty/alacritty config/env)
- [ ] Rate-limit reset zamanını output'tan parse + auto-resume
- [ ] `claudeops batch --dry-run`
- [ ] `claudeops list --json` machine-readable
- [ ] `claudeops send` stdin'den prompt okuma
- [ ] `claudeops layout` için "BR köşede her zaman boş bırak" benzeri kural

## Dokümantasyon

- [ ] README'ye actual workflow örnekleri (güncel session isimleri)
- [ ] CLAUDE.md'ye "ne zaman compact" rehberi
- [ ] Demo gif/video — visible mode reopen sırası

## Test/Quality

- [ ] Unit test: `find_self_claude_pid` (claude değil bash'tan çağrılınca)
- [ ] Smoke test: tek session aç, kill, compact, RC, doğrula
- [ ] Edge case: 0 session açıkken komut davranışı

## Açık sorular

- [ ] gnome-terminal `--title` flag'i claude TUI tarafından override mı?
- [ ] `--remote-control` flag'i `--name` ile çakışıyor mu? (RC name session name'i de set ediyor görünüyor)
