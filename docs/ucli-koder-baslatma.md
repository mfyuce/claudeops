# ucli koder oturumu: elle başlatma tarifi (2026-11-02, doğrulandı)

Amaç: unified-cli reposunda ucli ile kod yazan oturum (bootstrap). Kullanılan değerler gerçek çalışan süreçten alındı.

## Panel başlat penceresi (cli = ucli)
- Hizmet: Claude (Anthropic API) | Model: claude-sonnet-5-5 | Effort: medium | İzin kipi: allow-edit
- Tur başına USD tavanı: 1 | exec zaman aşımı: 600 (EN ÇOK 600) | exec komutları: git
- exec araç zinciri: rust (cargo+rustc, tam yol; panelde henüz alan YOK, bkz. TODO "başlatma ön ayarları")
- Anahtar: Ayarlar > byok.ucli (ANTHROPIC_API_KEY). Oturum adı: cli. Çalışma dizini: ~/work/projects/tmp/unified-cli

## Koddan (panel alanı olmayan exec_toolchain için)
cd ~/work/projects/tmp/claudeops/py && python3 -c "from claudeops.commands import web; print(web._start('cli', model='claude-sonnet-5-5', permission_mode='allow-edit', effort='medium', fresh=True, cli='ucli', cli_opts={'service':'claude','max_cost_usd':1,'exec_cmds':['git'],'exec_toolchain':'rust','exec_timeout':600}))"
Sonra pencere: panelden "Terminal'den aç" ya da POST /api/term/open-window {"name":"cli"} (Python'dan başlatınca pencere KENDİLİĞİNDEN açılmaz).

## Ortaya çıkan ucli komut satırı (özet)
--root ~/work/projects/tmp/unified-cli chat --repl --endpoint https://api.anthropic.com/v1 --provider anthropic-messages --model claude-sonnet-5-5 --effort medium --allow-edit --max-steps 25 --max-context-kib 256 --max-tool-calls 64 --max-output-tokens 16000 --request-timeout-secs 600 --stream --cache-ttl 1h --max-cost-usd 1 --session cli --status-file --usage-log ~/.claude/claudeops/ucli_usage/cli.jsonl
--allow-exec --allow-exec-cmd git,<TC>/bin/cargo,<TC>/bin/rustc   (TC = ~/.rustup/toolchains/1.98.0-x86_64-unknown-linux-gnu)
--exec-env RUSTUP_HOME=~/.rustup --exec-env CARGO_HOME=~/.cargo --exec-env RUSTUP_TOOLCHAIN=1.98.0-x86_64-unknown-linux-gnu --exec-env CARGO_NET_OFFLINE=true --exec-env PATH=<TC>/bin:/usr/local/bin:/usr/bin:/bin
--exec-memory-mib 32768 --exec-max-tasks 4096 --exec-timeout-secs 600 --exec-bind-ro <TC> --exec-bind-ro ~/.cargo/registry --exec-bind-ro ~/.cargo/git

## Tuzaklar (bugün canlı yaşandı)
1. Başlattıktan sonra süreci DOĞRULA (pgrep -af 'bin/ucli --root .../unified-cli', bayraklar görünmeli). Doğrulamadan direktif GÖNDERME.
2. `steward directive <ad>` oturum ÇALIŞMIYORSA Claude açar (roster varsayılanı). `steward handover` yeni oturum da açar.
3. Çok satırlı direktif ucli'de satır satır ayrı tur olur: TEK SATIR yaz.
4. ucli kafesi yalnız izinli env kabul eder (PATH, RUSTUP_HOME, RUSTUP_TOOLCHAIN, CARGO_HOME, CARGO_TARGET_DIR, CARGO_NET_OFFLINE...); RUSTC YOK.
5. Çıplak cargo = rustup vekili, kafeste $HOME boş: tam yol + PATH başa. Koderin işe yarayan yolu: tam yol cargo + `--config build.rustc=<TC>/bin/rustc --target-dir target-cage`.
6. Kafes içi testte atla: `-- --skip a_hostile_gitignore... ` yok artık; isolation testi düzeltildi (aca10e3). Zamanlama flake: a_hostile_gitignore_with_a_very_wide_brace_does_not_stall_the_scan.
7. Kafeste .git SALT-OKUNUR, `git add <yol>` own_file kuralıyla reddedilir: commit/push ana oturumda (diff incele, testi kafes DIŞINDA koş).
8. Durdurma: `py/cops kill cli` (tam isim; pkill YASAK). Yeniden başlatma konuşmayı korur (--session cli).
9. Yedek: ~/.claude/claudeops/backups/ucli-pre-coding-20261102/ (git bundle + worktree + ikili + ayarlar).
10. Ağ: api.anthropic.com IPv6 bağlanmıyor, IPv4 ~5 sn: "bağlanamadı" turları olabilir.

## Ne değişti (2026-11-03, uipol10 turları)
1. bin/ucli eskirse haber ver: `py/claudeops/ucli_freshness.py` `bin/ucli.info` içindeki `source_git` ile unified-cli HEAD'ini karşılaştırır; `py/cops steward status` uyarı satırı basar, `GET /api/ucli/freshness` aynı bilgiyi verir (UI rozeti yok).
2. bin/ucli kırpma: bu worktree'de kırpma davranışının kaynağı doğrulanmadı; ucli ters giderse önce madde 1'deki `source_git` farkına bak, eski ikili yüzünden olabilir. (Ayrıntı ana oturumdan gelecek.)
3. Önbellek TTL'i: 5m yazma = girdi fiyatının 1,25 katı, 1h yazma = 2 katı (`review.py` ANTHROPIC_PRICES, `ucli_cost.py` write_mult). Bu tarifteki `--cache-ttl 1h` bu yüzden yazma maliyetini artırır; maliyet tavanı (`--max-cost-usd`) buna göre seçilmeli.
4. Devir (handover): `py/claudeops/handover.py` ve `commands/handover.py`; önbellek politikası `test_handover_cache_policy.py` ile sabitli. Devir betiklerinin tam içeriği worktree'de doğrulanmadı.
5. `steward start` artık "ok" dönüp oturum görünmezse `start_not_visible` hatası verir (`web_steward._start_appeared`, 6 sn).
6. Uzak başlatmada `fresh` verilmemişse yanıta büyük bağlam `--resume` uyarısı (`warning`) eklenir; host'ta token sayımı henüz yok.
7. Review export bulgunun yoluna göre doğru depoya yazar (`review.export_root`); çözülemezse yazmaz, bulgu `approved` kalır.
8. Review zaman aşımında akıştaki ham metin `# KISMI RAPOR` başlığıyla kaydedilir (yalnız UCLI modları).
9. Panel açılışında `dist/index.html` içindeki `/assets/` dosyaları eksikse log'a `dist-eksik` yazılır; `/api/status` `diag.dist` alanı verir.
10. `py/cops steward exclude-check`: RTODO.md/RTBD.md `.git/info/exclude`'da mı, git'te izli mi (yalnız rapor).
11. Snapshot test yöntemi: ben testleri koşmam; kod + `unittest.TestCase` testi yazılır, ana oturum snapshot'ta `python3 -m unittest discover -s py/tests` koşar. pytest tarzı yasak, testler geçici dizin kullanır (gerçek ~/.claude/claudeops'a dokunma).
12. Tam pakette düşüp tek başına geçen testler (watch_input, run_tunnel_script, web_review_runner) flake sayılır; kök neden: web_review_runner = Base.setUp global `_REVIEW_LOCK` assert'i (başka testin join'lenmemiş iş thread'i; setUp artık 15 sn bekler), watch_input = KANITSIZ (kod okumayla zaman penceresi bulunamadı), run_tunnel = kanıtsız, yalnız `proc.wait` payı 10→30 sn.
13. Kafes içinde commit/push yok (.git salt-okunur); commit ana oturumda.
14. Tuzak 6 (zamanlama flake) hâlâ geçerli: önce tek başına, sonra ardışık 3 kez koş.
15. Kaynak: GATE-TODO4.md ILERLEME notları (madde 1-7); madde 8 (TS test kurulumu yok) onayla yapılmadı.
