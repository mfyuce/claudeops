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

- **İki-grup model:** **coding→sonnet, paper→opus** + `--permission-mode=auto` + `--effort=max` + RC. **[1m] YOK** (2026-06-09: 1M context kaldırıldı — kullanıcı istemiyor). Harita: **`~/.claude/claudeops/models.tsv`** (name→model). **Sonnet (coding, 12):** hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido evolvi done mamut (+co) → `claude-sonnet-4-6`. **Opus (paper, 11 canlı):** rr aggroot oa hms hve qve rve emrgence araroot carla → `claude-opus-4-8` + **gencmuh → `claude-opus-4-8[1m]`** (2026-06-09 eklendi; **TEK `[1m]` session**, kullanıcı istedi; cwd `.../backups/genc_muh`). (mecdtfl KAPALI.) (Tarihçe: 05-30 tek-model → 06-01 split → 06-05 geçici all-opus`[1m]` [sonnet limit] → **06-09 split geri + `[1m]` kaldırıldı**.)
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
#   ŞU AN: split (coding→sonnet / paper→opus), [1m] YOK → 2 AYRI rc:
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> kulturiot<F> gedikvm<F> gedikido<F> evolvi<F> done<F> mamut<F> \
  --suffix=<TO> --new --kill-first --model='claude-sonnet-4-6' --permission-mode=auto --effort=max
./claudeops rc rr<F> aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> carla<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8' --permission-mode=auto --effort=max
#   gencmuh AYRI (tek 1m): ./claudeops rc gencmuh<F> --suffix=<TO> --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max
#   (self skip; mecdtfl kapalı→dahil değil; --suffix→suffix-dosyası→guard *<TO>; straggler'a --prompt='commit+TÜM remote push')
#   ⚠ guard-race: fix b8bad9e (2.1.169 proc-keşfi) SONRASI guard fresh proc'ları görür → dup riski büyük ölçüde azaldı; yine de kill→spawn boşluğu için Faz1+Faz2'de background lock-holder güvenli ([[handover-edge-cases]] edge-9). ⚠ Lock-holder'ı öldürürken parent bash DEĞİL `sleep` çocuğu da `fuser guard.lock` ile öldür (fd çocukta).

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

## READY FOR HANDOVER (2026-06-12)

**Nerede kaldık (2026-06-12):** co39 (claudeops repo, self). Fleet **23 \*42 çalışıyor** ama **4'ü EMEKLİ-pending** (↓ blok). Model: **sonnet (coding) `claude-sonnet-4-6[1m]` / opus (paper) GEÇİCİ normal `claude-opus-4-8` (`[1m]` YOK)** — 2026-06-12 kullanıcı "geçici olarak opusları normal opus"; **gencmuh dahil tüm opus non-1m**; models.tsv güncel; **geri-al:** opus satırları→`[1m]`+respawn. suffix=42, dup yok (`guard --dry-run reopened=0`), mecdtfl KAPALI. Layout 7 ws (pin co39/anomaly42/rustrino42/ulaksec40; grup1 hc/hcr/evolvi; grup2 mo/kulturiot/gedikvm/gedikido). **ulaksec40** (pid 735921, work/sec — "dokunma/KORU") + **monitoring_temp** (pid 24636, `-`) → fleet dışı, KORU.

**⏳ EMEKLİ-pending (2026-06-12):** **rr42, gedikvm42, gedikido42, kulturiot42** (kullanıcı: "şimdilik emekli edelim; önce ho faz1, açmayalım, şimdilik kaydet, sonraki ho'da hallet"). **ho-faz1 (iş kaydı) YAPILDI:** kulturiot idle-dirty puanlama işi → co-side commit `d8b0167` (github+gitlab); rr42/gedikvm42/gedikido42 zaten temizdi. models.tsv'de 4'ü `# EMEKLİ 2026-06-12` yorumlu → guard reopen ETMEZ ("açmayalım"); modeller korundu. **4 session HÂLÂ ÇALIŞIYOR — kill EDİLMEDİ.** **SONRAKİ HO'DA HALLET:** (1) Faz2 rc listelerinden 4'ü çıkar, (2) layout grup2'yi `mo` only yap (kulturiot/gedikvm/gedikido sil), (3) Model-konvansiyon roster + roster.tsv'den çıkar, (4) sonra kill. **Kalan aktif: 19 \*42** (10 opus + 9 sonnet) + ulaksec40 + co39.

**⚠⚠ BUGÜNÜN BÜYÜK DERSİ — claude 2.1.169 + dup felaketi:** claude 2.1.169'a güncellendi; **fresh `--new` session'lar `sessions/<pid>.json` yazmıyor** → claudeops kör → **guard fresh'leri 'down' sanıp sürekli DUPLICATE açtı** (gün boyu). **FIX `b8bad9e`** (`all_sessions_tsv` canlı `--remote-control` proc'larından da keşfeder) → list/guard/layout artık fresh'leri görür, **dup bitti** (`guard --dry-run reopened=0`). Detay: [[claude-2169-session-detection]]. Ayrıca sabah **API outage** (503/529) vardı → reboot ile geçti (resume'lu session'lar eski `session_` bridge'i yeniden kullanır; fresh `--new` yeni bridge kurar — outage'da takılırdı). Tüm gün için [[handover-edge-cases]] + [[feedback-ho-stop-on-error]].

**Straggler işi güvende** (co-side commit+push, junk hariç): rustrino+anomaly+gedikvm+gedikido (wrap-up doc'ları/puanlama) ve daha önce anomaly/kulturiot/mamut.

**Kalıcı altyapı (✅ DONE.md):** Cold-boot (`boot`/`snapshot`/`recover`+autostart; boot.list=co+mo; isim: **hc=videogen hcr=hoca-reader vrk=varaka mo=machine_ops**). guard watchdog (OOM→`claudeops guard`, cron */2; **oomd'ye dokunma**). ⚠ autologin kapalı (sudo); boot models.tsv lookup eksik.

**Yeni session yapacaklar:**
1. **MEMORY.md** oku — [[claude-2169-session-detection]] + [[feedback-ho-stop-on-error]] + [[handover-procedure]] + [[handover-edge-cases]] + [[add-session-to-fleet]] + [[model-1m-context]] + [[oomd-cgroup-kill]].
2. **needs-ho:** `claudeops needs-ho --from-suffix=42`. **fleet kapalıysa:** `claudeops guard` (fix sayesinde fresh'leri görür, dup açmaz). **ho'da:** Faz2 = 2 ayrı rc (sonnet `[1m]` / opus **GEÇİCİ non-1m** — kullanıcı [1m]'e döndürmediyse); **EMEKLİ 4'ünü (rr/gedikvm/gedikido/kulturiot) DAHİL ETME**; API hatası varsa DUR; Faz 2 öncesi kullanıcı onayı al.
3. **Açık TODO bug'lar:** (a) rc virgül, (b) layout orphan, (c) cancel Esc, (d) --model→auto, (e) handover --layout --group, (f) deep-ho, (g) boot models.tsv, **(h+j) rc/handover lock'u kendi al + kayıt bitene tut**, (i) --exclude base-name, (k) Faz1 bridge-verify NAME, (l) spawn-sonrası kayıt-doğrula.

**Açık kararlar:** (1) **Model: split; sonnet `[1m]` / opus GEÇİCİ non-1m** (2026-06-12; models.tsv güncel; geri-al: opus→`[1m]`+respawn). (2) **mamut** coding varsayımı. (3) **mecdtfl KAPALI** — review gelince aç (`#` kaldır + guard). (4) anomaly `rumeysa.zip` + rustrino `bench/results/` junk. (5) TOBEDECIDED #5. `~/.cache/huggingface` 29G KORU.

READY FOR HANDOVER
