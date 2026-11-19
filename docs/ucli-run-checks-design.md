# ucli `run_checks` (kayıtlı kontrol çalıştırıcı) tasarımı

Durum: tasarım (19 Kas 2026). Kaynak: claudeops `TODO.md` satır 19 (iki modlu çalıştırıcı) ve 20 (ek kararlar a-f). ucli'de
`run_checks` / `--allow-checks` YOK (unified-cli `crates/` arandı): sözleşmeyi biz öneriyoruz. Dayanılan ucli parçaları: `exec.rs`
(bwrap kafesi, `--exec-env`, baş+kuyruk çıktı), `approval.rs` (çıkış 75), `ask_user.rs`, `--state-dir`, REPL `/plan` (yetki daraltma).

## 1. Amaç ve tehdit modeli

**Amaç:** model test/derleme/denetim komutlarını, kabuk ya da genel `exec` izni almadan, İNSANIN önceden yazdığı adlandırılmış
kontroller üzerinden çalıştırsın. Model yalnız `ad + parametre` seçer; argv'yi, cwd'yi, ortamı, kafesi insan belirler.

**Model (restricted) YAPABİLİR:** kayıttaki kontrolü doğrulanmış parametrelerle çağırmak, çıkış kodunu ve kırpılmış çıktıyı
görmek, bütçe bitene kadar tekrarlamak. **YAPAMAZ:** kaydı okumak/değiştirmek (kök DIŞI); argv'ye parça eklemek; yorumlayıcıya
serbest kod vermek (`-c`, `-e`); ağa çıkmak (`network = "host"` işaretli kontrol hariç, bkz. Sahip kararı 1); kontrolün `write`
kapsamı dışına yazmak; modu genişletmek (yalnız insan, bkz. 3.4); değiştirici kontrolü onaysız uygulamak.

**Kalan risk (bilerek kabul):** kontrol kafeste model tarafından değiştirilmiş kodu çalıştırabilir (`python3 -m unittest`
modelin düzenlediği testleri içe aktarır, `deno test` aynı). Bunu kafes sınırlar (ağsız, salt-okunur sistem, boş `$HOME`, süre/bellek
tavanı), kayıt değil (`exec.rs` başlığı aynı sınırı yazıyor). Yasak liste (`ucli_session_opts.FORBIDDEN_CMDS`) genel `exec` için
DEĞİŞMEZ; kayıttaki kontrolün argv[0]'ı yorumlayıcı olabilir, çünkü argv'yi insan yazdı ve model kod enjekte edemez.

**Kapsam dışı tehdit:** aynı Unix kullanıcısıyla çalışan başka bir sınırsız ajan (ör. kabuk izni olan bir Claude Code oturumu)
kayıt dosyasını değiştirebilir. Kayıt, ucli modeline karşı korur; aynı UID'deki başka süreçlere karşı korumaz.

**full:** açık `accept_risk` ile açılır. Kayıttaki kontroller + `[full]` bölümünde listelenen programlarla serbest argv
(yorumlayıcı `-c`/`-e` dahil). Yine kafeste; ağ yalnız `--exec-net` verildiyse. GPU cihaz bind'i yalnız full'da.

## 2. Kayıt dosyası

**Konum:** ucli tek başına: `~/.config/ucli/checks.toml` (varsayılan). claudeops: `<CLAUDEOPS_DIR>/ucli_checks/<sahip>.json`
(aynı şemanın JSON hali, bkz. 4.3; sahip = panel kullanıcısı, tek kullanıcıda `owner.json`), `--checks-file` ile verilir.

**Yükleme kuralları (ucli zorlar, ihlal = oturum AÇILMAZ, kapalı başarısız):**
- düz dosya; yolun hiçbir parçası symlink değil (mevcut `status::check_operator_path` aynı kontrolü yapıyor);
- sahibi ucli'nin etkin UID'i, kip `0600` (grup/diğer bitlerinden biri açıksa red);
- çözülmüş yol `--root` altında DEĞİL ve `--state-dir` altında değil;
- `version = 1`; bilinmeyen sürüm, bilinmeyen anahtar, yinelenen `name` = red (sessiz yok sayma yok);
- oturum başında okunur, sha256 özeti durum dosyasına; yeniden okuma yalnız insan `/checks reload` (hatalıysa eski görüntü kalır).

**Örnek:**

```toml
version = 1

[defaults]                 # her kontrol bunları devralır, kendi değeriyle daraltabilir (genişletemez: tavan aşılırsa red)
timeout_secs = 120         # duvar saati; ucli exec tavanı 300 sn (exec.rs MAX_TIMEOUT_SECS), kontrol tavanı ayrı: en çok 1800
memory_mib = 2048          # RLIMIT_AS + cgroup MemoryMax (exec ile aynı mekanizma)
max_tasks = 256
output_kib = 64            # akış başına baş+kuyruk toplamı
calls_per_session = 40
network = false
write = "tmp"              # none | tmp | root | ["göreli/dizin", ...]

[[check]]
name = "unittest"
description = "claudeops birim testleri: tümü ya da tek modül"
argv = ["python3", "-m", "unittest", "{module}"]
cwd = "py"                 # kök içi göreli; .. ve mutlak yol yok
env = { PYTHONDONTWRITEBYTECODE = "1", LANG = "C.UTF-8" }
timeout_secs = 900
# optional: verilmezse argv öğesi DÜŞER -> `python3 -m unittest` (tümü)
params.module = { kind = "regex", pattern = '^tests\.test_[a-z0-9_]+$', optional = true }

[[check]]
name = "webui-build"
argv = ["npm", "run", "build"]
cwd = "webui"
require_worktree = true    # kök bir git worktree değilse (".git" dosya değilse) red
write = ["webui/dist", "webui/node_modules/.vite"]
memory_mib = 8192          # node adres alanı (exec.rs E3 iletisi aynı sorunu anlatıyor)

[[check]]
name = "k8s-get"
argv = ["kubectl", "-n", "{ns}", "get", "{kind}", "-o", "wide"]
env = { KUBECONFIG = "/run/ucli-kube/config" }
bind_ro = [{ src = "~/.config/ucli/kube/anomaly-ro.yaml", dst = "/run/ucli-kube/config" }]
network = "host"           # bkz. Sahip kararı 1
params.ns = { kind = "enum", values = ["anomaly", "anomaly-dev"] }
params.kind = { kind = "enum", values = ["pods", "deployments", "services", "events"] }

[[check]]
name = "k8s-apply"
mutating = true
argv = ["kubectl", "-n", "anomaly", "apply", "-f", "{manifest}"]
dry_run = ["kubectl", "-n", "anomaly", "diff", "-f", "{manifest}"]
dry_run_ok_exit = [0, 1]   # kubectl diff: 1 = fark var (hata değil)
env = { KUBECONFIG = "/run/ucli-kube/config" }
bind_ro = [{ src = "~/.config/ucli/kube/anomaly-deployer.yaml", dst = "/run/ucli-kube/config" }]
network = "host"
params.manifest = { kind = "path", under = "deploy", file = true, glob = "*.yaml" }

[full]                     # yalnız --allow-checks=full ile anlamlı; devices yalnız full (ör. /dev/nvidia0)
programs = ["python3", "node", "deno", "bash"]
timeout_secs = 600
memory_mib = 8192
calls_per_session = 100
write = "root"
devices = []
```

**Şablon kuralları:** `{param}` argv öğesinin TAMAMI olmalı (alt dize birleştirme yok, kabuk yok); `optional` parametre verilmezse
öğe düşer; parametre değeri `-` ile başlıyorsa yalnız `enum` ise kabul. argv[0] çıplak ad ise yüklemede PATH'ten mutlak yola
çözülür ve o yoldan çalışır (`exec` ile aynı ilke).

**Doğrulayıcılar:** `enum {values}`, `regex {pattern, max_len<=256}` (tam eşleşme zorlanır), `path {under, file|dir, glob,
must_exist}` (çözülmüş yol kök ve `under` içinde; `.git`/`.ucli` reddi exec'in `protected_paths` kuralıyla aynı),
`int {min, max}`. Bilinmeyen `kind` = yükleme reddi.

**env:** kafes ortamı boş başlar (exec gibi); yalnız `env` tablosundaki DEĞİŞMEZ değerler girer. Anahtar serbesttir (insan yazdı)
ama `LD_*`, `*PRELOAD*`, `NODE_OPTIONS`, `PYTHONSTARTUP` yükleme reddi. Gizli değer (token) env'e yazılmaz: kontrol çıktısı
modele gider. Not: exec'in `EXEC_ENV_ALLOWED` listesinde `KUBECONFIG` YOK; kontrol env'i bu listeden bağımsız olmalı (ucli değişikliği).

**bind:** kontrol başına `bind_ro` (`src` ev dizini altında olabilir ama `exec.rs BIND_RO_SENSITIVE_HOME` kuralları geçerli,
`dst` kafes içi sabit yol). kubeconfig YALNIZ k8s kontrolüne bağlanır, test kontrollerine ASLA (karar c); admin değil, namespace'li
RBAC'lı ServiceAccount; salt-okunur ve değiştirici kontroller AYRI SA. Kayıt bunu denetleyemez: panelde uyarı metni.

**write:** `none` = kök salt-okunur, tmp yok; `tmp` = taze `/tmp`; `root` = kök yazılabilir; liste = yalnız o kök içi dizinler
yazılabilir (geri kalan salt-okunur). Oturum `--ask-edit` ile açıksa ucli exec kafesini salt-okunur yapıyor
(`main.rs exec_cage_writable = allow_edit && !ask_edit`): aynı ilke burada da geçerli olmalı, `write = "root"` olan kontrol
`--ask-edit` altında **değiştirici** sayılır (onaya düşer); liste biçimindeki çıktı dizinleri onaysız kalır.

## 3. ucli sözleşmesi (ucli koderi için)

### 3.1 Bayraklar
- `--allow-checks restricted|full`: başlangıç modu; yoksa araç modele HİÇ sunulmaz. `--checks-max restricted|full`: çalışırken
  çıkılabilecek tavan (varsayılan = başlangıç). Biri `full` ise `--checks-accept-risk` şart, yoksa başlatma hatası.
- `--checks-file PATH`: kayıt (varsayılan `~/.config/ucli/checks.toml`). Dosya yok/geçersiz = başlatma hatası.
- `--exec-net`: full'daki serbest argv için ağ. Kayıttaki `network = "host"` kontrolleri bu bayraktan bağımsızdır (bkz. Sahip kararı 1).
- Mod dosyası: `--state-dir` ve `--session` verilmişse `<state-dir>/<session>.checks.json`. ucli bu dosyayı HER TUR başında ve her
  `run_checks` çağrısından önce okur. Biçim `{"v":1, "mode":"off|restricted|full", "seq":N, "set_by":"...", "at":"..."}`.
  Etkin mod = min(dosyadaki mod, `--checks-max`). Dosya yok/bozuk = başlangıç modu sürer (genişletme yok, daraltma uygulanmışsa
  daraltılmış kalır). Araçlar state-dir'e zaten yazamaz (`main.rs` `--state-dir` yardım metni).

### 3.2 Araç şeması
Ad `run_checks`. Açıklama metni kayıttan üretilir: her kontrolün adı, `description`'ı, parametre adları ve doğrulayıcı özeti
(regex desenleri, enum değerleri). argv ve env modele GÖSTERİLMEZ (`argv_echo` hariç, aşağıda).

Girdi: `{"name": "unittest", "params": {"module": "tests.test_x"}}`. full modda ek olarak `{"argv": ["python3", "x.py"]}`
(`name` yerine; program `[full].programs` içinde olmalı).

Sonuç (çalıştıysa, çıkış kodu sıfır olmasa da SONUÇTUR):
```json
{"check":"unittest","mode":"restricted","argv_echo":"python3 -m unittest tests.test_x","exit_code":1,"timed_out":false,
 "duration_ms":8123,"stdout":"...","stderr":"...","dropped":{"stdout":0,"stderr":5120},"calls_left":37}
```
Ret (exec'in `{"error","rule","program"}` biçimiyle aynı aile): `{"error": "...", "rule": "<kural>", "check": "<ad>"}`;
kurallar: `mode_off`, `unknown_check`, `param_invalid`, `param_missing`, `budget_exhausted`, `not_worktree`, `cage_unavailable`,
`dry_run_failed`, `approval_rejected`, `approval_expired`, `full_only`, `program_not_listed`.

### 3.3 Değiştirici kontrol akışı (karar b)
1. `dry_run` argv'si kafeste çalışır (`dry_run_ok_exit` dışı çıkış = `dry_run_failed`, uygulama yok).
2. Onay istenir, mevcut kanal: REPL'de `--ask-dir` (soru: kontrol adı + parametreler + kuru çalıştırma çıktısının kırpılmış hali),
   tek atımlık işte `--approval-dir` (`pending/<id>.json` içinde `kind: "check"`, bugün yalnız `"edit"` var: `approval.rs` 217),
   terminalde `--interactive`. Hiçbiri yoksa mutating kontrol modele SUNULMAZ (araç açıklamasında görünmez).
3. Onay kuru çalıştırma çıktısının sha256'sına bağlanır. Uygulamadan hemen önce kuru çalıştırma yeniden koşar; özet değiştiyse ret
   (`approval.rs`'in "hedef dosya değişti" kuralının karşılığı).
4. `approve_session` mutating kontrolde KABUL EDİLMEZ; `edit` parametreleri değiştirebilir, aynı doğrulayıcılardan geçer.

### 3.4 REPL `/checks`
- `/checks`: etkin mod, tavan, kayıt özeti, kontrol başına kalan bütçe.
- `/checks off|restricted`: DARALTMA, anında; mod dosyası varsa ucli `seq+1` ile oraya da yazar (claudeops görür).
- `/checks full` (ya da tavanı aşan her genişletme): REPL'den UYGULANMAZ; "genişletme panelden onaylanır" iletisi basar
  (bkz. Sahip kararı 2). Genişletme yalnız mod dosyası üzerinden ve `--checks-max` tavanına kadar.
- `/checks reload`: kayıdı yeniden doğrular. Hepsi `/plan`, `/permissions` gibi REPL yerleşik komutu: model araçla üretemez.

### 3.5 Durum ve çıkış kodları
- Durum dosyası (`--status-file`): `checks: {mode, max, registry_sha256, calls: {ad: kullanılan}}` eklenir.
- Başlatma hatası (kayıt geçersiz, izin/symlink, accept_risk yok): sıfır olmayan çıkış + stderr'de `checks:` önekli tek satır;
  kod ucli'nin mevcut başlatma hatasıyla aynı (hangi kod olduğu doğrulanmadı). Onay askısı: mevcut `75`, yeni kod YOK.
  Kontrolün başarısızlığı ucli çıkış kodunu etkilemez.

## 4. claudeops tarafı

### 4.1 Başlatma seçeneği
`cli_opts.ucli_checks`: `{"mode": "restricted"|"full", "max": "restricted"|"full", "accept_risk": bool}`.
`ucli_session_opts.validate_opts` kuralları (geçersiz = HATA, sessiz atlama yok, modülün mevcut ilkesi):
- `mode` yoksa anahtar düşer (varsayılan KAPALI); bilinmeyen değer = hata; `max` < `mode` = hata, `max` yoksa = `mode`;
- `mode` ya da `max` `full` ise `accept_risk` doğru olmalı (mevcut `BROAD_GLOBS` kabul düzeniyle aynı metin);
- sahibin kayıt dosyası yoksa ya da doğrulamadan geçmiyorsa hata ("Ayarlar > Ucli > Kontroller'den kayıt ekle");
- oturum adı + state-dir şart: `ucli_checks` açıkken `_state_dir_args` ayardan bağımsız state-dir verir (ayar
  `ucli_state_dir_enabled` varsayılan kapalı; mod dosyası onsuz çalışmaz);
- `approval_dir` ile birlikte mutating kontrol varsa geçerli; yoksa mutating kontroller ucli'de zaten sunulmaz (uyarı, hata değil).

### 4.2 `_apply_cli_opts` bağlantısı
`--allow-checks`, `--checks-max`, `--checks-file`, (`full` ise) `--checks-accept-risk` için `binary_supports_flag` kapısı.
Güvenlik izni: tanımayan ikilide `ValueError` + `diag_log("ucli_flag_unsupported")` (ask_dir/git düzeni), sessiz düşme yok; `full`
açılışı `diag_log("ucli_grant", checks="full", accept_risk=True)`.

### 4.3 Kayıt yönetimi
- claudeops Python 3.10'da koşuyor (`tomllib` yok, kodda TOML ayrıştırıcı yok; doğrulandı): kayıt claudeops'ta **JSON** tutulur
  (`<sahip>.json`, aynı şema). ucli `--checks-file` uzantıya göre `.toml` ya da `.json` okur (U1). Doğrulamanın tek kaynağı ucli:
  yeni alt komut `ucli checks validate --checks-file F --json` (`{ok, errors:[{check, field, message}], checks:[...]}`); yaprak
  modül `ucli_checks.py` yalnız biçim/boyut ön denetimi yapar ve kaydetmeden önce bu alt komutu çağırır.
- Yazım: atomik, `os.open(..., O_NOFOLLOW, 0o600)` (mevcut `_service_key_file` deseni), dizin `0700`.
- Panel: Ayarlar > Ucli > "Kontroller": liste (ad, açıklama, mutating rozeti, ağ rozeti), ekle/düzenle (alan alan form + ham JSON),
  sil. Hazır şablonlar (TODO 19'daki ihtiyaç listesi: claudeops unittest/tsc/webui build/`cops check`, kulturweb deno, makale
  latexmk, git status/diff/log, k8s salt-okunur fiiller). kubeconfig alanının yanında "dar ServiceAccount kullan" uyarısı.
- `/api/files/*` (`files.write`) bu dizine erişememeli: dosya API'sinin `CLAUDEOPS_DIR` altına yazamadığı doğrulanmadı; C2'de test edilir.

### 4.4 Mod seçici
- Başlatma penceresi: "Kontroller: kapalı / restricted / full (+ tavan)"; full işaretlenince accept_risk kutusu.
- Çalışan oturum satırı: mevcut etkin mod (durum dosyasından) + seçici. Daraltma: `POST /api/ucli/checks-mode {name, mode}` mod
  dosyasını yazar (`seq+1`), onay yok. Genişletme: aynı uç `confirm: true` ister, panel açık onay penceresi gösterir; denetim
  kaydı `<CLAUDEOPS_DIR>/ucli_checks/audit.jsonl` (0600, ekleme): `{at, user, session, from, to, max, ip}`. Tavanı aşan
  genişletme 409 ("oturumu yeni tavanla yeniden aç").
- Ajan token'ı (`/api/agents/*`) ve orkestrasyon/steward yolları bu uca erişemez.

### 4.5 authz
- `/api/ucli/checks` (kayıt CRUD): `admin.config` (kayıt bir güvenlik izni; `/api/settings` ile aynı).
- `/api/ucli/checks-mode`: `session.control`, kaynak = oturum (mevcut `ucli/approvals` kaynak eşlemesi gibi).
- Çok kullanıcı: oturumu açanın kaydı kullanılır; mod değişimi yalnız oturum sahibi ya da admin. Uzak makinede (yuhem, ulak_31)
  kayıt ucli'nin koştuğu makinede: iki uç `HOST_ROUTED_PATHS`'a eklenir, dosyayı o makinenin claudeops'u yazar.

## 5. Dilimler

| Dilim | Sahibi | İş | Doğrulama |
|---|---|---|---|
| U1 | ucli koder | kayıt ayrıştırıcı + doğrulayıcılar + yükleme kuralları (0600, symlink, kök dışı, sürüm) | birim: her red kuralı için bir test, örnek TOML'un tamamı geçer |
| U2 | ucli koder | `run_checks` aracı, restricted, kafes (exec `CageSpec` yeniden kullanımı), kontrol başına env/bind/write/ağ, bütçe, sonuç/ret biçimi | birim + kafes testi (`UCLI_REQUIRE_CAGE=1`): ağ yok, `$HOME` boş, yazma kapsamı, şablon dışı argüman reddi |
| U3 | ucli koder | mod dosyası okuma, `--checks-max`, REPL `/checks`, durum dosyası alanı | birim: daraltma anında, genişletme yalnız dosyadan ve tavana kadar, REPL'den genişletme reddi |
| U4 | ucli koder | mutating: dry_run, ask-dir/approval-dir/interactive bağlantısı (`kind: "check"`), özet bağlama | birim: onaysız uygulanmaz, özet değişince ret, `approve_session` reddi, 75 ile askı + sürdürme |
| U5 | ucli koder | full: `[full].programs`, `--checks-accept-risk`, cihaz bind | birim: accept_risk yokken başlatma hatası, liste dışı program reddi, `--exec-net` yokken ağ yok |
| C1 (YAPILDI 19 Kas) | cops | `ucli_checks.py` + `validate_opts` + `_apply_cli_opts` kapısı | birim: her `validate_opts` kuralı; tanımayan ikilide açılış reddi |
| C2 (YAPILDI 19 Kas: çekirdek+uçlar+authz+denetim, 9 test; uzak host yönlendirmesi ve `/api/files` yazma denemesi KALDI) | cops | `/api/ucli/checks`, `/api/ucli/checks-mode`, authz, denetim kaydı | birim: authz eşlemesi, genişletme `confirm` ister, tavan 409, ajan token'ı 403 |
| C3 | cops | panel: Ayarlar > Ucli > Kontroller, başlatma seçici, satır seçici, onay kutusu (mutating `UcliAskBox`/`UcliApprovalsPanel` `kind: check` gösterimi) | `tsc --noEmit`, izole 8790 Chrome masaüstü + dar ekran ekran görüntüsü |
| C4 | cops | gerçek ikiliyle uçtan uca: claudeops worktree'de `unittest` + `tsc` kontrolü, daraltma/genişletme | canlı oturum, durum dosyasında mod ve sayaç |
| C5 | cops | (karar f) ulak_31'e ucli kurulumu + kafes testi, sonra anomaly k8s salt-okunur kontrolleri | `ucli doctor` + kafes testi uzak makinede; k8s-get gerçek çıktı |
| C6 | cops | (karar e) bash'siz kabuk işleri: yerleşik araç + Lua `run_script` örtüşme listesi, araç günlüğündeki başarısız kabuk denemelerinden eksik listesi, ucli'ye istek | liste dosyası + ucli TODO maddesi |

Sıra: U1 > U2 > C1 > C4 (restricted yeterli ilk değer) > U3 > C2 > C3 > U4 > U5 > C5 > C6.

**Teslim kuralı (karar a):** ucli koder yalnız unified-cli reposuna commit eder. `cargo build --release` ve `<claudeops>/bin/ucli`
kopyasını HER ZAMAN cops yapar, sonra `binary_supports_flag` ile yeni bayrakların göründüğünü doğrular; koder kopyalamaz.

## 6. Açık noktalar

Varsayım (soru değil, geri alınabilir): kayıt oturum başında okunur, çalışırken yalnız `/checks reload`; kontrol duvar saati tavanı
1800 sn; liste biçimli `write` çıktı dizinleri `--ask-edit` altında onaysız kalır; varsayılan `write = "tmp"`, kökü yazan kontrol
bunu açıkça `root`/liste ile söyler.

### Sahip kararı (HEPSİ KARARA BAĞLANDI 19 Kas, TBD#260: 1a, 2a, 3a; aşağıdaki öneriler kesinleşti)

1. **k8s kontrolünün ağı.** kubectl API sunucusuna ağ ister; bwrap'ta ağ ya hep ya hiç (`--share-net`). Seçenekler:
   (a) kontrol başına `network = "host"` restricted'da da izinli (kubeconfig dar SA ile sınırlı);
   (b) k8s kontrolleri yalnız full'da;
   (c) kafes içi tek hedefli vekil (yalnız API sunucusu). Öneri: (a) şimdi, panelde kırmızı ağ rozetiyle; (c) ileride.
2. **REPL'den genişletme.** Sahip notu "`/checks full` insan girdisinden çalışır" diyor; ama claudeops'ta tmux girdisini insan
   dışında da yazan yollar var (`web_orch` istemi `/api/term/input` ile gönderiyor; steward yolları doğrulanmadı). ucli ayrımı göremez.
   Seçenekler: (a) REPL yalnız daraltır, genişletme yalnız panel onayı + mod dosyası; (b) REPL genişletir, claudeops orkestrasyon
   yollarında `/checks` ile başlayan satırları süzer. Öneri: (a), süzgeç unutulursa açık kapı kalır.
3. **full'da program kapsamı.** (a) `[full].programs` listesi şart (önerilen örnekteki gibi); (b) PATH'teki her program.
   Öneri: (a), "yorumlayıcılar serbest" isteğini karşılar, `curl`/`ssh` gibi araçları dışarıda tutar.
