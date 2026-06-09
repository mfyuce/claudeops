# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Self Protection

`find_self_claude_pid`: (1) `$CLAUDE_CODE_SESSION_ID` env var (Claude TUI çocuklara geçirir — nohup-detached'te tek güvenilir yol), (2) fallback `$$` ata zinciri. `all-but-self` buna bağlı; self'i ASLA hedef almaz.

## Önemli teknik kararlar (kod-okumakla anlaşılmaz)

- **stdin redirect** `< /dev/null`: `claude -p` her çağrıda zorunlu (stdin leak fix).
- **`script -qfc` detached pty**: `nohup &` yetmez, Claude TUI gerçek terminal ister.
- **Visible window**: `gnome-terminal -- bash -c "claude ...; exec bash"` (claude exit etse pencere bash'a düşer).
- **wmctrl -s vs xprop**: sadece `wmctrl -s N` Mutter'da görsel switch tetikler.
- **VTE keystroke rejection**: synthetic key (`xdotool type`/`key`) çoğu zaman REDDEDİLİR. Güvenilir prompt enjeksiyonu = **CLI argümanı**: `claude ... -n NAME --remote-control NAME 'PROMPT'` (Enter'sız otomatik). Idle/stuck session'a iş → kill + fresh-spawn böyle.
- **`-n NAME` ≠ `--remote-control NAME`**: `-n` display, `--remote-control` RC bridge. Server-side bridge cache: aynı sid resume → RC name cache'li, değiştirmek için `--new`.
- **Layout in-place**: `xdotool windowmove` (**`--sync` YOK** — pencere hedefteyse hang) + `wmctrl -s` desktop-switch + `get_desktop` verify (pencere görünür değilse yanlış taşır) + read-back. Konum doğrulaması `xdotool getwindowgeometry` (wmctrl -G 2× raporluyor).
- **1M context**: model ID'ye `[1m]` suffix → CLI `context-1m-2025-08-07` beta header ekler + context=1e6. Örn `claude-opus-4-8[1m]`. Detay: memory [[model-1m-context]].

## Model konvansiyonu

- **İki-grup model** (2026-06-01 revize): **coding→sonnet, paper→opus**, hepsi `[1m]` (1M ctx) + `--permission-mode=auto` + `--effort=max` + RC. Harita: **`~/.claude/claudeops/models.tsv`** (name→model). **Sonnet (coding, 12):** hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido evolvi done mamut (+co). **Opus (paper, 11):** rr aggroot oa hms hve qve rve emrgence araroot mecdtfl carla. (Tarihçe: 2026-05-30 tek-model'e indirilmişti → 2026-06-01 tekrar split'e dönüldü; eskiden 13 opus + 7 sonnet idi.)
- `rc` flag'leri model-agnostic pass-through: `--model`, `--permission-mode`, `--effort` (low/medium/high/xhigh/max).

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--exclude=name1,name2] [--model='claude-opus-4-8[1m]']
#   ⚠ --model (2026-06-05): wrap-up resume'unu bu modelde aç. SONNET LİMİT dolunca sonnet
#   session'larını opus'a resume edip wrap-up yaptır (konuşma geçmişi model-agnostik → limit bypass,
#   bağlam korunur). vrk35 ho'sunda doğrulandı. ho_model boşsa eski davranış (session'ın kendi modeli).

# Faz 2 — respawn (suffix bump). ⚠⚠ ÖNCE: Faz1 sonrası session'lar SAĞLIKLI mı? (API hatası 503/529 YOK + RFH var)
#   Hata/eksik varsa → DUR, kullanıcıya söyle, GEÇME. Faz 2 yıkıcı (KILL eder); kullanıcı onayı olmadan geçme. [[feedback-ho-stop-on-error]]
#   ŞU AN all-opus (sonnet limit dolu) → TEK komut:
./claudeops rc all-but-self --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max
#   (self skip; mecdtfl kapalı→dahil değil; --suffix→suffix-dosyası→guard *<TO>; straggler'a --prompt='commit+TÜM remote push')
#   ⚠ guard-race: Faz1+Faz2 boyunca background lock-holder ile guard'ı blokla, kayıt list'te TAM olunca bırak. [[handover-edge-cases]] edge-9
#   Sonnet dönerse split: coding→sonnet / paper→opus (models.tsv'den 2 ayrı rc).

# Faz 3 — layout (self/co ws0 pin; mecdtfl KAPALI → grup1=hc,hcr,evolvi; grup2=mo,kulturiot,gedikvm,gedikido)
./claudeops layout grid 4 --pin=co<SELF>,anomaly<TO>,rustrino<TO> --group=hc,hcr,evolvi --group=mo,kulturiot,gedikvm,gedikido
```

⚠ `[1m]` köşeli parantez için **tek tırnak ŞART** (shell glob). Target listesi **SPACE-separated** (virgül parse bug — TODO).
⚠ `--group=` **base-name** alır (suffix'siz) → handover'da `<TO>` bump GEREKMEZ, sabit kalır. Tekrarlanabilir; her grup serbest-others'tan sonra kendi taze desktop'una blok yerleşir, asla bölünmez. 2 grup → ilk yazılan önce (düşük ws). 12 serbest-other ws1-3 → grup1 ws4, grup2 ws5.
**Flag'ler:** `handover --force` (skip baypas; jsonl yoksa fresh-spawn) · `--layout [--pin=a,b]` (spawn bitince oto-tile) · `cancel <names>` (stuck modal'a Esc; inmezse `rc --kill-first`).
**Skip kriteri (done):** jsonl'de RFH var + son RFH'den sonra yeni istek yok + repo temiz. `repo_dirty`: untracked saymaz; dirty = tracked-modified **veya** TÜM remote'lara push edilmemiş (çift remote github+gitlab, `@{u}` değil) **veya** behind. Pre-check 1× `git fetch --all` (20s).
Detay: memory [[handover-procedure]] + [[handover-edge-cases]].

## Bilinen sınırlamalar / açık bug'lar

- **Wayland**: layout çalışmaz (wmctrl X11-only). **Terminal**: gnome-terminal hard-coded.
- **Permission modal**: RC'yi bloklar; garantili iptal = `rc --kill-first`.
- **`rc <a,b,c>` virgül**: parse yok, SPACE kullan (TODO). **Layout orphan terminal**: window-name validation eksik, orphan quad slot işgal eder (TODO).

## Meta

- `DONE.md` = de facto CHANGELOG. `desktops.local.md` = layout snapshot (gitignored).
- Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
- **Handover-prep MD sync** (her ho'da): (1) TODO'da tamamlanmış → DONE'a taşı+TODO'dan sil; (2) TOBEDECIDED'da karar verilmiş → TODO'ya taşı+sil.

## READY FOR HANDOVER (2026-06-09)

**Nerede kaldık:** co36 (claudeops repo, self). Fleet **\*38 İSİMLİ ama içerik \*37** (guard-resume; aşağıda). suffix=38, dup yok, *37 isimli kalmadı, all-opus, mecdtfl KAPALI. Layout 7 ws standart (pin co36/anomaly38/rustrino38; mamut38 ws4; grup1 hc/hcr/evolvi ws5; grup2 mo/kulturiot/gedikvm/gedikido ws6).

**⚠ \*37→\*38 HANDOVER YARIM/HATALI (API outage):** Bugün TÜM fleet **claude.ai API hatası** (jsonl'lerde yüzlerce 503/529/rate-limit) veriyordu. Ben "yavaş kayıt" sanıp ho'yu **zorladım** → 2 fazda guard-race + duplicate (kurtarıldı: lock-holder + dedup, [[handover-edge-cases]] edge-9/10). Kullanıcı: **"37 bitmedi ki 38 geçtin. ben demeden geçme."** → **DERS [[feedback-ho-stop-on-error]]: hata varken DUR, zorlama; Faz 2 cutover'ı onaysız yapma.** \*38'ler = \*37 konuşmalarının guard-resume'u (**context içlerinde, kayıp yok**); kullanıcı \*37 işini bu \*38 pencerelerinde devam ettiriyor. **NOT: gerçek handover henüz YAPILMADI** — API düzelip kullanıcı "geç" deyince temiz ho gerekebilir.

**Straggler işi güvende** (dedup öncesi co-side commit+push, junk hariç): anomaly (k8s shipper+docs→3 remote), kulturiot (puanlama→2 remote), mamut (1 commit→origin).

**Kalıcı altyapı (✅ DONE.md):** Cold-boot (`boot`/`snapshot`/`recover`+autostart; boot.list=co+mo; isim: **hc=videogen hcr=hoca-reader vrk=varaka mo=machine_ops**). guard watchdog (OOM→`claudeops guard`, cron */2; **oomd'ye dokunma, guard kurtarsın**). ⚠ autologin kapalı (sudo); boot models.tsv lookup eksik.

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — özellikle [[feedback-ho-stop-on-error]] + [[handover-procedure]] + [[handover-edge-cases]] + [[add-session-to-fleet]] + [[model-1m-context]] + [[oomd-cgroup-kill]].
2. **needs-ho:** `claudeops needs-ho --from-suffix=38`. **fleet kapalıysa:** `claudeops guard`. **ho'da:** API hatası varsa DUR; Faz 2 öncesi kullanıcı onayı al; Faz1+Faz2 boyunca background lock-holder ile guard'ı blokla, kayıt tam olunca bırak.
3. **Açık TODO bug'lar:** (a) rc virgül, (b) layout orphan, (c) cancel Esc, (d) --model→auto, (e) handover --layout --group, (f) deep-ho, (g) boot models.tsv, **(h+j) rc/handover lock'u kendi al + kayıt bitene tut (KALICI)**, (i) --exclude base-name, (k) Faz1 bridge-verify NAME eşlesin, (l) spawn-sonrası kayıt-doğrula.

**Açık kararlar:** (1) **sonnet limit dolu** → all-opus (açılınca split revert: hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido evolvi done mamut co). (2) **mamut** coding varsayımı. (3) **mecdtfl KAPALI** — review gelince aç (`#` kaldır + guard). (4) anomaly `rumeysa.zip` + rustrino `bench/results/` junk. (5) TOBEDECIDED #5. `~/.cache/huggingface` 29G KORU.

READY FOR HANDOVER
