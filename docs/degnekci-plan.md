# Değnekçi (steward) — plan ve handover notu

Son güncelleme: 2026-10-19 (Sonnet 5.5 oturumu: faz 1 `9c1e612` + faz 2 ile proje kartları ve observe modu/günlük özet ana dalda; faz 0 `369c931`).
Bu dosya tasarım/plan belgesidir; kişisel fleet notları (TODO.md / TOBEDECIDED.md / DONE.md) her zamanki
gibi private docs reposunda tutulur. En alttaki "yapıştırmalık" bloklar oraya taşınmak için.

## Ne var (faz 0, bitti)

- `py/claudeops/steward.py` — saf çekirdek: proje kayıtları (faz `idea|planning|planned|paused|done`,
  öncelik 1-5, `cadence_minutes`, not, model/effort), soru kutusu, fikir kutusu, state, `log.jsonl`;
  `plan_tick` kural motoru; faz direktifleri; beyin tur prompt'u; `STEWARD-ASK/IDEA/BLOCKED/PLAN-READY/DONE`
  işaretleri; `review_items`.
- `py/claudeops/commands/web_steward.py` — `py/cops web` içinde daemon döngü (`steward.enabled`, varsayılan
  KAPALI), eylemler `web.py`'nin kendi `_start/_stop/_handover/_register_project`'iyle, `/api/steward/*`,
  beyin oturumu (`degnekci`, cwd `~/.claude/claudeops/steward/workspace`, CLAUDE.md = persona + araç kılavuzu,
  `--mcp-config` ile `py/cops mcp-steward`), ntfy bildirimi, `http_register` (klasör + git init + GOAL.md +
  kaynak kopyalama + roster).
- `py/claudeops/commands/mcp_steward.py` — 16 araç; protokol döngüsü `mcp_queue.py`'den paylaşılır.
- `py/claudeops/commands/steward.py` — `py/cops steward` CLI.
- `py/claudeops/data/steward.md` — persona (Ayarlar `steward_persona_text` ile ezilir).
- `settings.json` `steward` bloğu + `steward_config()`; `/api/status` içinde hafif `steward` özeti.
- `py/tests/test_steward.py` — 27 test. Tam paket geçiyor; `test_web_ws_ping.py` bu cloud ortamında
  temiz `main`'de de asılı kalıyor (ortam, kodla ilgisiz).
- Bilinen sınırlar: panel sekmesi yok; direktif enjeksiyonu tmux ister; MCP claude/codex'te var, agy'de
  yok; model/effort yalnız yeniden açılışta uygulanır; `_wait_ready` sezgisel.

## Ne var (faz 1-2, bitti)

- **Proje kartları** — `steward/cards/<ad>.json`: `goal`, `phase_guess`, `next_step`, `open_tbds[]`,
  `blockers[]`, `recent_done[]`, `last_activity`, `source_hash`, `updated_at` (+ `summarized`, `stale`,
  `model`, `cli`, `last_error`/`attempt_*`). Ham kısım `steward.build_raw_card(cwd)` (GOAL/PLAN/TODO/
  TOBEDECIDED/DONE başları + `git log -5`, modelsiz); özet `web_steward.summarize_card` →
  `CliProvider.oneshot` (claude `-p ... --output-format text --tools ""`, ucli `ucli_chat_once`; diğer CLI'lar
  desteklemez). JSON çıkmazsa ham karttan türetilen kart kalır. Tick'te, ÇALIŞMAYAN aktif fazlı projelerden
  kartı olmayan / bayat (respawn sonrası) / `source_hash`'i değişmiş / `card_max_age_hours`'tan eski olan
  `cards_per_tick` kadarı yenilenir (arka plan thread'i, tick kilidi dışında; başarısız deneme aynı kaynak için
  geri çekilir). `http_context` ve tur maddeleri ham doc başları yerine kartı verir (`docs=true` ikisini),
  `projects`/`steward_overview` `next_step` taşır. `py/cops steward cards [AD] [--refresh]`;
  `GET /api/steward/cards|card`, `POST /api/steward/cards/refresh`.
- **Observe modu** — `steward.mode = observe | act` (VARSAYILAN observe). observe'da `handover/respawn/start/
  stop/deliver_answer/tour` uygulanmaz: `log.jsonl`'a `would:<tür>`, `_RECENT`e `dry=True`; aynı anahtar 6 saatte
  bir (`steward.observe_filter`). Uğrama `observed_visit` ile cadence'a göre ilerler. `ask_user/idea/set_phase`
  ve kart yenileme çalışır. Beynin MCP çağrıları (`actor: brain`) da observe'da kuru döner. Her tick `tick`
  olayı loglar (özetin sayacı).
- **Günlük özet** — `steward.daily_summary(entries, date, lang, pending)` (saf) →
  `steward.summary_hour` (21) sonrası günde bir `steward/daily/<tarih>.md` + ntfy + `summary` olayı;
  `py/cops steward summary [--date] [--lang] [--save]`, `GET /api/steward/summary`.
- Testler: `py/tests/test_steward.py` 53 test. Tam paket (test_web_ws_ping hariç) 1324+ test yeşil.
- Küçükler (2026-10-19, Fable oturumu): özet sonrası günün `tick` satırları tek `ticks` satırına katlanır
  (`steward.compact_log`, özet aynı kalır) + 5 MB'da `log.jsonl.1`e devir (`rotate_log`); kaçan günlerin özeti
  açılıştan sonraki ilk tick'te (`missed_summary_dates`, 3 gün geriye, yalnız kaydı olan günler, ntfy'de
  "(gecikmiş özet)"); claude `-p` kart çağrısına `--no-session-persistence` YALNIZ `claude --help` listeliyorsa
  (`claude_provider.claude_supports_flag`, ucli'deki `binary_supports_flag` disiplini: eski ikili bayrağı
  tanımayınca "unknown option" ile çıkardı).
- Bilinen sınırlar / sonraki adımlar: `suggest` modu yok; kart yenileme çalışan projelere dokunmaz (çalışırken
  kart eski kalabilir); ucli kart yolu gerçek Evren ile denenmedi.

## Ne var (faz 3, bitti)

- **Soru seçenekleri** — `Question.options` (≤6, ≤80 karakter, `steward.normalize_options`), `key` (soruya özel
  16 hex anahtar), `notified_at`. `resolve_answer`: `1`/`A`/metin → kanonik seçenek, aksi serbest metin.
  `steward_ask_user` MCP aracı `options` alır; `py/cops steward ask [-p P] [-o A -o B] "soru"` panel
  üzerinden; `questions` seçenekleri basar. Aynı açık soru ikinci kez bildirilmez.
- **`/q/<id>?k=<key>`** — `web.py` `do_GET/do_POST` başında, panel token'ından BAĞIMSIZ yetki (anahtar sabit
  zamanlı karşılaştırma; token da geçer). Sayfa saf `steward.question_page_html` (inline CSS, JS yok, 320 px'te
  taşma yok, kaçışlı); form POST `answer` → `answer_question` + `answer` olayı (`source: phone`) + WS bildirimi.
  ntfy gövdesi `question_notification` (seçenekler numaralı + bağlantı), `Click` başlığı sayfayı açar; bağlantı
  tabanı `tunnel_url.txt` (yoksa yalnız CLI ipucu).
- **Panel "Değnekçi" sekmesi** — `StewardTab.tsx`: `data.steward` (WS) sayaçları değişince `/api/steward/state`
  çekilir (kendi zamanlayıcısı yok). Üç sayı + proje/faz, soru kartları (seçenek düğmesi ya da metin),
  "soru aç" (seçenekli), proje tablosu (çalışıyor noktası, faz, öncelik, kartın sıradaki adımı, son uğrama),
  fikir kutusu (ekle/sonra/vazgeç), son eylemler (`dry` işaretli), `tick` düğmesi. Sekme etiketi açık soru
  sayısını taşır. Headless Chromium ile uçtan uca sürüldü (cevaplama, fikir, soru açma, EN/TR, telefon sayfası).
- Yapılmayanlar: mod değiştirme/ayarlar sekmede yok (CLI `config mode`); soru sıklığı sınırı (TBD#94) yok.

## Kararlar (2026-10-19 sohbeti)

- Model eğitimi YOK (şimdilik). "Benim gibi düşünme" = persona + **karar hafızası** (transkript ve
  TOBEDECIDED.md'den çıkarılan soru/cevap çiftleri). Yüzlerce cevaplı soru birikince dar bir
  sınıflandırıcı düşünülebilir; `questions.json` zaten o veri setidir.
- Beyin 160 repoyu değil **proje kartlarını** okur.
- Güven rampası: `observe → suggest → act`. İlk hafta observe.
- Mekanik işler (kart özetleme, çıkarım) ucuz/yerel model; tur kararları Sonnet/Opus sınıfı.
- İmplementasyon modeli: faz 1-2 Sonnet 5.5 (high). Faz 4 (karar hafızası) ve review turları için
  Opus/Fable'a dönülür.

## Plan

1. ~~**Proje kartları**~~ (bitti, `9c1e612`)
2. ~~**Observe modu + günlük özet**~~ (bitti)
3. ~~Soru seçenekleri (`options`) + `/q/<id>` compact mobil sayfa + panelde "Değnekçi" sekmesi~~ (bitti)
4. Karar hafızası (transkript + TOBEDECIDED.md çıkarımı, benzer karar getirme)
5. `suggest`/`act` modları, proje bazında yetki
6. Bütçe: günlük token tavanı, `/usage` kota okuma, gece toplu çalışma

## Faz 1-2 implementasyon brief'i (UYGULANDI — tarihçe için duruyor)

```
claudeops değnekçi — faz 1 ve 2 implementasyonu. Bağlam: docs/degnekci-plan.md, py/README.md
"The steward" bölümü, py/claudeops/steward.py (çekirdek), commands/web_steward.py (motor),
tests/test_steward.py. Doğrudan main'de çalış, yeni dal açma. Her adımda test + commit + push.

1) Proje kartları
- steward/cards/<ad>.json: {goal, phase_guess, next_step, open_tbds[], blockers[], recent_done[],
  last_activity, source_hash, updated_at}. Saf build_raw_card(cwd): GOAL/PLAN/TODO/TOBEDECIDED/DONE
  başları + git log -5 + son commit tarihi (model yok, testlenir).
- summarize_card(raw): tek seferlik headless çağrı. CliProvider'a oneshot_argv(prompt, model) ekle;
  claude: `claude -p --model <m> --output-format text --tools ""` (dosya okutma, içerik prompt'ta;
  stdin /dev/null), ucli: ucli_client.ucli_chat_once. JSON iste, parse edilemezse ham kart kalsın.
- Ayar: steward.card_cli (claude), card_model ("" = model_choices içinde "haiku" geçen),
  card_max_age_hours (24), cards_per_tick (1), card_refresh (on).
- Yenileme: tick'te kartı olmayan / eskimiş / source_hash değişmiş ve ÇALIŞMAYAN aktif-fazlı proje,
  tick başına 1; respawn sonrası stale işaretle. CLI: py/cops steward cards [--refresh] [AD].
- Kullanım: http_context ve tur maddeleri ham doc başları yerine kartı versin; `projects` listesi
  next_step göstersin; steward_overview'a next_step.

2) Observe modu + günlük özet
- steward.mode = observe | act (varsayılan observe). observe: handover/respawn/start/stop/
  deliver_answer/tour uygulanmaz, log'a would:<kind> + _RECENT'e dry=True yazılır; ask_user/idea/
  set_phase/kart yenileme çalışır.
- Günlük özet: saf daily_summary(log_entries, date, lang) -> metin (tick sayısı, would/yapılan
  eylemler türe göre, açılan/cevaplanan soru, fikir, yenilenen kart, handover'lar, bekleyen
  maddeler). Günde bir steward.summary_hour (21) sonrası: steward/daily/<tarih>.md + ntfy +
  log. CLI: py/cops steward summary; API: GET /api/steward/summary.
- README (EN+TR) güncelle, test ekle, docs/degnekci-plan.md'yi "Ne var" kısmıyla güncelle.
```

## Yapıştırmalık: TODO.md

```
## Değnekçi (steward) — 2026-10-19
- [ ] Proje kartı: CLAUDE/TODO/TOBEDECIDED/DONE'dan ucuz modelle özet; handover'da yenile; context aracı kartı dönsün
- [ ] steward.mode = observe | suggest | act; observe'da sadece log + günlük ntfy özeti
- [ ] Soru `options` alanı (evet/hayır, A/B/C, sonra) + /q/<id> compact mobil sayfa + ntfy deep link
- [ ] Panelde "Değnekçi" sekmesi: üç sayı, soru kartları, proje listesi, fikir kutusu
- [ ] Karar hafızası: transkript + TOBEDECIDED.md'den (soru, cevap, proje, tarih) çıkar; beyin karar öncesi benzerleri alsın
- [ ] TBD iletimi: TOBEDECIDED.md açık maddelerini soruya çevir, cevabı dosyaya ve oturuma yaz
- [ ] Beynin kendi handover'ı: NOTLAR.md'de hafıza, CLAUDE.md her açılışta yeniden yazılıyor
- [ ] ucli provider ile beyin: MCP araçları ucli'de çalışıyor mu doğrula (yerel model yolu)
- [ ] Bütçe: günlük token tavanı, /usage kota okuma, gece batch penceresi
- [ ] Direktif enjeksiyonunda "hazır" tespiti sezgisel (_wait_ready); claude için MCP push ile değiştir
- [ ] Roster'da olmayan projeye set yapılınca her tick başarısız start; set anında uyarı var, API'de de reddet
- [ ] history_size None (tmux'suz oturum) için handover sinyali yok; context_command ile ölç
- [ ] test_web_ws_ping.py cloud ortamında asılı kalıyor (websockets request_line.encode ascii); yerelde doğrula
```

## Yapıştırmalık: TOBEDECIDED.md

```
- TBD: Model eğitimi — fine-tuning yok; önce karar hafızası + persona. Yüzlerce cevaplı soru birikince dar sınıflandırıcı. (2026-10-19: şimdilik yok, kabul)
- TBD: Beyin modeli — tur kararları Sonnet/Opus, mekanik çıkarım yerel/ucuz mu, tamamı tek model mi?
- TBD: Varsayılan yetki — yeni projeler observe mi suggest mi başlasın; act proje bazında mı global mi?
- TBD: Soru sıklığı — günde en fazla N soru, geri kalanı toplu "akşam turu" mu?
- TBD: 160 proje, 4 slot: devir süresi ~3 gün kabul mü, max_active kota okuyarak dinamik mi?
- TBD: Kart yenileme tetiği — her handover mı, her commit mi, günde bir mi? (brief: 24 saat + hash değişimi, çalışmayan proje)
- TBD: Transkript tarama kapsamı — tüm jsonl'ler mi, son 90 gün mü; kişisel içerik filtresi?
- TBD: Fikir → proje kararı beyne mi, her zaman sana mı?
```

## READY FOR HANDOVER (2026-10-19)

- Faz 0 ana dalda (`369c931`), testler yeşil, push edildi; working tree temiz.
- Kullanıcı kararı: planla devam, faz 1 ve 2 ile başla; implementasyon Sonnet 5.5 (high) ile yeni oturumda.
- Yeni oturuma ilk mesaj: yukarıdaki brief bloğu, olduğu gibi.
- Private docs reposuna taşınacak: yukarıdaki iki yapıştırmalık blok.
- Açık değil, bekleyen yok: değnekçi `steward.enabled` kapalı; hiçbir canlı oturuma dokunulmadı.
