# claudeops — Claude Context

Tek-dosya bash CLI: açık Claude CLI session'larını toplu yönet.

## Kritik kısıtlar

- **stdin/pty**: `< /dev/null` her `-p`'de zorunlu. Spawn: `gnome-terminal -- bash -c "claude ...; exec bash"`. Detached: `script -qfc`. `nohup &` yetmez.
- **VTE rejection**: synthetic key REDDEDİLİR. Güvenilir prompt = CLI argümanı: `-n NAME --remote-control NAME 'PROMPT'`. `-n` display, `--remote-control` RC bridge; aynı sid resume → cache'li, değiştirmek için `--new`.
- **xdotool**: `windowmove` → **`--sync` YOK** (hang). `--claude-only`: sadece aktif RC proc'larını tile'la.
- **claude 2.1.169** (`b8bad9e`): fresh `--new` session'lar `sessions/<pid>.json` YAZMIYOR → guard DUP. Fix: proc-scan. [[claude-2169-session-detection]]
- **claude 2.1.183 KILL=TRUNCATE riski**: yeni storage **lazy-checkpoint** (her mesaj değil, ara ara diske yazar). Kill'de claude'a **flush için ~2s** gerekir → `SIGTERM`'den `SIGKILL`'e **<2s = konuşma eski checkpoint'e TRUNCATE**. proc-scan sweep 0.3s'ydi → **8s grace** (`adad34f`). **Kural: kill ederken hep SIGTERM + ~8-10s bekle, sadece canlıysa SIGKILL.** Fresh session.json yazmaz → ana-kill PID'le bulamaz → sweep'e düşer. [[claude-2183-conversation-truncation]] [[handover-hold-guardlock]]
- **1M context**: `[1m]` suffix → beta header. **Opus [1m] KAPALI** (Anthropic, 2026-06-16). **Sonnet [1m] bu hafta kapalı** (token kısıtı). [[model-1m-context]]
- **Security**: ulaksec → "dokunma". `~/.cache/huggingface` 29G KORU. Commit öncesi kullanıcı onayı.

## Model (`~/.claude/claudeops/models.tsv`)

- **Coding 13** (hc hcr mo vrk rustrino anomaly evolvi done mamut hof iggy vc asp) → `claude-sonnet-4-6` plain
- **Paper 12** (aggroot oa hms hve qve rve emrgence araroot gencmuh marwan sase trroot) → `claude-opus-4-8` plain
- **co** (self) + **ulaksec** → models.tsv'de AKTİF (guard crash-recovery'de ayakta tutsun — istenen). AMA **handover YAPMAZ**: co self (filter_not_self), ulaksec base-name exclude. ⚠ guard die olunca onları fleet suffix'ine bumplar (co43→co50) → ho `--from-suffix=N` artık eşleşir → ho co+ulaksec'i base-name ile atlamalı (TODO-n). **EMEKLİ:** rr gedikvm gedikido kulturiot. **KAPALI:** mecdtfl, carla (`#` kaldır açmak için).

## Handover (3-fazlı)

```
# Faz 1  (⚠ TÜM fleet'e AYNI ANDA = sunucu rate-limit → blank-TUI hang [3/24 oldu]; gruplara böl/throttle, [[mass-faz1-ratelimit-stuck]])
./claudeops handover --from-suffix=<FROM> [--model='claude-opus-4-8']

# Faz 2 — ⚠ Faz1 SAĞLIKLI? (RFH var, 503/529 yok) → değilse DUR; kullanıcı onayı şart.
# TEK-TEK; config doğrula: python3 -c "import json;json.load(open('$HOME/.claude.json'))"
./claudeops rc hc<F> hcr<F> mo<F> vrk<F> rustrino<F> anomaly<F> evolvi<F> done<F> mamut<F> hof<F> iggy<F> vc<F> asp<F> \
  --suffix=<TO> --new --kill-first --model='claude-sonnet-4-6' --permission-mode=auto --effort=max --one-by-one
./claudeops rc aggroot<F> oa<F> hms<F> hve<F> qve<F> rve<F> emrgence<F> araroot<F> gencmuh<F> marwan<F> sase<F> trroot<F> \
  --suffix=<TO> --new --kill-first --model='claude-opus-4-8' --permission-mode=auto --effort=max --one-by-one

# Faz 3 — ws0 pin: co(self)+rustrino+anomaly+iggy (anomaly+iggy yan yana); ulaksec pin'siz → ws1
# --group tekrarlanabilir. 26 session → önce `claudeops desktops 8` gerekebilir.
./claudeops layout grid 4 --claude-only --pin=co<SELF>,rustrino<TO>,anomaly<TO>,iggy<TO> --group=hc,hcr,evolvi --group=vc,vrk
```
⚠ `[1m]` **tek tırnak ŞART** (shell glob). Target **SPACE-separated** (virgül parse bug). `--group=` base-name (suffix'siz).
**Skip kriteri:** RFH var + son RFH'den sonra yeni istek yok + repo temiz+pushed (github+gitlab).
Detay: [[handover-procedure]] [[handover-edge-cases]] [[feedback-ho-stop-on-error]] [[config-corruption-resume-hang]]

## Sınırlamalar / açık bug'lar

Wayland: layout çalışmaz. Terminal: gnome-terminal hard-coded. `rc --kill-first` permission modal keser.
Target virgül parse yok (SPACE kullan, TODO-a). Layout orphan terminal slot işgal (TODO-b). Tam: TODO.md.

## Meta

`DONE.md` = CHANGELOG. Memory: `~/.claude/projects/-home-fatihyuce-work-projects-tmp-claudeops/memory/`.
Ho-prep sync (her ho'da): TODO done → DONE; TOBEDECIDED karar → TODO.

## READY FOR HANDOVER (2026-06-21 gece)

**✅ DURUM:** co53 (self). Fleet **25 \*54** (+co53 +ulaksec53 = 27 guard-takipli), **SPLIT** (coding 13 sonnet / paper 12 opus — geçici opus-all'dan KONVANSİYONA dönüldü). suffix=54, config VALID, **guard cron AÇIK**, **DUP yok, 0 stuck**. **Opus/Sonnet [1m] KAPALI**. carla/mecdtfl KAPALI. `~/.cache/huggingface` 29G KORU.

**Bu session kazanımları (commit'li):** (1) **truncation kök-sebep+fix** `adad34f` (proc-scan sweep 0.3s→8s grace, kanıtlı — haftalarca veri kaybının sebebiydi, iş git'te güvende); (2) **handover başarı=proc-varlığı** `420fc4d` (bridge-field gecikmeli → false-"failed" düzeltildi); (3) **tam handover *53→*54**: Faz1 (21/24) + **Faz2 THROTTLE'lı 25/25, 0-stuck** (mass-Faz1 rate-limit dersi uygulandı: guard-disable + gruplara böl + ara bekleme [[mass-faz1-ratelimit-stuck]]). Kill kuralı: hep SIGTERM + ~8-10s grace. Detay: DONE.md.

**🔨 DEVAM EDEN İŞ → TOBEDECIDED #8: claudeops Python rewrite BAŞLADI** (`py/` dizini). >2000 satır bash sürdürülemez (bu gece kırılganlık somut: dup yarışı, cwd-türetme bug, quoting/pattern). Strateji: **bash `claudeops` CANLI fleet için ROOT'ta kalır**; Python `py/`'de yanında yazılır, komut-komut devralır (incremental). İlk hedef: proc-discovery (psutil → ps|grep cımbızını bitir) + `list` (read-only, canlıya karşı test).

**Yeni session yapacaklar:**
1. MEMORY.md oku — [[claude-2183-conversation-truncation]] + [[mass-faz1-ratelimit-stuck]] + [[handover-hold-guardlock]] + [[faz2-new-session-devam]].
2. **Python rewrite'a DEVAM** (TBD#8) — `py/` dizini, durum: aşağıda README/TODO.
3. ho gerekirse: İLK `uptime -s` + guard.lock kesintisiz + **Faz1/Faz2'yi gruplara böl/throttle** (rate-limit, TODO-v) + Faz2 `--new --prompt='devam'`.

**Açık kararlar:** **#8 Python rewrite (DEVAM EDİYOR)** + **#7 fleet hâlâ büyük** (split'e döndük ama 27 session = OOM + remote ~10-limit; küçült?). Tam: TOBEDECIDED.md / TODO.md.

READY FOR HANDOVER
