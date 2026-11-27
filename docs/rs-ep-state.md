# rs-ep-state: salt okuma durum uçları (Rust dalga 2, İz B1)

Dal `rs/state`, taban `main` `b767d777` (B0 birleşmiş). Plan: `docs/rust-wave2-plan.md` bölüm 2 (R1-R6) ve 3 (B1), B0 belgesi
`docs/rs-b0.md`. Canlıya ALINMADI (servis, `8765`/`28765`, `~/.claude` dokunulmadı); canlıya alma cops işi (aşağıda).

## Yapılanlar

| Madde | Kod | Test |
|---|---|---|
| `GET /api/instances` yerel dalı (web.py `_instances_list` + değnekçi rozeti) | `rust/crates/cops-ep-state/src/{instances,badge,lib}.rs` | `cops-ep-state/tests/parity.rs` (Python'a karşı bayt bayt, üç kip), `tests/live.rs` (sahte `/proc`, vekil uçtan uca) |
| `GET /api/diag/log` (web.py `{"lines": diag_log_tail(30)}`) | `cops-ep-state/src/diag.rs` | `parity.rs::diag_tail_parity` (pencere sınırı, bozuk UTF-8, satır ayıraçları) |
| Python `json.dumps(obj)` gövdesi (`ensure_ascii=True`, sıra korunur, `preserve_order` YOK) | `cops-ep-state/src/pyjson.rs` | birim + parite testleri |
| `cops-state` SALT OKUMA kipi | `cops-state/src/statedocs.rs` (`StateDocs::into_read_only`), `instances.rs`, `roster.rs` | `cops-state/tests/read_only.rs` (5 karşılaştırmalı test) |
| Yan dosya yaratmayan salt okunur SQLite açılışı | `cops-state/src/store.rs` (`Store::open_read_only`, `wal_open_mode`) | `store::tests` (3 test, biri SQLite'ın eski davranışını kanıtlar) |
| copsd kaydı | `copsd/src/routes.rs` (`RouteCtx.state`, `register`), `copsd/Cargo.toml` | `copsd/tests/b1_routes.rs` (3), `route_force.rs` (gerçek tablo 2 rota, force_proxy ile Python'a) |
| Parite listesi | `cops-parity/requests/endpoints.json` (5 istek, hepsi `"expect": "local"`) | `route_force::parity_list_matches_registered_routes` |

### cops-state salt okuma kipi

`StateDocs::new(dir).into_read_only()` (ya da `isolated(..).into_read_only()`): okuma KARARI Python `statedocs.read_json` ile
aynı kalır, yan etkiler kalkar:
- `db` kipte DB'de olmayan belge dosyadan okunur ama İÇE AKTARILMAZ; `dual` kipte dosya DB'den farklıysa DB UYDURULMAZ
  (`drift`/`import`); kirli kurtarma (`recover`) yok.
- DB her kullanımda yeni salt okunur bağlantıyla açılır (`store()` de bu kipte salt okunur bağlantı döner, önbellek yok).
- `write` -> `WriteError::ReadOnly` (yeni varyant); `mirror_log` false; `shadow_tsv` hiçbir şey yapmaz; `diag_log` dosyaya
  YAZMAZ (günlükçü ya da stderr); `Instances` bozuk ayna yedeği (`.corrupt-<sha8>`) yazmaz, `mutate` kilit dosyası AÇMADAN
  reddeder; `Roster::lock` reddeder.
- Kanıt (`cops-state/tests/read_only.rs`): her test aynı durumu önce salt okumayla okur (geçici kökün yol + içerik + izin
  anlık görüntüsü değişmez), sonra ham `StateDocs` ile okur ve ham yolun YAZDIĞINI gösterir (db içe aktarma, dual drift +
  `diag.log`, bozuk ayna yedeği + `diag.log`, `tsv_rows`/`log` akışı/`instances.json.lock`, DB hata dalı günlüğü). Ham yol
  yazmayı bırakırsa ya da salt okuma yazarsa test kırmızı.

### Bulgu: SQLite'ın salt okunur açılışı dosya yaratır

`SQLITE_OPEN_READ_ONLY` ile WAL kipindeki bir DB açılırsa ve DB'yi açık tutan süreç yoksa (`-wal`/`-shm` yok), SQLite
`-shm` ve `-wal` dosyalarını YARATIR (unix VFS `-shm`i `O_CREAT` ile açar; Python `sqlite3` 3.37.2 ve rusqlite paketli sürümüyle
ölçüldü). B0'ın `ReadDocs` yolu ve B0 testleri bu yüzden WAL kipini bilerek kullanmıyordu (`state_ctx.rs::make_db` yorumu).
`Store::open_read_only` artık DB başlığına (bayt 18/19) ve yan dosyalara bakar:

| Durum | Açılış |
|---|---|
| WAL değil, ya da `-wal` ve `-shm` ikisi de var (açık bir yazar var; canlıda hep böyle) | olağan `file:...?mode=ro` |
| WAL, ikisi de yok (tüm veri ana dosyada) | `file:...?mode=ro&immutable=1` (kilit ve yan dosya yok) |
| Yalnız biri var (çökme artığı, kurtarma yazım ister) | `StoreError::Io`, çağıran dosyaya düşer |

`immutable` dalının riski: okuma sırasında başka bir süreç DB'yi açıp kontrol noktası yazarsa yırtık okuma (SQLite hatası ->
dosyaya düşülür). Pencere, DB'yi açık tutan süreç yokken gelen ilk yazarın kontrol noktasına kadar; canlıda Python ve copsd
(`rootrel_learned`) DB'yi açık tuttuğu için bu dala girilmez. Değişiklik B0 `ReadDocs::read`ini de kapsar (aynı işlev).

## Python -> Rust eşleme tablosu

Durum: **eş** (aynı sonuç, testle), **fark** (bilinçli, gerekçeli), **Python** (Python'a devredilir).

| Python davranışı | Rust | Durum |
|---|---|---|
| `do_GET` yol `urlparse(self.path).path == "/api/instances"` | `RouteTable::get("/api/instances")` tam yol; `;param`/`#` gibi biçimler tabloya düşmez | eş / Python |
| `_host_from_qs`: `(parse_qs(q).get("host") or ["local"])[0].strip() or "local"` | `local_host`: `cops_auth::query_param` (aynı `parse_qs`: boş değer atılır, ad/değer çözülür) + `pycompat::strip` (U+001C-1F dahil) | eş (11 vektör Python'la) |
| `host` yerel değil -> `web_hosts.proxy_get` + `host` alanı yeniden yazımı | `route()` `None` | Python |
| `lang` (yalnız uzak dal) | okunmaz | eş |
| Kimlik/yetki (`_authorized` / `_principal` + `_gate`: `fleet.admin`, `admin.config`, kaynak `global`) | `RouteTable::get`: `LocalAuth` (copsd-ent, aynı eylem tablosu) ya da `web.token` | eş (bkz. Kimlik kararı) |
| `find_sessions(measure_cpu=False)` adları | `cops_procscan::find_sessions(cfg, CpuMode::Skip)` adları (`docs/rs-proc.md` paritesi) | eş (sahte `/proc` testi; izole koşuda gerçek süreç) |
| `find_sessions` içinde agy eşlemesi öğrenilince `agy_sids.json` yazımı | `Scan::agy_learned` atılır, yazılmaz | fark: yalnız `sid`i etkiler, `name`/`running` değişmez; Python `/api/status` turları öğrenmeye devam eder |
| `psutil.process_iter` istisnası (`/proc` okunamaz) | `ScanDiag::proc_root_error` -> 500 | fark (aşağıda "istisna yolları") |
| `HOME` yok: Python `expanduser` parola veritabanı | `RouteCtx.env.home` yok/boş -> `route()` `None` | Python |
| `inst_mod.view_instances()` (`_shared`: db kipinde `read_strict`, diğerlerinde dosya anahtarlı önbellek) | `cops_state::instances::Instances::load` (salt okuma `StateDocs`) | eş |
| `read_strict`: dosya yok -> boş şekil + `read_json`; `ValueError`/`OSError` -> `db_truth`; şekil bozuk -> `{}` | `Instances::read_checked` (aynı dallar) | eş (bozuk/yok/`[]` testleri) |
| `read_strict` bozuk aynada `.corrupt-<sha8>` yedeği + `diag_log` | salt okumada yazılmaz | fark (R2) |
| `statedocs.read_json` `db`: DB'de yoksa dosyadan içe aktarma; `dual`: drift uydurma | salt okumada aynı değer, yazım yok | fark (R2), değer eş |
| `statedocs._DIRTY` (süreç içi: son DB yazımı başarısız, dosya daha yeni) | görünmez (R3) | fark: B0 madde (b) ile aynı; Python'un DB yazımı kalıcı bozuksa Rust DB'deki eski değeri görür |
| `rec.get("forgotten")` doğruluk değeri | `Json::truthy` | eş |
| `dict(rec, name=, running=, host="local")` (var olan anahtar yerinde güncellenir, yoksa sona) | `IndexMap::insert` | eş (kayıt içi `name`/`host`/`running` testi) |
| `sort(key=last_started_at or created_at or 0, reverse=True)` kararlı | `sort_by` (kararlı) ters karşılaştırma; `int`/`float`/büyük tam sayı TAM karşılaştırma | eş (eşitlikler, `300` ile `300.0`, büyük tam sayı testi) |
| sıralamada NaN (Python'da sırasız, sonuç algoritmaya bağlı) | NaN en küçük sayılır (toplam sıra; Rust sıralaması toplam olmayan sırada paniğe düşebilir) | fark (Python NaN yazmaz) |
| sıralamada `str` ile sayı karışımı, iki sözlük | `ListError::SortType` -> 500 | fark (istisna yolu) |
| sıralamada iki liste (Python eleman eleman karşılaştırır) | `SortType` -> 500 | fark (zaman damgası liste değil) |
| sözlük olmayan kayıt (`AttributeError`) | `ListError::NotDict` -> 500 | fark (istisna yolu) |
| `steward.ownership_index()` | `badge::owners` | eş (aşağıdaki satırlar) |
| `discover_steward_ids`: `default` + `steward/stewards/<[a-z]+>/` dizinleri | `discover_ids` | eş |
| `reviewer_ids`: `load_settings()["stewards"]`, `role` kırpılmış `reviewer`, `valid_custom_id` | `cops_state::settings::load` + aynı süzgeç | eş |
| `_project_meta`: `os.stat` yoksa ad yok; `_load_json`; nesne değerli `valid_name` anahtarlar, sıralı | `project_names` | eş (`db` kipinde ayna yokken DB adı sayılmaz testi) |
| `_project_meta` `(mtime_ns, size)` önbelleği (`db` kipinde içerik DB'den, anahtar dosyadan) | önbellek yok, her istekte okunur | fark (R3): ayna yazımı başarısızken Python bayat ad görebilir, Rust güncel |
| `_load_json` `files` kipinde: `json.load` hatası `{}`, ama UTF-8 olmayan dosya `UnicodeDecodeError` (yakalanmaz) -> `_instances_list` rozetsiz | `load_json` -> `IndexFailed` -> hiç rozet yok | eş (testli; `services.json` için de) |
| `_load_json` `files` dışı kip (`_db_ok`): `read_json` (bozuk = `{}`) | `docs.read` (salt okuma) | eş (dual'de aynı bayt rozetli: testli) |
| `_load_json` bozuk dosyada `_corrupt_backup` yedeği | yazılmaz | fark (R2) |
| `build_ownership_index` `owners` (tek kimlikte görünen ad), `brains` (`brain_name_for`) | `owners`; `brains` önek kuralına eşdeğer olduğu için ayrıca kurulmaz | eş |
| `steward_badge`: beyin (`degnekci`, `degnekci_<sid>`, boş sid değil), proje (`_project_key` en uzun `derived_of`) | `badge::badge` | eş |
| `DERIVED_TAIL_RE` (`\d` Unicode ondalık) | `derived_tail` (`pycompat::is_re_digit`) | eş (birim) |
| `valid_name` (`^[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*$`, <= 48) | `valid_name` | eş |
| rozet hatası yutulur, satırlar rozetsiz | aynı | eş |
| `self._json(obj)`: `json.dumps` (`ensure_ascii=True`), 200, `Content-Type: application/json; charset=utf-8` | `pyjson::dumps` + `json_response` | eş (bayt bayt) |
| eşlenmemiş vekil kaçışı (`"\ud800"`) içeren kayıt: Python aynen geri yazar | `Json::parse_lossy` U+FFFD okur, `�` yazar | fark (yalnız bozuk elle düzenleme) |
| `/api/diag/log`: `diag_log_path()` (`CLAUDEOPS_DIAG_LOG` ya da `<durum>/diag.log`) | `diag_log_path` (copsd açılışında ortam okunur) | eş (ortam değişkeni yalnız testlerde) |
| `diag_log_tail`: son 512 KiB, UTF-8 `replace`, `splitlines`, pencere ortadaysa ilk satır atılır, son 30, `strip`, boşlar atılır, her hata `[]` | `diag::diag_log_tail` (`from_utf8_lossy`, Python ayıraç kümesi) | eş (bayt bayt; pencere çok baytlı karakterin ortasında testi) |
| `diag.log` FIFO ise `open` sonsuza dek bekler | `spawn_blocking` da bekler, kanca 60 sn sonra 503 | fark (yalnız bozuk kurulum) |
| `do_HEAD` yok (501) | yalnız `GET` kayıtlı, `HEAD` Python'a | Python |

İstisna yolları: Python bu durumlarda istisna verir, `ThreadingHTTPServer` yanıt yazmadan bağlantıyı kapatır; copsd arkasında
istemci `502 upstream: ...` görür. Rust `500 {"ok": false, "error": "internal error"}` döner ve stderr'e (servis günlüğü)
nedeni yazar. Hepsi bozuk veri (sözlük olmayan kayıt, dize zaman damgası) ya da okunamayan `/proc`.

Bellek durumu (R3) özeti: `running` ve kayıtlar tamamen dosya/DB/`/proc`ten gelir; Python'un süreç içi tek etkileri
`_DIRTY` (fark, yukarıda) ve önbellekler (`_OWN_CACHE`, `_cache`, `_db_cache`, ayar önbelleği: hepsi içerik anahtarlı, sonuç
aynı). Uydurulan alan yok.

## Kimlik kararı

- Python: `action_for("GET", "/api/instances")` = `fleet.admin` (`/api/instances/` önekinin `rstrip` eşleşmesi),
  `/api/diag/log` = `admin.config`; `resources_from` ad yok -> `Resource(kind="global", host=<qs host>)`. web.py yanıtı
  `filter_status` (K3) ile SÜZMEZ; `extensions.match_route` yalnız `/api/enterprise/` önekini kabul eder.
- Enterprise (`claudeops-enterprise/claudeops_enterprise/auth/service.py` `authorize`, salt okundu): yönetici her şeye
  izinli; yönetici olmayan için `SELF_OK` dışındaki eylemde `res.kind != "session"` -> RED. Yani iki uç da çok kullanıcı
  kipinde YALNIZ yöneticiye açık; kullanıcıya göre süzülen veri yok.
- Rust: `cops_auth::authz::action_for` aynı eylemleri verir (`copsd/tests/b1_routes.rs` denetler). copsd-ent `EntLocalAuth`
  `on` kipinde aynı tabloyla karar verir; `off` kipinde ve tek kullanıcıda `LocalVerdict::Default` -> yalnız `web.token`.
- Karar: `RouteTable::get` (vekil kimliği) yeterli; `own_auth` gerekmez. Sızıntı yolu yok: kanca yalnız vekilin izin verdiği
  isteği görür ve izin verilen herkes (yönetici / `web.token`) Python'da da aynı veriyi görürdü.
- Açık nokta (cops/sahip): çok kullanıcı kipi AÇIK ve `ent_auth_rust=off` iken (`Default`), çerezle giriş yapmış YÖNETİCİ
  bu uçlarda Rust'tan 401 alır (Python 200 verirdi). Kapalı yöne düşer, veri sızmaz; aynı durum B0 öncesinden beri
  `/api/steward/questions` yerel ucunda da var (`docs/rs-b0.md`: "Çok kullanıcı kipinde yalnız admin token'ı"). Canlıda
  `ent_multi_user` kapalı. Çok kullanıcı açılmadan önce ya `ent_auth_rust=on` ya da bu öneklerin `front_force_proxy`de
  kalması gerekir.

## Kabul koşuları

Kapı betiği `~/.cargo-target/rs-state/gate-logs/gate.sh` (`CARGO_TARGET_DIR=~/.cargo-target/rs-state`, günlükler aynı dizinde
`b1-*`; repoda `target/` yok). Sonuçlar:

- `cargo test --workspace --no-fail-fast`: 1079 geçti, 0 kaldı, 1 yok sayıldı (tek koşu; oynak test görülmedi).
- `cargo test -p copsd --no-fail-fast` (özelliksiz, canlı yapılandırma): 30 geçti, 0 kaldı (`b1_routes` 3, `route_force` 6:
  gerçek tabloda 2 rota force_proxy ile Python'a gidiyor, parite listesi eşleşiyor).
- `cargo clippy --workspace --all-targets -- -D warnings`: temiz.
- `cargo fmt --all --check`: kapı koşusunda 1 fark (`store.rs` bir `match` kolunun sarılması); `cargo fmt --all` ile
  düzeltildi, yeniden `--check` temiz, `cops-state` `store` testleri yeniden geçti (5/5). Tam kapı fmt sonrası yeniden koşulmadı
  (değişiklik yalnız biçim).
- Eşlemeler `--check`: steward `map.py` (EKSİK 0), procscan `mapping.py` (2229 satır, EKSİK 0, hata 0), review `map_table.py`
  (temiz), hosts `mapping.py` (1310 satır, AÇIK 0, hata 0). Üretilen dosya güncellenmesi gerekmedi.
- `cargo tree -e features -i serde_json -p copsd`: `preserve_order` 0 satır (R1; `cops-ep-state` `cops-steward-core`a bağlı değil).
- `cargo build --release -p copsd`: başarılı, ikili 6 495 608 bayt (B0 5 891 624; +603 984, +%10,3: `cops-procscan` +
  `cops-ep-state`). RSS ölçülmedi.
- Python: kod değişmedi; parite testleri Python'u yalnız `python3 -c` alt süreciyle (geçici `CLAUDEOPS_DIR`/`HOME`) çağırır.

İzole parite koşusu (canlıya dokunmadan): `unshare -rn` (kullanıcı + ağ ad alanı: yalnız loopback, dışarı ağ YOK),
geçici `CLAUDEOPS_DIR` ve `HOME` (scratch), rastgele loopback portta Python paneli (worktree `py/`, periyodik işler
`periodic.json` ile kapalı, `gnome-terminal` gizli) + aynı worktree'den release `copsd` (`--state-dir`, `--upstream`), sahte
`web.token`/`front.secret`. Fikstür: zengin `instances.json` (eşitlikler, Unicode, unutulmuş), iki değnekçi kimliği, çakışan
proje, 45 satırlık `diag.log`, `exec -a claude ... --remote-control parite` ile sahte canlı oturum. Betikler scratch'te
(`parity/run.sh`, `parity/launch.py`); yalnız başlatılan PID'ler kapatıldı.

| Kip | `endpoints.json` (5 istek) | Ek denetim |
|---|---|---|
| files | geçti 5, fark 0, hata 0, hepsi `local` | `parite` `running: true`, 4 satır rozetli, `?host=uzak` -> `python` |
| dual | geçti 5, fark 0, hata 0, hepsi `local` | aynı |
| db | geçti 5, fark 0, hata 0, hepsi `local` | aynı; `basic.json`: 6 geçti, 1 fark (`durum` = `/api/status`, iki taraf da Python'dan, zamanla değişen alan; B1 dışı) |

`cops-parity` gövdeyi JSON anlamıyla karşılaştırır; bayt eşitliği (anahtar sırası, `ensure_ascii`, sayı biçimi) birim
testlerinde Python çıktısına karşı sınandı (`cops-ep-state/tests/parity.rs`, üç kip).

## Canlıya alma ve geri dönüş (cops yapacak)

1. Önce öneki Python'a sabitle: `~/.claude/claudeops/front_force_proxy` dosyasına iki satır `/api/instances` ve `/api/diag/`
   ekle, `kill -HUP <copsd pid>` (restart yok).
2. `main`e birleştir, `cargo build --release -p copsd` (ÖZELLİKSİZ yapılandırma; kökten `cargo build --release` DEĞİL, R1),
   `bin/copsd` -> `copsd.prev`, yenisini koy, YALNIZ `claudeops-front.service` restart. Günlükte `copsd: yerel uç açık: GET
   /api/instances` ve `GET /api/diag/log` satırları.
3. Önekler duruyorken canlı çifte parite: `cops-parity rust/crates/cops-parity/requests/endpoints.json` (8765 dış, 28765 iç).
   Önekli koşuda Rust tarafı da Python'a gider (`expect: local` notu beklenir); asıl karşılaştırma 4. adımdan sonra.
4. Önekleri dosyadan sil + `kill -HUP`; parite yeniden: 0 fark ve `served local`; `/api/front/stats` `local` sayacı artmalı.
5. 24 saat `route_hook_failed` ve `copsd: /api/instances:` hata satırı yok.
- Geri dönüş (uç bazında): öneki `front_force_proxy`ye geri yaz + `kill -HUP`. Tam geri dönüş: `copsd.prev` + front restart.
- copsd-ent: çekirdek rev iki `Cargo.toml`da birlikte yükselir; `run_auth_on.py` e2e bu uçlarda 401/403 kuralını korumalı
  (koşulmadı, aşağıda).

## Doğrulanmayanlar

- Canlı çift paritesi, `/api/front/stats` sayaçları, 24 saatlik günlük (canlıya dokunulmadı).
- copsd-ent derlemesi ve `run_auth_on.py`/`run_auth_shadow.py` e2e (enterprise yalnız okundu; rev yükseltmesi cops işi).
  `RouteCtx`a alan eklendi (`state`); copsd-ent `RouteCtx`i kurmuyor (B0 notu), `register` imzası değişmedi.
- Başsız tarayıcıda Geçmiş sekmesi (gövde Python'la aynı olduğu için arayüz değişikliği beklenmez).
- Postgres `CLAUDEOPS_DB_URL`: salt okunur açılış `Unsupported` döner, dosyaya düşülür (koddan; koşulmadı). Python Postgres'te
  DB'yi okurdu: o kurulumda `db` kipinde fark olur; canlı SQLite.
- copsd ve Python süreçlerinin ortamı farklıysa (`CLAUDEOPS_STORE_BACKEND`, `CLAUDEOPS_DB_URL`, `CLAUDEOPS_DIAG_LOG` yalnız
  birinde) kip/yol farklı çözülür (B0'dan beri aynı varsayım).
- `immutable=1` dalında eşzamanlı ilk yazarla yırtık okuma: kuramsal, sınanmadı (bkz. bulgu).
- RSS ve 60 sn CPU ölçülmedi (ikili boyutu yukarıda).
