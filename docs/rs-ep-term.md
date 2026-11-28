# rs-ep-term: terminal okuma uçları (Rust dalga 2, İz B2a)

Dal `rs/state`, taban `main` `34048c58` (B1 birleşmiş). Plan: `docs/rust-wave2-plan.md` bölüm 2 (R1-R6) ve 3 (B2a); B1 kalıbı
`docs/rs-ep-state.md`. Canlıya ALINMADI (servis, `8765`/`28765`, `~/.claude`, sahibin tmux sunucusu dokunulmadı); canlıya alma
cops işi (aşağıda).

## Yapılanlar

| Madde | Kod | Test |
|---|---|---|
| `GET /api/term/output` yerel dalı (web.py `_term_output`, `_term_output_viewport`, `web_term_lite.to_lite`) | `rust/crates/cops-ep-term/src/{lib,frame,lite,mode}.rs` | `tests/real_tmux.rs` (Python'a karşı bayt bayt, gerçek tmux + gerçek süreç), `tests/pure_parity.rs` |
| `GET /api/term/history` yerel dalı (web.py `_term_history`) | `cops-ep-term/src/frame.rs` | `tests/real_tmux.rs` (aralık kırpma, 500 satır sınırı, doyan tamsayılar) |
| Ad çözümü (`_find_running_for_action`, `_term_resolve`) ve 30 sn önbellek (`_TERM_OUTPUT_RESOLVE_TTL`, `_term_resolve_for_output`) | `cops-ep-term/src/resolve.rs` | birim (sahte `Probe`: sıra, kayıtlı taban, süre, hata önbelleğe girmez) + `real_tmux.rs::gone_session_drops_the_cache_and_rescans` |
| Hata şablonları (web.py `ERR`, `_err`) | `cops-ep-term/src/err.rs` | `pure_parity.rs` (6 anahtar x 3 dil değeri, `{...}` içeren ad) |
| Mod algılama (`_detect_mode_in_text`, sağlayıcı desenleri) | `cops-ep-term/src/mode.rs` | `pure_parity.rs` (406 ekran x 8 cli; harf sınıfları tüm BMP'de Python `re.IGNORECASE` ile) |
| copsd kaydı + `--tmux-socket` (yalnız yalıtılmış deneme) | `copsd/src/{routes,lib,main}.rs`, `copsd/Cargo.toml` | `copsd/tests/b2a_routes.rs` (4), `route_force.rs` (gerçek tablo 4 rota) |
| Parite listesi | `cops-parity/requests/endpoints.json` (+6 istek, hepsi `"expect": "local"`) | `route_force::parity_list_matches_registered_routes` |
| Ek: şema sürümü (TODO "B1 bağımsız incelemesi") | `cops-state/src/{store,statedocs}.rs` | `store::tests::read_only_accepts_newer_schema_with_the_docs_contract` |

Kapsam dışı (bilerek): `/api/term/input|key|raw|resize|set-mode` (yazan uçlar), `/ws/term`, `/api/ws-ticket` bilet deposu
(B2b, sahip onayı), uzak host dalı (Python'da), `cops-proxy` kanca türü (değişmedi).

### tmux kullanımı

Yalnız okuma komutları: `has-session`, `capture-pane -e -p -S/-E` (copy-mode YOK), `list-panes -F`, `display-message -p`
(`pane_tty` ve tek süreçli anlık görüntü). Hedef hep `=ad:` (`cops_tmux::exact_target`; `$`, `:`, `#`, denetim karakterli ad
tmux'a hiç gitmez, Python `_exact` ValueError ile aynı sonuç). Bayraklar `cops-tmux`un 3.0a/3.2a ortak kümesi (`docs/rs-tmux.md`);
B2a yeni tmux komutu ya da bayrağı eklemedi, `cops-tmux` değişmedi. Maskeli giriş yoklaması `O_NOCTTY` ile (`cops_tmux::tty_is_masked`).
`real_tmux.rs::every_tmux_call_uses_the_test_socket`: Rust'ın bütün tmux çağrıları argv günlüğü tutan bir sarmalayıcıdan geçirilir;
her satır test soketi (`-L cxet...`) ve geçici `TMUX_TMPDIR` ile başlar, komut kümesi tam olarak `capture-pane`, `display-message`,
`has-session`, `list-panes`; `send-keys`/`copy-mode` ve ön ekli (`-t ad`) hedef yok.

Soket: canlıda `cops` (Python `tmux_backend.TMUX_SOCKET` ile aynı; `b2a_routes::live_socket_is_pythons` Python kaynağını okuyup
denetler), soket dizini süreç ortamındaki `TMUX_TMPDIR`. Canlı servislerde ikisinde de `TMUX_TMPDIR` yok (systemd kullanıcı ortamı,
`~/.bashrc` okundu), tmux `/usr/bin/tmux`. `--tmux-socket AD` yalnız yalıtılmış deneme içindir. Testler: her tmux çağrısı özel
soket + geçici `TMUX_TMPDIR`, `TMUX` ortamı silinir, `kill-server` yalnız kendi soketine; copsd testlerinde kayıt bağlamı da var
olmayan özel sokete ayarlanır (`b1_routes.rs`, `route_force.rs`).

## Python -> Rust eşleme tablosu

Durum: **eş** (aynı sonuç, testle), **fark** (bilinçli, gerekçeli), **Python** (Python'a devredilir).

| Python davranışı | Rust | Durum |
|---|---|---|
| `do_GET` `urlparse(path).path == "/api/term/output"` / `"/api/term/history"` | `RouteTable::get` tam yol; `;param` gibi biçimler tabloya düşmez | eş / Python |
| `name = (qs.get("name") or [""])[0].strip()`; boşsa `name_required` 400 | `cops_auth::query_param` (Python `parse_qs`: boş değer atılır) + `pycompat::strip` | eş (birim + parite) |
| `lang`: yalnız tam `"en"`; `lite`/`viewport`: yalnız tam `"1"`, İLK dolu değer | aynı | eş |
| sıra: ad denetimi, (history) `int()` denetimi, SONRA `host` | `route()` uzak `host`ta `None`: Python aynı sırayla yanıtlar | eş / Python |
| history `int((qs.get("start") or [""])[0])`, `ValueError` -> `invalid_range` 400 | `pycompat::parse_int` (Unicode rakam, `_`, `+`, boşluk; 4300 haneden uzun = `ValueError`, `INT_MAX_STR_DIGITS`, R-B2a-1) -> `i64`e doyurma | eş (`%D9%A3`, `1_0`, `+3`, 23 basamak: izole parite; 4300/4301 hane `parity_settings.rs::int_digit_limit_matches_python`) |
| sınırsız Python `int` | doyurulmuş `i64`: iki kırpma adımı aynı sonucu verir (aynı uca doyan çift ikinci denetimde `invalid_range`) | eş (`i64::MIN/MAX` çiftleri, 23 basamak) |
| `host` yerel değil -> `web_hosts.proxy_get` | `route()` `None` | Python |
| imzalı kimlik iletimi (`X-Cops-Fwd*` başlığı, enterprise `fwd`) | `route()` `None` | Python (bkz. Kimlik kararı) |
| `_term_resolve_for_output`: önbellekte ve 30 sn'den taze ise taramasız | `Resolver` (`RESOLVE_TTL` 30 sn, `production_ttl_is_pythons_30s`) | eş |
| önbellek yalnız başarılı çözümü saklar; hata dalında `pop` | aynı | eş (birim) |
| tarama tek-uçuş (`_shared_find_sessions`, R-B2a-4): çağrıdan SONRA başlamış tarama paylaşılır, patlamada en çok iki tarama | `Resolver::shared_sessions` | eş (Python `test_term_scan_coalesce.py`, Rust `concurrent_cold_resolves_share_scans`); Python'da `_find_running_for_action`ın tüm çağıranları, Rust'ta iki REST ucu |
| önbellek web.py modül sözlüğü: `/ws/term` tikleri ve iki REST ucu ORTAK | copsd'de yalnız iki REST ucunun (Python'un `/ws/term`i kendi önbelleğini kullanmaya devam eder) | fark (R3): sonuç aynı kural; ad başına 30 sn'de en çok bir ek `/proc` taraması (Rust tarafında). Python'da REST'in `pop`u WS kaydını da düşürürdü; WS kendi başarısız capture'ında zaten düşürür |
| `_find_running_for_action`: `find_sessions(measure_cpu=False)`; tam ad; yoksa `s.base == name` ve `get_instance(s.name) is None`; 2+ belirsiz | `resolve::find_for_action` + `cops_procscan::find_sessions(CpuMode::Skip)` + `session::base_name` | eş (gerçek süreçle: tam, tek taban, belirsiz, kayıtlı taban) |
| `get_instance(n) is None` (değeri `null` olan kayıt da "yok") | `!matches!(get, None \| Some(Null))` | eş (null kayıt: birim + izole parite) |
| `find_sessions` içinde agy eşlemesi öğrenilince `agy_sids.json` yazımı | yazılmaz | fark (B1 ile aynı; yalnız agy `sid`ini etkiler, ad/pid/cli değişmez) |
| `procs[0]` (aynı adlı birden çok süreç: tarama sırasındaki ilki) | ilk eleman | eş (`docs/rs-proc.md` sıra paritesine dayanır; aynı adlı iki süreç ayrıca sınanmadı) |
| `ambiguous_name` adaylar `", ".join(...)`, tarama sırası | aynı | eş |
| `is_tmux_backed(pid)`: ata zinciri (6), gerçek uid, `tmux -L <soket>` | `Tmux::is_tmux_backed` (`docs/rs-tmux.md`) | eş (tmux dışı süreç: `not_tmux_backed`) |
| `tmux_has_session` hata/istisna -> `False` | `has_session().unwrap_or(false)` | eş (`:`'lı ad: `term_session_gone`) |
| hata kodları: çözüm hataları ve `term_session_gone`, `invalid_range` (ters/kırpılmış aralık) 200 + `ok:false` | aynı | eş |
| `_err`: `{"ok", "error", "code"}`, `str.format` değeri yorumlamaz | `err::err` tek geçiş | eş (ad `ad {x} ç\x1c`, aday `a, {name}`) |
| `_term_output`: `tmux_capture(lines=2000)` (`-e -p -S -2000`); None -> `pop` + `term_session_gone` | `Tmux::capture(…, 2000)`; hata -> `forget` | eş |
| `tmux_pane_size` None -> `cols/rows/history_size/alternate_screen` `null` | aynı | eş |
| `masked: bool(pane_is_masked_input)` (`None` -> `false`) | `== Some(true)` | eş (getpass benzeri pane: `true`) |
| `mode: _detect_mode_in_text(text, get_provider(cli))` | `mode::detect`; tanınmayan cli `claude` desenleri | eş (406 ekran x 8 cli) |
| `re.IGNORECASE` (`i` ~ `İ`/`ı`, `s` ~ `ſ`), `\s` (U+001C..U+001F dahil), `splitlines`, `strip` | açık karakter sınıfları, `py_splitlines`, `pycompat::strip` | eş (BMP taraması) |
| `viewport=1`: `tmux_pane_snapshot` (tek süreç), `viewport_text`, `tty_is_masked`, `urls/paths` boş, `lite: true` | `Tmux::snapshot` + aynı alanlar | eş |
| snapshot başarısızsa sıradan yola düşülür (önbellek DÜŞMEZ) | aynı | eş |
| snapshot `fields[4].strip()` (Python boşluk kümesi) | `str::trim` (`cops-tmux`) | fark değil pratikte: pty yolu boşluk/denetim karakteri içermez |
| `lite=1`: `to_lite(result)` memo'suz: `ok` ve `rows >= 1` (bool değil) ise son `rows` satır, `urls` (3), `paths` (8, en az 2 kod noktası), sondaki noktalama kırpılır | `lite::to_lite` | eş (406 ekran x 3 `rows`) |
| `viewport_text(text, 0)` Python `[-0:]` = tüm satırlar | aynı | eş |
| `_term_history`: `end < start` -> `invalid_range`; `pane_size` None -> `pop` + `term_session_gone`; `max(start, -hist)`, `min(end, rows-1)`; yeniden ters -> `invalid_range`; `end <= start+499`; `capture_range` None -> `pop` + `term_session_gone`; sondaki tek `\n` atılır | `frame::term_history` | eş (12 aralık + 6 adda iki aralık) |
| `subprocess.run(text=True)`: UTF-8 + evrensel satır sonu; çözme hatası -> `None` | `Output::text` (aynı), hata -> `Err` | eş |
| `self._json(obj, status)`: `json.dumps` (`ensure_ascii`), `Content-Type: application/json; charset=utf-8` | `cops_ep_state::json_response` + durum | eş (bayt bayt, izole parite) |
| `psutil.process_iter` istisnası (`/proc` okunamaz): yanıt yazılmadan bağlantı kapanır | 500 `{"ok": false, "error": "internal error"}` + günlük | fark (B1 "istisna yolları") |
| `HOME` yok | uçlar KAYDEDİLMEZ (`b2a_routes::without_home_term_stays_in_python`) | Python |
| `do_HEAD` yok (501) | yalnız `GET` kayıtlı | Python |

R3 (bellek durumu) özeti: Python'un bu uçlarda dokunduğu süreç içi durum yalnız çözüm önbelleği (yukarıda, fark) ve içerik
anahtarlı desen önbelleği (`_MODE_PATTERN_CACHE`, sonuç aynı). Başka önbellek, damga, poller tetiklemesi ya da yazım yok
(web.py `_term_output`/`_term_history`/`to_lite` okundu). Uydurulan alan yok. Rust bu uçlarda durum belgesine YAZMAZ
(`real_tmux.rs`: durum ve ev dizininin anlık görüntüsü okuma öncesi/sonrası aynı).

## Kimlik kararı

- Python: `action_for("GET", "/api/term/output"|"/api/term/history")` = `term.read` (`/api/term/` öneki; yazan uçlar `term.write`);
  `resources_from`: `name` ve `host` sorgudan -> `Resource(kind="session", host=<qs host>, name=<ad>)`. Yanıt `filter_status` (K3)
  ile SÜZÜLMEZ; `extensions.match_route` yalnız `/api/enterprise/` önekini kabul eder (bu uçlara eklenti kancası yok).
- Enterprise `authorize` (salt okundu, `claudeops_enterprise/auth/service.py`): yönetici her şeye; yönetici olmayan için yerel
  `session` kaynağında oturum sahibi (`owners()`), salt okur atanmış (`viewers()`, `SESSION_VIEWER`) ya da red. Karar yalnız
  İSTEKTEKİ ada bağlı; yanıt içeriği kimliğe göre değişmez.
- Rust: `RouteTable::get` (vekil). copsd-ent `EntLocalAuth`: `on` kipinde aynı eylem tablosu (`cops_auth::authz::action_for`,
  `b2a_routes` denetler) ve aynı kaynak kuralı (`cops_proxy::resources`) ile karar verir; `shadow` kipinde Python karar verir;
  `off` kipinde ve tek kullanıcıda `Default` = yalnız `web.token`. Kanca yalnız izin verilen isteği görür ve izin verilen kişi
  Python'da da aynı baytları görürdü: sızıntı yolu yok. `own_auth` gerekmez.
- Taban adı çözümü (istenen ad `x`, cevaplanan oturum `x7`): yetki istekteki ada verildiği için `x`in sahibi kayıtsız `x7`yi
  okuyabiliyordu (Python'da da). 28 Kas düzeltildi (kapalı yön, iki tarafta): çok kullanıcıda (Python authorizer kayıtlı;
  copsd'de `Hooks.local_auth` takılı, `RouteCtx.multi_user`) `_find_running_for_action` / `Resolver::exact_only` yalnız TAM
  adı çözer; taban ad ve belirsizlik `not_running` (aday adı sızmaz). Tek kullanıcıda davranış aynı. Python bu kuralı TÜM
  tekil hedefli uçlara uygular (dosya, terminal yazma, kapatma); copsd yalnız iki okuma ucunu taşır. Testler
  `py/tests/test_base_name_authz.py`, `resolve.rs` `exact_only_resolver_never_falls_back_to_base`, copsd
  `state_ctx.rs` `term_resolver_is_exact_only_in_multi_user`.
- K9 denetim: Python'da yalnız authorizer kayıtlıyken (`_gate` -> `authz.check` -> denetim kancaları). Rust `on` kipinde
  `gate_audit` aynı kararı denetime yazar; `shadow` kipinde karar (ve denetim) Python'da; `off`/tek kullanıcıda iki tarafta da
  denetim yok. Fark yok.
- Kimlik iletimi (`fwd`): imzalı istek (`X-Cops-Fwd*` başlığı) her kipte Python'a gider (`route()` `None`;
  `b2a_routes::local_pane_in_rust_remote_and_signed_in_python`). Gerekçe: `off` kipinde Rust imzayı görmeden `web.token`la tam yetki
  verir, Python ise imzalı isteği iletilen (daha dar) kimliğe indirir.
- AÇIK NOKTA (cops/sahip; B1'den beri var, B2a'da da geçerli): `ent_fwd_mode=require` iken Python imzasız (yalnız host
  token'lı) isteği durum uçları dışında reddeder (401). copsd-ent `ent_auth_rust=off` iken yerel Rust uçları `Default` ->
  `web.token`la kabul eder: bu kipte terminal okuması imzasız token'la Rust'tan alınabilir. `on`/`shadow` kipinde karar Python'a
  sorulduğu için sorun yok. Öneri: (a) copsd-ent `Off` + `!fwd_off()` iken de Python'a sorsun (enterprise değişikliği), ya da
  (b) `ent_fwd_mode` açık bir host'ta `/api/term/` (ve B1 önekleri) `front_force_proxy`de kalsın. Canlıda `ent_fwd_mode` uzak
  host'larda (yuhem, ulak_31) önemlidir; yerel canlıda değeri okunmadı (doğrulanmadı).
- Çok kullanıcı kipi AÇIK ve `ent_auth_rust=off` iken çerezli kullanıcılar bu uçlarda Rust'tan 401 alır (Python 200 verirdi):
  kapalı yön, veri sızmaz; B1'deki notla aynı. Çok kullanıcı açılmadan önce ya `ent_auth_rust=on` ya da `/api/term/` önekinin
  `front_force_proxy`de kalması gerekir. Canlıda `ent_multi_user` kapalı.

## TICK ölçümü

Yöntem (hafıza `remote-panel-cpu-measurement-method`): `/proc/<pid>/stat` `utime+stime` (sürecin kendisi) ve `cutime+cstime`
(toplanmış çocuklar: her istekte açılan tmux istemci süreçleri) farkı, 60 sn pencere, çekirdek yüzdesi; tmux SUNUCUSU ayrıca.
Önce taban, sonra yük, sonda yeniden taban. Ortam YALITILMIŞ: `unshare -rn` (yalnız loopback, dış ağ yok), geçici
`CLAUDEOPS_DIR`/`HOME`, özel tmux soketi (`tmux -L b2a<pid>x<rastgele>`, geçici `TMUX_TMPDIR`, `-f /dev/null`), rastgele loopback
port; Python paneli worktree `py/`den (periyodik işler kapalı, `tmux_backend.TMUX_SOCKET` özel sokete yamalı), copsd release
`--tmux-socket` ile. Yük: 10 sahte claude oturumu (120x40 pane, 600 satır durağan renkli metin + mod satırı),
`poll.py` oturum başına 1 istek/sn (10 istek/sn), her istekten önce ısınma (önbellek dolu). Betikler scratch'te
(`term/tick.sh`, `env.sh`, `poll.py`, `cpu.py`, `fake_cli.py`, `launch.py`); yalnız başlatılan PID'ler ve kendi tmux sunucusu
kapatıldı. Makine 8 çekirdek, ölçüm boyunca yük ortalaması 3-10 (başka oturumlar): tek koşu, sayılar gürültülü; ±%2-3 puanı
fark saymayın.

Python (istek doğrudan Python portuna; 27 Kas 23:28-23:35):

| Yük (10 x 1 istek/sn) | Python kendi | Python çocuk (tmux istemcileri) | Toplam | tmux sunucusu | ort. gecikme |
|---|---|---|---|---|---|
| taban (yük yok) | %0,5 | %1,6 | %2,1 | %0,0 | |
| `lite=1` | %16,3 | %7,5 | %23,8 | %7,7 | 169 ms |
| `lite=1&viewport=1` | %7,6 | %3,1 | %10,7 | %1,2 | 93 ms |
| tam kare (`lite`siz) | %11,2 | %9,0 | %20,2 | %9,8 | 192 ms |
| `history` 120 satır | %7,8 | %6,1 | %13,9 | %3,0 | 80 ms |
| taban (sonra) | %0,6 | %0,8 | %1,4 | %0,0 | |

Rust (istek copsd'ye, `x-cops-served: local` 650/650; 23:35-23:41; Python paneli aynı anda boşta):

| Yük (10 x 1 istek/sn) | copsd kendi | copsd çocuk | Toplam | tmux sunucusu | Python (boşta) | ort. gecikme |
|---|---|---|---|---|---|---|
| taban | %0,0 | %0,0 | %0,0 | %0,0 | %0,7 | |
| `lite=1` | %3,6 | %6,1 | %9,7 | %6,8 | %0,5 | 65 ms |
| `lite=1&viewport=1` | %1,9 | %1,5 | %3,4 | %0,7 | %0,5 | 5,4 ms |
| tam kare | %4,4 | %6,0 | %10,4 | %6,5 | %0,4 | 70 ms |
| `history` 120 satır | %2,2 | %3,5 | %5,7 | %1,6 | %0,7 | 13,7 ms |
| taban (sonra) | %0,0 | %0,0 | %0,0 | %0,0 | %0,3 | |

Okuma: istek başına iş aynı (3 tmux istemcisi + capture; `viewport` 1 istemci); çocuk (tmux istemcisi) maliyeti iki tarafta benzer
(%6 civarı tam kare/lite), fark sürecin kendi işinde: Python `lite` %16,3 -> Rust %3,6, tam kare %11,2 -> %4,4, `viewport`
%7,6 -> %1,9, `history` %7,8 -> %2,2. Gecikme Python'da GIL ve yükle büyüyor (169/93 ms), Rust'ta tmux süreç süresine iniyor
(`viewport` 5 ms). tmux SUNUCUSU tarafı istek türüne bağlı ve iki tarafta aynı büyüklükte (tam capture `-S -2000`). 30 sn
çözüm önbelleği iki tarafta da açık (10 oturum için 3 sn'de bir tam `/proc` taraması); pencere 60 sn olduğu için her oturum
pencerede ~2 kez yeniden çözüldü (iki tarafta eşit).

Bu ölçüm REST uçlarınındır; panelin terminal görünümü `/ws/term` (Python, B2b) kullanır, REST yolu `cops watch` mirror'ının
yedeği (`lite=1`, canlıyken 1/sn), geçmiş kaydırma (`history`) ve tam kare çekişidir. Canlıdaki gerçek kazanç bu uçların
kullanım sıklığına bağlıdır; canlı ölçülmedi.

## Kabul koşuları

Kapı betiği `~/.claude/claudeops/backups/gates/rsstate/gate-b2a.sh` (B1 `gate.sh` kopyası; günlükler aynı dizinde `b2a-*`;
`CARGO_TARGET_DIR=~/.cargo-target/rs-state`, repoda `target/` yok). Not: B1 `gate.sh` ve günlükleri `~/.cargo-target/rs-state`
silinince kayboldu; kapı yolu sahip/cops kararıyla yeni dizine taşındı. Sonuçlar (28 Kas, tek tam koşu):

- `cargo test --workspace --no-fail-fast`: 1104 geçti, 0 kaldı, 1 yok sayıldı.
- `cargo test -p copsd --no-fail-fast`: 33 geçti, 1 kaldı: `state_dir::taken_port_is_reported_with_the_reason` ("dolu portta
  açıldı sayıldı"). Aynı test aynı kapının workspace koşusunda geçti; tek başına 3 ardışık koşuda 4/4 geçti. B2a koduna dokunmayan
  port/zamanlama testi (makine yük ortalaması 3-10); OYNAK olarak işaretlendi, kök nedeni araştırılmadı. `b2a_routes` 4/4,
  `route_force` 6/6 (gerçek tabloda 4 rota force_proxy ile Python'a gidiyor, parite listesi eşleşiyor), `b1_routes` 3/3.
- `cargo clippy --workspace --all-targets -- -D warnings`: temiz. `cargo fmt --all --check`: temiz.
- Eşlemeler `--check`: steward `map.py` (EKSİK 0), procscan `mapping.py` (2232 satır, EKSİK 0, hata 0), hosts `mapping.py`
  (1311 satır, AÇIK 0, hata 0) temiz. review `map_table.py`: KIRMIZI, "eşleme tablosu bayat". Yeniden üretilen tablodaki tek
  fark `load_history` satırına eklenen "okuma sırasında başka iş parçacığı yazdı (dosya karşılaştırılmadı): 1" parçası; betik
  bu yarış parçasını karşılaştırmadan siler ama önündeki "; " ayıracını silmez (`map_table.py` `race` deseni yalnız SONRAKİ
  ayıracı yutar). B2a ile ilgisiz oynak denetim; `docs/rs-rev.md` değiştirilmedi. Yeniden koşu (`cops-review-core --test parity` + `map_table.py --check`, günlük `b2a-map-rev-2.log`): temiz (rc 0).
- `cargo tree -e features -i serde_json -p copsd`: `preserve_order` 0 satır (R1).
- `cargo build --release -p copsd`: başarılı, 9 045 112 bayt.
- Birim/entegrasyon (`cops-ep-term`): 15 birim, `real_tmux` 3 (84 istek Python'a karşı bayt bayt; argv günlüğü; önbellek düşüşü),
  `pure_parity` 2 (406 ekran; BMP sınıfları). Mutasyonla kırmızı gösterildi: `i` sınıfından `ı`, `\s` sınıfından U+001C..1F ve
  URL deseninden U+001C..1F çıkarılınca iki parite testi de kırmızı (geri alındı).

İzole parite koşusu (canlıya dokunmadan; `unshare -rn`, geçici `CLAUDEOPS_DIR`/`HOME`, özel tmux soketi + geçici `TMUX_TMPDIR`,
worktree Python paneli + release copsd `--tmux-socket`; betikler scratch `term/parity.sh`, `term/bytecmp.py`, `term/fake2.py`).
Fikstür: 11 tmux oturumu (tam ad, tek taban, belirsiz taban, kayıtlı taban, maskeli, alternatif ekran, copilot, ucli, Türkçe ad,
başka adlı tmux oturumundaki süreç) + tmux dışı süreç; hepsi durağan içerik.

| Kip | `term-requests.json` (178 istek) | `endpoints.json` (11) | Bayt karşılaştırması (durum + Content-Type + gövde) | Ek |
|---|---|---|---|---|
| files | geçti 178, fark 0, hata 0, hepsi `local` | geçti 11 | 178 istek, fark 0 | `host=yuhem` ve `X-Cops-Fwd-Sig` -> `python` |
| db | geçti 178, fark 0, hata 0, hepsi `local` | geçti 11 | 178 istek, fark 0 | aynı |

Sonuç dağılımı (her kipte): 200 `ok` 71, `not_running` 24, `ambiguous_name` 17, `not_tmux_backed` 17, `term_session_gone` 17,
`invalid_range` 11; 400 `invalid_range` 18, `name_required` 3.

## Ek: şema sürümü düzeltmesi (TODO "B1 bağımsız incelemesi")

Sorun: `Store::open_read_only` şema sürümünde TAM eşleşme istiyordu. Python yeni göç ekleyip canlı DB'yi `v3`e taşıyınca güncellenmemiş
copsd'nin her okuması `Schema` hatasıyla dosya aynasına düşüyordu (`statedocs` her okumada `read X: DB sürümü 3 ... -> dosya`
satırı yazıyordu: sessiz değildi ama her istekte tekrar eden, gürültülü bir düşüş).

Karar: salt OKUMA açılışı daha yeni sürümü kabul eder, YAZMA açılışı tam eşleşmede kalır.

- Neden `>=` (okuma için): `store.py` sözleşmesi göçlerin yalnız SONA eklendiğini, var olan öğenin değiştirilmediğini söyler; yeni bir
  göç eski okuma sorgularını bozmaz. Yine de Rust'ın okuduğu `docs(name, body, version, updated)` sütunları açılışta hazırlanarak
  sınanır (`READ_CONTRACT`); yoksa `Schema` hatası ve dosyaya düşüş (eskisi gibi). Daha ESKİ sürüm reddedilir.
- Riskler tartıldı: db kipinde dosya aynasına düşmek, ayna yazımı başarısızken BAYAT değer okumak ve elle düzenlenen aynayı (Python
  okumaz) okumak demektir; Python ile ayrışma kaynağıdır. Bilinmeyen (yeni) şemayı okumanın riski, sözleşmeyi bozan bir göçün
  (sütun anlamı değişimi) yanlış okunmasıdır; bu durumda gövde JSON değilse `BadDoc` -> dosya, sütun yoksa `Schema` -> dosya.
  Kalan risk (aynı sütunda anlamı değişen veri) yalnız sözleşme ihlaliyle olur. Yazma tarafında bilinmeyen şemaya yazmak çok daha
  zararlı olduğu için tam eşleşme korunur.
- Parite: `cops-state/tests/parity.rs` zaten `SCHEMA_VERSION == len(store.MIGRATIONS)` denetler (Python göç ekleyince kırmızı,
  ikili güncellenmeden birleştirilemez). Çalışma anında daha yeni şema görülürse süreç başına sürüm başına BİR kez günlüğe
  yazılır (`StateDocs::read_only_store`).
- Test: `store::tests::read_only_accepts_newer_schema_with_the_docs_contract` (daha yeni: okunur ve `schema()` döner; yazma açılışı
  reddeder; eski: red; sütunu eksik yeni: red; aynı: kabul).

## Canlıya alma ve geri dönüş (cops yapacak)

1. Önce öneki Python'a sabitle: `~/.claude/claudeops/front_force_proxy` dosyasına `/api/term/` satırı ekle, `kill -HUP <copsd pid>`
   (restart yok). Önek yazan uçları ETKİLEMEZ: `front_force_proxy` yalnız Rust tablosunda kayıtlı yolları Python'a geri verir;
   `/api/term/` altında tabloda yalnız iki GET okuma ucu var (`b2a_routes::b2a_routes_registered_read_only_with_python_action`),
   yazan uçlar (`input|key|raw|resize|set-mode|open-window|mirror-window`) ve `/api/term/chat` tabloda değil, zaten Python'a gider.
   `/ws/term` `/api/term/` altında değildir.
2. `main`e birleştir, `cargo build --release -p copsd` (ÖZELLİKSİZ; kökten `cargo build --release` DEĞİL, R1), `bin/copsd` ->
   `copsd.prev`, yenisini koy, YALNIZ `claudeops-front.service` restart. Günlükte `copsd: yerel uç açık: GET /api/term/output` ve
   `GET /api/term/history` satırları; `copsd: tmux soketi:` satırı OLMAMALI (canlı `--tmux-socket` almaz).
3. Önek duruyorken canlı çifte parite: `cops-parity rust/crates/cops-parity/requests/endpoints.json` (8765 dış, 28765 iç); önekli
   koşuda Rust tarafı da Python'a gider.
4. Öneki sil + `kill -HUP`; parite yeniden: 0 fark ve `served local` (B2a'nın 6 isteği olmayan oturum adıyla: canlı pane'e
   dokunmaz). Gerçek bir pane için ek elle denetim: sessiz bir oturumda `viewport=1&lite=1` iki porttan art arda (pane zamanla
   değiştiği için yalnız durağan pane'de bayt eşitliği beklenir). `/api/front/stats` `local` sayacı artmalı.
5. 24 saat `route_hook_failed` ve `copsd: /api/term/` hata satırı yok; panelde terminal açılır, geçmiş kaydırılır, `cops watch`
   mirror'ı (REST yedeği `lite=1`) çalışır.
- Geri dönüş (uç bazında): `/api/term/` önekini `front_force_proxy`ye geri yaz + `kill -HUP`. Tam geri dönüş: `copsd.prev` + front
  restart.
- copsd-ent: çekirdek rev iki `Cargo.toml`da birlikte yükselir; `run_auth_on.py` e2e bu uçlarda 401/403 kuralını korumalı
  (koşulmadı). Yukarıdaki `fwd` açık noktası karara bağlanmadan `ent_fwd_mode != off` olan bir host'ta önek KALMALI.

## Doğrulanmayanlar

- Canlı çift paritesi, `/api/front/stats` sayaçları, 24 saatlik günlük, canlı TICK (canlıya dokunulmadı; ölçüm yalnız yalıtılmış).
- tmux 3.0a (yuhem): yerelde yalnız 3.2a var. B2a yeni tmux komutu/bayrağı eklemedi; kullanılanlar `cops-tmux`un iki sürümde
  ortak sayılan kümesi (`docs/rs-tmux.md`), 3.0a'da gerçek koşu yapılmadı. B2a yalnız YEREL pane'i cevaplar; yuhem'in kendi
  copsd'si bu sürümle canlıya alınırsa 3.0a orada sınanmalı.
- copsd-ent derlemesi ve `run_auth_on.py`/`run_auth_shadow.py` e2e (enterprise yalnız okundu). `RouteCtx`a alan eklendi (`tmux`);
  copsd-ent `RouteCtx`i kurmuyor, `register` imzası değişmedi.
- `ent_fwd_mode` + `ent_auth_rust=off` açık noktası (Kimlik kararı): kodla gösterildi, e2e ile sınanmadı.
- Aynı adlı iki canlı süreçte `procs[0]` seçimi: `cops-procscan` sıra paritesine dayanır, B2a'da ayrıca sınanmadı.
- Başsız tarayıcıda terminal görünümü ve `cops watch` mirror'ı (gövde Python'la bayt bayt aynı; arayüz değişikliği beklenmez).
- İkili boyutu: release `copsd` 9 045 128 bayt (B1 belgesi 6 495 608; +2 549 520, +%39). Hangi bağımlılığın büyüttüğü (`cops-tmux`
  + `regex` Unicode tabloları + `cops-ep-term` olası) ayrıştırılmadı. RSS ölçülmedi.
- Ölçüm sırasında (27 Kas 23:35:54) `~/.cargo-target` altındaki `rs-*` hedef dizinleri (B1 kapı günlükleri dahil) bu işin
  dışında silindi; ölçümdeki copsd silinmeden önce başlamıştı, sonuçlar etkilenmedi; ikili ve kapı yeniden üretildi.
