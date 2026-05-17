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
