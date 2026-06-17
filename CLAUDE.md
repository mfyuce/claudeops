# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Teknik kararlar ve Self Protection

`find_self_claude_pid`: (1) `$CLAUDE_CODE_SESSION_ID` env var (nohup-detached'te tek güvenilir yol), (2) fallback `$$` ata zinciri. `all-but-self` buna bağlı — self'i ASLA hedef alamaz.
- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. `-n` display, `--remote-control` RC bridge (ayrı); aynı sid resume → cache'li, değiştirmek için `--new`.
- **claude 2.1.169 (KRİTİK, `b8bad9e`)**: fresh `--new` session'lar `sessions/<pid>.json` YAZMIYOR → guard DUP açar. Fix: proc-scan ile keşif. [[claude-2169-session-detection]].
- **Layout**: `xdotool windowmove` (**`--sync` YOK** — hang) + `wmctrl -s` + `get_desktop` verify. `--claude-only`: sadece aktif RC proc'larını tile'la; ssh/bare terminaller SKIP.
- **1M context**: model ID'ye `[1m]` suffix → beta header. **Opus [1m] KAPALI** (Anthropic, 2026-06-16); sonnet [1m] çalışıyor. [[model-1m-context]].

## Model konvansiyonu

**Split (2026-06-16)** — `~/.claude/claudeops/models.tsv` (name→model):
- **Coding 10:** hc hcr mo vrk rustrino anomaly evolvi done mamut hof → `claude-sonnet-4-6` + auto/max (⚠ [1m] kapalı bu hafta: token kısıtı)
- **Paper 11:** aggroot oa hms hve qve rve emrgence araroot carla gencmuh marwan → `claude-opus-4-8` + auto/max
- **co** (self) → `claude-opus-4-8` AYRI/dokunulmaz. **ulaksec** (work/sec, "dokunma") → `claude-sonnet-4-6` AYRI.
- **EMEKLİ (fleet dışı):** rr, gedikvm, gedikido, kulturiot. **mecdtfl KAPALI** (review gelince `#` kaldır + guard).
- `rc` pass-through flag'leri: `--model`, `--permission-mode`, `--effort`.

## Handover (3-fazlı, "ho" istek)

```
# Faz 1 — wrap-up (visible, sıralı, idle-only auto-skip)
./claudeops handover --from-suffix=<FROM> [--model='claude-opus-4-8']
# ⚠ --model: sonnet limit dolunca opus ile resume et (bağlam korunur)

# Faz 2 — respawn. ⚠⚠ Faz1 SAĞLIKLI? (503/529 YOK + RFH var) → değilse DUR; kullanıcı onayı olmadan geçme.
# TEK-TEK aç; config: python3 -c "import json;json.load(open('$HOME/.claude.json'))" → BOZUK → DUR + backups/.
# Register: bridge/jsonl YANILTICI (geç yazar) → proc+commit+kullanıcı-gözü. [[config-corruption-resume-hang]] [[feedback-ho-stop-on-error]]
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> evolvi<F> done<F> mamut<F> hof<F> \
  --suffix=<TO> --new --kill-first --model='claude-sonnet-4-6' --permission-mode=auto --effort=max --one-by-one
./claudeops rc aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> carla<F> gencmuh<F> marwan<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8' --permission-mode=auto --effort=max --one-by-one
# self/co skip; mecdtfl + 4 EMEKLİ dahil değil. [[handover-edge-cases]]

# Faz 3 — layout
./claudeops layout grid 4 --claude-only --pin=co<SELF>,anomaly<TO>,rustrino<TO>,ulaksec43 --group=hc,hcr,evolvi
```
⚠ `[1m]` **tek tırnak ŞART** (shell glob). Target **SPACE-separated** (virgül parse bug). `--group=` base-name (suffix'siz); grup, serbest-others'tan sonra taze desktop'a blok.
**Skip kriteri:** RFH var + son RFH'den sonra yeni istek yok + repo temiz+pushed (github+gitlab). Detay: [[handover-procedure]] + [[handover-edge-cases]].

## Bilinen sınırlamalar / açık bug'lar

- **Wayland**: layout çalışmaz. **Terminal**: gnome-terminal hard-coded. **Permission modal**: `rc --kill-first`.
- **Virgül-hedef**: parse yok, SPACE kullan (TODO). **Layout orphan terminal**: slot işgal (TODO).

## Meta

- `DONE.md` = CHANGELOG. Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
- **Ho-prep sync** (her ho'da): TODO done → DONE'a taşı; TOBEDECIDED karar → TODO'ya taşı.

## READY FOR HANDOVER (2026-06-16)

**✅ DURUM:** co43 (self). Fleet **21 \*47** auto/max — coding 10 × sonnet-1m (hc hcr mo vrk rustrino anomaly evolvi done mamut hof) + paper 11 × opus-plain (aggroot oa hms hve qve rve emrgence araroot carla gencmuh marwan). +**hof47** (optical_form/hoca-optic-form, 2026-06-16). suffix=47, dup yok, config VALID. co43+ulaksec43 fleet-respawn dışı. 4 EMEKLİ fleet dışı. **Opus [1m] KAPALI** (Anthropic 2026-06-16) → models.tsv+roster.tsv plain opus. evolvi gitlab non-fast-forward (pre-existing). `~/.cache/huggingface` 29G KORU.
**Altyapı ✅:** guard cron `*/2`, cold-boot autostart, boot.list=co+mo. isim: hc=videogen, hcr=hoca-reader, vrk=varaka, mo=machine_ops.

**Yeni session yapacaklar:**
1. MEMORY.md oku — [[config-corruption-resume-hang]] + [[handover-procedure]] + [[handover-edge-cases]] + [[feedback-ho-stop-on-error]] + [[add-session-to-fleet]] + [[claude-2169-session-detection]].
2. `claudeops needs-ho --from-suffix=47` → kapalıysa `claudeops guard`.
3. ho Faz 1 → kullanıcı onayı → **Faz 2** (2 rc, <F>=47 <TO>=48, TEK-TEK, config doğrula) → **Faz 3** layout.

**Açık TODO bug'lar (kritik):** **(h+j) guard.lock kendi al + kayıt bitene tut; (m) TEK-TEK ho** ([[config-corruption-resume-hang]]); (a) rc virgül; (b) orphan terminal. Tam: TODO.md.
**Açık kararlar:** (1) sonnet [1m] tutuldu. (2) mamut coding varsayımı. (3) mecdtfl KAPALI. (4) anomaly/rustrino junk. (5) TOBEDECIDED #5 açık-kaynak.

READY FOR HANDOVER
