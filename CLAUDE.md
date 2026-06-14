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
- **claude 2.1.169 session keşfi (KRİTİK, fix `b8bad9e`)**: fresh `--new` session'lar `~/.claude/sessions/<pid>.json` **YAZMIYOR** (yalnız resume/içerikli olanlar yazıyor) → claudeops fresh'leri göremez, **guard onları 'down' sanıp DUPLICATE açar** (2026-06-09 gün boyu dup felaketinin kökü). Fix: `all_sessions_tsv` canlı `claude --remote-control NAME` proc'larından DA keşfeder (dedup session.json'u önceler). Fresh-only session list'te bridge `-` görünür. Detay: [[claude-2169-session-detection]].
- **Layout in-place**: `xdotool windowmove` (**`--sync` YOK** — pencere hedefteyse hang) + `wmctrl -s` desktop-switch + `get_desktop` verify (pencere görünür değilse yanlış taşır) + read-back. Konum doğrulaması `xdotool getwindowgeometry` (wmctrl -G 2× raporluyor).
- **1M context**: model ID'ye `[1m]` suffix → CLI `context-1m-2025-08-07` beta header ekler + context=1e6. Örn `claude-opus-4-8[1m]`. ⚠ **ŞU AN KAPALI** (2026-06-09 kullanıcı: "1m olmasın"); flag/mekanizma duruyor, kullanılmıyor. Detay: memory [[model-1m-context]].

## Model konvansiyonu

- **Model (2026-06-13): TÜM aktif fleet `claude-opus-4-8[1m]`** (opus + 1M) + `--permission-mode=auto` + `--effort=max` + RC. **Split YOK** (06-13'te birleşti). Harita: **`~/.claude/claudeops/models.tsv`** (name→model). **19 aktif → opus-1m:** hc hcr mo vrk rustrino anomaly evolvi done mamut (coding 9) + aggroot oa hms hve qve rve emrgence araroot carla gencmuh (paper 10). **co** (self, claudeops) + **ulaksec** (korunan, work/sec — "dokunma") AYRI/dokunulmaz. **EMEKLİ (06-13 fleet'ten çıktı, kill'lendi):** rr, gedikvm, gedikido, kulturiot. (mecdtfl KAPALI.) **Fable denendi 06-13 ama "Claude Fable 5 currently unavailable" (Anthropic erişim) → opus-1m'e geçildi.** (Tarihçe: 05-30 tek → 06-01 split → 06-09 no-1m → 06-12 opus-non-1m → **06-13 all-opus-1m + 4 emekli**.)
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
#   ŞU AN (06-13): TÜM fleet opus-1m, split YOK → TEK rc (19 isim). ⚠ ama TEK-TEK aç (aşağı):
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> evolvi<F> done<F> mamut<F> aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> carla<F> gencmuh<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max
#   (self/co skip; mecdtfl + 4 EMEKLİ [rr/gedikvm/gedikido/kulturiot] DAHİL DEĞİL; --suffix→suffix-dosyası→guard *<TO>)
#   ⚠⚠ TEK-TEK YAP (2026-06-13 dersi): toplu/eşzamanlı respawn ~/.claude.json'u BOZAR (truncated JSON → resume BLANK-hang).
#   Her session'ı tek tek aç → *<TO> kaydını (bridge) bekle → config'i `python3 -c "json.load(open(~/.claude.json))"` ile
#   doğrula → bozuksa DUR (backups/'tan restore). [[config-corruption-resume-hang]] [[handover-edge-cases]]
#   ⚠ guard-race: fix b8bad9e (2.1.169 proc-keşfi) SONRASI guard fresh proc'ları görür → dup riski büyük ölçüde azaldı; yine de kill→spawn boşluğu için Faz1+Faz2'de background lock-holder güvenli ([[handover-edge-cases]] edge-9). ⚠ Lock-holder'ı öldürürken parent bash DEĞİL `sleep` çocuğu da `fuser guard.lock` ile öldür (fd çocukta).

# Faz 3 — layout (co+ulaksec ws0 pin; grup1=hc,hcr,evolvi; grup2 KALKTI — kulturiot/gedikvm/gedikido emekli, mo→serbest)
./claudeops layout grid 4 --pin=co<SELF>,anomaly<TO>,rustrino<TO>,ulaksec40 --group=hc,hcr,evolvi
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

## READY FOR HANDOVER (2026-06-13)

**✅ DURUM (2026-06-14 — handover \*43→\*44 BİTTİ):** co43 (self). Fleet **19 \*44, HEPSİ `claude-opus-4-8[1m]`** (opus+1M, split YOK), auto/max. suffix=44, **dup yok, config VALID** (TEK-TEK korundu), layout 6-7 ws (pin co43/anomaly44/rustrino44/ulaksec43; grup1 hc/hcr/evolvi). **co43** self + **ulaksec43** (work/sec, korunan — guard 40→43 bumplamış, konuşma korundu; istenirse 40'a alınır). **4 EMEKLİ** (rr/gedikvm/gedikido/kulturiot) fleet dışı (models.tsv `# EMEKLİ`). Bu tur: Faz1 wrap-up tek-tek (mamut/evolvi co-side) → Faz2 \*44 tek-tek → Faz3 layout. **Fable hâlâ "currently unavailable" → opus-1m.** ⚠ **DERS: register/done-detection (session.json bridge-field + jsonl-stale) YANILTICI/geç yazılıyor** — 2 kez boşuna durdurdum, session'lar çalışıyordu (kullanıcı+RC doğruladı). Güvenilir sinyal: **proc-varlığı + git-commit + KULLANICI GÖZÜ**, bridge-field/jsonl-stale DEĞİL. [[config-corruption-resume-hang]]. (token bütçe bol.)

**Kalıcı altyapı (✅ DONE.md):** Cold-boot (`boot`/`snapshot`/`recover`+autostart; boot.list=co+mo; isim: **hc=videogen hcr=hoca-reader vrk=varaka mo=machine_ops**). guard watchdog (OOM→`claudeops guard`, cron */2; **oomd'ye dokunma**). ⚠ autologin kapalı (sudo); boot models.tsv lookup eksik.

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[claude-2169-session-detection]] + [[feedback-ho-stop-on-error]] + **[[config-corruption-resume-hang]]** + [[handover-procedure]] + [[handover-edge-cases]] + [[add-session-to-fleet]] + [[model-1m-context]] + [[oomd-cgroup-kill]].
2. **needs-ho:** `claudeops needs-ho --from-suffix=44`. **fleet kapalıysa:** `claudeops guard`. **ho'da:** Faz2 = **TEK rc, hepsi `claude-opus-4-8[1m]`** (split YOK); **TEK-TEK aç + her birinden sonra config doğrula** ([[config-corruption-resume-hang]]); API hatası varsa DUR; Faz 2 öncesi kullanıcı onayı al. ⚠ **register/done'u bridge-field VEYA jsonl-stale ile bekleme — geç/yanıltıcı; proc-var + commit + kullanıcı-gözü kullan** (2026-06-14, boşuna 2 kez durdum). (4 emekli + co/ulaksec fleet-respawn dışı.)
3. **Açık TODO bug'lar:** (a) rc virgül, (b) layout orphan, (c) cancel Esc, (d) --model→auto, (e) handover --layout --group, (f) deep-ho, (g) boot models.tsv, **(h+j) rc/handover lock'u kendi al + kayıt bitene tut**, (i) --exclude base-name, (k) Faz1 bridge-verify NAME, (l) spawn-sonrası kayıt-doğrula, **(m) handover'ı TEK TEK yap (sıralı) — toplu/eşzamanlı işlem `~/.claude.json`'u bozdu (2026-06-13, [[config-corruption-resume-hang]]); resume sonrası `python3 json.load(~/.claude.json)` ile config'i doğrula, bozulursa DUR**.

**Açık kararlar:** (1) **Model: TÜM aktif `claude-opus-4-8[1m]`** (2026-06-13; split YOK; fable "unavailable" olunca seçildi; models.tsv güncel; fable açılırsa kullanıcı denemek isteyebilir). (2) **mamut** coding varsayımı. (3) **mecdtfl KAPALI** — review gelince aç (`#` kaldır + guard). (4) anomaly `rumeysa.zip` + rustrino `bench/results/` junk. (5) TOBEDECIDED #5. `~/.cache/huggingface` 29G KORU.

READY FOR HANDOVER
