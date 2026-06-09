# claudeops — DONE

> Tamamlanan iş kalemleri. Son tarih yukarıda.

## 2026-06-09 (handover *37→*38 — guard-race ÇİLESİ + yavaş RC-kayıt dersi)

- ✅ **Handover *37→*38** — kullanıcı "ho". ALL-OPUS. needs-ho: 12 HO / 10 skip. **İKİ FAZDA DA guard-race DUPLICATE** (kök: RC bridge kaydı bugün saniyeler yerine **dakikalarca** sürdü; claude.ai RC servisi/makine yükü → flock'u komut bitince bırakınca guard kayıtsız pencerede yarıştı). **Faz1** (`handover --from-suffix=37`, flock'lu): handover resume-reopen 6s bridge-verify'ı (`sessionId==eski_sid`) resume sid-fork'ta TUTMADI → 12'sine `nobridge` log, ama session'lar AÇILDI → flock-release sonrası guard 12 down-görüneni resume etti = **12 handover-copy + 12 guard-copy (24 proc)**. Ayrım: handover-copy `--model`'siz (resume satırı), guard-copy `--model`'li. **Dedup:** guard.lock background-holder ile guard bloklandı → handover-copy'ler (--model'siz, self değil) `kill -KILL -pgid` → 23 temiz. **Straggler işi co-side commit+push** (dedup öncesi güvence): anomaly (mod=6+2 untracked: k8s-audit-shipper + s1-force-restart + install.md + CHANGELOG/DONE/LESSONS/TODO → github+gitlab+origin), kulturiot (final-proje puanlama xlsx+PUANLAMA+decisions → gitlab+origin), mamut (1 commit → origin). rumeysa.zip/bench-results junk hariç. **Faz2** (`rc all-but-self --suffix=38 --new --kill-first`, flock+8s settle): rc-bridge-check BOŞ döndü (sadece co36) → 8s settle yetmedi → release sonrası kayıt ~6dk → guard **22'sini de dupledi (44 proc!)**. **Kurtarma:** background lock-holder (15dk) ile guard blokla → dedup **registered (list-PID) kopyayı tut, kayıtsızı öldür** → 22 temiz. Hayatta kalanlar guard-resume kopyaları (rc --new'ler kayıt olamamıştı) → *38'ler *37 context'li (fresh değil; süreklilik, sorun değil). **Faz3** layout 7 ws standart. suffix→38. Final: `guard --dry-run reopened=0 skipped=23`, ps-dup=0. **Yeni memory edge-9 (yavaş-kayıt guard-race) + edge-10 (registered-kopya dedup).** Yeni TODO: (h+j) rc/handover lock'u kendi alsın + kayıt bitene kadar tutsun, (k) Faz1 bridge-verify NAME eşlesin, (l) spawn sonrası kaydı doğrula.

## 2026-06-08 (handover *36→*37, temiz)

- ✅ **Handover *36→*37** — kullanıcı "ho". ALL-OPUS (sonnet limit dolu). needs-ho: 10 HO / 12 skip. **Faz1** 10 wrap-up (hc hcr mo rustrino anomaly kulturiot gedikvm gedikido rr evolvi; hepsi *36 zaten opus → `--model` gerekmedi) → **rescan straggler 0** (hepsi mod=0/unpush=0 temiz+pushed; gedikido `ODEV_INCELEME_BULGULARI.md` + evolvi `CHANGELOG.md` commit'lendi; rustrino `bench/results/` + anomaly `rumeysa.zip` junk untracked kaldı). 12 skip. **Faz2** = ALL-OPUS **tek komut** `rc all-but-self --suffix=37 --new --kill-first --model='claude-opus-4-8[1m]' --permission-mode=auto --effort=max` → 22 session *37, duplicate 0, suffix→37. **Faz1+Faz2 elle `guard.lock` flock** (edge-case-8 mitigation; guard-race önlendi — iki ho üst üste doğrulandı). **Faz3** layout 7 ws (pin co36/anomaly37/rustrino37; grup1 hc/hcr/evolvi ws5; grup2 mo/kulturiot/gedikvm/gedikido ws6; rr37 ws4 tek). mecdtfl Faz dışı (KAPALI). co self → co36 kalır (all-but-self bump etmez; guard cwd-match co37 duplicate açmaz). ⚠ **Bug:** `handover --exclude=<base-name>` filtrelemiyor (anomaly yine wrap-up edildi → suffix'li isim ister/buggy, TODO).

## 2026-06-07 (handover *35→*36 + mamut fleet'e eklendi + mecdtfl kapatıldı)

- ✅ **Handover *35→*36** — ALL-OPUS (kullanıcı "faz 2 opus"; sonnet limit dolu). 23 session *36, duplicate 0; Faz1+Faz2 flock'lu (guard-race önlendi, *34→*35'teki done35 dup tekrarlanmadı). 10 wrap-up. **mamut35 fleet'e eklendi** ("ekle"/"sende"): bare `claude` → convention spawn (cmd_new kırık → rc visible-spawn pattern elle), roster (sonnet-canonical) + models (opus-temp) + revert-list + layout. Yeni memory [[add-session-to-fleet]] (mamut **coding varsayıldı**). **mecdtfl36 KAPATILDI** (review'a kadar; models.tsv comment-out → guard skip). Önceki opus-resume wrap-up `--model` passthrough + guard 5-bug fix `f4d949f` geçerli.

## 2026-06-04 (handover *33→*34 + guard OOM-recovery 5 kök bug sertleştirme)

- ✅ **Guard OOM-recovery 5 kök bug fix** (`f4d949f`) — OOM sonrası cron `reopened=0 skipped=22` + pencerelerde `claude: command not found` sendromunun kökü 5 bağımsız bug: **(1) PATH**: gnome-terminal child spawner'ın değil SERVER'ın env'ini miras alır; cron minimal-PATH'le yeni server başlatınca `~/.local/bin/claude` bulunamıyor → `SPAWN_ENV="PATH=$HOME/.local/bin:\$PATH"` her `bash -c` spawn'ına command-prefix (claudeops'un kendi PATH guard'ı ayrıca). **(2) stale-json liveness**: `all_sessions_tsv` `~/.claude/sessions/*.json`'u pid canlılığı kontrol etmeden okuyordu; SIGKILL'de json silinmez → 22 ölü session "çalışıyor" sanılıp skip → `reopened=0` sonsuza → fix: `os.kill(pid,0)` + `procStart==/proc/pid/stat` field22 (pid-reuse koruması — OOM 274 proc öldürür, pid'ler hızla geri döner). **(3) resume semantiği**: guard 'son ho'dan sonra iş varsa resume' (suffix-gate) yapıyordu → idle/crash'te FRESH açıp *33 context kaybettiriyordu; kullanıcı: "cron önceki/son session'dan devam etmeli" → `cmd_boot` gibi HER ZAMAN en güncel jsonl resume (handover ETKİLENMEZ — o ayrı komut `rc --new`). **(4) agent-sid çöpü**: `_latest_sid_for_cwd` subagent transcript (`agent-*.jsonl`) en güncel olunca `resume=agent-a2...` deniyordu → `! -name 'agent-*'` + UUID-only basename filtresi. **(5) concurrent-guard duplicate**: iki guard (cron+manuel ya da yavaş-cron overlap) aynı anda fleet'i down görüp HEPSİNİ açar → her cwd'de duplicate (37 proc gördük) → `flock -n` non-blocking, kilit başkasındaysa "atlandı". Verified: gerçek cron env (minimal PATH, DISPLAY yok) `hms33 ← resume=d9565347` doğru açtı, `claude --resume ... --model claude-opus-4-8[1m]` process cmdline'da. Stale-json temizlendikten sonra `list` 22→1 (sadece co).
- ✅ **Handover *33→*34** — Faz1: opened=17/skipped=4/failed=0. Straggler'lar: mo+vrk (unpush=2), anomaly (mod=7/unt=3), mecdtfl (unt=2), evolvi (unt=1). Faz2: sonnet-10 + opus-11 respawn `[1m]`/auto/max/RC. Faz3 layout standart.

## 2026-06-03 (handover *32→*33 + idle-session/kısa-sid resume dersleri)

- ✅ **Handover *32→*33** — kullanıcı "ho => 33". needs-ho: 11 HO / 10 skip. **Faz1** wrap-up (opened=8/skip=13) → **re-scan straggler ayrımı**: (a) **push-only** (mo/vrk/kulturiot working-tree TEMİZ ama tek mirror behind: vrk **gitlab 14-ahead**, mo+kulturiot **origin 1-ahead**) → **co kendisi push etti** (commit'li, fast-forward, güvenli — session'ı uğraştırmaya gerek yok); (b) **commit-gerektiren** anomaly (mod=5: k8s audit pipeline Dockerfile/deploy-yaml/shipper.py + 5 MD) → **ayakta *32'ye `send` commit-prompt** (kill GEREKMEDİ; *32 zaten geçmişiyle ayakta, k8s context'i biliyor → `fece838` commit+push, junk rumeysa.zip kaldı); (c) **junk-only** mecdtfl(`main_1_page.pdf`)/rustrino(`bench/results`) → temiz sayıldı, idle respawn. **DERS session krizi** (kullanıcı "wrap up ama 32'den atmalısın"): Faz2 kısmi-çalışmada hcr/kulturiot/gedikvm/gedikido **idle *33 açılmıştı (jsonl YOK=boş bağlam)** → bunlara wrap-up göndermek anlamsız (ne yaptıklarını bilmiyorlar). Çözüm: boş *33 kill → **\*32 sid'i TAM UUID ile `--resume` + wrap-up CLI-arg** ile aç (geçmiş+wrap-up otomatik). **İlk denemede 8-char kısa-sid verdim → hcr hariç 3'ü SESSİZCE fresh açıldı** (yeni sid aldılar, geçmiş yok); tam UUID ile düzeltildi. 4 ders temizlendi (mod=0/unt=0/remote+0). **Faz2** 17 temiz *32 → *33 (sonnet 6: hc mo vrk rustrino anomaly evolvi; opus 11) + 4 ders *33 → 21 *33. **Orphan temizliği**: 12 `exec bash`-orphan (kill edilen *32'lerden, layout'u 9 ws'ye şişirdi) `gnome-terminal class + ✳/⠂-prefix-yok` ile kapatıldı → 7 ws temiz layout. **Yeni edge case'ler** (memory [[handover-edge-cases]] 5-6): idle session wrap-up alamaz (*32-resume gerek) + `claude --resume` TAM-UUID şart (8-char sessiz-fresh). Faz3 layout pin co/anomaly33/rustrino33 + grup1(+evolvi)→ws5 + grup2→ws6.

## 2026-06-03 (guard watchdog + oomd cgroup-kill kök neden)

- ✅ **`claudeops guard` watchdog komutu** — kullanıcı: "cli'lar kapanınca kapanan session'ı bulup açsın + cron". `cmd_guard`: `models.tsv` (model) + `roster.tsv` (cwd) + suffix state okur, beklenen fleet'i çalışanlarla diff'ler, eksikleri `--resume <latest-sid>` ile gnome-terminal'de açar. **İdempotent**: zaten çalışanları atlar — hem isim (`co32`) hem **cwd** eşleşmesi (isim değişse de aynı cwd varsa skip → co29 çalışırken co32 açıp **2 co** sorunu fix'lendi, `29d2e9b`). **Resume vs fresh**: sadece son mesaj timestamp'i suffix-state mtime'dan SONRA ise resume, yoksa fresh `*32` (suffix-öncesi idle *31 session'ları temiz açılır; `eb728a9`). Flag: `--boot` (X/WM 90s bekle), `--lock`, `--dry-run`, `--pace`. **roster.tsv** 21 fleet session'ıyla tam dolduruldu (9 eksikti; cwd'ler jsonl'lerden çekildi). Autostart `.desktop` `boot --lock` → `guard --boot --lock`. **Cron** `*/2 * * * *` (her 2dk).
- ✅ **OOMD CGROUP-KILL kök neden + guard DISPLAY oto-tespit** — fleet (sen dahil 21 session + co) bir anda kapandı. **Reboot DEĞİL** (sistem dün 16:12'den ayakta). Asıl neden journal'da: `Haz 03 16:56:03 gnome-terminal-server.service: systemd-oomd killed 274 process(es) in this unit. Main process exited code=killed status=9/KILL`. **`systemd-oomd`** (userspace, kernel OOM değil → `dmesg`'te yok) gnome-terminal-server.service cgroup'unu **komple SIGKILL** etti. Tetik: tek cgroup 18 saat CPU (`Consumed 17h 58min`) + 274 process → memory-pressure (PSI) eşiği; `free` 35Gi boş gösterse de oomd PSI/swap'e bakar. **KRİTİK MİMARİ GERÇEK**: 20 fleet + co + tüm child'lar (python/npm/playwright) **TEK cgroup** `/user.slice/.../app-org.gnome.Terminal.slice/gnome-terminal-server.service` → oomd **process değil cgroup** öldürür, "fleet muaf ama py child değil" imkansız (aynı cgroup). **Kullanıcı kararı: oomd'ye dokunma, guard cron fix yeter** (öldürülse de 2dk'da geri gelsin). **Bug**: cron `DISPLAY=:0` hardcode'tu ama gerçek `:1` → guard her 2dk "DISPLAY/WM yok, atlanıyor" deyip ÇALIŞMIYORDU (watchdog ölüydü). Fix `_detect_display` (`18295fb`): env'de WM yoksa çalışan GNOME process'inden (gnome-shell>gnome-session>nautilus>gnome-terminal-server) `/proc/PID/environ`'dan DISPLAY+XAUTHORITY+DBUS çeker (reboot'ta display değişse de tutar). Temiz-env testte `:1` + gdm Xauthority doğru bulundu. Cron sadeleşti (sadece `XDG_RUNTIME_DIR`). Kurtarma: guard ile 21/21 reopen (aktifler resume, idle fresh) + standart layout. Detay: memory [[oomd-cgroup-kill]].

## 2026-06-01 (handover *30→*31 + model-split'e dönüş + models.tsv)

- ✅ **Handover *30→*31 + iki-grup model-split** — kullanıcı "ho başlayalım" + "faz 3'te kodlama→sonnet, paper→opus, max/auto/1m yine; liste yap karar verelim kaydet sonra exec". **Model kararı** (AskUserQuestion ile borderline netleşti, eski 13/7 split revize): **Sonnet (coding, 9):** hc hcr mo vrk rustrino anomaly kulturiot gedikvm gedikido (+co); **Opus (paper, 11):** rr aggroot oa hms hve qve rve emrgence araroot mecdtfl carla. (carla seçilmedi→opus; gedikvm/gedikido seçildi→sonnet.) Harita **`~/.claude/claudeops/models.tsv`** (name→model, base-name) yeni eklendi. **Akış:** Faz1 wrap-up (önce mecdtfl hariç → opened10/skip10; sonra mecdtfl+rr ayrı çağrı) → **straggler tespiti** (kullanıcı "gönderilmeyenlerde yeni commit olursa onlara da": skip'lenen `anomaly30` aslında mod=4/untracked=2/**unpush=5** taşıyordu; resume edilince kendini "tam" sanıp git commit ATLAMIŞTI — jsonl'inde "hepsi yerinde" diyip idle olmuş; 3-remote repo [internal origin + github/gitlab mirror]) → Faz3 **2-grup respawn = 3 rc çağrısı** (sonnet-idle 6, **sonnet+commit-prompt 3** [anomaly/gedikido/kulturiot, "commit+TÜM remote'lara push" prompt'uyla fresh], opus-idle 11), `--suffix=31 --new --kill-first`, hepsi `[1m]`/auto/max/RC → **straggler doğrulandı** (anomaly: docs+FINDINGS commit, github+gitlab 0-ahead, sadece rumeysa.zip junk kaldı; gedikido/kulturiot: temiz + gitlab/origin 0-ahead) → Faz3 layout standart (pin co/anomaly31/rustrino31 + grup1 ws4 + grup2 ws5). suffix state→31. **Ders:** resume-edilen session kendi git durumunu yanlış değerlendirip commit atlayabiliyor → straggler için fresh+explicit-prompt güvenilir.

## 2026-05-31 (window grouping + layout --group + needs-ho detection + app-id handover + cold-boot autostart + reboot recovery)

- ✅ **Cold-boot oto-açılış (`boot`/`snapshot`/`recover`) + autologin + reboot recovery** — kullanıcı: "reboot sonrası login olmadan bu CLI nasıl oto açılır?". Gerçek: CLI X11 desktop'a bağımlı (gnome-terminal/wmctrl/xdotool) → tam-headless olmaz; çözüm **passwordless autologin + autostart hook**. Kapsam (kullanıcı): boot'ta sadece **co + mo** açılsın (gerisini co açar). **`claudeops boot [--lock] [--layout] [--from-roster] [--pace=N]`**: `~/.claude/claudeops/boot.list` (curated co+mo) okur, X/WM hazır olana dek bekler (~90s), her session'ı **base-name + SON SUFFIX** (`co30`) ve cwd'sinin **en güncel transcript'iyle `--resume`** ederek paced açar (geçmiş korunur — "son session no'sundan başlamalı"+"giden session bilgisi önemli"), `--lock` ile EN SON ekranı kilitler ("autologin olur olmaz lock" → fleet arkada, şifreyle aç). Suffix state `~/.claude/claudeops/suffix` (`rc --suffix=N` oto-yazar). Resume sid `_latest_sid_for_cwd` (jsonl içi gerçek "cwd" eşleştir — encoding lossy, ters yön; compaction'da sid değişse de en taze). **`claudeops recover [--since=ISO]`** READ-ONLY resume tablosu (cwd·sid·git-dirty·son-aktif). **`claudeops snapshot`** canlı fleet → roster.tsv. `~/.config/autostart/claudeops.desktop` → `boot --lock`. **REBOOT RECOVERY (bu oturum):** reboot 20 *30 session'ı düşürdü; hiçbir konuşma kaybolmadı (jsonl reboot'tan sağ çıkar) → handover-log *29 sid'lerinden isim→cwd kesin çözüldü, 9 iş-yapan session geçmişiyle resume (`boot --from-roster`), 11 idle-only fresh açıldı; 20/20 tek temiz server'da (reboot iki-server wedge'ini temizledi — READY'nin dediği gibi), standart layout (pin+2grup). isim sürprizi: **hc=videogen**, **hcr=hoca-reader**, **vrk=varaka**, **mo=machine_ops**.

- ✅ **Wedged-server handover (app-id workaround)** — Faz 1'de gnome-terminal-server (1436029) rapid-spawn'dan **wedged** oldu ("Failed to get screen", server canlı ama yeni terminal AÇAMIYOR; default'u restart = co29'u öldürür → yasak). Çözüm: ayrı **`--app-id`** server instance'ı yeni terminal açabiliyor. `cmd_rc`: `--app-id=X` (gnome-terminal ayrı server'da) + `--pace=N` (spawn arası bekleme; rapid spawn wedge sebebi). `cmd_layout`: `--server=PID` (gtp override → çok-server'da doğru server'ı hedefle). **29→30:** 20 session `fleet30` app-id server'ında respawn (paced=6, 0 wedge), co29 default server'da kaldı. Faz 3 layout `--server=fleet30`. İki-server durumu reboot'a kadar; co29 reboot'ta normale döner. Faz 1 wrap-up'lar tek-tek RC-resend (rate-limit burst'ten kaçınmak için) — anomaly/oa/mo/rr/mecdtfl commit+push+RFH, gerisi commit'liydi.

- ✅ **`needs-ho` generic tespit (commit-vs-baseline sinyali)** — handover sınıflandırması `repo_dirty`+jsonl'e bakıyordu; commit'lenip PUSH'lanmış ama jsonl'siz (compaction → sid değişmiş) session'ları "idle-clean" sanıp **ATLIYORDU** (gedikvm/gedikido/kulturiot 85dk önce commit'lemişti ama Faz 1 skip etti — kullanıcı yakaladı). Fix: `needs_ho()` 6 sinyal (tracked-mod/staged · untracked · unpushed/behind · **commit-since-baseline** · jsonl-not-RFH); biri pozitifse ho. `repo_committed_since()` + `repo_untracked_count()` helper. Baseline state `~/.claude/claudeops/last-handover.ts` (her ho sonunda `_handover_stamp`). **`claudeops needs-ho [--from-suffix=N] [--baseline=ISO] [--no-fetch]`** READ-ONLY 6-sinyal tablo (ad-hoc python yerine). Handover pre-check + per-session skip artık `needs_ho` kullanıyor; jsonl'siz-ama-iş-yapmış → WARN (silent skip değil). **Baseline = per-repo "ho SONRASI commit-id"** (kullanıcı: "commit ids must be the one after ho"): `repo_committed_since` HEAD≠baseline-id (primary) / son-commit-zamanı>ts (fallback, ilk kurulum); `_repo_baseline_set` respawn'da (`rc --new`) + **`claudeops stamp-baseline <names>`** ile yazılır (`~/.claude/claudeops/baselines/<sha1-toplevel>`). anomaly29 rate-limit'te commit edemedi (RFH yazdı, commit adımında kesildi) → co güvene aldı (`7e58d89`, github+gitlab+origin), baseline stamp'lendi.
- ✅ **`layout --group=` flag** (`a9867da`, github+gitlab) — belirli session'ları (base-name eşleşme, suffix stripli → handover'da 29→30 değişse de tutar) tek desktop'ta blok halinde tutar; serbest-others'tan SONRA kendi taze desktop'una yerleşir, asla bölünmez. Tekrarlanabilir (çok grup). `cmd_layout`: arg parse + oth_wins'i grouped/real_oth ayrımı (`win_by_base`, base = `${nm%"${nm##*[!0-9]}"}`) + grup yerleştirme bloğu + max_ws ile needed_ws düzeltmesi. Standart Faz 3 komutu + handover-procedure memory + --help güncellendi. Base-name kullandığı için Faz 3'te `<TO>` bump gerekmez (sabit). 2 grup tanımlandı: **grup1 `hc,hcr,mecdtfl` → ws4** (BR boş), **grup2 `mo,kulturiot,gedikvm,gedikido` → ws5** (tam). 12 serbest-other ws1-3 doldurur. İlk yazılan grup düşük ws alır.
- ✅ **Window grouping (in-place, kapatmadan)** — kullanıcı isteğiyle 2 grup tek desktop'a toplandı (önce manuel in-place swap, sonra `--group` ile kalıcı). Swap kuralı: displaced pencere mover'ın eski slotuna (mecdtfl29↔aggroot29 TR↔TR, kulturiot29↔carla29 TL↔TL). xdotool windowmove + wmctrl -t + read-back verify. Kill/respawn YOK.

## 2026-05-30 (28→29 transition + tek-model geçişi + 1M context + --effort flag)
- ✅ **`rc --effort` flag** (`4e31b4a`) — `--effort low/medium/high/xhigh/max` pass-through eklendi (`effort_arg` → `model_arg`'a append). `claude --effort` CLI flag'ini destekler.
- ✅ **Handover 28→29 (standard)** — 20 session 29-suffix'e geçti, --prompt yok (idle). Faz 3 layout grid 4 --pin=anomaly29,rustrino29.
- ✅ **Tek-model geçişi** — opus/sonnet ayrımı KALDIRILDI. Tüm 20 session tek modelde: `claude-opus-4-8[1m]` (1M context) + `--permission-mode=auto` + `--effort=max`. Faz 2 artık tek `rc` komutu (eski 2 komut: opus grubu + sonnet grubu). CLAUDE.md + handover-procedure memory güncellendi.
- ✅ **1M context mekanizması keşfedildi** — claude binary (v2.1.157) strings analizi: `function TZ(H){return /\[1m\]/i.test(H)}` → model ID'de `[1m]` varsa `Sg=context-1m-2025-08-07` beta header eklenir + context=1e6. Alternatif: `CLAUDE_CODE_MAX_CONTEXT_TOKENS` env var. Model'in `-p` ile self-report'u güvenilmez (200K diyordu). Memory: [[model-1m-context]]. Menüde "Default (recommended) — Opus 4.8 with 1M context" = `claude-opus-4-8[1m]`.
- ✅ **CLAUDE.md büyüklük optimizasyonu** — 83→58 satır. Model-permission konvansiyonu tek-modele güncellendi, eski READY bloğu yenilendi, Self Protection + Bilinen sınırlamalar sıkılaştırıldı.

## 2026-05-28 (handover 26→27→28 + araroot/aggroot eklendi)

- ✅ **Handover 26→27 (TODO-loop)** — 19 session (12 opus + 7 sonnet) 27-suffix'e geçti. Her session'a "TODO.md'deki karar gerektirmeyen tüm iş kalemlerini çöz, 5dk'da bir bak, sadece kullanıcı kararı gerekince dur" prompt'u verildi.
- ✅ **Handover 27→28 (standard)** — 19 session 28-suffix'e geçti, --prompt yok (idle açıldı). Faz 3 layout grid 4 --pin=anomaly28,rustrino28 tamamlandı.
- ✅ **araroot28 + aggroot28 yeni session** — opus grubuna eklendi; araroot ws2 (trroot'un eski slotu), aggroot ws5.
- ✅ **trroot28 kapatıldı** — simdilik; bir sonraki ho'da opus listesinden çıkar.
- ✅ **desktops.local.md** — 26→27→28 geçişleri + yeni sessionlar güncellendi.

## 2026-05-26 (repo_dirty çift-remote fix + handover 25→26)

- ✅ **`repo_dirty` çift-remote + fetch + behind** (`418ebf8`) — eski hâl sadece `@{u}` bakıyordu; çift-remote'lu repolarda (github+gitlab) birine push edilip diğerine edilmemiş "clean" yanılması vardı. Yeni: HER remote için ahead (unpushed) **ve** behind (remote ileride) kontrolü. `repo_fetch_once()` eklendi: pre-check'te session başına 1× `git fetch --all` (timeout 20s, dedup) → ref'ler taze.
- ✅ **idle-only-DIRTY rescue** — Faz 1 skip edilen gedikvm/gedikido/kulturiot'un commitlenmemiş tracked değişiklikleri fetch+ahead/behind ile tespit edildi → fresh respawn + commit prompt CLI-argümanıyla kendi repolarında commitlendi + tüm remote'lara push'landı. Doğrulama: ahead=0 behind=0 her remote'da.
- ✅ **Handover-prep MD sync kuralı** (CLAUDE.md Meta) — her ho'da: (1) TODO'da done → DONE'a taşı+sil; (2) TOBEDECIDED'da karar verilmiş → TODO'ya taşı+sil.
- ✅ **TOBEDECIDED #4 + #6 kapatıldı** — layout default=4 ve github+gitlab ikisine push kararları Kapatılmış bölümüne taşındı.
- ✅ **TODO: Layout in-place** — xdotool no-sync + read-back implement edilmişti (2026-05-25); TODO'dan çıkarıldı.
- ✅ **Handover 24→25 + 25→26** — 19 session (12 opus + 7 sonnet) iki round'da geçti, hepsi idle+auto. idle-only-DIRTY rescue ile kayıp iş yok.
- ✅ **TOBEDECIDED #7** — açık-kaynak durumunda kişiye/makineye özel kısımlar (session listeleri, path'ler, geometri, terminal) lokal kalmalı → karar bekliyor.

## 2026-05-25 (b) (sonnet→auto + layout hız/self-pin + cancel + handover --force)

- ✅ **Sonnet → auto** — sonnet'e de `--permission-mode=auto` geldi; convention "hepsi auto" oldu (model hâlâ ayrı: opus/sonnet). 7 sonnet session auto ile respawn. CLAUDE.md + memory güncel.
- ✅ **Layout hız fix (321s→~3-9s)** — `xdotool windowmove --sync` pencere zaten hedefteyse ConfigureNotify gelmeyince ~15s hang ediyordu (20 pencere=321s). Fix: önce "zaten hedefte mi?" read-back kontrol (idempotent anında döner) + `--sync`'siz move + sleep + verify + retry. Ayrıca desktop-grouped (`_ensure_desktop`: switch sadece ws değişince → switch sayısı=desktop sayısı).
- ✅ **Layout self-pin** — self session (co) artık ws0'a pinleniyor (self_pid→session.json→name). Eski "machine cleaning required" başlık kontrolü hiç eşleşmiyordu → self ws1'e kaçıyordu.
- ✅ **`claudeops cancel <names>`** — RC'yi bloklayan modal'a (permission/model/trust dialog) Esc gönderir (görünür yap+activate+Esc). VTE reject ihtimaline karşı rc --kill-first fallback önerir.
- ✅ **`handover --force`** — skip kontrollerini (already-done/idle-only/dirty) baypas, hepsine gönder. jsonl yoksa fresh-spawn (model/perm /proc/cmdline'dan). Default'ta skip geçerli (kullanıcı: "bu sefer dirty bakmasın hepsine, dahakine baksın").
- ✅ **ho mesajına cross-session satırı** — "paralel/diğer session'larda konuşulup kaydedilmemiş bulgu/karar kaldı mı? kaydet."
- ✅ **`handover --layout [--pin=a,b]`** — tüm wrap-up pencereleri açıldıktan sonra otomatik `layout grid 4` çalıştırır (kullanıcı: "Faz 1 komutları gittikten sonra layout çalışmalı"). Faz 1 + tile tek komutta.
- ✅ **23 forced-ho sonucu** — 19/19 işlendi (force). dirty-check fix değerini kanıtladı: emergence dışında carla23/anomaly23/vrk23 de "idle-only KİRLİ" (limbo iş) çıktı → fresh-spawn + commit prompt'uyla kendileri commit etti. 15 temiz session RFH baseline aldı.

## 2026-05-25 (22→23 transition + handover skip kriteri + layout xdotool fix)

### Handover doğruluk

- ✅ **Skip kriteri yeniden tanımlandı: `handover_done()`** — kullanıcı: "repo temizliği yetmez". Doğru kriter = jsonl'de READY FOR HANDOVER var **VE** son RFH'den sonra yeni user isteği yok **VE** repo temiz+pushed. Üçü birden → güvenle atla. Aksi → wrap-up. jsonl parse (python) ile son-RFH-index vs son-user-istek-index karşılaştırılır.
- ✅ **`repo_dirty()` helper** — idle-only skip artık jsonl yokluğuna değil repo durumuna da bakıyor. jsonl yok + repo KİRLİ → WARN (limbo iş, emrgence vakası), sessiz skip yok.
- ✅ **PRE-CHECK 2 sınıflandırma** — handover öncesi: needs-ho / already-done / idle-clean / idle-DIRTY listesi basılır.
- ✅ **emrgence kurtarma** — 2 gündür commit'lenmemiş 11. tur wrap-up (idle-only döngüsünde limboda). Fresh respawn'da **commit prompt'u CLI argümanı olarak** verilerek (keystroke değil → VTE reject bypass) session kendi commit+push etti (`9be23ae`).

### Layout (kapatmadan in-place)

- ✅ **`_place_win` wmctrl -e → xdotool --sync** — Mutter multi-monitor'da `wmctrl -e` flaky (pencereler ekran dışına/üst üste). Kök neden: xdotool windowmove pencere **görünür (aktif desktop) değilse** yanlış konuma taşıyor. Fix: hedef desktop'a ata + `wmctrl -s` ile SWITCH + `xdotool get_desktop` ile doğrula (Mutter rapid switch coalesce ediyor) + sonra taşı. `_reopen_win` da xdotool'a geçti. Dependency check'e xdotool eklendi.
- ✅ **wmctrl -G güvenilmez** — koordinatları ~2× raporluyor (scale artifact). Gerçek konum doğrulaması `xdotool getwindowgeometry` ile yapılmalı.

## 2026-05-24 (convention genişletme + idle-only handover fix)

- ✅ **gedikvm, gedikido, kulturiot → opus auto convention** — 3 mevcut 21-session (BLM308 veri madenciliği, BLMS431 ileri derin öğrenme, kultur/iot) handover-procedure memory + CLAUDE.md Faz 2 rc örneğine eklendi. Sonraki handover round'undan itibaren dahil. Toplam: opus auto 12 + sonnet acceptEdits 7 + co (self) = 20 (+ sqli SKIP).
- ✅ **Handover Faz 1: idle-only session pre-flight skip** — `--prompt YOK` ile açılan session hiç mesaj almazsa jsonl yazılmaz; kill edilince resume edilemez (`nobridge` fail). Vaka: 21→22 Faz 1'de emrgence21 (20→21'de idle açılmıştı). Fix: cmd_handover pre-check 2 ekledi — `find_jsonl` boşsa session'ı kill etmeden SKIP. Summary'de `skipped=N` ayrı sayılır. Faz 2'deki `rc --new --kill-first` fresh respawn'da otomatik hallolur. Memory: [[handover-edge-cases]].
- ✅ **rc: orphan target warning** — `claudeops rc <name>` ile verilen isim aktif session'larda yoksa sessizce skip ediliyordu. Vaka: 21→22 Faz 2'de emrgence21 rc'ye verildi ama emrgence21 Faz 1'de zaten kill edilmişti → emrgence22 spawn olmadı. Fix: cmd_rc başına WARN ekledi (eşleşmeyen isimleri liste olarak söyler + `claudeops new` önerir). emrgence22 manuel `gnome-terminal ... claude --model opus --permission-mode auto -n emrgence22 --remote-control emrgence22` ile açıldı (memory: [[handover-edge-cases]] case 3).

## 2026-05-23 (20→21 transition + mo migration + migrate komutu)

### Yeni komut / flag

- ✅ **`claudeops migrate <name> --to=<new-cwd>`** — session cwd taşıma + ilgili md/memory dosyalarını taşıma + path rewrite + trust dialog patch + opsiyonel `--gh`/`--glab` ile private remote yaratma + respawn (model/permission-mode /proc/<pid>/cmdline'dan inherit).
- ✅ **`claudeops handover --exclude=name1,name2`** — handover'dan belirli session'ları skip. 2026-05-23 20→21 transition'ında trroot dahil edilmedi sonra dahil edildi senaryosunda kullanıldı.

### Operasyon

- ✅ **mo session /home/fatihyuce → /home/fatihyuce/work/projects/tmp/machine_ops** — yeni cwd, github + gitlab private remote, CLAUDE.md/howtos.md/sessions-snapshot.md taşındı, memory dosyalarındaki path'ler güncellendi, trust patch + .claude.json backup.
- ✅ **20→21 transition** — Faz 1: 17 wrap-up (hms20+hve20 manuel önce, sonra 15 handover-komutu, trroot dahil), Faz 2: 16 fresh respawn (sqli SKIP, **--prompt YOK** kullanıcı tercihi → idle açıldılar), Faz 3: layout grid 4 --pin=anomaly21,rustrino21. sqli20 wrap-up sonrası kapatıldı.
- ✅ **hve20 recovery** — handover sırasında TaskStop ile yarıda kalan hve20 (kill edildi, yeni TUI açılamadan) manuel `gnome-terminal --window ... claude --resume <sid> --remote-control hve20 '<HANDOVER_MSG>'` ile wrap-up'a yeniden alındı.

### Kararlar

- ✅ **Faz 2 respawn'da `--prompt` opsiyonel olabilir** — kullanıcı 2026-05-23'te "devam yazmayalim, sadece acilsin" dedi. Yeni session'lar idle açıldı, kullanıcı manuel prompt verecek.
- ✅ **sqli21 SKIP** — kullanıcı "sqli simdilik bir daha acilmasin" → Faz 2'ye girmedi, sqli20 wrap-up sonrası kill edildi (`./claudeops kill sqli20`).

## 2026-05-17/18 (yoğun iterasyon — production tests)

### Kritik fix'ler

- ✅ **CLAUDE_CODE_SESSION_ID env var self-protection** — nohup-detached script $$ ata zincirinde claude bulamıyordu, filter_not_self no-op → SELF KILL incident'i (pid 78492 öldü, harness 1506400 olarak rebirth). Fix: env var ile sessionId match (`find_self_claude_pid`'in birinci preferred mekanizması)
- ✅ **`-n NAME + --remote-control NAME` combo** — `--remote-control devam` "devam"ı RC name yapıyordu (claude.ai mobilde "devam" gözüküyordu). Doğru syntax: `-n NAME --remote-control NAME 'prompt'` üçü ayrı. Session display name, RC bridge name, initial prompt.
- ✅ **Pre-busy-wait safety in rc --kill-first** — handover mid-process'te kill ile 7 repo uncommitted state'te yarım kaldı. Fix: kill-first ile target busy'lere idle olana kadar bekle (60dk timeout). cmd_handover'a da var.
- ✅ **xdotool windowactivate + type + key Return** — initial prompt auto-submit ve permission prompts için. `--clearmodifiers` + sync. Permission prompt'lar kısmen sorunlu (VTE/Ink synthetic keypress reject), type devam+Enter genelde çalışıyor.
- ✅ **gnome-terminal-server pid match fix** — `pgrep -x gnome-terminal-server` boş döner (comm 15-char truncate). Doğrusu `ps -eo pid,comm | awk '$2 == "gnome-terminal-"'`. cmd_cleanup + cmd_layout düzeltildi.
- ✅ **wmctrl -s gerçek visual desktop switch** — xprop -root _NET_CURRENT_DESKTOP sadece property set ediyor (Mutter görsel uygulamıyor). wmctrl -s ClientMessage yolu ile Mutter visible switch yapıyor.
- ✅ **claude.ai/projects path encoding** — `_` ve `/` ikisi de `-` olarak encoded. tr '/_' '-'.

### Yeni flag'ler / komutlar

- ✅ `--prompt=<text>` (rc komutu) — initial prompt için
- ✅ `--model=<sonnet|opus>` (rc/handover) — per-session model seçimi
- ✅ `--permission-mode=<auto|acceptEdits|...>` (rc/handover)
- ✅ `--sticky=<csv>` (rc) — açılan pencereleri sticky yapar
- ✅ `--desktop=<name>:<n>,...` (rc) — open sonrası belirli desktop'a
- ✅ `handover` komutu — kill+wrap-up+respawn zinciri (visible mode default, RC + tool onayı için)
- ✅ `layout --reopen` flag — Mutter in-place desktop change buggy olduğunda kill+switch+reopen on target desktop (proven recipe)
- ✅ `--include-sticky` / sticky-skip default — sticky pencerelere layout default'ta dokunmaz

### Kararlar (TOBEDECIDED → kapatıldı)

- ✅ **Opus → --permission-mode=auto** (classifier-based, esnek)
- ✅ **Sonnet → --permission-mode=acceptEdits** (Edit/Write auto, Bash hâlâ onay ister)

### OCR + screenshot

- ✅ tesseract 4.1 + ImageMagick (sudo apt gerekmedi, varolan) ile permission prompt'ları OCR ile okuma kanıtlandı
- ✅ `import -window $WID /tmp/out.png` + `tesseract /tmp/out.png stdout` çalışıyor
- Keystroke auto-submit hâlâ blocker (TODO)

### Production tests (2026-05-17/18)

- ✅ 14 session compact pipeline (sequential, sıfır kayıp, jsonl backup'lı, isCompactSummary marker ile doğrulamalı)
- ✅ Birden çok handover round + 13→14→15 transition cycles
- ✅ Layout grid 4 --reopen --pin=rustrino+anomaly (test edildi, çalışıyor — Mutter snap'ten kurtaran tek yol)
- ✅ desktops 5 + 2×2 grid + pin (kullanıcı eDP primary'de 1680×1050 quadrants)
- ⚠️ Geometry occasionally fails on multi-monitor (HDMI'a düşüyor) — kullanıcı ekran kilidi hipotezi öne sürdü (TODO)
- ⚠️ Permission prompt auto-respond hâlâ manuel (RC URL'den telefonla) — xdotool keystroke landing'i intermittent

## 2026-05-17 (ilk versiyon)

### Script

- ✅ `claudeops` tek dosya bash script (~400 satır)
- ✅ Self protection: `find_self_claude_pid` via `$$` ata zinciri
- ✅ Komutlar: `self`, `list`, `kill`, `compact`, `rc`, `send`, `batch`, `desktops`, `layout`, `new`, `cleanup`, `help`
- ✅ Hedef syntax: `all`, `all-but-self`, `<name1> <name2>...`
- ✅ Compact için `< /dev/null` zorunlu (stdin leak fix'i)
- ✅ Compact başarı doğrulaması (isCompactSummary marker count)
- ✅ Rate-limit tespit + otomatik durma
- ✅ RC visible (gnome-terminal) + detached (script -qfc) mode'ları
- ✅ `--kill-first` flag mevcut session'ı kapatıp resume
- ✅ `--rename=<name>` ve `--suffix=<n>` (toplu rename: <name>13→<name>14)
- ✅ `--new` flag (yeni boş session)
- ✅ `layout` 2×2 grid, primary monitor, pinned-on-desktop-0 (`--pin=`)
- ✅ `desktops <N>` gsettings ile workspace count
- ✅ `cleanup` orphan bash pencereleri kapatır
- ✅ `compact --visible` gnome-terminal penceresinde canlı görünür

### Dokümantasyon

- ✅ `README.md` — usage + bug'lar + fix'ler
- ✅ `CLAUDE.md` — proje context (gelecek session'lar için)
- ✅ `TODO.md` — açık işler
- ✅ `TOBEDECIDED.md` — kullanıcı kararı bekleyenler
- ✅ `DONE.md` — bu dosya

### Gerçek dünya kanıtı (script doğmadan önce manuel yapıldı, sonra script'leştirildi)

- ✅ **14/14 Claude session compact** (sequential, ~25dk, sıfır kayıp; tüm backup'lar diskte)
- ✅ **13/14 RC reopen** (home13 = bu konuşma kabul edildi, skip)
- ✅ **14 görünür gnome-terminal pencere** (compact + RC + bash exec ile pencere kalıcılığı)
- ✅ Bug bulundu+fix'lendi: stdin leak'i ("/compact" sonrası TSV içeriği sızıyordu)
- ✅ Self-protection mekanizması test edildi (`pid 78492` bu konuşma, dokunulmadı)

### Snapshot

- `~/sessions-snapshot.md` — 2026-05-16 akşamı tüm session envanteri
- `~/howtos.md` — RC enable + kompakt-via-resume recipe (claudeops bu öğrenilenlerin script hali)
