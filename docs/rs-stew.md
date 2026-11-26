# İz rs/stew: değnekçi saf çekirdeği (`rust/crates/cops-steward-core`)

## Kapsam ve ayrım

`py/claudeops/steward.py` (6.253 satır). Saf kararlar ve prompt üreticileri bu crate'e taşınır; dosya deposu, kilit,
olay günlüğü, alt süreç ve saat okuyan işlevler taşınmaz (gerekçe ve ait olduğu iz: `parity/out_of_scope.json`, aşağıdaki
tabloda satır satır). `web_steward.py` bu izde yok. İşlev haritası (saf / G/Ç) = alttaki eşleme tablosu.

## Parite düzeni

- `parity/gen.py`: tüm modül sabitleri/regex'leri ve veri sınıfları Python'dan ÜRETİLİR (`generated` testi bayatlığı yakalar).
- `parity/record.py`: Python steward testleri (2.531 test, yalıtılmış geçici dizin) koşarken saf işlevlerin girdi/çıktısı
  `fixtures/vectors/*.jsonl.gz`'ye kaydedilir; `tests/parity` Rust'ta tekrar oynatır. İşlev başına en çok 250
  (`plan_tick` 600, `scan_markers` 500) tekil çağrı, özet sırasıyla seçilir (her test çağrısı değil).
- `parity/map.py`: aşağıdaki tabloyu `ast` ile üretir; EKSİK satır varsa `--check` kırmızı.
- Altın tick: `py/tests/steward_golden_tick.json`.

## Durum ve devir (26 Kas 2026 akşam): BİRLEŞTİRMEYE HAZIR DEĞİL

Taşınan: `identity.rs`, `markers.rs` (`fa5cecc`), `cards.rs`, `prompts.rs` (`c9e1d80`), grup 1 (soru/fikir):
`questions.rs`, `store.rs`, `notify.rs`, `inserts.rs`, `logdedup.rs` (+ `cards.rs`de `make_card`, `mark_card_stale`,
`note_card_failure`; `identity.rs`de `derived_of`, `project_key`: `owner_key` kopyası kalktı) ve grup 2 (`a619ca2`):
`world.rs` (`World`, izlenen oturumlar, satır seçimi, teslim), `closing.rs` (devir erteleme, kontrollü kapatma, bağlam
sorusu, toparlama, DONE çelişkisi), `gates.rs` (iş/cevap kapıları, beyin araç hükmü), `generic.rs` (`generic` rolü),
`ask.rs` (`steward_ask`: `owner_class`, `blocked_reason`, `tour_eligible`), `tour.rs` (`review_items`, işaret kayıt
eylemleri, `plan_markers`); grup 2'nin bağımlılığı olduğu için `markers.rs`e `clip_words`, `is_conditional_note`,
`marker_next_work` de alındı (grup 3 bunları atlar). `map.py`: 1331 -> 921 EKSİK satır (grup 1 ve 2 işlev
satırlarında EKSİK yok; kalanlar sonraki grupların öğeleri ve testleri). Grup 2 işlevlerini de çağıran üç test satırı
başka grubun öğesini beklediği için EKSİK kalır (`_ask_gate_lines`, `daily_summary`, `plan_tick`). "Saf çekirdek çağrısı
yok, gerekçe yazılmadı" satırlarının tümü kapanış grubunundur. `owner_class`/`blocked_reason` kaydı için `record.py`
`steward_ask` sarmalı ve `map.py` `DEPS` genişletildi.

Grup 3 (boşta/kurtarma): `recovery.rs` (API hatası ve otomatik "devam", `loop_guard`, sonuç doğrulama),
`idletext.rs` (son cevap/sahip cevabı okuyucuları, sıradaki iş, bayat not), `idle.rs` (`plan_ucli_idle`,
`plan_claude_idle`), `explain.rs` (`explain_idle`, `explain_idle_all`). `explain_idle_all` saf olduğu için
kapsam dışı ve `io_functions.json` listelerinden çıkarıldı. Grup 3'te taşınmayan öğe yok. `map.py`: 921 -> 718 EKSİK.
`pyc`: `ci_span` eklendi, `py_pattern` `(?im)`/`(?is)` bayrak gruplarında da büyük/küçük harf hazırlığı yapar.

Grup 3 sözleşmesi (T10): saat parametredir. Boşta planları `IdleInput` + geri çağrılar alır (`None` dönüşü =
bilinmiyor/Python istisnası; `has_question` için "soru var"). `explain_idle` `ExplainInput` alır
(`from_idle` ile boşta girdisinden). `without_stale_note` `Cow` döner. Parite: elle girdiler `parity/hand_cases.py`
"grup 3" bölümü (geri çağrı tabloları girdide; istisna fırlatan çağrı `null` kaydedilir; `plan_api_recovery`
`eligible` tablosu görünüm başınadır). Python istisnası beklenen vektörde Rust'ın hata dönmesi yeterlidir (sınıf ve
ileti karşılaştırılmaz).

Grup 2'de taşınmayanlar: `tour_delivery`, `panic_active`, `set_panic`, `read_brain_mcp`, `touch_brain_mcp` (dosya G/Ç'si;
kapsam dışı listesinde); `steward_ask.passes`, `decisions_path`, `decisions_section` (cevap kapısı uygulaması; `steward.py` bölgesinde
değil, `map.py` satırı yok; `passes` saftır, cevap yolunu taşıyan iz almalı).

Grup 2 sözleşmesi (T10): `review_items(TourInput)`; `plan_markers(.., now)` (Python `time.time()` okur);
`ask::*` ve `plan_deliveries`te saat parametredir; `panic_path(STEWARD_DIR)`; `upper_main_views`/`pick_delivery_view`
ödünç referans döner; `shutdown_note_result`, `note_project_next`, `request_pause_close` verilen sözlüğü yerinde
değiştirir, `plan_shutdown` yeni `sd` döner. Parite: elle girdiler `parity/hand_cases.py` "grup 2" bölümünde (ayrı
tohumlu rastgele üretici; geri çağrılı dallar yalnız kayıtlı vektörlerde). `topic_match` elle girdisi küme sırasına
bağlıydı, sıralı seçime çevrildi (artık belirlenimli).

Grup 1'de taşınmayanlar (kapsam dışı listesinde duruyor; T10 uygulama katmanı ya da sonraki grup):
- `apply_review_where_answer`: `review_remote.parse_answer`/`find_local_copy` (review modülü, disk) ister. `answer_question`
  çekirdeği `Answered::Done { review_where: true }` ile çağırana bildirir.
- `remove_project`, `transfer_project` (görev listesinde yoktu; `transfer_project`in soru/iş taşıma kararı hâlâ yalnız
  Python'da), `auto_remove_labels`, `project_owner`, `log_event`/`compact_log` ve diğer günlük/depo G/Ç'si.

Depo çekirdeği sözleşmesi (T10): çağıran kimlik kilidini alır, belgeyi okur, çekirdeği `now` ve kimlik üreticisiyle çağırır,
`dirty`/`Some`/`true` ise kaydeder. `upsert_project` sonrası: kaydet; `host_changed` ise `clear_project_state` + `project_host`
olayı; `auto_label_via` doluysa etiket kaldırma. `log_dedup` durumu (`LogSeen`) çağıranda tek kopya tutulur.
`questions::{open_questions, undelivered_answers, recent_answers}` bu süzgeçlerin tek kopyasıdır (`prompts` bunları kullanır).

Parite kaydı: durumlu işlevler `record.py` `STATEFUL` listesinde (saat dondurulur; önceki/sonraki belge, üretilen kimlikler ve
istisnalar kaydedilir; ana iş parçacığı dışındaki çağrılar ve kilit/disk hataları kaydedilmez). `record.py <ad...>` yalnız o
vektörleri yeniden yazar. `python3 -I` ile koşar (kullanıcı paketleri sistem paketlerinin önüne eklenir; yoksa testlerin bir
kısmı yüklenemez). `gen.py` artık `src/unicode_gen.rs`yi de üretir (`casefold`, `isdigit`). Crate'te `rustfmt.toml`
(`max_width = 120`): mevcut dosyaların biçimi buydu, ayar commit'lenmemişti.

Kalan gruplar, SIRAYLA (her biri taze Sonnet alt ajanı, `PORTING.md` ile):
4. Gözlem/rapor (5923-son).
5. `plan_tick` (4120-4805), Opus alt ajanı; altın kayıt `py/tests/steward_golden_tick.json`.
6. Kapanış: `parity/test_reasons.json`, `map.py --check` temiz, ders listesi (aşağıda).

Python `re` farkları için `pyc::py_regex` (`\b \w \W \s \S` Python tanımıyla; `(?i)` desende girdi `pyc::ci_input`tan geçer);
sonraki gruplarda da bunu kullanın, desenleri elle yazmayın.

## Python dersleri (`docs/rust-lessons-from-python.md` 2.6 ve bölüm 3)

HENÜZ KARŞILANMADI: her madde için test adı ya da gerekçe bu bölüme yazılacak (birleştirme koşulu).

## Python hatası?

"Python düzeltildi" işaretliler iki tarafta düzeltildi (TBD#370, sahip cevabı (c)); diğerleri aynen taşındı:

- Python düzeltildi: `290f6a3`. `valid_name`, `valid_custom_id`, `valid_steward_id`, `reviewer_ids`: `^...$` + `match` sondaki TEK
  satır sonunu geçiriyordu (`"default\n"` rezerve listesini aşıyordu). Python `fullmatch`; Rust `is_match` (`$` metin sonu).
  Aynı kalıbı (`^...$` + `match`) kullanan başka doğrulayıcılar var, DOKUNULMADI (girdinin önceden kırpılıp kırpılmadığı
  incelenmedi): `commands/web._NAME_VALID_RE`, `hosts`/`session` `_NAME_RE`, `labels.NAME_RE` ve `_COLOR_RE`, `review._LENS_NAME_RE`,
  `periodic._ID_RE`, `settings` (`_SVC_ID_RE`, `_SVC_ENV_RE`, `_HOST_RE`, tarih ve URL desenleri), `ucli_agents._SAFE_NAME_RE`,
  `ucli_approval` (`_KEY`, `_ID`), `ucli_ask._SAFE`, `ucli_checks` (`_OWNER`, `_NAME`), `ucli_session_opts` (`_CMD_RE`,
  `_PATTERN_CHARS`, `_GLOB_RE`, `_BIND_RE`), `ucli_client._SAFE_ENV_NAME_RE`, `providers/ucli_provider._MCP_TOOL_RE`,
  `chat_remote._TAG`, `graphical_session._DIGITS`, `window_actions._MODEL_RE`, `commands/web._MIRROR_ARG_RE`,
  `commands/web_steward` (`_DID_RE`, `_MODEL_LIST_RE`, satır içi model/ad desenleri), `steward._JOB_KIND_RE`.
- Python düzeltildi: `6097ed9`. `scan_markers`: düzyazıdaki `STEWARD-DONE-CONFIRMED yazmıyorum, ...` `confirmed` dolduruyordu.
  Kural (`_is_confirm_line`): işaretin ardında `:` varsa teyit; yoksa işaret satır başında (ya da `…:` ardında) olmalı ve
  ardından commit hash'i gelmeli ya da hiçbir şey gelmemeli. `:`siz "son commit abc1234 ..." biçimi artık sayılmaz.
- Python düzeltildi: `bdc2d68`. `build_tour_prompt(now=...)` kart yaşını verilen `now`dan hesaplar (Rust: `stamp` = Python `now`,
  başlık ve kart yaşı; yoksa `now` = saat).
- Python düzeltildi: `bdc2d68`. İngilizce turda faz satırının tür etiketi `kind:`.
- Otomatik bağlam cevabı (`plan_tick` 1b, `is_context_question`): dışlama deseni yalnız
  `commit|push|merge|deploy|force|\bsil|delete`; kurulum/harcama/parola/yetki geçen "bu oturumda mı, devirle mi" sorusu
  da otomatik cevaplanır (`OWNER_ONLY_RE` bakılmaz), rutin olmayan sahip sorusu dahil.
- `brain_tools_missing_text`: `no (matching )?(deferred )?tools?` dalı "no tools needed" gibi olağan cümlede de eşleşir
  (beyin gereksiz yeniden açılabilir).
- `upper_tier_approved`: `strip().rstrip(".!")` sırası yüzünden "evet ." / "onayla !" (noktalamadan önce boşluk) onay
  sayılmaz.
- `plan_deliveries`: `limit <= 0` yine bir eylem üretir (sınır eklemeden SONRA denetlenir).
- `plan_markers` `_now()` yerine `time.time()` okur (testte dondurulan saat `project_next.at`i etkilemez).
- `steward_ask.owner_class`: `now or time.time()`; `now=0.0` saat okur.
- `review_items` madde metinleri (`routine`, `ask`, `blocked`, `contradictions`) panel dili `en` olsa da Türkçedir.
- `resolve_answer` (seçenekli soru): `isdigit` doğru ama `int` kabul etmeyen cevap ("²", "①") `ValueError`, büyük hâli iki
  karakter olan tek harf ("ß", "ﬁ", "ŉ", "ǰ") `TypeError` fırlatır; cevap kaydedilmez. `answer_question` da aynen düşer.
- `add_question_ex`: açık soru sınırı (L7b) `CEVAP OTURUM AÇMADI:` önekli metin `routine=False` verilirse onu da en yeni
  açık soruya "ek" yapar; yorum bu maddelerin kendi başına kalacağını söylüyor (üretimde rutin açılıyor mu doğrulanmadı).
- `mark_notified` / `mark_delivered`: soru bulunmasa da depo yeniden yazılır.
- `upsert_project`: `priority`/`cadence_minutes`/`visits` dışındaki alanlar tip denetimsiz yazılır (`goal=5` kalıcı olur).
- `is_defer_answer`: desende hem "şimdi vereceğim" hem ASCII "simdi vereceğim" var, tam ASCII ("simdi verecegim") yok.
- Python düzeltildi: `bdc2d68`. `_clip(text, 0)` boş döner (eskiden `text[:-1] + "…"`).

Grup 3 (aynen taşındı; ilk üçü yalıtılmış Python koşusuyla doğrulandı):

- `is_open_answer`: baştaki olumlu sözcük deseni olumsuz çekimi de yakalar: "Başlamasın", "başlama", "devam etme",
  "start etme" -> `True` (paused/done proje AÇILIR). "ok, ama bekle" de `True` (baştaki olumlu sözcük kazanır; bu
  belgelenen davranış).
- `next_line`: `_NEXT_NONE_RE` yalnız `yok|none|nothing|-` tanır ve `-` ardında sözcük karakteri ister: "sıradaki: -",
  "sıradaki: —", "sıradaki: n/a", "sıradaki: bitti" gerçek iş sayılır (`(True, "bitti")`); `idle_finish_marker` bu
  satır varken aynı cevaptaki bitti işaretini yok sayar, `stated_next_work` bu metni iş diye döndürür.
- `next_line`: `\s*` satır sonunu geçer: boş "sıradaki:" satırı sonraki satırı iş sayar.
- `explain_idle` `idle_wait` ayrıntısı panel dili `en` olsa da "dk" yazar.
- `loop_guard`: `pause_h` tur (45 dk) ve cevap iletimi (15 dk) kesintisinde 0'dır (`pause_min` ayrıca var; tüketicinin
  hangisini kullandığı bu izde incelenmedi).

Rust'ta kaçınılmaz farklar (tipli arayüz):

- Grup 3: bozuk tipli `state` bölümü/kaydında `BadValue` (`loop_guard`, `loop_paused`, `check_outcomes`,
  `api_error_brief`, `plan_api_recovery`, `plan_ucli_idle`, `plan_claude_idle`, `explain_idle`). `plan_claude_idle`
  `ho_pending` sözlük ister (Python `in` listeyi de kabul ederdi). `plan_api_recovery` `st_err` sözlük alır. Python'un
  `try` ile yuttuğu geri çağrı istisnaları `None` dönüşüyle ifade edilir. `explain_idle_all` Python gibi tek projenin
  hatasında o projeyi atlar; bozuk `project_next` tüm çağrıyı düşürür. Zaman damgaları (`loop_guard`,
  `brain_stopped` ayrıntısı) sürecin `TZ`sine uyar.

- `identity::from_dict`: Python `_from_dict` yanlış tipli alanı olduğu gibi saklar; Rust `BadType` hatası döner (`null`, `3.0` -> tamsayı
  dahil). Yükleyiciyi yazan katman buna göre davranmalı.
- `lang_fix_action`: `state.lang_fix_at` sözlük olmayan dolu değerse hata (Python `dict()` ikili listesini kabul ederdi).
- Grup 2: bozuk tipli `state`/`sd`/`card` alanında `BadValue` (`plan_shutdown`, `shutdown_note_result`,
  `request_pause_close`, `plan_deliveries`, `plan_markers`, `note_project_next`, `start_decision_event`, `tour_eligible`,
  `review_items`, `job_request_gate`, `generic_backlog`). Python'dan farklı: `plan_shutdown` `items` sözlük değilse hemen
  hata; `dict()`in ikili listesi kabul etmesi taklit edilmez; sözlük olması beklenen yerde yanlış tip hep hatadır.
  `owner_class`/`blocked_reason` `now`u zorunlu alır (0.0 saat okumaz). `owned_evidence` yaz saati boşluğundaki damgayı
  bir saat sonrasından hesaplar (`mktime` platforma bağlı; TZ=UTC/İstanbul'da oluşmaz). Desen araması hata verirse
  (geri izleme sınırı) kapılar KAPALI yöne düşer: `owner_only` doğru, bağlam sorusu otomatik cevaplanmaz, DONE "bitti"
  sayılmaz, soru sahipte kalır.
- Hız: `pyc::py_regex`in `\b` çevirisi `OWNER_ONLY_RE` gibi uzun desende yavaştır (debug derlemede 73 bin karakterde
  yaklaşık 3,6 sn; release ölçülmedi). `backtrack_limit` 2^28'e çıkarıldı (varsayılan 1e6 uzun metinde aşılıyordu).
- `marker_texts` yalnız `Markers` alır (Python'un sözlük öğeli girdi dalı `scan_markers` çıktısında oluşmaz).
- Kartlar (`cards`): ham kart tipli `RawCard`dır; bozuk tipli kart/tur maddesi/`state` alanında (Python istisna fırlatır)
  `cards::BadValue` döner (`brain_pause_verdict`, `card_refresh_reason`, `card_lines`, `build_tour_prompt`, `mark_ask_seen`).
- `parse_card_json`: `serde_json` Python `json.loads`tan dardır: `NaN`/`Infinity`, eşsiz `\ud800` kaçışı ve 128'den derin iç içe
  yapı `None` verir (Python ayrıştırır); i64/u64 dışı tamsayılar ve `-0` kayan sayı olarak yazılır.
- `build_directive` `paths` yerine kimliğin soru listesini alır; `recent_answers`/`undelivered_answers`ın süzme kısmı
  `prompts` içinde (depo okuma çağıranda). Kayıtlı vektörlerde "Önceki cevaplarım" bloğu olan kayıtlarda depo beklenen metinden
  kurulur; süzme, sıralama ve kırpma `fixtures/hand` ile gerçek depoya karşı sınanır.
- `note_claims`: üretilen regex'lerde `\s` U+001C..U+001F'i saymaz, `\b` birleşen işaretleri sözcük sayar (Python tersi).
- Grup 1: `resolve_answer` istisnaları `ResolveError`; `upsert_project` yanlış tipli metin/sayı alanında `BadType` (Python
  saklar), i64 dışı tamsayı alanı yok sayılır (Python `priority`yi 5'e kırpardı); `os.path.expanduser` çağırandan
  (`UpsertContext::expanduser`); `log_dedup` içerik özetini kendi kanonik biçiminden alır (özet bellek içidir, dışarı çıkmaz);
  `casefold`/`isdigit` tablosu kaydın Python sürümünden (3.10, Unicode 13), diğer karakter sınıfları Rust'ın daha yeni
  Unicode'undan; 4300 haneden uzun sayı cevabında Python `int` istisnası taklit edilmez.
- `fixtures/hand` (`python3 -I parity/hand_cases.py`): kaydın kapsamadığı dallar için elle yazılmış girdiler, beklenen değer Python'dan.

## Eşleme tablosu

<!-- MAP:BEGIN (parity/map.py üretir) -->

### Python öğeleri (552 satır)

| Python adı (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `STEWARD_DIR` (steward.py:50) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `PROJECTS_JSON` (steward.py:51) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `IDEAS_JSON` (steward.py:52) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `QUESTIONS_JSON` (steward.py:53) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `STATE_JSON` (steward.py:54) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `LOG_JSONL` (steward.py:55) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `WORKSPACE_DIR` (steward.py:56) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `BUNDLED_PERSONA` (steward.py:57) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `StewardPaths` (steward.py:62) | `identity::StewardPaths` | identity::paths_layout_and_errors | tamam |
| `_SID_RE` (steward.py:84) | `consts_gen::P_SID_RE` | generated::generated_files_are_current | tamam |
| `paths_for` (steward.py:87) | `identity::paths_for` | identity::paths_for_vectors, identity::paths_layout_and_errors | tamam |
| `paths_for._rv` (steward.py:94) | `identity::paths_for (içinde)` | identity::paths_for_vectors, identity::paths_layout_and_errors | tamam |
| `_pp` (steward.py:112) | `identity::pp` | identity::p_pp | tamam |
| `CARD_DOCS` (steward.py:115) | `consts_gen::CARD_DOCS` | generated::generated_files_are_current | tamam |
| `CARD_DOC_CHARS` (steward.py:116) | `consts_gen::CARD_DOC_CHARS` | generated::generated_files_are_current | tamam |
| `CARD_LIST_ITEMS` (steward.py:117) | `consts_gen::CARD_LIST_ITEMS` | generated::generated_files_are_current | tamam |
| `CARD_TEXT_CHARS` (steward.py:118) | `consts_gen::CARD_TEXT_CHARS` | generated::generated_files_are_current | tamam |
| `PHASES` (steward.py:120) | `consts_gen::PHASES` | generated::generated_files_are_current | tamam |
| `KINDS` (steward.py:121) | `consts_gen::KINDS` | generated::generated_files_are_current | tamam |
| `ACTIVE_PHASES` (steward.py:122) | `consts_gen::ACTIVE_PHASES` | generated::generated_files_are_current | tamam |
| `MODES` (steward.py:125) | `consts_gen::MODES` | generated::generated_files_are_current | tamam |
| `SUBAGENT_QUIET_SECONDS` (steward.py:128) | `consts_gen::SUBAGENT_QUIET_SECONDS` | generated::generated_files_are_current | tamam |
| `OBSERVE_SKIPPED` (steward.py:129) | `consts_gen::OBSERVE_SKIPPED` | generated::generated_files_are_current | tamam |
| `OBSERVE_DEDUP_SECONDS` (steward.py:130) | `consts_gen::OBSERVE_DEDUP_SECONDS` | generated::generated_files_are_current | tamam |
| `MARK_END` (steward.py:135) | `consts_gen::MARK_END` | generated::generated_files_are_current | tamam |
| `MARK_ASK` (steward.py:136) | `consts_gen::MARK_ASK` | generated::generated_files_are_current | tamam |
| `MARK_IDEA` (steward.py:137) | `consts_gen::MARK_IDEA` | generated::generated_files_are_current | tamam |
| `MARK_DETAIL` (steward.py:138) | `consts_gen::MARK_DETAIL` | generated::generated_files_are_current | tamam |
| `MARK_ROUTINE` (steward.py:139) | `consts_gen::MARK_ROUTINE` | generated::generated_files_are_current | tamam |
| `MARK_BLOCKED` (steward.py:140) | `consts_gen::MARK_BLOCKED` | generated::generated_files_are_current | tamam |
| `MARK_LESSON` (steward.py:141) | `consts_gen::MARK_LESSON` | generated::generated_files_are_current | tamam |
| `MARK_NEXT` (steward.py:142) | `consts_gen::MARK_NEXT` | generated::generated_files_are_current | tamam |
| `MARK_JOB` (steward.py:143) | `consts_gen::MARK_JOB` | generated::generated_files_are_current | tamam |
| `JOB_REQUEST_PREFIX` (steward.py:144) | `consts_gen::JOB_REQUEST_PREFIX` | generated::generated_files_are_current | tamam |
| `MARK_PLAN_READY` (steward.py:145) | `consts_gen::MARK_PLAN_READY` | generated::generated_files_are_current | tamam |
| `MARK_DONE` (steward.py:146) | `consts_gen::MARK_DONE` | generated::generated_files_are_current | tamam |
| `MARK_DONE_CONFIRMED` (steward.py:147) | `consts_gen::MARK_DONE_CONFIRMED` | generated::generated_files_are_current | tamam |
| `DONE_CONFIRM_TTL` (steward.py:148) | `consts_gen::DONE_CONFIRM_TTL` | generated::generated_files_are_current | tamam |
| `_CONFIRM_HASH_RE` (steward.py:149) | `consts_gen::P_CONFIRM_HASH_RE` | generated::generated_files_are_current | tamam |
| `_CONFIRM_ZERO_RE` (steward.py:150) | `consts_gen::P_CONFIRM_ZERO_RE` | generated::generated_files_are_current | tamam |
| `_CONFIRM_COLON_RE` (steward.py:151) | `consts_gen::P_CONFIRM_COLON_RE` | generated::generated_files_are_current | tamam |
| `_CONFIRM_LEAD_HASH_RE` (steward.py:152) | `consts_gen::P_CONFIRM_LEAD_HASH_RE` | generated::generated_files_are_current | tamam |
| `NO_DONE_TAG` (steward.py:153) | `consts_gen::NO_DONE_TAG` | generated::generated_files_are_current | tamam |
| `READY_FOR_HANDOVER` (steward.py:154) | `consts_gen::READY_FOR_HANDOVER` | generated::generated_files_are_current | tamam |
| `_NAME_RE` (steward.py:158) | `consts_gen::P_NAME_RE` | generated::generated_files_are_current | tamam |
| `_MAX_QUESTION_CHARS` (steward.py:159) | `consts_gen::P_MAX_QUESTION_CHARS` | generated::generated_files_are_current | tamam |
| `QUESTION_MAX_OPTIONS` (steward.py:160) | `consts_gen::QUESTION_MAX_OPTIONS` | generated::generated_files_are_current | tamam |
| `_MAX_OPTION_CHARS` (steward.py:161) | `consts_gen::P_MAX_OPTION_CHARS` | generated::generated_files_are_current | tamam |
| `_MAX_IDEA_CHARS` (steward.py:162) | `consts_gen::P_MAX_IDEA_CHARS` | generated::generated_files_are_current | tamam |
| `_MAX_NOTE_CHARS` (steward.py:163) | `consts_gen::P_MAX_NOTE_CHARS` | generated::generated_files_are_current | tamam |
| `Project` (steward.py:169) | `types::Project` | generated::generated_files_are_current | tamam |
| `normalize_host` (steward.py:189) | `identity::normalize_host` | identity::normalize_host_edges, identity::normalize_host_vectors | tamam |
| `Idea` (steward.py:196) | `types::Idea` | generated::generated_files_are_current | tamam |
| `Question` (steward.py:208) | `types::Question` | generated::generated_files_are_current | tamam |
| `SessionView` (steward.py:233) | `types::SessionView` | generated::generated_files_are_current | tamam |
| `SessionView.project` (steward.py:260) | `types::SessionView::project` | basics::session_view_project | tamam |
| `Action` (steward.py:265) | `types::Action` | generated::generated_files_are_current | tamam |
| `Config` (steward.py:275) | `types::Config` | generated::generated_files_are_current | tamam |
| `MACHINE_KEYS` (steward.py:403) | `consts_gen::MACHINE_KEYS` | generated::generated_files_are_current | tamam |
| `STEWARD_ID_RE` (steward.py:407) | `consts_gen::STEWARD_ID_RE` | generated::generated_files_are_current | tamam |
| `ROLES` (steward.py:408) | `consts_gen::ROLES` | generated::generated_files_are_current | tamam |
| `RESERVED_IDS` (steward.py:409) | `consts_gen::RESERVED_IDS` | generated::generated_files_are_current | tamam |
| `BRAIN_PREFIX` (steward.py:410) | `consts_gen::BRAIN_PREFIX` | generated::generated_files_are_current | tamam |
| `valid_custom_id` (steward.py:413) | `identity::valid_custom_id` | identity::name_rules_edges, identity::valid_custom_id_vectors | tamam |
| `valid_steward_id` (steward.py:419) | `identity::valid_steward_id` | identity::name_rules_edges, identity::valid_steward_id_vectors | tamam |
| `ReviewerRefused` (steward.py:424) | `identity::ReviewerRefused` | identity::error_messages | tamam |
| `reviewer_ids` (steward.py:428) | `identity::reviewer_ids` | identity::reviewers_from_settings | tamam |
| `is_reviewer` (steward.py:440) | `identity::is_reviewer` | identity::reviewers_from_settings | tamam |
| `brain_name_for` (steward.py:446) | `identity::brain_name_for` | identity::brain_name_for_vectors | tamam |
| `steward_title` (steward.py:451) | `identity::steward_title` | identity::steward_title_vectors | tamam |
| `steward_badge` (steward.py:459) | `identity::steward_badge` | identity::badge_edges, identity::steward_badge_vectors | tamam |
| `_now` (steward.py:479) | - | - | kapsam dışı: G/Ç (saat/rastgele kimlik): crate saat ve kimliği parametre alır; T10 uygulama katmanı |
| `_new_id` (steward.py:483) | - | - | kapsam dışı: G/Ç (saat/rastgele kimlik): crate saat ve kimliği parametre alır; T10 uygulama katmanı |
| `valid_name` (steward.py:487) | `identity::valid_name` | identity::name_rules_edges, identity::valid_name_vectors | tamam |
| `_corrupt_backup` (steward.py:493) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `_load_json` (steward.py:501) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `_save_json` (steward.py:515) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `LOCK_TIMEOUT` (steward.py:526) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `_LOCK_POLL` (steward.py:527) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `_HELD` (steward.py:528) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `LockTimeout` (steward.py:531) | `identity::LockTimeout` | identity::error_messages | tamam |
| `OwnedElsewhere` (steward.py:535) | `identity::OwnedElsewhere` | identity::error_messages | tamam |
| `OwnedElsewhere.__init__` (steward.py:537) | `identity::OwnedElsewhere::new` | identity::error_messages | tamam |
| `_flock` (steward.py:544) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `steward_lock` (steward.py:579) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `ownership_lock` (steward.py:584) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `project_owner` (steward.py:590) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `_OWN_CACHE` (steward.py:611) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `ReservedName` (steward.py:614) | `identity::ReservedName` | identity::error_messages | tamam |
| `ReservedName.__init__` (steward.py:616) | `identity::ReservedName::new` | identity::error_messages | tamam |
| `services_path` (steward.py:622) | `identity::services_path` | identity::services_path_vectors | tamam |
| `discover_steward_ids` (steward.py:627) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `_project_meta` (steward.py:638) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `_project_names` (steward.py:657) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `build_ownership_index` (steward.py:661) | `identity::build_ownership_index` | identity::build_ownership_index_vectors, identity::ownership_index_edges_keep_order | tamam |
| `ownership_index` (steward.py:684) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `reserved_reason` (steward.py:697) | `identity::reserved_reason` | identity::reserved_reason_edges, identity::reserved_reason_vectors | tamam |
| `_from_dict` (steward.py:710) | `identity::from_dict` | identity::from_dict_drops_unknown_and_requires | tamam |
| `load_projects` (steward.py:715) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `save_projects` (steward.py:731) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `HostChangeRefused` (steward.py:736) | `store::HostChangeRefused` | store::error_messages | tamam |
| `_HOST_STATE_KEYS` (steward.py:742) | `consts_gen::P_HOST_STATE_KEYS` | generated::generated_files_are_current | tamam |
| `_clear_project_state` (steward.py:745) | `store::clear_project_state` | store::p_clear_project_state | tamam |
| `upsert_project` (steward.py:764) | `store::upsert_project` | store::upsert_project_vectors, store::wrong_field_type_is_rejected_without_changes | tamam |
| `auto_remove_labels` (steward.py:835) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `remove_project` (steward.py:849) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `transfer_project` (steward.py:859) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `load_ideas` (steward.py:922) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `save_ideas` (steward.py:927) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `add_idea` (steward.py:932) | `store::add_idea` | store::add_idea_vectors | tamam |
| `update_idea` (steward.py:944) | `store::update_idea` | store::update_idea_vectors | tamam |
| `record_idea_export` (steward.py:961) | `store::record_idea_export` | store::record_idea_export_vectors | tamam |
| `load_questions` (steward.py:974) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `save_questions` (steward.py:979) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `normalize_options` (steward.py:984) | `questions::normalize_options` | questions::normalize_options_vectors | tamam |
| `resolve_answer` (steward.py:1003) | `questions::resolve_answer` | questions::resolve_answer_vectors | tamam |
| `DEFER_SECONDS` (steward.py:1018) | `consts_gen::DEFER_SECONDS` | generated::generated_files_are_current | tamam |
| `_DEFER_ANSWER_RE` (steward.py:1019) | `consts_gen::P_DEFER_ANSWER_RE` | generated::generated_files_are_current | tamam |
| `is_defer_answer` (steward.py:1024) | `questions::is_defer_answer` | questions::is_defer_answer_vectors | tamam |
| `REASK_WINDOW_SECONDS` (steward.py:1030) | `consts_gen::REASK_WINDOW_SECONDS` | generated::generated_files_are_current | tamam |
| `REASK_MIN_SIMILARITY` (steward.py:1031) | `consts_gen::REASK_MIN_SIMILARITY` | generated::generated_files_are_current | tamam |
| `TOUR_INLINE_MAX_CHARS` (steward.py:1032) | `consts_gen::TOUR_INLINE_MAX_CHARS` | generated::generated_files_are_current | tamam |
| `TOUR_FILES_KEEP` (steward.py:1033) | `consts_gen::TOUR_FILES_KEEP` | generated::generated_files_are_current | tamam |
| `TOUR_MAX_ITEMS` (steward.py:1034) | `consts_gen::TOUR_MAX_ITEMS` | generated::generated_files_are_current | tamam |
| `TOUR_MAX_QUESTION_ITEMS` (steward.py:1035) | `consts_gen::TOUR_MAX_QUESTION_ITEMS` | generated::generated_files_are_current | tamam |
| `ASK_ITEM_CHARS` (steward.py:1036) | `consts_gen::ASK_ITEM_CHARS` | generated::generated_files_are_current | tamam |
| `BRAIN_ASK_PREFIX` (steward.py:1037) | `consts_gen::BRAIN_ASK_PREFIX` | generated::generated_files_are_current | tamam |
| `BLOCKED_ESCALATE_SECONDS` (steward.py:1038) | `consts_gen::BLOCKED_ESCALATE_SECONDS` | generated::generated_files_are_current | tamam |
| `BLOCKED_TEXT_PREFIX` (steward.py:1039) | `consts_gen::BLOCKED_TEXT_PREFIX` | generated::generated_files_are_current | tamam |
| `OWNER_ONLY_TOPICS_TR` (steward.py:1041) | `consts_gen::OWNER_ONLY_TOPICS_TR` | generated::generated_files_are_current | tamam |
| `OWNER_ONLY_TOPICS_EN` (steward.py:1042) | `consts_gen::OWNER_ONLY_TOPICS_EN` | generated::generated_files_are_current | tamam |
| `ROUTINE_ESCALATE_SECONDS` (steward.py:1043) | `consts_gen::ROUTINE_ESCALATE_SECONDS` | generated::generated_files_are_current | tamam |
| `REASK_MAX_REPEATS` (steward.py:1044) | `consts_gen::REASK_MAX_REPEATS` | generated::generated_files_are_current | tamam |
| `_WORD_RE` (steward.py:1045) | `consts_gen::P_WORD_RE` | generated::generated_files_are_current | tamam |
| `_words` (steward.py:1048) | `questions::words` | questions::p_words | tamam |
| `_SALIENT_RE` (steward.py:1052) | `consts_gen::P_SALIENT_RE` | generated::generated_files_are_current | tamam |
| `SALIENT_MIN_TOKENS` (steward.py:1053) | `consts_gen::SALIENT_MIN_TOKENS` | generated::generated_files_are_current | tamam |
| `_salient` (steward.py:1056) | `questions::salient` | questions::p_salient | tamam |
| `_TOPIC_BT_RE` (steward.py:1064) | `consts_gen::P_TOPIC_BT_RE` | generated::generated_files_are_current | tamam |
| `_TOPIC_CODE_RE` (steward.py:1065) | `consts_gen::P_TOPIC_CODE_RE` | generated::generated_files_are_current | tamam |
| `_TOPIC_CAP_RE` (steward.py:1066) | `consts_gen::P_TOPIC_CAP_RE` | generated::generated_files_are_current | tamam |
| `_TOPIC_CAP_STOP` (steward.py:1067) | `consts_gen::P_TOPIC_CAP_STOP` | generated::generated_files_are_current | tamam |
| `TOPIC_MIN_OVERLAP` (steward.py:1069) | `consts_gen::TOPIC_MIN_OVERLAP` | generated::generated_files_are_current | tamam |
| `TOPIC_PREV_KEEP` (steward.py:1070) | `consts_gen::TOPIC_PREV_KEEP` | generated::generated_files_are_current | tamam |
| `MAX_OPEN_QUESTIONS_PER_PROJECT` (steward.py:1071) | `consts_gen::MAX_OPEN_QUESTIONS_PER_PROJECT` | generated::generated_files_are_current | tamam |
| `EXTRA_TEXTS_KEEP` (steward.py:1072) | `consts_gen::EXTRA_TEXTS_KEEP` | generated::generated_files_are_current | tamam |
| `_BARE_CHOICE_RE` (steward.py:1073) | `consts_gen::P_BARE_CHOICE_RE` | generated::generated_files_are_current | tamam |
| `TOPIC_OPEN_WINDOW_SECONDS` (steward.py:1074) | `consts_gen::TOPIC_OPEN_WINDOW_SECONDS` | generated::generated_files_are_current | tamam |
| `TOPIC_HOLD_WINDOW_SECONDS` (steward.py:1075) | `consts_gen::TOPIC_HOLD_WINDOW_SECONDS` | generated::generated_files_are_current | tamam |
| `HOLD_ANSWER_RE` (steward.py:1077) | `consts_gen::HOLD_ANSWER_RE` | generated::generated_files_are_current | tamam |
| `topic_tokens` (steward.py:1081) | `questions::topic_tokens` | questions::topic_tokens_vectors | tamam |
| `_strong_topic` (steward.py:1096) | `questions::strong_topic` | questions::p_strong_topic | tamam |
| `topic_match` (steward.py:1100) | `questions::topic_match` | questions::topic_match_vectors | tamam |
| `SIMILAR_MIN_SCORE` (steward.py:1114) | `consts_gen::SIMILAR_MIN_SCORE` | generated::generated_files_are_current | tamam |
| `similar_answers` (steward.py:1117) | `questions::similar_answers` | questions::similar_answers_vectors | tamam |
| `find_answered_duplicate` (steward.py:1144) | `questions::find_answered_duplicate` | questions::find_answered_duplicate_vectors | tamam |
| `OPEN_MERGE_WINDOW_SECONDS` (steward.py:1173) | `consts_gen::OPEN_MERGE_WINDOW_SECONDS` | generated::generated_files_are_current | tamam |
| `OPEN_MERGE_MIN_WORDS` (steward.py:1174) | `consts_gen::OPEN_MERGE_MIN_WORDS` | generated::generated_files_are_current | tamam |
| `find_open_similar` (steward.py:1177) | `questions::find_open_similar` | questions::find_open_similar_vectors | tamam |
| `find_open_topic` (steward.py:1202) | `questions::find_open_topic` | questions::find_open_topic_vectors | tamam |
| `_PAUSED_SWEEP_RE` (steward.py:1221) | `consts_gen::P_PAUSED_SWEEP_RE` | generated::generated_files_are_current | tamam |
| `_COUNT_RE` (steward.py:1223) | `consts_gen::P_COUNT_RE` | generated::generated_files_are_current | tamam |
| `SAME_SENTENCE_MIN_SIMILARITY` (steward.py:1224) | `consts_gen::SAME_SENTENCE_MIN_SIMILARITY` | generated::generated_files_are_current | tamam |
| `paused_sweep_text` (steward.py:1227) | `questions::paused_sweep_text` | questions::paused_sweep_text_vectors | tamam |
| `_question_sentences` (steward.py:1231) | `questions::question_sentences` | questions::p_question_sentences | tamam |
| `find_open_same_ask` (steward.py:1242) | `questions::find_open_same_ask` | questions::find_open_same_ask_vectors | tamam |
| `find_answered_hold` (steward.py:1269) | `questions::find_answered_hold` | questions::find_answered_hold_vectors | tamam |
| `recent_answers` (steward.py:1291) | `questions::recent_answers` | questions::recent_answers_vectors | tamam |
| `_unique_question_key` (steward.py:1300) | - | - | kapsam dışı: G/Ç (saat/rastgele kimlik): crate saat ve kimliği parametre alır; T10 uygulama katmanı |
| `_MAX_DETAIL_CHARS` (steward.py:1313) | `consts_gen::P_MAX_DETAIL_CHARS` | generated::generated_files_are_current | tamam |
| `add_question_ex` (steward.py:1316) | `store::add_question_ex` | store::add_question_ex_vectors | tamam |
| `set_question_detail` (steward.py:1394) | `store::set_question_detail` | store::set_question_detail_vectors | tamam |
| `add_question` (steward.py:1409) | `store::add_question` | store::add_question_vectors | tamam |
| `ANSWERED_BY` (steward.py:1415) | `consts_gen::ANSWERED_BY` | generated::generated_files_are_current | tamam |
| `ON_BEHALF_PREFIX` (steward.py:1416) | `consts_gen::ON_BEHALF_PREFIX` | generated::generated_files_are_current | tamam |
| `answer_question` (steward.py:1419) | `store::answer_question` | store::answer_question_vectors | tamam |
| `set_answered_by` (steward.py:1463) | `store::set_answered_by` | store::set_answered_by_vectors | tamam |
| `apply_review_where_answer` (steward.py:1479) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `find_question` (steward.py:1501) | `questions::find_question` | questions::find_question_vectors | tamam |
| `mark_notified` (steward.py:1505) | `store::mark_notified` | store::mark_notified_vectors | tamam |
| `question_link` (steward.py:1514) | `notify::question_link` | notify::question_link_vectors | tamam |
| `ask_hint` (steward.py:1523) | `notify::ask_hint` | notify::ask_hint_vectors | tamam |
| `ask_prefix` (steward.py:1528) | `notify::ask_prefix` | notify::ask_prefix_vectors | tamam |
| `PENDING_DIGEST_HOURS` (steward.py:1536) | `consts_gen::PENDING_DIGEST_HOURS` | generated::generated_files_are_current | tamam |
| `pending_digest_slot` (steward.py:1539) | `notify::pending_digest_slot` | notify::pending_digest_slot_vectors | tamam |
| `pending_digest_text` (steward.py:1546) | `notify::pending_digest_text` | notify::pending_digest_text_vectors | tamam |
| `question_notification` (steward.py:1565) | `notify::question_notification` | notify::question_notification_vectors | tamam |
| `_QPAGE_TXT` (steward.py:1576) | `consts_gen::P_QPAGE_TXT` | generated::generated_files_are_current | tamam |
| `_QPAGE_CSS` (steward.py:1589) | `consts_gen::P_QPAGE_CSS` | generated::generated_files_are_current | tamam |
| `question_page_html` (steward.py:1605) | `notify::question_page_html` | notify::question_page_html_vectors | tamam |
| `escalate_routine` (steward.py:1649) | `store::escalate_routine` | store::escalate_routine_vectors | tamam |
| `mark_delivered` (steward.py:1663) | `store::mark_delivered` | store::mark_delivered_vectors | tamam |
| `_TBD_ID_RE` (steward.py:1672) | `consts_gen::P_TBD_ID_RE` | generated::generated_files_are_current | tamam |
| `_ITEM_START_RE` (steward.py:1673) | `consts_gen::P_ITEM_START_RE` | generated::generated_files_are_current | tamam |
| `tbd_insert_answer` (steward.py:1676) | `inserts::tbd_insert_answer` | inserts::tbd_insert_answer_vectors | tamam |
| `answer_has_action` (steward.py:1706) | `inserts::answer_has_action` | inserts::answer_has_action_vectors | tamam |
| `todo_insert_directive` (steward.py:1713) | `inserts::todo_insert_directive` | inserts::todo_insert_directive_vectors | tamam |
| `todo_insert_answer` (steward.py:1724) | `inserts::todo_insert_answer` | inserts::todo_insert_answer_vectors | tamam |
| `mark_undeliverable` (steward.py:1733) | `store::mark_undeliverable` | store::mark_undeliverable_vectors | tamam |
| `open_questions` (steward.py:1749) | `questions::open_questions` | questions::open_questions_vectors | tamam |
| `HANDOVER_QUESTIONS_MAX` (steward.py:1753) | `consts_gen::HANDOVER_QUESTIONS_MAX` | generated::generated_files_are_current | tamam |
| `HANDOVER_QUESTION_CHARS` (steward.py:1754) | `consts_gen::HANDOVER_QUESTION_CHARS` | generated::generated_files_are_current | tamam |
| `handover_questions_note` (steward.py:1757) | `notify::handover_questions_note` | notify::handover_questions_note_vectors | tamam |
| `undelivered_answers` (steward.py:1786) | `questions::undelivered_answers` | questions::undelivered_answers_vectors | tamam |
| `load_state` (steward.py:1791) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `save_state` (steward.py:1796) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `_LOG_LOCK` (steward.py:1801) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `LOG_MAX_BYTES` (steward.py:1802) | `consts_gen::LOG_MAX_BYTES` | generated::generated_files_are_current | tamam |
| `SUMMARY_CATCHUP_DAYS` (steward.py:1803) | `consts_gen::SUMMARY_CATCHUP_DAYS` | generated::generated_files_are_current | tamam |
| `_log_guard` (steward.py:1807) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `LOG_DEDUP_SECONDS` (steward.py:1825) | `consts_gen::LOG_DEDUP_SECONDS` | generated::generated_files_are_current | tamam |
| `LOG_DEDUP_EXEMPT` (steward.py:1826) | `consts_gen::LOG_DEDUP_EXEMPT` | generated::generated_files_are_current | tamam |
| `_LOG_SEEN` (steward.py:1827) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `_log_dedup` (steward.py:1830) | `logdedup::log_dedup` | logdedup::old_subjects_are_evicted_past_the_cap, logdedup::p_log_dedup | tamam |
| `log_event` (steward.py:1856) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `_rewrite_log` (steward.py:1876) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `compact_log` (steward.py:1881) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `rotate_log` (steward.py:1921) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `tail_log` (steward.py:1935) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `card_path` (steward.py:1957) | `cards::card_path` | cards::card_path_vectors | tamam |
| `_read_doc_head` (steward.py:1961) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `_git_recent` (steward.py:1969) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `build_raw_card` (steward.py:1996) | - | - | kapsam dışı: G/Ç sarmalayıcı (depodan okuyup yazan işlem): T10 uygulama katmanı |
| `raw_card_from_docs` (steward.py:2014) | `cards::raw_card_from_docs` | cards::raw_card_from_docs_vectors | tamam |
| `_short` (steward.py:2024) | `cards::short` | cards::p_short | tamam |
| `_str_list` (steward.py:2028) | `cards::str_list` | cards::p_str_list | tamam |
| `_tbd_lines` (steward.py:2037) | `cards::tbd_lines` | cards::p_tbd_lines | tamam |
| `_goal_from_docs` (steward.py:2049) | `cards::goal_from_docs` | cards::p_goal_from_docs | tamam |
| `raw_card_fields` (steward.py:2057) | `cards::raw_card_fields` | cards::raw_card_fields_vectors | tamam |
| `parse_card_json` (steward.py:2071) | `cards::parse_card_json` | cards::parse_card_json_vectors | tamam |
| `build_card_prompt` (steward.py:2104) | `cards::build_card_prompt` | cards::build_card_prompt_vectors | tamam |
| `pick_card_model` (steward.py:2142) | `cards::pick_card_model` | cards::pick_card_model_vectors | tamam |
| `make_card` (steward.py:2151) | `cards::make_card` | store::make_card_vectors | tamam |
| `BRAIN_PAUSE_RECENT_SECONDS` (steward.py:2172) | `consts_gen::BRAIN_PAUSE_RECENT_SECONDS` | generated::generated_files_are_current | tamam |
| `brain_pause_verdict` (steward.py:2175) | `cards::brain_pause_verdict` | cards::brain_pause_verdict_vectors | tamam |
| `load_card` (steward.py:2196) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `save_card` (steward.py:2201) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `load_cards` (steward.py:2205) | - | - | kapsam dışı: G/Ç (dosya deposu, kilit, DB aynası): rs/state (cops-state) + T10 |
| `mark_card_stale` (steward.py:2219) | `cards::mark_card_stale` | store::mark_card_stale_vectors | tamam |
| `card_refresh_reason` (steward.py:2229) | `cards::card_refresh_reason` | cards::card_refresh_reason_vectors | tamam |
| `note_card_failure` (steward.py:2248) | `cards::note_card_failure` | store::note_card_failure_vectors | tamam |
| `card_one_liner` (steward.py:2259) | `cards::card_one_liner` | cards::card_one_liner_vectors | tamam |
| `persona_text` (steward.py:2265) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `_unwrap_ticks` (steward.py:2278) | `markers::unwrap_ticks` | markers::p_unwrap_ticks | tamam |
| `_PLACEHOLDER_BODY_RE` (steward.py:2291) | `consts_gen::P_PLACEHOLDER_BODY_RE` | generated::generated_files_are_current | tamam |
| `count_open_tbd` (steward.py:2294) | `markers::count_open_tbd` | markers::count_open_tbd_edges, markers::count_open_tbd_vectors | tamam |
| `done_blocked` (steward.py:2313) | `markers::done_blocked` | markers::done_blocked_vectors | tamam |
| `_bare_marker` (steward.py:2319) | `markers::bare_marker` | markers::p_bare_marker | tamam |
| `_is_confirm_line` (steward.py:2337) | `markers::is_confirm_line` | markers::is_confirm_line_vectors | tamam |
| `scan_markers` (steward.py:2350) | `markers::scan_markers` | markers::scan_markers_corpus, markers::scan_markers_vectors | tamam |
| `_PROTOCOL_TR` (steward.py:2418) | `consts_gen::P_PROTOCOL_TR` | generated::generated_files_are_current | tamam |
| `_PROTOCOL_EN` (steward.py:2454) | `consts_gen::P_PROTOCOL_EN` | generated::generated_files_are_current | tamam |
| `REPLY_LANG_TR` (steward.py:2489) | `consts_gen::REPLY_LANG_TR` | generated::generated_files_are_current | tamam |
| `REPLY_LANG_EN` (steward.py:2490) | `consts_gen::REPLY_LANG_EN` | generated::generated_files_are_current | tamam |
| `LANG_FIX_TEXT_TR` (steward.py:2491) | `consts_gen::LANG_FIX_TEXT_TR` | generated::generated_files_are_current | tamam |
| `LANG_FIX_TEXT_EN` (steward.py:2492) | `consts_gen::LANG_FIX_TEXT_EN` | generated::generated_files_are_current | tamam |
| `LANG_FIX_COOLDOWN_SECONDS` (steward.py:2493) | `consts_gen::LANG_FIX_COOLDOWN_SECONDS` | generated::generated_files_are_current | tamam |
| `_TR_WORDS` (steward.py:2495) | `consts_gen::P_TR_WORDS` | generated::generated_files_are_current | tamam |
| `_EN_WORDS` (steward.py:2496) | `consts_gen::P_EN_WORDS` | generated::generated_files_are_current | tamam |
| `_DE_WORDS` (steward.py:2497) | `consts_gen::P_DE_WORDS` | generated::generated_files_are_current | tamam |
| `reply_language_line` (steward.py:2500) | `markers::reply_language_line` | markers::reply_language_line_vectors | tamam |
| `text_lang_mismatch` (steward.py:2504) | `markers::text_lang_mismatch` | markers::text_lang_mismatch_edges, markers::text_lang_mismatch_vectors | tamam |
| `marker_texts` (steward.py:2519) | `markers::marker_texts` | markers::marker_texts_vectors | tamam |
| `lang_fix_action` (steward.py:2530) | `markers::lang_fix_action` | markers::lang_fix_action_state_handling, markers::lang_fix_action_vectors | tamam |
| `build_directive` (steward.py:2543) | `prompts::build_directive` | prompts::build_directive_vectors | tamam |
| `_clip` (steward.py:2624) | `prompts::clip` | prompts::p_clip | tamam |
| `card_lines` (steward.py:2631) | `prompts::card_lines` | prompts::card_lines_vectors | tamam |
| `build_tour_prompt` (steward.py:2652) | `prompts::build_tour_prompt` | prompts::build_tour_prompt_vectors | tamam |
| `MODEL_RULE_TR` (steward.py:2754) | `consts_gen::MODEL_RULE_TR` | generated::generated_files_are_current | tamam |
| `MODEL_RULE_EN` (steward.py:2789) | `consts_gen::MODEL_RULE_EN` | generated::generated_files_are_current | tamam |
| `identity_section` (steward.py:2827) | `prompts::identity_section` | prompts::identity_section_vectors | tamam |
| `MEMORY_TR` (steward.py:2848) | `consts_gen::MEMORY_TR` | generated::generated_files_are_current | tamam |
| `MEMORY_EN` (steward.py:2854) | `consts_gen::MEMORY_EN` | generated::generated_files_are_current | tamam |
| `REMOTE_NOTE_TR` (steward.py:2861) | `consts_gen::REMOTE_NOTE_TR` | generated::generated_files_are_current | tamam |
| `REMOTE_NOTE_EN` (steward.py:2866) | `consts_gen::REMOTE_NOTE_EN` | generated::generated_files_are_current | tamam |
| `build_workspace_claude_md` (steward.py:2874) | `prompts::build_workspace_claude_md` | prompts::build_workspace_claude_md_vectors | tamam |
| `_is_project_session` (steward.py:2927) | `prompts::is_project_session` | prompts::p_is_project_session | tamam |
| `phase_model_effort` (steward.py:2931) | `prompts::phase_model_effort` | prompts::phase_model_effort_vectors | tamam |
| `main_session_model_effort` (steward.py:2940) | `prompts::main_session_model_effort` | prompts::main_session_model_effort_vectors | tamam |
| `SKIP_QUIET_SECONDS` (steward.py:2952) | `consts_gen::SKIP_QUIET_SECONDS` | generated::generated_files_are_current | tamam |
| `STALE_ANSWER_SECONDS` (steward.py:2953) | `consts_gen::STALE_ANSWER_SECONDS` | generated::generated_files_are_current | tamam |
| `BLOCKED_MAX_TOURS` (steward.py:2954) | `consts_gen::BLOCKED_MAX_TOURS` | generated::generated_files_are_current | tamam |
| `item_signature` (steward.py:2957) | `prompts::item_signature` | prompts::item_signature_vectors | tamam |
| `stale_answers` (steward.py:2969) | `prompts::stale_answers` | prompts::stale_answers_vectors | tamam |
| `NOTE_PID_RE` (steward.py:2986) | `consts_gen::NOTE_PID_RE` | generated::generated_files_are_current | tamam |
| `NOTE_GATE_RE` (steward.py:2987) | `consts_gen::NOTE_GATE_RE` | generated::generated_files_are_current | tamam |
| `note_claims` (steward.py:2990) | `prompts::note_claims` | prompts::note_claims_vectors | tamam |
| `check_note_claims` (steward.py:2996) | `prompts::check_note_claims` | prompts::check_note_claims_branches, prompts::check_note_claims_vectors | tamam |
| `cut_tour_items` (steward.py:3015) | `prompts::cut_tour_items` | prompts::cut_tour_items_vectors | tamam |
| `mark_ask_seen` (steward.py:3027) | `prompts::mark_ask_seen` | prompts::mark_ask_seen_vectors | tamam |
| `review_items` (steward.py:3038) | `tour::review_items` | tour::review_items_vectors | tamam |
| `OWNER_TODO_LINE_RE` (steward.py:3127) | `consts_gen::OWNER_TODO_LINE_RE` | generated::generated_files_are_current | tamam |
| `TODO_TRIAGE_TEXT` (steward.py:3128) | `consts_gen::TODO_TRIAGE_TEXT` | generated::generated_files_are_current | tamam |
| `OWNER_TODO_MOVE_SECONDS` (steward.py:3131) | `consts_gen::OWNER_TODO_MOVE_SECONDS` | generated::generated_files_are_current | tamam |
| `OWNER_WAIT_LINE_RE` (steward.py:3132) | `consts_gen::OWNER_WAIT_LINE_RE` | generated::generated_files_are_current | tamam |
| `BRAIN_STOP_COOLDOWN_SECONDS` (steward.py:3134) | `consts_gen::BRAIN_STOP_COOLDOWN_SECONDS` | generated::generated_files_are_current | tamam |
| `DERIVED_TAIL_RE` (steward.py:3137) | `consts_gen::DERIVED_TAIL_RE` | generated::generated_files_are_current | tamam |
| `derived_of` (steward.py:3140) | `identity::derived_of` | identity::derived_of_vectors | tamam |
| `_project_key` (steward.py:3147) | `identity::project_key` | identity::p_project_key | tamam |
| `_DENY` (steward.py:3159) | `consts_gen::P_DENY` | generated::generated_files_are_current | tamam |
| `World` (steward.py:3163) | `types::World` | generated::generated_files_are_current | tamam |
| `World.start_held` (steward.py:3183) | `world::World::start_held` | world::world_start_held | tamam |
| `World.host_of` (steward.py:3187) | `world::World::host_of` | world::world_host_of | tamam |
| `World.owner_of` (steward.py:3191) | `world::World::owner_of` | world::world_owner_of | tamam |
| `World.owns` (steward.py:3195) | `world::World::owns` | world::world_owns | tamam |
| `World.own_projects` (steward.py:3198) | `world::World::own_projects` | world::world_own_projects | tamam |
| `World._owner_tag` (steward.py:3202) | `world::World::owner_tag` | world::world_p_owner_tag | tamam |
| `World.resolve` (steward.py:3205) | `world::World::resolve` | world::world_resolve | tamam |
| `World._class` (steward.py:3224) | `world::World::class` | world::world_p_class | tamam |
| `World.name_class` (steward.py:3236) | `world::World::name_class` | world::world_name_class | tamam |
| `World.session_class` (steward.py:3240) | `world::World::session_class` | world::world_session_class | tamam |
| `World.owned_key` (steward.py:3262) | `world::World::owned_key` | world::world_owned_key | tamam |
| `World.is_manual` (steward.py:3268) | `world::World::is_manual` | world::world_is_manual | tamam |
| `World.project_key` (steward.py:3274) | `world::World::project_key` | world::world_project_key | tamam |
| `world_for` (steward.py:3280) | `world::world_for` | world::world_for_vectors | tamam |
| `OWNED_EVIDENCE_EVENTS` (steward.py:3294) | `consts_gen::OWNED_EVIDENCE_EVENTS` | generated::generated_files_are_current | tamam |
| `_OWNED_EVIDENCE_KINDS` (steward.py:3295) | `consts_gen::P_OWNED_EVIDENCE_KINDS` | generated::generated_files_are_current | tamam |
| `owned_evidence` (steward.py:3298) | `world::owned_evidence` | world::owned_evidence_vectors | tamam |
| `update_owned` (steward.py:3323) | `world::update_owned` | world::update_owned_vectors | tamam |
| `select_rows` (steward.py:3357) | `world::select_rows` | world::select_rows_vectors | tamam |
| `_sibling_running` (steward.py:3382) | `world::sibling_running` | world::p_sibling_running | tamam |
| `plan_deliveries` (steward.py:3396) | `world::plan_deliveries` | world::plan_deliveries_vectors | tamam |
| `pick_delivery_view` (steward.py:3421) | `world::pick_delivery_view` | world::pick_delivery_view_vectors | tamam |
| `context_threshold` (steward.py:3433) | `closing::context_threshold` | closing::context_threshold_vectors | tamam |
| `handover_defer_decision` (steward.py:3440) | `closing::handover_defer_decision` | closing::handover_defer_decision_vectors | tamam |
| `SHUTDOWN_QUIET_SECONDS` (steward.py:3461) | `consts_gen::SHUTDOWN_QUIET_SECONDS` | generated::generated_files_are_current | tamam |
| `SHUTDOWN_WAIT_MAX_SECONDS` (steward.py:3462) | `consts_gen::SHUTDOWN_WAIT_MAX_SECONDS` | generated::generated_files_are_current | tamam |
| `SHUTDOWN_HO_MAX_SECONDS` (steward.py:3463) | `consts_gen::SHUTDOWN_HO_MAX_SECONDS` | generated::generated_files_are_current | tamam |
| `SHUTDOWN_ACTION_FAIL_MAX` (steward.py:3464) | `consts_gen::SHUTDOWN_ACTION_FAIL_MAX` | generated::generated_files_are_current | tamam |
| `_SD_TERMINAL` (steward.py:3465) | `consts_gen::P_SD_TERMINAL` | generated::generated_files_are_current | tamam |
| `shutdown_note_result` (steward.py:3468) | `closing::shutdown_note_result` | closing::bad_state_types_are_errors, closing::shutdown_note_result_vectors | tamam |
| `plan_shutdown` (steward.py:3489) | `closing::plan_shutdown` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors | tamam |
| `plan_shutdown._is_own` (steward.py:3506) | `closing::plan_shutdown (içinde)` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors | tamam |
| `plan_shutdown._step` (steward.py:3523) | `closing::plan_shutdown (içinde)` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors | tamam |
| `_CTX_Q_SESSION_RE` (steward.py:3571) | `consts_gen::P_CTX_Q_SESSION_RE` | generated::generated_files_are_current | tamam |
| `_CTX_Q_HANDOVER_RE` (steward.py:3572) | `consts_gen::P_CTX_Q_HANDOVER_RE` | generated::generated_files_are_current | tamam |
| `_CTX_Q_EXCLUDE_RE` (steward.py:3573) | `consts_gen::P_CTX_Q_EXCLUDE_RE` | generated::generated_files_are_current | tamam |
| `is_context_question` (steward.py:3576) | `closing::is_context_question` | closing::is_context_question_vectors, gates::long_texts_stay_within_regex_limits | tamam |
| `context_answer` (steward.py:3582) | `closing::context_answer` | closing::context_answer_vectors | tamam |
| `tour_delivery` (steward.py:3596) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `SLOT_RECENT_SECONDS` (steward.py:3619) | `consts_gen::SLOT_RECENT_SECONDS` | generated::generated_files_are_current | tamam |
| `DIRECTIVE_MIN_GAP_SECONDS` (steward.py:3620) | `consts_gen::DIRECTIVE_MIN_GAP_SECONDS` | generated::generated_files_are_current | tamam |
| `OWNER_ONLY_RE` (steward.py:3625) | `consts_gen::OWNER_ONLY_RE` | generated::generated_files_are_current | tamam |
| `_JOB_RED_RE` (steward.py:3628) | `consts_gen::P_JOB_RED_RE` | generated::generated_files_are_current | tamam |
| `JOB_RED_MIN_CHARS` (steward.py:3629) | `consts_gen::JOB_RED_MIN_CHARS` | generated::generated_files_are_current | tamam |
| `panic_path` (steward.py:3632) | `gates::panic_path` | gates::panic_path_is_under_default_root | tamam |
| `panic_active` (steward.py:3637) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `set_panic` (steward.py:3641) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `job_request_gate` (steward.py:3654) | `gates::job_request_gate` | gates::bad_values_are_errors, gates::job_request_gate_vectors | tamam |
| `READONLY_JOB_KINDS` (steward.py:3673) | `consts_gen::READONLY_JOB_KINDS` | generated::generated_files_are_current | tamam |
| `is_readonly_job_request` (steward.py:3676) | `gates::is_readonly_job_request` | gates::is_readonly_job_request_vectors | tamam |
| `brain_may_answer` (steward.py:3684) | `gates::brain_may_answer` | gates::brain_may_answer_vectors, gates::long_texts_stay_within_regex_limits | tamam |
| `owner_pending_block` (steward.py:3694) | `gates::owner_pending_block` | gates::owner_pending_block_vectors | tamam |
| `directive_defer_reason` (steward.py:3706) | `gates::directive_defer_reason` | gates::directive_defer_reason_vectors | tamam |
| `GENERIC_MODEL` (steward.py:3718) | `consts_gen::GENERIC_MODEL` | generated::generated_files_are_current | tamam |
| `GENERIC_EFFORT` (steward.py:3719) | `consts_gen::GENERIC_EFFORT` | generated::generated_files_are_current | tamam |
| `UPPER_MODEL_RE` (steward.py:3720) | `consts_gen::UPPER_MODEL_RE` | generated::generated_files_are_current | tamam |
| `UPPER_EFFORTS` (steward.py:3721) | `consts_gen::UPPER_EFFORTS` | generated::generated_files_are_current | tamam |
| `UPPER_MODEL_SOURCE` (steward.py:3722) | `consts_gen::UPPER_MODEL_SOURCE` | generated::generated_files_are_current | tamam |
| `APPROVE_WORDS` (steward.py:3723) | `consts_gen::APPROVE_WORDS` | generated::generated_files_are_current | tamam |
| `GENERIC_BACKLOG_ITEMS` (steward.py:3724) | `consts_gen::GENERIC_BACKLOG_ITEMS` | generated::generated_files_are_current | tamam |
| `_TODO_DONE_RE` (steward.py:3725) | `consts_gen::P_TODO_DONE_RE` | generated::generated_files_are_current | tamam |
| `_TBD_DECIDED_RE` (steward.py:3726) | `consts_gen::P_TBD_DECIDED_RE` | generated::generated_files_are_current | tamam |
| `is_generic` (steward.py:3729) | `generic::is_generic` | gates::is_generic_vectors | tamam |
| `is_upper_tier` (steward.py:3733) | `generic::is_upper_tier` | gates::is_upper_tier_vectors | tamam |
| `is_claude_model` (steward.py:3738) | `generic::is_claude_model` | gates::is_claude_model_vectors | tamam |
| `upper_main_views` (steward.py:3744) | `generic::upper_main_views` | gates::upper_main_views_vectors | tamam |
| `upper_main_text` (steward.py:3769) | `generic::upper_main_text` | gates::upper_main_text_vectors | tamam |
| `upper_tier_tag` (steward.py:3783) | `generic::upper_tier_tag` | gates::upper_tier_tag_vectors | tamam |
| `upper_tier_question_text` (steward.py:3788) | `generic::upper_tier_question_text` | gates::upper_tier_question_text_vectors | tamam |
| `upper_tier_approved` (steward.py:3797) | `generic::upper_tier_approved` | gates::upper_tier_approved_vectors | tamam |
| `generic_backlog` (steward.py:3807) | `generic::generic_backlog` | gates::generic_backlog_vectors | tamam |
| `generic_backlog._add` (steward.py:3815) | `generic::generic_backlog (içinde)` | gates::generic_backlog_vectors | tamam |
| `GENERIC_RULE_TR` (steward.py:3837) | `consts_gen::GENERIC_RULE_TR` | generated::generated_files_are_current | tamam |
| `GENERIC_RULE_EN` (steward.py:3853) | `consts_gen::GENERIC_RULE_EN` | generated::generated_files_are_current | tamam |
| `_JOB_KIND_RE` (steward.py:3871) | `consts_gen::P_JOB_KIND_RE` | generated::generated_files_are_current | tamam |
| `_JOB_STATUS_NOTE_RE` (steward.py:3873) | `consts_gen::P_JOB_STATUS_NOTE_RE` | generated::generated_files_are_current | tamam |
| `JOB_NOTE_TEXT` (steward.py:3875) | `consts_gen::JOB_NOTE_TEXT` | generated::generated_files_are_current | tamam |
| `job_marker_verdict` (steward.py:3879) | `gates::job_marker_verdict` | gates::job_marker_verdict_vectors | tamam |
| `_ASK_STATUS_RE` (steward.py:3898) | `consts_gen::P_ASK_STATUS_RE` | generated::generated_files_are_current | tamam |
| `_ask_is_status_line` (steward.py:3901) | `gates::ask_is_status_line` | gates::p_ask_is_status_line | tamam |
| `_DATED_NAME_RE` (steward.py:3908) | `consts_gen::P_DATED_NAME_RE` | generated::generated_files_are_current | tamam |
| `_ask_base` (steward.py:3911) | `tour::ask_base` | tour::p_ask_base | tamam |
| `start_decision_event` (steward.py:3918) | `tour::start_decision_event` | tour::bad_state_types_are_errors, tour::start_decision_event_vectors | tamam |
| `marker_record_actions` (steward.py:3934) | `tour::marker_record_actions` | tour::marker_record_actions_vectors | tamam |
| `note_project_next` (steward.py:3963) | `tour::note_project_next` | tour::bad_state_types_are_errors, tour::note_project_next_vectors | tamam |
| `plan_markers` (steward.py:3976) | `tour::plan_markers` | tour::bad_state_types_are_errors, tour::plan_markers_vectors | tamam |
| `holds_total_slot` (steward.py:4005) | `world::holds_total_slot` | world::holds_total_slot_vectors | tamam |
| `DONE_CONFIRM_TEXT_TR` (steward.py:4018) | `consts_gen::DONE_CONFIRM_TEXT_TR` | generated::generated_files_are_current | tamam |
| `DONE_CONFIRM_TEXT_EN` (steward.py:4021) | `consts_gen::DONE_CONFIRM_TEXT_EN` | generated::generated_files_are_current | tamam |
| `BRAIN_MCP_FILE` (steward.py:4027) | `consts_gen::BRAIN_MCP_FILE` | generated::generated_files_are_current | tamam |
| `BRAIN_MCP_RESTART_COOLDOWN` (steward.py:4028) | `consts_gen::BRAIN_MCP_RESTART_COOLDOWN` | generated::generated_files_are_current | tamam |
| `BRAIN_NOTOOLS_MIN_AGE` (steward.py:4029) | `consts_gen::BRAIN_NOTOOLS_MIN_AGE` | generated::generated_files_are_current | tamam |
| `_NO_TOOLS_RE` (steward.py:4030) | `consts_gen::P_NO_TOOLS_RE` | generated::generated_files_are_current | tamam |
| `brain_mcp_path` (steward.py:4036) | `gates::brain_mcp_path` | gates::brain_mcp_path_vectors | tamam |
| `read_brain_mcp` (steward.py:4040) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `touch_brain_mcp` (steward.py:4050) | - | - | kapsam dışı: G/Ç (proje/beyin dosyaları, alt süreç): T10 uygulama katmanı |
| `brain_tools_missing_text` (steward.py:4066) | `gates::brain_tools_missing_text` | gates::brain_tools_missing_text_vectors | tamam |
| `brain_notools_verdict` (steward.py:4071) | `gates::brain_notools_verdict` | gates::brain_notools_verdict_vectors | tamam |
| `DONE_ANSWER_TTL` (steward.py:4086) | `consts_gen::DONE_ANSWER_TTL` | generated::generated_files_are_current | tamam |
| `_DONE_NO_RE` (steward.py:4087) | `consts_gen::P_DONE_NO_RE` | generated::generated_files_are_current | tamam |
| `_DONE_HEDGE_RE` (steward.py:4089) | `consts_gen::P_DONE_HEDGE_RE` | generated::generated_files_are_current | tamam |
| `_DONE_YES_RE` (steward.py:4091) | `consts_gen::P_DONE_YES_RE` | generated::generated_files_are_current | tamam |
| `done_conflict_answer` (steward.py:4094) | `closing::done_conflict_answer` | closing::done_conflict_answer_vectors | tamam |
| `_confirm_action` (steward.py:4110) | `closing::confirm_action` | closing::p_confirm_action | tamam |
| `_WRAP_UP_RE` (steward.py:4116) | `consts_gen::P_WRAP_UP_RE` | generated::generated_files_are_current | tamam |
| `_WRAP_UP_ACT_RE` (steward.py:4117) | `consts_gen::P_WRAP_UP_ACT_RE` | generated::generated_files_are_current | tamam |
| `PAUSE_CLOSE_EXPIRE_SECONDS` (steward.py:4118) | `consts_gen::PAUSE_CLOSE_EXPIRE_SECONDS` | generated::generated_files_are_current | tamam |
| `is_wrap_up_directive` (steward.py:4121) | `closing::is_wrap_up_directive` | closing::is_wrap_up_directive_vectors | tamam |
| `directive_keeps_phase` (steward.py:4128) | `closing::directive_keeps_phase` | closing::directive_keeps_phase_vectors | tamam |
| `request_pause_close` (steward.py:4133) | `closing::request_pause_close` | closing::bad_state_types_are_errors, closing::request_pause_close_vectors | tamam |
| `plan_tick` (steward.py:4140) | - | - | EKSİK |
| `plan_tick._mine` (steward.py:4169) | - | - | EKSİK |
| `plan_tick._unavail` (steward.py:4187) | - | - | EKSİK |
| `plan_tick._managed` (steward.py:4192) | - | - | EKSİK |
| `plan_tick._threshold_handover` (steward.py:4207) | - | - | EKSİK |
| `plan_tick._halted_phase` (steward.py:4226) | - | - | EKSİK |
| `plan_tick._close_done` (steward.py:4340) | - | - | EKSİK |
| `plan_tick._quiet_idle` (steward.py:4355) | - | - | EKSİK |
| `plan_tick._active_busy` (steward.py:4503) | - | - | EKSİK |
| `plan_tick._slots` (steward.py:4509) | - | - | EKSİK |
| `_API_ERR_RE` (steward.py:4805) | `consts_gen::P_API_ERR_RE` | generated::generated_files_are_current | tamam |
| `_API_RETRY_HEAD_RE` (steward.py:4806) | `consts_gen::P_API_RETRY_HEAD_RE` | generated::generated_files_are_current | tamam |
| `_API_RETRY_WORD_RE` (steward.py:4811) | `consts_gen::P_API_RETRY_WORD_RE` | generated::generated_files_are_current | tamam |
| `API_NUDGE_TEXT` (steward.py:4815) | `consts_gen::API_NUDGE_TEXT` | generated::generated_files_are_current | tamam |
| `API_NUDGE_DELAYS` (steward.py:4816) | `consts_gen::API_NUDGE_DELAYS` | generated::generated_files_are_current | tamam |
| `API_NUDGE_MAX` (steward.py:4817) | `consts_gen::API_NUDGE_MAX` | generated::generated_files_are_current | tamam |
| `API_GIVEUP_AFTER` (steward.py:4818) | `consts_gen::API_GIVEUP_AFTER` | generated::generated_files_are_current | tamam |
| `API_QUIET_SECONDS` (steward.py:4819) | `consts_gen::API_QUIET_SECONDS` | generated::generated_files_are_current | tamam |
| `API_OUTAGE_MIN` (steward.py:4820) | `consts_gen::API_OUTAGE_MIN` | generated::generated_files_are_current | tamam |
| `API_OUTAGE_PROBE_SECONDS` (steward.py:4821) | `consts_gen::API_OUTAGE_PROBE_SECONDS` | generated::generated_files_are_current | tamam |
| `API_WAKE_GROUP` (steward.py:4822) | `consts_gen::API_WAKE_GROUP` | generated::generated_files_are_current | tamam |
| `api_error_kind` (steward.py:4825) | `recovery::api_error_kind` | recovery::api_error_kind_vectors | tamam |
| `LOOP_MAX` (steward.py:4839) | `consts_gen::LOOP_MAX` | generated::generated_files_are_current | tamam |
| `LOOP_PAUSE_SECONDS` (steward.py:4840) | `consts_gen::LOOP_PAUSE_SECONDS` | generated::generated_files_are_current | tamam |
| `LOOP_PAUSE_TOUR_SECONDS` (steward.py:4841) | `consts_gen::LOOP_PAUSE_TOUR_SECONDS` | generated::generated_files_are_current | tamam |
| `LOOP_PAUSE_DELIVER_SECONDS` (steward.py:4842) | `consts_gen::LOOP_PAUSE_DELIVER_SECONDS` | generated::generated_files_are_current | tamam |
| `LOOP_FORGET_SECONDS` (steward.py:4843) | `consts_gen::LOOP_FORGET_SECONDS` | generated::generated_files_are_current | tamam |
| `LOOP_KINDS` (steward.py:4844) | `consts_gen::LOOP_KINDS` | generated::generated_files_are_current | tamam |
| `_loop_sig` (steward.py:4847) | `recovery::loop_sig` | recovery::p_loop_sig | tamam |
| `loop_guard` (steward.py:4856) | `recovery::loop_guard` | recovery::loop_guard_vectors | tamam |
| `VERIFY_KINDS` (steward.py:4911) | `consts_gen::VERIFY_KINDS` | generated::generated_files_are_current | tamam |
| `VERIFY_WINDOW_SECONDS` (steward.py:4912) | `consts_gen::VERIFY_WINDOW_SECONDS` | generated::generated_files_are_current | tamam |
| `VERIFY_MAX_PENDING` (steward.py:4913) | `consts_gen::VERIFY_MAX_PENDING` | generated::generated_files_are_current | tamam |
| `_outcome_views` (steward.py:4918) | `recovery::outcome_views` | recovery::p_outcome_views | tamam |
| `_DATED_TAIL_RE` (steward.py:4925) | `consts_gen::P_DATED_TAIL_RE` | generated::generated_files_are_current | tamam |
| `_outcome_project` (steward.py:4928) | `recovery::outcome_project` | recovery::p_outcome_project | tamam |
| `outcome_baseline` (steward.py:4937) | `recovery::outcome_baseline` | recovery::outcome_baseline_vectors | tamam |
| `_via` (steward.py:4949) | `recovery::via` | recovery::p_via | tamam |
| `check_outcomes` (steward.py:4953) | `recovery::check_outcomes` | recovery::check_outcomes_vectors | tamam |
| `loop_paused` (steward.py:4984) | `recovery::loop_paused` | recovery::loop_paused_vectors | tamam |
| `api_error_brief` (steward.py:4994) | `recovery::api_error_brief` | recovery::api_error_brief_vectors | tamam |
| `plan_api_recovery` (steward.py:5004) | `recovery::plan_api_recovery` | recovery::plan_api_recovery_vectors | tamam |
| `plan_api_recovery._nudge` (steward.py:5030) | `recovery::plan_api_recovery (içinde)` | recovery::plan_api_recovery_vectors | tamam |
| `plan_api_recovery._due_single` (steward.py:5036) | `recovery::plan_api_recovery (içinde)` | recovery::plan_api_recovery_vectors | tamam |
| `plan_api_recovery._giveup` (steward.py:5044) | `recovery::plan_api_recovery (içinde)` | recovery::plan_api_recovery_vectors | tamam |
| `_observe_cluster` (steward.py:5096) | `recovery::observe_cluster` | recovery::p_observe_cluster | tamam |
| `_AJ_CHILD_RE` (steward.py:5108) | `consts_gen::P_AJ_CHILD_RE` | generated::generated_files_are_current | tamam |
| `_NEXT_NOTE_RE` (steward.py:5109) | `consts_gen::P_NEXT_NOTE_RE` | generated::generated_files_are_current | tamam |
| `_NO_WORK_VALUES` (steward.py:5110) | `consts_gen::P_NO_WORK_VALUES` | generated::generated_files_are_current | tamam |
| `marker_next_work` (steward.py:5113) | `markers::marker_next_work` | tour::marker_next_work_vectors | tamam |
| `_DONE_TEXT_RE` (steward.py:5123) | `consts_gen::P_DONE_TEXT_RE` | generated::generated_files_are_current | tamam |
| `_NEGATED_TAIL_RE` (steward.py:5124) | `consts_gen::P_NEGATED_TAIL_RE` | generated::generated_files_are_current | tamam |
| `_NEXT_NONE_LINE_RE` (steward.py:5126) | `consts_gen::P_NEXT_NONE_LINE_RE` | generated::generated_files_are_current | tamam |
| `CLAUDE_IDLE_NUDGE_TEXT` (steward.py:5127) | `consts_gen::CLAUDE_IDLE_NUDGE_TEXT` | generated::generated_files_are_current | tamam |
| `next_none_stated` (steward.py:5131) | `idletext::next_none_stated` | idletext::next_none_stated_vectors | tamam |
| `_NO_WORK_PHRASES` (steward.py:5138) | `consts_gen::P_NO_WORK_PHRASES` | generated::generated_files_are_current | tamam |
| `_GATE_WAIT_RE` (steward.py:5144) | `consts_gen::P_GATE_WAIT_RE` | generated::generated_files_are_current | tamam |
| `IDLE_STALE_NOTE_ESCAPE` (steward.py:5150) | `consts_gen::IDLE_STALE_NOTE_ESCAPE` | generated::generated_files_are_current | tamam |
| `_TODO_HINT_PREFIX` (steward.py:5151) | `consts_gen::P_TODO_HINT_PREFIX` | generated::generated_files_are_current | tamam |
| `_TURN_FAILED_RE` (steward.py:5156) | `consts_gen::P_TURN_FAILED_RE` | generated::generated_files_are_current | tamam |
| `_TURN_FAILED_STATUS_RE` (steward.py:5159) | `consts_gen::P_TURN_FAILED_STATUS_RE` | generated::generated_files_are_current | tamam |
| `_TURN_FAILED_WORD_RE` (steward.py:5160) | `consts_gen::P_TURN_FAILED_WORD_RE` | generated::generated_files_are_current | tamam |
| `turn_failed` (steward.py:5163) | `idletext::turn_failed` | idletext::turn_failed_vectors | tamam |
| `waiting_for_gate` (steward.py:5171) | `idletext::waiting_for_gate` | idletext::waiting_for_gate_vectors | tamam |
| `one_line` (steward.py:5176) | `idletext::one_line` | idletext::one_line_vectors | tamam |
| `clip_words` (steward.py:5181) | `markers::clip_words` | tour::clip_words_vectors | tamam |
| `notes_wait` (steward.py:5192) | `idletext::notes_wait` | idletext::notes_wait_vectors | tamam |
| `ucli_idle_threshold` (steward.py:5197) | `idletext::ucli_idle_threshold` | idletext::ucli_idle_threshold_vectors | tamam |
| `_COND_RE` (steward.py:5202) | `consts_gen::P_COND_RE` | generated::generated_files_are_current | tamam |
| `_NEG_ANSWER_RE` (steward.py:5206) | `consts_gen::P_NEG_ANSWER_RE` | generated::generated_files_are_current | tamam |
| `NEG_ANSWER_MAX_CHARS` (steward.py:5209) | `consts_gen::NEG_ANSWER_MAX_CHARS` | generated::generated_files_are_current | tamam |
| `is_negative_answer` (steward.py:5212) | `idletext::is_negative_answer` | idletext::is_negative_answer_vectors | tamam |
| `_OPEN_LEAD_RE` (steward.py:5219) | `consts_gen::P_OPEN_LEAD_RE` | generated::generated_files_are_current | tamam |
| `_OPEN_ANY_RE` (steward.py:5220) | `consts_gen::P_OPEN_ANY_RE` | generated::generated_files_are_current | tamam |
| `_HOLD_ANY_RE` (steward.py:5221) | `consts_gen::P_HOLD_ANY_RE` | generated::generated_files_are_current | tamam |
| `_OPT_NUM_RE` (steward.py:5222) | `consts_gen::P_OPT_NUM_RE` | generated::generated_files_are_current | tamam |
| `is_open_answer` (steward.py:5225) | `idletext::is_open_answer` | idletext::is_open_answer_vectors | tamam |
| `_HELD_ANSWER_PREFIX` (steward.py:5240) | `consts_gen::P_HELD_ANSWER_PREFIX` | generated::generated_files_are_current | tamam |
| `_held_instruction_item` (steward.py:5243) | `idletext::held_instruction_item` | idletext::p_held_instruction_item | tamam |
| `CARD_NOTE_MAX_CHARS` (steward.py:5256) | `consts_gen::CARD_NOTE_MAX_CHARS` | generated::generated_files_are_current | tamam |
| `expired_handover_note` (steward.py:5259) | `idletext::expired_handover_note` | idletext::expired_handover_note_vectors | tamam |
| `is_conditional_note` (steward.py:5272) | `markers::is_conditional_note` | tour::is_conditional_note_vectors | tamam |
| `_FABLE_POLISH_RE` (steward.py:5277) | `consts_gen::P_FABLE_POLISH_RE` | generated::generated_files_are_current | tamam |
| `is_fable_polish` (steward.py:5280) | `idletext::is_fable_polish` | idletext::is_fable_polish_vectors | tamam |
| `next_work_hint` (steward.py:5285) | `idletext::next_work_hint` | idletext::next_work_hint_vectors | tamam |
| `_TODO_ITEM_RE` (steward.py:5320) | `consts_gen::P_TODO_ITEM_RE` | generated::generated_files_are_current | tamam |
| `_NOTE_WORD_RE` (steward.py:5321) | `consts_gen::P_NOTE_WORD_RE` | generated::generated_files_are_current | tamam |
| `_NOTE_STOPWORDS` (steward.py:5322) | `consts_gen::P_NOTE_STOPWORDS` | generated::generated_files_are_current | tamam |
| `STALE_NOTE_MIN_WORDS` (steward.py:5323) | `consts_gen::STALE_NOTE_MIN_WORDS` | generated::generated_files_are_current | tamam |
| `STALE_NOTE_CLOSED_MIN` (steward.py:5324) | `consts_gen::STALE_NOTE_CLOSED_MIN` | generated::generated_files_are_current | tamam |
| `STALE_NOTE_MARGIN` (steward.py:5325) | `consts_gen::STALE_NOTE_MARGIN` | generated::generated_files_are_current | tamam |
| `STALE_NOTE_DONE_MIN` (steward.py:5326) | `consts_gen::STALE_NOTE_DONE_MIN` | generated::generated_files_are_current | tamam |
| `_DONE_BULLET_RE` (steward.py:5327) | `consts_gen::P_DONE_BULLET_RE` | generated::generated_files_are_current | tamam |
| `_note_words` (steward.py:5330) | `idletext::note_words` | idletext::p_note_words | tamam |
| `stale_next_note` (steward.py:5334) | `idletext::stale_next_note` | idletext::stale_next_note_vectors | tamam |
| `without_stale_note` (steward.py:5366) | `idletext::without_stale_note` | idletext::without_stale_note_vectors | tamam |
| `_OWNER_WAIT_PHRASES` (steward.py:5382) | `consts_gen::P_OWNER_WAIT_PHRASES` | generated::generated_files_are_current | tamam |
| `_NEXT_LINE_RE` (steward.py:5385) | `consts_gen::P_NEXT_LINE_RE` | generated::generated_files_are_current | tamam |
| `_NEXT_NONE_RE` (steward.py:5386) | `consts_gen::P_NEXT_NONE_RE` | generated::generated_files_are_current | tamam |
| `next_line` (steward.py:5389) | `idletext::next_line` | idletext::next_line_vectors | tamam |
| `_STATED_NEXT_RE` (steward.py:5400) | `consts_gen::P_STATED_NEXT_RE` | generated::generated_files_are_current | tamam |
| `stated_next_work` (steward.py:5406) | `idletext::stated_next_work` | idletext::stated_next_work_vectors | tamam |
| `owner_wait` (steward.py:5425) | `idletext::owner_wait` | idletext::owner_wait_vectors | tamam |
| `_done_at_line_end` (steward.py:5431) | `idletext::done_at_line_end` | idletext::p_done_at_line_end | tamam |
| `idle_finish_marker` (steward.py:5437) | `idletext::idle_finish_marker` | idletext::idle_finish_marker_vectors | tamam |
| `plan_ucli_idle` (steward.py:5465) | `idle::plan_ucli_idle` | idle::plan_ucli_idle_vectors | tamam |
| `_ASK_MARKERS` (steward.py:5561) | `consts_gen::P_ASK_MARKERS` | generated::generated_files_are_current | tamam |
| `_forced_open_nudge` (steward.py:5564) | `idle::forced_open_nudge` | idle::p_forced_open_nudge | tamam |
| `OWNER_CLAIM_MIN_IDLE_SECS` (steward.py:5577) | `consts_gen::OWNER_CLAIM_MIN_IDLE_SECS` | generated::generated_files_are_current | tamam |
| `OWNER_CLAIM_NUDGE_TEXT` (steward.py:5578) | `consts_gen::OWNER_CLAIM_NUDGE_TEXT` | generated::generated_files_are_current | tamam |
| `plan_claude_idle` (steward.py:5583) | `idle::plan_claude_idle` | idle::plan_claude_idle_vectors | tamam |
| `_WHY_TR` (steward.py:5754) | `consts_gen::P_WHY_TR` | generated::generated_files_are_current | tamam |
| `_WHY_EN` (steward.py:5773) | `consts_gen::P_WHY_EN` | generated::generated_files_are_current | tamam |
| `_START_BLOCK_TR` (steward.py:5791) | `consts_gen::P_START_BLOCK_TR` | generated::generated_files_are_current | tamam |
| `_why` (steward.py:5796) | `explain::why` | explain::p_why | tamam |
| `explain_idle` (steward.py:5802) | `explain::explain_idle` | explain::explain_idle_vectors | tamam |
| `explain_idle_all` (steward.py:5916) | `explain::explain_idle_all` | explain::explain_idle_all_vectors | tamam |
| `observe_filter` (steward.py:5943) | - | - | EKSİK |
| `daily_path` (steward.py:5994) | - | - | EKSİK |
| `log_entries_for_date` (steward.py:5998) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `DRY_KIPS` (steward.py:6017) | `consts_gen::DRY_KIPS` | generated::generated_files_are_current | tamam |
| `DRY_REPORT_HOURS` (steward.py:6019) | `consts_gen::DRY_REPORT_HOURS` | generated::generated_files_are_current | tamam |
| `dry_report` (steward.py:6022) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `dry_report_text` (steward.py:6052) | - | - | EKSİK |
| `dry_ask_due` (steward.py:6063) | - | - | EKSİK |
| `summary_due` (steward.py:6074) | - | - | EKSİK |
| `missed_summary_dates` (steward.py:6081) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `_NO_LOG_DAYS` (steward.py:6105) | - | - | kapsam dışı: yol ya da çalışma zamanı nesnesi (dosya yolu, kilit, bellek içi önbellek): rs/state + T10 |
| `_SUMMARY_TXT` (steward.py:6108) | `consts_gen::P_SUMMARY_TXT` | generated::generated_files_are_current | tamam |
| `_names` (steward.py:6132) | - | - | EKSİK |
| `_kind_counts` (steward.py:6137) | - | - | EKSİK |
| `_ask_gate_lines` (steward.py:6142) | - | - | EKSİK |
| `daily_summary` (steward.py:6161) | - | - | EKSİK |
| `summary_text` (steward.py:6244) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `write_daily` (steward.py:6262) | - | - | kapsam dışı: G/Ç (olay günlüğü, rapor dosyaları): T10 uygulama katmanı |
| `summarize_projects` (steward.py:6269) | - | - | EKSİK |
| `rfh_marker_in` (needs_ho.py:135) | `markers::rfh_marker_in` | markers::rfh_marker_edges | tamam |
| `collapse_ws` (textutil.py:7) | `pyc::collapse_ws` | markers::collapse_ws_edges | tamam |
| `owner_class` (steward_ask.py:36) | `ask::owner_class` | gates::owner_class_vectors | tamam |
| `blocked_reason` (steward_ask.py:61) | `ask::blocked_reason` | gates::blocked_reason_vectors | tamam |
| `tour_eligible` (steward_ask.py:71) | `ask::tour_eligible` | gates::bad_values_are_errors, gates::tour_eligible_hand | tamam |

### Python testleri (1808 satır)

| Python testi | Rust karşılığı / gerekçe |
|---|---|
| `test_answered_by.AnsweredByTest.test_by_recorded_and_unknown_dropped` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_answered_by.AnsweredByTest.test_cops_adds_prefix_once_and_keeps_option_resolution` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_answered_by.AnsweredByTest.test_load_old_record_without_field` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+15) |
| `test_answered_by.AnsweredByTest.test_cli_default_by_env` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_answered_by.AnsweredByTest.test_cli_fallback_detects_claude_parent_or_claude_env_without_cops_name` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_answered_by.AnsweredByTest.test_fix_answered_by_changes_only_the_field_and_does_not_redeliver` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+17) |
| `test_answered_by.HttpAnswerByTest.test_panel_default_cli_by_and_brain` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+23) |
| `test_answered_by.CmdAnswerGuardTest.test_overwrite_refused_without_force` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+17) |
| `test_body_sensitive_c.BodySensitive.test_flags` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_body_sensitive_c.BodySensitive.test_remote_candidate_body_omitted_not_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_body_sensitive_c.BodySensitive.test_redacted_row_strips_body_only_for_auto` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_body_sensitive_c.BodySensitive.test_export_sensitive_ignores_body_keyword` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_body_sensitive_c.AutoApprove.test_body_keyword_approved_title_keyword_held` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_brain_directive_subagent_gate.TestBrainDirectiveSubagentGate.test_subagent_active_defers` | identity::normalize_host_edges, identity::normalize_host_vectors |
| `test_brain_directive_subagent_gate.TestBrainDirectiveSubagentGate.test_idle_without_subagent_sends` | gates::directive_defer_reason_vectors, identity::normalize_host_edges, identity::normalize_host_vectors |
| `test_brain_pause.TestVerdict.test_finished_project_is_accepted` | cards::brain_pause_verdict_vectors |
| `test_brain_pause.TestVerdict.test_blocked_project_with_open_work_is_accepted` | cards::brain_pause_verdict_vectors |
| `test_brain_pause.TestVerdict.test_refusals` | cards::brain_pause_verdict_vectors |
| `test_brain_pause.TestGate.test_accepted_when_finished_and_logged` | cards::brain_pause_verdict_vectors, cards::card_one_liner_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+19) |
| `test_brain_pause.TestGate.test_refused_when_work_should_continue` | cards::brain_pause_verdict_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires (+16) |
| `test_brain_pause.TestGate.test_refused_without_reason_or_when_running` | cards::brain_pause_verdict_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires (+16) |
| `test_brain_pause.TestGate.test_idea_and_done_stay_owner_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_brain_permission_ucli.BrainPermission.test_default_allow_edit_is_a_valid_ucli_mode` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_brain_permission_ucli.BrainPermission.test_applied_only_for_ucli` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_brain_rules_g_h.TestBrainRules.test_rules_present_in_both_languages` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_brain_rules_g_h.TestBrainRules.test_h_is_limited_to_reversible_questions` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_card_prompt_blockers.CardPromptBlockersTest.test_tr_prompt_demands_currently_open_blockers` | cards::build_card_prompt_vectors |
| `test_card_prompt_blockers.CardPromptBlockersTest.test_en_prompt_demands_currently_open_blockers` | cards::build_card_prompt_vectors |
| `test_directive_auto_todo.DirectiveAutoTodo.test_adds_line_with_id_and_flattens_text` | inserts::todo_insert_directive_vectors |
| `test_directive_auto_todo.DirectiveAutoTodo.test_same_content_or_same_id_not_duplicated` | inserts::todo_insert_directive_vectors |
| `test_directive_auto_todo.DirectiveAutoTodo.test_closed_line_allows_same_text_again` | inserts::todo_insert_directive_vectors |
| `test_directive_auto_todo.DirectiveAutoTodo.test_brain_directive_recorded_unless_short_or_nudge` | inserts::answer_has_action_vectors, inserts::todo_insert_directive_vectors |
| `test_directive_auto_todo.DirectiveAutoTodo.test_system_directives_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_auto_todo.DirectiveAutoTodo.test_missing_project_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_auto_todo.DirectiveAutoTodo.test_remote_project_uses_host_routed_edit` | inserts::todo_insert_directive_vectors |
| `test_directive_auto_todo.DirectiveAutoTodo.test_state_open_then_closed_then_missing` | inserts::todo_insert_directive_vectors |
| `test_directive_delivery.SendVerified.test_delivered_when_message_appears` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_old_identical_header_does_not_fake_delivery` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_pasted_text_in_box_gets_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_pasted_text_ignoring_enter_gets_space_then_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_permanently_stuck_paste_fails_without_resend` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_text_unsent_in_input_box_is_not_delivered` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_text_stuck_in_input_box_forever_fails_without_resend` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_placeholder_text_in_transcript_does_not_trigger_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_pasted_placeholder_in_input_box_gets_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_grey_suggestion_in_box_is_not_unsent_text` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_colored_typed_text_in_box_counts_as_unsent` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_resend_when_nothing_arrived` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.SendVerified.test_ucli_unverified_skip` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_directive_delivery.Queue.test_start_path_returns_queued_immediately_then_delivered` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_directive_delivery.Queue.test_failure_is_visible_with_reason_and_notifies` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_directive_delivery.Queue.test_brain_actor_stays_synchronous` | gates::panic_path_is_under_default_root, identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_directive_delivery.HoDoneFresh.test_ho_done_live_session_stopped_exact_and_started_fresh` | identity::paths_for_vectors, identity::paths_layout_and_errors, prompts::main_session_model_effort_vectors |
| `test_directive_delivery.ClosedHoDoneAndPersistence.test_closed_ho_done_conversation_starts_fresh` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_directive_delivery.ClosedHoDoneAndPersistence.test_deliveries_survive_restart_and_queued_becomes_failed` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+5) |
| `test_done_conflict_answer.DoneAnswerTest.test_clear_yes_closes` | closing::done_conflict_answer_vectors |
| `test_done_conflict_answer.DoneAnswerTest.test_clear_no_does_not` | closing::done_conflict_answer_vectors |
| `test_done_conflict_answer.DoneAnswerTest.test_hedged_yes_does_not_close` | closing::done_conflict_answer_vectors |
| `test_done_conflict_answer.DoneAnswerTest.test_no_answer_or_stale_or_other_project` | closing::done_conflict_answer_vectors |
| `test_empty_fleet_p0.NoneRejected.test_second_none_with_same_todo_gets_oldest_item_not_silence` | idle::p_forced_open_nudge, idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::one_line_vectors (+8) |
| `test_empty_fleet_p0.NoneRejected.test_without_oldest_callback_old_behaviour` | idle::p_forced_open_nudge, idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::turn_failed_vectors (+6) |
| `test_empty_fleet_p0.NoneRejected.test_zero_open_still_silent` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+11) |
| `test_empty_fleet_p0.NoneRejected.test_loop_guard_caps_repeated_rejection` | idle::p_forced_open_nudge, idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::one_line_vectors (+8) |
| `test_empty_fleet_p0.QuotaReopen.test_reopen_ready_gate` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_empty_fleet_p0.QuotaReopen.test_alarm_rules` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_empty_fleet_p0.QuotaReopen.test_reopens_recorded_sids_after_two_ok_polls_and_clears` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_empty_fleet_p0.QuotaReopen.test_cold_reopen_under_two_hours_sends_one_summary` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_empty_fleet_p0.QuotaReopen.test_not_ok_resets_streak_and_keeps_list` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_extension_directive_park.ExtensionDirectivePark.test_closed_session_writes_todo_and_does_not_open` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_extension_directive_park.ExtensionDirectivePark.test_paused_project_not_revived_even_if_session_live` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_extension_directive_park.ExtensionDirectivePark.test_live_active_session_goes_through` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::name_rules_edges, identity::valid_name_vectors (+1) |
| `test_extension_directive_park.ExtensionDirectivePark.test_drain_blocks_extension` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_extension_directive_park.ExtensionDirectivePark.test_repeated_note_not_duplicated` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_idea_project.IdeaProject.test_idea_with_project_and_unknown_project` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_input_box_typed.TypedBoxTest.test_empty_box_is_not_typed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_grey_suggestion_is_not_typed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_default_color_text_is_typed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_whitespace_only_and_borders_ignored` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_no_box_is_unknown` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_last_box_wins` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_ucli_uses_its_own_box_reader` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.TypedBoxTest.test_helper_false_on_error_and_unknown` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_input_box_typed.KeepwarmApplyTest.test_box_full_skips_keepwarm` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_input_box_typed.KeepwarmApplyTest.test_box_empty_sends_keepwarm` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_input_box_typed.ApiNudgeApplyTest.test_box_full_skips_nudge` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_input_box_typed.ApiNudgeApplyTest.test_target_denied_skips_nudge` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_input_box_typed.ApiNudgeApplyTest.test_box_empty_sends_nudge` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_labels.TestLabels.test_concurrent_updates_lose_nothing` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_system_defs_present_and_undeletable` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_name_validation` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_add_remove_autodefine_and_find` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_delete_def_strips_assignments` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_key_for_and_attach` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_api_action` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_corrupt_file_is_empty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestLabels.test_auto_remove_only_listed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestCli.test_flow` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestStewardAutoRemove.test_phase_back_to_planned_removes` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_labels.TestStewardAutoRemove.test_new_project_in_planned_does_not_touch_labels` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_labels.TestStewardAutoRemove.test_directive_success_removes_but_not_job_delivery` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_labels.TestApi.test_local_only_route` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestApi.test_post_flow_ignores_host_field` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestApi.test_status_payload_has_labels` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_labels.TestSearchParserTs.test_label_terms` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_note_claims.TestClaims.test_parse` | prompts::note_claims_vectors |
| `test_note_claims.TestClaims.test_dead_pid_and_empty_gate_are_contradictions` | prompts::check_note_claims_branches, prompts::check_note_claims_vectors, prompts::note_claims_vectors |
| `test_note_claims.TestClaims.test_alive_unknown_or_ahead_are_silent` | prompts::check_note_claims_branches, prompts::check_note_claims_vectors, prompts::note_claims_vectors |
| `test_note_claims.TestClaims.test_contradiction_rides_the_idle_item_and_renders` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, prompts::build_tour_prompt_vectors (+10) |
| `test_orphan_digest.OrphanDigestTest.test_line_shown_only_when_orphans` | EKSİK: parite testi olmayan _ask_gate_lines, daily_summary |
| `test_orphan_digest.BrainTourRatioTest.test_ratio_line` | EKSİK: parite testi olmayan _ask_gate_lines, _names, daily_summary |
| `test_owner_answer_persist.Pure.test_action_heuristic` | inserts::answer_has_action_vectors |
| `test_owner_answer_persist.Pure.test_todo_insert_once` | inserts::todo_insert_answer_vectors |
| `test_owner_answer_persist.Http.test_owner_answer_written_under_tbd_and_todo` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+25) |
| `test_owner_answer_persist.Http.test_short_answer_only_tbd` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+24) |
| `test_owner_answer_persist.Http.test_second_answer_same_qid_not_duplicated` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+25) |
| `test_owner_answer_persist.Http.test_phone_page_answer_persisted` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+27) |
| `test_owner_answer_persist.Http.test_cli_answer_asks_panel_to_persist` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+26) |
| `test_owner_answer_persist.Http.test_cli_answer_persists_locally_when_panel_down` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+26) |
| `test_owner_answer_persist.Http.test_persist_only_rejects_open_question` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+12) |
| `test_owner_answer_persist.Http.test_brain_action_answer_persisted` | gates::bad_values_are_errors, gates::brain_may_answer_vectors, gates::job_request_gate_vectors, gates::long_texts_stay_within_regex_limits (+27) |
| `test_owner_answer_persist.Http.test_brain_short_or_nudge_answer_not_persisted` | gates::bad_values_are_errors, gates::brain_may_answer_vectors, gates::job_request_gate_vectors, gates::long_texts_stay_within_regex_limits (+19) |
| `test_owner_claim_nudge.OwnerClaim.test_nudges_once_when_no_recorded_question` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::owner_wait_vectors (+6) |
| `test_owner_claim_nudge.OwnerClaim.test_no_nudge_when_question_recorded_or_short_idle` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::owner_wait_vectors (+6) |
| `test_owner_claim_nudge.OwnerClaim.test_no_nudge_without_owner_phrase` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+7) |
| `test_owner_claim_nudge.OwnerClaim.test_close_blocked_until_nudged_then_waived` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+5) |
| `test_owner_claim_nudge.UsageScan.test_counters_not_secret` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_owner_claim_nudge.UsageScan.test_real_secret_in_usage_still_held` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_owner_claim_nudge.UsageScan.test_md_unchanged` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.AtomicWriteTextTest.test_writes_and_leaves_no_tmp` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.AtomicWriteTextTest.test_tmp_name_is_per_thread` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.AtomicWriteTextTest.test_concurrent_writers_never_raise` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.AtomicWriteTextTest.test_failed_write_removes_tmp` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.WriteLessonTest.test_concurrent_lessons_no_tmp_race_and_no_stale_tmp` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.CloseModelsTest.test_comment_and_restore` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.CloseModelsTest.test_dry_run_and_missing_do_not_write` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.CloseModelsTest.test_missing_file_is_notfound` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.CloseModelsTest.test_concurrent_closes_lose_no_update` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.FilesWriteTextFsyncTest.test_fsync_before_replace` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.QuotaTest.test_parse_reset_invalid_day_returns_none` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.QuotaTest.test_parse_reset_leap_day_rollover_does_not_raise` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.QuotaTest.test_parse_reset_normal` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.QuotaTest.test_num_rejects_nan_inf` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p2_atomic_writes.QuotaTest.test_decide_nan_limit_falls_back_to_default_final` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p3_fixes.FilesRootTest.test_filesystem_root_allows_children` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p3_fixes.FilesRootTest.test_sibling_prefix_still_rejected` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p3_fixes.QuotaDstTest.test_day_boundary_uses_wall_clock_across_dst_end` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_p3_fixes.FileLockReentrantTest.test_nested_same_thread_does_not_deadlock` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_pool_focus_action.TestPoolFocusAction.test_focus_then_unfocus` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_pool_focus_action.TestPoolFocusAction.test_focus_needs_enabled_project` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_pool_focus_action.TestPoolFocusAction.test_focus_unknown_project` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_pool_focus_action.TestPoolFocusAction.test_disable_and_remove_clear_focus` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_pool_only_action.TestPoolOnly.test_only_enables_target_disables_rest_atomically` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_pool_only_action.TestPoolOnly.test_only_unknown_project_changes_nothing` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_pool_only_action.TestPoolOnly.test_only_remote_block_refuses_before_any_change` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_question_detail_gen.GenTest.test_generates_once_and_caches` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_question_detail_gen.GenTest.test_failure_is_silent_and_not_retried_within_cache` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_question_detail_gen.GenTest.test_daily_cap` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_question_detail_gen.GenTest.test_model_is_cheap` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_question_detail_gen.GenTest.test_ensure_detail_saves_on_question` | identity::from_dict_drops_unknown_and_requires, store::set_question_detail_vectors |
| `test_question_detail_gen.HookTest.test_ensure_async_skips_routine_detailed_answered` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_question_detail_gen.HookTest.test_ws_auto_detail_swallows_errors` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_manual_and_month.MonthTests.test_unknown_month_returns_none` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_manual_and_month.MonthTests.test_known_month_still_parses` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_manual_and_month.ManualDayCapTests.test_manual_without_limit_honours_day_cap` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_manual_and_month.ManualDayCapTests.test_manual_without_limit_and_cap_is_ok` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_scoped_api_credit.TestPlanTickQuotaHeld.test_quota_held_project_is_not_started_others_are` | EKSİK: parite testi olmayan plan_tick |
| `test_quota_scoped_api_credit.TestPlanTickQuotaHeld.test_answer_does_not_start_held_project` | EKSİK: parite testi olmayan plan_tick |
| `test_quota_scoped_api_credit.TestQuotaScopeHelpers.test_held_projects_only_metered_cli` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_scoped_api_credit.TestQuotaScopeHelpers.test_blocks_target_depends_on_brain_cli` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_scoped_api_credit.TestBrainCliConfig.test_set_brain_cli_service_cost` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_quota_scoped_api_credit.TestBrainCliConfig.test_rejects_bad` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_scoped_api_credit.TestCreditWindow.test_config_dates_validated` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_scoped_api_credit.TestCreditWindow.test_spent_counts_only_since` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_quota_scoped_api_credit.TestCreditWindow.test_window_days_and_budget` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestSlugTargets.test_slug` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestSlugTargets.test_targets_all_and_filtered` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestSlugTargets.test_claude_mode_opt_in` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_complete_window` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_skip_pairs_drops_only_that_pair_not_the_project` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_focus_project_goes_first` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_order_partial_then_never_then_oldest` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_unchanged_head_is_not_reviewed_again_after_the_window` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_busy_running_disabled_and_empty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_attempt_cap` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPlanner.test_evren_single_attempt_per_window` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestUncountedAttempts.test_restart_cancel_spawn_do_not_consume_attempt` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestUncountedAttempts.test_single_word_denetlenmemistir_is_not_incomplete` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPoolSync.test_sync` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestParse.test_findings` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestParse.test_prompt` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestRedactLabel.test_redact` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestRedactLabel.test_agy_label` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestPathsAndStores.test_paths` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_custom_id_vectors |
| `test_review.TestPathsAndStores.test_review_path` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_history_and_pool_roundtrip` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_running_without_started_at_does_not_carry_old_window_attempts` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_findings_store` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_findings_dedup_by_key` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_dedup_canonical_prefers_live_over_refuted` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_dedup_same_report_never_and_undup` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_findings_fid_collision_prefix_case_severity` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_finding_key_folds_turkish_case_and_accents` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestPathsAndStores.test_planner_survives_corrupt_history_numbers` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review.TestConfigRole.test_defaults_and_settings` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_review.TestClaudeArgv.test_claude_argv_read_only_and_prompt_first` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestClaudeArgv.test_claude_argv_denies_every_forbidden_path_at_tool_level` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestCodexArgv.test_codex_argv_read_only` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestCopilotMode.test_argv_read_only_and_prompt` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestCopilotMode.test_targets_and_effort_path` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestCopilotMode.test_monthly_quota_is_a_limit` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestRequeueStaleVerify.test_stale_goes_back_then_gives_up` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestRequeueStaleVerify.test_self_verify_and_other_states_untouched` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestUsageSummary.test_sums_per_project_and_target` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestRedactLeaks.test_leaks_closed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestRedactLeaks.test_plain_text_untouched` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestDsnRedact.test_dsn_password_masked_and_learned` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestDsnRedact.test_redact_learns_dsn_password_from_same_text` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestDsnRedact.test_iolog_learns_across_events` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestEffortPairs.test_same_model_two_efforts_are_separate_pairs` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TerminateReapsTest.test_wait_after_sigkill` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestReviewSmallFixes.test_report_incomplete_recognizes_parser_heading_forms` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestReviewSmallFixes.test_usage_summary_ignores_unreadable_file` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestDsnEdgeCases.test_uppercase_scheme_and_special_chars_in_password` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.TestLearnedPasswordLength.test_short_learned_password_does_not_corrupt_text` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.ExportNoLocalPathTest.test_absolute_path_outside_root_is_shortened` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.R10SubMigrationTest.test_moves_only_post_switch_claude_pairs` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review.R10SubMigrationTest.test_idempotent` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_cleanup_fixes.FindingKeyTest.test_markdown_link_where_same_key_as_plain` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_cleanup_fixes.FindingKeyTest.test_different_file_or_title_differs` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_cleanup_fixes.ConditionalNoteTest.test_turkish_conditions` | tour::is_conditional_note_vectors |
| `test_review_duration_summary.DurationTest.test_run_seconds` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.DurationTest.test_update_pair_records_seconds_in_runs` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review_duration_summary.DurationTest.test_duration_summary` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.StaleTextTest.test_where_relpath` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.StaleTextTest.test_stale_reason_text` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.ClaudeJsonTest.test_argv_json_flag_only_for_review` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.ClaudeJsonTest.test_extract_and_usage` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.ClaudeJsonTest.test_non_json_and_errors_fall_back` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.CodexUsageTest.test_parse` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.CodexUsageTest.test_summary_totals_without_invented_split` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_duration_summary.RunDurTest.test_run_dur` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_findings_flow.TestAutoFindings.test_done_review_records_findings_as_new` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestExportStaleCheck.test_stale_reason_pure` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_review_findings_flow.TestExportStaleCheck.test_stale_finding_not_exported_and_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestExportStaleCheck.test_changed_after_review_is_marked` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestScanVerdicts.test_only_real_line_start` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_findings_flow.TestVerify.test_verify_sends_via_owner_human_directive_and_marks` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+33) |
| `test_review_findings_flow.TestVerify.test_closed_project_is_explicit_error_and_nothing_sent` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_review_findings_flow.TestVerify.test_busy_or_subagent_defers` | gates::directive_defer_reason_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+31) |
| `test_review_findings_flow.TestVerify.test_remote_routed_to_its_host_unknown_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+16) |
| `test_review_findings_flow.TestVerdicts.test_verdict_from_owner_session_applied_once` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+46) |
| `test_review_findings_flow.TestVerdicts.test_code_block_example_not_counted` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+46) |
| `test_review_findings_flow.TestVerdicts.test_other_session_source_rejected` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+46) |
| `test_review_findings_flow.TestVerdicts.test_baseline_text_not_reprocessed` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+46) |
| `test_review_findings_flow.TestVerdicts.test_ambiguous_sessions_not_read` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+46) |
| `test_review_findings_flow.TestExportUnverifiedToRtodo.test_split_by_kind_and_note_and_state` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestExportUnverifiedToRtodo.test_unknown_kind_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestDecideExport.test_approve_rules` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestDecideExport.test_export_only_approved_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestDecideExport.test_export_tbd_and_remote_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExport.test_remote_export_once_and_sensitive_skipped` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExport.test_remote_stale_finding_rejected_not_written` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExport.test_remote_unreadable_source_does_not_block_export` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExport.test_remote_missing_file_stops_and_reports` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExport.test_remote_sensitive_finding_skipped` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExport.test_no_driver_is_error_not_crash` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestRemoteExportRealDriver.test_real_driver_writes_once_and_marks_exported` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestRemoteExportRealDriver.test_real_driver_conflict_between_reads_leaves_finding_approved` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestGates.test_brain_actor_rejected_on_all_new_posts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestGates.test_non_reviewer_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestGates.test_reviewer_target_refusal_unchanged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestCli.test_cli_maps` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestEvrenRemoteExportE2E.test_report_to_remote_todo_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestEvrenRemoteExportE2E.test_busy_session_written_but_not_notified` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestEvrenRemoteExportE2E.test_write_failure_keeps_approved_for_retry` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestEvrenRemoteExportE2E.test_conflict_during_export_keeps_approved` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestEvrenRemoteExportE2E.test_transient_conflict_retries_once_and_succeeds` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoApprove.test_held_sensitive_finding_notifies_owner_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_review_findings_flow.TestAutoApprove.test_level_1_approves_only_verified_p3_without_secrets` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_review_findings_flow.TestAutoApprove.test_level_2_adds_p2_but_never_p1_unclear_or_secret` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_review_findings_flow.TestAutoApprove.test_level_3_approves_all_but_secret_and_unclear` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_review_findings_flow.TestAutoApprove.test_off_and_tick_wiring` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+35) |
| `test_review_findings_flow.TestAutoExport.test_off_by_default_writes_nothing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_findings_flow.TestAutoExport.test_on_exports_to_todo_only_never_tbd` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_unclear_goes_to_tbd_after_todo` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_already_in_file_is_not_written_twice` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_sensitive_and_remote_are_skipped` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_body_secret_is_exported_without_body` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_secret_skip_is_loud_once_and_listed_for_manual_export` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_word_only_finding_is_auto_written_redacted` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_one_project_per_tick_and_error_continues` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_exception_is_logged_and_next_project_goes` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_findings_flow.TestAutoExport.test_review_tick_runs_it_when_on` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+35) |
| `test_review_findings_flow.TestAutoVerify.test_sends_once_per_tick_and_marks` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+33) |
| `test_review_findings_flow.TestAutoVerify.test_stale_waiting_does_not_block` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, identity::brain_name_for_vectors (+33) |
| `test_review_findings_flow.TestAutoVerify.test_off_and_busy_send_nothing` | gates::directive_defer_reason_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+31) |
| `test_review_findings_flow.TestBeforeTbd.test_writes_only_unclear_and_refuted_once_and_hides_secrets` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_review_findings_flow.TestBeforeTbd.test_off_when_dir_empty_or_missing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_review_findings_flow.TestBeforeTbd.test_tick_wiring` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+35) |
| `test_review_findings_flow.StoreReportsTest.test_copies_report_and_usage_once_and_skips_private_traces` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_incremental_and_roles` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_stdout_secret_split_across_chunks_is_redacted` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_stdout_stream_flush_emits_held_tail_and_nonstream_unchanged` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_plain_stderr_is_system_when_not_a_delta_stream` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_split_prefix_and_secret` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_trim_note` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestIoLog.test_bad_line_tolerated` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestRunWritesIo.test_persisted_after_done_and_cancel` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_error_keeps_io_and_redacts_stdout` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_review_io_history.TestRunWritesIo.test_stream_flags_gated` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_real_pipes_stream_and_heartbeat` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_budget_flags_gated_and_configurable` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_create_dir_flag_and_draft_recovery` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_findings_written_as_found_survive_a_cut_run` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_streamed_report_recovery_on_empty_stdout` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_report_and_draft_mask_password_learned_from_stream` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_recovered_text_with_clean_exit_is_partial_not_done` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_no_findings_report_recovered_from_stream` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_deltas_memory_bounded_keeps_tail_report` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review_io_history.TestRunWritesIo.test_recover_draft_atomic_and_ignores_symlink` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_review_io_history.TestRunWritesIo.test_tool_call_cap_and_usage_log_flags` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_script_read_flag_is_on_by_default_and_read_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_effective_wall_secs_keeps_wrap_up_margin` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_wall_and_request_timeout_flags` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_max_output_tokens_flag` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestRunWritesIo.test_recover_leaves_io` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_review_io_history.TestChatApi.test_chat_conversion_and_runs_row` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_io_history.TestChatApi.test_runs_are_newest_first_across_projects` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_io_history.TestChatApi.test_result_without_stream_is_answer` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_review_io_history.TestChatApi.test_path_security` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_io_history.TestChatApi.test_needs_reviewer` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_io_history.TestChatApi.test_live_by_pair_no_client_path` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_io_history.TestNaming.test_review_title` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.TestNaming.test_steward_title_and_badge` | identity::badge_edges, identity::derived_of_vectors, identity::p_project_key, identity::steward_badge_vectors (+1) |
| `test_review_io_history.ReportIncompleteTests.test_budget_exhausted_without_finding_is_incomplete` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_io_history.ReportIncompleteTests.test_real_findings_or_clean_reports_are_not` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_model_health.TestHealth.test_limit_runs_do_not_count_and_candidates_need_min_runs` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_model_health.TestHealth.test_old_runs_are_outside_the_window` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_model_health.TestHealth.test_digest_lists_only_non_excluded_candidates` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_model_health.TestExclusion.test_toggle_and_targets_filter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_model_health.TestHttp.test_human_only_and_validation` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.PureTest.test_parse_answer` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.PureTest.test_parse_answer_long_free_text_starting_with_no_is_not_off` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.PureTest.test_parse_answer_keyword_beats_path` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.PureTest.test_parse_answer_word_boundary` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.PureTest.test_prepare_copy_updates_and_refuses_dirty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.PureTest.test_prepare_copy_stops_on_divergence` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.RemoteFlowTest.test_set_where_from_panel` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_remote.RemoteFlowTest.test_unknown_choice_blocks_review_and_asks_the_owner_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+28) |
| `test_review_remote.RemoteFlowTest.test_local_answer_enables_the_copy_and_runs_there` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+33) |
| `test_review_remote.RemoteFlowTest.test_dirty_copy_blocks_manual_run_and_tick_logs_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_remote.RemoteFlowTest.test_off_answer_stops_asking_and_remote_is_recorded_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+32) |
| `test_review_remote.RemoteFlowTest.test_remote_mode_tick_starts_job_with_empty_cwd_when_ready` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_remote.RemoteFlowTest.test_remote_mode_tick_waits_when_gates_say_no` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_remote.RemoteFlowTest.test_remote_mode_accepts_only_evren_targets` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_remote.RemoteFlowTest.test_remote_run_job_end_to_end_writes_report_and_stops_session` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_remote.RemoteFlowTest.test_recover_on_start_skips_live_job_of_this_process` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_review_remote.RemoteFlowTest.test_sweep_closes_orphan_only_when_no_live_job_and_is_throttled` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_remote.RemoteFlowTest.test_unrecognized_answer_reasks_only_after_retry_window` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+32) |
| `test_review_remote.RemoteFlowTest.test_invalid_values_are_ignored_by_upsert` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_review_remote.FirstPollRaceTest.test_early_running_false_is_not_a_dead_run` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_remote.FirstPollRaceTest.test_running_false_after_grace_still_ends_run` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_self_verify.SelfVerifyTest.test_verdicts_applied_session_not_woken` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_failure_returns_to_new_then_unclear_after_max_tries` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_apply_verdicts_exception_requeues_not_stuck` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_timeout_kills_and_requeues` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_concurrent_calls_same_project_only_one_starts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_missing_verdict_line_requeues_only_that_finding` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_recover_returns_orphaned_self_verify_to_new` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_recover_also_returns_orphaned_remote_verify_to_new` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_recover_leaves_live_remote_verify_alone` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_process_verdicts_ignores_self_sessions` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_http_verify_and_auto_verify_use_self_mode` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_bulk_approve_only_verified_filtered` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_bulk_endpoint_is_human_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_default_verifier_is_claude_sonnet` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_codex_verifier_read_only_argv` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_evren_verifier_waits_for_running_evren_review_and_has_no_allow_flags` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_self_verify.SelfVerifyTest.test_missing_model_is_busy_not_marked` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_self_verify.SelfVerifyTest.test_config_accepts_provider_and_single_model` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_slots.TestParseSlots.test_parse` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.TestTakeSlot.test_single_mode_one_job` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.TestTakeSlot.test_slots` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.TestTakeSlot.test_agy_home_per_slot` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.TestSlotsTick.test_default_single_job` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_slot_counts_per_mode` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_same_project_never_twice` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_zero_slot_mode_never_starts_and_running_survives` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_remote_project_only_evren` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_review_slots.TestSlotsTick.test_evren_review_not_started_while_evren_self_verify_runs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_single_job_mode_also_skips_evren_during_verify` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_quota_blocked_target_skipped` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_freed_slot_refilled_next_tick` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestSlotsTick.test_min_gap_one_start_per_tick` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_review_slots.TestAgyHomeTokenPrivate.test_token_copy_is_0600_never_wider_and_replaces_symlink` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.TestReportFilesPrivateUtf8.test_write_report_utf8_0600_and_recover_partial_0600` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.TestClaudeIsError.test_is_error_message_is_not_a_report_but_real_report_is_kept` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyBlockClearedBySuccessTest.test_done_after_limit_clears_pool_block` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyBlockClearedBySuccessTest.test_done_before_block_or_other_pool_keeps_block` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyBlockClearedBySuccessTest.test_non_agy_block_unaffected_and_planner_picks_pool_again` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyBlockClearedBySuccessTest.test_set_block_records_set_at` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyUsageBlocksTest.test_parse` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyUsageBlocksTest.test_blocked_until_picks_window` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyUsageBlocksTest.test_reconcile_removes_stale_and_sets_five_hour` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyUsageBlocksTest.test_unknown_pool_untouched` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyUsageBlocksTest.test_fetch_reads_shared_usage_state_not_own_measure` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_slots.AgyUsageBlocksTest.test_refresh_skips_without_agy_targets` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.PureTest.test_parse_remote` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.PureTest.test_dest_guard_fails_closed_on_check_ignore_error` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.PureTest.test_dest_guard_localized_not_a_repo_is_rejected_not_open` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.PureTest.test_dest_guard` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.PureTest.test_unrecognized_remote_makes_repo_unknown_not_private` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.PureTest.test_visibility_any_public_wins_and_cache` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_dry_run_lists_without_touching_anything` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_commit_refuses_when_prv_remote_is_public_or_unverifiable` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_gitdir_visibility_classifies_remotes_fresh` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_visibility_cache_is_bounded` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_glob_chars_in_filename_are_literal` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_junk_files_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_secret_written_between_scan_and_add_is_unstaged` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_saved_page_files_dirs_are_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_act_commits_only_reviews_to_prv_and_pushes_both` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_unpushed_local_commit_is_pushed_on_next_run` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_no_commit_yet_and_nothing_new_is_noop` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_act_works_from_foreign_cwd` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.CommitTest.test_refuses_main_repo_git_dir` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.StoreCommitGateTest.test_off_dry_first_then_act_daily` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.ParseRemotePortTest.test_ssh_port_and_alt_hosts` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_review_store.ParseRemotePortTest.test_unknown_not_cached` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_stated_next.Helper.test_marker_next_work` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors (+3) |
| `test_stated_next.Keepwarm.test_keepwarm_sends_devam_with_next_not_ok` | idletext::next_work_hint_vectors, idletext::one_line_vectors, idletext::turn_failed_vectors, markers::p_bare_marker (+6) |
| `test_stated_next.IdleNudge.test_nudges_with_stated_next_even_with_empty_todo_and_ask_marker` | idle::plan_claude_idle_vectors, idletext::one_line_vectors, idletext::turn_failed_vectors, markers::p_bare_marker (+6) |
| `test_stated_next.IdleNudge.test_no_next_empty_todo_no_nudge_as_before` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+10) |
| `test_stated_next.IdleNudge.test_chain_limit_still_applies` | idle::plan_claude_idle_vectors, idletext::one_line_vectors, idletext::turn_failed_vectors, markers::p_bare_marker (+6) |
| `test_stated_next.TourItem.test_prompt_shows_stated_next_and_contradiction` | prompts::build_tour_prompt_vectors, prompts::p_clip |
| `test_statedocs_writers.WritersShadowTests.test_name_for` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_statedocs_writers.WritersShadowTests.test_steward_save_load_shadow` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_statedocs_writers.WritersShadowTests.test_steward_corrupt_backup_kept_and_db_recovers` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_statedocs_writers.WritersShadowTests.test_non_ready_docs_stay_file_even_in_db_mode` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_statedocs_writers.WritersShadowTests.test_ready_docs_db_only_in_db_mode` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_statedocs_writers.WritersShadowTests.test_mocked_writer_never_touches_db_or_file` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_statedocs_writers.WritersShadowTests.test_instances_shadow` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.TodoStatusTest.test_open_done_missing_and_path_safety` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.TodoStatusTest.test_candidates_only_exported` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.TodoStatusTest.test_secret_findings_are_held_back` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.PlanTest.test_p1_first_batch_limit_and_single_action` | prompts::p_is_project_session, world::pick_delivery_view_vectors, world::plan_deliveries_vectors |
| `test_steward_advance.PlanTest.test_only_own_open_and_idle` | prompts::p_is_project_session, world::pick_delivery_view_vectors, world::plan_deliveries_vectors |
| `test_steward_advance.PlanTest.test_resend_policy` | prompts::p_is_project_session, world::pick_delivery_view_vectors, world::plan_deliveries_vectors |
| `test_steward_advance.PlanTest.test_message_carries_authority_limits` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.RemoteAdvanceTest.test_remote_candidates_take_approved_without_todo_check` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.RemoteAdvanceTest.test_remote_secret_in_body_is_stripped_not_held` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.RemoteAdvanceTest.test_plan_delivers_to_remote_view_and_sends_once` | prompts::p_is_project_session, world::pick_delivery_view_vectors, world::plan_deliveries_vectors |
| `test_steward_advance.RemoteAdvanceTest.test_remote_todo_state_tracks_and_resends` | prompts::p_is_project_session, world::pick_delivery_view_vectors, world::plan_deliveries_vectors |
| `test_steward_advance.RemoteAdvanceTest.test_todo_status_text` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.RemoteAdvanceTest.test_remote_message_carries_detail_and_limits` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_advance.RemoteAdvanceTest.test_deliver_findings_passes_host` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_advance.TickE2E.test_exported_finding_delivered_once_then_done_line_stops_it` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_advance.TickE2E.test_done_line_never_sent_and_flag_off_sends_nothing` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_advance.TickE2E.test_act_mode_never_sends_secret_findings` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_advance.TickE2E.test_observe_mode_only_logs_would` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_advance.TickE2E.test_observe_does_not_change_state_and_repeats_only_when_set_changes` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_ago.AgoTest.test_units` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_answer_dialog_blocked.SendFailResult.test_dialog_reason_is_reported` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_answer_dialog_blocked.SendFailResult.test_plain_failure_stays_send_failed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_answer_dialog_blocked.LoopGuardDeliverAnswer.test_short_pause_then_retry` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_answer_dialog_blocked.LoopGuardDeliverAnswer.test_other_kinds_keep_long_pause` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_answer_dialog_blocked.PermissionDialog.test_classified_as_permission_not_pressed` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_steward_id_vectors |
| `test_steward_answer_dialog_blocked.PermissionDialog.test_brain_restart_refused_while_dialog_open_but_not_when_stale` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_steward_answer_dialog_blocked.TrustRecheckRace.test_stale_screen_after_accept_is_waited_out` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_answer_dialog_blocked.TrustRecheckRace.test_dialog_that_never_clears_still_fails` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_api_recovery.KindTest.test_classification` | recovery::api_error_kind_vectors |
| `test_steward_api_recovery.KindTest.test_network_and_cut_responses_are_retry` | recovery::api_error_kind_vectors |
| `test_steward_api_recovery.KindTest.test_brain_eai_again_gets_nudged` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.SingleSessionTest.test_backoff_nudges_then_giveup` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.SingleSessionTest.test_recovery_clears_state_and_new_error_resets` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.SingleSessionTest.test_untouched_when_busy_subagent_recent_activity_fatal_or_skipped` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.OutageTest.test_outage_single_notice_probe_then_grouped_wake` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.OutageTest.test_exhausted_outage_gives_up_instead_of_staying_silent` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.OutageTest.test_closed_probe_session_is_not_a_recovery` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.OutageTest.test_two_sessions_is_an_outage_one_is_not` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.PlanTickIntegrationTest.test_state_keys_absent_when_clean_and_present_when_stuck` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_api_recovery.PlanTickIntegrationTest.test_observe_mode_does_not_apply_nudge` | EKSİK: parite testi olmayan observe_filter |
| `test_steward_api_recovery.ApplyTest.test_nudge_sends_devam_to_tmux_session` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_api_recovery.ApplyTest.test_nudge_refused_when_not_tmux_or_not_running` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+13) |
| `test_steward_api_recovery.ApplyTest.test_giveup_and_outage_only_notify` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_api_recovery.WokenButStuckTest.test_woken_still_stuck_is_renudged_then_gives_up` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_api_recovery.WokenButStuckTest.test_state_clears_after_giveup` | recovery::api_error_kind_vectors, recovery::plan_api_recovery_vectors |
| `test_steward_append_note.AppendNote.test_merge` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_append_note.AppendNote.test_appends_to_existing_and_does_not_overwrite` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_append_note.AppendNote.test_conflicts_refused` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ask_gate.OwnerClassTest.test_plain_process_question_is_eligible` | gates::steward_ask_owner_class |
| `test_steward_ask_gate.OwnerClassTest.test_owner_only_classes` | gates::steward_ask_owner_class |
| `test_steward_ask_gate.OwnerClassTest.test_scans_options_detail_and_previous_texts` | gates::steward_ask_owner_class |
| `test_steward_ask_gate.OwnerClassTest.test_structural_classes` | gates::steward_ask_owner_class |
| `test_steward_ask_gate.OwnerClassTest.test_owner_projects_setting_and_project_note` | gates::steward_ask_owner_class |
| `test_steward_ask_gate.ConfigTest.test_defaults_and_validation` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_ask_gate.AnswerPathTest.test_off_is_unchanged_owner_only_and_hook_not_called` | gates::brain_may_answer_vectors, gates::long_texts_stay_within_regex_limits, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+29) |
| `test_steward_ask_gate.AnswerPathTest.test_on_allowed_closes_question_with_brain_prefix` | gates::panic_path_is_under_default_root, gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors (+34) |
| `test_steward_ask_gate.AnswerPathTest.test_on_denied_keeps_open_notifies_once_and_calls_gate_once` | gates::panic_path_is_under_default_root, gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors (+39) |
| `test_steward_ask_gate.AnswerPathTest.test_core_rechecks_the_three_conditions` | gates::panic_path_is_under_default_root, gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors (+39) |
| `test_steward_ask_gate.AnswerPathTest.test_missing_or_failing_hook_fails_closed` | gates::panic_path_is_under_default_root, gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors (+39) |
| `test_steward_ask_gate.AnswerPathTest.test_shadow_records_only` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+31) |
| `test_steward_ask_gate.AnswerPathTest.test_panic_turns_on_into_shadow` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+31) |
| `test_steward_ask_gate.AnswerPathTest.test_owner_class_never_reaches_gate` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+29) |
| `test_steward_ask_gate.AnswerPathTest.test_brain_cannot_defer_owner_question` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+29) |
| `test_steward_ask_gate.AnswerPathTest.test_owner_answer_in_between_is_not_overwritten` | gates::panic_path_is_under_default_root, gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, identity::brain_name_for_vectors (+32) |
| `test_steward_ask_gate.AnswerPathTest.test_answered_question_is_refused_without_gate_call` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+28) |
| `test_steward_ask_gate.TourTest.test_off_has_no_ask_items` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+27) |
| `test_steward_ask_gate.TourTest.test_eligible_ask_listed_owner_class_not` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, gates::steward_ask_tour_eligible, identity::brain_name_for_vectors (+31) |
| `test_steward_ask_gate.TourTest.test_seen_limits_and_gated` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, gates::steward_ask_tour_eligible, identity::brain_name_for_vectors (+31) |
| `test_steward_ask_gate.TourTest.test_tour_prompt_mentions_ask_item` | gates::steward_ask_blocked_reason, gates::steward_ask_owner_class, gates::steward_ask_tour_eligible, identity::brain_name_for_vectors (+32) |
| `test_steward_ask_gate.TourTest.test_cut_question_items_16_others_8` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_ask_gate.TourTest.test_plan_tick_sends_ask_and_records_seen` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ask_gate.DecisionsAndSummaryTest.test_owner_decisions_appended_to_brain_claude_md` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_ask_gate.DecisionsAndSummaryTest.test_summary_lists_brain_answers_override_and_shadow` | EKSİK: parite testi olmayan _ask_gate_lines, daily_summary |
| `test_steward_audit_p9.TestY1TransferredQuestionLink.test_old_link_with_the_previous_identity_still_finds_the_question_by_key` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+34) |
| `test_steward_audit_p9.TestY1TransferredQuestionLink.test_fallback_needs_the_key_not_just_the_id` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+30) |
| `test_steward_audit_p9.TestY1TransferredQuestionLink.test_find_question_any_prefers_the_stated_store` | identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+14) |
| `test_steward_audit_p9.TestY1TransferredQuestionLink.test_cli_answer_reports_the_other_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+30) |
| `test_steward_audit_p9.TestY2JobsAck.test_ack_on_an_open_job_is_refused_and_the_result_is_still_delivered_later` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_audit_p9.TestY2JobsAck.test_ack_on_a_terminal_job_still_works` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_audit_p9.TestY2JobsAck.test_ack_on_an_unknown_state_is_refused_too` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_audit_p9.TestO1BrainCannotCreateProjects.test_brain_upsert_of_a_new_name_is_refused_but_existing_updates_work` | cards::brain_pause_verdict_vectors, cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors (+32) |
| `test_steward_audit_p9.TestO1BrainCannotCreateProjects.test_human_may_still_create_a_project` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+18) |
| `test_steward_audit_p9.TestO1BrainCannotCreateProjects.test_brain_refusal_applies_in_other_identities_and_the_mcp_tool_marks_the_actor` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+5) |
| `test_steward_audit_p9.TestO2UnknownRemoteState.test_an_unknown_state_stays_open_keeps_polling_and_is_logged_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+10) |
| `test_steward_audit_p9.TestO2UnknownRemoteState.test_known_states_unchanged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_steward_audit_p9.TestO3TransferWriteOrder.test_failure_writing_the_destination_leaves_everything_at_the_source` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+26) |
| `test_steward_audit_p9.TestO3TransferWriteOrder.test_failure_writing_the_source_leaves_the_name_in_both_places_and_loses_nothing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+26) |
| `test_steward_audit_p9.TestO3TransferWriteOrder.test_successful_transfer_unchanged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+28) |
| `test_steward_audit_p9.TestO4OrphanBrain.test_degnekci_family_without_an_owner_is_another_brain_not_adhoc` | identity::brain_name_for_vectors, identity::p_project_key, world::world_for_vectors, world::world_name_class (+3) |
| `test_steward_audit_p9.TestO4OrphanBrain.test_remove_refuses_while_the_identity_brain_runs` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+2) |
| `test_steward_audit_p9.TestD5LockTimeoutAfterSend.test_lock_timeout_while_recording_the_directive_does_not_unmark_the_delivery` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+40) |
| `test_steward_audit_p9.TestD5LockTimeoutAfterSend.test_a_single_lock_timeout_on_the_delivery_mark_is_retried` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+40) |
| `test_steward_audit_p9.TestD5LockTimeoutAfterSend.test_persistent_lock_timeout_on_the_mark_is_logged_not_raised` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+39) |
| `test_steward_audit_p9.TestD5LockTimeoutAfterSend.test_next_tick_does_not_resend_what_already_went_out` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+40) |
| `test_steward_audit_p9.TestD5LockTimeoutAfterSend.test_job_delivery_mark_timeout_is_not_raised_either` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+38) |
| `test_steward_audit_p9.TestD8TransferTargetMustBeConfigured.test_unconfigured_target_is_refused_without_creating_a_directory` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_audit_p9.TestD8TransferTargetMustBeConfigured.test_configured_target_and_default_still_work` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_auto_start_off.AutoStart.test_default_true_and_field_exists` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_auto_start_off.AutoStart.test_source_guard` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestDefaultClaudeMdGolden.test_default_output_is_byte_identical_to_pre_p5` | prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors |
| `test_steward_brain.TestDefaultClaudeMdGolden.test_identity_section_only_for_non_default` | prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors |
| `test_steward_brain.TestWorkspace.test_default_workspace_claude_md_is_unchanged_and_not_rewritten` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+4) |
| `test_steward_brain.TestWorkspace.test_default_persona_override_still_applies` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_brain.TestWorkspace.test_identity_workspace_is_separate_with_identity_and_model_rule` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_brain.TestWorkspace.test_identity_persona_falls_back_to_shared` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_brain.TestBrainMcp.test_verify_uses_connect_heartbeat` | gates::brain_mcp_path_vectors, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_brain.TestBrainMcp.test_start_without_mcp_restarts_once_then_gives_up` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+7) |
| `test_steward_brain.TestBrainMcp.test_start_defaults_to_new_conversation` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+7) |
| `test_steward_brain.TestBrainMcp.test_close_note_written_without_model_turn` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+3) |
| `test_steward_brain.TestBrainMcp.test_notools_verdict_pure` | gates::brain_notools_verdict_vectors, gates::brain_tools_missing_text_vectors |
| `test_steward_brain.TestBrainMcp.test_recover_restarts_once_with_cooldown` | gates::brain_mcp_path_vectors, gates::brain_notools_verdict_vectors, gates::brain_tools_missing_text_vectors, identity::p_pp (+4) |
| `test_steward_brain.TestBrainMcp.test_mcp_server_heartbeat_hook` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestBrainMcp.test_touch_records_call_and_connect` | gates::brain_mcp_path_vectors, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_brain.TestBrainStart.test_brain_spec_default_is_the_old_command_line` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestBrainStart.test_disabled_identity_never_starts_a_brain` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+13) |
| `test_steward_brain.TestBrainStart.test_enabled_identity_starts_its_own_brain` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+7) |
| `test_steward_brain.TestBrainStart.test_default_brain_start_is_unchanged` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+6) |
| `test_steward_brain.TestBrainStart.test_running_brain_is_not_started_twice` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_brain.TestBrainStart.test_brain_stop_uses_only_the_act_stop_path_with_the_exact_name` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_brain.TestClaudeMcpConfigFile.test_identity_gets_its_own_config_file` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestMcpIdentity.test_default_server_adds_nothing` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestMcpIdentity.test_identity_server_adds_it_to_every_call_and_the_brain_cannot_change_it` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestMcpIdentity.test_run_validates_the_identity_and_sets_it` | identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_brain.TestMcpIdentity.test_cli_parses_the_flag` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_brain.TestCtxFor.test_resolution` | identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_brain.TestCtxFor.test_unknown_identity_is_an_explicit_error_and_writes_nothing` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_steward_brain.TestCtxFor.test_no_param_means_default_and_old_callers_work` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_brain.TestCtxFor.test_requests_reach_the_right_store` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_brain.TestCtxFor.test_manual_tick_and_note_and_skip_use_the_identity` | EKSİK: parite testi olmayan observe_filter, plan_tick |
| `test_steward_brain.TestHumanGate.test_human_in_default_context_is_unrestricted` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+31) |
| `test_steward_brain.TestHumanGate.test_human_in_other_context_only_own_projects_and_brain` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+31) |
| `test_steward_brain.TestHumanGate.test_brain_in_identity_context` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_brain.TestHumanGate.test_reads_are_limited_to_own_projects_outside_default` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+30) |
| `test_steward_bridges_e2e.LessonsBridge.test_reviewer_lesson_reaches_cli_session_once` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_bridges_e2e.LessonsBridge.test_lesson_masks_learned_password_in_error` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_bridges_e2e.LessonsBridge.test_lesson_already_sent_in_state_is_not_resent` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_bridges_e2e.LessonsBridge.test_waits_for_idle_session_and_never_starts_one` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_bridges_e2e.LessonsBridge.test_observe_mode_only_logs_would_and_disabled_project_sends_nothing` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_bridges_e2e.LessonsBridge.test_hand_written_and_old_lines_are_not_delivered` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_bridges_e2e.HandoverQuestions.test_open_question_travels_in_handover_extra` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+45) |
| `test_steward_bridges_e2e.HandoverQuestions.test_ask_user_notifies_once_and_again_only_on_promotion` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges (+23) |
| `test_steward_bridges_e2e.HandoverQuestions.test_directive_prior_answers_come_from_the_identitys_own_store` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+18) |
| `test_steward_bridges_e2e.HandoverQuestions.test_project_name_resolves_to_the_dated_session` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+42) |
| `test_steward_card_blockers_not_stale.CardBlockersNotStale.test_raw_card_has_no_blockers` | cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines, cards::raw_card_fields_vectors (+1) |
| `test_steward_card_blockers_not_stale.CardBlockersNotStale.test_make_card_without_parse_has_empty_blockers` | cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines, cards::raw_card_fields_vectors (+2) |
| `test_steward_card_blockers_not_stale.CardBlockersNotStale.test_fresh_parse_without_blockers_does_not_inherit_old` | cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines, cards::raw_card_fields_vectors (+2) |
| `test_steward_card_blockers_not_stale.CardBlockersNotStale.test_fresh_parse_blockers_are_used` | cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines, cards::raw_card_fields_vectors (+2) |
| `test_steward_claude_idle_stated.StatedNextWorkTest.test_extracts_last_stated_next` | idletext::next_line_vectors, idletext::stated_next_work_vectors, tour::clip_words_vectors |
| `test_steward_claude_idle_stated.StatedNextWorkTest.test_nothing_stated` | idletext::next_line_vectors, idletext::stated_next_work_vectors |
| `test_steward_claude_idle_stated.StatedNextWorkTest.test_explicit_next_line` | idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::stated_next_work_vectors, tour::clip_words_vectors |
| `test_steward_claude_idle_stated.StatedNextWorkTest.test_next_none_is_not_work` | idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::p_done_at_line_end, idletext::stated_next_work_vectors (+2) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_open_ownerless_todo_nudges_with_fixed_text` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+8) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_no_open_work_no_nudge` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+5) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_text_content_does_not_matter` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+10) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_next_none_stops_until_todo_changes` | idle::p_forced_open_nudge, idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors (+11) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_steward_next_none_marker_also_stops_and_new_activity_resumes` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+11) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_max_consecutive_kept` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+8) |
| `test_steward_claude_idle_work.WorkBasedNudgeTest.test_owner_wait_and_gate_still_skip` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::owner_wait_vectors (+6) |
| `test_steward_claude_idle_work.StewardNextMarkerTest.test_scan_next_marker_last_wins_and_ignores_fenced_and_prose` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_claude_idle_work.StewardNextMarkerTest.test_next_creates_no_question_or_decision` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors, tour::marker_record_actions_vectors |
| `test_steward_claude_idle_work.StewardNextMarkerTest.test_note_project_next_state` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors, tour::bad_state_types_are_errors (+2) |
| `test_steward_claude_idle_work.StewardNextMarkerTest.test_plan_markers_records_state` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors (+5) |
| `test_steward_claude_idle_work.StewardNextMarkerTest.test_explain_shows_next_work_and_next_none` | explain::explain_idle_all_vectors, explain::explain_idle_vectors, explain::p_why, idletext::idle_finish_marker_vectors (+13) |
| `test_steward_claude_idle_work.StewardNextMarkerTest.test_protocol_mentions_marker` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_claude_idle_work.FinishMarkerNegationTest.test_negative_phrasings_are_not_finished` | idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::p_done_at_line_end, markers::needs_ho_rfh_marker_in (+1) |
| `test_steward_claude_idle_work.FinishMarkerNegationTest.test_real_finish_still_detected` | idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::p_done_at_line_end, markers::needs_ho_rfh_marker_in (+1) |
| `test_steward_cli.TestSkipHandoverCommands.test_skip_and_handover_post_to_the_api` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_custom_id_vectors (+1) |
| `test_steward_cli.TestBrainCommand.test_bare_brain_is_read_only_status` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_steward_cli.TestBrainCommand.test_start_and_stop_are_explicit` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_custom_id_vectors (+1) |
| `test_steward_cli.TestBrainCommand.test_help_mentions_status` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_cli.TestSidResolution.test_flag_env_default_and_unknown` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_cli.TestSidResolution.test_data_commands_use_selected_store_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+18) |
| `test_steward_cli.TestSidResolution.test_api_body_default_unchanged_other_gets_steward` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_custom_id_vectors (+1) |
| `test_steward_cli.TestIdentityCommands.test_create_list_and_defaults_off` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_cli.TestIdentityCommands.test_remove_refuses_with_projects_then_moves_dir` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_cli.TestIdentityCommands.test_transfer_moves_record_questions_and_logs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+28) |
| `test_steward_cli.TestIdentityCommands.test_transfer_refusals` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_cli.TestIdentityCommands.test_transfer_moves_pending_jobs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_cli.TestConfigAndStatus.test_config_machine_key_warns_and_is_not_written` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_cli.TestConfigAndStatus.test_on_off_per_identity_and_off_all` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_cli.TestConfigAndStatus.test_status_prints_ownership_conflict_for_this_identity` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_cli.TestConfigAndStatus.test_default_status_output_has_no_new_lines` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_cli.TestNtfy.test_default_ask_is_byte_identical_to_before` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges (+29) |
| `test_steward_cli.TestNtfy.test_other_identity_title_prefix_and_link` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+32) |
| `test_steward_cli.TestNtfy.test_per_identity_topic_reaches_urlopen` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_steward_cli.TestSummaryPerIdentity.test_daily_summary_and_compact_are_per_identity` | EKSİK: parite testi olmayan _ask_gate_lines, daily_path, daily_summary, summary_due |
| `test_steward_cli.TestSummaryPerIdentity.test_default_summary_unchanged_call_shape` | EKSİK: parite testi olmayan _ask_gate_lines, daily_path, daily_summary, summary_due |
| `test_steward_cli.TestQuestionPage.test_s_param_and_legacy_search` | identity::brain_name_for_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::p_pp (+17) |
| `test_steward_cli.TestQuestionPage.test_post_answers_into_owning_store` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+27) |
| `test_steward_cli.TestQuestionPage.test_keys_do_not_collide_across_identities` | identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+13) |
| `test_steward_cli.TestQuestionPage.test_same_id_in_two_stores_prefers_matching_key` | identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+14) |
| `test_steward_cli.TestListAndStatusSlice.test_list_endpoint_and_stewards_slice` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_cli.TestListAndStatusSlice.test_default_summary_keys_unchanged` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_cli_jobs_service.JobsServiceTest.test_show_picks_named_service` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_cli_jobs_service.JobsServiceTest.test_show_unknown_service_errors` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_cli_jobs_service.JobsServiceTest.test_ack_marks_named_service` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_cli_stop.CmdStopTest.test_posts_stop_with_actor_cli` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_cli_stop.CmdStopTest.test_failure_returns_1` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.StoreTest.test_project_roundtrip_and_validation` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_core_a.StoreTest.test_defer_answer_keeps_question_open` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+15) |
| `test_steward_core_a.StoreTest.test_questions_dedup_answer_deliver` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+17) |
| `test_steward_core_a.StoreTest.test_ideas_and_log` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+4) |
| `test_steward_core_a.StoreTest.test_persona_override_and_bundled` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.MarkerTest.test_scan_markers_ask_ending_with_colon_takes_following_lines` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_a.MarkerTest.test_scan_markers_ignores_writing_examples` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_a.MarkerTest.test_scan_markers_ignores_inline_code_mention_in_prose` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_a.MarkerTest.test_scan_markers_job_line` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors (+1) |
| `test_steward_core_a.MarkerTest.test_scan_markers` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_a.PromptTest.test_directive_by_phase_and_answer` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, markers::reply_language_line_vectors (+2) |
| `test_steward_core_a.PromptTest.test_tour_prompt_lists_items_and_end_marker` | prompts::build_tour_prompt_vectors, prompts::p_clip |
| `test_steward_core_a.PromptTest.test_workspace_claude_md` | prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors |
| `test_steward_core_a.RulesTest.test_handover_then_respawn` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_handover_grace_expiry_and_gone_session` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_markers_once_per_reply` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_done_marker_stops_session` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_done_confirmed_with_open_owner_question_pauses_not_done` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_done_marker_ignored_when_project_notes_have_no_done_tag` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_due_projects_respect_slots_priority_and_cadence` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_todo_change_opens_active_project_without_waiting_cadence` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_todo_change_reopens_done_project_to_planned` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_todo_change_paused_project_asks_owner_once_per_day` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_first_observation_done_project_with_open_work_goes_planned` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_daily_sweep_done_project_with_unchanged_sha` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_daily_sweep_paused_asks_once` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_only_fable_cila_open_work_does_not_trigger` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_drain_starts_nothing_but_keeps_answers_and_running` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_slot_pressure_stops_idle_session` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_answer_delivery_running_busy_or_stopped` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_adhoc_session_answer_goes_to_asking_session_only_if_running` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_instance_sessions_map_to_blueprint_project` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_tour_only_when_brain_idle_and_due` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.RulesTest.test_phase_model_effort` | prompts::phase_model_effort_vectors |
| `test_steward_core_a.CardCoreTest.test_build_raw_card_reads_doc_heads_and_git` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.CardCoreTest.test_raw_card_without_git_or_docs` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.CardCoreTest.test_parse_card_json_variants` | cards::p_short, cards::p_str_list, cards::parse_card_json_vectors, prompts::p_clip |
| `test_steward_core_a.CardCoreTest.test_make_card_falls_back_to_raw_fields` | cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines, cards::raw_card_fields_vectors (+2) |
| `test_steward_core_a.CardCoreTest.test_refresh_reason_matrix_and_failure_backoff` | cards::card_path_vectors, cards::card_refresh_reason_vectors, cards::p_short, identity::p_pp (+4) |
| `test_steward_core_a.CardCoreTest.test_store_stale_and_listing` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::name_rules_edges, identity::p_pp (+4) |
| `test_steward_core_a.CardCoreTest.test_model_pick_prompt_and_tour_rendering` | cards::build_card_prompt_vectors, cards::p_short, cards::pick_card_model_vectors, prompts::build_tour_prompt_vectors (+2) |
| `test_steward_core_a.OneshotProviderTest.test_claude_argv_shape_and_unsupported_default` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.OneshotProviderTest.test_ucli_oneshot_uses_chat_once_without_key_in_argv` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.OneshotProviderTest.test_oneshot_runs_argv_and_reports_failures` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.SimilarAnswersTest.test_ranks_by_similarity_and_excludes_self` | questions::p_salient, questions::p_words, questions::similar_answers_vectors |
| `test_steward_core_a.SimilarAnswersTest.test_open_or_unanswered_ignored_and_prompt_renders` | prompts::build_tour_prompt_vectors, prompts::p_clip, questions::p_salient, questions::p_words (+1) |
| `test_steward_core_a.RosterGateTest.test_active_phase_needs_roster_but_idea_does_not` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+18) |
| `test_steward_core_a.ScanCacheTest.test_scan_is_cached_inside_a_scope_and_invalidated_by_start` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.EngineSmallsTest.test_fail_logged_is_pruned_and_thread_safe` | identity::normalize_host_edges, identity::normalize_host_vectors, identity::p_pp, identity::paths_for_vectors (+3) |
| `test_steward_core_a.EngineSmallsTest.test_shutdown_blockers_survive_corrupt_jobs_file` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+6) |
| `test_steward_core_a.ShutdownOnlyLeavesPausedTest.test_done_records_left_paused_and_warns` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_core_a.BrainCannotPauseTest.test_brain_cannot_pause_or_done_but_owner_can` | cards::brain_pause_verdict_vectors, cards::card_one_liner_vectors, cards::card_path_vectors, closing::bad_state_types_are_errors (+34) |
| `test_steward_core_a.ShutdownPlanTest.test_waits_for_quiet_then_handover_then_stop_then_brain` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_core_a.ShutdownPlanTest.test_subagent_blocks_and_timeouts_leave_session_open` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_core_a.ShutdownPlanTest.test_stale_ready_text_before_handover_does_not_count` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_core_a.ReviewFindings20261029Test.test_job_requests_for_different_files_are_not_merged` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_steward_core_a.ReviewFindings20261029Test.test_done_and_plan_ready_in_prose_are_ignored` | markers::p_bare_marker, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_a.ReviewFindings20261029Test.test_owner_only_false_positives` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.OpenQuestionMergeTest.test_paraphrased_open_question_is_merged` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+13) |
| `test_steward_core_a.OpenQuestionMergeTest.test_other_project_or_topic_not_merged` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+12) |
| `test_steward_core_a.OpenQuestionMergeTest.test_short_distinct_questions_not_merged` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+11) |
| `test_steward_core_a.OpenQuestionMergeTest.test_routine_question_promoted_when_asked_to_owner` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+12) |
| `test_steward_core_a.OpenQuestionMergeTest.test_answered_question_not_merged_into_open_path` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+15) |
| `test_steward_core_a.TopicMergeTest.test_topic_tokens` | questions::topic_tokens_vectors |
| `test_steward_core_a.TopicMergeTest.test_generic_names_alone_do_not_match` | questions::p_strong_topic, questions::topic_match_vectors, questions::topic_tokens_vectors |
| `test_steward_core_a.TopicMergeTest.test_open_question_rephrased_is_merged_and_keeps_old_text` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+16) |
| `test_steward_core_a.TopicMergeTest.test_hold_answer_suppresses_same_topic` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+18) |
| `test_steward_core_a.TopicMergeTest.test_non_hold_answer_lets_new_decision_open` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+15) |
| `test_steward_core_a.TopicMergeTest.test_old_open_question_outside_window_not_merged` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+11) |
| `test_steward_core_a.TopicMergeTest.test_other_project_not_merged` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+11) |
| `test_steward_core_a.SalientReaskTest.test_paraphrased_same_topic_is_duplicate` | questions::find_answered_duplicate_vectors, questions::p_salient, questions::p_words |
| `test_steward_core_a.SalientReaskTest.test_different_topic_not_duplicate` | questions::find_answered_duplicate_vectors, questions::p_salient, questions::p_words |
| `test_steward_core_a.DoneDeferralTest.test_done_deferred_while_subagent_then_applied` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneDeferralTest.test_deferred_done_dropped_when_no_done_tag_added_later` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneDeferralTest.test_done_immediate_without_subagent` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.AnswerStartPhaseTest.test_active_phase_starts` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.AnswerStartPhaseTest.test_owner_answer_reopens_paused_and_done_project` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.NegativeAnswerTest.test_is_negative_answer` | idletext::is_negative_answer_vectors |
| `test_steward_core_a.NegativeAnswerTest.test_negative_answer_does_not_reopen` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.NegativeAnswerTest.test_hold_answers_real_texts_do_not_reopen` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.NegativeAnswerTest.test_sweep_question_has_options` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.HeldInstructionAnswerTest.test_long_owner_instruction_reaches_brain` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.HeldInstructionAnswerTest.test_second_held_instruction_gets_its_own_item` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.HeldInstructionAnswerTest.test_later_question_does_not_overwrite_held_item` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.HeldInstructionAnswerTest.test_short_hold_brain_and_routine_answers_stay_silent` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_done_hands_over_then_stops_never_respawns` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_session_gone_during_done_handover_is_not_respawned` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_grace_expiry_still_stops` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_small_context_skips_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_switch_off_is_old_direct_stop` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_owner_answer_stops_reasking_and_bitti_closes` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_unknown_open_work_symlinked_worktree_accepts_proof` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneHandoverTest.test_unanswered_conflict_still_asks` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_plain_done_asks_for_confirmation_and_keeps_phase` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_second_plain_done_does_not_spam_but_ttl_reasks` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_confirmed_with_evidence_sets_done_and_stops` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_confirmed_without_evidence_is_not_done` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_confirmed_but_local_open_work_asks_owner_not_done` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_no_steward_done_tag_ignores_both_markers` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_confirm_marker_is_not_plain_done_and_placeholder_ignored` | markers::is_confirm_line_vectors, markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus (+1) |
| `test_steward_core_a.DoneConfirmTest.test_subagent_active_defers_confirmed` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.DoneConfirmTest.test_open_work_of_counts_local_todo` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.DoneConfirmTest.test_open_tbd_of_falls_back_to_main_worktree` | markers::count_open_tbd_edges, markers::count_open_tbd_vectors |
| `test_steward_core_a.TourQuietTest.test_skipped_unchanged_item_stays_out_until_state_changes_or_ttl` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, prompts::item_signature_vectors (+5) |
| `test_steward_core_a.TourQuietTest.test_plan_tick_records_tour_sig_and_honors_skip_seen` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.TourQuietTest.test_stale_undelivered_answer_closed_not_toured` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.TourQuietTest.test_projectless_answer_closes_when_brain_never_runs` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.TourQuietTest.test_brain_question_answer_goes_to_live_session_named_by_project` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.TourQuietTest.test_keepwarm_ok_does_not_change_the_item_signature_and_routine_carries_age` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, prompts::item_signature_vectors (+3) |
| `test_steward_core_a.TourQuietTest.test_observe_tour_does_not_burn_blocked_tour_budget` | EKSİK: parite testi olmayan observe_filter, plan_tick |
| `test_steward_core_a.TourQuietTest.test_pending_count_is_the_full_list_even_when_a_tour_is_sent` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.TourQuietTest.test_count_open_tbd_new_format_needs_an_AÇIK_heading` | markers::count_open_tbd_edges, markers::count_open_tbd_vectors |
| `test_steward_core_a.TourQuietTest.test_shutdown_unknown_activity_waits_unless_idle` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors |
| `test_steward_core_a.TourQuietTest.test_blocked_item_closed_after_max_tours_not_urgent_again` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.IdleSkipTest.test_no_idle_item_for_waiting_or_done_projects` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, prompts::item_signature_vectors (+5) |
| `test_steward_core_a.MergedAnswersTest.test_planner_merges_same_session_answers_in_one_action` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.MergedAnswersTest.test_answer_waits_while_subagent_active` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_a.MergedAnswersTest.test_subagent_active_for_reads_mtime` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_a.MergedAnswersTest.test_compact_answer_directive_drops_preamble` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, markers::reply_language_line_vectors (+2) |
| `test_steward_core_a.MergedAnswersTest.test_directive_contains_all_answers` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, markers::reply_language_line_vectors (+2) |
| `test_steward_core_b.ScanTicksTest.test_leading_code_tick_in_question_kept` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_b.ScanTicksTest.test_wrapped_marker_and_wrapped_body` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_b.PlanMarkersTest.test_records_asks_and_ideas_only` | gates::p_ask_is_status_line, markers::is_confirm_line_vectors, markers::p_bare_marker, markers::p_unwrap_ticks (+6) |
| `test_steward_core_b.PlanMarkersTest.test_same_reply_not_rescanned_and_routine_needs_question_mark` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors, tour::bad_state_types_are_errors (+3) |
| `test_steward_core_b.PlanMarkersTest.test_matches_plan_tick_marker_actions` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.ObserveCoreTest.test_filter_act_passes_everything_and_clears_traces` | EKSİK: parite testi olmayan observe_filter |
| `test_steward_core_b.ObserveCoreTest.test_filter_observe_splits_dedups_and_prunes` | EKSİK: parite testi olmayan observe_filter |
| `test_steward_core_b.ObserveCoreTest.test_observed_visit_paces_due_projects_across_ticks` | EKSİK: parite testi olmayan observe_filter, plan_tick |
| `test_steward_core_b.SummaryCoreTest.test_daily_summary_counts_and_filters_by_date` | EKSİK: parite testi olmayan _ask_gate_lines, _kind_counts, _names, daily_summary |
| `test_steward_core_b.SummaryCoreTest.test_summary_due` | EKSİK: parite testi olmayan summary_due |
| `test_steward_core_b.SummaryCoreTest.test_log_reader_and_summary_text` | EKSİK: parite testi olmayan _ask_gate_lines, _kind_counts, _names, daily_path |
| `test_steward_core_b.SummaryCoreTest.test_compact_log_folds_ticks_and_keeps_summary_identical` | EKSİK: parite testi olmayan _ask_gate_lines, _kind_counts, _names, daily_summary |
| `test_steward_core_b.SummaryCoreTest.test_missed_summary_dates_and_catch_up` | EKSİK: parite testi olmayan _ask_gate_lines, _names, daily_path, daily_summary |
| `test_steward_core_b.RoutineQuestionTest.test_marker_scan_and_session_reply_opens_routine_ask` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.RoutineQuestionTest.test_routine_goes_to_brain_tour_not_phone_and_escalates_late` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.RoutineQuestionTest.test_brain_answer_is_delivered_like_any_answer` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_finished_handover_of_second_session_stops_it_instead_of_respawn` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_economy_rules_only_touch_managed_sessions` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_brain_respawn_after_handover_is_a_new_conversation` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_context_tokens_trigger_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_line_count_is_only_a_fallback_and_ignores_young_sessions` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_workspace_claude_md_carries_the_permanent_model_rule` | prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_fable_sessions_use_the_lower_context_threshold` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.OneLiveSessionPerProjectTest.test_context_tokens_from_transcript_tail` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.StuckBrainTest.test_status_sentence_is_not_a_routine_question_and_tour_is_capped` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.StuckBrainTest.test_two_failed_tours_restart_the_brain` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_core_b.StuckBrainTest.test_undeliverable_adhoc_answer_is_given_up` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+27) |
| `test_steward_core_b.DeliveryTargetTest.test_prefers_asking_session_then_main_over_experiment_sessions` | world::pick_delivery_view_vectors |
| `test_steward_core_b.ReaskTest.test_similar_answered_question_is_redelivered_not_reopened` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+20) |
| `test_steward_core_b.ReaskTest.test_repeat_cap_other_project_old_and_clarification_open_new` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_steward_core_b.ReaskTest.test_answered_routine_question_asked_to_owner_opens_new` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+12) |
| `test_steward_core_b.ReaskTest.test_directive_lists_earlier_answers` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+19) |
| `test_steward_core_b.QuestionOptionsTest.test_options_normalize_resolve_and_key` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+17) |
| `test_steward_core_b.QuestionOptionsTest.test_notification_text_and_page_html` | identity::normalize_host_edges, identity::normalize_host_vectors, notify::ask_hint_vectors, notify::ask_prefix_vectors (+2) |
| `test_steward_core_b.SettingsTest.test_defaults_parse_and_clamp` | identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_core_b.McpTest.test_tools_list_and_dispatch_cover_each_other` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.McpTest.test_tool_calls_hit_expected_endpoints` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.JobMarkerParseTest.test_hyphenated_kind_and_malformed_body_are_not_dropped` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_b.JobMarkerParseTest.test_prose_mentions_and_placeholders_still_ignored` | markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors |
| `test_steward_core_b.QuestionPageHttpTest.test_question_page_round_trip` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+25) |
| `test_steward_core_b.QuestionPageHttpTest.test_notify_phone_sets_click_header` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_non_routine_question_is_owner_only` | gates::brain_may_answer_vectors, gates::long_texts_stay_within_regex_limits |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_routine_owner_only_topics` | gates::brain_may_answer_vectors, gates::is_readonly_job_request_vectors, gates::long_texts_stay_within_regex_limits |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_commit_push_merge_build_deploy_are_not_owner_only` | gates::brain_may_answer_vectors, gates::long_texts_stay_within_regex_limits |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_blocked_marker_goes_to_brain_not_owner` | tour::marker_record_actions_vectors |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_rules_text_no_longer_reserves_commit_push_for_owner` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_readonly_job_request_not_owner_only` | gates::brain_may_answer_vectors, gates::is_readonly_job_request_vectors, gates::long_texts_stay_within_regex_limits |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_plain_routine_is_answerable` | gates::brain_may_answer_vectors, gates::long_texts_stay_within_regex_limits |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_defer_reason` | gates::directive_defer_reason_vectors |
| `test_steward_core_b.BrainAuthorityAndDeferTest.test_tour_retry_gap_after_deferral` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.TourDeliveryTest.test_short_tour_inline` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.TourDeliveryTest.test_long_tour_goes_to_file_and_old_files_pruned` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.ShutdownKeepModeTest.test_keep_does_not_stop` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_core_b.ShutdownKeepModeTest.test_default_stops` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_core_b.ShutdownOnlyTest.test_only_closes_selected_project_and_leaves_rest` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_core_b.ShutdownBlockersTest.test_quiet_session_without_blocker_gets_handover` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors |
| `test_steward_core_b.ShutdownBlockersTest.test_blocked_session_waits_and_records_reason` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors |
| `test_steward_core_b.ShutdownBlockersTest.test_blocked_session_left_open_after_wait_max` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors |
| `test_steward_core_b.SmartTickTest.test_count_open_tbd` | markers::count_open_tbd_edges, markers::count_open_tbd_vectors |
| `test_steward_core_b.SmartTickTest.test_routine_question_skips_tour_interval` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.SmartTickTest.test_done_confirmed_with_open_tbd_asks_owner` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.SmartTickTest.test_tbd_only_project_not_started_owner_asked_once` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.SmartTickTest.test_brain_stopped_project_not_restarted_by_cadence_until_cooldown` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.SmartTickTest.test_idle_session_without_open_todo_not_nudged` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, prompts::item_signature_vectors (+5) |
| `test_steward_core_b.AskStatusLineTests.test_status_lines_do_not_open_records` | gates::p_ask_is_status_line, tour::marker_record_actions_vectors |
| `test_steward_core_b.AskBaseTests.test_dated_session_name_collapses_to_base` | gates::p_ask_is_status_line, tour::marker_record_actions_vectors, tour::p_ask_base |
| `test_steward_core_b.DeferAnswerTests.test_is_defer_answer` | questions::is_defer_answer_vectors |
| `test_steward_core_b.DeferAnswerTests.test_digest_hides_deferred_until_expiry` | notify::pending_digest_text_vectors |
| `test_steward_core_b.StartDecisionEventTests.test_event_shape` | tour::bad_state_types_are_errors, tour::start_decision_event_vectors |
| `test_steward_core_b.ExpiredHandoverNoteTest.test_note_helper` | idletext::expired_handover_note_vectors |
| `test_steward_core_b.ExpiredHandoverNoteTest.test_expired_without_marker_carries_note` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.ExpiredHandoverNoteTest.test_ready_marker_has_no_card_note` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_core_b.UcliStuckLadderTest.test_shorten_helper` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.UcliStuckLadderTest.test_ladder` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_core_b.RemoteRespawnNoteTest.test_note_reaches_directive` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_core_b.RemoteRespawnNoteTest.test_no_note_keeps_empty_directive` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_ctx.ContextQuestionTest.test_classifier` | closing::is_context_question_vectors, gates::long_texts_stay_within_regex_limits |
| `test_steward_ctx.ContextQuestionTest.test_low_context_continues_without_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.ContextQuestionTest.test_high_context_hands_over` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.ContextQuestionTest.test_unknown_context_or_disabled_leaves_question` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.ContextQuestionTest.test_over_threshold_single_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.PausedProjectNoContextHandoverTest.test_paused_over_threshold_sends_no_handover_on_any_tick` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.PausedProjectNoContextHandoverTest.test_done_project_also_gets_no_threshold_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.PausedProjectNoContextHandoverTest.test_planned_project_still_hands_over_at_threshold` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.PausedProjectNoContextHandoverTest.test_context_question_on_paused_project_does_not_start_a_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_pure_decision` | closing::handover_defer_decision_vectors |
| `test_steward_ctx.HandoverDeferTest.test_subagent_active_defers_then_hands_over_when_quiet` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_busy_and_unknown_defer` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_history_fallback_defers_too` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_force_by_ratio` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_force_by_time` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_defer_disabled_keeps_old_behaviour` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_below_threshold_drops_deferral` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_brain_same_rule` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_no_second_action_while_deferred` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_context_question_path_defers` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ctx.HandoverDeferTest.test_engine_logs_deferral` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_dialog_stuck.ClassifyTest.test_kinds` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.ClassifyTest.test_history_mention_is_not_dialog` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.ClassifyTest.test_head_is_first_two_lines` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.RecoverTest.test_unknown_dialog_presses_no_keys_and_notifies_once` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_steward_id_vectors |
| `test_steward_dialog_stuck.RecoverTest.test_trust_unregistered_folder_not_touched` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_steward_id_vectors |
| `test_steward_dialog_stuck.RecoverTest.test_trust_registered_folder_accepted` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.RecoverTest.test_accepted_then_waits_for_prompt_marker_before_send` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.RecoverTest.test_wait_prompt_ready_times_out_but_does_not_block` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.RecoverTest.test_wait_prompt_ready_immediate` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_dialog_stuck.RecoverTest.test_send_fail_streak_notifies` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_steward_id_vectors |
| `test_steward_dialog_stuck.ExplainTest.test_dialog_stuck_and_send_failed_codes` | explain::explain_idle_all_vectors, explain::explain_idle_vectors, explain::p_why, idletext::next_work_hint_vectors (+2) |
| `test_steward_digests.TestDigests.test_empty` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_digests.TestDigests.test_order_and_cap` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_digests.TestDigests.test_read_and_redact` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_digests.TestDigests.test_size_cap` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_digests.TestDigests.test_path_safety` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_digests.TestDigests.test_other_identity_and_reviewer` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_steward_directive_retry.ClientRetry.test_timeout_then_success_same_did_long_timeout` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_directive_retry.ClientRetry.test_all_attempts_timeout_reports_unknown_outcome` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_directive_retry.ClientRetry.test_real_errors_are_not_retried` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_directive_retry.ServerDedupe.test_same_did_delivers_once` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::name_rules_edges, identity::valid_name_vectors |
| `test_steward_directive_retry.ServerDedupe.test_bad_did_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+10) |
| `test_steward_directive_retry.ServerDedupe.test_failed_delivery_not_cached` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::name_rules_edges, identity::valid_name_vectors |
| `test_steward_directive_trace.Trace.test_trace_has_sha1_prefix_and_delivered_flag` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_directive_trace.Trace.test_empty_text_has_no_hash` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_directive_trace.DeferLogged.test_deferred_event_carries_hash_and_not_delivered` | gates::directive_defer_reason_vectors, identity::normalize_host_edges, identity::normalize_host_vectors |
| `test_steward_directive_trace.DeferLogged.test_old_call_without_text_still_works` | gates::directive_defer_reason_vectors, identity::normalize_host_edges, identity::normalize_host_vectors |
| `test_steward_engine_multi.TestTwoIdentityTick.test_each_identity_acts_only_on_its_own_and_writes_only_its_own_files` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick, summarize_projects |
| `test_steward_engine_multi.TestTwoIdentityTick.test_markers_land_in_the_owners_store_adhoc_only_default` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_engine_multi.TestTwoIdentityTick.test_max_starts_total_is_shared_across_identities` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_engine_multi.TestTwoIdentityTick.test_max_active_total_counts_the_other_identity` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_engine_multi.TestTwoIdentityTick.test_disabled_identity_is_skipped` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_engine_multi.TestTwoIdentityTick.test_one_identity_failing_does_not_skip_the_other` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_engine_multi.TestTwoIdentityTick.test_manual_action_does_not_wait_for_another_identitys_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_engine_multi.TestTwoIdentityTick.test_restart_does_not_deadlock_on_its_own_lock` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+32) |
| `test_steward_engine_multi.TestIdentityGate.test_engine_of_one_identity_cannot_touch_the_other` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_engine_multi.TestIdentityGate.test_global_prefix_resolution` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_engine_multi.TestIdentityGate.test_human_calls_are_unrestricted` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_engine_multi.TestIdentityGate.test_non_default_brain_is_governed_like_default_p5` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+22) |
| `test_steward_engine_multi.TestConflictAndRegister.test_ownership_conflict_logged_once_a_day_and_in_status` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick, summarize_projects |
| `test_steward_engine_multi.TestConflictAndRegister.test_no_conflict_key_without_conflicts` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick, summarize_projects |
| `test_steward_engine_multi.TestConflictAndRegister.test_register_checks_claim_before_side_effects_and_warns_on_prefix` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+24) |
| `test_steward_engine_multi.TestEngineGolden.test_default_tick_once_matches_golden` | EKSİK: parite testi olmayan daily_path, dry_ask_due, observe_filter, plan_tick |
| `test_steward_explain_idle.Explain.test_phase` | explain::explain_idle_vectors, explain::p_why |
| `test_steward_explain_idle.Explain.test_notes_wait_and_cadence` | explain::explain_idle_vectors, explain::p_why, idletext::notes_wait_vectors, idletext::one_line_vectors |
| `test_steward_explain_idle.Explain.test_questions` | explain::explain_idle_vectors, explain::p_why, idletext::notes_wait_vectors, idletext::one_line_vectors |
| `test_steward_explain_idle.Explain.test_not_running_decisions` | explain::explain_idle_vectors, explain::p_why, identity::derived_of_vectors, identity::p_project_key (+1) |
| `test_steward_explain_idle.Explain.test_loop_guard` | explain::explain_idle_vectors, explain::p_why, idletext::notes_wait_vectors |
| `test_steward_explain_idle.Explain.test_running_session_reasons` | explain::explain_idle_vectors, explain::p_why, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors (+16) |
| `test_steward_explain_idle.Explain.test_matches_engine_nudge_decision` | explain::explain_idle_vectors, explain::p_why, idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors (+14) |
| `test_steward_explain_idle.Explain.test_all_and_lang` | explain::explain_idle_all_vectors, explain::explain_idle_vectors, explain::p_why |
| `test_steward_explain_idle.ConfigAndLoopReset.test_new_ui_keys` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_explain_idle.ConfigAndLoopReset.test_loop_reset_human_only` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_generic.TestConfig.test_generic_defaults_to_sonnet_medium` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_generic.TestConfig.test_own_block_is_the_owners_explicit_choice` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_generic.TestConfig.test_default_can_never_be_generic` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_generic.TestCreate.test_http_create_with_role_generic` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_generic.TestCreate.test_cli_create_with_role_generic` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_generic.TestCreate.test_list_row_carries_role_generic` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_generic.TestBrainMd.test_generic_section_only_for_generic` | prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors |
| `test_steward_generic.TestBrainMd.test_ensure_workspace_writes_generic_section` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_generic.TestBacklog.test_classification` | cards::p_short, gates::generic_backlog_vectors, prompts::p_clip |
| `test_steward_generic.TestBacklog.test_empty_and_dedup_and_cap` | cards::p_short, gates::generic_backlog_vectors, prompts::p_clip |
| `test_steward_generic.TestBacklog.test_tour_prompt_renders_backlog_only_when_present` | prompts::build_tour_prompt_vectors, prompts::p_clip |
| `test_steward_generic.TestUpperTier.test_is_upper_tier` | gates::is_upper_tier_vectors |
| `test_steward_generic.TestUpperTier.test_approval_is_specific_to_project_model_effort` | gates::upper_tier_approved_vectors, gates::upper_tier_question_text_vectors, gates::upper_tier_tag_vectors |
| `test_steward_generic.TestUpperGate.test_brain_directive_to_opus_refused_and_question_opened_once` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::brain_may_answer_vectors, gates::is_generic_vectors (+57) |
| `test_steward_generic.TestUpperGate.test_owner_approval_opens_the_gate` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::is_generic_vectors, gates::is_upper_tier_vectors (+58) |
| `test_steward_generic.TestUpperGate.test_owner_rejection_keeps_it_closed` | gates::is_generic_vectors, gates::is_upper_tier_vectors, gates::panic_path_is_under_default_root, gates::upper_tier_approved_vectors (+55) |
| `test_steward_generic.TestUpperGate.test_human_and_non_generic_are_free` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::is_generic_vectors, gates::is_upper_tier_vectors (+34) |
| `test_steward_generic.TestUpperGate.test_restart_refused_before_stop` | gates::is_generic_vectors, gates::is_upper_tier_vectors, gates::upper_tier_approved_vectors, gates::upper_tier_question_text_vectors (+51) |
| `test_steward_generic.TestUpperGate.test_set_project_gate` | cards::card_one_liner_vectors, cards::card_path_vectors, gates::is_generic_vectors, gates::is_upper_tier_vectors (+40) |
| `test_steward_generic.TestUpperGate.test_register_gate_before_side_effects` | gates::is_generic_vectors, gates::is_upper_tier_vectors, gates::upper_tier_approved_vectors, gates::upper_tier_question_text_vectors (+38) |
| `test_steward_generic.TestDynamicProjects.test_remove_is_human_only_and_logged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_generic.TestDynamicProjects.test_cli_drop` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_generic.TestDynamicProjects.test_panel_add_then_tick_treats_it_as_normal_project` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+19) |
| `test_steward_generic.TestTourBacklog.test_generic_tour_item_has_backlog` | cards::p_short, gates::generic_backlog_vectors, gates::is_generic_vectors, identity::brain_name_for_vectors (+28) |
| `test_steward_generic.TestTourBacklog.test_plain_steward_tour_is_unchanged` | gates::is_generic_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_get_paths_complete.GetPathsCompleteTest.test_every_handled_get_path_is_registered` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_handover_log_session.HandoverLogSessionTest.test_log_has_session_name` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_handover_questions.HandoverQuestionsTest.test_note_lists_only_own_open_questions` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+16) |
| `test_steward_handover_questions.HandoverQuestionsTest.test_note_is_bounded` | notify::handover_questions_note_vectors |
| `test_steward_handover_questions.HandoverQuestionsTest.test_local_handover_passes_extra_only_when_open_questions` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+21) |
| `test_steward_ho_halted.HoHaltedTest.test_paused_ready_no_respawn_session_stays` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_halted.HoHaltedTest.test_paused_session_gone_no_start` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_halted.HoHaltedTest.test_done_ready_no_respawn` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_halted.HoHaltedTest.test_planned_unchanged_respawn_and_start` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_halted.HoHaltedTest.test_planning_unchanged` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_halted.HoHaltedTest.test_done_close_flow_still_stops` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_halted.HoHaltedTest.test_paused_busy_waits_then_halts` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ho_on_open.ResumeLacksHoTest.test_work_without_ho_is_detected` | markers::needs_ho_rfh_marker_in |
| `test_steward_ho_on_open.ResumeLacksHoTest.test_ho_done_is_clean` | markers::needs_ho_rfh_marker_in |
| `test_steward_ho_on_open.ResumeLacksHoTest.test_new_request_after_ho_needs_ho_again` | markers::needs_ho_rfh_marker_in |
| `test_steward_ho_on_open.ResumeLacksHoTest.test_empty_conversation_is_clean` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ho_on_open.ResumeLacksHoTest.test_off_and_non_claude_and_ucli_record` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ho_on_open.ResumeLacksHoTest.test_missing_jsonl` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ho_on_open.EnsureRunningHoOnOpenTest.test_lacking_ho_resumes_then_hands_over` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_ho_on_open.EnsureRunningHoOnOpenTest.test_clean_open_no_handover` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_ho_on_open.EnsureRunningHoOnOpenTest.test_handover_failure_no_pending` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_http.HttpTest.test_idea_export_project_todo_hides_idea_and_keeps_record` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_http.HttpTest.test_idea_export_all_tbd_and_idempotent` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_http.HttpTest.test_idea_export_appends_under_existing_heading_and_validates` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_http.HttpTest.test_running_names_resolve_digit_in_project_name` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+15) |
| `test_steward_http.HttpTest.test_project_ask_answer_idea_note` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_http.HttpTest.test_ask_with_options_notifies_with_link_once` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges (+34) |
| `test_steward_http.HttpTest.test_question_page_auth_and_answer_flow` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+25) |
| `test_steward_http.HttpTest.test_register_creates_folder_goal_and_roster` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+31) |
| `test_steward_http.HttpTest.test_tick_applies_actions_with_mocked_views` | EKSİK: parite testi olmayan daily_path, dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.HttpTest.test_refresh_card_writes_summary_and_logs` | cards::build_card_prompt_vectors, cards::card_path_vectors, cards::p_short, cards::p_str_list (+31) |
| `test_steward_http.HttpTest.test_refresh_card_failure_keeps_old_card_or_writes_raw` | cards::build_card_prompt_vectors, cards::card_path_vectors, cards::p_short, cards::p_str_list (+32) |
| `test_steward_http.HttpTest.test_refresh_due_cards_rules` | cards::build_card_prompt_vectors, cards::card_path_vectors, cards::card_refresh_reason_vectors, cards::p_goal_from_docs (+34) |
| `test_steward_http.HttpTest.test_tick_runs_card_step_unless_disabled` | EKSİK: parite testi olmayan daily_path, dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.HttpTest.test_respawn_marks_card_stale` | cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+31) |
| `test_steward_http.HttpTest.test_cards_in_context_projects_and_api` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_http.HttpTest.test_observe_tick_records_would_and_touches_nothing` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick, summarize_projects |
| `test_steward_http.HttpTest.test_observe_still_runs_questions_ideas_and_phase_changes` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.HttpTest.test_act_mode_applies_and_logs_actions` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.HttpTest.test_brain_calls_are_dry_in_observe_but_cli_calls_apply` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::directive_defer_reason_vectors, gates::is_upper_tier_vectors (+35) |
| `test_steward_http.HttpTest.test_brain_cannot_touch_unregistered_session` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::panic_path_is_under_default_root, identity::brain_name_for_vectors (+24) |
| `test_steward_http.HttpTest.test_brain_may_touch_brain_and_registered_projects` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_http.HttpTest.test_apply_gate_denies_engine_actions_on_unregistered_sessions` | identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+16) |
| `test_steward_http.HttpTest.test_daily_summary_runs_once_after_hour_and_notifies` | EKSİK: parite testi olmayan _ask_gate_lines, daily_path, daily_summary, dry_ask_due |
| `test_steward_http.HttpTest.test_summary_api_and_cli` | EKSİK: parite testi olmayan _ask_gate_lines, _names, daily_path, daily_summary |
| `test_steward_http.HttpTest.test_handover_route_marks_pending` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+12) |
| `test_steward_http.JobRequestGateTest.test_gate_pure` | gates::bad_values_are_errors, gates::job_request_gate_vectors |
| `test_steward_http.JobRequestGateTest.test_brain_bare_devam_rejected_owner_allowed` | gates::bad_values_are_errors, gates::brain_may_answer_vectors, gates::job_request_gate_vectors, gates::long_texts_stay_within_regex_limits (+18) |
| `test_steward_http.JobRequestGateTest.test_brain_red_closes_and_opens_owner_question` | gates::bad_values_are_errors, gates::brain_may_answer_vectors, gates::job_request_gate_vectors, gates::long_texts_stay_within_regex_limits (+36) |
| `test_steward_http.JobRequestGateTest.test_red_feedback_to_project_session_and_no_repeat_owner_question` | gates::bad_values_are_errors, gates::brain_may_answer_vectors, gates::job_request_gate_vectors, gates::long_texts_stay_within_regex_limits (+36) |
| `test_steward_http.JobRequestGateTest.test_job_kinds_list_shapes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_http.JobRequestGateTest.test_brain_answer_after_submit_ok` | gates::bad_values_are_errors, gates::brain_may_answer_vectors, gates::job_request_gate_vectors, gates::long_texts_stay_within_regex_limits (+11) |
| `test_steward_http.SkipMemoryHttpTest.test_skip_records_signature_from_last_tour` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+10) |
| `test_steward_http.SkipMemoryHttpTest.test_close_stale_answer_action_marks_delivered` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+23) |
| `test_steward_http.ActionJournalTest.test_crash_between_state_save_and_apply_replays_once` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.ActionJournalTest.test_normal_tick_leaves_no_journal_and_no_duplicates` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.ActionJournalTest.test_replay_skips_duplicate_idea` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.DryReportTest.test_report_counts_and_window` | EKSİK: parite testi olmayan dry_report_text |
| `test_steward_http.DryReportTest.test_ask_due_only_known_kip_after_72h_once` | EKSİK: parite testi olmayan dry_ask_due |
| `test_steward_http.DryReportTest.test_maybe_dry_ask_opens_one_question_and_not_again` | EKSİK: parite testi olmayan dry_ask_due, dry_report_text |
| `test_steward_http.DryReportTest.test_no_ask_when_kip_already_act` | EKSİK: parite testi olmayan dry_ask_due |
| `test_steward_http.BrainWakeGateTest.test_brain_directive_capped_per_day_separately_from_due` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_http.BrainWakeGateTest.test_brain_gate_dry_logs_would_and_sends` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_http.WakeGateTest.test_first_send_never_gated_then_repeat_dry_logs_but_sends_act_skips` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_http.WakeGateTest.test_gate_is_skipped_when_the_directive_just_opened_the_session` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+5) |
| `test_steward_http.WakeGateTest.test_other_text_other_reason_answer_off_and_window` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_http.BigResumeTest.test_oversized_detection` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_http.BigResumeTest.test_small_unknown_other_cli_and_off_keep_resume` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_http.BigResumeTest.test_ensure_running_starts_fresh_for_big_context` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+10) |
| `test_steward_http.WakeCapPanicTest.test_daily_cap_dry_and_act_and_reset_on_answer` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_http.WakeCapPanicTest.test_panic_flag_forces_observe_and_blocks_brain_directive` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_http.BlockedEscalationTest.test_blocked_waits_four_hours_routine_thirty_minutes` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_http.BlockedEscalationTest.test_owner_only_denial_escalates_routine_immediately` | gates::brain_may_answer_vectors, gates::is_readonly_job_request_vectors, gates::long_texts_stay_within_regex_limits, identity::build_ownership_index_vectors (+31) |
| `test_steward_http.BlockedEscalationTest.test_owner_only_denial_blocks_brain_directive_until_answered` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, gates::brain_may_answer_vectors, gates::is_readonly_job_request_vectors (+55) |
| `test_steward_http.BlockedEscalationTest.test_owner_pending_block_pure` | gates::owner_pending_block_vectors |
| `test_steward_http.BlockedEscalationTest.test_protocol_and_guide_derive_from_owner_topics` | prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors |
| `test_steward_hyphen_names.ValidNameTest.test_hyphen_rules` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_steward_hyphen_names.HyphenProjectTest.test_store_and_session_mapping` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+15) |
| `test_steward_hyphen_names.HyphenProjectTest.test_shorter_prefix_does_not_claim` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+15) |
| `test_steward_job_gate_and_qcap.Verdict.test_real_request` | gates::job_marker_verdict_vectors |
| `test_steward_job_gate_and_qcap.Verdict.test_status_notes` | gates::job_marker_verdict_vectors |
| `test_steward_job_gate_and_qcap.Verdict.test_unknown_kind_and_no_service` | gates::job_marker_verdict_vectors |
| `test_steward_job_gate_and_qcap.Verdict.test_catalog_unreachable_skips_kind_check_only` | gates::job_marker_verdict_vectors |
| `test_steward_job_gate_and_qcap.Cap.test_open_question_cap_appends_extra` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+11) |
| `test_steward_job_gate_and_qcap.Cap.test_other_project_job_and_routine_unaffected` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+11) |
| `test_steward_job_gate_and_qcap.Cap.test_bare_choice_answers_only_main_and_reopens_extras` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_steward_job_gate_and_qcap.Cap.test_written_answer_closes_extras_too` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_steward_job_gate_and_qcap.Cap.test_answered_frees_slot` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_steward_job_gate_and_qcap.Gate.test_rejected_without_service_no_question` | gates::job_marker_verdict_vectors, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_job_gate_and_qcap.KindsCatalogue.test_parse_both_shapes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_job_gate_and_qcap.KindsCatalogue.test_closest_three` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_job_gate_and_qcap.KindsCatalogue.test_format` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_job_gate_and_qcap.KindsCatalogue.test_prompts_mention_catalogue` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_job_gate_and_qcap.TourLoopSig.test_changing_items_do_not_trip` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_job_gate_and_qcap.TourLoopSig.test_same_items_same_reply_trip` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_job_gate_and_qcap.GateMessage.test_note_has_catalogue_hint_file_rule_and_closest_kinds` | gates::job_marker_verdict_vectors, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_jobs.TestServiceRegistry.test_add_list_rm_without_token_in_records` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestServiceRegistry.test_validation` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestServiceRegistry.test_service_name_cannot_shadow_a_project_and_projects_cannot_take_service_names` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestServiceRegistry.test_token_file_permission_warning` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestPassiveService.test_target_denies_everyone_for_service_sessions` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_jobs.TestPassiveService.test_every_http_action_refuses_service_sessions` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_jobs.TestPassiveService.test_tick_never_touches_a_service_session` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestSubmit.test_json_submit_contract_and_local_record` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_same_request_is_idempotent_locally_and_on_the_server` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_failed_or_lost_job_can_be_resubmitted_but_live_or_done_cannot` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_multipart_upload_with_project_files` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_file_path_escape_is_refused` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+18) |
| `test_steward_jobs.TestSubmit.test_only_own_registered_projects` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+20) |
| `test_steward_jobs.TestSubmit.test_unregistered_service_and_server_errors` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_service_down_at_submit_is_reported_not_raised` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_observe_mode_brain_submit_is_only_recorded` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestSubmit.test_awaiting_approval_is_surfaced_and_never_approved` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestSubmit.test_token_never_reaches_logs_or_state_files` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+25) |
| `test_steward_jobs.TestPoll.test_poll_updates_record_and_respects_interval` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_interval_limits_open_job_polling` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_due_interval_is_per_state_and_finished_counted` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_summary_is_clipped_and_404_marks_lost_and_foreign_requester_ignored` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_unreachable_is_one_event_with_backoff_and_recovery` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_auth_failure_is_swallowed_and_logged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_down_service_does_not_break_the_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestPoll.test_service_removed_leaves_jobs_untouched` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestPoll.test_redirects_are_not_followed` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestDeliver.test_result_is_delivered_once_to_the_running_idle_session` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_kick_delivers_without_waiting_for_the_timed_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_kick_is_noop_in_observe_mode` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestDeliver.test_fast_path_submits_auto_kind_without_the_brain_and_answers_the_item` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+28) |
| `test_steward_jobs.TestDeliver.test_fast_path_defers_to_brain_when_ambiguous_or_not_auto_or_observe` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_jobs.TestDeliver.test_fast_path_reads_sql_file_in_project` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+28) |
| `test_steward_jobs.TestDeliver.test_fast_path_json_params_and_file` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+29) |
| `test_steward_jobs.TestDeliver.test_waits_while_a_subagent_is_active_or_unknown` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_waits_when_session_busy_or_not_running_and_never_starts_one` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_observe_mode_logs_would_deliver_job_and_does_not_mark` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_failed_and_cancelled_results_and_artifacts_in_message` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_approval_notice_then_result_are_two_separate_deliveries` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_approval_notice_is_skipped_when_already_approved_before_delivery` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_only_the_owner_delivers_and_transfer_moves_the_jobs` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_failed_send_is_retried_then_given_up` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_tick_polls_in_background_slot_and_delivers_next_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestDeliver.test_no_jobs_means_no_poll_and_no_files` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_jobs.TestHttpAndMcp.test_routes_and_jobs_listing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestHttpAndMcp.test_list_refresh_polls_now` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestHttpAndMcp.test_mcp_tools_exist_and_have_no_approve_tool` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestHttpAndMcp.test_mcp_submit_goes_through_panel_api_as_brain` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestHttpAndMcp.test_kitap_brain_cannot_submit_default_projects_through_mcp_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_jobs.TestCli.test_service_add_list_rm` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestCli.test_service_does_not_need_a_steward_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_jobs.TestCli.test_jobs_list_show_poll_ack` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_jobs.TestCli.test_jobs_poll_with_service_down_reports_error` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestCli.test_identity_selection_for_jobs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_jobs.TestParseAutoRequest.test_parser` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_jobs.TestRefreshBounded.test_slow_poll_returns_false_and_runs_in_background_once` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_jobs.TestRefreshBounded.test_fast_poll_is_fresh_and_reports_no_refreshing_flag` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.KeepwarmTest.test_pings_due_idle_big_active` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, markers::scan_markers_corpus (+2) |
| `test_steward_keepwarm.KeepwarmTest.test_no_ping_for_session_in_ho_pending` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, markers::scan_markers_corpus (+2) |
| `test_steward_keepwarm.KeepwarmTest.test_not_due_window` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.KeepwarmTest.test_never_definitely_idle` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.KeepwarmTest.test_no_repeat_in_same_window_and_chain_cap` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, markers::scan_markers_corpus (+2) |
| `test_steward_keepwarm.KeepwarmTest.test_text_default_when_no_work` | idletext::next_work_hint_vectors, tour::clip_words_vectors, tour::marker_next_work_vectors |
| `test_steward_keepwarm.KeepwarmTest.test_text_continue_when_work_pending` | idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+9) |
| `test_steward_keepwarm.KeepwarmTest.test_text_light_ping_when_finished` | idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+10) |
| `test_steward_keepwarm.KeepwarmTest.test_empty_last_assistant_is_not_finished` | idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+9) |
| `test_steward_keepwarm.KeepwarmTest.test_dry_mode_payload_has_text` | idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+9) |
| `test_steward_keepwarm.ChainCloseTest.test_default_dry_and_max3` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.ChainCloseTest.test_act_hands_over_closes_and_defers_pause` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.ChainCloseTest.test_dry_writes_no_handover_state_and_does_not_block_act` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.ChainCloseTest.test_exempt_off_unregistered_and_paused_only_cut` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.ChainCloseTest.test_real_activity_resets_chain_no_close` | idletext::next_none_stated_vectors, idletext::owner_wait_vectors, markers::p_bare_marker, markers::scan_markers_corpus (+2) |
| `test_steward_keepwarm.NoWorkTest.test_no_work_no_keepwarm` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, markers::p_bare_marker (+5) |
| `test_steward_keepwarm.NoWorkTest.test_work_gets_keepwarm` | idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+12) |
| `test_steward_keepwarm.NoWorkTest.test_answer_pending_keeps_warm` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, markers::scan_markers_corpus (+2) |
| `test_steward_keepwarm.NoWorkTest.test_no_work_does_not_burn_chain_counter` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, markers::scan_markers_corpus (+2) |
| `test_steward_keepwarm.OwnerWaitTest.test_owner_wait` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.ConditionalNoteTest.test_detect` | tour::is_conditional_note_vectors |
| `test_steward_keepwarm.ConditionalNoteTest.test_conditional_note_gives_no_hint_and_plain_keepwarm` | idletext::is_fable_polish_vectors, idletext::next_work_hint_vectors, tour::clip_words_vectors, tour::is_conditional_note_vectors (+1) |
| `test_steward_keepwarm.ChainCloseWarmTest.test_full_chain_closes_while_cache_warm` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.ChainCloseWarmTest.test_act_sets_handover_state` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.ChainCloseWarmTest.test_real_activity_after_nudge_no_action_before_due` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.ChainCloseWarmTest.test_incomplete_chain_waits_for_due` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.NotOwnerWaitTest.test_waiting_on_other_project_not_closed` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.NotOwnerWaitTest.test_open_owner_question_closes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_keepwarm.NotOwnerWaitTest.test_owner_phrase_closes` | idletext::owner_wait_vectors |
| `test_steward_keepwarm.NotOwnerWaitTest.test_question_of_other_project_does_not_count` | idletext::owner_wait_vectors |
| `test_steward_launch_cli.LaunchKwargsTest.test_no_record_gives_nothing` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_ucli_record_passes_cli_opts_model_effort_from_record` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_ucli_record_passes_permission_mode` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_record_without_permission_mode_omits_key` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_claude_plain_record_with_permission_mode_stays_empty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_opts_copied_not_aliased` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_latest_instance_of_blueprint_when_no_own_record` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_claude_record_matching_roster_is_old_behaviour` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_claude_record_with_ucli_roster_forces_claude_keeps_steward_model` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_newer_agy_helper_record_does_not_override_claude_roster` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.LaunchKwargsTest.test_unknown_cli_record_ignored` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_launch_cli.EnsureRunningUsesRecordTest.test_ucli_start_gets_recorded_cli_and_opts_and_fresh` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_launch_cli.EnsureRunningUsesRecordTest.test_permission_mode_reaches_start` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_launch_cli.EnsureRunningUsesRecordTest.test_no_record_leaves_start_args_unchanged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+11) |
| `test_steward_launch_cli.InstanceRecordsCliOptsTest.test_record_and_mark_started_persist_and_clear_on_cli_change` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.ReadTest.test_only_auto_tagged_lines_and_dedup` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.DuplicateSignatureTest.test_same_signature_second_is_duplicate_and_not_sent` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.PruneTest.test_keeps_last_auto_lines_and_manual_notes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.PruneTest.test_write_lesson_prunes_file` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.PlanTest.test_sends_one_action_with_batch_limit` | prompts::p_is_project_session, world::pick_delivery_view_vectors |
| `test_steward_lessons.PlanTest.test_gates` | prompts::p_is_project_session, world::pick_delivery_view_vectors |
| `test_steward_lessons.PlanTest.test_sent_lines_not_resent_and_failures_capped` | prompts::p_is_project_session, world::pick_delivery_view_vectors |
| `test_steward_lessons.DeliverTest.test_success_marks_sent_once_and_failure_counts` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_lessons.DeliverTest.test_answer_delivery_failures_alert_once_and_answer_stays` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+26) |
| `test_steward_lessons.DeliverTest.test_stop_with_pause_payload_pauses_with_reason_after_ok_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_lessons.DeliverTest.test_lessons_reads_reviewer_workspaces_only_when_enabled` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.AckTest.test_scan_markers_reads_lesson_ack` | markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors (+1) |
| `test_steward_lessons.AckTest.test_parse_ack` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.AckTest.test_message_carries_ids_and_ack_instruction` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_lessons.AckStateTest.test_ack_only_for_sent_lessons_first_wins_and_rows` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_lessons.AckStateTest.test_stale_failed_and_resend` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_lessons.AckStateTest.test_apply_lesson_ack_action` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_lock.LockRaceTest.test_two_processes_upsert_same_projects_json_lose_nothing` | identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges, identity::normalize_host_vectors (+4) |
| `test_steward_lock.LockRaceTest.test_two_processes_questions_and_ideas_lose_nothing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.LockRaceTest.test_two_processes_claim_same_name_exactly_one_winner` | identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges, identity::normalize_host_vectors (+4) |
| `test_steward_lock.OwnershipTest.test_default_behaviour_unchanged_single_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.OwnershipTest.test_second_identity_cannot_claim_existing_name` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.OwnershipTest.test_default_cannot_claim_name_owned_by_other_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.OwnershipTest.test_name_free_again_after_remove` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.OwnershipTest.test_rejected_claim_writes_nothing_for_second_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.OwnershipTest.test_project_owner_ignores_exclude_and_invalid_dirs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_lock.LockTimeoutTest.test_timeout_raises_not_silent` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_lock.LockTimeoutTest.test_write_paths_raise_and_leave_file_untouched` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_lock.LockTimeoutTest.test_ownership_lock_timeout_blocks_upsert_of_any_identity` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+4) |
| `test_steward_lock.LockTimeoutTest.test_locks_are_per_identity` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_steward_lock.LockTimeoutTest.test_lock_released_after_timeout_and_after_exception` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_lock.ReentrancyTest.test_same_thread_can_nest_same_lock` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_lock.ReentrancyTest.test_other_thread_blocked_until_release` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_loop_guard.LoopGuardTest.test_repeats_without_change_break_once_then_pause` | recovery::loop_guard_vectors, recovery::loop_paused_vectors, recovery::p_loop_sig |
| `test_steward_loop_guard.LoopGuardTest.test_progress_resets_counter` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_loop_guard.LoopGuardTest.test_failing_start_on_absent_session_breaks` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_loop_guard.LoopGuardTest.test_other_kinds_untouched` | recovery::loop_guard_vectors |
| `test_steward_loop_guard.LogDedupTest.test_identical_events_within_window_are_suppressed_and_counted` | logdedup::old_subjects_are_evicted_past_the_cap, logdedup::p_log_dedup |
| `test_steward_main_model.MainSessionModel.test_registered_fable_becomes_sonnet_medium` | prompts::main_session_model_effort_vectors |
| `test_steward_main_model.MainSessionModel.test_opus_and_empty_on_claude` | prompts::main_session_model_effort_vectors |
| `test_steward_main_model.MainSessionModel.test_non_claude_cli_untouched` | prompts::main_session_model_effort_vectors |
| `test_steward_main_model.MainSessionModel.test_remote_unknown_cli_only_claude_models` | prompts::main_session_model_effort_vectors |
| `test_steward_main_model.MainSessionModel.test_non_claude_model_on_claude_cli_untouched` | prompts::main_session_model_effort_vectors |
| `test_steward_main_model.MainSessionModel.test_no_sonnet_known_is_noop` | prompts::main_session_model_effort_vectors |
| `test_steward_multi.TestGolden.test_world_none_is_byte_identical` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestGolden.test_default_world_is_identical` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestGolden.test_default_world_from_disk_index_is_identical` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestOwnershipIndex.test_two_identities_owners_and_brains` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_multi.TestOwnershipIndex.test_settings_ids_reserve_brains_without_dirs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_steward_multi.TestOwnershipIndex.test_conflict_nobody_owns` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_multi.TestOwnershipIndex.test_cache_follows_file_changes` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_multi.TestOwnershipIndex.test_services_are_read_and_reserved` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+16) |
| `test_steward_multi.TestOwnershipIndex.test_reading_writes_nothing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_steward_multi.TestReservedNames.test_reserved_reason` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::ownership_index_edges_keep_order, identity::reserved_reason_edges (+1) |
| `test_steward_multi.TestReservedNames.test_claim_rejects_new_reserved_name_but_keeps_existing` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_multi.TestReservedNames.test_owned_elsewhere_still_wins_for_other_identity` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_multi.TestGlobalPrefix.test_ncs_vs_ncs2` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+13) |
| `test_steward_multi.TestGlobalPrefix.test_same_owner_keeps_old_longest_prefix` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+5) |
| `test_steward_multi.TestGlobalPrefix.test_brains_are_never_projects` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::normalize_host_edges, identity::normalize_host_vectors (+7) |
| `test_steward_multi.TestGlobalPrefix.test_blueprint_can_only_deny` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+12) |
| `test_steward_multi.TestNoCrossActions.test_each_identity_touches_only_its_own` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestNoCrossActions.test_kitap_brain_tours_and_economy_only_for_kitap` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestNoCrossActions.test_sibling_check_is_per_identity` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestNoCrossActions.test_conflicted_project_gets_no_actions` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestMarkers.test_adhoc_markers_only_default_and_project_markers_only_owner` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestMarkers.test_adhoc_answer_delivery_only_default` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_max_active_total_counts_other_identities` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_start_blocked_reason_is_visible` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_start_blocked_reason_auto_start_off` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_max_active_total_counts_only_busy_sessions` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_busy_signal_variants_for_total_slot` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_local_max_active_still_counts_open_sessions` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestSlots.test_starts_left_budget` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_multi.TestReviewItems.test_only_own_sessions` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+23) |
| `test_steward_nowork.Check.test_closes_when_nothing_pending` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.Check.test_aged_open_question_does_not_block_but_answer_pending_does` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+5) |
| `test_steward_nowork.Check.test_each_blocker` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+8) |
| `test_steward_nowork.Check.test_open_todo_means_work_unless_session_says_none` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.Plan.test_dry_lists_and_records_report_without_ho_state` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.Plan.test_act_queues_handover_close_pause_like_keepwarm_chain` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.Plan.test_report_covers_blocked_candidates_too` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.Plan.test_off_and_drain_do_nothing` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_nowork.Plan.test_exempt_brain_manual_and_phases` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_nowork.Plan.test_same_idle_period_decided_once` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.Plan.test_world_manual_class_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_nowork.PausedOpen.test_idle_open_session_of_inactive_project_is_closed_without_pause` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+6) |
| `test_steward_nowork.PausedOpen.test_work_or_review_items_do_not_block_inactive_but_questions_and_subagents_do` | idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+8) |
| `test_steward_nowork.StaleVerified.test_stale_after_two_hours_and_reasons` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_nowork.FablePolish.test_note_next_that_is_fable_polish_is_not_work` | idletext::is_fable_polish_vectors, idletext::next_work_hint_vectors, tour::clip_words_vectors, tour::is_conditional_note_vectors |
| `test_steward_nowork.FablePolish.test_polish_only_note_lets_session_close` | idletext::is_fable_polish_vectors, idletext::next_none_stated_vectors, idletext::next_work_hint_vectors, idletext::owner_wait_vectors (+9) |
| `test_steward_nowork.Reopen.test_triggers` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_nowork.Reopen.test_no_trigger_no_reopen` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_nowork.Apply.test_directive_reopens_only_no_work_paused` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_nowork.Apply.test_manual_pause_is_not_reopened_by_directive` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_nowork.ChainStopIsExact.test_pause_payload_stop_passes_exact` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_outcomes.OutcomeTest.test_start_opened_under_dated_name` | identity::derived_of_vectors, recovery::check_outcomes_vectors, recovery::outcome_baseline_vectors, recovery::p_outcome_project (+2) |
| `test_steward_outcomes.OutcomeTest.test_start_never_opened_is_none_after_window` | recovery::check_outcomes_vectors, recovery::outcome_baseline_vectors, recovery::p_outcome_project, recovery::p_outcome_views (+1) |
| `test_steward_outcomes.OutcomeTest.test_directive_with_new_activity_or_reply` | identity::derived_of_vectors, recovery::check_outcomes_vectors, recovery::outcome_baseline_vectors, recovery::p_loop_sig (+2) |
| `test_steward_outcomes.OutcomeTest.test_other_project_with_same_prefix_does_not_count` | identity::derived_of_vectors, recovery::check_outcomes_vectors, recovery::outcome_baseline_vectors, recovery::p_outcome_project (+1) |
| `test_steward_outcomes.OutcomeTest.test_respawn_new_session_under_project_name` | identity::derived_of_vectors, recovery::check_outcomes_vectors, recovery::outcome_baseline_vectors, recovery::p_loop_sig (+3) |
| `test_steward_outcomes.OutcomeTest.test_directive_baseline_has_no_project` | recovery::outcome_baseline_vectors, recovery::p_outcome_views |
| `test_steward_outcomes.OutcomeTest.test_pending_is_capped` | recovery::check_outcomes_vectors, recovery::p_outcome_views |
| `test_steward_outcomes.OutcomeTest.test_via_passes_through` | identity::derived_of_vectors, recovery::check_outcomes_vectors, recovery::p_outcome_views, recovery::p_via |
| `test_steward_outcomes.BrainDirectiveOutcomeTest.test_register_only_real_sends` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_owned.SessionClassTest.test_unrecorded_project_is_own` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+13) |
| `test_steward_owned.SessionClassTest.test_recorded_name_own_other_name_manual` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+13) |
| `test_steward_owned.SessionClassTest.test_empty_record_means_every_session_is_manual` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+13) |
| `test_steward_owned.SessionClassTest.test_brain_never_manual` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::normalize_host_edges, identity::normalize_host_vectors (+6) |
| `test_steward_owned.UpdateOwnedTest.test_first_sight_rules` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+11) |
| `test_steward_owned.UpdateOwnedTest.test_two_sessions_ambiguous_hands_off` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+11) |
| `test_steward_owned.UpdateOwnedTest.test_recorded_project_untouched` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+11) |
| `test_steward_owned.UpdateOwnedTest.test_seeding_needs_evidence` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+11) |
| `test_steward_owned.EvidenceTest.test_rules` | world::owned_evidence_vectors |
| `test_steward_owned.PlanTickManualTest.test_manual_session_holds_project_no_start_no_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_owned.PlanTickManualTest.test_owned_dead_and_no_manual_starts` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_owned.TargetAndEnsureTest.test_target_denies_manual_session` | identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+24) |
| `test_steward_owned.TargetAndEnsureTest.test_ensure_running_refuses_beside_manual_session` | identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+24) |
| `test_steward_owned.TargetAndEnsureTest.test_ensure_running_uses_owned_session` | identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+22) |
| `test_steward_owned.TargetAndEnsureTest.test_start_records_the_new_session` | identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+24) |
| `test_steward_owned.TargetAndEnsureTest.test_seed_request_seeds_by_evidence_once` | identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+22) |
| `test_steward_owned.OwnedCliTest.test_set_and_clear` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_steward_owner_todo.Regex.test_tags` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_owner_todo.Regex.test_wait_re_covers_new_and_old` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_owner_todo.Counting.test_scan` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_owner_todo.Counting.test_scan_unboxed_todo_not_no_work` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_owner_todo.Counting.test_scan_numbered_checkboxes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_owner_todo.Move.test_sent_once_per_24h` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+6) |
| `test_steward_owner_todo.Move.test_zero_remote_busy_and_off` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+5) |
| `test_steward_owner_todo.Move.test_done_project_skipped` | idle::plan_claude_idle_vectors |
| `test_steward_owner_todo.Move.test_dry_mode_does_not_lock_act` | idle::plan_claude_idle_vectors, idletext::one_line_vectors, idletext::turn_failed_vectors, idletext::waiting_for_gate_vectors (+1) |
| `test_steward_owner_todo.Move.test_observe_skips_kind` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_owner_todo.Explain.test_count_in_why` | explain::explain_idle_all_vectors, explain::explain_idle_vectors, explain::p_why, idletext::notes_wait_vectors |
| `test_steward_paths.PathsForTest.test_default_equals_legacy_layout` | EKSİK: parite testi olmayan daily_path |
| `test_steward_paths.PathsForTest.test_default_follows_constant_patches` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_paths.PathsForTest.test_other_sid_under_stewards` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_paths.PathsForTest.test_sid_rejects_traversal` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_paths.PathsForTest.test_no_arg_matches_explicit_default_byte_for_byte` | EKSİK: parite testi olmayan daily_path |
| `test_steward_paths.PathsForTest.test_other_sid_isolated_from_default` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+27) |
| `test_steward_pause_close.WrapUpText.test_wrap_up_detected` | closing::is_wrap_up_directive_vectors |
| `test_steward_pause_close.WrapUpText.test_plain_work_not_wrap_up` | closing::is_wrap_up_directive_vectors |
| `test_steward_pause_close.WrapUpText.test_keep_phase_flag` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors |
| `test_steward_pause_close.PauseClose.test_idle_session_gets_handover_then_close` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_pause_close.PauseClose.test_busy_session_waits` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_pause_close.PauseClose.test_not_paused_anymore_clears` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_pause_close.PauseClose.test_no_request_no_action` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_pause_close.PauseClose.test_gone_session_clears_request` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_pause_close.PauseClose.test_request_helper` | closing::bad_state_types_are_errors, closing::request_pause_close_vectors |
| `test_steward_pending_digest.SlotTest.test_slots` | notify::pending_digest_slot_vectors |
| `test_steward_pending_digest.TextTest.test_empty_when_nothing_open` | notify::pending_digest_text_vectors |
| `test_steward_pending_digest.TextTest.test_counts_oldest_and_unnotified` | notify::pending_digest_text_vectors |
| `test_steward_pending_digest.ApplyTest.test_once_per_slot_and_skipped_without_questions` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+15) |
| `test_steward_question_detail.DetailTest.test_scan_and_actions` | gates::p_ask_is_status_line, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors (+1) |
| `test_steward_question_detail.DetailTest.test_no_detail` | gates::p_ask_is_status_line, markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors (+1) |
| `test_steward_question_detail.DetailTest.test_page_shows_detail` | notify::question_page_html_vectors |
| `test_steward_question_same_ask.SameAskTest.test_two_consecutive_sweeps_keep_one_open_question` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_question_same_ask.SameAskTest.test_answered_sweep_question_does_not_swallow_next_one` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+14) |
| `test_steward_question_same_ask.SameAskTest.test_same_question_sentence_with_different_lead_merges` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+10) |
| `test_steward_question_same_ask.SameAskTest.test_only_count_differs_merges_even_after_a_day` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+10) |
| `test_steward_question_same_ask.SameAskTest.test_identifier_numbers_and_generic_sentences_stay_separate` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+10) |
| `test_steward_question_same_ask.SameAskTest.test_other_project_never_merges` | identity::from_dict_drops_unknown_and_requires, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+10) |
| `test_steward_questions_pending_delivery.QuestionHeadTests.test_answered_not_delivered_shows_pending` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_questions_pending_delivery.QuestionHeadTests.test_answered_delivered_has_no_pending_label` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_questions_pending_delivery.QuestionHeadTests.test_open_question_has_no_pending_label` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.ParseTest.test_parse_real_output` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.ParseTest.test_parse_unknown_format_is_none` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.ParseTest.test_reset_rolls_into_next_year` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_off_and_unknown_never_act` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_manual_stops_at_limit` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_budget_pct_derives_the_three_tiers_and_overrides_explicit_limits` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_budget_pct_zero_or_missing_keeps_the_explicit_limits` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_enabling_above_95_needs_confirmation` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_manual_three_tiers` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_manual_without_limit_only_final_acts` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_auto_daily_cap_pacing` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_per_weekday_override` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_day_after_monday_reset_is_tuesday` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota.DecideTest.test_auto_without_reset_has_no_cap` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_http.QuotaHttp.test_brain_denied` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_http.QuotaHttp.test_set_and_get` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_http.QuotaHttp.test_enable_above_95_needs_confirm` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_http.QuotaHttp.test_day_empty_deletes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_http.QuotaHttp.test_validation` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_http.QuotaHttp.test_routes_registered` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_restore.QuotaRestoreTest.test_restart_at_same_level_does_not_stop_again` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_steward_quota_restore.QuotaRestoreTest.test_higher_level_after_restart_still_stops` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_steward_quota_restore.QuotaRestoreTest.test_no_file_behaves_as_before` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+1) |
| `test_steward_quota_unresolved_reset.UnresolvedResetTests.test_auto_without_reset_reports_reason_and_does_not_drain` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_unresolved_reset.UnresolvedResetTests.test_auto_without_reset_still_stops_at_final_limit` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_unresolved_reset.UnresolvedResetTests.test_unparseable_reset_text_gives_none` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_quota_unresolved_reset.UnresolvedResetTests.test_manual_mode_without_reset_has_no_unresolved_warning` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote.TestSelectRows.test_remote_rows_only_for_their_projects_on_fresh_hosts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::name_rules_edges (+9) |
| `test_steward_remote.TestSelectRows.test_stale_host_rows_drop` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::name_rules_edges (+9) |
| `test_steward_remote.TestSelectRows.test_index_hosts_skip_local_and_conflicts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::normalize_host_edges, identity::normalize_host_vectors (+3) |
| `test_steward_remote.TestPlanTickRemote.test_unavailable_project_is_not_started_nor_forgotten` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_remote.TestPlanTickRemote.test_pending_answer_for_unavailable_project_neither_starts_nor_blocks` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_remote.TestPlanTickRemote.test_remote_session_counts_for_max_active` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_remote.TestPlanTickRemote.test_subagent_unknown_defers_done_and_shutdown_handover` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_remote.TestPlanTickRemote.test_subagent_unknown_but_quiet_idle_session_is_closed` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_remote.TestPlanTickRemote.test_answer_delivery_still_allowed_with_unknown_subagent` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_remote.TestProjectHost.test_old_records_load_as_local` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+9) |
| `test_steward_remote.TestProjectHost.test_validation_and_normalization` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote.TestProjectHost.test_host_change_needs_a_stopped_project_or_force_and_clears_state` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+18) |
| `test_steward_remote.TestProjectHost.test_ownership_lock_first` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_remote.TestEngineRemote.test_views_come_from_cache_and_term_chat` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_remote.TestEngineRemote.test_observe_records_would_with_host_and_never_posts` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote.TestEngineRemote.test_observe_start_and_answer_of_remote_project` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote.TestEngineRemote.test_act_mode_denies_remote_while_remote_actions_off` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote.TestEngineRemote.test_act_mode_remote_project_does_not_eat_local_start_budget` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote.TestEngineRemote.test_host_down_keeps_state_and_drops_views` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote.TestEngineRemote.test_last_assistant_reads_share_a_budget` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote.TestEngineRemote.test_one_slow_session_does_not_blame_a_reachable_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote.TestEngineRemote.test_all_reads_timing_out_still_blames_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote.TestTargetRemote.test_rules` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+29) |
| `test_steward_remote.TestTargetRemote.test_http_endpoints` | gates::panic_path_is_under_default_root, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+24) |
| `test_steward_remote.TestLocalFsGuards.test_cwd_and_cards` | cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+21) |
| `test_steward_remote.TestLocalFsGuards.test_idea_export_register_file_context` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+25) |
| `test_steward_remote.TestLocalFsGuards.test_project_for_session_skips_local_instance_registry` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_remote.TestUpsertRemote.test_active_phase_needs_remote_roster` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+18) |
| `test_steward_remote.TestUpsertRemote.test_host_change_checks_running_sessions` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+21) |
| `test_steward_remote.TestUpsertRemote.test_cli_set_host_goes_through_the_panel` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_remote.TestWebHostsLastOk.test_last_ok_at_tracks_only_successes` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_actions.TestRemoteActions.test_handover_path_body_timeout` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteActions.test_handover_needs_an_exact_running_row` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_actions.TestRemoteActions.test_answer_goes_through_term_input_exact_and_preamble_key_is_host_colon_name` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteActions.test_unknown_born_sends_full_preamble_and_records_nothing` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteActions.test_start_waits_on_the_poller_cache_without_network` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteActions.test_start_ready_timeout_is_bounded` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_actions.TestRemoteActions.test_unknown_busy_is_ready_after_a_few_polls_not_the_full_timeout` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_actions.TestRemoteActions.test_start_is_not_attempted_on_a_down_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_remote_actions.TestRemoteActions.test_directive_endpoint_and_remote_reject_passes_through` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+34) |
| `test_steward_remote_actions.TestRemoteActions.test_not_tmux_backed_or_not_running_rows_are_not_sent` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+30) |
| `test_steward_remote_actions.TestRemoteGates.test_observe_records_would_and_never_posts` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteGates.test_remote_actions_off_denies_in_act_and_logs_once` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteGates.test_mismatch_unknown_and_unregistered_are_denied` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_remote_actions.TestRemoteGates.test_down_or_stale_host_gets_no_actions` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteGates.test_destructive_kinds_need_exact_target_on_the_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_actions.TestRemoteGates.test_local_actions_are_unchanged_next_to_a_remote_project` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+28) |
| `test_steward_remote_actions.TestRemoteResilience.test_breaker_stops_after_first_transport_error_in_a_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteResilience.test_404_and_app_level_reject_do_not_open_the_breaker` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteResilience.test_backoff_after_three_failed_ticks_and_single_state_events` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteResilience.test_no_phone_notification_for_unreachable` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteResilience.test_one_freshness_snapshot_per_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_actions.TestRemoteResilience.test_read_timeouts_feed_the_breaker` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_actions.TestRemoteResilience.test_snapshot_drives_both_unavailable_and_views` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_actions.TestRemoteResilience.test_proxy_action_timeout_and_forced_local_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote_actions.TestRemoteResilience.test_remote_post_refuses_a_body_with_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote_answer_persist.MissingFile.test_200_files_not_found_creates_file` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+33) |
| `test_steward_remote_answer_persist.MissingFile.test_other_error_code_does_not_create` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+31) |
| `test_steward_remote_answer_persist.Retry.test_timeout_queued_silently_then_written` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+34) |
| `test_steward_remote_answer_persist.Retry.test_stale_host_notifies_once_after_30_min_and_gives_up_after_a_day` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+32) |
| `test_steward_remote_answer_persist.Retry.test_remote_actions_off_notifies_at_once_without_queue` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+31) |
| `test_steward_remote_answer_persist.Retry.test_tick_keeps_queue_and_jobs_step_retries` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_answer_persist.OwnedSessionName.test_tracked_hyphen_session_gives_project_folder` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+33) |
| `test_steward_remote_answer_persist.DeliveryAlert.test_transient_host_errors_alert_only_after_30_min` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+35) |
| `test_steward_remote_cards.TestRemoteCards.test_card_built_from_remote_reads_and_written_locally` | cards::build_card_prompt_vectors, cards::card_path_vectors, cards::card_refresh_reason_vectors, cards::p_goal_from_docs (+28) |
| `test_steward_remote_cards.TestRemoteCards.test_manual_refresh_card_uses_remote` | cards::card_path_vectors, cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines (+24) |
| `test_steward_remote_cards.TestRemoteCards.test_skipped_when_off_or_host_unavailable` | cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires (+17) |
| `test_steward_remote_cards.TestRemoteCards.test_running_remote_project_is_skipped` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+22) |
| `test_steward_remote_cards.TestRemoteCards.test_one_remote_card_per_tick_oldest_checked_first` | cards::card_path_vectors, cards::card_refresh_reason_vectors, cards::p_goal_from_docs, cards::p_short (+27) |
| `test_steward_remote_cards.TestRemoteCards.test_remote_card_budget_stops_reads` | cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires (+17) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_reads_first_then_writes_to_remote_path` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+18) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_tbd_target_file` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+18) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_missing_remote_notes_file_is_created_with_flag` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+18) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_conflict_between_reads_leaves_file_alone` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_observe_brain_is_dry_but_human_http_writes` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+18) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_gate_off_stale_down_skip_without_any_request` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_remote_cards.TestRemoteIdeaExport.test_write_failure_reported` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_remote_cards.TestRemoteRegister.test_adopts_existing_remote_roster_row_without_creating_anything` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+18) |
| `test_steward_remote_cards.TestRemoteRegister.test_missing_remote_row_or_gate_gives_clear_error` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_remote_cards.TestRemoteRegister.test_conflicting_host_refused` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_remote_destructive.TestRemoteStop.test_steward_done_stop_path_body_timeout` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteStop.test_done_confirmed_read_from_term_chat_when_facts_last_assistant_is_empty` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteStop.test_done_confirmed_on_host_without_facts_closes_a_quiet_idle_session` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteStop.test_no_exact_target_logs_remote_too_old_once_and_never_posts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteStop.test_unknown_capabilities_are_not_treated_as_supported` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteStop.test_precheck_exact_running_own_row` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+25) |
| `test_steward_remote_destructive.TestRemoteStop.test_no_exact_match_is_not_applied_and_does_not_open_the_breaker` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteStop.test_transport_error_still_opens_the_breaker` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteStop.test_observe_records_would_and_never_posts` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteStop.test_remote_actions_off_and_down_host_are_denied` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_remote_destructive.TestRemoteStop.test_one_destructive_action_per_host_per_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteStop.test_human_http_stop_gates` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_ready_after_handover_respawns_stop_start_directive_in_order` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteRespawn.test_stop_failure_means_no_start` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_stop_ok_but_row_never_closes_waits_bounded_then_stops` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_start_failure_means_no_directive` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+32) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_session_already_gone_skips_stop` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+34) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_old_host_respawn_is_refused_without_any_post` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_two_respawns_on_one_host_second_is_deferred_to_next_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_destructive.TestRemoteRespawn.test_restart_stops_waits_then_directs` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+36) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_restart_without_confirmed_stop_sends_nothing_more` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_destructive.TestRemoteRespawn.test_restart_host_mismatch_is_denied` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_remote_destructive.TestLocalUnchanged.test_local_stop_and_respawn_use_the_local_callbacks` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+31) |
| `test_steward_remote_facts.TestFactsEndpoint.test_facts_for_exact_names` | closing::context_threshold_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges (+6) |
| `test_steward_remote_facts.TestFactsEndpoint.test_non_claude_has_no_context_or_subagent` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestFactsEndpoint.test_codex_context_from_provider_live_context` | closing::context_threshold_vectors, identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_remote_facts.TestFactsEndpoint.test_codex_background_work_reported` | closing::context_threshold_vectors, identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_remote_facts.TestFactsEndpoint.test_no_names_gives_capabilities_only` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestFactsEndpoint.test_route_is_host_routed` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestExact.test_stop_exact_requires_full_name` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestExact.test_stop_without_exact_keeps_unique_base` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestExact.test_term_input_exact` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestExact.test_handover_exact_refuses_before_touching_session` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestExact.test_term_resolve_exact` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_remote_facts.TestClient.test_404_caches_api0_and_rechecks_after_ten_minutes` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_facts.TestClient.test_404_is_not_a_transport_failure` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote_facts.TestClient.test_network_error_does_not_write_cache` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote_facts.TestClient.test_view_enriched_from_facts_single_request` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_facts.TestClient.test_empty_facts_last_assistant_falls_back_to_term_chat_but_keeps_facts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_facts.TestClient.test_facts_missing_for_a_session_falls_back_to_term_chat` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_facts.TestClient.test_old_host_keeps_a1_behavior` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_facts.TestClient.test_enriched_view_clears_subagent_unknown` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_nudge.TestRemoteNudge.test_nudge_posts_exact_devam_without_local_fallback` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_nudge.TestRemoteNudge.test_two_sessions_is_refused_and_nothing_is_sent` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_nudge.TestRemoteNudge.test_no_session_and_no_tmux_are_refused` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+28) |
| `test_steward_remote_nudge.TestRemoteNudge.test_tick_wakes_a_stuck_remote_session_after_the_first_delay` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_session_resolve.TestDirective.test_project_name_reaches_the_single_dated_session_without_any_start` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+34) |
| `test_steward_remote_session_resolve.TestDirective.test_engine_counts_a_dated_session_without_blueprint_as_running` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_session_resolve.TestDirective.test_no_running_session_starts_with_the_project_name` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+36) |
| `test_steward_remote_session_resolve.TestDirective.test_prefix_neighbour_session_is_not_a_second_session_of_the_project` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+34) |
| `test_steward_remote_session_resolve.TestDirective.test_repeated_identical_failure_is_logged_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_remote_session_resolve.TestDirective.test_two_running_sessions_are_ambiguous_and_nothing_is_posted` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+32) |
| `test_steward_remote_session_resolve.TestDirective.test_full_session_name_is_verified_against_the_rows` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+34) |
| `test_steward_remote_session_resolve.TestDirective.test_underscore_suffix_resolves` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+34) |
| `test_steward_remote_session_resolve.TestDirective.test_another_projects_prefix_does_not_mix_in` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+36) |
| `test_steward_remote_session_resolve.TestDestructiveAndHandover.test_handover_uses_the_real_name_and_records_it` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_session_resolve.TestDestructiveAndHandover.test_stop_uses_the_real_name` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_session_resolve.TestDestructiveAndHandover.test_wait_closed_watches_the_real_name` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+28) |
| `test_steward_remote_session_resolve.TestDestructiveAndHandover.test_respawn_after_handover_stops_real_name_starts_project_directs_new_name` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_session_resolve.TestDestructiveAndHandover.test_human_restart_stops_real_name_then_starts_the_project` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+36) |
| `test_steward_remote_session_resolve.TestDestructiveAndHandover.test_engine_handover_on_dated_view_name` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_remote_session_resolve.TestStartOnceAndReads.test_refresh_after_start_sees_the_new_session` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+30) |
| `test_steward_remote_session_resolve.TestStartOnceAndReads.test_lagging_cache_still_gets_no_second_start_in_the_tick` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_remote_session_resolve.TestStartOnceAndReads.test_cwd_and_file_reads_use_the_real_name` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+20) |
| `test_steward_remote_session_resolve.TestLocalUnchanged.test_local_directive_still_uses_the_local_path` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+31) |
| `test_steward_remote_surface.TestState.test_running_has_remote_rows_with_host_and_project_flag` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestState.test_state_shows_open_tbd_and_todo_counts` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestState.test_local_namesake_does_not_make_remote_project_running` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestState.test_no_double_count` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+27) |
| `test_steward_remote_surface.TestState.test_stale_host_rows_not_listed` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestState.test_question_host_and_remote_hosts_health` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestState.test_local_only_state_has_no_remote_keys` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestRemoteReads.test_context_reads_over_host_not_local_fs` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+24) |
| `test_steward_remote_surface.TestRemoteReads.test_context_running_with_dated_session_name` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestRemoteReads.test_same_path_local_folder_is_never_read` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+24) |
| `test_steward_remote_surface.TestRemoteReads.test_errors_and_down_host_return_empty_never_raise` | cards::card_one_liner_vectors, cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors (+24) |
| `test_steward_remote_surface.TestRemoteReads.test_file_read_and_path_guard` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+19) |
| `test_steward_remote_surface.TestRemoteReads.test_enrich_item_remote` | cards::card_path_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+20) |
| `test_steward_remote_surface.TestNotifyAndLog.test_ask_prefix` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+27) |
| `test_steward_remote_surface.TestNotifyAndLog.test_ask_goes_out_with_host_prefix` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+37) |
| `test_steward_remote_surface.TestNotifyAndLog.test_action_log_host_only_remote` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_remote_surface.TestJobSubmit.test_host_is_the_projects_host` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_remote_surface.TestJobSubmit.test_remote_project_rejects_local_files` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_remote_surface.TestMcpAndBrain.test_mcp_overview_carries_host_only_for_remote` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestMcpAndBrain.test_mcp_signatures_unchanged_notes_added` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+13) |
| `test_steward_remote_surface.TestMcpAndBrain.test_workspace_note_only_when_remote` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+16) |
| `test_steward_remote_surface.TestCli.test_projects_host_column_only_with_remote` | cards::card_one_liner_vectors, identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires (+14) |
| `test_steward_remote_surface.TestCli.test_status_remote_summary_and_health` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestCli.test_status_panel_down_is_unknown_not_error` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remote_surface.TestCli.test_status_without_remote_does_not_call_panel` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_remove_lock.RemoveLock.test_settings_delete_happens_while_lock_held` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_reply_language.Heuristic.test_mismatch_both_ways` | markers::text_lang_mismatch_edges, markers::text_lang_mismatch_vectors |
| `test_steward_reply_language.Heuristic.test_short_or_neutral_text_never_flagged` | markers::text_lang_mismatch_edges, markers::text_lang_mismatch_vectors |
| `test_steward_reply_language.Directive.test_language_line_in_full_and_compact_both_languages` | markers::reply_language_line_vectors, prompts::build_directive_vectors |
| `test_steward_reply_language.Directive.test_handover_messages_carry_language` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_reply_language.FixNote.test_once_per_day_per_session` | markers::lang_fix_action_state_handling, markers::lang_fix_action_vectors, markers::text_lang_mismatch_edges, markers::text_lang_mismatch_vectors |
| `test_steward_reply_language.FixNote.test_plan_tick_emits_note_for_wrong_language_marker` | markers::marker_texts_vectors, markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus (+3) |
| `test_steward_review_api.TestPool.test_pool_add_disable_enable_remove` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_review_api.TestPool.test_remove_of_auto_project_is_not_reenabled_by_sync` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_review_api.TestPool.test_list_row_carries_role_only_for_reviewer` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_review_api.TestPool.test_non_reviewer_and_unknown_steward_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestPool.test_brain_actor_rejected_everywhere` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestRunCancel.test_manual_run_validates_and_starts` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_review_api.TestRunCancel.test_manual_run_picks_the_effort_pair` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_review_api.TestRunCancel.test_manual_run_refused_when_disabled_or_busy` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestRunCancel.test_cancel_calls_cancel_key` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+17) |
| `test_steward_review_api.TestReads.test_state_findings_and_file` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestReads.test_file_path_escape_rejected` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestReads.test_reads_need_reviewer` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestCli.test_parsing_maps_to_api` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_review_api.TestCli.test_reads_status_history_findings` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_reviewer_gate.TestReviewerTick.test_reviewer_tick_runs_only_review_tick` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_reviewer_gate.TestReviewerTick.test_idle_review_tick_is_noop_and_spawns_nothing` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_reviewer_gate.TestReviewerTick.test_disabled_reviewer_is_not_passively_scanned` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_reviewer_gate.TestReviewerTick.test_ownership_ignores_reviewer_projects_json` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+14) |
| `test_steward_reviewer_gate.TestReviewerTarget.test_target_always_denied` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_reviewer_gate.TestReviewerTarget.test_default_target_unchanged` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+11) |
| `test_steward_reviewer_gate.TestReviewerTarget.test_brain_start_refused` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors (+2) |
| `test_steward_reviewer_gate.TestReviewerProjects.test_upsert_refused` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+7) |
| `test_steward_reviewer_gate.TestReviewerProjects.test_transfer_to_reviewer_refused` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_steward_reviewer_gate.TestReviewerProjects.test_transfer_from_reviewer_refused` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_reviewer_gate.TestReviewerCreate.test_http_create_with_role` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+6) |
| `test_steward_reviewer_gate.TestReviewerCreate.test_http_create_unknown_role_refused` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_reviewer_gate.TestReviewerCreate.test_brain_cannot_create` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_reviewer_gate.TestReviewerCreate.test_cli_create_with_role` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_reviewer_gate.TestReviewerCreate.test_cli_parser_role_choices` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_reviewer_gate.TestReviewerCreate.test_cli_config_cannot_change_role` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_reviewer_gate.TestReviewerCreate.test_cli_config_without_value_reads_and_writes_nothing` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+3) |
| `test_steward_reviewer_gate.TestReviewerCreate.test_cli_config_and_toggle_leave_an_audit_trail` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_reviewer_gate.TestReviewerCreate.test_default_is_never_reviewer` | identity::name_rules_edges, identity::reviewers_from_settings, identity::valid_steward_id_vectors |
| `test_steward_settings.TestIds.test_valid` | identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_settings.TestIds.test_brain_name` | identity::brain_name_for_vectors |
| `test_steward_settings.TestStewardSettings.test_golden_default_empty` | identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_settings.TestStewardSettings.test_handover_defer_fields` | identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_settings.TestStewardSettings.test_default_ignores_stewards_block` | identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_settings.TestStewardSettings.test_default_brain_name_override_kept` | identity::name_rules_edges, identity::valid_steward_id_vectors |
| `test_steward_settings.TestStewardSettings.test_ids` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_settings.TestStewardSettings.test_custom_cfg` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_settings.TestStewardSettings.test_unknown_and_invalid_sid` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_settings.TestStewardSettings.test_custom_bad_values_tolerated` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_settings.TestSaveTwoLevel.test_partial_update_keeps_other_ids` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_settings.TestSaveTwoLevel.test_empty_removes_field_none_removes_id` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_settings.TestSaveTwoLevel.test_invalid_ids_skipped_and_other_keys_untouched` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_settings.TestSaveTwoLevel.test_bool_and_steward_block_unaffected` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_settings.TestSaveTwoLevel.test_non_dict_stored_recovers` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_shell_ignored.ShellIgnored.test_select_rows_drops_shell_local_and_remote` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+7) |
| `test_steward_shell_ignored.ShellIgnored.test_other_clis_kept` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+6) |
| `test_steward_shell_ignored.ShellIgnored.test_claude_plus_shell_is_adopted_not_ambiguous` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+13) |
| `test_steward_shell_ignored.ShellIgnored.test_unfiltered_would_have_been_ambiguous` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::normalize_host_edges (+11) |
| `test_steward_shutdown_fail.ShutdownNoteResultTests.test_failure_rolls_back_then_gives_up` | closing::bad_state_types_are_errors, closing::shutdown_note_result_vectors |
| `test_steward_shutdown_fail.ShutdownNoteResultTests.test_stop_failure_goes_back_to_ho` | closing::bad_state_types_are_errors, closing::shutdown_note_result_vectors |
| `test_steward_shutdown_fail.ShutdownNoteResultTests.test_failed_stop_is_retried_end_to_end` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors, closing::shutdown_note_result_vectors, markers::needs_ho_rfh_marker_in |
| `test_steward_shutdown_fail.ShutdownNoteResultTests.test_success_resets_counter` | closing::bad_state_types_are_errors, closing::shutdown_note_result_vectors |
| `test_steward_shutdown_fail.ShutdownNoteResultTests.test_destructive_budget_defers_without_counting_failure` | closing::bad_state_types_are_errors, closing::shutdown_note_result_vectors |
| `test_steward_shutdown_fail.ShutdownNoteResultTests.test_terminal_plan_finishes` | closing::bad_state_types_are_errors, closing::plan_shutdown_vectors |
| `test_steward_stale_note.StaleNoteTest.test_closed_item_is_stale` | idletext::p_note_words, idletext::stale_next_note_vectors, tour::clip_words_vectors |
| `test_steward_stale_note.StaleNoteTest.test_open_item_wins` | idletext::p_note_words, idletext::stale_next_note_vectors |
| `test_steward_stale_note.StaleNoteTest.test_unknown_is_not_stale` | idletext::p_note_words, idletext::stale_next_note_vectors |
| `test_steward_stale_note.StaleNoteTest.test_copy_replaces_line_and_keeps_record` | idletext::next_work_hint_vectors, idletext::p_note_words, idletext::stale_next_note_vectors, idletext::without_stale_note_vectors (+3) |
| `test_steward_stale_note.StaleNoteTest.test_item_moved_to_done_is_stale` | idletext::p_note_words, idletext::stale_next_note_vectors, idletext::without_stale_note_vectors, tour::clip_words_vectors |
| `test_steward_stale_note.StaleNoteTest.test_open_item_wins_over_done` | idletext::p_note_words, idletext::stale_next_note_vectors |
| `test_steward_stale_note.StaleNoteTest.test_done_history_needs_stronger_match` | idletext::p_note_words, idletext::stale_next_note_vectors, tour::clip_words_vectors |
| `test_steward_stale_note.DoneFileWiringTest.test_note_project_reads_done_md` | idletext::p_note_words, idletext::stale_next_note_vectors, idletext::without_stale_note_vectors, prompts::note_claims_vectors (+1) |
| `test_steward_start_appears.StartAppearsTest.test_appears_after_a_few_polls` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_start_appears.StartAppearsTest.test_never_appears_returns_false_without_real_sleep` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_start_appears.StartAppearsTest.test_cache_is_invalidated_each_poll` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_start_appears.StartAppearsTest.test_ensure_running_errors_when_ok_but_no_session` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+11) |
| `test_steward_start_backoff.BackoffMath.test_steps_and_reset` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_start_backoff.EnsureRunningBackoff.test_failed_start_backs_off_and_logs_no_big_context` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_start_backoff.EnsureRunningBackoff.test_success_logs_big_context_and_clears` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+9) |
| `test_steward_symlinked_todo.SymlinkedTodo.test_symlinked_worktree_is_unknown` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_symlinked_todo.SymlinkedTodo.test_owner_main_checkout_still_counts` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_symlinked_todo.SymlinkedTodo.test_symlink_to_unregistered_dir_still_counts` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_tbd370.TrailingNewlineNameTest.test_valid_name` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_steward_tbd370.TrailingNewlineNameTest.test_valid_custom_id` | identity::name_rules_edges, identity::valid_custom_id_vectors |
| `test_steward_tbd370.TrailingNewlineNameTest.test_valid_steward_id` | identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_steward_tbd370.TrailingNewlineNameTest.test_reviewer_ids` | identity::name_rules_edges, identity::reviewers_from_settings, identity::valid_custom_id_vectors |
| `test_steward_tbd370.ConfirmedMentionTest.test_mention_is_not_a_confirmation` | markers::is_confirm_line_vectors, markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus (+1) |
| `test_steward_tbd370.ConfirmedMentionTest.test_mention_does_not_overwrite_real_confirmation` | markers::is_confirm_line_vectors, markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus (+1) |
| `test_steward_tbd370.ConfirmedMentionTest.test_colon_forms_still_count` | markers::is_confirm_line_vectors, markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus (+1) |
| `test_steward_tbd370.ConfirmedMentionTest.test_colonless_forms_still_count` | markers::is_confirm_line_vectors, markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus (+1) |
| `test_steward_tbd370.TourPromptTest.test_card_age_uses_given_now` | prompts::build_tour_prompt_vectors, prompts::card_lines_vectors |
| `test_steward_tbd370.TourPromptTest.test_phase_line_kind_label_follows_language` | prompts::build_tour_prompt_vectors |
| `test_steward_tbd370.ClipTest.test_never_exceeds_limit` | prompts::p_clip |
| `test_steward_tbd370.ClipTest.test_zero_is_empty_and_positive_unchanged` | prompts::p_clip |
| `test_steward_tmp_isolation.DetailThreadIsolationTest.test_ask_starts_no_detail_generation` | identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges (+29) |
| `test_steward_ucli_idle.IdleModeTest.test_off_produces_nothing` | idle::plan_ucli_idle_vectors |
| `test_steward_ucli_idle.IdleModeTest.test_dry_plans_but_never_writes_handover_state` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+10) |
| `test_steward_ucli_idle.IdleModeTest.test_default_config_is_dry` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_idle.FailedTurnChainTest.test_detect` | idletext::turn_failed_vectors |
| `test_steward_ucli_idle.FailedTurnChainTest.test_failed_turn_does_not_reset_chain` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+10) |
| `test_steward_ucli_idle.FailedTurnChainTest.test_successful_turn_still_resets_chain` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+10) |
| `test_steward_ucli_idle.GateWaitTest.test_gate_wait_text_detected` | idletext::waiting_for_gate_vectors |
| `test_steward_ucli_idle.GateWaitTest.test_no_nudge_no_close_while_waiting_for_gate` | idle::plan_ucli_idle_vectors, idletext::turn_failed_vectors, idletext::ucli_idle_threshold_vectors, idletext::waiting_for_gate_vectors |
| `test_steward_ucli_idle.GateWaitTest.test_old_gate_text_far_back_does_not_block` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+10) |
| `test_steward_ucli_idle.HelpersTest.test_one_line_folds_newlines` | idletext::one_line_vectors |
| `test_steward_ucli_idle.HelpersTest.test_threshold_by_cache_ttl` | idletext::ucli_idle_threshold_vectors |
| `test_steward_ucli_idle.HelpersTest.test_next_work_hint` | idletext::is_fable_polish_vectors, idletext::next_work_hint_vectors, tour::clip_words_vectors, tour::is_conditional_note_vectors |
| `test_steward_ucli_idle.HelpersTest.test_finish_marker` | idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::p_done_at_line_end, markers::needs_ho_rfh_marker_in (+1) |
| `test_steward_ucli_idle.PlanTest.test_nudge_with_next_work_single_line` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+8) |
| `test_steward_ucli_idle.PlanTest.test_below_threshold_nothing` | idle::plan_ucli_idle_vectors, idletext::ucli_idle_threshold_vectors |
| `test_steward_ucli_idle.PlanTest.test_threshold_follows_cache_ttl` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+8) |
| `test_steward_ucli_idle.PlanTest.test_configurable_threshold_and_off` | idle::plan_ucli_idle_vectors, idletext::ucli_idle_threshold_vectors |
| `test_steward_ucli_idle.PlanTest.test_no_work_no_marker_does_nothing` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+5) |
| `test_steward_ucli_idle.PlanTest.test_open_todo_alone_sends_no_blind_nudge` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+4) |
| `test_steward_ucli_idle.PlanTest.test_open_todo_still_counts_for_close_decisions` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+6) |
| `test_steward_ucli_idle.PlanTest.test_close_marker_with_work_requests_handover_then_reopen` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+9) |
| `test_steward_ucli_idle.PlanTest.test_close_marker_without_work_pauses_and_closes_after_handover` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+6) |
| `test_steward_ucli_idle.PlanTest.test_ready_for_handover_already_written` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+7) |
| `test_steward_ucli_idle.PlanTest.test_observe_does_not_touch_handover_state` | EKSİK: parite testi olmayan observe_filter |
| `test_steward_ucli_idle.PlanTest.test_skips` | idle::plan_ucli_idle_vectors, idletext::ucli_idle_threshold_vectors |
| `test_steward_ucli_idle.PlanTest.test_chain_limit_and_reset_on_activity` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+8) |
| `test_steward_ucli_idle.PlanTest.test_dry_counts_do_not_block_act` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+8) |
| `test_steward_ucli_idle.PlanTest.test_legacy_record_without_mode_counts_as_dry` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+8) |
| `test_steward_ucli_idle.ApplyTest.test_nudge_is_sent_as_one_line` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+22) |
| `test_steward_ucli_idle.ApplyTest.test_nudge_skipped_when_input_box_has_text` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_ucli_idle.ApplyTest.test_close_handover_pauses_project_when_no_work` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_ucli_idle.ApplyTest.test_close_handover_keeps_phase_when_work_remains` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+21) |
| `test_steward_ucli_idle.ApplyTest.test_close_stop_and_respawn_use_existing_paths` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+23) |
| `test_steward_ucli_idle.ApplyTest.test_turn_failed_close_stops_and_asks_owner_once` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+32) |
| `test_steward_ucli_idle.ApplyTest.test_close_rejects_unknown_mode` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+19) |
| `test_steward_ucli_idle.DevamTextTest.test_clip_words_never_cuts_mid_word` | tour::clip_words_vectors |
| `test_steward_ucli_idle.DevamTextTest.test_next_hint_long_note_cut_on_word` | idletext::is_fable_polish_vectors, idletext::next_work_hint_vectors, tour::clip_words_vectors, tour::is_conditional_note_vectors |
| `test_steward_ucli_idle.DevamTextTest.test_same_devam_text_not_resent_after_answer` | idle::plan_ucli_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+8) |
| `test_steward_ucli_idle.ClaudeIdleTest.test_default_is_dry_and_ucli_untouched` | idle::plan_claude_idle_vectors, idle::plan_ucli_idle_vectors |
| `test_steward_ucli_idle.ClaudeIdleTest.test_nudges_after_threshold_with_next_work` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+11) |
| `test_steward_ucli_idle.ClaudeIdleTest.test_off_and_zero_do_nothing` | idle::plan_claude_idle_vectors |
| `test_steward_ucli_idle.ClaudeIdleTest.test_skips_busy_subagent_done_questions_no_work_paused` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_work_hint_vectors (+7) |
| `test_steward_ucli_idle.ClaudeIdleTest.test_chain_cap` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::is_fable_polish_vectors, idletext::next_line_vectors (+11) |
| `test_steward_ucli_idle.NotesWaitTest.test_notes_wait_detect` | idletext::notes_wait_vectors |
| `test_steward_ucli_idle.NotesWaitTest.test_due_project_with_bekleme_note_not_started_and_reason_recorded` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ucli_idle.ChainPauseFlowTest.test_claude_idle_skips_owner_wait` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::owner_wait_vectors (+6) |
| `test_steward_ucli_idle.ChainPauseFlowTest.test_pause_written_only_after_handover_finishes` | EKSİK: parite testi olmayan plan_tick |
| `test_steward_ucli_send.UcliSendTest.test_ucli_text_folded_not_truncated` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.UcliSendTest.test_non_ucli_untouched_and_no_recheck` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.UcliSendTest.test_claude_trust_dialog_blocks_send` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+5) |
| `test_steward_ucli_send.UcliSendTest.test_text_left_in_box_sends_one_more_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.UcliSendTest.test_still_stuck_logs_error` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_steward_ucli_send.UcliSendTest.test_stuck_event_uses_caller_sid` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.UcliSendTest.test_every_steward_send_call_passes_sid` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.UcliSendTest.test_late_drawn_text_gets_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.UcliSendTest.test_empty_box_no_extra_enter` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_prefixed_empty_prompt` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_prefixed_with_text` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_text_wrapped_over_two_lines` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_waiting_for_response_is_empty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_turn_output_after_prompt_is_empty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_last_prompt_line_wins` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ucli_send.BoxTextTest.test_no_prompt` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ui_api.UiConfigTest.test_config_writes_valid_int_and_mode` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_ui_api.UiConfigTest.test_config_rejects_bad_values_and_unknown_fields` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ui_api.UiConfigTest.test_config_review_budgets_and_script_choice` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_ui_api.UiConfigTest.test_brain_cannot_change_config_or_enable` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ui_api.UiConfigTest.test_drain_toggle_and_brain_directive_gate` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+4) |
| `test_steward_ui_api.UiConfigTest.test_enable_toggles` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+3) |
| `test_steward_ui_api.UiUpTest.test_up_enables_restores_and_starts_brain_but_brain_cannot` | identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges, identity::normalize_host_vectors (+7) |
| `test_steward_ui_api.UiShutdownStateTest.test_state_exposes_shutdown_only_when_started` | EKSİK: parite testi olmayan summarize_projects |
| `test_steward_ui_api.UiIdentityTest.test_create_validates_and_opens_off_observe` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+5) |
| `test_steward_ui_api.UiIdentityTest.test_brain_cannot_manage_identities` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_ui_api.UiIdentityTest.test_remove_refuses_default_unknown_and_nonempty` | identity::brain_name_for_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges (+8) |
| `test_steward_ui_api.UiIdentityTest.test_remove_refuses_while_review_job_runs` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+4) |
| `test_steward_ui_api.UiIdentityTest.test_remove_empty_identity` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+4) |
| `test_steward_ui_api.UiIdentityTest.test_transfer_moves_project_and_refuses_running` | identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges, identity::normalize_host_edges (+11) |
| `test_steward_ui_api.DirectiveDatedSessionTest.test_dated_session_gets_the_directive_without_a_start` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+30) |
| `test_steward_ui_api.DirectiveDatedSessionTest.test_two_live_sessions_are_ambiguous_and_nothing_starts` | closing::directive_keeps_phase_vectors, closing::is_wrap_up_directive_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors (+24) |
| `test_steward_ui_api.UiServiceJobTest.test_add_list_hides_token_and_rm` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+10) |
| `test_steward_ui_api.UiServiceJobTest.test_add_validates_and_brain_refused` | identity::name_rules_edges, identity::valid_name_vectors |
| `test_steward_ui_api.UiServiceJobTest.test_rm_refused_with_open_job_and_ack_only_terminal` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+10) |
| `test_steward_upper_main.TestPure.test_picks_only_running_main_sessions_above_sonnet_medium` | gates::is_claude_model_vectors, gates::is_upper_tier_vectors, gates::upper_main_views_vectors, prompts::phase_model_effort_vectors |
| `test_steward_upper_main.TestPure.test_owners_explicit_upper_choice_is_not_flagged` | gates::is_claude_model_vectors, gates::is_upper_tier_vectors, gates::upper_main_views_vectors, prompts::phase_model_effort_vectors |
| `test_steward_upper_main.TestPure.test_only_claude_family_models_are_audited` | gates::is_claude_model_vectors, gates::is_upper_tier_vectors, gates::upper_main_views_vectors, prompts::phase_model_effort_vectors |
| `test_steward_upper_main.TestPure.test_is_upper_tier_itself_stays_model_family_agnostic` | gates::is_upper_tier_vectors |
| `test_steward_upper_main.TestPure.test_reviewer_role_is_not_audited` | gates::upper_main_views_vectors |
| `test_steward_upper_main.TestPure.test_reminder_text_is_a_reminder_not_an_order` | gates::upper_main_text_vectors |
| `test_steward_upper_main.TestTick.test_upper_main_logged_once_and_never_sent_to_the_session` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_flapping_unknown_live_reading_is_not_a_change` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_unknown_effort_on_known_upper_model_is_not_a_change` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_known_change_or_back_and_up_again_logs_again` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_new_process_same_combo_logs_once_more` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_observe_mode_logs_too` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_setting_off_disables` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestTick.test_sonnet_medium_main_is_silent` | EKSİK: parite testi olmayan dry_ask_due, observe_filter, plan_tick |
| `test_steward_upper_main.TestCollectViews.test_status_row_live_values_reach_the_view` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::normalize_host_edges (+14) |
| `test_steward_upper_main.TestCollectViews.test_dated_local_session_without_instance_resolves_to_its_project` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+24) |
| `test_steward_upper_main.TestCollectViews.test_remote_row_live_values_reach_the_view` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_steward_urgent_answers.TourPause.test_break_is_short_and_retries` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_urgent_answers.TourPause.test_new_item_resumes_immediately` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_urgent_answers.TourPause.test_break_payload_has_minutes` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_urgent_answers.TourPause.test_other_kinds_keep_long_pause` | recovery::loop_guard_vectors, recovery::p_loop_sig |
| `test_steward_urgent_answers.TbdInsert.test_under_matching_item` | inserts::tbd_insert_answer_vectors |
| `test_steward_urgent_answers.TbdInsert.test_append_when_not_found_and_idempotent` | inserts::tbd_insert_answer_vectors |
| `test_steward_urgent_answers.Preserve.test_local_written_and_committed_only_that_file` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+8) |
| `test_steward_urgent_answers.Preserve.test_remote_and_no_folder_notify` | identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order, identity::p_pp (+7) |
| `test_tmux_send_raw_semicolon.SemicolonArgv.test_trailing_semicolon_escaped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_tmux_send_raw_semicolon.SemicolonArgv.test_whole_semicolon_chunk` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_tmux_send_raw_semicolon.RealTmux.test_literal_roundtrip` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_tmux_send_raw_semicolon.JobAttemptsResetOnStateChange.test_state_change_resets_attempts` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_todo_triage.Plan.test_mismatch_sends_one_triage_not_continue` | idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::turn_failed_vectors, idletext::waiting_for_gate_vectors (+5) |
| `test_todo_triage.Plan.test_owner_wait_text_also_triggers` | idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::owner_wait_vectors, idletext::turn_failed_vectors (+5) |
| `test_todo_triage.Plan.test_same_sha_never_again_and_no_continue_nudge` | idle::p_forced_open_nudge, idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::turn_failed_vectors (+6) |
| `test_todo_triage.Plan.test_changed_todo_allows_again` | idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::turn_failed_vectors, idletext::waiting_for_gate_vectors (+5) |
| `test_todo_triage.Plan.test_zero_open_sends_nothing` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+11) |
| `test_todo_triage.Plan.test_no_sha_available_sends_nothing_extra` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+11) |
| `test_todo_triage.Plan.test_dry_and_act_counted_separately` | idle::plan_claude_idle_vectors, idletext::next_none_stated_vectors, idletext::turn_failed_vectors, idletext::waiting_for_gate_vectors (+5) |
| `test_todo_triage.Plan.test_session_with_real_work_still_gets_normal_nudge` | idle::plan_claude_idle_vectors, idletext::idle_finish_marker_vectors, idletext::next_line_vectors, idletext::next_none_stated_vectors (+10) |
| `test_todo_triage.Plan.test_busy_or_recent_untouched` | idle::plan_claude_idle_vectors |
| `test_todo_triage.Plan.test_explain_reason` | explain::explain_idle_vectors, explain::p_why, idletext::idle_finish_marker_vectors, idletext::next_line_vectors (+12) |
| `test_todo_triage.Plan.test_observe_list_and_preamble_rule` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_todo_triage.Sha.test_sha_changes_with_content_and_unknown_is_empty` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.ValidateMaxCostTests.test_valid_values` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.ValidateMaxCostTests.test_zero_or_empty_drops_the_key` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.ValidateMaxCostTests.test_invalid_values_rejected` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.MaxCostArgsTests.test_priced_model_gets_the_flag_once` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.MaxCostArgsTests.test_unpriced_model_is_skipped_and_logged` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.MaxCostArgsTests.test_binary_without_flag_is_skipped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_server_name_follows_ucli_rule` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_add_argv_shape` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_launch_args_register_then_with_mcp` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_failed_add_means_no_with_mcp` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_nothing_runs_without_tools_workspace_or_flag` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_symlinked_state_dir_is_refused` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.McpRegisterTests.test_steward_spec_allowlists_exactly_the_steward_tools` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.BuildWithMcpTests.test_only_with_mcp_is_taken_from_extra_args` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.BuildWithMcpTests.test_claude_service_with_cost_cap_and_mcp` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.SpawnCwdWiringTests.test_cwd_only_for_providers_that_ask` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.SpawnCwdWiringTests.test_dry_run_preview_shows_env_and_command_not_priority_prefix` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.SpawnCwdWiringTests.test_dry_run_preview_masks_secret_env_values` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.SpawnCwdWiringTests.test_dry_run_preview_caps_very_long_command` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_brain_mcp.BrainUcliTests.test_default_claude_brain_passes_no_cli_opts` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+6) |
| `test_ucli_brain_mcp.BrainUcliTests.test_ucli_brain_uses_claude_service_and_cost_cap` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+6) |
| `test_ucli_brain_mcp.BrainUcliTests.test_settings_override_service_model_and_cap` | identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors (+7) |
| `test_ucli_brain_mcp.BrainUcliTests.test_defaults` | identity::name_rules_edges, identity::valid_custom_id_vectors, identity::valid_steward_id_vectors |
| `test_ucli_brain_mcp.BrainUcliTests.test_unknown_service_refuses_without_spawn` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+6) |
| `test_ucli_brain_mcp.BrainUcliTests.test_spawn_refusal_is_reported_not_raised` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+6) |
| `test_ucli_brain_mcp.BrainUcliTests.test_claude_brain_value_error_still_raises` | identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors (+4) |
| `test_ucli_cost_watch.CostWatch.test_no_cap_does_nothing` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_warn_once_at_80` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_second_warning_at_90_once` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_cap_stops_brain_once` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_default_identity_in_steward_ids_not_double_counted` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_claude_brain_not_stopped` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_raising_cap_rearms_watch` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_cap_stops_all_ucli_identities` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_failed_brain_stop_retries_without_renotify` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_ucli_cost_watch.CostWatch.test_same_cap_does_not_rearm` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |
| `test_web_review_runner.TestEvren.test_argv_safe_and_key_in_env_only` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_no_io_flag_when_unsupported` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_claude_env_filtered` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_redact_applied_and_answer_extracted` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_timeout_writes_partial` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestEvren.test_effort_always_sent_unless_model_rejects_it` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_partial_file_flag_added_only_when_supported` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_partial_file_path_is_symlink_free` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_killed_run_is_recovered_from_partial_file_masked` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_partial_without_report_heading_is_not_a_report` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestEvren.test_partial_turn_in_error_json_is_recovered` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_failed_run_keeps_error_log_masked_0600` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestEvren.test_successful_run_has_no_error_log` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestEvren.test_nonzero_no_output_is_error` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestEvren.test_busy_lock` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestEvren.test_missing_key_errors_and_releases_lock` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestCancel.test_cancel_kills_own_group_and_marks_partial` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestCancel.test_cancel_before_process_exists_is_not_swallowed` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestCancel.test_cancelled_before_spawn_kills_new_process` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestAgy.test_isolated_home_with_readonly_allow_list` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_bwrap_jail_wraps_argv_when_available` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_no_bwrap_or_jail_off_falls_back_to_allow_list` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_agy_model_quota_blocks_only_that_model_until_reset` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_tmpdir_is_writable_home_tmp_and_stale_entries_pruned` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_allow_override_and_off` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_ok_done_and_argv` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_label_mismatch_is_model_fallback_but_file_kept` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_no_log_is_model_fallback` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_old_log_not_taken_for_new_run` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestAgy.test_no_effort_for_non_gemini` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestAgy.test_model_not_in_agy_list` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestBannerLimit.test_monthly_quota_banner_with_rc0_is_limit_not_done` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestBannerLimit.test_real_report_mentioning_quota_stays_done` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+6) |
| `test_web_review_runner.TestBannerLimit.test_month_start_helper` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestBodyless.test_failed_run_with_junk_body_is_error` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestBodyless.test_successful_exit_with_junk_body_is_error` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::name_rules_edges, identity::ownership_index_edges_keep_order (+8) |
| `test_web_review_runner.TestBodyless.test_report_bodyless_rule` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestRecover.test_recover_on_start` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestRecover.test_recover_on_start_salvages_draft_report` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestRecover.test_recover_on_start_salvages_report_from_io_log` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestRecover.test_recover_on_start_no_report_head_keeps_file_empty` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestDetached.test_findings_are_saved_before_pair_turns_done` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestDetached.test_detached_run_writes_files_and_finishes` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestDetached.test_restart_adopts_live_run_and_finishes_it` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_web_review_runner.TestDetached.test_run_finished_while_service_down_is_processed` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_web_review_runner.TestDetached.test_pid_reuse_is_not_adopted_as_alive` | identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_runner.TestDetached.test_adopt_keeps_pre_restart_io_log` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_web_review_runner.TestDetached.test_adopt_failure_marks_partial_not_stuck_running` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors, logdedup::old_subjects_are_evicted_past_the_cap (+1) |
| `test_web_review_runner.TestDetached.test_without_cfg_old_behavior_partial` | identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors |
| `test_web_review_tick.TestReviewerSmalls.test_report_file_is_private` | identity::name_rules_edges, identity::paths_for_vectors, identity::paths_layout_and_errors, identity::valid_custom_id_vectors |
| `test_web_review_tick.TestReviewerSmalls.test_cfg_lang_reaches_run_job` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_pool_autofills_and_starts_one_job_at_a_time` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_remote_project_skipped` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::derived_of_vectors, identity::from_dict_drops_unknown_and_requires (+35) |
| `test_web_review_tick.TestTick.test_disabled_identity_starts_nothing_and_cancels` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_disabled_project_cancels_running_job` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_readded_project_resumes_skipping_done_pairs` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_drain_finishes_running_job_but_starts_nothing_new` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_min_gap_blocks_start` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestTick.test_recover_once_and_missing_cwd_skipped_and_no_targets` | identity::brain_name_for_vectors, identity::build_ownership_index_vectors, identity::from_dict_drops_unknown_and_requires, identity::name_rules_edges (+15) |
| `test_web_review_tick.TestModelsFailure.test_current_targets_swallows_errors` | EKSİK: saf çekirdek çağrısı yok, gerekçe yazılmadı |

<!-- MAP:END -->
