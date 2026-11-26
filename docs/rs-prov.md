# İz rs/prov: `cops-providers` (W1-pre sağlayıcılar)

Durum (26 Kas 2026): **BİRLEŞTİRMEYE HAZIR DEĞİL** (eşleme tablosunda EKSİK G1-G11 ve ders listesi açık). `cargo clippy -p cops-providers
--all-targets -- -D warnings` temiz, `cargo test -p cops-providers` 8/8.

## Parite (`tests/parity.rs`)
- Python tek alt süreçte (boş ortam, geçici HOME/CLAUDEOPS_DIR/PATH, eklentiler kapalı), süreç/ağ çağrıları sahte. Her vaka aynı
  başlangıç ağacından iki tarafta koşar; dönüş, hata metni, diag, argv ve dosya ağacı (izinlerle) karşılaştırılır.
- 1646 vaka: model/effort 105, settings/pyfmt 84, build 315, ucli 324, spawn 392, misc 426.
- 26 "bilinen ayrışma" testte gerekçesiyle kayıtlı (eşit çıkarsa test düşer): Python hatası 8, Python repr/JSON metni 5, sınırsız int 2,
  dize olmayan kimlik 2, NaN 1, Unicode kategorisi 2, urlsplit NFKC 1, daha sıkı regex 3, doğrulanmamış `exec_cmds` 2, Effect sözleşmesi 1.
- Tek vakanın Python çıktısı: `COPS_PARITY_DUMP=<vaka-id> cargo test -p cops-providers --test parity -- --nocapture`.
- Kapsanmayan: süreç başlatma, tmux parçası, resume taraması, hayalet oturum temizliği; gerçek `Effect` uygulayıcısı; eşzamanlı yazım ve
  zaman aşımı; `--help` önbellek tazelemesi.
- Rust'ta henüz yok: `rust_toolchain`, `_rustup_default_toolchain`, `path_executables` (`_CMD_RE`); `_sync_one` dosya adımları;
  `normalize_ucli_services` `label`/`models`, `service_models`, `ucli_cost_config` tavan/kredi; diag `ucli_web_searxng_error`,
  `ucli_usage_log_dir_failed`; model listesi TTL önbellekleri.
- Python hatası şüpheleri: TBD#373 (Rust şimdilik Python gibi ya da kayıtlı ayrışma).
- API değişikliği: `plan_spawn(p, req, &mut BuildOutput)` (hata durumunda da biriken Effect/diag korunur).

## Kapsam (ilk görev metni)
- Yazılabilir yollar: `rust/crates/cops-providers/**`, `rust/Cargo.toml` members satırı, `docs/rs-prov.md` (`rust/Cargo.lock` yeni bağımlılıklarla değişti).
  `py/` ve diğer crate'lere YAZMA. `docs/rust-*.md`, CLAUDE.md, TODO.md, TOBEDECIDED.md, DONE.md symlink: bu dalda git add etme.
- Saf mantık (G/Ç yok): `providers/` spawn argv + ortam, resolve_effort/default_effort_for/default_model_for/preferred_default_model,
  `_EFFORT_LIMITS`, agy `gemini-*-high` kademesi, `routing.py` yönerge bayrakları, spawn_nice, main_session_model_effort.
- Parite: Python'u alt süreçte (`PYTHONPATH=py`, geçici `CLAUDEOPS_DIR` ve geçici `HOME`) çağıran tablo testi; tüm sağlayıcılar ve effort/model kombinasyonları.
- Kurallar: önce `docs/rust-sprint-plan.md`, strangler planı 1-4 ve 10, CLAUDE.md. Kendi dalına commit, origin+gitlab'a push; main'e push/merge YOK.
  Testler canlı durum dizinine yazmaz. Ana oturum Sonnet; zor tasarım Opus alt ajan; Fable yok. Sahibe soru: cevabın sonunda `STEWARD-ASK:`.
  Cargo hedefi `~/.cargo-target`. Bitişte son satır: `BİRLEŞTİRMEYE HAZIR: <dal> <commit> <test özeti>`. Canlıya almayı cops yapar.

## EK (sahip 26 Kas): Python dersleri
`docs/rust-lessons-from-python.md` genel liste + bu izin kontrol listesi ZORUNLU; her madde burada test adı ya da gerekçeyle karşılanır.
26 Kas devir anında dosya YOKTU: yeniden bak.

## EK 2 (sahip 26 Kas): işlevce eşlik
- Rust'ta Python'dan eksik hiçbir şey kalmayacak. Aşağıdaki EŞLEME TABLOSU: kapsamdaki modüllerin HER işlev/metot/sınıf/modül düzeyi
  ataması (ast) bir satır; HER `py/tests` `test_*` metodu bir satır (Rust test adı ya da neden gereksiz).
- Boş/"sonra"/AÇIK satır varken BİRLEŞTİRMEYE HAZIR yazılmaz. cops tabloyu ast çıktısıyla karşılaştırır.
- Boş girdi, bozuk JSON/dosya, Unicode, eksik alan, eşzamanlı yazım, zaman aşımı Python gibi davranır. Python davranışı hatalıysa
  sessizce düzeltme: tabloda `Python hatası?` + `STEWARD-ASK`.
- İlk görev metni yalnız komut kurulumu/effort/model/yönerge/nice istiyordu; EK 2'nin "izin kapsadığı modüller"i için ayrıştırıcılar, keşif
  (`matches_proc`/`extract_*`), transkript okuma, kullanım ayrıştırma satırları da tabloya girer: ya taşınır ya `kapsam dışı: neden + iz` yazılır.

## Tasarım (yazılan)
- `Probe` (dış olgular) + `Effect` listesi (dosya yazma/silme isteği, sırayla uygulanır) + `Diag` (diag_log olayları). Sır içeren `Effect`
  Debug'da maskeli. Durum değiştiren üç `Probe` yöntemi: `claude_cost_gate`, `issue_agent_token`, `register_mcp`.
- Modüller: `provider` (Cli enum, model/effort, build), `claude|agy|codex|copilot|shell|ucli`, `ucli_opts`, `routing`, `spawn`, `settings`, `effort`, `pyfmt`.
- `resume_id` çözümü (transkript taraması) ve `_ids_held_by_others` girdi sayıldı.

## Sıradaki
1. EŞLEME TABLOSU'ndaki EKSİK grupları taşı (aşağıdaki liste). Önerilen sıra: G11, G5, G6, G2, G3, G7, G1, G8, G4, G10, G9.
2. TAŞINDI-TESTSİZ test satırları için parite vakası ya da birim testi ekle.
3. `docs/rust-lessons-from-python.md` genel liste ve bu izin kontrol listesini madde madde karşıla.
4. `cargo fmt --check` şu an farklı (rustfmt.toml yok; satır genişliği elle 120): diğer crate'lerin biçimine bak, karar ver.
5. Birim testi yalnız `pyfmt.rs`de (2 test): effort, `with_block`, `validate_opts`, "sır argv'de yok" için ekle.
6. Birleştirmede: `main_session_model_effort` rs/stew'de de var (tek kopya); `is_safe_env_name`, `py_*` yardımcıları ve ayar okuma rs/proc, rs/state ile ortaklaştırılmalı.

## Parite testinde bakılacak bilinen farklar / şüpheler
Parite testinde kayıtlı ayrışmalar yukarıdaki "Parite" bölümünde. Açık kalanlar:
- Mutasyonlar `Effect` olduğundan Python'da yazım hatasının komutu değiştirdiği dallar (anahtar dosyası yazılamazsa istisna, metrics mkdir hatası = bayrak yok, usage-log dizini hatası, yönerge override yazılamazsa bayraksız açılış) çağıran sözleşmesine kalıyor; gerçek uygulayıcıyla (G8) sınanmalı.
- `register_mcp`: günlük olayları crate'te; silme, 20 sn zaman aşımı ve `OSError` metin biçimi gerçek `Probe` uygulamasında sınanacak (G8).
- `_MCP_TOOL_RE`: Rust (`valid_tool_name`) Python gibi sondaki tek satır sonunu kabul ediyor; TBD#373 cevabına göre iki tarafta birlikte düzeltilecek.
- `copilot.rs::trust_folder_edit` ve Python `trust_folder`: dizinin sonu ilk `]` ile aranıyor; kayıtlı bir yol ya da `cwd` `]` içeriyorsa aynı giriş her açılışta yeniden eklenir (yeni Python hatası şüphesi, henüz sorulmadı).
- `Settings` yalnız ayrıştırılmış nesneyi yorumlar; Python `load_settings`in varsayılan birleştirmesi ve bilinmeyen anahtar süzmesi rs/state'te. Birleştirmede iki okuyucu aynı belgeyi görmeli.

## EKSİK taşıma grupları
Satır sayıları aşağıdaki iki tablodan üretildi (işlev/atama satırı + test satırı).

| Grup | Kapsam | işlev/atama | test | zorluk notu |
|---|---|---|---|---|
| G1 oturum kimliği ve devam | resume çözümü (claude/codex/agy/copilot transkript taraması, `_ids_held_by_others`), durdurulmuş oturum sid'i, canlı sid anlık görüntüsü/keşfi, agy sid yazımı, transkript yolu düşüşü | 39 | 35 | zor: Python davranış ayrıntısı çok (stub eleme, cwd/ad eşleme, önbellek); rs/proc ve rs/state'e bağlanır |
| G2 sohbet geçmişi okuma | `last_exchange`/`full_history`/`extra_file_roots` (claude, codex, agy protobuf, copilot SQLite, ucli jsonl) | 38 | 24 | orta-zor: dört ayrı biçim, boundary/summary rolleri |
| G3 transkriptten model/effort ve önbellek sıcaklığı | `last_assistant_*`, `live_or_spawn_*`, `last_real_request_epoch`, TTL ve effort-önbellek kuralı | 18 | 54 | orta: tek dosya ailesi, kuyruktan okuma |
| G4 TUI girdisi, canlı geçiş, devir kancaları | canlı model/effort değiştirme, başıboş diyalog, `prepare_input`, mod kalıpları, `wants_*` | 37 | 17 | orta-zor: rs/tmux'a bağlı, zamanlama ve kör Enter kuralları |
| G5 kota/bağlam komutları ve ayrıştırma | `usage_*`, `context_*`, `parse_*` ve regex'leri | 36 | 9 | orta: saf ayrıştırıcılar, parite kolay |
| G6 canlı durum okuyucuları | ucli durum dosyası (`live_*`, faz, hata kayıtları), `background_work` (`bg_work`), codex/copilot bağlamı, meşgul kalıpları | 39 | 51 | orta: çok satır, çoğu bağımsız saf okuma |
| G7 model kaynakları | `agy models`, codex/claude belge okuma, ucli `/models` HTTP, `service_models`, TTL önbellekleri | 17 | 11 | orta: G/Ç ve önbellek tazeleme |
| G8 `Probe` ve `Effect` gerçek uygulayıcısı | atomik/gizli yazım, `--help`, `path_executables`, `rust_toolchain`, searxng, checks kaydı, maliyet defteri, ajan token'ı, `register_mcp`, diag günlüğü | 54 | 52 | zor: güvenlik (0600, O_NOFOLLOW), eşzamanlılık, zaman aşımı; iki alt göreve bölünebilir (dosya/süreç ve maliyet defteri) |
| G9 spawn yürütme ve küresel yönerge | `spawn_session` akışı, gnome/headless, hayalet temizliği, fallback bekçisi, pencere açma, kanca/eklenti çağrıları, `sync_global_files` | 15 | 13 | zor: rs/tmux ve G1/G8'e bağlı, canlı filoyu etkiler |
| G10 tek atımlık çağrı ve onay | `oneshot`, `ucli_chat_once`, onay kaydı (`ucli_approval` kullanılan kısım), bütçe notu | 19 | 19 | orta: alt süreç, zaman aşımı, sır ortamda |
| G11 ayar ve panel okuyucu artıkları | hizmet `label`/`models`, `ucli_cost_config` tavan/kredi, `ucli_metrics.get_config`, `instructions_check` | 8 | 12 | kolay: saf |

## Sır / argv notları (Python'a dokunulmadı)
- `spawn.py`: `env_overrides` + kanca ortamı `KEY=VAL` olarak komut satırına gömülür (tmux argv). Kanca bir API anahtarı döndürürse argv'ye girer;
  yalnız dry-run satırı maskeliyor. Bugünkü sağlayıcı override'ları sır içermiyor. Sorulacak/izlenecek.
- ucli anahtarı argv'de değil (`$(cat dosya)`); ancak `UCLI_API_KEY="$(cat {_API_KEY_FILE})"` yolunda tırnaklama yok (boşluklu HOME'da kırılır): Python hatası?
- copilot BYOK: dosya source edilir, argv temiz.

## EŞLEME TABLOSU

26 Kas 2026'da `564c4cf` koduna bakarak dolduruldu. 630 satır: TAŞINDI 256, TAŞINDI-TESTSİZ 0, KAPSAM DIŞI 54, EKSİK 320.
- Durumlar: `TAŞINDI` (Rust adı + onu sınayan parite vaka ailesi; vaka kimliğinde geçen parça yazıldı), `TAŞINDI-TESTSİZ`, `EKSİK(Gn)`, `KAPSAM DIŞI` (sahibi olan iz).
- `KAPSAM DIŞI` karşılıkları `origin/rs/{proc,tmux,state,stew}` dallarında görüldü; o dallar henüz birleşmedi (rs/tmux, rs/state, rs/stew kendi belgelerinde "birleştirmeye hazır değil" diyor). Sprint planındaki T1..T10 sahipleri için kod henüz yok.
- `rs/proc` kendi tablosunda sağlayıcıların çoğunu "rs/prov" diye bu ize bırakıyor; burada yalnız süreç tarama işlevleri ona bırakıldı.

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `DEFAULT_CLI` (py/claudeops/providers/__init__.py:14) | `provider.rs::Cli::parse` (bilinmeyen = claude) | `parity.rs::parity_spawn` `bogus-*` | TAŞINDI |
| `PROVIDERS` (py/claudeops/providers/__init__.py:16) | `provider.rs::Cli`, `Cli::ALL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `get_provider` (py/claudeops/providers/__init__.py:26) | `provider.rs::Cli::parse` | `parity.rs::parity_build` `bogus`; ayrıca `parity_spawn` `bogus-*` | TAŞINDI |
| `CONVERSATIONS_CACHE` (py/claudeops/providers/agy_provider.py:84) | yok | - | EKSİK(G1) |
| `CONVERSATIONS_DIR` (py/claudeops/providers/agy_provider.py:85) | yok | - | EKSİK(G2) |
| `AGY_SIDS_JSON` (py/claudeops/providers/agy_provider.py:94) | `rs/proc` `Config::agy_sids` | rs/proc: `fake_proc::broken_agy_files` (okuma; yazım G1) | KAPSAM DIŞI |
| `_STEP_TYPE_USER` (py/claudeops/providers/agy_provider.py:98) | yok | - | EKSİK(G2) |
| `_STEP_TYPE_ASSISTANT` (py/claudeops/providers/agy_provider.py:99) | yok | - | EKSİK(G2) |
| `_STEP_TYPE_CHECKPOINT` (py/claudeops/providers/agy_provider.py:101) | yok | - | EKSİK(G2) |
| `_read_varint` (py/claudeops/providers/agy_provider.py:104) | yok | - | EKSİK(G2) |
| `_iter_fields` (py/claudeops/providers/agy_provider.py:116) | yok | - | EKSİK(G2) |
| `_get_bytes_field` (py/claudeops/providers/agy_provider.py:144) | yok | - | EKSİK(G2) |
| `_get_text_field` (py/claudeops/providers/agy_provider.py:160) | yok | - | EKSİK(G2) |
| `_step_user_text` (py/claudeops/providers/agy_provider.py:165) | yok | - | EKSİK(G2) |
| `_step_assistant_text` (py/claudeops/providers/agy_provider.py:172) | yok | - | EKSİK(G2) |
| `_conversation_ids` (py/claudeops/providers/agy_provider.py:179) | yok | - | EKSİK(G1) |
| `PERMISSION_MODES` (py/claudeops/providers/agy_provider.py:187) | `agy.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/agy_provider.py:188) | `agy.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/agy_provider.py:195) | yok | - | EKSİK(G6) |
| `_PERMISSION_FLAGS` (py/claudeops/providers/agy_provider.py:197) | `agy.rs::permission_flags` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/providers/agy_provider.py:203) | yok: `ModelCatalog::agy_models` girdisi; TTL/arka plan tazeleme yok | - | EKSİK(G7) |
| `_load_agy_sids` (py/claudeops/providers/agy_provider.py:206) | `rs/proc` `providers.rs::AgyState::load` | rs/proc: `providers.rs::agy_sid_rules`, `broken_agy_files`; DB yerine dosya aynası okur | KAPSAM DIŞI |
| `_remember_agy_sid` (py/claudeops/providers/agy_provider.py:215) | yok: rs/proc yalnız `AgyState::learned` döndürür, yazmaz (rs-proc.md sapma 3) | - | EKSİK(G1) |
| `_sid_claimed_by_other` (py/claudeops/providers/agy_provider.py:230) | yok | - | EKSİK(G1) |
| `AgyProvider` (py/claudeops/providers/agy_provider.py:237) | `agy.rs` + `Cli::Agy` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `AgyProvider.name` (py/claudeops/providers/agy_provider.py:238) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.__init__` (py/claudeops/providers/agy_provider.py:240) | yok: `ModelCatalog::agy_models` girdisi; TTL/arka plan tazeleme yok | - | EKSİK(G7) |
| `AgyProvider.resolve_resume_id` (py/claudeops/providers/agy_provider.py:244) | yok | - | EKSİK(G1) |
| `AgyProvider.build_inner_command` (py/claudeops/providers/agy_provider.py:271) | `agy.rs::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra`; ve `parity_spawn` `agy-effort-ayar agy-effort-kardes` | TAŞINDI |
| `AgyProvider.env_overrides` (py/claudeops/providers/agy_provider.py:320) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.mcp_setup_command` (py/claudeops/providers/agy_provider.py:323) | `agy.rs::mcp_setup_command` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `AgyProvider.matches_proc` (py/claudeops/providers/agy_provider.py:333) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `AgyProvider.extract_name` (py/claudeops/providers/agy_provider.py:336) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `AgyProvider.extract_info` (py/claudeops/providers/agy_provider.py:343) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `AgyProvider._fetch_models` (py/claudeops/providers/agy_provider.py:380) | yok: yalnız çıktı ayrıştırma `agy.rs::parse_models` (parite `parity_misc` `agy*`); `agy models` çalıştırma yok | - | EKSİK(G7) |
| `AgyProvider.model_choices` (py/claudeops/providers/agy_provider.py:394) | `provider.rs::Providers::model_choices` (`ModelCatalog::agy_models`) | `parity.rs::parity_model_effort` `agy-models`; canlı liste çağırandan (G7) | TAŞINDI |
| `AgyProvider.permission_modes` (py/claudeops/providers/agy_provider.py:411) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.effort_levels` (py/claudeops/providers/agy_provider.py:414) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `AgyProvider.model_effort_levels` (py/claudeops/providers/agy_provider.py:417) | `agy.rs::model_effort_levels` | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyProvider.busy_status_pattern` (py/claudeops/providers/agy_provider.py:430) | yok | - | EKSİK(G6) |
| `AgyProvider.usage_command` (py/claudeops/providers/agy_provider.py:433) | yok | - | EKSİK(G5) |
| `AgyProvider.usage_fresh_argv` (py/claudeops/providers/agy_provider.py:444) | yok | - | EKSİK(G5) |
| `AgyProvider.usage_auth_missing` (py/claudeops/providers/agy_provider.py:449) | yok | - | EKSİK(G5) |
| `AgyProvider.parse_fresh_usage` (py/claudeops/providers/agy_provider.py:454) | yok | - | EKSİK(G5) |
| `AgyProvider.usage_needs_dismiss` (py/claudeops/providers/agy_provider.py:457) | yok | - | EKSİK(G5) |
| `AgyProvider.parse_usage_text` (py/claudeops/providers/agy_provider.py:467) | yok | - | EKSİK(G5) |
| `AgyProvider._transcript_steps` (py/claudeops/providers/agy_provider.py:498) | yok | - | EKSİK(G2) |
| `AgyProvider._steps_desc` (py/claudeops/providers/agy_provider.py:528) | yok | - | EKSİK(G2) |
| `AgyProvider.last_exchange` (py/claudeops/providers/agy_provider.py:554) | yok | - | EKSİK(G2) |
| `AgyProvider.full_history` (py/claudeops/providers/agy_provider.py:573) | yok | - | EKSİK(G2) |
| `AgyProvider.sid_for_stopped_session` (py/claudeops/providers/agy_provider.py:591) | yok | - | EKSİK(G1) |
| `AgyProvider.snapshot_for_live_sid` (py/claudeops/providers/agy_provider.py:601) | yok | - | EKSİK(G1) |
| `AgyProvider.discover_live_sid` (py/claudeops/providers/agy_provider.py:611) | yok | - | EKSİK(G1) |
| `cmd_arg` (py/claudeops/providers/base.py:20) | `rs/proc` `providers.rs::arg` | rs/proc: `providers.rs::claude_info` | KAPSAM DIŞI |
| `OneshotError` (py/claudeops/providers/base.py:28) | yok | - | EKSİK(G10) |
| `McpServerSpec` (py/claudeops/providers/base.py:33) | `provider.rs::McpSpec` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.name` (py/claudeops/providers/base.py:44) | `provider.rs::McpSpec::name` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.command` (py/claudeops/providers/base.py:45) | `provider.rs::McpSpec::command` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.args` (py/claudeops/providers/base.py:46) | `provider.rs::McpSpec::args` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `McpServerSpec.allowed_tools` (py/claudeops/providers/base.py:49) | `provider.rs::McpSpec::allowed_tools` | `parity.rs::parity_build` `mcp`; ve `parity_ucli` `ucli-mcp-*` | TAŞINDI |
| `CliProvider` (py/claudeops/providers/base.py:52) | `provider.rs::{Cli, Providers}` (spawn tarafı) | `parity.rs::parity_model_effort` `bos-*` `ayar-*`; yalnız satırlarında TAŞINDI yazan yöntemler | TAŞINDI |
| `CliProvider.name` (py/claudeops/providers/base.py:53) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.accepts_cli_opts` (py/claudeops/providers/base.py:57) | `provider.rs::Cli::accepts_cli_opts` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.mcp_needs_cwd` (py/claudeops/providers/base.py:61) | `provider.rs::Cli::mcp_needs_cwd` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.validate_cli_opts` (py/claudeops/providers/base.py:63) | `provider.rs::Providers::validate_cli_opts` | `parity.rs::parity_ucli` `opts-*`; ucli dışı ret: `parity_spawn` `claude-opts`; ret metni için ayrı vaka yok | TAŞINDI |
| `CliProvider.resolve_resume_id` (py/claudeops/providers/base.py:70) | yok: `resume_id` çağırandan girdi sayılıyor | - | EKSİK(G1) |
| `CliProvider.build_inner_command` (py/claudeops/providers/base.py:92) | `provider.rs::Providers::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra` | TAŞINDI |
| `CliProvider.has_conversation` (py/claudeops/providers/base.py:113) | yok | - | EKSİK(G4) |
| `CliProvider.wants_handover_wrapup` (py/claudeops/providers/base.py:121) | yok | - | EKSİK(G4) |
| `CliProvider.wants_stuck_recovery` (py/claudeops/providers/base.py:125) | yok | - | EKSİK(G4) |
| `CliProvider.last_exchange` (py/claudeops/providers/base.py:129) | yok | - | EKSİK(G2) |
| `CliProvider.full_history` (py/claudeops/providers/base.py:138) | yok | - | EKSİK(G2) |
| `CliProvider.sid_for_stopped_session` (py/claudeops/providers/base.py:147) | yok: `resume_id` çağırandan girdi sayılıyor | - | EKSİK(G1) |
| `CliProvider.last_message_role` (py/claudeops/providers/base.py:162) | yok | - | EKSİK(G2) |
| `CliProvider.handover_model_downgrade` (py/claudeops/providers/base.py:175) | yok | - | EKSİK(G4) |
| `CliProvider.apply_live_model_switch` (py/claudeops/providers/base.py:185) | yok | - | EKSİK(G4) |
| `CliProvider.handover_effort_downgrade` (py/claudeops/providers/base.py:193) | yok | - | EKSİK(G4) |
| `CliProvider.apply_live_effort_switch` (py/claudeops/providers/base.py:200) | yok | - | EKSİK(G4) |
| `CliProvider.prompt_cache_ttl_seconds` (py/claudeops/providers/base.py:206) | yok | - | EKSİK(G3) |
| `CliProvider.last_request_epoch` (py/claudeops/providers/base.py:218) | yok | - | EKSİK(G3) |
| `CliProvider.effort_switch_keeps_cache` (py/claudeops/providers/base.py:226) | yok | - | EKSİK(G3) |
| `CliProvider.dismiss_stray_dialog` (py/claudeops/providers/base.py:233) | yok | - | EKSİK(G4) |
| `CliProvider.input_settle_delay` (py/claudeops/providers/base.py:252) | yok | - | EKSİK(G4) |
| `CliProvider.prepare_input` (py/claudeops/providers/base.py:264) | yok | - | EKSİK(G4) |
| `CliProvider.compact_command` (py/claudeops/providers/base.py:269) | yok | - | EKSİK(G4) |
| `CliProvider.usage_fresh_argv` (py/claudeops/providers/base.py:284) | yok | - | EKSİK(G5) |
| `CliProvider.usage_fresh_tui_argv` (py/claudeops/providers/base.py:290) | yok | - | EKSİK(G5) |
| `CliProvider.usage_auth_missing` (py/claudeops/providers/base.py:295) | yok | - | EKSİK(G5) |
| `CliProvider.parse_fresh_usage` (py/claudeops/providers/base.py:299) | yok | - | EKSİK(G5) |
| `CliProvider.usage_command` (py/claudeops/providers/base.py:303) | yok | - | EKSİK(G5) |
| `CliProvider.parse_usage_text` (py/claudeops/providers/base.py:319) | yok | - | EKSİK(G5) |
| `CliProvider.context_command` (py/claudeops/providers/base.py:330) | yok | - | EKSİK(G5) |
| `CliProvider.parse_context_text` (py/claudeops/providers/base.py:344) | yok | - | EKSİK(G5) |
| `CliProvider.context_needs_dismiss` (py/claudeops/providers/base.py:356) | yok | - | EKSİK(G5) |
| `CliProvider.usage_needs_dismiss` (py/claudeops/providers/base.py:367) | yok | - | EKSİK(G5) |
| `CliProvider.extra_file_roots` (py/claudeops/providers/base.py:379) | yok | - | EKSİK(G2) |
| `CliProvider.env_overrides` (py/claudeops/providers/base.py:394) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.mcp_launch_args` (py/claudeops/providers/base.py:410) | `provider.rs::Providers::mcp_launch_args` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `CliProvider.mcp_setup_command` (py/claudeops/providers/base.py:421) | `provider.rs::Providers::mcp_setup_command` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `CliProvider.oneshot_argv` (py/claudeops/providers/base.py:433) | `provider.rs::Providers::oneshot_argv` | `parity.rs::parity_build` `oneshot` | TAŞINDI |
| `CliProvider.oneshot` (py/claudeops/providers/base.py:440) | yok | - | EKSİK(G10) |
| `CliProvider.matches_proc` (py/claudeops/providers/base.py:464) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` (taban sözleşmesi) | KAPSAM DIŞI |
| `CliProvider.extract_name` (py/claudeops/providers/base.py:468) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) (taban sözleşmesi) | KAPSAM DIŞI |
| `CliProvider.extract_info` (py/claudeops/providers/base.py:473) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` (taban sözleşmesi) | KAPSAM DIŞI |
| `CliProvider.model_choices` (py/claudeops/providers/base.py:485) | `provider.rs::Providers::model_choices` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.refresh_stored_model` (py/claudeops/providers/base.py:488) | `provider.rs::Providers::refresh_stored_model` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.permission_modes` (py/claudeops/providers/base.py:497) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.effort_levels` (py/claudeops/providers/base.py:501) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.model_effort_levels` (py/claudeops/providers/base.py:504) | `provider.rs::Providers::model_effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.effort_levels_for` (py/claudeops/providers/base.py:514) | `provider.rs::Providers::effort_levels_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.default_permission_mode` (py/claudeops/providers/base.py:520) | `provider.rs::Cli::default_permission_mode` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.preferred_default_model` (py/claudeops/providers/base.py:525) | `provider.rs::Providers::preferred_default_model` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.default_effort` (py/claudeops/providers/base.py:530) | `provider.rs::Cli::default_effort` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.resolve_effort` (py/claudeops/providers/base.py:536) | `provider.rs::Providers::resolve_effort` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CliProvider.mode_status_patterns` (py/claudeops/providers/base.py:548) | yok | - | EKSİK(G4) |
| `CliProvider.busy_status_pattern` (py/claudeops/providers/base.py:555) | yok | - | EKSİK(G6) |
| `CliProvider.background_work` (py/claudeops/providers/base.py:565) | yok | - | EKSİK(G6) |
| `CliProvider.live_busy` (py/claudeops/providers/base.py:571) | yok | - | EKSİK(G6) |
| `CliProvider.live_tools` (py/claudeops/providers/base.py:584) | yok | - | EKSİK(G6) |
| `CliProvider.live_context` (py/claudeops/providers/base.py:589) | yok | - | EKSİK(G6) |
| `CliProvider.live_usage` (py/claudeops/providers/base.py:596) | yok | - | EKSİK(G6) |
| `CliProvider.live_failed_turns` (py/claudeops/providers/base.py:606) | yok | - | EKSİK(G6) |
| `CliProvider.live_phase` (py/claudeops/providers/base.py:611) | yok | - | EKSİK(G6) |
| `CliProvider.cyclable_modes` (py/claudeops/providers/base.py:620) | yok | - | EKSİK(G4) |
| `CliProvider.snapshot_for_live_sid` (py/claudeops/providers/base.py:629) | yok: `resume_id` çağırandan girdi sayılıyor | - | EKSİK(G1) |
| `CliProvider.discover_live_sid` (py/claudeops/providers/base.py:650) | yok: `resume_id` çağırandan girdi sayılıyor | - | EKSİK(G1) |
| `MODEL_CHOICES` (py/claudeops/providers/claude_provider.py:18) | `claude.rs::MODEL_CHOICES` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `PERMISSION_MODES` (py/claudeops/providers/claude_provider.py:24) | `claude.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/claude_provider.py:25) | `claude.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `_SONNET_PIN_RE` (py/claudeops/providers/claude_provider.py:29) | `claude.rs::SONNET_PIN` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `_sonnet_version` (py/claudeops/providers/claude_provider.py:32) | `claude.rs::sonnet_version` | `parity.rs::parity_model_effort` `bos-*` `claude-state` | TAŞINDI |
| `_USAGE_HEADER_RE` (py/claudeops/providers/claude_provider.py:39) | yok | - | EKSİK(G5) |
| `_USAGE_PERCENT_RE` (py/claudeops/providers/claude_provider.py:40) | yok | - | EKSİK(G5) |
| `_USAGE_RESETS_RE` (py/claudeops/providers/claude_provider.py:41) | yok | - | EKSİK(G5) |
| `_USAGE_FRESH_RE` (py/claudeops/providers/claude_provider.py:43) | yok | - | EKSİK(G5) |
| `_CONTEXT_TOTAL_RE` (py/claudeops/providers/claude_provider.py:48) | yok | - | EKSİK(G5) |
| `_CONTEXT_CATEGORY_RE` (py/claudeops/providers/claude_provider.py:49) | yok | - | EKSİK(G5) |
| `MODE_STATUS_PATTERNS` (py/claudeops/providers/claude_provider.py:61) | yok | - | EKSİK(G4) |
| `CYCLABLE_MODES` (py/claudeops/providers/claude_provider.py:73) | yok | - | EKSİK(G4) |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/claude_provider.py:80) | yok | - | EKSİK(G6) |
| `_encode_cwd` (py/claudeops/providers/claude_provider.py:83) | `rs/proc` `transcript.rs::encode_cwd` | rs/proc: `transcript.rs::encodes_non_ascii_per_char`, altın ad+cwd kodlama | KAPSAM DIŞI |
| `_safe_mtime` (py/claudeops/providers/claude_provider.py:102) | yok | - | EKSİK(G1) |
| `jsonl_path_for` (py/claudeops/providers/claude_provider.py:110) | yok: rs/proc `transcript.rs::jsonl_path_for` YALNIZ tam sid eşleşmesi; Python'daki "cwd'deki en yeni dosya" düşüşü bilerek yok | - | EKSİK(G1) |
| `find_latest_jsonl` (py/claudeops/providers/claude_provider.py:125) | yok | - | EKSİK(G1) |
| `_LAST_MODEL_CHUNK_BYTES` (py/claudeops/providers/claude_provider.py:143) | yok | - | EKSİK(G3) |
| `_LAST_MODEL_MAX_BYTES` (py/claudeops/providers/claude_provider.py:144) | yok | - | EKSİK(G3) |
| `_row_epoch` (py/claudeops/providers/claude_provider.py:147) | yok | - | EKSİK(G3) |
| `_last_assistant_value` (py/claudeops/providers/claude_provider.py:158) | yok | - | EKSİK(G3) |
| `last_assistant_model` (py/claudeops/providers/claude_provider.py:208) | yok | - | EKSİK(G3) |
| `last_assistant_effort` (py/claudeops/providers/claude_provider.py:214) | yok | - | EKSİK(G3) |
| `PROMPT_CACHE_TTL_SECONDS` (py/claudeops/providers/claude_provider.py:228) | yok | - | EKSİK(G3) |
| `_real_request_epoch` (py/claudeops/providers/claude_provider.py:231) | yok | - | EKSİK(G3) |
| `last_real_request_epoch` (py/claudeops/providers/claude_provider.py:254) | yok | - | EKSİK(G3) |
| `session_file_sid` (py/claudeops/providers/claude_provider.py:260) | yok | - | EKSİK(G1) |
| `_EFFORT_BUSTS_CACHE_RE` (py/claudeops/providers/claude_provider.py:293) | yok | - | EKSİK(G3) |
| `live_or_spawn_model` (py/claudeops/providers/claude_provider.py:296) | yok | - | EKSİK(G3) |
| `live_or_spawn_effort` (py/claudeops/providers/claude_provider.py:315) | yok | - | EKSİK(G3) |
| `_META_HEAD_LINES` (py/claudeops/providers/claude_provider.py:331) | yok | - | EKSİK(G1) |
| `_RESUME_SCAN_LIMIT` (py/claudeops/providers/claude_provider.py:334) | yok | - | EKSİK(G1) |
| `_jsonl_meta` (py/claudeops/providers/claude_provider.py:337) | yok | - | EKSİK(G1) |
| `_same_path` (py/claudeops/providers/claude_provider.py:364) | yok | - | EKSİK(G1) |
| `_META_CACHE` (py/claudeops/providers/claude_provider.py:372) | yok | - | EKSİK(G1) |
| `_META_CACHE_MAX` (py/claudeops/providers/claude_provider.py:373) | yok | - | EKSİK(G1) |
| `_jsonl_meta_cached` (py/claudeops/providers/claude_provider.py:376) | yok | - | EKSİK(G1) |
| `_STUB_MAX_BYTES` (py/claudeops/providers/claude_provider.py:391) | yok | - | EKSİK(G1) |
| `_has_chat_rows` (py/claudeops/providers/claude_provider.py:394) | yok | - | EKSİK(G1) |
| `MCP_CONFIG_PATH` (py/claudeops/providers/claude_provider.py:414) | `probe.rs::Paths::mcp_config` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `_mcp_config_path` (py/claudeops/providers/claude_provider.py:417) | `claude.rs::mcp_config_path` | `parity.rs::parity_spawn` `-mcp` `-eklenti-mcp`; beyin/eklenti dosya adı dalları | TAŞINDI |
| `_write_mcp_config_file` (py/claudeops/providers/claude_provider.py:431) | `claude.rs::{mcp_config_json, mcp_launch_args}` + `Effect::WriteAtomic` | `parity.rs::parity_build` `mcp-orchestration-dosya` `mcp-orchestration-engel`; dosya yazımı yalnız test uygulayıcısında (G8) | TAŞINDI |
| `_extract_text` (py/claudeops/providers/claude_provider.py:440) | yok | - | EKSİK(G2) |
| `_is_real_user_text` (py/claudeops/providers/claude_provider.py:452) | yok | - | EKSİK(G2) |
| `_HELP_CACHE` (py/claudeops/providers/claude_provider.py:466) | yok: yalnız `Probe::claude_help` arayüzü; alt süreç, zaman aşımı ve önbellek yok | - | EKSİK(G8) |
| `_HELP_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:467) | yok: yalnız `Probe::claude_help` arayüzü; alt süreç, zaman aşımı ve önbellek yok | - | EKSİK(G8) |
| `claude_help_text` (py/claudeops/providers/claude_provider.py:470) | yok: yalnız `Probe::claude_help` arayüzü; alt süreç, zaman aşımı ve önbellek yok | - | EKSİK(G8) |
| `claude_supports_flag` (py/claudeops/providers/claude_provider.py:492) | `claude.rs::supports_flag` (`ucli.rs::find_flag`) | `parity.rs::parity_build` `oneshot` | TAŞINDI |
| `ClaudeProvider` (py/claudeops/providers/claude_provider.py:498) | `claude.rs` + `provider.rs::Cli::Claude` | `parity.rs::parity_build` `claude-extra` `claude-routing-` | TAŞINDI |
| `ClaudeProvider.name` (py/claudeops/providers/claude_provider.py:499) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.resolve_resume_id` (py/claudeops/providers/claude_provider.py:501) | yok | - | EKSİK(G1) |
| `ClaudeProvider.build_inner_command` (py/claudeops/providers/claude_provider.py:545) | `claude.rs::build_inner_command` | `parity.rs::parity_build` `claude-extra` `claude-routing-` `claude-bilinen` | TAŞINDI |
| `ClaudeProvider.oneshot_argv` (py/claudeops/providers/claude_provider.py:586) | `claude.rs::oneshot_argv` | `parity.rs::parity_build` `oneshot` | TAŞINDI |
| `ClaudeProvider.mcp_launch_args` (py/claudeops/providers/claude_provider.py:602) | `claude.rs::mcp_launch_args` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `ClaudeProvider.compact_command` (py/claudeops/providers/claude_provider.py:610) | yok | - | EKSİK(G4) |
| `ClaudeProvider.usage_command` (py/claudeops/providers/claude_provider.py:613) | yok | - | EKSİK(G5) |
| `ClaudeProvider.usage_needs_dismiss` (py/claudeops/providers/claude_provider.py:616) | yok | - | EKSİK(G5) |
| `ClaudeProvider.parse_usage_text` (py/claudeops/providers/claude_provider.py:624) | yok | - | EKSİK(G5) |
| `ClaudeProvider.usage_fresh_argv` (py/claudeops/providers/claude_provider.py:666) | yok | - | EKSİK(G5) |
| `ClaudeProvider.parse_fresh_usage` (py/claudeops/providers/claude_provider.py:669) | yok | - | EKSİK(G5) |
| `ClaudeProvider.context_command` (py/claudeops/providers/claude_provider.py:678) | yok | - | EKSİK(G5) |
| `ClaudeProvider.context_needs_dismiss` (py/claudeops/providers/claude_provider.py:681) | yok | - | EKSİK(G5) |
| `ClaudeProvider.parse_context_text` (py/claudeops/providers/claude_provider.py:687) | yok | - | EKSİK(G5) |
| `ClaudeProvider.handover_model_downgrade` (py/claudeops/providers/claude_provider.py:744) | yok | - | EKSİK(G4) |
| `ClaudeProvider._MODEL_SWITCH_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:761) | yok | - | EKSİK(G4) |
| `ClaudeProvider._MODEL_SWITCH_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:762) | yok | - | EKSİK(G4) |
| `ClaudeProvider.apply_live_model_switch` (py/claudeops/providers/claude_provider.py:764) | yok | - | EKSİK(G4) |
| `ClaudeProvider.handover_effort_downgrade` (py/claudeops/providers/claude_provider.py:824) | yok | - | EKSİK(G4) |
| `ClaudeProvider.prompt_cache_ttl_seconds` (py/claudeops/providers/claude_provider.py:837) | yok | - | EKSİK(G3) |
| `ClaudeProvider.last_request_epoch` (py/claudeops/providers/claude_provider.py:840) | yok | - | EKSİK(G3) |
| `ClaudeProvider.effort_switch_keeps_cache` (py/claudeops/providers/claude_provider.py:859) | yok | - | EKSİK(G3) |
| `ClaudeProvider._EFFORT_SWITCH_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:862) | yok | - | EKSİK(G4) |
| `ClaudeProvider._EFFORT_SWITCH_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:863) | yok | - | EKSİK(G4) |
| `ClaudeProvider._EFFORT_SWITCH_DONE_MARKERS` (py/claudeops/providers/claude_provider.py:864) | yok | - | EKSİK(G4) |
| `ClaudeProvider.apply_live_effort_switch` (py/claudeops/providers/claude_provider.py:867) | yok | - | EKSİK(G4) |
| `ClaudeProvider._STRAY_DIALOG_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:926) | yok | - | EKSİK(G4) |
| `ClaudeProvider._STRAY_DIALOG_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:927) | yok | - | EKSİK(G4) |
| `ClaudeProvider.dismiss_stray_dialog` (py/claudeops/providers/claude_provider.py:929) | yok | - | EKSİK(G4) |
| `ClaudeProvider.matches_proc` (py/claudeops/providers/claude_provider.py:970) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `ClaudeProvider.extract_name` (py/claudeops/providers/claude_provider.py:975) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `ClaudeProvider.extract_info` (py/claudeops/providers/claude_provider.py:978) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `ClaudeProvider.preferred_default_model` (py/claudeops/providers/claude_provider.py:986) | `claude.rs::newest_sonnet` | `parity.rs::parity_model_effort` `claude-state` | TAŞINDI |
| `ClaudeProvider.default_effort` (py/claudeops/providers/claude_provider.py:992) | `provider.rs::Cli::default_effort` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.model_choices` (py/claudeops/providers/claude_provider.py:995) | `claude.rs::model_choices` | `parity.rs::parity_model_effort` `claude-state` `claude-state-bozuk`; `claude_models` belgesini okumak çağıranda (G7) | TAŞINDI |
| `ClaudeProvider.refresh_stored_model` (py/claudeops/providers/claude_provider.py:1010) | `claude.rs::refresh_stored_model` | `parity.rs::parity_model_effort` `claude-state` | TAŞINDI |
| `ClaudeProvider.permission_modes` (py/claudeops/providers/claude_provider.py:1029) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.effort_levels` (py/claudeops/providers/claude_provider.py:1032) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ClaudeProvider.mode_status_patterns` (py/claudeops/providers/claude_provider.py:1035) | yok | - | EKSİK(G4) |
| `ClaudeProvider.background_work` (py/claudeops/providers/claude_provider.py:1038) | yok | - | EKSİK(G6) |
| `ClaudeProvider.busy_status_pattern` (py/claudeops/providers/claude_provider.py:1048) | yok | - | EKSİK(G6) |
| `ClaudeProvider.cyclable_modes` (py/claudeops/providers/claude_provider.py:1051) | yok | - | EKSİK(G4) |
| `ClaudeProvider._transcript_lines` (py/claudeops/providers/claude_provider.py:1054) | yok | - | EKSİK(G2) |
| `ClaudeProvider.last_exchange` (py/claudeops/providers/claude_provider.py:1080) | yok | - | EKSİK(G2) |
| `ClaudeProvider.extra_file_roots` (py/claudeops/providers/claude_provider.py:1110) | yok | - | EKSİK(G2) |
| `ClaudeProvider.full_history` (py/claudeops/providers/claude_provider.py:1115) | yok | - | EKSİK(G2) |
| `ClaudeProvider.sid_for_stopped_session` (py/claudeops/providers/claude_provider.py:1144) | yok | - | EKSİK(G1) |
| `CODEX_HOME` (py/claudeops/providers/codex_provider.py:42) | yok: `ModelCatalog::codex_cache` girdisi; yol, okuma ve TTL yok | - | EKSİK(G7) |
| `SESSIONS_DIR` (py/claudeops/providers/codex_provider.py:43) | yok | - | EKSİK(G2) |
| `MODELS_CACHE` (py/claudeops/providers/codex_provider.py:44) | yok: `ModelCatalog::codex_cache` girdisi; yol, okuma ve TTL yok | - | EKSİK(G7) |
| `PERMISSION_MODES` (py/claudeops/providers/codex_provider.py:46) | `codex.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/codex_provider.py:47) | `codex.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/codex_provider.py:58) | yok | - | EKSİK(G6) |
| `FALLBACK_MODELS` (py/claudeops/providers/codex_provider.py:62) | `codex.rs::FALLBACK_MODELS` | `parity.rs::parity_model_effort` `codex-cache-bozuk` `bos-*` | TAŞINDI |
| `_NON_SESSION_SUBCOMMANDS` (py/claudeops/providers/codex_provider.py:77) | `rs/proc` `providers.rs::CODEX_NON_SESSION` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `_PERMISSION_FLAGS` (py/claudeops/providers/codex_provider.py:84) | `codex.rs::permission_flags` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/providers/codex_provider.py:91) | yok: `ModelCatalog::codex_cache` girdisi; yol, okuma ve TTL yok | - | EKSİK(G7) |
| `_ROLLOUT_UUID_RE` (py/claudeops/providers/codex_provider.py:92) | yok | - | EKSİK(G1) |
| `_MAX_ROLLOUT_SCAN` (py/claudeops/providers/codex_provider.py:93) | yok | - | EKSİK(G1) |
| `_config_value` (py/claudeops/providers/codex_provider.py:96) | `rs/proc` `providers.rs::codex_config` | rs/proc: `providers.rs::codex_info` | KAPSAM DIŞI |
| `_safe_mtime` (py/claudeops/providers/codex_provider.py:104) | yok | - | EKSİK(G1) |
| `_session_meta` (py/claudeops/providers/codex_provider.py:111) | yok | - | EKSİK(G1) |
| `_codex_text` (py/claudeops/providers/codex_provider.py:125) | yok | - | EKSİK(G2) |
| `_is_real_codex_user_text` (py/claudeops/providers/codex_provider.py:139) | yok | - | EKSİK(G2) |
| `CodexProvider` (py/claudeops/providers/codex_provider.py:148) | `codex.rs` + `Cli::Codex` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `CodexProvider.name` (py/claudeops/providers/codex_provider.py:149) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.__init__` (py/claudeops/providers/codex_provider.py:151) | yok: `ModelCatalog::codex_cache` girdisi; yol, okuma ve TTL yok | - | EKSİK(G7) |
| `CodexProvider.resolve_resume_id` (py/claudeops/providers/codex_provider.py:155) | yok | - | EKSİK(G1) |
| `CodexProvider.build_inner_command` (py/claudeops/providers/codex_provider.py:178) | `codex.rs::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra` | TAŞINDI |
| `CodexProvider.mcp_launch_args` (py/claudeops/providers/codex_provider.py:196) | `codex.rs::mcp_launch_args` | `parity.rs::parity_build` `mcp` | TAŞINDI |
| `CodexProvider.env_overrides` (py/claudeops/providers/codex_provider.py:207) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.matches_proc` (py/claudeops/providers/codex_provider.py:210) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `CodexProvider.extract_name` (py/claudeops/providers/codex_provider.py:218) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `CodexProvider.extract_info` (py/claudeops/providers/codex_provider.py:225) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `CodexProvider.model_choices` (py/claudeops/providers/codex_provider.py:246) | `codex.rs::model_choices` | `parity.rs::parity_model_effort` `codex-cache`; TTL önbelleği yok (G7) | TAŞINDI |
| `CodexProvider.permission_modes` (py/claudeops/providers/codex_provider.py:265) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.effort_levels` (py/claudeops/providers/codex_provider.py:268) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CodexProvider.model_effort_levels` (py/claudeops/providers/codex_provider.py:271) | `codex.rs::model_effort_levels` | `parity.rs::parity_model_effort` `codex-cache`; ve `parity_spawn` `codex-effort` | TAŞINDI |
| `CodexProvider.busy_status_pattern` (py/claudeops/providers/codex_provider.py:292) | yok | - | EKSİK(G6) |
| `CodexProvider.input_settle_delay` (py/claudeops/providers/codex_provider.py:295) | yok | - | EKSİK(G4) |
| `CodexProvider.background_work` (py/claudeops/providers/codex_provider.py:306) | yok | - | EKSİK(G6) |
| `CodexProvider._rollout_path` (py/claudeops/providers/codex_provider.py:317) | yok | - | EKSİK(G1) |
| `CodexProvider._transcript_lines` (py/claudeops/providers/codex_provider.py:336) | yok | - | EKSİK(G2) |
| `CodexProvider.live_context` (py/claudeops/providers/codex_provider.py:358) | yok | - | EKSİK(G6) |
| `CodexProvider.last_exchange` (py/claudeops/providers/codex_provider.py:385) | yok | - | EKSİK(G2) |
| `CodexProvider.full_history` (py/claudeops/providers/codex_provider.py:410) | yok | - | EKSİK(G2) |
| `SESSION_STORE_DB` (py/claudeops/providers/copilot_provider.py:107) | yok | - | EKSİK(G2) |
| `_BYOK_ENV_FILE` (py/claudeops/providers/copilot_provider.py:119) | `probe.rs::Paths::copilot_env_file` | `parity.rs::parity_build` `copilot-byok-` | TAŞINDI |
| `_BYOK_ENV_MANAGED_MARKER` (py/claudeops/providers/copilot_provider.py:120) | `copilot.rs::sync_byok_env_file` (`.managed`) | `parity.rs::parity_build` `byok-sil-yonetilen` `byok-elle` | TAŞINDI |
| `_sync_byok_env_file` (py/claudeops/providers/copilot_provider.py:123) | `copilot.rs::sync_byok_env_file` + `Effect` | `parity.rs::parity_build` `byok-`; yazım uygulayıcısı yalnız testte (G8) | TAŞINDI |
| `MODEL_CHOICES` (py/claudeops/providers/copilot_provider.py:157) | `copilot.rs::MODEL_CHOICES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `PERMISSION_MODES` (py/claudeops/providers/copilot_provider.py:176) | `copilot.rs::PERMISSION_MODES` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `EFFORT_LEVELS` (py/claudeops/providers/copilot_provider.py:177) | `copilot.rs::EFFORT_LEVELS` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `MODE_STATUS_PATTERNS` (py/claudeops/providers/copilot_provider.py:183) | yok | - | EKSİK(G4) |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/copilot_provider.py:187) | yok | - | EKSİK(G6) |
| `_PERMISSION_FLAGS` (py/claudeops/providers/copilot_provider.py:189) | `copilot.rs::permission_flags` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_RESUME_SCAN_LIMIT` (py/claudeops/providers/copilot_provider.py:196) | yok | - | EKSİK(G1) |
| `_USAGE_PLAN_RE` (py/claudeops/providers/copilot_provider.py:205) | yok | - | EKSİK(G5) |
| `_USAGE_FRACTION_RE` (py/claudeops/providers/copilot_provider.py:206) | yok | - | EKSİK(G5) |
| `_USAGE_RESET_RE` (py/claudeops/providers/copilot_provider.py:207) | yok | - | EKSİK(G5) |
| `trust_folder` (py/claudeops/providers/copilot_provider.py:210) | `copilot.rs::{trust_folder, trust_folder_edit}` + `Effect` | `parity.rs::parity_build` `trust-`; Python hatası? (yeni) dizi sonu ilk `]` ile aranıyor: `]` içeren yol varsa/`cwd` `]` içeriyorsa her açılışta yinelenen giriş; Rust aynen. `config_path` parametresi yok | TAŞINDI |
| `_connect_ro` (py/claudeops/providers/copilot_provider.py:232) | yok | - | EKSİK(G2) |
| `CopilotProvider` (py/claudeops/providers/copilot_provider.py:239) | `copilot.rs` + `Cli::Copilot` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `CopilotProvider.name` (py/claudeops/providers/copilot_provider.py:240) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.resolve_resume_id` (py/claudeops/providers/copilot_provider.py:242) | yok | - | EKSİK(G1) |
| `CopilotProvider.build_inner_command` (py/claudeops/providers/copilot_provider.py:270) | `copilot.rs::build_inner_command` | `parity.rs::parity_build` `-perm` `-extra` `byok-` `trust-` | TAŞINDI |
| `CopilotProvider.env_overrides` (py/claudeops/providers/copilot_provider.py:297) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.matches_proc` (py/claudeops/providers/copilot_provider.py:303) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `CopilotProvider.extract_name` (py/claudeops/providers/copilot_provider.py:322) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `CopilotProvider.extract_info` (py/claudeops/providers/copilot_provider.py:329) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `CopilotProvider.model_choices` (py/claudeops/providers/copilot_provider.py:345) | `provider.rs` `model_choices` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.permission_modes` (py/claudeops/providers/copilot_provider.py:348) | `provider.rs` `permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.effort_levels` (py/claudeops/providers/copilot_provider.py:351) | `provider.rs` `effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `CopilotProvider.mode_status_patterns` (py/claudeops/providers/copilot_provider.py:354) | yok | - | EKSİK(G4) |
| `CopilotProvider.busy_status_pattern` (py/claudeops/providers/copilot_provider.py:357) | yok | - | EKSİK(G6) |
| `CopilotProvider.usage_command` (py/claudeops/providers/copilot_provider.py:360) | yok | - | EKSİK(G5) |
| `CopilotProvider.parse_usage_text` (py/claudeops/providers/copilot_provider.py:369) | yok | - | EKSİK(G5) |
| `CopilotProvider.usage_fresh_tui_argv` (py/claudeops/providers/copilot_provider.py:380) | yok | - | EKSİK(G5) |
| `CopilotProvider._turns` (py/claudeops/providers/copilot_provider.py:384) | yok | - | EKSİK(G2) |
| `CopilotProvider.live_context` (py/claudeops/providers/copilot_provider.py:407) | yok | - | EKSİK(G6) |
| `CopilotProvider.last_exchange` (py/claudeops/providers/copilot_provider.py:425) | yok | - | EKSİK(G2) |
| `CopilotProvider.full_history` (py/claudeops/providers/copilot_provider.py:434) | yok | - | EKSİK(G2) |
| `PROC_TAG` (py/claudeops/providers/shell_provider.py:31) | `shell.rs::PROC_TAG` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `_SENTINEL` (py/claudeops/providers/shell_provider.py:38) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider` (py/claudeops/providers/shell_provider.py:41) | `shell.rs` + `Cli::Shell` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.name` (py/claudeops/providers/shell_provider.py:42) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.has_conversation` (py/claudeops/providers/shell_provider.py:44) | yok | - | EKSİK(G4) |
| `ShellProvider.resolve_resume_id` (py/claudeops/providers/shell_provider.py:47) | yok: sabit None; crate'te resume çözümü hiç yok | - | EKSİK(G1) |
| `ShellProvider.build_inner_command` (py/claudeops/providers/shell_provider.py:51) | `shell.rs::build_inner_command` | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `ShellProvider.env_overrides` (py/claudeops/providers/shell_provider.py:58) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.matches_proc` (py/claudeops/providers/shell_provider.py:61) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `ShellProvider.extract_name` (py/claudeops/providers/shell_provider.py:64) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `ShellProvider.extract_info` (py/claudeops/providers/shell_provider.py:70) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `ShellProvider.model_choices` (py/claudeops/providers/shell_provider.py:73) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.permission_modes` (py/claudeops/providers/shell_provider.py:76) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `ShellProvider.effort_levels` (py/claudeops/providers/shell_provider.py:79) | `shell.rs::SENTINEL` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `_EFFORT_LIMITS` (py/claudeops/providers/ucli_provider.py:153) | `ucli.rs::{EFFORT_LIMITS, EFFORT_LEVELS}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` | TAŞINDI |
| `_EFFORT_LEVELS` (py/claudeops/providers/ucli_provider.py:157) | `ucli.rs::{EFFORT_LIMITS, EFFORT_LEVELS}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` | TAŞINDI |
| `_REQUEST_TIMEOUT_SECS` (py/claudeops/providers/ucli_provider.py:167) | `ucli.rs::{REQUEST_TIMEOUT_SECS, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_MAX_HISTORY_KIB` (py/claudeops/providers/ucli_provider.py:173) | `ucli.rs::{MAX_HISTORY_KIB, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_USAGE_FIELDS` (py/claudeops/providers/ucli_provider.py:178) | yok | - | EKSİK(G6) |
| `_PHASE_INT_FIELDS` (py/claudeops/providers/ucli_provider.py:182) | yok | - | EKSİK(G6) |
| `_READ_ONLY` (py/claudeops/providers/ucli_provider.py:187) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_ALLOW_EDIT` (py/claudeops/providers/ucli_provider.py:188) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_ALLOW_CREATE` (py/claudeops/providers/ucli_provider.py:192) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_PERMISSION_MODES` (py/claudeops/providers/ucli_provider.py:193) | `ucli.rs::{ALLOW_EDIT, PERMISSION_MODES}` (+ özel sabitler) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `_MODEL_CHOICES` (py/claudeops/providers/ucli_provider.py:201) | `ucli.rs::{FALLBACK_MODEL, LiveModels::choices}` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `DEFAULT_ENDPOINT` (py/claudeops/providers/ucli_provider.py:202) | `ucli.rs::DEFAULT_ENDPOINT` | `parity.rs::parity_ucli` `temel-` `ayar-endpoint` | TAŞINDI |
| `_ENDPOINT` (py/claudeops/providers/ucli_provider.py:203) | `ucli.rs::DEFAULT_ENDPOINT` | `parity.rs::parity_ucli` `temel-` `ayar-endpoint` | TAŞINDI |
| `endpoint` (py/claudeops/providers/ucli_provider.py:206) | `ucli.rs::build_inner_command` (`Settings::ucli_endpoint` yoksa varsayılan) | `parity.rs::parity_ucli` `ayar-endpoint` `endpoint-gecersiz`; ayrı public işlev yok | TAŞINDI |
| `_MODELS_TTL` (py/claudeops/providers/ucli_provider.py:221) | yok | - | EKSİK(G7) |
| `_LIVE_MODEL_CACHE` (py/claudeops/providers/ucli_provider.py:222) | yok | - | EKSİK(G7) |
| `_LIVE_MODEL_CACHE_TS` (py/claudeops/providers/ucli_provider.py:223) | yok | - | EKSİK(G7) |
| `_LIVE_CAPS` (py/claudeops/providers/ucli_provider.py:226) | yok: `LiveModels::caps` girdisi var; doldurma/saklama yok | - | EKSİK(G7) |
| `_fetch_live_models` (py/claudeops/providers/ucli_provider.py:229) | yok: yalnız yanıt ayrıştırma `ucli.rs::parse_live_models` (parite `parity_misc` `live*`); HTTP, anahtar, zaman aşımı yok. Python hatası? `/models` nesne değil (TBD#373) | - | EKSİK(G7) |
| `_live_models` (py/claudeops/providers/ucli_provider.py:266) | yok | - | EKSİK(G7) |
| `reasoning_effort_for` (py/claudeops/providers/ucli_provider.py:283) | `ucli.rs::reasoning_effort_for` | `parity.rs::parity_misc` `ucli-misc`; ve `parity_ucli` `temel-` | TAŞINDI |
| `_API_KEY_FILE` (py/claudeops/providers/ucli_provider.py:307) | `probe.rs::Paths::ucli_key_file` | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `_API_KEY_MANAGED_MARKER` (py/claudeops/providers/ucli_provider.py:313) | `ucli.rs::Ctx::sync_api_key_file` + `Effect` | `parity.rs::parity_ucli` `anahtar-`; yazım uygulayıcısı yalnız testte (G8) | TAŞINDI |
| `_sync_api_key_file` (py/claudeops/providers/ucli_provider.py:316) | `ucli.rs::Ctx::sync_api_key_file` + `Effect` | `parity.rs::parity_ucli` `anahtar-`; yazım uygulayıcısı yalnız testte (G8) | TAŞINDI |
| `_web_args` (py/claudeops/providers/ucli_provider.py:345) | `ucli.rs::Ctx::web_args` | `parity.rs::parity_ucli` `web-` `eksik`; `ucli_web_searxng_error` diag yok (G8) | TAŞINDI |
| `_script_args` (py/claudeops/providers/ucli_provider.py:383) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_stream_args` (py/claudeops/providers/ucli_provider.py:397) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_reasoning_display_args` (py/claudeops/providers/ucli_provider.py:409) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_metrics_file_args` (py/claudeops/providers/ucli_provider.py:420) | `ucli.rs::Ctx::tuning_args` + `Effect::MkdirPrivate` | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-`; Python mkdir hatasında bayrağı düşürür; Rust'ta çağıran sözleşmesi (G8) | TAŞINDI |
| `_interactive_args` (py/claudeops/providers/ucli_provider.py:442) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `eksik` `temel-` | TAŞINDI |
| `_state_dir_args` (py/claudeops/providers/ucli_provider.py:451) | `ucli.rs::Ctx::state_dir_args` | `parity.rs::parity_ucli` `statedir-` | TAŞINDI |
| `_timeout_args` (py/claudeops/providers/ucli_provider.py:468) | `ucli.rs::{REQUEST_TIMEOUT_SECS, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_history_args` (py/claudeops/providers/ucli_provider.py:478) | `ucli.rs::{MAX_HISTORY_KIB, Ctx::tuning_args}` | `parity.rs::parity_ucli` `temel-` `ayar-limit` `eksik` | TAŞINDI |
| `_effort_args` (py/claudeops/providers/ucli_provider.py:495) | `ucli.rs::Ctx::tuning_args` | `parity.rs::parity_ucli` `ayar-reasoning-` `ayar-script-full` `ayar-stream-off` `eksik` | TAŞINDI |
| `_set_flag_value` (py/claudeops/providers/ucli_provider.py:513) | `ucli.rs::set_flag_value` | `parity.rs::parity_ucli` `hizmet-claude` `opts-` | TAŞINDI |
| `_service_key_file` (py/claudeops/providers/ucli_provider.py:525) | `probe.rs::Paths::ucli_key_file` | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `_INSTRUCTIONS_MAX_BYTES` (py/claudeops/providers/ucli_provider.py:529) | `ucli.rs::Ctx::claude_service_flags` | `parity.rs::parity_ucli` `hizmet-claude-buyuk-talimat` `hizmet-claude-sinir-talimat` | TAŞINDI |
| `_instructions_too_big` (py/claudeops/providers/ucli_provider.py:532) | `ucli.rs::Ctx::claude_service_flags` | `parity.rs::parity_ucli` `hizmet-claude-buyuk-talimat` `hizmet-claude-sinir-talimat` | TAŞINDI |
| `instructions_check` (py/claudeops/providers/ucli_provider.py:543) | yok: panel okuyucusu (`/api/ucli/instructions-check`) | - | EKSİK(G11) |
| `_claude_service_flags` (py/claudeops/providers/ucli_provider.py:564) | `ucli.rs::Ctx::claude_service_flags` | `parity.rs::parity_ucli` `hizmet-claude`; günlük tavan `Probe::claude_cost_gate` sahte (G8); `ucli_usage_log_dir_failed` diag yok (G8) | TAŞINDI |
| `_PRICED_MODELS` (py/claudeops/providers/ucli_provider.py:597) | `ucli.rs::{PRICED_MODELS, Ctx::apply_cli_opts}` | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` `opts-cost-modelsiz` | TAŞINDI |
| `_default_session_cap` (py/claudeops/providers/ucli_provider.py:600) | `ucli.rs::Ctx::apply_cli_opts` + `Settings::default_max_session_usd` | `parity.rs::parity_ucli` `hizmet-grok-tavan-ayar` `ham-service-evren` | TAŞINDI |
| `_max_cost_args` (py/claudeops/providers/ucli_provider.py:609) | `ucli.rs::{PRICED_MODELS, Ctx::apply_cli_opts}` | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` `opts-cost-modelsiz` | TAŞINDI |
| `_MCP_NAME_BAD` (py/claudeops/providers/ucli_provider.py:624) | `ucli.rs::mcp_server_name` | `parity.rs::parity_misc` `ucli-misc`; ve `parity_ucli` `ucli-mcp-ad` | TAŞINDI |
| `_MCP_TOOL_RE` (py/claudeops/providers/ucli_provider.py:625) | `ucli.rs::valid_tool_name` | `parity.rs::parity_ucli` `ucli-mcp-aracsiz`; Python hatası? `$` sondaki satır sonunu kabul eder (TBD#373); Rust aynen. Satır sonlu araç adı vakası yok | TAŞINDI |
| `_MCP_ADD_TIMEOUT` (py/claudeops/providers/ucli_provider.py:626) | yok: 20 sn zaman aşımı yalnız `Probe::register_mcp` belge notunda | - | EKSİK(G8) |
| `mcp_server_name` (py/claudeops/providers/ucli_provider.py:629) | `ucli.rs::mcp_server_name` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `mcp_add_argv` (py/claudeops/providers/ucli_provider.py:633) | `ucli.rs::mcp_add_argv` | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `register_mcp` (py/claudeops/providers/ucli_provider.py:642) | yok: symlink reddi ve diag olayları `ucli.rs::mcp_launch_args` içinde TAŞINDI (parite `ucli-mcp-*`); silme ve `mcp add` çalıştırma `Probe::register_mcp` gerçek uygulaması yok | - | EKSİK(G8) |
| `_apply_cli_opts` (py/claudeops/providers/ucli_provider.py:672) | `ucli.rs::Ctx::apply_cli_opts` | `parity.rs::parity_ucli` `opts-` `ham-` | TAŞINDI |
| `_agent_setup` (py/claudeops/providers/ucli_provider.py:845) | `ucli.rs::Ctx::agent_setup` | `parity.rs::parity_ucli` `ajan-`; token üretimi `Probe` sahte (G8) | TAŞINDI |
| `UcliProvider` (py/claudeops/providers/ucli_provider.py:867) | `ucli.rs::build_inner_command` | `parity.rs::parity_ucli` `temel-` `anahtar-` `opts-`; Python hatası? `$(cat {_API_KEY_FILE})` tırnaksız (TBD#373); Rust aynen | TAŞINDI |
| `UcliProvider.name` (py/claudeops/providers/ucli_provider.py:868) | `provider.rs::Cli::name` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.prepare_input` (py/claudeops/providers/ucli_provider.py:870) | yok | - | EKSİK(G4) |
| `UcliProvider.has_conversation` (py/claudeops/providers/ucli_provider.py:878) | yok | - | EKSİK(G4) |
| `UcliProvider.wants_handover_wrapup` (py/claudeops/providers/ucli_provider.py:881) | yok | - | EKSİK(G4) |
| `UcliProvider.resolve_resume_id` (py/claudeops/providers/ucli_provider.py:884) | yok: sabit None; crate'te resume çözümü hiç yok | - | EKSİK(G1) |
| `UcliProvider.accepts_cli_opts` (py/claudeops/providers/ucli_provider.py:888) | `provider.rs::Cli::accepts_cli_opts` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.mcp_needs_cwd` (py/claudeops/providers/ucli_provider.py:889) | `provider.rs::Cli::mcp_needs_cwd` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.validate_cli_opts` (py/claudeops/providers/ucli_provider.py:891) | `ucli_opts.rs::validate_opts` | `parity.rs::parity_ucli` `opts-` | TAŞINDI |
| `UcliProvider.mcp_launch_args` (py/claudeops/providers/ucli_provider.py:894) | `ucli.rs::mcp_launch_args` | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `UcliProvider.build_inner_command` (py/claudeops/providers/ucli_provider.py:917) | `ucli.rs::build_inner_command` | `parity.rs::parity_ucli` `temel-` `anahtar-` `opts-`; Python hatası? `$(cat {_API_KEY_FILE})` tırnaksız (TBD#373); Rust aynen | TAŞINDI |
| `UcliProvider.oneshot` (py/claudeops/providers/ucli_provider.py:997) | yok | - | EKSİK(G10) |
| `UcliProvider.env_overrides` (py/claudeops/providers/ucli_provider.py:1017) | `provider.rs::Cli::env_overrides` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.matches_proc` (py/claudeops/providers/ucli_provider.py:1022) | `rs/proc` `cops-procscan/src/providers.rs::Cli::detect` | rs/proc: `providers.rs::detect`, altın `detect_info` | KAPSAM DIŞI |
| `UcliProvider._parse_session` (py/claudeops/providers/ucli_provider.py:1027) | `rs/proc` `providers.rs::arg` (`Cli::extract_name`, `ucli_info`) | rs/proc: `providers.rs::ucli_effort_presets`, altın `detect_info` | KAPSAM DIŞI |
| `UcliProvider.extract_name` (py/claudeops/providers/ucli_provider.py:1033) | `rs/proc` `providers.rs::Cli::extract_name` | rs/proc: `golden.rs::provider_detect_and_info` (süreç taraması rs/proc) | KAPSAM DIŞI |
| `UcliProvider.extract_info` (py/claudeops/providers/ucli_provider.py:1036) | `rs/proc` `providers.rs::Cli::extract_info` | rs/proc: `providers.rs::{claude,codex,copilot}_info`, `ucli_effort_presets`, `agy_sid_rules` | KAPSAM DIŞI |
| `UcliProvider.model_choices` (py/claudeops/providers/ucli_provider.py:1072) | `ucli.rs::LiveModels::choices` | `parity.rs::parity_model_effort` `ucli-live`; canlı liste çağırandan (G7) | TAŞINDI |
| `UcliProvider.default_permission_mode` (py/claudeops/providers/ucli_provider.py:1075) | `provider.rs::Cli::default_permission_mode` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.permission_modes` (py/claudeops/providers/ucli_provider.py:1080) | `provider.rs::Cli::permission_modes` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.effort_levels` (py/claudeops/providers/ucli_provider.py:1083) | `provider.rs::Cli::effort_levels` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `UcliProvider.full_history` (py/claudeops/providers/ucli_provider.py:1086) | yok | - | EKSİK(G2) |
| `UcliProvider.sid_for_stopped_session` (py/claudeops/providers/ucli_provider.py:1091) | yok | - | EKSİK(G1) |
| `UcliProvider.live_busy` (py/claudeops/providers/ucli_provider.py:1097) | yok | - | EKSİK(G6) |
| `UcliProvider.background_work` (py/claudeops/providers/ucli_provider.py:1112) | yok | - | EKSİK(G6) |
| `UcliProvider.live_tools` (py/claudeops/providers/ucli_provider.py:1127) | yok | - | EKSİK(G6) |
| `UcliProvider.live_context` (py/claudeops/providers/ucli_provider.py:1141) | yok | - | EKSİK(G6) |
| `UcliProvider.live_usage` (py/claudeops/providers/ucli_provider.py:1156) | yok | - | EKSİK(G6) |
| `UcliProvider.live_failed_turns` (py/claudeops/providers/ucli_provider.py:1173) | yok | - | EKSİK(G6) |
| `UcliProvider.live_phase` (py/claudeops/providers/ucli_provider.py:1196) | yok | - | EKSİK(G6) |
| `UcliProvider.last_exchange` (py/claudeops/providers/ucli_provider.py:1226) | yok | - | EKSİK(G2) |
| `BUNDLED_PATH` (py/claudeops/routing.py:21) | `probe.rs::Paths::routing_bundled` | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `OVERRIDE_PATH` (py/claudeops/routing.py:22) | `probe.rs::Paths::routing_override` | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `BLOCK_BEGIN` (py/claudeops/routing.py:23) | `routing.rs::BLOCK_BEGIN` | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `BLOCK_END` (py/claudeops/routing.py:24) | `routing.rs::BLOCK_END` | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `CODEX_AGENTS` (py/claudeops/routing.py:25) | yok | - | EKSİK(G9) |
| `AGY_GEMINI` (py/claudeops/routing.py:26) | yok | - | EKSİK(G9) |
| `routing_text` (py/claudeops/routing.py:29) | `routing.rs::routing_text` | `parity.rs::parity_misc` `sync`; ve `parity_build` `claude-routing-` | TAŞINDI |
| `claude_guidance_path` (py/claudeops/routing.py:41) | `routing.rs::claude_guidance_path` | `parity.rs::parity_build` `claude-routing-`; Python hatası? bozuk UTF-8 override (TBD#373) | TAŞINDI |
| `_with_block` (py/claudeops/routing.py:66) | `routing.rs::with_block` | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `_sync_one` (py/claudeops/routing.py:81) | yok: karar `routing.rs::sync_plan` TAŞINDI (parite `sync*`); yedek, silme, atomik yazım, OSError dönüşü yalnız test koşucusunda. Python hatası? bozuk UTF-8 (TBD#373) | - | EKSİK(G9) |
| `sync_global_files` (py/claudeops/routing.py:109) | yok | - | EKSİK(G9) |
| `_DANGEROUS_ENV_NAMES` (py/claudeops/spawn.py:36) | `spawn.rs::DANGEROUS_ENV` | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `FALLBACK_ATTEMPT_WAIT_SECONDS` (py/claudeops/spawn.py:50) | yok | - | EKSİK(G9) |
| `FALLBACK_RETRY_COUNT` (py/claudeops/spawn.py:51) | yok | - | EKSİK(G9) |
| `_filter_env_overrides` (py/claudeops/spawn.py:54) | `spawn.rs::filter_env_overrides` | `parity.rs::parity_spawn` `filter` `-kanca` | TAŞINDI |
| `DRY_RUN_PREVIEW_MAX` (py/claudeops/spawn.py:59) | `spawn.rs::DRY_RUN_PREVIEW_MAX` | `parity.rs::parity_spawn` `preview-sinir` `preview-sinir2` | TAŞINDI |
| `_SECRET_ENV_RE` (py/claudeops/spawn.py:60) | `spawn.rs::{SECRET_WORDS, fold_char}` | `parity.rs::parity_spawn` `preview` | TAŞINDI |
| `_dry_run_preview` (py/claudeops/spawn.py:63) | `spawn.rs::{dry_run_preview, SpawnPlan::dry_run_line}` | `parity.rs::parity_spawn` `preview` `-dry` | TAŞINDI |
| `detect_display` (py/claudeops/spawn.py:71) | `spawn.rs::detect_display` | `parity.rs::parity_spawn` `display-env` `display-bos` `display-yok`; soket/kilit dosyası senaryoları denetimli değil | TAŞINDI |
| `_ids_held_by_others` (py/claudeops/spawn.py:83) | yok: rs/proc `discovery.rs::find_sessions` var; süzgeç yok (parite harness boş küme sahteler) | - | EKSİK(G1) |
| `SESSION_USD_CAP_KEY` (py/claudeops/spawn.py:110) | `spawn.rs::SESSION_USD_CAP_KEY` | `parity.rs::parity_spawn` `kanca-` | TAŞINDI |
| `_apply_hook_session_cap` (py/claudeops/spawn.py:113) | `spawn.rs::apply_hook_session_cap` | `parity.rs::parity_spawn` `kanca-` | TAŞINDI |
| `BRAIN_NAME_PREFIXES` (py/claudeops/spawn.py:138) | `spawn.rs::BRAIN_NAME_PREFIX` | `parity.rs::parity_spawn` `prefix-` | TAŞINDI |
| `spawn_priority_prefix` (py/claudeops/spawn.py:141) | `spawn.rs::priority_prefix` + `Settings::spawn_nice` | `parity.rs::parity_spawn` `prefix-` | TAŞINDI |
| `spawn_session` (py/claudeops/spawn.py:163) | yok: komut kurma kısmı `spawn.rs::{plan_spawn, child_env, window_command, gnome_terminal_argv}` (parite `parity_spawn` `{cli}-{mode}`); resume, eklenti/kanca çağrıları, hayalet temizliği, gnome/tmux başlatma yok. Python hatası? dry_run yan etkisi (TBD#373) | - | EKSİK(G9) |
| `_launch_gnome_terminal` (py/claudeops/spawn.py:325) | yok: yalnız argv `spawn.rs::gnome_terminal_argv` (parite `gt`, `ayna`); Popen ve zombi toplama yok | - | EKSİK(G9) |
| `_reclaim_ghost_session` (py/claudeops/spawn.py:366) | yok: rs/tmux `ghost_session`/`kill_session` var; sıralama ve diag yok | - | EKSİK(G9) |
| `_fallback_watchdog` (py/claudeops/spawn.py:384) | yok | - | EKSİK(G9) |
| `open_window` (py/claudeops/spawn.py:409) | yok: rs/tmux `attach_shell_fragment` var; işlev yok | - | EKSİK(G9) |
| `open_mirror_window` (py/claudeops/spawn.py:425) | yok: `spawn.rs::{mirror_window_command, mirror_child_env, gnome_terminal_argv}` TAŞINDI (parite `ayna ayna-tirnak`); başlatma yok | - | EKSİK(G9) |
| `EFFORT_LADDER` (py/claudeops/effort.py:19) | `effort.rs::EFFORT_LADDER` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `_RANK` (py/claudeops/effort.py:20) | `effort.rs::effort_rank` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `_ID_TIERS` (py/claudeops/effort.py:25) | `effort.rs::ID_TIERS` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `effort_rank` (py/claudeops/effort.py:28) | `effort.rs::effort_rank` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `split_tier` (py/claudeops/effort.py:33) | `effort.rs::split_tier` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `sort_levels` (py/claudeops/effort.py:45) | `effort.rs::sort_levels` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `nearest_effort` (py/claudeops/effort.py:56) | `effort.rs::nearest_effort` | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `ENV_NAME_RE` (py/claudeops/envnames.py:7) | `settings.rs::is_safe_env_name` | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `is_safe_env_name` (py/claudeops/envnames.py:10) | `settings.rs::is_safe_env_name` | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `services` (py/claudeops/ucli_session_opts.py:21) | `settings.rs::Settings::ucli_services` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `effort_levels_for` (py/claudeops/ucli_session_opts.py:27) | `settings.rs::Settings::ucli_effort_levels_for` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `FORBIDDEN_CMDS` (py/claudeops/ucli_session_opts.py:40) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_FORBIDDEN_RE` (py/claudeops/ucli_session_opts.py:54) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `is_forbidden_cmd` (py/claudeops/ucli_session_opts.py:57) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_FORBIDDEN_LOWER` (py/claudeops/ucli_session_opts.py:62) | `ucli_opts.rs::{FORBIDDEN, FORBIDDEN_VERSIONED, is_forbidden_cmd}` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_CMD_RE` (py/claudeops/ucli_session_opts.py:64) | `ucli_opts.rs::CMD` | `parity.rs::parity_ucli` `opts-`; `path_executables` içindeki kullanımı yok (G8) | TAŞINDI |
| `_GLOB_RE` (py/claudeops/ucli_session_opts.py:65) | `ucli_opts.rs::{GLOB, MAX_GLOBS, BROAD_GLOBS}` | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `MAX_CMDS` (py/claudeops/ucli_session_opts.py:66) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `MAX_EXPANDED` (py/claudeops/ucli_session_opts.py:67) | `ucli_opts.rs::{MAX_EXPANDED, expand_exec_cmds}` | `parity.rs::parity_misc` `expand` `re-exp` | TAŞINDI |
| `_PATTERN_CHARS` (py/claudeops/ucli_session_opts.py:68) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `MAX_GLOBS` (py/claudeops/ucli_session_opts.py:69) | `ucli_opts.rs::{GLOB, MAX_GLOBS, BROAD_GLOBS}` | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `MAX_BINDS` (py/claudeops/ucli_session_opts.py:70) | `ucli_opts.rs::{MAX_BINDS, BIND}` | `parity.rs::parity_ucli` `bind-` | TAŞINDI |
| `_BIND_RE` (py/claudeops/ucli_session_opts.py:71) | `ucli_opts.rs::{MAX_BINDS, BIND}` | `parity.rs::parity_ucli` `bind-` | TAŞINDI |
| `TIMEOUT_RANGE` (py/claudeops/ucli_session_opts.py:72) | `ucli_opts.rs::TIMEOUT_RANGE` | `parity.rs::parity_ucli` `timeout-` | TAŞINDI |
| `MAX_COST_USD` (py/claudeops/ucli_session_opts.py:73) | `ucli_opts.rs::MAX_COST_USD` | `parity.rs::parity_ucli` `cost-` `session-sinir` | TAŞINDI |
| `INT_LIMITS` (py/claudeops/ucli_session_opts.py:75) | `ucli_opts.rs::INT_LIMITS` | `parity.rs::parity_ucli` `int-` | TAŞINDI |
| `PRICE_MAX` (py/claudeops/ucli_session_opts.py:83) | `ucli_opts.rs::PRICE_MAX` | `parity.rs::parity_ucli` `price-` | TAŞINDI |
| `BROAD_GLOBS` (py/claudeops/ucli_session_opts.py:86) | `ucli_opts.rs::{GLOB, MAX_GLOBS, BROAD_GLOBS}` | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `_is_glob` (py/claudeops/ucli_session_opts.py:89) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `_items` (py/claudeops/ucli_session_opts.py:93) | `ucli_opts.rs::{MAX_CMDS, PATTERN, is_glob, items}` | `parity.rs::parity_ucli` `cmds-` | TAŞINDI |
| `validate_opts` (py/claudeops/ucli_session_opts.py:101) | `ucli_opts.rs::validate_opts` | `parity.rs::parity_ucli` `opts-`; ve `parity_misc` `val re-val` | TAŞINDI |
| `DEFAULT_MAX_SESSION_USD` (py/claudeops/ucli_session_opts.py:305) | `settings.rs::{DEFAULT_MAX_SESSION_USD, Settings::default_max_session_usd}` | `parity.rs::parity_settings_pyfmt` `usd` | TAŞINDI |
| `default_max_session_usd` (py/claudeops/ucli_session_opts.py:308) | `settings.rs::{DEFAULT_MAX_SESSION_USD, Settings::default_max_session_usd}` | `parity.rs::parity_settings_pyfmt` `usd` | TAŞINDI |
| `path_executables` (py/claudeops/ucli_session_opts.py:323) | yok: yalnız `Probe::path_executables` arayüzü | - | EKSİK(G8) |
| `expand_exec_cmds` (py/claudeops/ucli_session_opts.py:343) | `ucli_opts.rs::{MAX_EXPANDED, expand_exec_cmds}` | `parity.rs::parity_misc` `expand` `re-exp` | TAŞINDI |
| `_rustup_default_toolchain` (py/claudeops/ucli_session_opts.py:368) | yok: yalnız `Probe::rust_toolchain` arayüzü ve `Toolchain` türü | - | EKSİK(G8) |
| `rust_toolchain` (py/claudeops/ucli_session_opts.py:381) | yok: yalnız `Probe::rust_toolchain` arayüzü ve `Toolchain` türü | - | EKSİK(G8) |
| `exec_flags` (py/claudeops/ucli_session_opts.py:410) | `ucli_opts.rs::exec_flags` | `parity.rs::parity_misc` `exec` | TAŞINDI |
| `_MODELS_CACHE` (py/claudeops/ucli_session_opts.py:446) | yok | - | EKSİK(G7) |
| `_MODELS_TTL` (py/claudeops/ucli_session_opts.py:447) | yok | - | EKSİK(G7) |
| `service_models` (py/claudeops/ucli_session_opts.py:450) | yok | - | EKSİK(G7) |

### Kapsam dosyalarının çağırdığı dış adlar (`ucli_session_opts` dışındaki ayar/ucli/paths/steward modülleri; yalnız kullanılanlar ve onların bağımlılıkları)

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `HOME` (py/claudeops/paths.py:5) | `rs/state` `paths.rs` / `probe.rs::Paths::home` girdisi | rs/state (yol çözümü); crate girdi alır | KAPSAM DIŞI |
| `CLAUDE_DIR` (py/claudeops/paths.py:6) | `rs/proc` `Config::claude_dir` | rs/proc | KAPSAM DIŞI |
| `CLAUDEOPS_DIR` (py/claudeops/paths.py:45) | `rs/state` `paths.rs::StateDir::resolve` | rs/state; crate `Paths::claudeops_dir` girdisi alır | KAPSAM DIŞI |
| `REPO_DIR` (py/claudeops/paths.py:50) | yok: `Paths::repo_dir` girdisi var; değeri çözen kod yok | - | EKSİK(G9) |
| `CLAUDE_MODELS_JSON` (py/claudeops/paths.py:54) | yok: `ModelCatalog::claude_state` girdisi; okuma yok (rs/state `statedocs` DB_READY `claude_models` hazır) | - | EKSİK(G7) |
| `SESSIONS_DIR` (py/claudeops/paths.py:56) | `rs/proc` `Config::claude_dir` | rs/proc (`sessions/`, `projects/`) | KAPSAM DIŞI |
| `PROJECTS_DIR` (py/claudeops/paths.py:57) | `rs/proc` `Config::claude_dir` | rs/proc (`sessions/`, `projects/`) | KAPSAM DIŞI |
| `parse_proc_stat` (py/claudeops/paths.py:60) | `rs/proc` `procfs.rs::parse_stat` | rs/proc: `procfs::tests::stat_with_parens_in_comm` | KAPSAM DIŞI |
| `proc_stat_fields` (py/claudeops/paths.py:66) | `rs/proc` `procfs.rs::OwnProc::stat` | rs/proc: `fake_proc::own_ppid_from_real_proc` | KAPSAM DIŞI |
| `ucli_key_file` (py/claudeops/paths.py:76) | `probe.rs::Paths::ucli_key_file` | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `SETTINGS_JSON` (py/claudeops/settings.py:28) | `rs/state` `paths.rs::StateDir::settings_json` | rs/state (durum dizini ve dosya okuma) | KAPSAM DIŞI |
| `DEFAULT_SETTINGS` (py/claudeops/settings.py:38) | `rs/state` `settings.rs::defaults` (`default_settings.json`) | rs/state; bu crate okuduğu anahtarların varsayılanını kendi içinde verir (`dosya-yok`) | KAPSAM DIŞI |
| `_LOAD_CACHE` (py/claudeops/settings.py:239) | `rs/state` `settings.rs::SettingsReader` | rs/state (önbellek) | KAPSAM DIŞI |
| `load_settings` (py/claudeops/settings.py:242) | `settings.rs::Settings::from_json` (ayrıştırma toleransı) | `parity.rs::parity_settings_pyfmt` `bozuk-json` `json-liste` `dosya-yok`; dosya okuma, varsayılan birleştirme, önbellek rs/state `SettingsReader`; Python hatası? bozuk UTF-8 (TBD#373) | TAŞINDI |
| `_load_settings_uncached` (py/claudeops/settings.py:268) | `settings.rs::Settings::from_json` (ayrıştırma toleransı) | `parity.rs::parity_settings_pyfmt` `bozuk-json` `json-liste` `dosya-yok`; dosya okuma, varsayılan birleştirme, önbellek rs/state `SettingsReader`; Python hatası? bozuk UTF-8 (TBD#373) | TAŞINDI |
| `resolved_binary` (py/claudeops/settings.py:442) | `provider.rs::Providers::resolved_binary` | `parity.rs::parity_build` `-override` `-path-` `rb-`; Python hatası? `provider_bin` dize değil (TBD#373) | TAŞINDI |
| `_KNOWN_BINARY_PATHS` (py/claudeops/settings.py:466) | `provider.rs::CLAUDE_KNOWN_PATHS` | `parity.rs::parity_build` `claude-bilinen` | TAŞINDI |
| `default_model_for` (py/claudeops/settings.py:478) | `provider.rs::Providers::default_model_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `default_effort_for` (py/claudeops/settings.py:504) | `provider.rs::Providers::default_effort_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `resolved_model_for` (py/claudeops/settings.py:513) | `provider.rs::Providers::resolved_model_for` | `parity.rs::parity_model_effort` `bos-*` `ayar-*` | TAŞINDI |
| `byok_env_for` (py/claudeops/settings.py:532) | `settings.rs::Settings::byok_env` | `parity.rs::parity_settings_pyfmt` `byok` | TAŞINDI |
| `ucli_limit_overrides` (py/claudeops/settings.py:555) | `settings.rs::Settings::ucli_limit_overrides` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `routing_guidance_enabled` (py/claudeops/settings.py:601) | `settings.rs::Settings::routing_guidance_enabled` | `parity.rs::parity_settings_pyfmt` `metrics` | TAŞINDI |
| `_REASONING_LEVELS` (py/claudeops/settings.py:615) | `settings.rs::{REASONING_LEVELS, Settings::ucli_reasoning_mode}` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_reasoning_mode` (py/claudeops/settings.py:618) | `settings.rs::{REASONING_LEVELS, Settings::ucli_reasoning_mode}` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `_ON_WORDS` (py/claudeops/settings.py:632) | `settings.rs::{ON_WORDS, OFF_WORDS}` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `UCLI_STREAM_DEFAULT` (py/claudeops/settings.py:637) | `settings.rs::Settings::ucli_stream` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_stream_enabled` (py/claudeops/settings.py:640) | `settings.rs::Settings::ucli_stream` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `UCLI_SHOW_REASONING_DEFAULT` (py/claudeops/settings.py:655) | `settings.rs::Settings::ucli_show_reasoning` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_show_reasoning_enabled` (py/claudeops/settings.py:658) | `settings.rs::Settings::ucli_show_reasoning` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `UCLI_STATE_DIR_DEFAULT` (py/claudeops/settings.py:674) | `settings.rs::Settings::ucli_state_dir` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ucli_state_dir_enabled` (py/claudeops/settings.py:677) | `settings.rs::Settings::ucli_state_dir` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `_HOST_RE` (py/claudeops/settings.py:696) | `settings.rs::{HOST, MAX_FETCH_DOMAINS, Settings::ucli_web}` | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `_MAX_FETCH_DOMAINS` (py/claudeops/settings.py:697) | `settings.rs::{HOST, MAX_FETCH_DOMAINS, Settings::ucli_web}` | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `_valid_http_url` (py/claudeops/settings.py:700) | `settings.rs::valid_http_url` | `parity.rs::parity_settings_pyfmt` `url` `url-nfkc`; NFKC denetimi taşınmadı (kayıtlı ayrışma) | TAŞINDI |
| `_OFF_WORDS` (py/claudeops/settings.py:713) | `settings.rs::{ON_WORDS, OFF_WORDS}` | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `DEFAULT_UCLI_SERVICES` (py/claudeops/settings.py:769) | yok: `settings.rs::{builtin_services, Settings::ucli_services}` id/wire/endpoint/env/efforts için TAŞINDI (parite `servisler*`); `label` ve `models` yok | - | EKSİK(G11) |
| `UCLI_REASONING_LEVELS` (py/claudeops/settings.py:784) | `settings.rs::{REASONING_LEVELS, SVC_ID, SVC_ENV}` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `_SVC_ID_RE` (py/claudeops/settings.py:785) | `settings.rs::{REASONING_LEVELS, SVC_ID, SVC_ENV}` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `_SVC_ENV_RE` (py/claudeops/settings.py:786) | `settings.rs::{REASONING_LEVELS, SVC_ID, SVC_ENV}` | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `normalize_ucli_services` (py/claudeops/settings.py:789) | yok: `settings.rs::{builtin_services, Settings::ucli_services}` id/wire/endpoint/env/efforts için TAŞINDI (parite `servisler*`); `label` ve `models` yok | - | EKSİK(G11) |
| `ucli_services` (py/claudeops/settings.py:828) | yok: `settings.rs::{builtin_services, Settings::ucli_services}` id/wire/endpoint/env/efforts için TAŞINDI (parite `servisler*`); `label` ve `models` yok | - | EKSİK(G11) |
| `ucli_cost_config` (py/claudeops/settings.py:832) | yok: yalnız `cache_ttl`: `Settings::ucli_cache_ttl` (parite `script*`); tavan/kredi/tarih yok | - | EKSİK(G11) |
| `ucli_script_mode` (py/claudeops/settings.py:858) | `settings.rs::Settings::ucli_script_mode` | `parity.rs::parity_settings_pyfmt` `script` | TAŞINDI |
| `ucli_endpoint` (py/claudeops/settings.py:868) | `settings.rs::Settings::ucli_endpoint` | `parity.rs::parity_settings_pyfmt` `endpoint` | TAŞINDI |
| `ucli_web_config` (py/claudeops/settings.py:875) | `settings.rs::{HOST, MAX_FETCH_DOMAINS, Settings::ucli_web}` | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `main_session_model_effort` (py/claudeops/steward.py:2920) | `provider.rs::main_session_model_effort` | `parity.rs::parity_spawn` `ana-oturum`; rs/stew `prompts.rs::main_session_model_effort` ikinci kopya: birleştirmede tek kopyaya indirilmeli | TAŞINDI |
| `STATE_FILE` (py/claudeops/ucli_agents.py:26) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `TOKEN_DIR` (py/claudeops/ucli_agents.py:27) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_CHILD_RE` (py/claudeops/ucli_agents.py:35) | `ucli.rs::is_child_name` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_SAFE_NAME_RE` (py/claudeops/ucli_agents.py:36) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_LOCK` (py/claudeops/ucli_agents.py:38) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_PREVIEW` (py/claudeops/ucli_agents.py:39) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_PANEL_PORT` (py/claudeops/ucli_agents.py:49) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_OFF_WORDS` (py/claudeops/ucli_agents.py:54) | `settings.rs::AGENTS_OFF_WORDS` | `parity.rs::parity_settings_pyfmt` `metrics` | TAŞINDI |
| `enabled` (py/claudeops/ucli_agents.py:57) | `settings.rs::Settings::ucli_agents_enabled` | `parity.rs::parity_settings_pyfmt` `metrics` | TAŞINDI |
| `panel_url` (py/claudeops/ucli_agents.py:96) | `ucli.rs::Ctx::agent_setup` (port -> URL) | `parity.rs::parity_ucli` `ajan-acik` `ajan-port` | TAŞINDI |
| `is_child_name` (py/claudeops/ucli_agents.py:102) | `ucli.rs::is_child_name` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_empty` (py/claudeops/ucli_agents.py:127) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_load` (py/claudeops/ucli_agents.py:131) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_save` (py/claudeops/ucli_agents.py:145) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_digest` (py/claudeops/ucli_agents.py:150) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `token_file` (py/claudeops/ucli_agents.py:154) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `_write_token_file` (py/claudeops/ucli_agents.py:158) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `issue_token` (py/claudeops/ucli_agents.py:168) | yok: `Probe::{issue_agent_token, panel_port}` arayüzü; gerçek uygulama yok | - | EKSİK(G8) |
| `ROOT` (py/claudeops/ucli_approval.py:21) | yok | - | EKSİK(G10) |
| `STATES` (py/claudeops/ucli_approval.py:25) | yok | - | EKSİK(G10) |
| `_KEY` (py/claudeops/ucli_approval.py:26) | yok | - | EKSİK(G10) |
| `_ID` (py/claudeops/ucli_approval.py:27) | yok | - | EKSİK(G10) |
| `_index_path` (py/claudeops/ucli_approval.py:30) | yok | - | EKSİK(G10) |
| `dir_for` (py/claudeops/ucli_approval.py:34) | yok | - | EKSİK(G10) |
| `_load_index` (py/claudeops/ucli_approval.py:47) | yok | - | EKSİK(G10) |
| `register` (py/claudeops/ucli_approval.py:56) | yok | - | EKSİK(G10) |
| `set_state` (py/claudeops/ucli_approval.py:72) | yok | - | EKSİK(G10) |
| `parse_suspended` (py/claudeops/ucli_approval.py:144) | yok | - | EKSİK(G10) |
| `ROOT` (py/claudeops/ucli_ask.py:22) | `probe.rs::Paths::ucli_ask_root` | `parity.rs::parity_ucli` `askdir` | TAŞINDI |
| `_SAFE` (py/claudeops/ucli_ask.py:24) | `ucli.rs::valid_ask_name` | `parity.rs::parity_ucli` `askdir-gecersiz-ad` `askdir-satir-sonu` `askdir-uzun` | TAŞINDI |
| `dir_for` (py/claudeops/ucli_ask.py:27) | `ucli.rs::Ctx::apply_cli_opts` (ask_dir) + `Effect` | `parity.rs::parity_ucli` `askdir`; dizin açma yalnız test uygulayıcısında (G8) | TAŞINDI |
| `ROOT` (py/claudeops/ucli_checks.py:18) | `probe.rs::Paths::ucli_checks_root` | `parity.rs::parity_ucli` `checks-uygula` | TAŞINDI |
| `MAX_BYTES` (py/claudeops/ucli_checks.py:20) | yok: yalnız `Probe::checks_registry` arayüzü | - | EKSİK(G8) |
| `MAX_CHECKS` (py/claudeops/ucli_checks.py:21) | yok: yalnız `Probe::checks_registry` arayüzü | - | EKSİK(G8) |
| `_OWNER` (py/claudeops/ucli_checks.py:22) | yok: yalnız `Probe::checks_registry` arayüzü | - | EKSİK(G8) |
| `_NAME` (py/claudeops/ucli_checks.py:23) | yok: yalnız `Probe::checks_registry` arayüzü | - | EKSİK(G8) |
| `registry_path` (py/claudeops/ucli_checks.py:26) | `ucli.rs::Ctx::apply_cli_opts` (`owner.json`) | `parity.rs::parity_ucli` `checks-uygula`; yalnız varsayılan sahip | TAŞINDI |
| `check_shape` (py/claudeops/ucli_checks.py:33) | yok: yalnız `Probe::checks_registry` arayüzü | - | EKSİK(G8) |
| `load_registry` (py/claudeops/ucli_checks.py:53) | yok: yalnız `Probe::checks_registry` arayüzü | - | EKSİK(G8) |
| `OWN_UCLI` (py/claudeops/ucli_client.py:57) | `ucli.rs::resolve_binary` (`<repo>/bin/ucli`) | `parity.rs::parity_build` `ru-`; depo içi kopya senaryosu denetimli değil | TAŞINDI |
| `_SAFE_ENV_NAME_RE` (py/claudeops/ucli_client.py:72) | yok | - | EKSİK(G10) |
| `UcliError` (py/claudeops/ucli_client.py:75) | `probe.rs::SpawnError` | `parity.rs::parity_build` `ru-hic` | TAŞINDI |
| `resolve_binary` (py/claudeops/ucli_client.py:79) | `ucli.rs::resolve_binary` | `parity.rs::parity_build` `ru-`; `binary` parametresi yok; Python hatası? `provider_bin.ucli` null (TBD#373) | TAŞINDI |
| `_HELP_CACHE` (py/claudeops/ucli_client.py:149) | yok: yalnız `Probe::ucli_chat_help` arayüzü | - | EKSİK(G8) |
| `_HELP_TIMEOUT_SECONDS` (py/claudeops/ucli_client.py:150) | yok: yalnız `Probe::ucli_chat_help` arayüzü | - | EKSİK(G8) |
| `chat_help_text` (py/claudeops/ucli_client.py:153) | yok: yalnız `Probe::ucli_chat_help` arayüzü | - | EKSİK(G8) |
| `binary_supports_flag` (py/claudeops/ucli_client.py:177) | `ucli.rs::supports_flag` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `binary_flag_values` (py/claudeops/ucli_client.py:185) | `ucli.rs::flag_values` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_DERIVES_CONTEXT_MARK` (py/claudeops/ucli_client.py:195) | `ucli.rs::DERIVES_CONTEXT_MARK` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `binary_derives_context` (py/claudeops/ucli_client.py:198) | `ucli.rs::derives_context` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `build_chat_argv` (py/claudeops/ucli_client.py:203) | yok | - | EKSİK(G10) |
| `_subprocess_env` (py/claudeops/ucli_client.py:235) | yok | - | EKSİK(G10) |
| `STATE_ROOT` (py/claudeops/ucli_client.py:249) | `probe.rs::Paths::ucli_state_root` | `parity.rs::parity_ucli` `statedir-` | TAŞINDI |
| `state_dir_for` (py/claudeops/ucli_client.py:252) | `ucli.rs::state_dir_for` | `parity.rs::parity_misc` `ucli-misc`; ve `parity_ucli` `statedir-` | TAŞINDI |
| `legacy_chat_dir` (py/claudeops/ucli_client.py:260) | `ucli.rs::Ctx::state_dir_args` (satır içi yol) | `parity.rs::parity_ucli` `statedir-eski-gecmis`; okuyucular için public işlev yok (G6) | TAŞINDI |
| `chat_session_dirs` (py/claudeops/ucli_client.py:264) | yok | - | EKSİK(G6) |
| `find_chat_file` (py/claudeops/ucli_client.py:273) | yok | - | EKSİK(G6) |
| `failed_turn_records` (py/claudeops/ucli_client.py:292) | yok | - | EKSİK(G6) |
| `status_is_busy` (py/claudeops/ucli_client.py:348) | yok | - | EKSİK(G6) |
| `read_status_file` (py/claudeops/ucli_client.py:354) | yok | - | EKSİK(G6) |
| `read_chat_history` (py/claudeops/ucli_client.py:402) | yok | - | EKSİK(G2) |
| `_BUDGET_NOTES` (py/claudeops/ucli_client.py:429) | yok | - | EKSİK(G10) |
| `mark_budget_exhausted` (py/claudeops/ucli_client.py:434) | yok | - | EKSİK(G10) |
| `ucli_chat_once` (py/claudeops/ucli_client.py:460) | yok | - | EKSİK(G10) |
| `USAGE_DIR` (py/claudeops/ucli_cost.py:16) | `probe.rs::Paths::ucli_usage_dir` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `_CACHE` (py/claudeops/ucli_cost.py:17) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `_TTL` (py/claudeops/ucli_cost.py:18) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `DailyCapExceeded` (py/claudeops/ucli_cost.py:22) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `DailyCapExceeded.__init__` (py/claudeops/ucli_cost.py:25) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `log_path` (py/claudeops/ucli_cost.py:42) | `ucli.rs::usage_log_path` | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `OTHER_DIR` (py/claudeops/ucli_cost.py:47) | `ucli.rs::Ctx::apply_cli_opts` (`<usage>/other`) | `parity.rs::parity_ucli` `hizmet-` | TAŞINDI |
| `other_log_path` (py/claudeops/ucli_cost.py:50) | `ucli.rs::usage_log_path` + `/other` | `parity.rs::parity_ucli` `hizmet-grok` `opts-` | TAŞINDI |
| `CACHE_1H_WRITE_MULT` (py/claudeops/ucli_cost.py:57) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `write_mult` (py/claudeops/ucli_cost.py:60) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `_day_start_ms` (py/claudeops/ucli_cost.py:66) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `per_session_usd` (py/claudeops/ucli_cost.py:71) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `rate_by_session` (py/claudeops/ucli_cost.py:91) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `total_usd` (py/claudeops/ucli_cost.py:127) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `_date_ms` (py/claudeops/ucli_cost.py:147) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `credit_window` (py/claudeops/ucli_cost.py:157) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `today_usd` (py/claudeops/ucli_cost.py:174) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `BY_SESSION_TOP` (py/claudeops/ucli_cost.py:179) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `state` (py/claudeops/ucli_cost.py:182) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `cap_exceeded` (py/claudeops/ucli_cost.py:215) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `RESERVE_USD` (py/claudeops/ucli_cost.py:223) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `RESERVE_TTL` (py/claudeops/ucli_cost.py:224) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `_RESERVE_LOCK` (py/claudeops/ucli_cost.py:225) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `_RESERVED` (py/claudeops/ucli_cost.py:226) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `reserve` (py/claudeops/ucli_cost.py:229) | yok: yalnız `Probe::claude_cost_gate` arayüzü | - | EKSİK(G8) |
| `DEFAULTS` (py/claudeops/ucli_metrics.py:26) | yok: yalnız `enabled`: `Settings::ucli_metrics_enabled` (parite `metrics*`); aralık/saklama yok | - | EKSİK(G11) |
| `_num` (py/claudeops/ucli_metrics.py:41) | yok: yalnız `enabled`: `Settings::ucli_metrics_enabled` (parite `metrics*`); aralık/saklama yok | - | EKSİK(G11) |
| `get_config` (py/claudeops/ucli_metrics.py:49) | yok: yalnız `enabled`: `Settings::ucli_metrics_enabled` (parite `metrics*`); aralık/saklama yok | - | EKSİK(G11) |

### Diğer dış bağımlılıklar (görevdeki satır kümesinin dışında, bilgi için)

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `atomic_write_json` (py/claudeops/atomic_json.py:71) | `rs/state` `fsutil.rs::atomic_write_json` | rs/state | KAPSAM DIŞI |
| `atomic_write_text` (py/claudeops/atomic_json.py:101) | yok: `Effect::{WriteAtomic,WriteSecret}` uygulayıcısı yalnız testte | - | EKSİK(G8) |
| `file_lock` (py/claudeops/atomic_json.py:132) | `rs/state` `fsutil.rs::FileLock` | rs/state | KAPSAM DIŞI |
| `spawn_env` (py/claudeops/authz.py:493) | yok: `SpawnRequest::hook_env` girdisi | - | EKSİK(G9) |
| `codex_screen_count` (py/claudeops/bg_work.py:130) | yok | - | EKSİK(G6) |
| `codex_subagents_pending` (py/claudeops/bg_work.py:136) | yok | - | EKSİK(G6) |
| `screen_bg_count` (py/claudeops/bg_work.py:32) | yok | - | EKSİK(G6) |
| `tail_lines` (py/claudeops/bg_work.py:160) | yok | - | EKSİK(G6) |
| `transcript_pending_path` (py/claudeops/bg_work.py:112) | yok | - | EKSİK(G6) |
| `diag_log` (py/claudeops/diaglog.py:39) | yok: `Diag` biriktirilir, günlüğe yazan yok | - | EKSİK(G8) |
| `find_sessions` (py/claudeops/discovery.py:200) | `rs/proc` `discovery.rs::find_sessions` | rs/proc: `fake_proc::discovers_each_cli_and_names` | KAPSAM DIŞI |
| `session_mcp_spec` (py/claudeops/extensions.py:440) | yok: `SpawnRequest::extension_mcp` girdisi | - | EKSİK(G9) |
| `ensure_search_url` (py/claudeops/searxng.py:526) | yok: `Probe::searxng_url` arayüzü | - | EKSİK(G8) |
| `read_json` (py/claudeops/statedocs.py:130) | `rs/state` `statedocs.rs::StateDocs::read` | rs/state | KAPSAM DIŞI |
| `write_json` (py/claudeops/statedocs.py:175) | `rs/state` `statedocs.rs::StateDocs::write` | rs/state | KAPSAM DIŞI |
| `strip_ansi` (py/claudeops/tmux_backend.py:156) | `rs/tmux` `text.rs::strip_ansi` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_attach_shell_fragment` (py/claudeops/tmux_backend.py:73) | `rs/tmux` `shell.rs::attach_shell_fragment` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_available` (py/claudeops/tmux_backend.py:27) | `rs/tmux` `shell.rs::tmux_available` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_capture` (py/claudeops/tmux_backend.py:113) | `rs/tmux` `query.rs::capture` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_ghost_session` (py/claudeops/tmux_backend.py:642) | `rs/tmux` `shell.rs::ghost_session` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_has_session` (py/claudeops/tmux_backend.py:104) | `rs/tmux` `query.rs::has_session` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_kill_session` (py/claudeops/tmux_backend.py:677) | `rs/tmux` `shell.rs::kill_session` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_new_session_shell_fragment` (py/claudeops/tmux_backend.py:58) | `rs/tmux` `shell.rs::new_session_shell_fragment` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_send_keys` (py/claudeops/tmux_backend.py:160) | `rs/tmux` `keys.rs::send_text` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_send_special_key` (py/claudeops/tmux_backend.py:284) | `rs/tmux` `keys.rs::send_special_key` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |
| `tmux_spawn_direct` (py/claudeops/tmux_backend.py:81) | `rs/tmux` `shell.rs::spawn_direct` | rs/tmux (`cops-tmux`; iz henüz birleşmedi) | KAPSAM DIŞI |

## TEST EŞLEME TABLOSU

1327 satır: TAŞINDI 312, TAŞINDI-TESTSİZ 22, KAPSAM DIŞI 696, EKSİK 297.
- Vaka ailesi, `tests/parity/fam_*.rs` içindeki vaka kimliğinin bir parçasıdır. `TAŞINDI` = aynı davranış parite vakasıyla sınanıyor (Python testinin birebir kopyası değil).
- `steward_*` testlerinde `rs/stew` notu `origin/rs/stew:docs/rs-stew.md` satırından alındı.

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `AgyBinaryTest.test_inner_command_quotes_a_path_with_spaces` (py/tests/test_agy_binary_resolution.py:14) | `parity.rs::parity_build` `-override-bosluklu` | TAŞINDI |
| `AgyBinaryTest.test_model_choices_uses_the_resolved_binary` (py/tests/test_agy_binary_resolution.py:19) | yok: `agy models` çalıştırma yok | EKSİK(G7) |
| `AgyCompactionViewTests.test_checkpoint_becomes_boundary_and_plain_type23_is_ignored` (py/tests/test_agy_compaction_view.py:21) | yok | EKSİK(G2) |
| `AgyLastExchange.test_last_pair_skips_empty_assistant_steps` (py/tests/test_agy_last_exchange.py:33) | yok | EKSİK(G2) |
| `AgyLastExchange.test_empty_conversation_and_no_assistant` (py/tests/test_agy_last_exchange.py:37) | yok | EKSİK(G2) |
| `AgyLastExchange.test_checkpoint_between_does_not_break_pairing` (py/tests/test_agy_last_exchange.py:41) | yok | EKSİK(G2) |
| `AgyLastExchange.test_missing_db_is_empty` (py/tests/test_agy_last_exchange.py:45) | yok | EKSİK(G2) |
| `AgyModelsSwr.test_cold_blocks_then_stale_returns_old_immediately_and_refreshes_in_background` (py/tests/test_agy_models_swr.py:19) | yok | EKSİK(G7) |
| `AgySidsStoreTest.test_db_ready` (py/tests/test_agy_sids_store.py:31) | rs/state: `statedocs.rs::DB_READY` `agy_sids` | KAPSAM DIŞI |
| `AgySidsStoreTest.test_remember_writes_db_and_mirror` (py/tests/test_agy_sids_store.py:34) | yok: agy sid yazımı | EKSİK(G1) |
| `AgySidsStoreTest.test_unchanged_value_does_not_rewrite` (py/tests/test_agy_sids_store.py:42) | yok: agy sid yazımı | EKSİK(G1) |
| `AgySidsStoreTest.test_concurrent_remembers_lose_nothing` (py/tests/test_agy_sids_store.py:48) | yok: agy sid yazımı | EKSİK(G1) |
| `RoutingSymlink.test_symlink_kept_and_target_written_with_mode` (py/tests/test_atomic_users_symlink.py:13) | yok: karar `parity_misc` `sync-symlink`; gerçek yazım uygulayıcısı yok | EKSİK(G9) |
| `TokenFile.test_token_file_0600_atomic` (py/tests/test_atomic_users_symlink.py:30) | yok | EKSİK(G8) |
| `OrphanMarker.test_orphan_begin_does_not_eat_user_text` (py/tests/test_atomic_users_symlink.py:41) | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `OrphanMarker.test_normal_block_replaced_and_removed` (py/tests/test_atomic_users_symlink.py:50) | `parity.rs::parity_misc` `blok` | TAŞINDI |
| `DefaultsTest.test_no_hooks_is_noop` (py/tests/test_authz.py:27) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_every_web_path_has_an_action` (py/tests/test_authz.py:34) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_uzakgoz_freshness_is_read_only_mapped` (py/tests/test_authz.py:40) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_unknown_path_unmapped` (py/tests/test_authz.py:43) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_fail_closed` (py/tests/test_authz.py:48) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `DefaultsTest.test_public_route_only_auth_prefix` (py/tests/test_authz.py:60) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_legacy_token_unchanged_without_hooks` (py/tests/test_authz.py:87) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_authenticator_replaces_token_and_401` (py/tests/test_authz.py:91) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_agents_cookie_human_gated_on_get_and_post` (py/tests/test_authz.py:96) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_agent_bearer_token_works_in_multi_user_mode` (py/tests/test_authz.py:110) | T9: çok kullanıcı kimliği; token doğrulama T7 | KAPSAM DIŞI |
| `HttpTest.test_authorizer_denies_403_and_audits` (py/tests/test_authz.py:130) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_resource_from_body_name` (py/tests/test_authz.py:141) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_post_gate_sees_body_resource_once` (py/tests/test_authz.py:149) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ticket_gives_panel_cookie_only_to_admin_in_multi_user` (py/tests/test_authz.py:169) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ticket_keeps_panel_cookie_in_single_user` (py/tests/test_authz.py:177) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_orch_get_names_query_denied_if_any_name_denied` (py/tests/test_authz.py:180) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_files_without_name_is_400_even_when_global_allowed` (py/tests/test_authz.py:187) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ws_handshake_filters_status_for_principal` (py/tests/test_authz.py:199) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_status_filter_applied` (py/tests/test_authz.py:218) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_public_route_skips_auth_but_other_ext_routes_need_admin` (py/tests/test_authz.py:224) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_ui_extension_list_and_files` (py/tests/test_authz.py:236) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_session_event_emitted_on_success` (py/tests/test_authz.py:253) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_new_chat_and_adopt_event_use_real_instance_name` (py/tests/test_authz.py:264) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `HttpTest.test_session_event_emitted_before_response` (py/tests/test_authz.py:279) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `SpawnHookTest.test_no_hook_empty_and_threadlocal` (py/tests/test_authz.py:296) | T9: `authz` kancası ve ret biçimi | KAPSAM DIŞI |
| `SpawnHookTest.test_hook_env_refusal_and_fail_closed` (py/tests/test_authz.py:307) | T9: `authz` kancası ve ret biçimi | KAPSAM DIŞI |
| `SpawnHookTest.test_spawn_session_dry_run_gets_env` (py/tests/test_authz.py:320) | `parity.rs::parity_spawn` `-kanca`; kanca ortamı girdi | TAŞINDI |
| `SpawnHookTest.test_hook_session_usd_cap_min_with_default_and_popped_from_env` (py/tests/test_authz.py:330) | `parity.rs::parity_spawn` `kanca-` | TAŞINDI |
| `SpawnHookTest.test_refusal_formatting` (py/tests/test_authz.py:351) | T9: `authz` kancası ve ret biçimi | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_ws_ticket_bound_to_principal` (py/tests/test_authz.py:358) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_ticket_replaces_cookie_for_ws_only` (py/tests/test_authz.py:368) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_steward_resource_uses_sid_not_project_name` (py/tests/test_authz.py:382) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `TicketAndQuestionTest.test_question_page_access_check` (py/tests/test_authz.py:388) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_multi_resources` (py/tests/test_authz.py:405) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_names_query_and_body_each_a_resource` (py/tests/test_authz.py:413) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_files_path_never_becomes_a_resource` (py/tests/test_authz.py:420) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_event_sink_error_swallowed` (py/tests/test_authz.py:428) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_doc_prefix` (py/tests/test_authz.py:436) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ResourcesTest.test_ws_client_view` (py/tests/test_authz.py:445) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtensionCommandTest.test_register_and_dispatch` (py/tests/test_authz.py:470) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtensionCommandTest.test_core_name_not_overridden_and_no_load_for_core` (py/tests/test_authz.py:479) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtensionCommandTest.test_bad_name` (py/tests/test_authz.py:488) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtActionTableTest.test_action_for_reads_ext_table_longest_first` (py/tests/test_authz.py:498) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtActionTableTest.test_register_action_prefix_restricted` (py/tests/test_authz.py:508) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ExtActionTableTest.test_ui_extension_title_en` (py/tests/test_authz.py:512) | rs/gate / T9: `authz.py` eylem tablosu, HTTP kapısı ve eklenti kayıtları; bu iz kapsamı değil | KAPSAM DIŞI |
| `ScreenFixture.test_busy_screens` (py/tests/test_bg_work.py:39) | yok | EKSİK(G6) |
| `ScreenFixture.test_idle_screen_with_prose_numbers` (py/tests/test_bg_work.py:43) | yok | EKSİK(G6) |
| `TranscriptFixture.test_pending_without_notification` (py/tests/test_bg_work.py:69) | yok | EKSİK(G6) |
| `TranscriptFixture.test_completed_by_tool_use_id_or_task_id` (py/tests/test_bg_work.py:72) | yok | EKSİK(G6) |
| `TranscriptFixture.test_foreground_and_stale` (py/tests/test_bg_work.py:77) | yok | EKSİK(G6) |
| `TranscriptFixture.test_errored_call_is_not_pending` (py/tests/test_bg_work.py:81) | yok | EKSİK(G6) |
| `TranscriptFixture.test_one_of_two_pending` (py/tests/test_bg_work.py:87) | yok | EKSİK(G6) |
| `SubagentActiveForUsesBoth.test_screen_makes_active_even_without_subagent_files` (py/tests/test_bg_work.py:92) | T10: `web_steward` alt ajan etkinliği; `bg_work` okuyucusu G6 | KAPSAM DIŞI |
| `SubagentActiveForUsesBoth.test_transcript_pending_makes_active` (py/tests/test_bg_work.py:98) | T10: `web_steward` alt ajan etkinliği; `bg_work` okuyucusu G6 | KAPSAM DIŞI |
| `ProviderBackgroundWork.test_base_unknown_and_claude_counts` (py/tests/test_bg_work.py:113) | yok | EKSİK(G6) |
| `UcliBackgroundWork.test_reads_status_field_never_guesses` (py/tests/test_bg_work.py:126) | yok | EKSİK(G6) |
| `CodexBackgroundWork.test_screen_and_rollout` (py/tests/test_bg_work.py:150) | yok | EKSİK(G6) |
| `CodexBackgroundWork.test_provider_sums_screen_and_missing_rollout` (py/tests/test_bg_work.py:157) | yok | EKSİK(G6) |
| `BrainPermission.test_default_allow_edit_is_a_valid_ucli_mode` (py/tests/test_brain_permission_ucli.py:11) | rs/stew: `brain_permission`; mod listesi `parity_model_effort` `bos-*` | KAPSAM DIŞI |
| `BrainPermission.test_applied_only_for_ucli` (py/tests/test_brain_permission_ucli.py:15) | rs/stew | KAPSAM DIŞI |
| `CompactionViewTests.test_boundary_and_summary_roles_keep_pre_compaction_messages` (py/tests/test_chat_compaction_view.py:21) | yok | EKSİK(G2) |
| `CompactionViewTests.test_no_boundary_unchanged` (py/tests/test_chat_compaction_view.py:34) | yok | EKSİK(G2) |
| `CompactionViewTests.test_sidechain_summary_ignored` (py/tests/test_chat_compaction_view.py:38) | yok | EKSİK(G2) |
| `ClaudeModelsStoreTest.test_is_db_ready` (py/tests/test_claude_models_store.py:32) | rs/state: `statedocs.rs::DB_READY` `claude_models`; liste kuralı `parity_model_effort` `claude-state` | KAPSAM DIŞI |
| `ClaudeModelsStoreTest.test_write_goes_to_db_and_mirror_and_reads_from_db` (py/tests/test_claude_models_store.py:35) | rs/state: `statedocs.rs::DB_READY` `claude_models`; liste kuralı `parity_model_effort` `claude-state` | KAPSAM DIŞI |
| `ClaudeModelsStoreTest.test_db_wins_over_corrupt_or_missing_file` (py/tests/test_claude_models_store.py:42) | yok: katalog belgesini DB'den doldurma yok | EKSİK(G7) |
| `ClaudeModelsStoreTest.test_fallback_to_hardcoded_when_empty` (py/tests/test_claude_models_store.py:50) | `parity.rs::parity_model_effort` `claude-state` | TAŞINDI |
| `TrustFolder.test_adds_and_keeps_comments` (py/tests/test_copilot_trust.py:14) | `parity.rs::parity_build` `trust-dolu` | TAŞINDI |
| `TrustFolder.test_empty_list` (py/tests/test_copilot_trust.py:21) | `parity.rs::parity_build` `trust-bos` | TAŞINDI |
| `TrustFolder.test_keeps_private_mode` (py/tests/test_copilot_trust.py:26) | yok: izin koruyan atomik yazım uygulayıcısı yalnız testte | EKSİK(G8) |
| `TrustFolder.test_idempotent_and_missing` (py/tests/test_copilot_trust.py:34) | `parity.rs::parity_build` `trust-var` `trust-anahtar-yok` | TAŞINDI |
| `FindSessionsSidTests.test_a_fresh_session_gets_the_live_sid_from_the_json_entry` (py/tests/test_discovery_sid.py:77) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_resumed_session_keeps_its_sid_and_stays_resumed` (py/tests/test_discovery_sid.py:85) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_the_live_json_sid_wins_over_a_stale_cmdline_sid` (py/tests/test_discovery_sid.py:92) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_without_a_json_entry_the_cmdline_value_is_used_exactly_as_before` (py/tests/test_discovery_sid.py:101) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_json_entry_without_a_sid_never_blanks_the_cmdline_sid` (py/tests/test_discovery_sid.py:106) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_tui_renamed_session_is_listed_once_under_its_spawn_name` (py/tests/test_discovery_sid.py:110) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_each_session_gets_its_own_sid_by_pid` (py/tests/test_discovery_sid.py:116) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_json_entry_of_another_cli_never_donates_its_sid` (py/tests/test_discovery_sid.py:121) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `FindSessionsSidTests.test_a_non_claude_cli_keeps_its_cmdline_sid_and_its_old_is_fresh` (py/tests/test_discovery_sid.py:129) | rs/proc: rs-proc.md test eşlemesi: `fake_proc::json_sid_merge_rules_like_python`, `json_source_merges_with_proc_scan` | KAPSAM DIŞI |
| `IsFreshTests.test_flag_unknown_falls_back_to_the_sid` (py/tests/test_discovery_sid.py:138) | rs/proc: `session.rs::Session::is_fresh` | KAPSAM DIŞI |
| `IsFreshTests.test_flag_known_wins_over_the_sid` (py/tests/test_discovery_sid.py:143) | rs/proc: `session.rs::Session::is_fresh` | KAPSAM DIŞI |
| `SplitTierTests.test_tiered_ids` (py/tests/test_effort_by_model.py:56) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SplitTierTests.test_untiered_ids_are_untouched` (py/tests/test_effort_by_model.py:62) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SplitTierTests.test_non_string` (py/tests/test_effort_by_model.py:66) | rs/prov: gereksiz: Rust imzası yalnız dize alır | KAPSAM DIŞI |
| `SortAndNearestTests.test_sort_levels_orders_dedupes_keeps_unknown_last` (py/tests/test_effort_by_model.py:71) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_requested_in_levels_is_returned_as_is` (py/tests/test_effort_by_model.py:75) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_too_high_goes_to_the_top_supported` (py/tests/test_effort_by_model.py:78) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_prefers_below_over_equally_near_above` (py/tests/test_effort_by_model.py:81) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_nothing_below_takes_lowest_above` (py/tests/test_effort_by_model.py:85) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_empty_request_uses_default` (py/tests/test_effort_by_model.py:88) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_unknown_request_falls_back_via_default_rank` (py/tests/test_effort_by_model.py:92) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_empty_levels` (py/tests/test_effort_by_model.py:95) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `SortAndNearestTests.test_all_unknown_level_names` (py/tests/test_effort_by_model.py:98) | `parity.rs::parity_model_effort` `effort` | TAŞINDI |
| `AgyEffortTests.test_tier_in_id_fixes_the_levels` (py/tests/test_effort_by_model.py:103) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_untiered_non_gemini_has_no_info` (py/tests/test_effort_by_model.py:109) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_base_name_uses_live_siblings` (py/tests/test_effort_by_model.py:114) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_base_name_without_siblings_is_unknown` (py/tests/test_effort_by_model.py:118) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_empty_model` (py/tests/test_effort_by_model.py:122) | `parity.rs::parity_model_effort` `agy-models` | TAŞINDI |
| `AgyEffortTests.test_panel_default_max_no_longer_conflicts_with_tiered_id` (py/tests/test_effort_by_model.py:127) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_empty_effort_no_longer_defaults_to_medium_against_a_high_id` (py/tests/test_effort_by_model.py:134) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_requested_effort_follows_the_id_not_the_other_way` (py/tests/test_effort_by_model.py:140) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_matching_effort_is_unchanged` (py/tests/test_effort_by_model.py:145) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_non_gemini_still_gets_no_effort_flag` (py/tests/test_effort_by_model.py:151) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_argon_ids_are_consistent_with_their_tier` (py/tests/test_effort_by_model.py:159) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_gemini_base_name_clamps_to_live_tiers` (py/tests/test_effort_by_model.py:166) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `AgyEffortTests.test_gemini_base_name_without_info_keeps_old_behaviour` (py/tests/test_effort_by_model.py:171) | `parity.rs::parity_build` `-perm` ; `parity.rs::parity_spawn` `agy-effort-ayar` `agy-effort-kardes` | TAŞINDI |
| `CodexEffortTests.test_reads_per_model_levels` (py/tests/test_effort_by_model.py:195) | `parity.rs::parity_model_effort` `codex-cache` | TAŞINDI |
| `CodexEffortTests.test_unknown_model_or_empty_list_is_no_info` (py/tests/test_effort_by_model.py:199) | `parity.rs::parity_model_effort` `codex-cache` | TAŞINDI |
| `CodexEffortTests.test_missing_or_corrupt_cache_is_no_info` (py/tests/test_effort_by_model.py:204) | `parity.rs::parity_model_effort` `codex-cache-bozuk` `bos-` | TAŞINDI |
| `CodexEffortTests.test_unsupported_effort_is_clamped_supported_is_untouched` (py/tests/test_effort_by_model.py:211) | `parity.rs::parity_model_effort` `codex-cache` ; `parity.rs::parity_spawn` `codex-effort` | TAŞINDI |
| `CodexEffortTests.test_model_missing_from_cache_passes_through` (py/tests/test_effort_by_model.py:216) | `parity.rs::parity_model_effort` `codex-cache` ; `parity.rs::parity_spawn` `codex-effort` | TAŞINDI |
| `OtherProvidersPassThroughTests.test_fleet_values_pass_through_unchanged` (py/tests/test_effort_by_model.py:237) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `OtherProvidersPassThroughTests.test_unknown_values_are_not_rewritten_either` (py/tests/test_effort_by_model.py:244) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `OtherProvidersPassThroughTests.test_only_agy_and_codex_override_model_levels` (py/tests/test_effort_by_model.py:249) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `SpawnWiringTests.test_adjusted_effort_reaches_the_command_and_is_logged` (py/tests/test_effort_by_model.py:268) | `parity.rs::parity_spawn` `agy-effort-ayar` `codex-effort` | TAŞINDI |
| `SpawnWiringTests.test_unchanged_effort_is_not_logged` (py/tests/test_effort_by_model.py:275) | `parity.rs::parity_spawn` `-dry` | TAŞINDI |
| `SpawnWiringTests.test_resolver_failure_never_blocks_the_spawn` (py/tests/test_effort_by_model.py:280) | rs/prov: gereksiz: `Providers::resolve_effort` hata veremez | KAPSAM DIŞI |
| `EnvNames.test_valid_and_invalid` (py/tests/test_envnames.py:9) | `parity.rs::parity_spawn` `filter`; dize olmayan girdi tiple engelli | TAŞINDI |
| `EnvNames.test_spawn_filters_newline_and_dangerous` (py/tests/test_envnames.py:15) | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `McpHook.test_validation` (py/tests/test_extensions_mcp.py:22) | T9: `extensions` MCP kancası ve stdio sunucusu | KAPSAM DIŞI |
| `McpHook.test_stdio_roundtrip` (py/tests/test_extensions_mcp.py:34) | T9: `extensions` MCP kancası ve stdio sunucusu | KAPSAM DIŞI |
| `McpHook.test_unknown_server_exit_2` (py/tests/test_extensions_mcp.py:51) | T9: `extensions` MCP kancası ve stdio sunucusu | KAPSAM DIŞI |
| `SessionAttach.test_attach_predicate_and_spec` (py/tests/test_extensions_mcp.py:68) | yok: eklenti cwd koşulu ve `session_mcp_spec` çağrısı yok | EKSİK(G9) |
| `SessionAttach.test_claude_config_path_per_ext_and_spawn_wiring` (py/tests/test_extensions_mcp.py:82) | `parity.rs::parity_spawn` `-eklenti-mcp` `-mcp` | TAŞINDI |
| `SessionAttach.test_spawn_attaches_only_matching_cwd_and_claude` (py/tests/test_extensions_mcp.py:89) | yok: eklenti cwd koşulu ve `session_mcp_spec` çağrısı yok | EKSİK(G9) |
| `LastRealRequestEpochTests.test_returns_the_time_of_the_latest_real_request` (py/tests/test_handover_cache_policy.py:76) | yok | EKSİK(G3) |
| `LastRealRequestEpochTests.test_synthetic_placeholder_after_a_real_request_does_not_refresh_the_cache` (py/tests/test_handover_cache_policy.py:80) | yok | EKSİK(G3) |
| `LastRealRequestEpochTests.test_subagent_rows_are_a_separate_context_and_do_not_count` (py/tests/test_handover_cache_policy.py:86) | yok | EKSİK(G3) |
| `LastRealRequestEpochTests.test_rows_without_any_usage_tokens_do_not_count` (py/tests/test_handover_cache_policy.py:90) | yok | EKSİK(G3) |
| `LastRealRequestEpochTests.test_user_rows_are_ignored_and_no_assistant_means_unknown` (py/tests/test_handover_cache_policy.py:96) | yok | EKSİK(G3) |
| `LastRealRequestEpochTests.test_missing_file_is_unknown` (py/tests/test_handover_cache_policy.py:100) | yok | EKSİK(G3) |
| `LastRealRequestEpochTests.test_large_file_is_read_from_the_tail` (py/tests/test_handover_cache_policy.py:103) | yok | EKSİK(G3) |
| `ClaudeProviderCacheHookTests.test_ttl_is_one_hour` (py/tests/test_handover_cache_policy.py:110) | yok | EKSİK(G3) |
| `ClaudeProviderCacheHookTests.test_last_request_epoch_reads_only_the_exact_sid_file` (py/tests/test_handover_cache_policy.py:113) | yok | EKSİK(G3) |
| `ClaudeProviderCacheHookTests.test_no_sid_or_no_matching_file_is_unknown_never_the_newest_sibling` (py/tests/test_handover_cache_policy.py:123) | yok | EKSİK(G3) |
| `ClaudeProviderCacheHookTests.test_effort_switch_keeps_cache_by_model` (py/tests/test_handover_cache_policy.py:135) | yok | EKSİK(G3) |
| `ClaudeProviderCacheHookTests.test_other_providers_keep_the_old_behaviour` (py/tests/test_handover_cache_policy.py:148) | yok | EKSİK(G3) |
| `SessionFileSidTests.test_verified_file_gives_the_session_id` (py/tests/test_handover_cache_policy.py:177) | yok | EKSİK(G1) |
| `SessionFileSidTests.test_a_reused_pid_is_rejected_by_proc_start` (py/tests/test_handover_cache_policy.py:182) | yok | EKSİK(G1) |
| `SessionFileSidTests.test_unverifiable_or_inconsistent_files_are_not_trusted` (py/tests/test_handover_cache_policy.py:186) | yok | EKSİK(G1) |
| `SessionFileSidTests.test_dead_process_and_missing_file_and_no_pid` (py/tests/test_handover_cache_policy.py:202) | yok | EKSİK(G1) |
| `LastRequestEpochByPidTests.test_fresh_session_without_cmdline_sid_is_found_through_its_pid` (py/tests/test_handover_cache_policy.py:234) | yok | EKSİK(G3) |
| `LastRequestEpochByPidTests.test_without_a_pid_the_sidless_session_stays_unknown` (py/tests/test_handover_cache_policy.py:239) | yok | EKSİK(G3) |
| `LastRequestEpochByPidTests.test_the_newest_request_of_the_two_candidate_files_wins` (py/tests/test_handover_cache_policy.py:245) | yok | EKSİK(G3) |
| `LastRequestEpochByPidTests.test_a_missing_candidate_file_falls_back_to_the_other_one` (py/tests/test_handover_cache_policy.py:255) | yok | EKSİK(G3) |
| `LastRequestEpochByPidTests.test_a_sibling_session_in_the_same_directory_is_never_picked_up` (py/tests/test_handover_cache_policy.py:260) | yok | EKSİK(G3) |
| `LastRequestEpochByPidTests.test_empty_conversation_file_is_unknown` (py/tests/test_handover_cache_policy.py:266) | yok | EKSİK(G3) |
| `PromptCacheIsWarmTests.test_margin_is_five_minutes` (py/tests/test_handover_cache_policy.py:288) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_fresh_request_is_warm` (py/tests/test_handover_cache_policy.py:291) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_boundary_and_older_is_cold` (py/tests/test_handover_cache_policy.py:296) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_future_timestamp_from_clock_skew_counts_as_warm` (py/tests/test_handover_cache_policy.py:301) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_unknown_when_provider_has_no_ttl_or_no_transcript` (py/tests/test_handover_cache_policy.py:304) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_now_defaults_to_the_wall_clock` (py/tests/test_handover_cache_policy.py:309) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `PromptCacheIsWarmTests.test_the_process_id_reaches_the_provider` (py/tests/test_handover_cache_policy.py:314) | T4: `handover.prompt_cache_is_warm`; sağlayıcı girdileri G3 | KAPSAM DIŞI |
| `ModelDowngradeTests.test_warm_opus_keeps_its_model_but_still_lowers_effort` (py/tests/test_handover_cache_policy.py:373) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_cold_opus_goes_down_to_sonnet_then_effort_in_that_order` (py/tests/test_handover_cache_policy.py:385) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_fable_follows_the_same_rule` (py/tests/test_handover_cache_policy.py:395) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_boundary_is_the_ttl_minus_margin` (py/tests/test_handover_cache_policy.py:403) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_models_that_are_not_downgrade_candidates_never_get_a_model_command` (py/tests/test_handover_cache_policy.py:411) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_unknown_warmth_keeps_the_old_always_downgrade_behaviour` (py/tests/test_handover_cache_policy.py:420) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_a_failing_cache_probe_never_blocks_the_wrap_up` (py/tests/test_handover_cache_policy.py:427) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_escape_hatch_restores_the_old_behaviour_and_never_probes` (py/tests/test_handover_cache_policy.py:434) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_missing_setting_defaults_to_cache_aware` (py/tests/test_handover_cache_policy.py:442) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `ModelDowngradeTests.test_provider_without_a_cache_ttl_keeps_the_old_behaviour` (py/tests/test_handover_cache_policy.py:448) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_warm_sonnet_55_gets_the_cache_safe_effort_drop` (py/tests/test_handover_cache_policy.py:459) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_warm_sonnet_5_skips_the_effort_drop_that_would_rewrite_the_cache` (py/tests/test_handover_cache_policy.py:466) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_cold_sonnet_5_gets_the_effort_drop_because_the_cache_is_gone_anyway` (py/tests/test_handover_cache_policy.py:476) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_unknown_warmth_on_sonnet_5_keeps_the_old_behaviour` (py/tests/test_handover_cache_policy.py:482) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_effort_already_at_or_below_the_target_is_left_alone` (py/tests/test_handover_cache_policy.py:487) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_effort_command_failure_is_swallowed` (py/tests/test_handover_cache_policy.py:493) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `EffortDowngradeTests.test_public_wrapper_keeps_its_old_positional_signature` (py/tests/test_handover_cache_policy.py:500) | yok: devir politikası T4; canlı model/effort ve sağlayıcı kancaları yok | EKSİK(G3) |
| `CallSiteWiringTests.test_cli_path_calls_the_shared_policy_once_per_target` (py/tests/test_handover_cache_policy.py:520) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `CallSiteWiringTests.test_web_path_calls_the_shared_policy_with_the_spawn_time_values` (py/tests/test_handover_cache_policy.py:534) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `CallSiteWiringTests.test_web_path_targets_the_resolved_session_for_unique_base` (py/tests/test_handover_cache_policy.py:547) | T4: `handover`/web çağrı bağlantısı | KAPSAM DIŞI |
| `CallSiteWiringTests.test_real_policy_runs_end_to_end_through_the_web_path` (py/tests/test_handover_cache_policy.py:564) | yok | EKSİK(G3) |
| `LastAssistantSinceTests.test_since_returns_only_rows_written_after_the_process_started` (py/tests/test_live_model_effort.py:62) | yok | EKSİK(G3) |
| `LastAssistantSinceTests.test_only_previous_incarnation_rows_means_unknown` (py/tests/test_live_model_effort.py:68) | yok | EKSİK(G3) |
| `LastAssistantSinceTests.test_without_since_behaviour_is_unchanged` (py/tests/test_live_model_effort.py:74) | yok | EKSİK(G3) |
| `LastAssistantSinceTests.test_row_without_timestamp_is_not_treated_as_old` (py/tests/test_live_model_effort.py:79) | yok | EKSİK(G3) |
| `LastAssistantSinceTests.test_scan_stops_at_the_first_older_row` (py/tests/test_live_model_effort.py:84) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_live_values_written_by_this_process_replace_cmdline_values` (py/tests/test_live_model_effort.py:107) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_fresh_resume_without_a_turn_keeps_cmdline_values` (py/tests/test_live_model_effort.py:111) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_effort_missing_in_live_rows_falls_back_per_field` (py/tests/test_live_model_effort.py:115) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_another_sessions_file_is_ignored` (py/tests/test_live_model_effort.py:119) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_non_claude_and_sidless_sessions_never_touch_the_file` (py/tests/test_live_model_effort.py:123) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_unknown_process_start_falls_back` (py/tests/test_live_model_effort.py:129) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_unchanged_file_is_not_reread_and_changed_file_is_` (py/tests/test_live_model_effort.py:133) | yok | EKSİK(G3) |
| `LiveModelEffortTests.test_read_error_falls_back_and_does_not_raise` (py/tests/test_live_model_effort.py:151) | yok | EKSİK(G3) |
| `LiveModelEndpointTests.test_live_model_ignores_previous_incarnation` (py/tests/test_live_model_effort.py:168) | yok | EKSİK(G3) |
| `LiveModelEndpointTests.test_live_effort_ignores_previous_incarnation` (py/tests/test_live_model_effort.py:175) | yok | EKSİK(G3) |
| `LiveModelEndpointTests.test_neighbour_transcript_is_not_reported` (py/tests/test_live_model_effort.py:183) | yok | EKSİK(G3) |
| `EffortSwitchNoBlindEnter.test_no_dialog_no_enter` (py/tests/test_live_model_effort.py:215) | yok | EKSİK(G4) |
| `NoteMirrorTests.test_records_the_pid_under_the_spec` (py/tests/test_mirror_marker.py:47) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `NoteMirrorTests.test_same_spec_accumulates_pids` (py/tests/test_mirror_marker.py:52) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `NoteMirrorTests.test_anything_else_leaves_the_dict_alone` (py/tests/test_mirror_marker.py:58) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_viewers_are_collected_in_the_same_pass` (py/tests/test_mirror_marker.py:91) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_viewers_are_not_sessions_and_fleet_result_is_unchanged` (py/tests/test_mirror_marker.py:97) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_default_does_not_collect_anything` (py/tests/test_mirror_marker.py:104) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `FindSessionsMirrorsOutTests.test_a_real_viewer_process_is_seen_by_the_real_scan` (py/tests/test_mirror_marker.py:110) | rs/proc: `mirrors.rs`; rs-proc.md test eşlemesi | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_open_and_closed_are_stamped_per_remote_row` (py/tests/test_mirror_marker.py:148) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_same_name_on_two_hosts_is_told_apart` (py/tests/test_mirror_marker.py:155) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_match_is_exact_not_a_prefix` (py/tests/test_mirror_marker.py:162) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_cached_rows_are_copied_not_mutated` (py/tests/test_mirror_marker.py:169) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_stale_value_from_upstream_is_overwritten` (py/tests/test_mirror_marker.py:177) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_no_marker_at_all_when_the_state_is_unknown` (py/tests/test_mirror_marker.py:182) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_empty_set_means_known_and_closed` (py/tests/test_mirror_marker.py:187) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_local_closed_and_retired_rows_are_not_stamped` (py/tests/test_mirror_marker.py:192) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_a_dict_works_as_the_container_like_find_sessions_hands_it_over` (py/tests/test_mirror_marker.py:201) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `MergeStatusMarkerTests.test_unpolled_host_adds_no_rows_and_no_crash` (py/tests/test_mirror_marker.py:206) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `StatusPayloadWiringTests.test_remote_rows_carry_the_marker_from_the_fleet_scan` (py/tests/test_mirror_marker.py:243) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `StatusPayloadWiringTests.test_exactly_one_scan_carries_the_collector` (py/tests/test_mirror_marker.py:249) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `StatusPayloadWiringTests.test_a_closed_window_flips_the_marker_on_the_next_tick` (py/tests/test_mirror_marker.py:259) | T1: panel durum satırı işaretleme (rs-proc.md aynı sahip) | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_host_and_name` (py/tests/test_mirror_window.py:33) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_bare_name_is_local` (py/tests/test_mirror_window.py:36) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_flags_before_or_after_the_target` (py/tests/test_mirror_window.py:39) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_value_of_a_flag_is_not_mistaken_for_the_target` (py/tests/test_mirror_window.py:44) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_once_is_not_a_window` (py/tests/test_mirror_window.py:47) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_other_commands_do_not_match` (py/tests/test_mirror_window.py:50) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_watch_without_a_target` (py/tests/test_mirror_window.py:56) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `SpecFromCmdlineTests.test_empty_parts` (py/tests/test_mirror_window.py:60) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_collects_pids_per_spec` (py/tests/test_mirror_window.py:78) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_other_users_processes_are_ignored` (py/tests/test_mirror_window.py:83) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_unreadable_processes_are_skipped` (py/tests/test_mirror_window.py:86) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_default_uid_is_the_current_user` (py/tests/test_mirror_window.py:89) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `RunningMirrorsTests.test_a_process_vanishing_mid_scan_is_skipped` (py/tests/test_mirror_window.py:94) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `FocusWindowTests.test_uses_exact_title_matching_and_the_given_display` (py/tests/test_mirror_window.py:104) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `FocusWindowTests.test_failures_are_false_not_exceptions` (py/tests/test_mirror_window.py:117) | rs/proc: `mirrors.rs` | KAPSAM DIŞI |
| `OpenMirrorWindowSpawnTests.test_gnome_terminal_argv` (py/tests/test_mirror_window.py:138) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_the_command_runs_cops_watch_against_this_panels_port` (py/tests/test_mirror_window.py:145) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it` (py/tests/test_mirror_window.py:151) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_arguments_are_shell_quoted` (py/tests/test_mirror_window.py:158) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_environment` (py/tests/test_mirror_window.py:162) | `parity.rs::parity_spawn` `ayna` `ayna-tirnak` | TAŞINDI |
| `OpenMirrorWindowSpawnTests.test_popen_failure_is_false` (py/tests/test_mirror_window.py:170) | yok | EKSİK(G9) |
| `OpenMirrorWindowBackendTests.test_success_spawns_once_with_the_panels_port` (py/tests/test_mirror_window.py:211) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_local_sessions_are_rejected` (py/tests/test_mirror_window.py:215) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_bad_characters_never_reach_the_command_line` (py/tests/test_mirror_window.py:222) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_unknown_host` (py/tests/test_mirror_window.py:229) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_session_must_be_in_the_hosts_last_known_state` (py/tests/test_mirror_window.py:234) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_a_session_without_tmux_has_no_terminal_to_mirror` (py/tests/test_mirror_window.py:245) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_no_x11_display` (py/tests/test_mirror_window.py:250) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_an_open_mirror_is_focused_not_duplicated` (py/tests/test_mirror_window.py:257) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_force_opens_a_second_one` (py/tests/test_mirror_window.py:263) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_another_sessions_mirror_does_not_count` (py/tests/test_mirror_window.py:269) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_launch_failure` (py/tests/test_mirror_window.py:274) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `OpenMirrorWindowBackendTests.test_messages_follow_the_language` (py/tests/test_mirror_window.py:280) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_route_is_declared_local_only` (py/tests/test_mirror_window.py:323) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_post_with_a_remote_host_field_is_handled_locally` (py/tests/test_mirror_window.py:326) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_force_flag_is_passed_through` (py/tests/test_mirror_window.py:331) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_name_is_required` (py/tests/test_mirror_window.py:335) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `MirrorRouteHttpTests.test_token_is_required` (py/tests/test_mirror_window.py:340) | T2: `/api/term/mirror-window` ucu | KAPSAM DIŞI |
| `LayoutRecognisesMirrorWindowsTests.test_a_mirror_window_is_tiled_once_its_spec_is_known` (py/tests/test_mirror_window.py:355) | T7: pencere yerleşimi | KAPSAM DIŞI |
| `LayoutRecognisesMirrorWindowsTests.test_without_the_spec_it_is_skipped_as_before` (py/tests/test_mirror_window.py:360) | T7: pencere yerleşimi | KAPSAM DIŞI |
| `LayoutRecognisesMirrorWindowsTests.test_title_from_the_viewer_survives_list_windows_cleaning` (py/tests/test_mirror_window.py:365) | T7: pencere yerleşimi | KAPSAM DIŞI |
| `WebNeedsHoCachedTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` (py/tests/test_needs_ho_transcript.py:64) | T1: web önbelleği; `needs_ho` rs/proc | KAPSAM DIŞI |
| `WebNeedsHoCachedTests.test_without_a_sid_or_a_matching_file_it_falls_back_to_the_newest_file` (py/tests/test_needs_ho_transcript.py:68) | yok: "cwd'deki en yeni dosya" düşüşü rs/proc'ta bilerek yok | EKSİK(G1) |
| `HandoverBatchTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` (py/tests/test_needs_ho_transcript.py:89) | T4: devir toplu akışı; `needs_ho` rs/proc | KAPSAM DIŞI |
| `HandoverBatchTests.test_without_a_sid_it_falls_back_to_the_newest_file` (py/tests/test_needs_ho_transcript.py:93) | yok: "cwd'deki en yeni dosya" düşüşü rs/proc'ta bilerek yok | EKSİK(G1) |
| `MatchesProcTest.test_repl_is_fleet` (py/tests/test_proc07_io_ucli_not_fleet.py:15) | rs/proc: `providers.rs::detect` | KAPSAM DIŞI |
| `MatchesProcTest.test_oneshot_and_reviewer_are_not_fleet` (py/tests/test_proc07_io_ucli_not_fleet.py:18) | rs/proc: `providers.rs::detect` | KAPSAM DIŞI |
| `IoAskLiveNameTest.test_rejects_live_same_name` (py/tests/test_proc07_io_ucli_not_fleet.py:28) | T7: `/api/io` ucu | KAPSAM DIŞI |
| `IoAskLiveNameTest.test_other_name_goes_through` (py/tests/test_proc07_io_ucli_not_fleet.py:36) | T7: `/api/io` ucu | KAPSAM DIŞI |
| `NoBlindEnterTest.test_permission_dialog_is_not_confirmed` (py/tests/test_proc08_model_switch_no_blind_enter.py:33) | yok | EKSİK(G4) |
| `NoBlindEnterTest.test_switch_dialog_confirmed_once` (py/tests/test_proc08_model_switch_no_blind_enter.py:36) | yok | EKSİK(G4) |
| `NoBlindEnterTest.test_applied_without_dialog` (py/tests/test_proc08_model_switch_no_blind_enter.py:39) | yok | EKSİK(G4) |
| `TestBase.test_default_and_unsupported_are_none` (py/tests/test_provider_live_context.py:23) | yok | EKSİK(G6) |
| `TestCodex.test_last_token_count_input_tokens` (py/tests/test_provider_live_context.py:43) | yok | EKSİK(G6) |
| `TestCodex.test_no_token_event_or_no_file_is_none` (py/tests/test_provider_live_context.py:47) | yok | EKSİK(G6) |
| `TestCodex.test_null_info_is_none` (py/tests/test_provider_live_context.py:52) | yok | EKSİK(G6) |
| `TestCopilot.test_latest_main_agent_row` (py/tests/test_provider_live_context.py:75) | yok | EKSİK(G6) |
| `TestCopilot.test_unknown_session_or_no_db_is_none` (py/tests/test_provider_live_context.py:78) | yok | EKSİK(G6) |
| `TestStatusRow.test_context_info_uses_provider_hook_and_hides_unknown` (py/tests/test_provider_live_context.py:89) | yok | EKSİK(G6) |
| `WantsSplitTests.test_ucli_no_wrapup_but_has_conversation_and_stuck` (py/tests/test_provider_wants_split.py:15) | yok | EKSİK(G4) |
| `WantsSplitTests.test_claude_defaults_follow_has_conversation` (py/tests/test_provider_wants_split.py:21) | yok | EKSİK(G4) |
| `WantsSplitTests.test_shell_wants_nothing` (py/tests/test_provider_wants_split.py:26) | yok | EKSİK(G4) |
| `DefaultsTest.test_claude_defaults_to_newest_sonnet_medium` (py/tests/test_routing_guidance.py:32) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultsTest.test_provider_without_model_choices_gives_empty_default` (py/tests/test_routing_guidance.py:38) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultsTest.test_override_wins_and_invalid_override_falls_back` (py/tests/test_routing_guidance.py:44) | `parity.rs::parity_model_effort` `ayar-` | TAŞINDI |
| `DefaultsTest.test_other_providers_keep_old_top_level_effort` (py/tests/test_routing_guidance.py:53) | `parity.rs::parity_model_effort` `bos-` `ayar-` | TAŞINDI |
| `GuidanceTest.test_enabled_by_default_and_bundled_path_used` (py/tests/test_routing_guidance.py:60) | `parity.rs::parity_build` `-perm` | TAŞINDI |
| `GuidanceTest.test_off_disables_flag` (py/tests/test_routing_guidance.py:65) | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `GuidanceTest.test_override_text_is_written_and_used` (py/tests/test_routing_guidance.py:71) | `parity.rs::parity_build` `claude-routing-` | TAŞINDI |
| `GuidanceTest.test_guidance_failure_never_breaks_spawn` (py/tests/test_routing_guidance.py:80) | `routing.rs::claude_guidance_path`; sınanmayan senaryo: paketli dosya okunamayınca bayraksız açılış | TAŞINDI-TESTSİZ |
| `CodexSyncTest.test_agy_file_is_created_with_only_the_block_and_removed_with_it` (py/tests/test_routing_guidance.py:90) | yok: karar `parity_misc` `sync`; `sync_global_files` dosya adımları yok | EKSİK(G9) |
| `CodexSyncTest.test_existing_agy_file_keeps_user_text` (py/tests/test_routing_guidance.py:98) | yok: karar `parity_misc` `sync`; `sync_global_files` dosya adımları yok | EKSİK(G9) |
| `CodexSyncTest.test_missing_file_is_not_created` (py/tests/test_routing_guidance.py:117) | yok: karar `parity_misc` `sync`; `sync_global_files` dosya adımları yok | EKSİK(G9) |
| `CodexSyncTest.test_write_is_idempotent_keeps_rest_and_backs_up` (py/tests/test_routing_guidance.py:122) | yok: karar `parity_misc` `sync`; `sync_global_files` dosya adımları yok | EKSİK(G9) |
| `CodexSyncTest.test_text_change_replaces_block_and_off_removes_it` (py/tests/test_routing_guidance.py:131) | yok: karar `parity_misc` `sync`; `sync_global_files` dosya adımları yok | EKSİK(G9) |
| `RustToolchainPickTest.test_single_toolchain_without_env` (py/tests/test_rust_toolchain_pick.py:30) | yok | EKSİK(G8) |
| `RustToolchainPickTest.test_prefix_match` (py/tests/test_rust_toolchain_pick.py:35) | yok | EKSİK(G8) |
| `RustToolchainPickTest.test_mismatch_is_error_not_fallback` (py/tests/test_rust_toolchain_pick.py:40) | yok | EKSİK(G8) |
| `RustToolchainDefaultTest.test_single_toolchain_without_env` (py/tests/test_rust_toolchain_pick.py:59) | yok | EKSİK(G8) |
| `RustToolchainDefaultTest.test_default_toolchain_picks_one` (py/tests/test_rust_toolchain_pick.py:64) | yok | EKSİK(G8) |
| `RustToolchainDefaultTest.test_short_default_name` (py/tests/test_rust_toolchain_pick.py:70) | yok | EKSİK(G8) |
| `RustToolchainDefaultTest.test_env_still_wins` (py/tests/test_rust_toolchain_pick.py:76) | yok | EKSİK(G8) |
| `ServiceModelsCache.test_ttl_is_24h` (py/tests/test_service_models_cache.py:28) | yok | EKSİK(G7) |
| `ServiceModelsCache.test_success_cached_for_a_day` (py/tests/test_service_models_cache.py:31) | yok | EKSİK(G7) |
| `ServiceModelsCache.test_failure_returns_empty_and_retries_after_60s` (py/tests/test_service_models_cache.py:48) | yok | EKSİK(G7) |
| `DetectDisplayTest.test_socket_only_x0` (py/tests/test_spawn_detect_display_socket.py:25) | `spawn.rs::detect_display`; sınanmayan senaryo: denetimli soket/kilit dosyası düzeni (parite gerçek /tmp okur) | TAŞINDI-TESTSİZ |
| `DetectDisplayTest.test_lock_still_works` (py/tests/test_spawn_detect_display_socket.py:28) | `spawn.rs::detect_display`; sınanmayan senaryo: denetimli soket/kilit dosyası düzeni (parite gerçek /tmp okur) | TAŞINDI-TESTSİZ |
| `DetectDisplayTest.test_prefers_1_over_0` (py/tests/test_spawn_detect_display_socket.py:31) | `spawn.rs::detect_display`; sınanmayan senaryo: denetimli soket/kilit dosyası düzeni (parite gerçek /tmp okur) | TAŞINDI-TESTSİZ |
| `DetectDisplayTest.test_nothing_defaults_1` (py/tests/test_spawn_detect_display_socket.py:34) | `spawn.rs::detect_display`; sınanmayan senaryo: denetimli soket/kilit dosyası düzeni (parite gerçek /tmp okur) | TAŞINDI-TESTSİZ |
| `DetectDisplayTest.test_env_wins` (py/tests/test_spawn_detect_display_socket.py:37) | `parity.rs::parity_spawn` `display-env` | TAŞINDI |
| `EnvFilter.test_filters` (py/tests/test_spawn_env_filter.py:11) | `parity.rs::parity_spawn` `filter` | TAŞINDI |
| `GhostDetectTest.test_old_bare_bash_is_ghost` (py/tests/test_spawn_ghost_reclaim.py:25) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_live_cli_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:28) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_young_session_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:31) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_bash_with_child_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:34) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_no_session_or_garbage` (py/tests/test_spawn_ghost_reclaim.py:37) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `GhostDetectTest.test_mixed_panes` (py/tests/test_spawn_ghost_reclaim.py:42) | rs/tmux: `shell.rs::ghost_session` | KAPSAM DIŞI |
| `ReclaimTest.test_ghost_killed_and_tail_logged` (py/tests/test_spawn_ghost_reclaim.py:57) | yok | EKSİK(G9) |
| `ReclaimTest.test_shell_provider_untouched` (py/tests/test_spawn_ghost_reclaim.py:63) | yok | EKSİK(G9) |
| `ReclaimTest.test_not_ghost_untouched` (py/tests/test_spawn_ghost_reclaim.py:66) | yok | EKSİK(G9) |
| `ReclaimTest.test_error_never_raises` (py/tests/test_spawn_ghost_reclaim.py:69) | yok | EKSİK(G9) |
| `SpawnPriority.test_default_and_exempt_and_off` (py/tests/test_spawn_priority.py:17) | `parity.rs::parity_spawn` `prefix-` | TAŞINDI |
| `SpawnPriority.test_child_inherits_nice` (py/tests/test_spawn_priority.py:27) | `spawn.rs::priority_prefix`; sınanmayan senaryo: önekin gerçek kabukta çocuk sürece nice aktarması | TAŞINDI-TESTSİZ |
| `TestDefaultClaudeMdGolden.test_default_output_is_byte_identical_to_pre_p5` (py/tests/test_steward_brain.py:62) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `TestDefaultClaudeMdGolden.test_identity_section_only_for_non_default` (py/tests/test_steward_brain.py:71) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `TestWorkspace.test_default_workspace_claude_md_is_unchanged_and_not_rewritten` (py/tests/test_steward_brain.py:144) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors ... | KAPSAM DIŞI |
| `TestWorkspace.test_default_persona_override_still_applies` (py/tests/test_steward_brain.py:157) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors ... | KAPSAM DIŞI |
| `TestWorkspace.test_identity_workspace_is_separate_with_identity_and_model_rule` (py/tests/test_steward_brain.py:163) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp ... | KAPSAM DIŞI |
| `TestWorkspace.test_identity_persona_falls_back_to_shared` (py/tests/test_steward_brain.py:180) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp ... | KAPSAM DIŞI |
| `TestBrainMcp.test_verify_uses_connect_heartbeat` (py/tests/test_steward_brain.py:193) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_start_without_mcp_restarts_once_then_gives_up` (py/tests/test_steward_brain.py:201) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_start_defaults_to_new_conversation` (py/tests/test_steward_brain.py:216) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_close_note_written_without_model_turn` (py/tests/test_steward_brain.py:223) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges, identity::p_pp ... | KAPSAM DIŞI |
| `TestBrainMcp.test_notools_verdict_pure` (py/tests/test_steward_brain.py:231) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_recover_restarts_once_with_cooldown` (py/tests/test_steward_brain.py:249) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_mcp_server_heartbeat_hook` (py/tests/test_steward_brain.py:265) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainMcp.test_touch_records_call_and_connect` (py/tests/test_steward_brain.py:274) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_brain_spec_default_is_the_old_command_line` (py/tests/test_steward_brain.py:282) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_disabled_identity_never_starts_a_brain` (py/tests/test_steward_brain.py:289) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_enabled_identity_starts_its_own_brain` (py/tests/test_steward_brain.py:306) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_default_brain_start_is_unchanged` (py/tests/test_steward_brain.py:324) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestBrainStart.test_running_brain_is_not_started_twice` (py/tests/test_steward_brain.py:338) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::name_rules_edges ... | KAPSAM DIŞI |
| `TestBrainStart.test_brain_stop_uses_only_the_act_stop_path_with_the_exact_name` (py/tests/test_steward_brain.py:345) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestClaudeMcpConfigFile.test_identity_gets_its_own_config_file` (py/tests/test_steward_brain.py:353) | `parity.rs::parity_spawn` `-mcp`; `--steward <kimlik>` dosya adı | TAŞINDI |
| `TestMcpIdentity.test_default_server_adds_nothing` (py/tests/test_steward_brain.py:379) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestMcpIdentity.test_identity_server_adds_it_to_every_call_and_the_brain_cannot_change_it` (py/tests/test_steward_brain.py:390) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestMcpIdentity.test_run_validates_the_identity_and_sets_it` (py/tests/test_steward_brain.py:420) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::valid_custom_id_vectors ... | KAPSAM DIŞI |
| `TestMcpIdentity.test_cli_parses_the_flag` (py/tests/test_steward_brain.py:433) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestCtxFor.test_resolution` (py/tests/test_steward_brain.py:445) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::valid_custom_id_vectors ... | KAPSAM DIŞI |
| `TestCtxFor.test_unknown_identity_is_an_explicit_error_and_writes_nothing` (py/tests/test_steward_brain.py:456) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::p_pp, identity::paths_for_vectors ... | KAPSAM DIŞI |
| `TestCtxFor.test_no_param_means_default_and_old_callers_work` (py/tests/test_steward_brain.py:467) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestCtxFor.test_requests_reach_the_right_store` (py/tests/test_steward_brain.py:475) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestCtxFor.test_manual_tick_and_note_and_skip_use_the_identity` (py/tests/test_steward_brain.py:501) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_human_in_default_context_is_unrestricted` (py/tests/test_steward_brain.py:532) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_human_in_other_context_only_own_projects_and_brain` (py/tests/test_steward_brain.py:542) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_brain_in_identity_context` (py/tests/test_steward_brain.py:554) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TestHumanGate.test_reads_are_limited_to_own_projects_outside_default` (py/tests/test_steward_brain.py:563) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_project_roundtrip_and_validation` (py/tests/test_steward_core_a.py:56) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::build_ownership_index_vectors ... | KAPSAM DIŞI |
| `StoreTest.test_defer_answer_keeps_question_open` (py/tests/test_steward_core_a.py:67) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_questions_dedup_answer_deliver` (py/tests/test_steward_core_a.py:76) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_ideas_and_log` (py/tests/test_steward_core_a.py:88) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StoreTest.test_persona_override_and_bundled` (py/tests/test_steward_core_a.py:99) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_ask_ending_with_colon_takes_following_lines` (py/tests/test_steward_core_a.py:105) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_ignores_writing_examples` (py/tests/test_steward_core_a.py:117) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_ignores_inline_code_mention_in_prose` (py/tests/test_steward_core_a.py:126) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers_job_line` (py/tests/test_steward_core_a.py:135) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MarkerTest.test_scan_markers` (py/tests/test_steward_core_a.py:152) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `PromptTest.test_directive_by_phase_and_answer` (py/tests/test_steward_core_a.py:167) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors ... | KAPSAM DIŞI |
| `PromptTest.test_tour_prompt_lists_items_and_end_marker` (py/tests/test_steward_core_a.py:182) | rs/stew: rs-stew.md: prompts::build_tour_prompt_vectors, prompts::p_clip | KAPSAM DIŞI |
| `PromptTest.test_workspace_claude_md` (py/tests/test_steward_core_a.py:192) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `RulesTest.test_handover_then_respawn` (py/tests/test_steward_core_a.py:206) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_handover_grace_expiry_and_gone_session` (py/tests/test_steward_core_a.py:222) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_markers_once_per_reply` (py/tests/test_steward_core_a.py:230) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_done_marker_stops_session` (py/tests/test_steward_core_a.py:240) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_done_confirmed_with_open_owner_question_pauses_not_done` (py/tests/test_steward_core_a.py:244) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_done_marker_ignored_when_project_notes_have_no_done_tag` (py/tests/test_steward_core_a.py:255) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_due_projects_respect_slots_priority_and_cadence` (py/tests/test_steward_core_a.py:261) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_todo_change_opens_active_project_without_waiting_cadence` (py/tests/test_steward_core_a.py:274) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_todo_change_reopens_done_project_to_planned` (py/tests/test_steward_core_a.py:292) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_todo_change_paused_project_asks_owner_once_per_day` (py/tests/test_steward_core_a.py:303) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_first_observation_done_project_with_open_work_goes_planned` (py/tests/test_steward_core_a.py:318) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_daily_sweep_done_project_with_unchanged_sha` (py/tests/test_steward_core_a.py:327) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_daily_sweep_paused_asks_once` (py/tests/test_steward_core_a.py:339) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_only_fable_cila_open_work_does_not_trigger` (py/tests/test_steward_core_a.py:347) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_drain_starts_nothing_but_keeps_answers_and_running` (py/tests/test_steward_core_a.py:354) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_slot_pressure_stops_idle_session` (py/tests/test_steward_core_a.py:361) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_answer_delivery_running_busy_or_stopped` (py/tests/test_steward_core_a.py:372) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_adhoc_session_answer_goes_to_asking_session_only_if_running` (py/tests/test_steward_core_a.py:382) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_instance_sessions_map_to_blueprint_project` (py/tests/test_steward_core_a.py:394) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_tour_only_when_brain_idle_and_due` (py/tests/test_steward_core_a.py:400) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RulesTest.test_phase_model_effort` (py/tests/test_steward_core_a.py:416) | rs/stew: rs-stew.md: prompts::phase_model_effort_vectors | KAPSAM DIŞI |
| `CardCoreTest.test_build_raw_card_reads_doc_heads_and_git` (py/tests/test_steward_core_a.py:424) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `CardCoreTest.test_raw_card_without_git_or_docs` (py/tests/test_steward_core_a.py:440) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `CardCoreTest.test_parse_card_json_variants` (py/tests/test_steward_core_a.py:452) | rs/stew: rs-stew.md: cards::p_short, cards::p_str_list, cards::parse_card_json_vectors, prompts::p_clip | KAPSAM DIŞI |
| `CardCoreTest.test_make_card_falls_back_to_raw_fields` (py/tests/test_steward_core_a.py:465) | rs/stew: rs-stew.md: cards::p_goal_from_docs, cards::p_short, cards::p_tbd_lines ... | KAPSAM DIŞI |
| `CardCoreTest.test_refresh_reason_matrix_and_failure_backoff` (py/tests/test_steward_core_a.py:483) | rs/stew: rs-stew.md: cards::card_path_vectors, cards::card_refresh_reason_vectors, cards::p_short ... | KAPSAM DIŞI |
| `CardCoreTest.test_store_stale_and_listing` (py/tests/test_steward_core_a.py:506) | rs/stew: rs-stew.md: cards::card_one_liner_vectors, cards::card_path_vectors, identity::name_rules_edges ... | KAPSAM DIŞI |
| `CardCoreTest.test_model_pick_prompt_and_tour_rendering` (py/tests/test_steward_core_a.py:517) | rs/stew: rs-stew.md: cards::build_card_prompt_vectors, cards::p_short, cards::pick_card_model_vectors ... | KAPSAM DIŞI |
| `OneshotProviderTest.test_claude_argv_shape_and_unsupported_default` (py/tests/test_steward_core_a.py:534) | `parity.rs::parity_build` `oneshot`; varsayılan "desteklenmiyor" dahil | TAŞINDI |
| `OneshotProviderTest.test_ucli_oneshot_uses_chat_once_without_key_in_argv` (py/tests/test_steward_core_a.py:560) | yok | EKSİK(G10) |
| `OneshotProviderTest.test_oneshot_runs_argv_and_reports_failures` (py/tests/test_steward_core_a.py:579) | yok | EKSİK(G10) |
| `SimilarAnswersTest.test_ranks_by_similarity_and_excludes_self` (py/tests/test_steward_core_a.py:604) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SimilarAnswersTest.test_open_or_unanswered_ignored_and_prompt_renders` (py/tests/test_steward_core_a.py:613) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RosterGateTest.test_active_phase_needs_roster_but_idea_does_not` (py/tests/test_steward_core_a.py:622) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ScanCacheTest.test_scan_is_cached_inside_a_scope_and_invalidated_by_start` (py/tests/test_steward_core_a.py:636) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EngineSmallsTest.test_fail_logged_is_pruned_and_thread_safe` (py/tests/test_steward_core_a.py:663) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EngineSmallsTest.test_shutdown_blockers_survive_corrupt_jobs_file` (py/tests/test_steward_core_a.py:673) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownOnlyLeavesPausedTest.test_done_records_left_paused_and_warns` (py/tests/test_steward_core_a.py:685) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainCannotPauseTest.test_brain_cannot_pause_or_done_but_owner_can` (py/tests/test_steward_core_a.py:705) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownPlanTest.test_waits_for_quiet_then_handover_then_stop_then_brain` (py/tests/test_steward_core_a.py:721) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownPlanTest.test_subagent_blocks_and_timeouts_leave_session_open` (py/tests/test_steward_core_a.py:749) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownPlanTest.test_stale_ready_text_before_handover_does_not_count` (py/tests/test_steward_core_a.py:762) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReviewFindings20261029Test.test_job_requests_for_different_files_are_not_merged` (py/tests/test_steward_core_a.py:773) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReviewFindings20261029Test.test_done_and_plan_ready_in_prose_are_ignored` (py/tests/test_steward_core_a.py:779) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `ReviewFindings20261029Test.test_owner_only_false_positives` (py/tests/test_steward_core_a.py:787) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_paraphrased_open_question_is_merged` (py/tests/test_steward_core_a.py:798) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_other_project_or_topic_not_merged` (py/tests/test_steward_core_a.py:808) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_short_distinct_questions_not_merged` (py/tests/test_steward_core_a.py:814) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_routine_question_promoted_when_asked_to_owner` (py/tests/test_steward_core_a.py:819) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OpenQuestionMergeTest.test_answered_question_not_merged_into_open_path` (py/tests/test_steward_core_a.py:834) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_topic_tokens` (py/tests/test_steward_core_a.py:851) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_generic_names_alone_do_not_match` (py/tests/test_steward_core_a.py:856) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_open_question_rephrased_is_merged_and_keeps_old_text` (py/tests/test_steward_core_a.py:861) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_hold_answer_suppresses_same_topic` (py/tests/test_steward_core_a.py:873) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_non_hold_answer_lets_new_decision_open` (py/tests/test_steward_core_a.py:880) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_old_open_question_outside_window_not_merged` (py/tests/test_steward_core_a.py:887) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TopicMergeTest.test_other_project_not_merged` (py/tests/test_steward_core_a.py:895) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SalientReaskTest.test_paraphrased_same_topic_is_duplicate` (py/tests/test_steward_core_a.py:905) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SalientReaskTest.test_different_topic_not_duplicate` (py/tests/test_steward_core_a.py:910) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneDeferralTest.test_done_deferred_while_subagent_then_applied` (py/tests/test_steward_core_a.py:916) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneDeferralTest.test_deferred_done_dropped_when_no_done_tag_added_later` (py/tests/test_steward_core_a.py:927) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneDeferralTest.test_done_immediate_without_subagent` (py/tests/test_steward_core_a.py:938) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AnswerStartPhaseTest.test_active_phase_starts` (py/tests/test_steward_core_a.py:952) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AnswerStartPhaseTest.test_owner_answer_reopens_paused_and_done_project` (py/tests/test_steward_core_a.py:955) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_is_negative_answer` (py/tests/test_steward_core_a.py:963) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_negative_answer_does_not_reopen` (py/tests/test_steward_core_a.py:975) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_hold_answers_real_texts_do_not_reopen` (py/tests/test_steward_core_a.py:980) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `NegativeAnswerTest.test_sweep_question_has_options` (py/tests/test_steward_core_a.py:991) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_long_owner_instruction_reaches_brain` (py/tests/test_steward_core_a.py:1018) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_second_held_instruction_gets_its_own_item` (py/tests/test_steward_core_a.py:1027) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_later_question_does_not_overwrite_held_item` (py/tests/test_steward_core_a.py:1032) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HeldInstructionAnswerTest.test_short_hold_brain_and_routine_answers_stay_silent` (py/tests/test_steward_core_a.py:1039) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_done_hands_over_then_stops_never_respawns` (py/tests/test_steward_core_a.py:1063) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_session_gone_during_done_handover_is_not_respawned` (py/tests/test_steward_core_a.py:1074) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_grace_expiry_still_stops` (py/tests/test_steward_core_a.py:1080) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_small_context_skips_handover` (py/tests/test_steward_core_a.py:1087) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_switch_off_is_old_direct_stop` (py/tests/test_steward_core_a.py:1095) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_owner_answer_stops_reasking_and_bitti_closes` (py/tests/test_steward_core_a.py:1101) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_unknown_open_work_symlinked_worktree_accepts_proof` (py/tests/test_steward_core_a.py:1115) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneHandoverTest.test_unanswered_conflict_still_asks` (py/tests/test_steward_core_a.py:1122) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_plain_done_asks_for_confirmation_and_keeps_phase` (py/tests/test_steward_core_a.py:1139) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_second_plain_done_does_not_spam_but_ttl_reasks` (py/tests/test_steward_core_a.py:1147) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirmed_with_evidence_sets_done_and_stops` (py/tests/test_steward_core_a.py:1155) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirmed_without_evidence_is_not_done` (py/tests/test_steward_core_a.py:1160) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirmed_but_local_open_work_asks_owner_not_done` (py/tests/test_steward_core_a.py:1166) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_no_steward_done_tag_ignores_both_markers` (py/tests/test_steward_core_a.py:1178) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_confirm_marker_is_not_plain_done_and_placeholder_ignored` (py/tests/test_steward_core_a.py:1184) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `DoneConfirmTest.test_subagent_active_defers_confirmed` (py/tests/test_steward_core_a.py:1192) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_open_work_of_counts_local_todo` (py/tests/test_steward_core_a.py:1197) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DoneConfirmTest.test_open_tbd_of_falls_back_to_main_worktree` (py/tests/test_steward_core_a.py:1212) | rs/stew: rs-stew.md: markers::count_open_tbd_edges, markers::count_open_tbd_vectors | KAPSAM DIŞI |
| `TourQuietTest.test_skipped_unchanged_item_stays_out_until_state_changes_or_ttl` (py/tests/test_steward_core_a.py:1242) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_plan_tick_records_tour_sig_and_honors_skip_seen` (py/tests/test_steward_core_a.py:1256) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_stale_undelivered_answer_closed_not_toured` (py/tests/test_steward_core_a.py:1270) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_projectless_answer_closes_when_brain_never_runs` (py/tests/test_steward_core_a.py:1285) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_brain_question_answer_goes_to_live_session_named_by_project` (py/tests/test_steward_core_a.py:1299) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_keepwarm_ok_does_not_change_the_item_signature_and_routine_carries_age` (py/tests/test_steward_core_a.py:1309) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_observe_tour_does_not_burn_blocked_tour_budget` (py/tests/test_steward_core_a.py:1323) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_pending_count_is_the_full_list_even_when_a_tour_is_sent` (py/tests/test_steward_core_a.py:1339) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_count_open_tbd_new_format_needs_an_AÇIK_heading` (py/tests/test_steward_core_a.py:1350) | rs/stew: rs-stew.md: markers::count_open_tbd_edges, markers::count_open_tbd_vectors | KAPSAM DIŞI |
| `TourQuietTest.test_shutdown_unknown_activity_waits_unless_idle` (py/tests/test_steward_core_a.py:1356) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourQuietTest.test_blocked_item_closed_after_max_tours_not_urgent_again` (py/tests/test_steward_core_a.py:1364) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `IdleSkipTest.test_no_idle_item_for_waiting_or_done_projects` (py/tests/test_steward_core_a.py:1389) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MergedAnswersTest.test_planner_merges_same_session_answers_in_one_action` (py/tests/test_steward_core_a.py:1405) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MergedAnswersTest.test_answer_waits_while_subagent_active` (py/tests/test_steward_core_a.py:1413) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MergedAnswersTest.test_subagent_active_for_reads_mtime` (py/tests/test_steward_core_a.py:1421) | yok: transkript yolu + mtime; rs-stew.md EKSİK | EKSİK(G1) |
| `MergedAnswersTest.test_compact_answer_directive_drops_preamble` (py/tests/test_steward_core_a.py:1438) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors ... | KAPSAM DIŞI |
| `MergedAnswersTest.test_directive_contains_all_answers` (py/tests/test_steward_core_a.py:1454) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors ... | KAPSAM DIŞI |
| `ScanTicksTest.test_leading_code_tick_in_question_kept` (py/tests/test_steward_core_b.py:56) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `ScanTicksTest.test_wrapped_marker_and_wrapped_body` (py/tests/test_steward_core_b.py:60) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `PlanMarkersTest.test_records_asks_and_ideas_only` (py/tests/test_steward_core_b.py:71) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PlanMarkersTest.test_same_reply_not_rescanned_and_routine_needs_question_mark` (py/tests/test_steward_core_b.py:77) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PlanMarkersTest.test_matches_plan_tick_marker_actions` (py/tests/test_steward_core_b.py:84) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ObserveCoreTest.test_filter_act_passes_everything_and_clears_traces` (py/tests/test_steward_core_b.py:93) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ObserveCoreTest.test_filter_observe_splits_dedups_and_prunes` (py/tests/test_steward_core_b.py:100) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ObserveCoreTest.test_observed_visit_paces_due_projects_across_ticks` (py/tests/test_steward_core_b.py:117) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_daily_summary_counts_and_filters_by_date` (py/tests/test_steward_core_b.py:138) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_summary_due` (py/tests/test_steward_core_b.py:171) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_log_reader_and_summary_text` (py/tests/test_steward_core_b.py:179) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_compact_log_folds_ticks_and_keeps_summary_identical` (py/tests/test_steward_core_b.py:195) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SummaryCoreTest.test_missed_summary_dates_and_catch_up` (py/tests/test_steward_core_b.py:236) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RoutineQuestionTest.test_marker_scan_and_session_reply_opens_routine_ask` (py/tests/test_steward_core_b.py:277) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RoutineQuestionTest.test_routine_goes_to_brain_tour_not_phone_and_escalates_late` (py/tests/test_steward_core_b.py:288) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RoutineQuestionTest.test_brain_answer_is_delivered_like_any_answer` (py/tests/test_steward_core_b.py:313) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_finished_handover_of_second_session_stops_it_instead_of_respawn` (py/tests/test_steward_core_b.py:320) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_economy_rules_only_touch_managed_sessions` (py/tests/test_steward_core_b.py:333) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_brain_respawn_after_handover_is_a_new_conversation` (py/tests/test_steward_core_b.py:346) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_context_tokens_trigger_handover` (py/tests/test_steward_core_b.py:354) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_line_count_is_only_a_fallback_and_ignores_young_sessions` (py/tests/test_steward_core_b.py:369) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_workspace_claude_md_carries_the_permanent_model_rule` (py/tests/test_steward_core_b.py:392) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_fable_sessions_use_the_lower_context_threshold` (py/tests/test_steward_core_b.py:401) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `OneLiveSessionPerProjectTest.test_context_tokens_from_transcript_tail` (py/tests/test_steward_core_b.py:417) | yok: transkript kuyruğundan bağlam; rs-stew.md EKSİK | EKSİK(G3) |
| `StuckBrainTest.test_status_sentence_is_not_a_routine_question_and_tour_is_capped` (py/tests/test_steward_core_b.py:436) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StuckBrainTest.test_two_failed_tours_restart_the_brain` (py/tests/test_steward_core_b.py:449) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StuckBrainTest.test_undeliverable_adhoc_answer_is_given_up` (py/tests/test_steward_core_b.py:464) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DeliveryTargetTest.test_prefers_asking_session_then_main_over_experiment_sessions` (py/tests/test_steward_core_b.py:477) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_similar_answered_question_is_redelivered_not_reopened` (py/tests/test_steward_core_b.py:500) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_repeat_cap_other_project_old_and_clarification_open_new` (py/tests/test_steward_core_b.py:510) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_answered_routine_question_asked_to_owner_opens_new` (py/tests/test_steward_core_b.py:521) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ReaskTest.test_directive_lists_earlier_answers` (py/tests/test_steward_core_b.py:531) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `QuestionOptionsTest.test_options_normalize_resolve_and_key` (py/tests/test_steward_core_b.py:542) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `QuestionOptionsTest.test_notification_text_and_page_html` (py/tests/test_steward_core_b.py:571) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SettingsTest.test_defaults_parse_and_clamp` (py/tests/test_steward_core_b.py:596) | rs/stew: rs-stew.md: identity::name_rules_edges, identity::valid_steward_id_vectors | KAPSAM DIŞI |
| `McpTest.test_tools_list_and_dispatch_cover_each_other` (py/tests/test_steward_core_b.py:619) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `McpTest.test_tool_calls_hit_expected_endpoints` (py/tests/test_steward_core_b.py:631) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobMarkerParseTest.test_hyphenated_kind_and_malformed_body_are_not_dropped` (py/tests/test_steward_core_b.py:653) | rs/stew: rs-stew.md: markers::p_bare_marker, markers::p_unwrap_ticks, markers::scan_markers_corpus ... | KAPSAM DIŞI |
| `JobMarkerParseTest.test_prose_mentions_and_placeholders_still_ignored` (py/tests/test_steward_core_b.py:659) | rs/stew: rs-stew.md: markers::p_unwrap_ticks, markers::scan_markers_corpus, markers::scan_markers_vectors | KAPSAM DIŞI |
| `QuestionPageHttpTest.test_question_page_round_trip` (py/tests/test_steward_core_b.py:693) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `QuestionPageHttpTest.test_notify_phone_sets_click_header` (py/tests/test_steward_core_b.py:716) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_non_routine_question_is_owner_only` (py/tests/test_steward_core_b.py:743) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_routine_owner_only_topics` (py/tests/test_steward_core_b.py:749) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_commit_push_merge_build_deploy_are_not_owner_only` (py/tests/test_steward_core_b.py:756) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_blocked_marker_goes_to_brain_not_owner` (py/tests/test_steward_core_b.py:763) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_rules_text_no_longer_reserves_commit_push_for_owner` (py/tests/test_steward_core_b.py:768) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_readonly_job_request_not_owner_only` (py/tests/test_steward_core_b.py:773) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_plain_routine_is_answerable` (py/tests/test_steward_core_b.py:784) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_defer_reason` (py/tests/test_steward_core_b.py:788) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainAuthorityAndDeferTest.test_tour_retry_gap_after_deferral` (py/tests/test_steward_core_b.py:794) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourDeliveryTest.test_short_tour_inline` (py/tests/test_steward_core_b.py:799) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `TourDeliveryTest.test_long_tour_goes_to_file_and_old_files_pruned` (py/tests/test_steward_core_b.py:805) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownKeepModeTest.test_keep_does_not_stop` (py/tests/test_steward_core_b.py:831) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownKeepModeTest.test_default_stops` (py/tests/test_steward_core_b.py:836) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownOnlyTest.test_only_closes_selected_project_and_leaves_rest` (py/tests/test_steward_core_b.py:845) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownBlockersTest.test_quiet_session_without_blocker_gets_handover` (py/tests/test_steward_core_b.py:868) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownBlockersTest.test_blocked_session_waits_and_records_reason` (py/tests/test_steward_core_b.py:872) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ShutdownBlockersTest.test_blocked_session_left_open_after_wait_max` (py/tests/test_steward_core_b.py:879) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_count_open_tbd` (py/tests/test_steward_core_b.py:893) | rs/stew: rs-stew.md: markers::count_open_tbd_edges, markers::count_open_tbd_vectors | KAPSAM DIŞI |
| `SmartTickTest.test_routine_question_skips_tour_interval` (py/tests/test_steward_core_b.py:898) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_done_confirmed_with_open_tbd_asks_owner` (py/tests/test_steward_core_b.py:913) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_tbd_only_project_not_started_owner_asked_once` (py/tests/test_steward_core_b.py:925) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_brain_stopped_project_not_restarted_by_cadence_until_cooldown` (py/tests/test_steward_core_b.py:935) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SmartTickTest.test_idle_session_without_open_todo_not_nudged` (py/tests/test_steward_core_b.py:947) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AskStatusLineTests.test_status_lines_do_not_open_records` (py/tests/test_steward_core_b.py:960) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `AskBaseTests.test_dated_session_name_collapses_to_base` (py/tests/test_steward_core_b.py:970) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DeferAnswerTests.test_is_defer_answer` (py/tests/test_steward_core_b.py:981) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DeferAnswerTests.test_digest_hides_deferred_until_expiry` (py/tests/test_steward_core_b.py:987) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `StartDecisionEventTests.test_event_shape` (py/tests/test_steward_core_b.py:995) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ExpiredHandoverNoteTest.test_note_helper` (py/tests/test_steward_core_b.py:1007) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ExpiredHandoverNoteTest.test_expired_without_marker_carries_note` (py/tests/test_steward_core_b.py:1021) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ExpiredHandoverNoteTest.test_ready_marker_has_no_card_note` (py/tests/test_steward_core_b.py:1026) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliStuckLadderTest.test_shorten_helper` (py/tests/test_steward_core_b.py:1040) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliStuckLadderTest.test_ladder` (py/tests/test_steward_core_b.py:1047) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `RemoteRespawnNoteTest.test_note_reaches_directive` (py/tests/test_steward_core_b.py:1074) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `RemoteRespawnNoteTest.test_no_note_keeps_empty_directive` (py/tests/test_steward_core_b.py:1079) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `ContextQuestionTest.test_classifier` (py/tests/test_steward_ctx.py:71) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_low_context_continues_without_handover` (py/tests/test_steward_ctx.py:76) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_high_context_hands_over` (py/tests/test_steward_ctx.py:86) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_unknown_context_or_disabled_leaves_question` (py/tests/test_steward_ctx.py:95) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ContextQuestionTest.test_over_threshold_single_handover` (py/tests/test_steward_ctx.py:101) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_paused_over_threshold_sends_no_handover_on_any_tick` (py/tests/test_steward_ctx.py:119) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_done_project_also_gets_no_threshold_handover` (py/tests/test_steward_ctx.py:127) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_planned_project_still_hands_over_at_threshold` (py/tests/test_steward_ctx.py:131) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `PausedProjectNoContextHandoverTest.test_context_question_on_paused_project_does_not_start_a_handover` (py/tests/test_steward_ctx.py:136) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_pure_decision` (py/tests/test_steward_ctx.py:158) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_subagent_active_defers_then_hands_over_when_quiet` (py/tests/test_steward_ctx.py:172) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_busy_and_unknown_defer` (py/tests/test_steward_ctx.py:195) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_history_fallback_defers_too` (py/tests/test_steward_ctx.py:206) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_force_by_ratio` (py/tests/test_steward_ctx.py:212) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_force_by_time` (py/tests/test_steward_ctx.py:222) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_defer_disabled_keeps_old_behaviour` (py/tests/test_steward_ctx.py:234) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_below_threshold_drops_deferral` (py/tests/test_steward_ctx.py:240) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_brain_same_rule` (py/tests/test_steward_ctx.py:246) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_no_second_action_while_deferred` (py/tests/test_steward_ctx.py:257) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_context_question_path_defers` (py/tests/test_steward_ctx.py:267) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HandoverDeferTest.test_engine_logs_deferral` (py/tests/test_steward_ctx.py:282) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `HttpTest.test_idea_export_project_todo_hides_idea_and_keeps_record` (py/tests/test_steward_http.py:99) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_idea_export_all_tbd_and_idempotent` (py/tests/test_steward_http.py:113) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_idea_export_appends_under_existing_heading_and_validates` (py/tests/test_steward_http.py:123) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_running_names_resolve_digit_in_project_name` (py/tests/test_steward_http.py:143) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_project_ask_answer_idea_note` (py/tests/test_steward_http.py:156) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_ask_with_options_notifies_with_link_once` (py/tests/test_steward_http.py:177) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_question_page_auth_and_answer_flow` (py/tests/test_steward_http.py:201) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_register_creates_folder_goal_and_roster` (py/tests/test_steward_http.py:229) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_tick_applies_actions_with_mocked_views` (py/tests/test_steward_http.py:252) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_refresh_card_writes_summary_and_logs` (py/tests/test_steward_http.py:290) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_refresh_card_failure_keeps_old_card_or_writes_raw` (py/tests/test_steward_http.py:303) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_refresh_due_cards_rules` (py/tests/test_steward_http.py:326) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_tick_runs_card_step_unless_disabled` (py/tests/test_steward_http.py:349) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_respawn_marks_card_stale` (py/tests/test_steward_http.py:365) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_cards_in_context_projects_and_api` (py/tests/test_steward_http.py:378) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_observe_tick_records_would_and_touches_nothing` (py/tests/test_steward_http.py:421) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_observe_still_runs_questions_ideas_and_phase_changes` (py/tests/test_steward_http.py:443) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_act_mode_applies_and_logs_actions` (py/tests/test_steward_http.py:461) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_brain_calls_are_dry_in_observe_but_cli_calls_apply` (py/tests/test_steward_http.py:470) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_brain_cannot_touch_unregistered_session` (py/tests/test_steward_http.py:502) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_brain_may_touch_brain_and_registered_projects` (py/tests/test_steward_http.py:529) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_apply_gate_denies_engine_actions_on_unregistered_sessions` (py/tests/test_steward_http.py:545) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_daily_summary_runs_once_after_hour_and_notifies` (py/tests/test_steward_http.py:558) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_summary_api_and_cli` (py/tests/test_steward_http.py:584) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `HttpTest.test_handover_route_marks_pending` (py/tests/test_steward_http.py:609) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_gate_pure` (py/tests/test_steward_http.py:622) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_brain_bare_devam_rejected_owner_allowed` (py/tests/test_steward_http.py:634) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_brain_red_closes_and_opens_owner_question` (py/tests/test_steward_http.py:642) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_red_feedback_to_project_session_and_no_repeat_owner_question` (py/tests/test_steward_http.py:654) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_job_kinds_list_shapes` (py/tests/test_steward_http.py:678) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `JobRequestGateTest.test_brain_answer_after_submit_ok` (py/tests/test_steward_http.py:686) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SkipMemoryHttpTest.test_skip_records_signature_from_last_tour` (py/tests/test_steward_http.py:693) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `SkipMemoryHttpTest.test_close_stale_answer_action_marks_delivered` (py/tests/test_steward_http.py:701) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ActionJournalTest.test_crash_between_state_save_and_apply_replays_once` (py/tests/test_steward_http.py:716) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ActionJournalTest.test_normal_tick_leaves_no_journal_and_no_duplicates` (py/tests/test_steward_http.py:734) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ActionJournalTest.test_replay_skips_duplicate_idea` (py/tests/test_steward_http.py:743) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_report_counts_and_window` (py/tests/test_steward_http.py:765) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_ask_due_only_known_kip_after_72h_once` (py/tests/test_steward_http.py:777) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_maybe_dry_ask_opens_one_question_and_not_again` (py/tests/test_steward_http.py:788) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `DryReportTest.test_no_ask_when_kip_already_act` (py/tests/test_steward_http.py:798) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainWakeGateTest.test_brain_directive_capped_per_day_separately_from_due` (py/tests/test_steward_http.py:808) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BrainWakeGateTest.test_brain_gate_dry_logs_would_and_sends` (py/tests/test_steward_http.py:820) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeGateTest.test_first_send_never_gated_then_repeat_dry_logs_but_sends_act_skips` (py/tests/test_steward_http.py:836) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeGateTest.test_gate_is_skipped_when_the_directive_just_opened_the_session` (py/tests/test_steward_http.py:847) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeGateTest.test_other_text_other_reason_answer_off_and_window` (py/tests/test_steward_http.py:869) | rs/stew: rs-stew.md: identity::p_pp, identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `BigResumeTest.test_oversized_detection` (py/tests/test_steward_http.py:904) | yok: resume çözümü; karar T10, rs-stew.md EKSİK | EKSİK(G1) |
| `BigResumeTest.test_small_unknown_other_cli_and_off_keep_resume` (py/tests/test_steward_http.py:908) | yok: resume çözümü; karar T10, rs-stew.md EKSİK | EKSİK(G1) |
| `BigResumeTest.test_ensure_running_starts_fresh_for_big_context` (py/tests/test_steward_http.py:919) | yok: resume çözümü; karar T10, rs-stew.md EKSİK | EKSİK(G1) |
| `WakeCapPanicTest.test_daily_cap_dry_and_act_and_reset_on_answer` (py/tests/test_steward_http.py:935) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `WakeCapPanicTest.test_panic_flag_forces_observe_and_blocks_brain_directive` (py/tests/test_steward_http.py:952) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_blocked_waits_four_hours_routine_thirty_minutes` (py/tests/test_steward_http.py:982) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_owner_only_denial_escalates_routine_immediately` (py/tests/test_steward_http.py:989) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_owner_only_denial_blocks_brain_directive_until_answered` (py/tests/test_steward_http.py:997) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_owner_pending_block_pure` (py/tests/test_steward_http.py:1016) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BlockedEscalationTest.test_protocol_and_guide_derive_from_owner_topics` (py/tests/test_steward_http.py:1023) | rs/stew: rs-stew.md: prompts::build_workspace_claude_md_vectors, prompts::identity_section_vectors | KAPSAM DIŞI |
| `UcliSendTest.test_ucli_text_folded_not_truncated` (py/tests/test_steward_ucli_send.py:31) | yok: `prepare_input` yok; gönderim T10 | EKSİK(G4) |
| `UcliSendTest.test_non_ucli_untouched_and_no_recheck` (py/tests/test_steward_ucli_send.py:41) | yok: `prepare_input` yok; gönderim T10 | EKSİK(G4) |
| `UcliSendTest.test_claude_trust_dialog_blocks_send` (py/tests/test_steward_ucli_send.py:48) | rs/stew: rs-stew.md: identity::brain_name_for_vectors, identity::build_ownership_index_vectors ... | KAPSAM DIŞI |
| `UcliSendTest.test_text_left_in_box_sends_one_more_enter` (py/tests/test_steward_ucli_send.py:56) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_still_stuck_logs_error` (py/tests/test_steward_ucli_send.py:66) | rs/stew: rs-stew.md: identity::paths_for_vectors, identity::paths_layout_and_errors | KAPSAM DIŞI |
| `UcliSendTest.test_stuck_event_uses_caller_sid` (py/tests/test_steward_ucli_send.py:74) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_every_steward_send_call_passes_sid` (py/tests/test_steward_ucli_send.py:82) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_late_drawn_text_gets_enter` (py/tests/test_steward_ucli_send.py:92) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `UcliSendTest.test_empty_box_no_extra_enter` (py/tests/test_steward_ucli_send.py:103) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_prefixed_empty_prompt` (py/tests/test_steward_ucli_send.py:118) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_prefixed_with_text` (py/tests/test_steward_ucli_send.py:121) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_text_wrapped_over_two_lines` (py/tests/test_steward_ucli_send.py:124) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_waiting_for_response_is_empty` (py/tests/test_steward_ucli_send.py:128) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_turn_output_after_prompt_is_empty` (py/tests/test_steward_ucli_send.py:131) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_last_prompt_line_wins` (py/tests/test_steward_ucli_send.py:134) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `BoxTextTest.test_no_prompt` (py/tests/test_steward_ucli_send.py:137) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `ClaudeSidForStoppedSessionTests.test_own_conversation_wins_over_a_newer_sibling_stub` (py/tests/test_stopped_session_chat.py:80) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_each_sibling_resolves_to_its_own_file` (py/tests/test_stopped_session_chat.py:86) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_same_title_prefers_the_real_conversation_over_a_newer_stub` (py/tests/test_stopped_session_chat.py:95) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_same_title_picks_the_newest_real_conversation_even_when_it_is_the_smaller_one` (py/tests/test_stopped_session_chat.py:101) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_all_stubs_returns_the_newest_one` (py/tests/test_stopped_session_chat.py:107) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_a_large_file_counts_as_real_without_being_scanned` (py/tests/test_stopped_session_chat.py:112) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_no_title_match_returns_none` (py/tests/test_stopped_session_chat.py:119) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_title_is_an_exact_match_not_a_prefix` (py/tests/test_stopped_session_chat.py:123) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_untitled_files_never_match` (py/tests/test_stopped_session_chat.py:127) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_missing_project_dir_and_empty_name_return_none` (py/tests/test_stopped_session_chat.py:131) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_file_recording_a_different_cwd_is_ignored` (py/tests/test_stopped_session_chat.py:136) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_finds_a_file_older_than_the_resume_scan_limit` (py/tests/test_stopped_session_chat.py:141) | yok | EKSİK(G1) |
| `ClaudeSidForStoppedSessionTests.test_unchanged_files_are_not_reread_but_changed_ones_are` (py/tests/test_stopped_session_chat.py:149) | yok | EKSİK(G1) |
| `TermChatWiringTests.test_stopped_session_shows_its_own_full_history_not_the_newest_stub` (py/tests/test_stopped_session_chat.py:177) | yok | EKSİK(G2) |
| `TermChatWiringTests.test_stopped_session_last_exchange_is_its_own` (py/tests/test_stopped_session_chat.py:182) | yok | EKSİK(G2) |
| `TermChatWiringTests.test_incremental_since_still_works_on_the_resolved_conversation` (py/tests/test_stopped_session_chat.py:186) | yok | EKSİK(G2) |
| `TermChatWiringTests.test_unmatched_stopped_session_keeps_the_old_newest_in_cwd_behavior` (py/tests/test_stopped_session_chat.py:192) | yok | EKSİK(G2) |
| `TermChatWiringTests.test_live_session_never_consults_the_name_lookup` (py/tests/test_stopped_session_chat.py:200) | yok | EKSİK(G2) |
| `TermChatWiringTests.test_live_session_without_sid_is_left_alone_too` (py/tests/test_stopped_session_chat.py:207) | yok | EKSİK(G2) |
| `TermChatWiringTests.test_unsupported_cli_still_reports_supported_false` (py/tests/test_stopped_session_chat.py:214) | yok | EKSİK(G2) |
| `OtherProvidersTests.test_default_providers_do_not_guess` (py/tests/test_stopped_session_chat.py:220) | yok | EKSİK(G1) |
| `OtherProvidersTests.test_agy_uses_the_learned_name_to_sid_map_when_the_db_exists` (py/tests/test_stopped_session_chat.py:224) | yok | EKSİK(G1) |
| `OtherProvidersTests.test_ucli_sid_is_the_session_name` (py/tests/test_stopped_session_chat.py:237) | yok | EKSİK(G1) |
| `UcliChatTests.test_schema_header_row_is_skipped` (py/tests/test_stopped_session_chat.py:258) | yok | EKSİK(G2) |
| `UcliChatTests.test_header_only_file_means_no_messages_yet_not_unsupported` (py/tests/test_stopped_session_chat.py:263) | yok | EKSİK(G2) |
| `UcliChatTests.test_old_files_without_a_header_still_parse` (py/tests/test_stopped_session_chat.py:267) | yok | EKSİK(G2) |
| `UcliChatTests.test_corrupt_files_are_still_reported_as_unreadable` (py/tests/test_stopped_session_chat.py:271) | yok | EKSİK(G2) |
| `UcliChatTests.test_missing_file_is_an_empty_history` (py/tests/test_stopped_session_chat.py:277) | yok | EKSİK(G2) |
| `UcliChatTests.test_stopped_ucli_instance_chat_is_served_through_term_chat` (py/tests/test_stopped_session_chat.py:280) | yok | EKSİK(G2) |
| `RecoverStuckTest.test_uses_parent_aware_kill` (py/tests/test_stuck_kills_parent.py:13) | T4: `stuck.py` kurtarma akışı | KAPSAM DIŞI |
| `RecoverStuckTest.test_unknown_permission_uses_provider_default` (py/tests/test_stuck_kills_parent.py:28) | T4: `stuck.py` kurtarma akışı | KAPSAM DIŞI |
| `RecoverStuckTest.test_dry_run_kills_nothing` (py/tests/test_stuck_kills_parent.py:40) | T4: `stuck.py` kurtarma akışı | KAPSAM DIŞI |
| `RecoverStuckTest.test_recovery_uses_live_model_and_effort_not_spawn_argv` (py/tests/test_stuck_kills_parent.py:46) | yok | EKSİK(G3) |
| `TokenTests.test_concurrent_issue_keeps_file_and_digest_consistent` (py/tests/test_ucli_agents.py:29) | yok | EKSİK(G8) |
| `TokenTests.test_issue_writes_0600_file_and_only_hash_in_registry` (py/tests/test_ucli_agents.py:48) | yok | EKSİK(G8) |
| `TokenTests.test_reissue_invalidates_old_token_and_revoke_clears` (py/tests/test_ucli_agents.py:56) | yok | EKSİK(G8) |
| `TokenTests.test_children_get_no_token_and_garbage_rejected` (py/tests/test_ucli_agents.py:65) | yok | EKSİK(G8) |
| `TokenTests.test_revoke_unsafe_name_does_not_touch_files` (py/tests/test_ucli_agents.py:71) | yok | EKSİK(G8) |
| `ReserveTests.test_limit_two_live_and_names_sequential` (py/tests/test_ucli_agents.py:80) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ReserveTests.test_taken_names_skipped_and_depth_one` (py/tests/test_ucli_agents.py:91) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ReserveTests.test_fold_text` (py/tests/test_ucli_agents.py:97) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `SettingsTests.test_defaults` (py/tests/test_ucli_agents.py:108) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `SettingsTests.test_off_and_cost` (py/tests/test_ucli_agents.py:113) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `ProviderSetupTests.test_no_port_or_child_or_off_gives_nothing` (py/tests/test_ucli_agents.py:136) | `parity.rs::parity_ucli` `ajan-port-yok` `ajan-cocuk` `ajan-kapali` | TAŞINDI |
| `ProviderSetupTests.test_unsupported_binary_gives_nothing` (py/tests/test_ucli_agents.py:145) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `ProviderSetupTests.test_enabled_returns_flag_and_env_without_token_value` (py/tests/test_ucli_agents.py:151) | `parity.rs::parity_ucli` `ajan-acik` `ajan-anahtarli` | TAŞINDI |
| `ProviderSetupTests.test_build_inner_command_keeps_token_out_of_argv` (py/tests/test_ucli_agents.py:161) | `parity.rs::parity_ucli` `ajan-acik` `ajan-anahtarli` | TAŞINDI |
| `ApprovalExecTest.test_suspended_registered` (py/tests/test_ucli_approval_exec.py:34) | yok | EKSİK(G10) |
| `ApprovalExecTest.test_75_without_suspended_line_is_error` (py/tests/test_ucli_approval_exec.py:45) | yok | EKSİK(G10) |
| `ApprovalExecTest.test_bad_run_key` (py/tests/test_ucli_approval_exec.py:49) | yok | EKSİK(G10) |
| `ApprovalExecTest.test_opts_validation` (py/tests/test_ucli_approval_exec.py:53) | `parity.rs::parity_ucli` `approval` `askdir` | TAŞINDI |
| `ResumeTest.test_resume_done_and_argv_from_record` (py/tests/test_ucli_approval_exec.py:71) | yok | EKSİK(G10) |
| `ResumeTest.test_resume_chain_and_double_resume` (py/tests/test_ucli_approval_exec.py:83) | yok | EKSİK(G10) |
| `ResumeTest.test_resume_error_recorded` (py/tests/test_ucli_approval_exec.py:93) | yok | EKSİK(G10) |
| `ResumeTest.test_list_runs_owner_filter_hides_argv` (py/tests/test_ucli_approval_exec.py:100) | yok | EKSİK(G10) |
| `ResumeTest.test_recover_resuming` (py/tests/test_ucli_approval_exec.py:106) | yok | EKSİK(G10) |
| `ResumeTest.test_authz_resource_and_action` (py/tests/test_ucli_approval_exec.py:114) | yok | EKSİK(G10) |
| `AskDirTest.test_opts_default_off_and_ambiguous` (py/tests/test_ucli_ask_dir.py:27) | `parity.rs::parity_ucli` `approval-askdir` `askdir` | TAŞINDI |
| `AskDirTest.test_argv_has_private_dir_outside_workspace` (py/tests/test_ucli_ask_dir.py:33) | `parity.rs::parity_ucli` `askdir-var` | TAŞINDI |
| `AskDirTest.test_unsupported_binary_or_no_name_is_error` (py/tests/test_ucli_ask_dir.py:40) | `parity.rs::parity_ucli` `eksik-checks` `askdir-adsiz2` | TAŞINDI |
| `AskDirTest.test_pending_and_answer_roundtrip_and_stale_id` (py/tests/test_ucli_ask_dir.py:46) | T7: `/api/ucli/ask` soru/cevap okuyucusu | KAPSAM DIŞI |
| `AskDirTest.test_bad_names_rejected` (py/tests/test_ucli_ask_dir.py:58) | `parity.rs::parity_ucli` `askdir-gecersiz-ad` `askdir-uzun` | TAŞINDI |
| `AskDirTest.test_broken_question_file_is_none` (py/tests/test_ucli_ask_dir.py:63) | T7: `/api/ucli/ask` soru/cevap okuyucusu | KAPSAM DIŞI |
| `ValidateMaxCostTests.test_valid_values` (py/tests/test_ucli_brain_mcp.py:53) | `parity.rs::parity_ucli` `cost` | TAŞINDI |
| `ValidateMaxCostTests.test_zero_or_empty_drops_the_key` (py/tests/test_ucli_brain_mcp.py:59) | `parity.rs::parity_ucli` `cost` | TAŞINDI |
| `ValidateMaxCostTests.test_invalid_values_rejected` (py/tests/test_ucli_brain_mcp.py:63) | `parity.rs::parity_ucli` `cost` | TAŞINDI |
| `MaxCostArgsTests.test_priced_model_gets_the_flag_once` (py/tests/test_ucli_brain_mcp.py:89) | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` | TAŞINDI |
| `MaxCostArgsTests.test_unpriced_model_is_skipped_and_logged` (py/tests/test_ucli_brain_mcp.py:95) | `parity.rs::parity_ucli` `opts-cost-fiyatli` `opts-cost-fiyatsiz` | TAŞINDI |
| `MaxCostArgsTests.test_binary_without_flag_is_skipped` (py/tests/test_ucli_brain_mcp.py:100) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `McpRegisterTests.test_server_name_follows_ucli_rule` (py/tests/test_ucli_brain_mcp.py:113) | `parity.rs::parity_misc` `ucli-misc` ; `parity.rs::parity_ucli` `ucli-mcp-ad` | TAŞINDI |
| `McpRegisterTests.test_add_argv_shape` (py/tests/test_ucli_brain_mcp.py:118) | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `McpRegisterTests.test_launch_args_register_then_with_mcp` (py/tests/test_ucli_brain_mcp.py:124) | `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `McpRegisterTests.test_failed_add_means_no_with_mcp` (py/tests/test_ucli_brain_mcp.py:144) | `parity.rs::parity_ucli` `ucli-mcp-`; `Probe::register_mcp` sahte (G8) | TAŞINDI |
| `McpRegisterTests.test_nothing_runs_without_tools_workspace_or_flag` (py/tests/test_ucli_brain_mcp.py:152) | `parity.rs::parity_ucli` `ucli-mcp-aracsiz` `ucli-mcp-` | TAŞINDI |
| `McpRegisterTests.test_symlinked_state_dir_is_refused` (py/tests/test_ucli_brain_mcp.py:165) | `parity.rs::parity_ucli` `ucli-symlink` | TAŞINDI |
| `McpRegisterTests.test_steward_spec_allowlists_exactly_the_steward_tools` (py/tests/test_ucli_brain_mcp.py:176) | T10: `mcp_steward` araç listesi | KAPSAM DIŞI |
| `BuildWithMcpTests.test_only_with_mcp_is_taken_from_extra_args` (py/tests/test_ucli_brain_mcp.py:204) | `parity.rs::parity_ucli` `with-mcp` `with-mcp-yok` | TAŞINDI |
| `BuildWithMcpTests.test_claude_service_with_cost_cap_and_mcp` (py/tests/test_ucli_brain_mcp.py:210) | `parity.rs::parity_ucli` `hizmet-claude`; günlük tavan sahte (G8) | TAŞINDI |
| `SpawnCwdWiringTests.test_cwd_only_for_providers_that_ask` (py/tests/test_ucli_brain_mcp.py:245) | `parity.rs::parity_spawn` `-mcp` ; `parity.rs::parity_ucli` `ucli-mcp-` | TAŞINDI |
| `SpawnCwdWiringTests.test_dry_run_preview_shows_env_and_command_not_priority_prefix` (py/tests/test_ucli_brain_mcp.py:265) | `parity.rs::parity_spawn` `-dry` | TAŞINDI |
| `SpawnCwdWiringTests.test_dry_run_preview_masks_secret_env_values` (py/tests/test_ucli_brain_mcp.py:271) | `parity.rs::parity_spawn` `preview` | TAŞINDI |
| `SpawnCwdWiringTests.test_dry_run_preview_caps_very_long_command` (py/tests/test_ucli_brain_mcp.py:277) | `parity.rs::parity_spawn` `preview-uzun` | TAŞINDI |
| `BrainUcliTests.test_default_claude_brain_passes_no_cli_opts` (py/tests/test_ucli_brain_mcp.py:284) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_ucli_brain_uses_claude_service_and_cost_cap` (py/tests/test_ucli_brain_mcp.py:291) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_settings_override_service_model_and_cap` (py/tests/test_ucli_brain_mcp.py:303) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_defaults` (py/tests/test_ucli_brain_mcp.py:312) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_unknown_service_refuses_without_spawn` (py/tests/test_ucli_brain_mcp.py:319) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_spawn_refusal_is_reported_not_raised` (py/tests/test_ucli_brain_mcp.py:326) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BrainUcliTests.test_claude_brain_value_error_still_raises` (py/tests/test_ucli_brain_mcp.py:332) | T10: değnekçi beyni açılışı | KAPSAM DIŞI |
| `BroadGlobTests.test_broad_rejected_without_accept` (py/tests/test_ucli_broad_glob_and_instr_check.py:19) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_broad_accepted_with_accept` (py/tests/test_ucli_broad_glob_and_instr_check.py:26) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_narrow_glob_has_no_accept_flag` (py/tests/test_ucli_broad_glob_and_instr_check.py:33) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_always_rejected_even_when_accepted` (py/tests/test_ucli_broad_glob_and_instr_check.py:38) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_forbidden_cmds_never_open` (py/tests/test_ucli_broad_glob_and_instr_check.py:42) | `parity.rs::parity_ucli` `glob-` | TAŞINDI |
| `BroadGlobTests.test_grant_logged_in_apply` (py/tests/test_ucli_broad_glob_and_instr_check.py:46) | `parity.rs::parity_ucli` `glob-genis-kabul` | TAŞINDI |
| `InstructionsCheckTests.test_sizes` (py/tests/test_ucli_broad_glob_and_instr_check.py:62) | yok | EKSİK(G11) |
| `InstructionsCheckTests.test_exact_limit_not_over` (py/tests/test_ucli_broad_glob_and_instr_check.py:71) | yok | EKSİK(G11) |
| `InstructionsCheckTests.test_no_files_and_bad_cwd` (py/tests/test_ucli_broad_glob_and_instr_check.py:76) | yok | EKSİK(G11) |
| `InstructionsCheckTests.test_symlink_escape_ignored` (py/tests/test_ucli_broad_glob_and_instr_check.py:82) | yok | EKSİK(G11) |
| `InstructionsCheckTests.test_no_content_returned` (py/tests/test_ucli_broad_glob_and_instr_check.py:88) | yok | EKSİK(G11) |
| `CapabilityFlagsTest.test_default_off` (py/tests/test_ucli_capability_flags.py:27) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `CapabilityFlagsTest.test_image_scholar_independent_of_exec` (py/tests/test_ucli_capability_flags.py:36) | `parity.rs::parity_ucli` `yetenek` | TAŞINDI |
| `CapabilityFlagsTest.test_false_values_dropped` (py/tests/test_ucli_capability_flags.py:43) | `ucli_opts.rs::is_unset`; sınanmayan senaryo: `allow_image`/`allow_scholar` için yanlış değerler (aynı yardımcı `git-hayir` ile sınanıyor) | TAŞINDI-TESTSİZ |
| `CapabilityFlagsTest.test_invalid_value_is_error` (py/tests/test_ucli_capability_flags.py:48) | `parity.rs::parity_ucli` `bayrak-gecersiz` | TAŞINDI |
| `CapabilityFlagsTest.test_net_and_unbounded_exec_own_not_offered` (py/tests/test_ucli_capability_flags.py:54) | `parity.rs::parity_misc` `val` | TAŞINDI |
| `CapabilityFlagsTest.test_ask_edit_needs_write` (py/tests/test_ucli_capability_flags.py:62) | `parity.rs::parity_ucli` `ask-edit-yazmasiz` `ask-edit` | TAŞINDI |
| `CapabilityFlagsTest.test_exec_argv` (py/tests/test_ucli_capability_flags.py:69) | `parity.rs::parity_ucli` `toolchain-uygula` | TAŞINDI |
| `CapabilityFlagsTest.test_unsupported_binary_refuses` (py/tests/test_ucli_capability_flags.py:76) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `CapabilityFlagsTest.test_unsupported_but_off_no_error` (py/tests/test_ucli_capability_flags.py:84) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `AskEditWithoutExecTest.test_ask_edit_added_only_with_allow_edit` (py/tests/test_ucli_capability_flags.py:96) | `parity.rs::parity_ucli` `opts-ask-edit-exec-yok` | TAŞINDI |
| `CheckpointFlagTest.test_default_off` (py/tests/test_ucli_checkpoint_flag.py:21) | `ucli_opts.rs::is_unset`; sınanmayan senaryo: `checkpoint` yanlış değerleri/varsayılanı için ayrı vaka | TAŞINDI-TESTSİZ |
| `CheckpointFlagTest.test_false_values_dropped` (py/tests/test_ucli_checkpoint_flag.py:27) | `ucli_opts.rs::is_unset`; sınanmayan senaryo: `checkpoint` yanlış değerleri/varsayılanı için ayrı vaka | TAŞINDI-TESTSİZ |
| `CheckpointFlagTest.test_true_accepted` (py/tests/test_ucli_checkpoint_flag.py:33) | `parity.rs::parity_ucli` `bayraklar` `bayrak-gecersiz` | TAŞINDI |
| `CheckpointFlagTest.test_ambiguous_is_error` (py/tests/test_ucli_checkpoint_flag.py:38) | `parity.rs::parity_ucli` `bayraklar` `bayrak-gecersiz` | TAŞINDI |
| `CheckpointFlagTest.test_argv_added_once` (py/tests/test_ucli_checkpoint_flag.py:42) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `CheckpointFlagTest.test_unsupported_binary_skipped_not_rejected` (py/tests/test_ucli_checkpoint_flag.py:46) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `Validate.test_off_by_default_and_dropped` (py/tests/test_ucli_checks_opts.py:19) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Validate.test_restricted_ok_max_defaults_to_mode` (py/tests/test_ucli_checks_opts.py:24) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Validate.test_errors` (py/tests/test_ucli_checks_opts.py:29) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Validate.test_full_needs_accept_risk` (py/tests/test_ucli_checks_opts.py:33) | `parity.rs::parity_ucli` `checks-` | TAŞINDI |
| `Registry.test_missing_loose_mode_and_shape` (py/tests/test_ucli_checks_opts.py:55) | yok | EKSİK(G8) |
| `Registry.test_symlink_rejected` (py/tests/test_ucli_checks_opts.py:66) | yok | EKSİK(G8) |
| `Apply.test_flags_added` (py/tests/test_ucli_checks_opts.py:90) | `parity.rs::parity_ucli` `checks-uygula` | TAŞINDI |
| `Apply.test_full_adds_accept_risk` (py/tests/test_ucli_checks_opts.py:97) | `parity.rs::parity_ucli` `checks-uygula` | TAŞINDI |
| `Apply.test_full_refused_when_binary_only_knows_restricted` (py/tests/test_ucli_checks_opts.py:101) | `parity.rs::parity_ucli` `checks-deger-tanimsiz` | TAŞINDI |
| `Apply.test_unsupported_binary_refused` (py/tests/test_ucli_checks_opts.py:111) | `parity.rs::parity_ucli` `eksik-checks` | TAŞINDI |
| `Apply.test_needs_state_dir_and_registry` (py/tests/test_ucli_checks_opts.py:115) | `parity.rs::parity_ucli` `checks-statedir-yok` `checks-kayit-hata` | TAŞINDI |
| `RefusalTests.test_cap_refusal_has_code_and_amounts` (py/tests/test_ucli_cost_cap_refusal.py:13) | yok: `DailyCapExceeded` ve ret biçimi yok | EKSİK(G8) |
| `RefusalTests.test_plain_value_error_has_no_code` (py/tests/test_ucli_cost_cap_refusal.py:18) | yok: `DailyCapExceeded` ve ret biçimi yok | EKSİK(G8) |
| `ProviderRaisesTests.test_claude_service_flags_raises_over_cap` (py/tests/test_ucli_cost_cap_refusal.py:25) | yok: `DailyCapExceeded` ve ret biçimi yok | EKSİK(G8) |
| `DefaultPermissionMode.test_ucli_panel_default_is_allow_edit_and_listed` (py/tests/test_ucli_default_permission_mode.py:12) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultPermissionMode.test_ucli_server_internal_default_stays_read_only` (py/tests/test_ucli_default_permission_mode.py:17) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `DefaultPermissionMode.test_other_providers_keep_auto` (py/tests/test_ucli_default_permission_mode.py:21) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `ReasoningModeTests.test_unset_empty_and_unknown_values_mean_auto` (py/tests/test_ucli_effort.py:105) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_off_words_switch_it_off` (py/tests/test_ucli_effort.py:111) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_a_named_level_forces_that_level_case_insensitively` (py/tests/test_ucli_effort.py:116) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_a_non_dict_ucli_limits_is_tolerated` (py/tests/test_ucli_effort.py:121) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `ReasoningModeTests.test_it_does_not_leak_into_the_numeric_overrides` (py/tests/test_ucli_effort.py:125) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `CatalogTests.test_only_chat_models_are_listed_and_their_capabilities_kept` (py/tests/test_ucli_effort.py:147) | `parity.rs::parity_misc` `live` | TAŞINDI |
| `CatalogTests.test_a_failed_or_empty_fetch_keeps_the_previous_map` (py/tests/test_ucli_effort.py:155) | yok | EKSİK(G7) |
| `CatalogTests.test_without_a_key_nothing_is_fetched` (py/tests/test_ucli_effort.py:164) | yok | EKSİK(G7) |
| `CatalogTests.test_model_choices_and_the_effort_gate_share_one_fetch` (py/tests/test_ucli_effort.py:170) | yok | EKSİK(G7) |
| `ReasoningEffortForTests.test_a_model_that_declares_support_gets_the_level` (py/tests/test_ucli_effort.py:186) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_gemma_which_rejects_the_field_gets_nothing` (py/tests/test_ucli_effort.py:190) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_an_unknown_model_or_an_empty_catalog_gets_nothing` (py/tests/test_ucli_effort.py:195) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_a_malformed_capabilities_entry_is_tolerated` (py/tests/test_ucli_effort.py:200) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `ReasoningEffortForTests.test_an_allowed_values_list_restricts_the_level_unless_aliased` (py/tests/test_ucli_effort.py:208) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `EffortArgsTests.test_a_capable_model_and_a_new_binary_get_the_session_preset` (py/tests/test_ucli_effort.py:219) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `EffortArgsTests.test_off_is_silent_and_sends_nothing` (py/tests/test_ucli_effort.py:225) | `parity.rs::parity_ucli` `ayar-reasoning-` | TAŞINDI |
| `EffortArgsTests.test_a_named_level_overrides_the_preset_but_not_the_model_gate` (py/tests/test_ucli_effort.py:231) | `parity.rs::parity_ucli` `ayar-reasoning-` | TAŞINDI |
| `EffortArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` (py/tests/test_ucli_effort.py:237) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `EffortArgsTests.test_a_model_that_rejects_the_field_is_skipped_and_logged` (py/tests/test_ucli_effort.py:243) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `EffortArgsTests.test_no_model_and_a_missing_binary_give_nothing_instead_of_raising` (py/tests/test_ucli_effort.py:249) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_the_preset_name_rides_along_as_the_last_flag` (py/tests/test_ucli_effort.py:280) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_an_unknown_or_empty_effort_falls_back_to_medium_for_the_flag_too` (py/tests/test_ucli_effort.py:284) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_gemma_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:290) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:294) | `parity.rs::parity_ucli` `eski-ikili` | TAŞINDI |
| `BuildInnerCommandTests.test_off_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:298) | `parity.rs::parity_ucli` `ayar-reasoning-` | TAŞINDI |
| `BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` (py/tests/test_ucli_effort.py:302) | `parity.rs::parity_ucli` `anahtar-yaz` | TAŞINDI |
| `BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` (py/tests/test_ucli_effort.py:308) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` (py/tests/test_ucli_effort.py:318) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` (py/tests/test_ucli_effort.py:325) | rs/prov: gereksiz: teslim edilen gerçek ucli ikilisini sınar | KAPSAM DIŞI |
| `UcliEndpointTest.test_default_is_evren` (py/tests/test_ucli_endpoint.py:23) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `UcliEndpointTest.test_custom_valid_endpoint_wins_and_trailing_slash_dropped` (py/tests/test_ucli_endpoint.py:27) | `parity.rs::parity_ucli` `ayar-endpoint` `endpoint-gecersiz` ; `parity.rs::parity_settings_pyfmt` `endpoint` | TAŞINDI |
| `UcliEndpointTest.test_invalid_endpoint_falls_back_and_empty_clears` (py/tests/test_ucli_endpoint.py:31) | `parity.rs::parity_ucli` `ayar-endpoint` `endpoint-gecersiz` ; `parity.rs::parity_settings_pyfmt` `endpoint` | TAŞINDI |
| `UcliEndpointTest.test_model_list_fetch_uses_configured_endpoint` (py/tests/test_ucli_endpoint.py:40) | yok | EKSİK(G7) |
| `EvrenNoDefaultCapTest.test_evren_has_no_default_cap` (py/tests/test_ucli_evren_no_default_cap.py:18) | `parity.rs::parity_ucli` `hizmet-evren` | TAŞINDI |
| `EvrenNoDefaultCapTest.test_explicit_cap_on_evren_still_passes` (py/tests/test_ucli_evren_no_default_cap.py:22) | `parity.rs::parity_ucli` `ham-service-evren` | TAŞINDI |
| `ExecToolchainTests.test_only_rust_is_accepted` (py/tests/test_ucli_exec_toolchain.py:17) | `parity.rs::parity_ucli` `toolchain-baska` `toolchain` | TAŞINDI |
| `ExecToolchainTests.test_missing_toolchain_is_an_error_not_a_silent_skip` (py/tests/test_ucli_exec_toolchain.py:22) | `parity.rs::parity_ucli` `toolchain-yok` | TAŞINDI |
| `ExecToolchainTests.test_flags_use_real_binaries_and_only_allowed_env` (py/tests/test_ucli_exec_toolchain.py:28) | yok: gerçek `rust_toolchain` keşfi yok; bayraklar `parity_misc` `exec` | EKSİK(G8) |
| `ExecToolchainTests.test_no_toolchain_means_old_flags_unchanged` (py/tests/test_ucli_exec_toolchain.py:46) | `parity.rs::parity_misc` `exec` | TAŞINDI |
| `ExecToolchainTests.test_path_in_exec_cmds_is_still_rejected` (py/tests/test_ucli_exec_toolchain.py:53) | `parity.rs::parity_ucli` `cmds-yol` | TAŞINDI |
| `FailedTurnsTests.test_no_directory_or_no_record_is_none_not_zero` (py/tests/test_ucli_failed_turns.py:28) | yok | EKSİK(G6) |
| `FailedTurnsTests.test_counts_this_session_only_and_reports_the_newest_error` (py/tests/test_ucli_failed_turns.py:33) | yok | EKSİK(G6) |
| `FailedTurnsTests.test_a_broken_or_errorless_record_still_counts` (py/tests/test_ucli_failed_turns.py:42) | yok | EKSİK(G6) |
| `FailedTurnsTests.test_dict_error_uses_its_message` (py/tests/test_ucli_failed_turns.py:46) | yok | EKSİK(G6) |
| `FailedTurnsTests.test_no_sid_is_none` (py/tests/test_ucli_failed_turns.py:50) | yok | EKSİK(G6) |
| `FailedTurnsTests.test_web_wrapper_never_raises` (py/tests/test_ucli_failed_turns.py:53) | yok | EKSİK(G6) |
| `FailedTurnsTests.test_other_cli_has_no_failed_turns` (py/tests/test_ucli_failed_turns.py:58) | yok | EKSİK(G6) |
| `ForbiddenCmds.test_interpreters_rejected_by_name` (py/tests/test_ucli_forbidden_cmds.py:10) | `parity.rs::parity_misc` `ucli-misc` ; `parity.rs::parity_ucli` `cmds-kabuk` `cmds-python3` | TAŞINDI |
| `ForbiddenCmds.test_is_forbidden_cmd` (py/tests/test_ucli_forbidden_cmds.py:16) | `parity.rs::parity_misc` `ucli-misc` ; `parity.rs::parity_ucli` `cmds-kabuk` `cmds-python3` | TAŞINDI |
| `ArchiveTest.test_moves_history_and_status_keeps_others` (py/tests/test_ucli_fresh_handover.py:31) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `ArchiveTest.test_second_archive_does_not_overwrite` (py/tests/test_ucli_fresh_handover.py:43) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `ArchiveTest.test_nothing_to_move_and_bad_names` (py/tests/test_ucli_fresh_handover.py:50) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `StartFreshTest.test_fresh_ucli_archives` (py/tests/test_ucli_fresh_handover.py:72) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `StartFreshTest.test_not_fresh_or_not_ucli_or_running_does_not` (py/tests/test_ucli_fresh_handover.py:75) | T4: `archive_session_files` ve taze açılış akışı | KAPSAM DIŞI |
| `HandoverGateTest.test_ucli_handover_sends_message` (py/tests/test_ucli_fresh_handover.py:82) | yok | EKSİK(G4) |
| `ValidateTests.test_default_off` (py/tests/test_ucli_git_flags.py:21) | `parity.rs::parity_ucli` `git` | TAŞINDI |
| `ValidateTests.test_on_independent_of_each_other_and_exec` (py/tests/test_ucli_git_flags.py:26) | `parity.rs::parity_ucli` `git` | TAŞINDI |
| `ValidateTests.test_garbage_is_error` (py/tests/test_ucli_git_flags.py:32) | `parity.rs::parity_ucli` `git` | TAŞINDI |
| `ArgvTests.test_no_flags_by_default` (py/tests/test_ucli_git_flags.py:39) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `ArgvTests.test_only_requested_flag` (py/tests/test_ucli_git_flags.py:44) | `parity.rs::parity_ucli` `eksik` `git` | TAŞINDI |
| `ArgvTests.test_both_no_duplicates` (py/tests/test_ucli_git_flags.py:52) | `parity.rs::parity_ucli` `eksik` `git` | TAŞINDI |
| `ArgvTests.test_unsupported_binary_refuses` (py/tests/test_ucli_git_flags.py:57) | `parity.rs::parity_ucli` `eksik` `git` | TAŞINDI |
| `ArgvTests.test_unsupported_irrelevant_when_off` (py/tests/test_ucli_git_flags.py:61) | `parity.rs::parity_ucli` `opts-bos` `eski-ikili` | TAŞINDI |
| `InstructionsFlagsTest.test_default_off` (py/tests/test_ucli_instructions_flags.py:21) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `InstructionsFlagsTest.test_valid` (py/tests/test_ucli_instructions_flags.py:30) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_zero_and_empty_dropped` (py/tests/test_ucli_instructions_flags.py:36) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_invalid` (py/tests/test_ucli_instructions_flags.py:42) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_argv` (py/tests/test_ucli_instructions_flags.py:49) | `parity.rs::parity_ucli` `bayraklar` `int` | TAŞINDI |
| `InstructionsFlagsTest.test_unsupported_binary_skips` (py/tests/test_ucli_instructions_flags.py:54) | `ucli.rs::Ctx::apply_cli_opts`; sınanmayan senaryo: `--instructions-*` bayrağını tanımayan ikili | TAŞINDI-TESTSİZ |
| `InteractiveArgsTest.test_supported_adds_flag` (py/tests/test_ucli_interactive_flag.py:12) | `parity.rs::parity_ucli` `eksik` `temel-` | TAŞINDI |
| `InteractiveArgsTest.test_unsupported_skips_and_logs` (py/tests/test_ucli_interactive_flag.py:16) | `parity.rs::parity_ucli` `eksik` `temel-` | TAŞINDI |
| `UcliKeyPathTest.test_default_and_service` (py/tests/test_ucli_key_path.py:14) | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `UcliKeyPathTest.test_callers_share_helper` (py/tests/test_ucli_key_path.py:19) | `parity.rs::parity_ucli` `anahtar-` `hizmet-` | TAŞINDI |
| `LastExchangePairingTest.test_pending_user_turn_has_empty_assistant` (py/tests/test_ucli_last_exchange_pairing.py:17) | yok | EKSİK(G2) |
| `LastExchangePairingTest.test_answered_turn_pairs_normally` (py/tests/test_ucli_last_exchange_pairing.py:22) | yok | EKSİK(G2) |
| `LastExchangePairingTest.test_assistant_only_and_empty` (py/tests/test_ucli_last_exchange_pairing.py:26) | yok | EKSİK(G2) |
| `ValidateTests.test_empty_and_zero_drop_key` (py/tests/test_ucli_limit_flags.py:30) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_ints_accepted` (py/tests/test_ucli_limit_flags.py:36) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_ints_invalid_are_errors` (py/tests/test_ucli_limit_flags.py:41) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_bools` (py/tests/test_ucli_limit_flags.py:48) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_price_two_and_four` (py/tests/test_ucli_limit_flags.py:55) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ValidateTests.test_price_invalid` (py/tests/test_ucli_limit_flags.py:59) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ArgvTests.test_nothing_by_default` (py/tests/test_ucli_limit_flags.py:67) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `ArgvTests.test_int_flags_with_values` (py/tests/test_ucli_limit_flags.py:74) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ArgvTests.test_price_and_bools` (py/tests/test_ucli_limit_flags.py:80) | `parity.rs::parity_ucli` `int` `bayraklar` `price` | TAŞINDI |
| `ArgvTests.test_unsupported_flag_is_skipped_not_fatal` (py/tests/test_ucli_limit_flags.py:86) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `ArgvTests.test_only_supported_ones_added` (py/tests/test_ucli_limit_flags.py:90) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `LiveContext.test_bytes_over_four` (py/tests/test_ucli_live_context.py:16) | yok | EKSİK(G6) |
| `LiveContext.test_zero_is_zero` (py/tests/test_ucli_live_context.py:19) | yok | EKSİK(G6) |
| `LiveContext.test_unknown_cases_are_none` (py/tests/test_ucli_live_context.py:22) | yok | EKSİK(G6) |
| `LiveContext.test_reader_error_is_none` (py/tests/test_ucli_live_context.py:30) | yok | EKSİK(G6) |
| `MaxSessionUsd.test_valid_kept_as_float` (py/tests/test_ucli_max_session_usd.py:10) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `MaxSessionUsd.test_zero_and_empty_dropped` (py/tests/test_ucli_max_session_usd.py:14) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `MaxSessionUsd.test_invalid_rejected` (py/tests/test_ucli_max_session_usd.py:18) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `MaxSessionUsd.test_independent_of_per_turn_cap` (py/tests/test_ucli_max_session_usd.py:24) | `parity.rs::parity_ucli` `session` `cost` | TAŞINDI |
| `DefaultCap.test_default_is_8_and_configurable` (py/tests/test_ucli_max_session_usd.py:35) | `parity.rs::parity_settings_pyfmt` `usd` | TAŞINDI |
| `DefaultCap.test_provider_uses_default_when_record_has_none` (py/tests/test_ucli_max_session_usd.py:43) | `parity.rs::parity_ucli` `hizmet-grok-tavan-ayar` `hizmet-grok` | TAŞINDI |
| `MetricsFileArgs.test_on_and_supported` (py/tests/test_ucli_metrics_file_arg.py:22) | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-` | TAŞINDI |
| `MetricsFileArgs.test_off_unsupported_nameless` (py/tests/test_ucli_metrics_file_arg.py:27) | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-` | TAŞINDI |
| `MetricsFileArgs.test_name_sanitised` (py/tests/test_ucli_metrics_file_arg.py:32) | `parity.rs::parity_ucli` `ayar-metrics-off` `eksik` `temel-` | TAŞINDI |
| `FlattenTest.test_ucli_flattens` (py/tests/test_ucli_multiline_flatten.py:15) | yok | EKSİK(G4) |
| `FlattenTest.test_ucli_single_line_unchanged` (py/tests/test_ucli_multiline_flatten.py:19) | yok | EKSİK(G4) |
| `FlattenTest.test_ucli_trailing_newline` (py/tests/test_ucli_multiline_flatten.py:23) | yok | EKSİK(G4) |
| `FlattenTest.test_ucli_tab_single_line` (py/tests/test_ucli_multiline_flatten.py:26) | yok | EKSİK(G4) |
| `FlattenTest.test_ucli_long_text_not_truncated` (py/tests/test_ucli_multiline_flatten.py:29) | yok | EKSİK(G4) |
| `FlattenTest.test_single_fold_point_in_callers` (py/tests/test_ucli_multiline_flatten.py:37) | yok | EKSİK(G4) |
| `FlattenTest.test_other_providers_untouched` (py/tests/test_ucli_multiline_flatten.py:44) | yok | EKSİK(G4) |
| `LivePhaseTests.test_a_streaming_phase_comes_through` (py/tests/test_ucli_phase.py:36) | yok | EKSİK(G6) |
| `LivePhaseTests.test_the_last_write_time_of_the_file_comes_through_as_last_unix` (py/tests/test_ucli_phase.py:41) | yok | EKSİK(G6) |
| `LivePhaseTests.test_a_missing_or_garbage_last_activity_is_left_out_not_zeroed` (py/tests/test_ucli_phase.py:46) | yok | EKSİK(G6) |
| `LivePhaseTests.test_a_retry_phase_keeps_its_reason` (py/tests/test_ucli_phase.py:54) | yok | EKSİK(G6) |
| `LivePhaseTests.test_no_phase_a_null_phase_or_an_older_binary_mean_none` (py/tests/test_ucli_phase.py:60) | yok | EKSİK(G6) |
| `LivePhaseTests.test_a_phase_without_a_usable_name_is_ignored` (py/tests/test_ucli_phase.py:67) | yok | EKSİK(G6) |
| `LivePhaseTests.test_bad_numbers_are_dropped_never_turned_into_an_invented_zero` (py/tests/test_ucli_phase.py:73) | yok | EKSİK(G6) |
| `LivePhaseTests.test_text_is_trimmed_and_capped` (py/tests/test_ucli_phase.py:79) | yok | EKSİK(G6) |
| `LivePhaseTests.test_a_future_phase_name_passes_through_so_the_badge_does_not_go_silent` (py/tests/test_ucli_phase.py:85) | yok | EKSİK(G6) |
| `LivePhaseTests.test_only_the_known_fields_are_returned` (py/tests/test_ucli_phase.py:89) | yok | EKSİK(G6) |
| `LivePhaseTests.test_no_status_file_no_sid_or_a_broken_file_mean_none` (py/tests/test_ucli_phase.py:93) | yok | EKSİK(G6) |
| `LivePhaseTests.test_every_other_provider_has_no_phase` (py/tests/test_ucli_phase.py:101) | yok | EKSİK(G6) |
| `LivePhaseHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` (py/tests/test_ucli_phase.py:122) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_waiting_for_the_response_turns_amber_then_red_on_the_thresholds` (py/tests/test_ucli_phase.py:127) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_retries_and_rate_limits_are_always_amber` (py/tests/test_ucli_phase.py:133) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_model_that_is_thinking_or_writing_is_progress_not_a_warning` (py/tests/test_ucli_phase.py:139) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_stream_that_goes_quiet_turns_amber_then_red_and_progress_stays_green` (py/tests/test_ucli_phase.py:145) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_long_running_stream_that_keeps_writing_is_not_a_warning` (py/tests/test_ucli_phase.py:154) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_idle_is_reported_but_does_not_decide_the_waiting_colour` (py/tests/test_ucli_phase.py:159) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_without_a_last_write_time_a_stream_has_no_idle_and_no_warning` (py/tests/test_ucli_phase.py:163) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_the_internal_last_unix_is_not_leaked_to_the_wire` (py/tests/test_ucli_phase.py:167) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_the_providers_dict_is_not_mutated` (py/tests/test_ucli_phase.py:171) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_missing_since_unix_means_no_elapsed_and_no_warning` (py/tests/test_ucli_phase.py:176) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_since_in_the_future_never_gives_a_negative_elapsed` (py/tests/test_ucli_phase.py:180) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_no_phase_means_none` (py/tests/test_ucli_phase.py:184) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LivePhaseHelperTests.test_a_failing_provider_never_breaks_the_panel` (py/tests/test_ucli_phase.py:188) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_a_registered_running_ucli_row_carries_its_phase` (py/tests/test_ucli_phase.py:226) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait` (py/tests/test_ucli_phase.py:231) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_a_frozen_stream_row_goes_amber_from_the_file_write_time` (py/tests/test_ucli_phase.py:235) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadPhaseTests.test_a_stopped_row_and_a_phaseless_provider_have_no_phase` (py/tests/test_ucli_phase.py:242) | T1: panel faz rozeti ve durum satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LimitOverridesTests.test_the_timeout_is_a_valid_override_as_a_string_or_a_number` (py/tests/test_ucli_request_timeout.py:62) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `LimitOverridesTests.test_unset_empty_and_invalid_values_fall_back_to_the_default` (py/tests/test_ucli_request_timeout.py:66) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `LimitOverridesTests.test_the_other_overrides_are_unaffected` (py/tests/test_ucli_request_timeout.py:72) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `TimeoutArgsTests.test_a_binary_that_knows_the_flag_gets_the_600_second_default` (py/tests/test_ucli_request_timeout.py:78) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `TimeoutArgsTests.test_the_settings_override_replaces_the_default` (py/tests/test_ucli_request_timeout.py:84) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `TimeoutArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` (py/tests/test_ucli_request_timeout.py:88) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `TimeoutArgsTests.test_a_missing_binary_gets_nothing_instead_of_raising` (py/tests/test_ucli_request_timeout.py:94) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `BuildInnerCommandTests.test_the_default_command_ends_with_the_600_second_timeout` (py/tests/test_ucli_request_timeout.py:123) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_the_settings_override_reaches_the_command` (py/tests/test_ucli_request_timeout.py:126) | `parity.rs::parity_ucli` `ayar-limit` `temel-` | TAŞINDI |
| `BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_request_timeout.py:132) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` (py/tests/test_ucli_request_timeout.py:136) | `parity.rs::parity_ucli` `anahtar-yaz` | TAŞINDI |
| `BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` (py/tests/test_ucli_request_timeout.py:142) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` (py/tests/test_ucli_request_timeout.py:152) | rs/proc: `extract_info`/`matches_proc` gidiş dönüşü `cops-procscan/src/providers.rs` (`ucli_effort_presets`, `detect`); komut tarafı `parity_ucli` `temel-` | KAPSAM DIŞI |
| `RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` (py/tests/test_ucli_request_timeout.py:159) | rs/prov: gereksiz: teslim edilen gerçek ucli ikilisini sınar | KAPSAM DIŞI |
| `OwnCopyLocationTests.test_own_copy_lives_in_the_repo_bin_directory_and_is_named_ucli` (py/tests/test_ucli_resolve_binary.py:32) | `ucli.rs::resolve_binary`; sınanmayan senaryo: depo içi `bin/ucli` var/yok senaryosu (fixture depo dizinine yazamıyor) | TAŞINDI-TESTSİZ |
| `OwnCopyLocationTests.test_a_session_started_from_the_own_copy_is_still_recognised_as_ucli` (py/tests/test_ucli_resolve_binary.py:38) | rs/proc: `providers.rs::detect` | KAPSAM DIŞI |
| `ResolveBinaryTests.test_own_copy_beats_path_and_the_sibling_builds` (py/tests/test_ucli_resolve_binary.py:79) | `ucli.rs::resolve_binary`; sınanmayan senaryo: depo içi `bin/ucli` var/yok senaryosu (fixture depo dizinine yazamıyor) | TAŞINDI-TESTSİZ |
| `ResolveBinaryTests.test_path_beats_the_sibling_builds_when_there_is_no_own_copy` (py/tests/test_ucli_resolve_binary.py:85) | `ucli.rs::resolve_binary`; sınanmayan senaryo: kaynaklar birlikteyken öncelik sırası (`ru-` vakaları tek tek) | TAŞINDI-TESTSİZ |
| `ResolveBinaryTests.test_sibling_release_is_preferred_over_sibling_debug` (py/tests/test_ucli_resolve_binary.py:90) | `parity.rs::parity_build` `ru-kardes-release` `ru-kardes-debug` | TAŞINDI |
| `ResolveBinaryTests.test_sibling_debug_is_the_fallback_when_there_is_no_sibling_release` (py/tests/test_ucli_resolve_binary.py:94) | `parity.rs::parity_build` `ru-kardes-release` `ru-kardes-debug` | TAŞINDI |
| `ResolveBinaryTests.test_sibling_release_alone_is_used` (py/tests/test_ucli_resolve_binary.py:98) | `parity.rs::parity_build` `ru-kardes-release` `ru-kardes-debug` | TAŞINDI |
| `ResolveBinaryTests.test_no_build_raises_a_clear_error_that_names_the_installer` (py/tests/test_ucli_resolve_binary.py:102) | `parity.rs::parity_build` `ru-hic` | TAŞINDI |
| `ResolveBinaryTests.test_overrides_beat_the_own_copy_so_debug_can_be_forced` (py/tests/test_ucli_resolve_binary.py:109) | `ucli.rs::resolve_binary`; sınanmayan senaryo: kaynaklar birlikteyken öncelik sırası (`ru-` vakaları tek tek) | TAŞINDI-TESTSİZ |
| `ResolveBinaryTests.test_settings_override_beats_env_and_env_beats_the_own_copy` (py/tests/test_ucli_resolve_binary.py:123) | `ucli.rs::resolve_binary`; sınanmayan senaryo: kaynaklar birlikteyken öncelik sırası (`ru-` vakaları tek tek) | TAŞINDI-TESTSİZ |
| `ScriptModeSettingTests.test_default_and_garbage_mean_off` (py/tests/test_ucli_script.py:42) | `parity.rs::parity_settings_pyfmt` `script` | TAŞINDI |
| `ScriptModeSettingTests.test_read_and_full_in_any_spelling` (py/tests/test_ucli_script.py:47) | `parity.rs::parity_settings_pyfmt` `script` | TAŞINDI |
| `ScriptModeSettingTests.test_default_settings_carry_the_key` (py/tests/test_ucli_script.py:52) | rs/state: `default_settings.json` | KAPSAM DIŞI |
| `BuildCommandTests.test_off_leaves_the_command_exactly_as_before` (py/tests/test_ucli_script.py:75) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildCommandTests.test_read_and_full_append_one_equals_form_flag` (py/tests/test_ucli_script.py:79) | `parity.rs::parity_ucli` `ayar-script-full` `eksik` | TAŞINDI |
| `BuildCommandTests.test_old_binary_without_the_flag_is_not_given_it` (py/tests/test_ucli_script.py:84) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `BuildCommandTests.test_allow_create_mode_passes_only_that_flag` (py/tests/test_ucli_script.py:90) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildCommandTests.test_allow_create_on_a_binary_that_lacks_it_opens_read_only` (py/tests/test_ucli_script.py:95) | `parity.rs::parity_ucli` `eski-ikili` `eksik` | TAŞINDI |
| `BuildCommandTests.test_permission_modes_list_and_round_trip_from_the_running_command` (py/tests/test_ucli_script.py:102) | `parity.rs::parity_model_effort` `bos-`; çalışan komuttan geri okuma rs/proc `providers.rs::ucli_info` | TAŞINDI |
| `SaveScriptSettingTests.test_mode_round_trips_and_an_empty_one_switches_the_layer_off` (py/tests/test_ucli_script.py:122) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveScriptSettingTests.test_saving_the_mode_leaves_the_other_ucli_panels_alone` (py/tests/test_ucli_script.py:131) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveScriptSettingTests.test_a_hand_edited_non_dict_value_degrades_to_off` (py/tests/test_ucli_script.py:139) | `parity.rs::parity_settings_pyfmt` `limitler-tip` | TAŞINDI |
| `SaveScriptSettingTests.test_the_panel_endpoint_returns_the_field_on_the_wire` (py/tests/test_ucli_script.py:144) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SearchTokenEnvTest.test_default_absent` (py/tests/test_ucli_search_token_env.py:21) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `SearchTokenEnvTest.test_valid_name` (py/tests/test_ucli_search_token_env.py:27) | `parity.rs::parity_ucli` `ste` `ste-deger` `ste-uzun` | TAŞINDI |
| `SearchTokenEnvTest.test_empty_means_not_sent` (py/tests/test_ucli_search_token_env.py:32) | `ucli_opts.rs::present`; sınanmayan senaryo: boş `search_token_env` | TAŞINDI-TESTSİZ |
| `SearchTokenEnvTest.test_invalid_names_error` (py/tests/test_ucli_search_token_env.py:36) | `parity.rs::parity_ucli` `ste` `ste-deger` `ste-uzun` | TAŞINDI |
| `SearchTokenEnvTest.test_argv_with_search_url` (py/tests/test_ucli_search_token_env.py:42) | `parity.rs::parity_ucli` `ste-arama` | TAŞINDI |
| `SearchTokenEnvTest.test_skipped_without_search_url` (py/tests/test_ucli_search_token_env.py:47) | `parity.rs::parity_ucli` `ste` | TAŞINDI |
| `SearchTokenEnvTest.test_unsupported_binary_skips` (py/tests/test_ucli_search_token_env.py:50) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `ServicesTests.test_defaults_when_empty` (py/tests/test_ucli_services_settings.py:18) | `parity.rs::parity_settings_pyfmt` `bos` `servisler` | TAŞINDI |
| `ServicesTests.test_groq_label` (py/tests/test_ucli_services_settings.py:23) | yok: `label`/`models` yok; diğer alanlar `parity_settings_pyfmt` `servisler` | EKSİK(G11) |
| `ServicesTests.test_invalid_dropped_evren_always_present` (py/tests/test_ucli_services_settings.py:27) | yok: `label`/`models` yok; diğer alanlar `parity_settings_pyfmt` `servisler` | EKSİK(G11) |
| `ServicesTests.test_services_map_follows_settings` (py/tests/test_ucli_services_settings.py:39) | `parity.rs::parity_settings_pyfmt` `servisler` ; `parity.rs::parity_ucli` `hizmet-ozel` | TAŞINDI |
| `ServicesTests.test_effort_follows_model` (py/tests/test_ucli_services_settings.py:46) | `parity.rs::parity_settings_pyfmt` `servisler` | TAŞINDI |
| `SettingTests.test_default_off_and_words` (py/tests/test_ucli_show_reasoning.py:24) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `BuildTests.test_flag_added_only_when_enabled_and_supported` (py/tests/test_ucli_show_reasoning.py:43) | `parity.rs::parity_ucli` `ayar-stream-off` `eksik` | TAŞINDI |
| `BuildTests.test_old_binary_never_gets_the_flag_and_it_is_logged` (py/tests/test_ucli_show_reasoning.py:47) | `parity.rs::parity_ucli` `ayar-stream-off` `eksik` | TAŞINDI |
| `ValidateTests.test_empty_is_ok_and_empty` (py/tests/test_ucli_start_opts.py:29) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_unknown_service_rejected` (py/tests/test_ucli_start_opts.py:33) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_shells_and_wrappers_rejected` (py/tests/test_ucli_start_opts.py:36) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_glob_needs_cmds_and_must_be_narrow` (py/tests/test_ucli_start_opts.py:40) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `ValidateTests.test_timeout_range_and_requires_cmds` (py/tests/test_ucli_start_opts.py:48) | `parity.rs::parity_ucli` `hizmet-bilinmeyen` `cmds-kabuk` `glob-` `timeout-` | TAŞINDI |
| `BuildTests.test_no_opts_is_identical_to_before` (py/tests/test_ucli_start_opts.py:80) | `parity.rs::parity_ucli` `opts-bos` | TAŞINDI |
| `BuildTests.test_max_history_kib_is_passed_only_when_the_binary_knows_it_and_the_setting_wins` (py/tests/test_ucli_start_opts.py:84) | `parity.rs::parity_ucli` `ayar-limit` `eksik` | TAŞINDI |
| `BuildTests.test_claude_service_swaps_endpoint_once_and_key_stays_out_of_argv` (py/tests/test_ucli_start_opts.py:98) | `parity.rs::parity_ucli` `hizmet-claude` | TAŞINDI |
| `BuildTests.test_claude_service_gets_team_flags_and_is_refused_over_the_daily_cap` (py/tests/test_ucli_start_opts.py:116) | yok: gerçek günlük tavan yok; bayraklar `parity_ucli` `hizmet-claude` | EKSİK(G8) |
| `BuildTests.test_groq_service_uses_groq_endpoint_and_key_env` (py/tests/test_ucli_start_opts.py:145) | `parity.rs::parity_ucli` `hizmet-grok`; aynı hizmet yolu | TAŞINDI |
| `BuildTests.test_service_models_fetches_live_list_with_correct_auth` (py/tests/test_ucli_start_opts.py:153) | yok | EKSİK(G7) |
| `BuildTests.test_claude_service_skips_instructions_auto_when_file_over_16kib` (py/tests/test_ucli_start_opts.py:177) | `parity.rs::parity_ucli` `hizmet-claude-buyuk-talimat` | TAŞINDI |
| `BuildTests.test_missing_service_key_refuses_spawn` (py/tests/test_ucli_start_opts.py:202) | `parity.rs::parity_ucli` `hizmet-claude-anahtarsiz` | TAŞINDI |
| `BuildTests.test_evren_service_changes_nothing` (py/tests/test_ucli_start_opts.py:206) | `parity.rs::parity_ucli` `hizmet-evren` | TAŞINDI |
| `BuildTests.test_exec_flags_appended_and_gated_by_binary` (py/tests/test_ucli_start_opts.py:209) | `parity.rs::parity_ucli` `toolchain-uygula` `eksik` | TAŞINDI |
| `BuildTests.test_exec_bind_ro` (py/tests/test_ucli_start_opts.py:219) | `parity.rs::parity_ucli` `bind-temel` ; `parity.rs::parity_misc` `exec` | TAŞINDI |
| `BuildTests.test_star_expands_on_path_and_write_adds_allow_edit` (py/tests/test_ucli_start_opts.py:227) | `parity.rs::parity_ucli` `exec-write-create` ; `parity.rs::parity_misc` `expand` | TAŞINDI |
| `BuildTests.test_patterns_validate` (py/tests/test_ucli_start_opts.py:241) | `parity.rs::parity_ucli` `cmds-glob` `cmds-re` | TAŞINDI |
| `BuildTests.test_star_never_opens_forbidden` (py/tests/test_ucli_start_opts.py:249) | `parity.rs::parity_ucli` `cmds-glob-yasak` ; `parity.rs::parity_misc` `expand` | TAŞINDI |
| `BuildTests.test_write_permission_default_off` (py/tests/test_ucli_start_opts.py:259) | `parity.rs::parity_ucli` `write` | TAŞINDI |
| `WiringTests.test_only_ucli_accepts_cli_opts` (py/tests/test_ucli_start_opts.py:267) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `WiringTests.test_spawn_never_passes_cli_opts_to_other_providers` (py/tests/test_ucli_start_opts.py:273) | `parity.rs::parity_spawn` `claude-opts` | TAŞINDI |
| `WiringTests.test_start_rejects_opts_for_non_ucli_and_invalid_opts` (py/tests/test_ucli_start_opts.py:280) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_rejects_before_recording_an_instance` (py/tests/test_ucli_start_opts.py:293) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_lock_timeout_forgets_instance` (py/tests/test_ucli_start_opts.py:328) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_timeout_after_spawn_keeps_instance` (py/tests/test_ucli_start_opts.py:334) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `WiringTests.test_new_chat_unexpected_error_before_spawn_forgets_instance` (py/tests/test_ucli_start_opts.py:340) | T4: `/api/start`, `/api/new-chat` akışı | KAPSAM DIŞI |
| `CostCapTests.test_today_sums_only_today_and_uses_the_task_model` (py/tests/test_ucli_start_opts.py:370) | yok | EKSİK(G8) |
| `CostCapTests.test_cap_zero_means_off_and_cap_blocks_when_reached` (py/tests/test_ucli_start_opts.py:380) | yok | EKSİK(G8) |
| `CostCapTests.test_config_parsing_is_safe` (py/tests/test_ucli_start_opts.py:391) | yok: tavan/kredi ayarı yok | EKSİK(G11) |
| `CostCapTests.test_credit_total_parsing_is_safe` (py/tests/test_ucli_start_opts.py:403) | yok: tavan/kredi ayarı yok | EKSİK(G11) |
| `TokioThreadsEnvTests.test_env_overrides_limits_tokio_workers` (py/tests/test_ucli_start_opts.py:414) | `parity.rs::parity_model_effort` `bos-` | TAŞINDI |
| `TestSetting.test_default_off_and_words` (py/tests/test_ucli_state_dir.py:42) | `parity.rs::parity_settings_pyfmt` `limitler` | TAŞINDI |
| `TestChatOnce.test_state_dir_passed_only_when_on_supported_and_session` (py/tests/test_ucli_state_dir.py:67) | yok | EKSİK(G10) |
| `TestPaths.test_dir_is_per_root_and_stable_and_outside_the_repo` (py/tests/test_ucli_state_dir.py:79) | `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `TestPaths.test_off_reads_only_legacy_until_the_new_dir_exists` (py/tests/test_ucli_state_dir.py:88) | yok: oturum dizini okuyucuları yok | EKSİK(G6) |
| `TestPaths.test_on_prefers_new_then_falls_back_to_legacy_for_files` (py/tests/test_ucli_state_dir.py:95) | yok: oturum dizini okuyucuları yok | EKSİK(G6) |
| `TestSpawnArgv.test_off_by_default_adds_nothing` (py/tests/test_ucli_state_dir.py:118) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `TestSpawnArgv.test_on_adds_flag_for_new_session_only_when_binary_knows_it` (py/tests/test_ucli_state_dir.py:122) | `parity.rs::parity_ucli` `statedir-acik` `eksik` | TAŞINDI |
| `TestSpawnArgv.test_session_with_legacy_history_keeps_the_legacy_dir` (py/tests/test_ucli_state_dir.py:127) | `parity.rs::parity_ucli` `statedir-eski-gecmis` | TAŞINDI |
| `TestSpawnArgv.test_session_already_in_new_dir_keeps_it_even_if_setting_turned_off` (py/tests/test_ucli_state_dir.py:133) | `parity.rs::parity_ucli` `statedir-yeni-gecmis` | TAŞINDI |
| `StreamSettingTests.test_the_shipped_default_is_on` (py/tests/test_ucli_stream.py:38) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_an_untouched_install_asks_for_the_stream_and_off_still_wins` (py/tests/test_ucli_stream.py:43) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_missing_empty_and_garbage_fall_back_to_the_default` (py/tests/test_ucli_stream.py:49) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_on_words_enable_in_any_spelling` (py/tests/test_ucli_stream.py:56) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_off_words_disable_even_when_the_default_is_on` (py/tests/test_ucli_stream.py:61) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `StreamSettingTests.test_the_stream_key_is_not_mistaken_for_a_numeric_limit` (py/tests/test_ucli_stream.py:67) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `SaveStreamSettingTests.test_it_round_trips_and_an_empty_value_goes_back_to_the_default` (py/tests/test_ucli_stream.py:82) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `SaveStreamSettingTests.test_it_does_not_disturb_the_other_limit_fields` (py/tests/test_ucli_stream.py:90) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `SaveStreamSettingTests.test_a_hand_edited_non_dict_value_degrades_to_the_default` (py/tests/test_ucli_stream.py:98) | `parity.rs::parity_settings_pyfmt` `limitler` `bos` | TAŞINDI |
| `BuildCommandTests.test_off_leaves_the_command_without_the_flag` (py/tests/test_ucli_stream.py:124) | `parity.rs::parity_ucli` `ayar-stream-off` | TAŞINDI |
| `BuildCommandTests.test_on_adds_exactly_one_bare_flag` (py/tests/test_ucli_stream.py:129) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `BuildCommandTests.test_an_old_binary_without_the_flag_is_not_given_it_and_the_skip_is_logged` (py/tests/test_ucli_stream.py:134) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `LiveUsageTests.test_the_counters_come_through_as_written` (py/tests/test_ucli_usage.py:50) | yok | EKSİK(G6) |
| `LiveUsageTests.test_a_binary_without_usage_means_unknown_not_zero` (py/tests/test_ucli_usage.py:54) | yok | EKSİK(G6) |
| `LiveUsageTests.test_a_usage_that_is_not_an_object_means_unknown` (py/tests/test_ucli_usage.py:58) | yok | EKSİK(G6) |
| `LiveUsageTests.test_no_status_file_no_sid_or_a_broken_file_mean_unknown` (py/tests/test_ucli_usage.py:64) | yok | EKSİK(G6) |
| `LiveUsageTests.test_the_unmetered_fields_of_an_older_binary_count_as_zero` (py/tests/test_ucli_usage.py:72) | yok | EKSİK(G6) |
| `LiveUsageTests.test_garbage_values_become_zero_never_an_invented_number` (py/tests/test_ucli_usage.py:78) | yok | EKSİK(G6) |
| `LiveUsageTests.test_only_the_known_counters_are_returned` (py/tests/test_ucli_usage.py:86) | yok | EKSİK(G6) |
| `LiveUsageTests.test_every_other_provider_has_no_counter` (py/tests/test_ucli_usage.py:92) | yok | EKSİK(G6) |
| `LiveUsageHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` (py/tests/test_ucli_usage.py:104) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `LiveUsageHelperTests.test_a_failing_provider_never_breaks_the_panel` (py/tests/test_ucli_usage.py:112) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadUsageTests.test_a_registered_running_ucli_row_carries_its_counters` (py/tests/test_ucli_usage.py:148) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadUsageTests.test_an_unregistered_running_ucli_row_carries_its_counters` (py/tests/test_ucli_usage.py:153) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `StatusPayloadUsageTests.test_a_stopped_row_and_a_counterless_provider_have_no_usage` (py/tests/test_ucli_usage.py:157) | T1: panel kullanım satırı; sağlayıcı okuyucusu G6 | KAPSAM DIŞI |
| `UcliWebConfigTests.test_empty_unset_and_garbage_mean_the_defaults_search_via_the_managed_searxng` (py/tests/test_ucli_web.py:75) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_search_docker_can_be_turned_off_in_every_spelling` (py/tests/test_ucli_web.py:80) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_search_docker_stays_on_for_on_values_and_for_empty_or_null` (py/tests/test_ucli_web.py:86) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_an_explicit_address_wins_and_switches_the_managed_one_off` (py/tests/test_ucli_web.py:91) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_a_filled_but_invalid_address_does_not_fall_back_to_the_managed_searxng` (py/tests/test_ucli_web.py:96) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_valid_searxng_address_defaults_the_flavor` (py/tests/test_ucli_web.py:104) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_https_and_explicit_flavor_in_any_case` (py/tests/test_ucli_web.py:109) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_brave_is_not_supported_yet_and_fails_closed` (py/tests/test_ucli_web.py:113) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_invalid_addresses_keep_search_off` (py/tests/test_ucli_web.py:118) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_whitespace_around_the_address_is_trimmed_not_rejected` (py/tests/test_ucli_web.py:125) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_domains_are_split_lowercased_and_deduplicated_in_order` (py/tests/test_ucli_web.py:129) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_domains_accept_a_list_too` (py/tests/test_ucli_web.py:134) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_invalid_domains_are_dropped_not_fixed` (py/tests/test_ucli_web.py:138) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_whitespace_is_a_separator_not_part_of_a_name` (py/tests/test_ucli_web.py:144) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_single_label_hosts_are_valid` (py/tests/test_ucli_web.py:148) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_domain_count_is_capped` (py/tests/test_ucli_web.py:152) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `UcliWebConfigTests.test_fetch_domains_do_not_need_a_search_address` (py/tests/test_ucli_web.py:157) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `SaveSettingsTests.test_defaults_are_off_and_cache_aware` (py/tests/test_ucli_web.py:172) | rs/state: varsayılan ayar belgesi | KAPSAM DIŞI |
| `SaveSettingsTests.test_ucli_web_merges_per_field_and_empty_removes_the_field` (py/tests/test_ucli_web.py:177) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_a_boolean_search_docker_round_trips_and_false_does_not_mean_remove` (py/tests/test_ucli_web.py:185) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_the_off_switch_does_not_disturb_the_other_fields` (py/tests/test_ucli_web.py:196) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_a_list_value_is_stored_as_a_comma_separated_string` (py/tests/test_ucli_web.py:201) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_other_dict_settings_are_unaffected_by_the_list_handling` (py/tests/test_ucli_web.py:206) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `SaveSettingsTests.test_a_non_dict_stored_value_degrades_to_empty` (py/tests/test_ucli_web.py:212) | `parity.rs::parity_settings_pyfmt` `limitler-tip` | TAŞINDI |
| `SaveSettingsTests.test_the_escape_hatch_persists` (py/tests/test_ucli_web.py:218) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `BinaryFlagProbeTests.test_exact_flag_matching` (py/tests/test_ucli_web.py:225) | `parity.rs::parity_ucli` `benzer-bayrak` ; `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `BinaryFlagProbeTests.test_a_longer_flag_does_not_count_as_its_prefix` (py/tests/test_ucli_web.py:232) | `parity.rs::parity_ucli` `benzer-bayrak` ; `parity.rs::parity_misc` `ucli-misc` | TAŞINDI |
| `BinaryFlagProbeTests.test_old_binary_supports_neither` (py/tests/test_ucli_web.py:237) | `parity.rs::parity_ucli` `eski-ikili` | TAŞINDI |
| `BinaryFlagProbeTests.test_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` (py/tests/test_ucli_web.py:242) | yok: `--help` yoklaması ve önbelleği yok | EKSİK(G8) |
| `BinaryFlagProbeTests.test_missing_or_non_executable_binary_is_false_and_not_cached` (py/tests/test_ucli_web.py:252) | yok: `--help` yoklaması ve önbelleği yok | EKSİK(G8) |
| `BinaryFlagProbeTests.test_empty_help_output_is_not_cached` (py/tests/test_ucli_web.py:262) | yok: `--help` yoklaması ve önbelleği yok | EKSİK(G8) |
| `BinaryFlagProbeTests.test_the_real_delivered_binary_knows_the_web_flags_when_it_is_new_enough` (py/tests/test_ucli_web.py:267) | rs/prov: gereksiz: teslim edilen gerçek ucli ikilisini sınar | KAPSAM DIŞI |
| `WebArgsTests.test_everything_switched_off_adds_nothing_and_never_probes` (py/tests/test_ucli_web.py:292) | `parity.rs::parity_ucli` `web-docker-kapali` | TAŞINDI |
| `WebArgsTests.test_auto_search_uses_the_managed_searxng_address_and_names_the_session` (py/tests/test_ucli_web.py:300) | `ucli.rs::Ctx::web_args`; sınanmayan senaryo: `Probe::searxng_url` çağrılıp çağrılmadığı/oturum adı denetlenmiyor | TAŞINDI-TESTSİZ |
| `WebArgsTests.test_auto_search_not_ready_opens_the_session_without_search_and_without_error` (py/tests/test_ucli_web.py:307) | `parity.rs::parity_ucli` `web-docker-bos-url` `temel-` | TAŞINDI |
| `WebArgsTests.test_auto_search_with_an_old_binary_never_touches_docker` (py/tests/test_ucli_web.py:313) | `ucli.rs::Ctx::web_args`; sınanmayan senaryo: `Probe::searxng_url` çağrılıp çağrılmadığı/oturum adı denetlenmiyor | TAŞINDI-TESTSİZ |
| `WebArgsTests.test_an_explicit_address_never_starts_the_managed_one` (py/tests/test_ucli_web.py:321) | `ucli.rs::Ctx::web_args`; sınanmayan senaryo: `Probe::searxng_url` çağrılıp çağrılmadığı/oturum adı denetlenmiyor | TAŞINDI-TESTSİZ |
| `WebArgsTests.test_a_filled_invalid_address_neither_searches_nor_starts_docker` (py/tests/test_ucli_web.py:325) | `parity.rs::parity_settings_pyfmt` `web` | TAŞINDI |
| `WebArgsTests.test_a_crash_in_the_managed_searxng_never_breaks_the_spawn` (py/tests/test_ucli_web.py:329) | yok: gerçek searxng uygulaması yok | EKSİK(G8) |
| `WebArgsTests.test_auto_search_and_fetch_domains_combine` (py/tests/test_ucli_web.py:335) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `WebArgsTests.test_both_capabilities_on_a_new_binary` (py/tests/test_ucli_web.py:341) | `parity.rs::parity_ucli` `eksik` | TAŞINDI |
| `WebArgsTests.test_search_only_adds_no_fetch_flags` (py/tests/test_ucli_web.py:348) | `parity.rs::parity_ucli` `web-docker-hazir` `web-url` | TAŞINDI |
| `WebArgsTests.test_fetch_only_adds_no_search_flags` (py/tests/test_ucli_web.py:352) | `parity.rs::parity_ucli` `web-docker-kapali` `web-url` `eksik` | TAŞINDI |
| `WebArgsTests.test_a_binary_that_only_has_fetch_drops_search_and_says_so` (py/tests/test_ucli_web.py:356) | `parity.rs::parity_ucli` `web-eksik-bayrak-url` `eksik` | TAŞINDI |
| `WebArgsTests.test_an_old_binary_gets_no_web_flags_at_all_so_spawn_cannot_crash` (py/tests/test_ucli_web.py:362) | `parity.rs::parity_ucli` `eski-ikili` | TAŞINDI |
| `BuildInnerCommandTests.test_default_command_is_byte_identical_to_before_when_no_search_backend_is_ready` (py/tests/test_ucli_web.py:394) | `parity.rs::parity_ucli` `temel-` `web-docker-hazir` | TAŞINDI |
| `BuildInnerCommandTests.test_default_command_gets_the_managed_search_flags_when_the_backend_is_ready` (py/tests/test_ucli_web.py:398) | `parity.rs::parity_ucli` `temel-` `web-docker-hazir` | TAŞINDI |
| `BuildInnerCommandTests.test_web_flags_are_appended_after_everything_else` (py/tests/test_ucli_web.py:405) | `parity.rs::parity_ucli` `web-url` | TAŞINDI |
| `BuildInnerCommandTests.test_url_metacharacters_survive_shell_quoting` (py/tests/test_ucli_web.py:415) | `ucli.rs::{web_args, build_inner_command}`; sınanmayan senaryo: salt okunur/metakarakterli adres/anahtar sarmalı ile web bayraklarının birlikteliği | TAŞINDI-TESTSİZ |
| `BuildInnerCommandTests.test_read_only_sessions_get_web_too_and_no_allow_edit` (py/tests/test_ucli_web.py:420) | `ucli.rs::{web_args, build_inner_command}`; sınanmayan senaryo: salt okunur/metakarakterli adres/anahtar sarmalı ile web bayraklarının birlikteliği | TAŞINDI-TESTSİZ |
| `BuildInnerCommandTests.test_api_key_wrapper_keeps_the_flags_and_no_secret_enters_argv` (py/tests/test_ucli_web.py:425) | `ucli.rs::{web_args, build_inner_command}`; sınanmayan senaryo: salt okunur/metakarakterli adres/anahtar sarmalı ile web bayraklarının birlikteliği | TAŞINDI-TESTSİZ |
| `BuildInnerCommandTests.test_running_command_parsing_is_unaffected_by_the_new_flags` (py/tests/test_ucli_web.py:433) | rs/proc: `providers.rs::ucli_info`; rs-proc-mapping.md bir kenar durumu KISMİ diyor | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_every_effort_preset_round_trips_through_the_running_command` (py/tests/test_ucli_web.py:445) | rs/proc: `providers.rs::ucli_info`; rs-proc-mapping.md bir kenar durumu KISMİ diyor | KAPSAM DIŞI |
| `BuildInnerCommandTests.test_effort_stays_unknown_when_a_limit_was_changed_by_hand_or_is_missing` (py/tests/test_ucli_web.py:458) | rs/proc: `providers.rs::ucli_info`; rs-proc-mapping.md bir kenar durumu KISMİ diyor | KAPSAM DIŞI |
| `AutoContextTests.test_deriving_binary_gets_no_context_flag_and_effort_round_trips` (py/tests/test_ucli_web.py:495) | `parity.rs::parity_ucli` `turetir` | TAŞINDI |
| `AutoContextTests.test_old_binary_keeps_preset_context` (py/tests/test_ucli_web.py:502) | `parity.rs::parity_ucli` `temel-` | TAŞINDI |
| `AutoContextTests.test_explicit_setting_still_wins` (py/tests/test_ucli_web.py:506) | `parity.rs::parity_ucli` `turetir-ayar` | TAŞINDI |
| `AutoContextTests.test_legacy_session_with_other_context_value_is_unknown` (py/tests/test_ucli_web.py:511) | rs/proc: `providers.rs::ucli_info` | KAPSAM DIŞI |
| `FreshParse.test_parse_one_line_format` (py/tests/test_usage_fresh.py:21) | yok | EKSİK(G5) |
| `FreshParse.test_parse_falls_back_to_tui_format` (py/tests/test_usage_fresh.py:27) | yok | EKSİK(G5) |
| `FreshParse.test_other_providers_have_no_fresh_path` (py/tests/test_usage_fresh.py:32) | yok | EKSİK(G5) |
| `FreshParse.test_agy_fresh_argv_and_tsv_parse` (py/tests/test_usage_fresh.py:37) | yok | EKSİK(G5) |
| `FreshRun.test_fresh_ok_without_any_session` (py/tests/test_usage_fresh.py:52) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_fresh_failure_returns_none` (py/tests/test_usage_fresh.py:60) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_signed_out_agy_is_auth_required_not_read_failed` (py/tests/test_usage_fresh.py:66) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_missing_binary_is_not_installed` (py/tests/test_usage_fresh.py:77) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_usage_all_prefers_fresh_and_skips_sessions` (py/tests/test_usage_fresh.py:84) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_usage_never_injects_into_live_sessions` (py/tests/test_usage_fresh.py:94) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `FreshRun.test_api_balance_failure_does_not_break_usage` (py/tests/test_usage_fresh.py:110) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `NoUsageRows.test_codex_and_ucli_explain_instead_of_unsupported` (py/tests/test_usage_fresh.py:123) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `NoUsageRows.test_note_follows_request_language_without_mutating_state` (py/tests/test_usage_fresh.py:131) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `PruneTranscripts.test_only_pure_usage_command_files_after_since_are_removed` (py/tests/test_usage_fresh.py:144) | T7: kullanım yenileme akışı | KAPSAM DIŞI |
| `ResolvedBinaryFallback.test_claude_found_outside_path` (py/tests/test_usage_fresh.py:162) | yok: ikili bulma `parity_build` `claude-bilinen`; `usage_fresh_argv` yok | EKSİK(G5) |
| `ResolvedBinaryFallback.test_provider_bin_override_used_by_usage_fresh_argv` (py/tests/test_usage_fresh.py:175) | yok | EKSİK(G5) |
| `P.test_parse_percent_fraction_reset` (py/tests/test_usage_fresh_tui.py:21) | yok | EKSİK(G5) |
| `P.test_parse_without_reset_unchanged` (py/tests/test_usage_fresh_tui.py:25) | yok | EKSİK(G5) |
| `P.test_argv_and_no_print_mode` (py/tests/test_usage_fresh_tui.py:29) | yok | EKSİK(G5) |
| `Ttl.test_ttl_cache_and_stale` (py/tests/test_usage_fresh_tui.py:40) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `IsolatedNoRealRead.test_isolated_panel_does_not_launch_real_cli` (py/tests/test_usage_fresh_tui.py:52) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `IsolatedNoRealRead.test_default_dir_is_not_isolated` (py/tests/test_usage_fresh_tui.py:57) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `RealTmuxTrustDialog.test_dialog_accepted_before_command_in_private_cwd` (py/tests/test_usage_fresh_tui.py:78) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_dead_pid_socket_closed_and_unlinked` (py/tests/test_usage_fresh_tui.py:125) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_own_fresh_socket_untouched_but_own_old_one_closed` (py/tests/test_usage_fresh_tui.py:131) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_live_other_pid_fresh_untouched_old_closed` (py/tests/test_usage_fresh_tui.py:140) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `Sweep.test_other_sockets_ignored_and_missing_dir_ok` (py/tests/test_usage_fresh_tui.py:147) | T7: kullanım yenileme akışı (TUI yoklaması) | KAPSAM DIŞI |
| `TestEvren.test_argv_safe_and_key_in_env_only` (py/tests/test_web_review_runner.py:118) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_no_io_flag_when_unsupported` (py/tests/test_web_review_runner.py:133) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_claude_env_filtered` (py/tests/test_web_review_runner.py:137) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_redact_applied_and_answer_extracted` (py/tests/test_web_review_runner.py:145) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_timeout_writes_partial` (py/tests/test_web_review_runner.py:153) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_effort_always_sent_unless_model_rejects_it` (py/tests/test_web_review_runner.py:172) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_file_flag_added_only_when_supported` (py/tests/test_web_review_runner.py:187) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_file_path_is_symlink_free` (py/tests/test_web_review_runner.py:196) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_killed_run_is_recovered_from_partial_file_masked` (py/tests/test_web_review_runner.py:208) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_without_report_heading_is_not_a_report` (py/tests/test_web_review_runner.py:223) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_partial_turn_in_error_json_is_recovered` (py/tests/test_web_review_runner.py:231) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_failed_run_keeps_error_log_masked_0600` (py/tests/test_web_review_runner.py:240) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_successful_run_has_no_error_log` (py/tests/test_web_review_runner.py:253) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_nonzero_no_output_is_error` (py/tests/test_web_review_runner.py:257) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_busy_lock` (py/tests/test_web_review_runner.py:261) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestEvren.test_missing_key_errors_and_releases_lock` (py/tests/test_web_review_runner.py:267) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestCancel.test_cancel_kills_own_group_and_marks_partial` (py/tests/test_web_review_runner.py:276) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestCancel.test_cancel_before_process_exists_is_not_swallowed` (py/tests/test_web_review_runner.py:300) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestCancel.test_cancelled_before_spawn_kills_new_process` (py/tests/test_web_review_runner.py:312) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_isolated_home_with_readonly_allow_list` (py/tests/test_web_review_runner.py:345) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_bwrap_jail_wraps_argv_when_available` (py/tests/test_web_review_runner.py:361) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_no_bwrap_or_jail_off_falls_back_to_allow_list` (py/tests/test_web_review_runner.py:376) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_agy_model_quota_blocks_only_that_model_until_reset` (py/tests/test_web_review_runner.py:394) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_tmpdir_is_writable_home_tmp_and_stale_entries_pruned` (py/tests/test_web_review_runner.py:413) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_allow_override_and_off` (py/tests/test_web_review_runner.py:427) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_ok_done_and_argv` (py/tests/test_web_review_runner.py:458) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_label_mismatch_is_model_fallback_but_file_kept` (py/tests/test_web_review_runner.py:470) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_no_log_is_model_fallback` (py/tests/test_web_review_runner.py:476) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_old_log_not_taken_for_new_run` (py/tests/test_web_review_runner.py:480) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_no_effort_for_non_gemini` (py/tests/test_web_review_runner.py:489) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestAgy.test_model_not_in_agy_list` (py/tests/test_web_review_runner.py:493) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBannerLimit.test_monthly_quota_banner_with_rc0_is_limit_not_done` (py/tests/test_web_review_runner.py:508) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBannerLimit.test_real_report_mentioning_quota_stays_done` (py/tests/test_web_review_runner.py:516) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBannerLimit.test_month_start_helper` (py/tests/test_web_review_runner.py:526) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBodyless.test_failed_run_with_junk_body_is_error` (py/tests/test_web_review_runner.py:551) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBodyless.test_successful_exit_with_junk_body_is_error` (py/tests/test_web_review_runner.py:555) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestBodyless.test_report_bodyless_rule` (py/tests/test_web_review_runner.py:559) | rs/rev: `cops-review-core` parite (rs-rev.md) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start` (py/tests/test_web_review_runner.py:570) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start_salvages_draft_report` (py/tests/test_web_review_runner.py:578) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start_salvages_report_from_io_log` (py/tests/test_web_review_runner.py:590) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestRecover.test_recover_on_start_no_report_head_keeps_file_empty` (py/tests/test_web_review_runner.py:608) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_findings_are_saved_before_pair_turns_done` (py/tests/test_web_review_runner.py:647) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_detached_run_writes_files_and_finishes` (py/tests/test_web_review_runner.py:664) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_restart_adopts_live_run_and_finishes_it` (py/tests/test_web_review_runner.py:689) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_run_finished_while_service_down_is_processed` (py/tests/test_web_review_runner.py:704) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_pid_reuse_is_not_adopted_as_alive` (py/tests/test_web_review_runner.py:712) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_adopt_keeps_pre_restart_io_log` (py/tests/test_web_review_runner.py:717) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_adopt_failure_marks_partial_not_stuck_running` (py/tests/test_web_review_runner.py:728) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |
| `TestDetached.test_without_cfg_old_behavior_partial` (py/tests/test_web_review_runner.py:739) | T8: reviewer koşucusu (`web_review`) | KAPSAM DIŞI |

### İlk aday listesinde olmayan test dosyaları (kapsam ya da kullanılan dış adları sınıyor)

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `ProcStatTest.test_plain` (py/tests/test_proc_stat_parse.py:13) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_comm_with_space_and_paren` (py/tests/test_proc_stat_parse.py:18) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_starttime_index` (py/tests/test_proc_stat_parse.py:22) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_no_paren_raises` (py/tests/test_proc_stat_parse.py:26) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_own_ppid` (py/tests/test_proc_stat_parse.py:30) | rs/proc: `procfs.rs::{parse_stat, OwnProc::stat}` | KAPSAM DIŞI |
| `ProcStatTest.test_no_inline_copies` (py/tests/test_proc_stat_parse.py:33) | rs/proc: gereksiz: Python kaynak taraması | KAPSAM DIŞI |
| `TestPlanTickQuotaHeld.test_quota_held_project_is_not_started_others_are` (py/tests/test_quota_scoped_api_credit.py:20) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestPlanTickQuotaHeld.test_answer_does_not_start_held_project` (py/tests/test_quota_scoped_api_credit.py:31) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestQuotaScopeHelpers.test_held_projects_only_metered_cli` (py/tests/test_quota_scoped_api_credit.py:43) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestQuotaScopeHelpers.test_blocks_target_depends_on_brain_cli` (py/tests/test_quota_scoped_api_credit.py:47) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestBrainCliConfig.test_set_brain_cli_service_cost` (py/tests/test_quota_scoped_api_credit.py:64) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestBrainCliConfig.test_rejects_bad` (py/tests/test_quota_scoped_api_credit.py:71) | T10: kota kapsamı ve beyin ayarı (`steward`, `steward_quota`) | KAPSAM DIŞI |
| `TestCreditWindow.test_config_dates_validated` (py/tests/test_quota_scoped_api_credit.py:84) | yok | EKSİK(G11) |
| `TestCreditWindow.test_spent_counts_only_since` (py/tests/test_quota_scoped_api_credit.py:89) | yok | EKSİK(G8) |
| `TestCreditWindow.test_window_days_and_budget` (py/tests/test_quota_scoped_api_credit.py:102) | yok | EKSİK(G8) |
| `ResolvedBinaryOverrideTest.test_valid_executable_override_wins` (py/tests/test_resolved_binary_override.py:16) | `parity.rs::parity_build` `-override` `-override-calismaz` `-override-tilde-kullanici` | TAŞINDI |
| `ResolvedBinaryOverrideTest.test_tilde_expanded` (py/tests/test_resolved_binary_override.py:23) | `parity.rs::parity_build` `-override` `-override-calismaz` `-override-tilde-kullanici` | TAŞINDI |
| `ResolvedBinaryOverrideTest.test_missing_or_non_executable_falls_back_to_path` (py/tests/test_resolved_binary_override.py:30) | `parity.rs::parity_build` `-override` `-override-calismaz` `-override-tilde-kullanici` | TAŞINDI |
| `SelfVerifyTest.test_verdicts_applied_session_not_woken` (py/tests/test_review_self_verify.py:54) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_failure_returns_to_new_then_unclear_after_max_tries` (py/tests/test_review_self_verify.py:69) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_apply_verdicts_exception_requeues_not_stuck` (py/tests/test_review_self_verify.py:78) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_timeout_kills_and_requeues` (py/tests/test_review_self_verify.py:90) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_concurrent_calls_same_project_only_one_starts` (py/tests/test_review_self_verify.py:98) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_missing_verdict_line_requeues_only_that_finding` (py/tests/test_review_self_verify.py:131) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_recover_returns_orphaned_self_verify_to_new` (py/tests/test_review_self_verify.py:138) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_recover_also_returns_orphaned_remote_verify_to_new` (py/tests/test_review_self_verify.py:145) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_recover_leaves_live_remote_verify_alone` (py/tests/test_review_self_verify.py:153) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_process_verdicts_ignores_self_sessions` (py/tests/test_review_self_verify.py:165) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_http_verify_and_auto_verify_use_self_mode` (py/tests/test_review_self_verify.py:174) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_bulk_approve_only_verified_filtered` (py/tests/test_review_self_verify.py:183) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_bulk_endpoint_is_human_only` (py/tests/test_review_self_verify.py:198) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_default_verifier_is_claude_sonnet` (py/tests/test_review_self_verify.py:204) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_codex_verifier_read_only_argv` (py/tests/test_review_self_verify.py:207) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_evren_verifier_waits_for_running_evren_review_and_has_no_allow_flags` (py/tests/test_review_self_verify.py:220) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_missing_model_is_busy_not_marked` (py/tests/test_review_self_verify.py:240) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `SelfVerifyTest.test_config_accepts_provider_and_single_model` (py/tests/test_review_self_verify.py:246) | T8: reviewer doğrulama koşucusu | KAPSAM DIŞI |
| `ResumeLacksHoTest.test_work_without_ho_is_detected` (py/tests/test_steward_ho_on_open.py:51) | yok: resume çözümü ve transkript yolu; karar T10 | EKSİK(G1) |
| `ResumeLacksHoTest.test_ho_done_is_clean` (py/tests/test_steward_ho_on_open.py:55) | yok: resume çözümü ve transkript yolu; karar T10 | EKSİK(G1) |
| `ResumeLacksHoTest.test_new_request_after_ho_needs_ho_again` (py/tests/test_steward_ho_on_open.py:58) | yok: resume çözümü ve transkript yolu; karar T10 | EKSİK(G1) |
| `ResumeLacksHoTest.test_empty_conversation_is_clean` (py/tests/test_steward_ho_on_open.py:62) | yok: resume çözümü ve transkript yolu; karar T10 | EKSİK(G1) |
| `ResumeLacksHoTest.test_off_and_non_claude_and_ucli_record` (py/tests/test_steward_ho_on_open.py:65) | yok: resume çözümü ve transkript yolu; karar T10 | EKSİK(G1) |
| `ResumeLacksHoTest.test_missing_jsonl` (py/tests/test_steward_ho_on_open.py:71) | yok: resume çözümü ve transkript yolu; karar T10 | EKSİK(G1) |
| `EnsureRunningHoOnOpenTest.test_lacking_ho_resumes_then_hands_over` (py/tests/test_steward_ho_on_open.py:102) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EnsureRunningHoOnOpenTest.test_clean_open_no_handover` (py/tests/test_steward_ho_on_open.py:110) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `EnsureRunningHoOnOpenTest.test_handover_failure_no_pending` (py/tests/test_steward_ho_on_open.py:116) | rs/stew: rs-stew.md satırı var, orada henüz EKSİK | KAPSAM DIŞI |
| `MainSessionModel.test_registered_fable_becomes_sonnet_medium` (py/tests/test_steward_main_model.py:13) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_opus_and_empty_on_claude` (py/tests/test_steward_main_model.py:16) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_non_claude_cli_untouched` (py/tests/test_steward_main_model.py:20) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_remote_unknown_cli_only_claude_models` (py/tests/test_steward_main_model.py:24) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_non_claude_model_on_claude_cli_untouched` (py/tests/test_steward_main_model.py:29) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `MainSessionModel.test_no_sonnet_known_is_noop` (py/tests/test_steward_main_model.py:32) | `parity.rs::parity_spawn` `ana-oturum` | TAŞINDI |
| `PreviewOnlyTest.test_preview_does_not_issue_token` (py/tests/test_ucli_agents_preview.py:12) | yok | EKSİK(G8) |
| `ApprovalTest.test_register_dirs_private_and_state` (py/tests/test_ucli_approval.py:30) | yok | EKSİK(G10) |
| `ApprovalTest.test_bad_run_key` (py/tests/test_ucli_approval.py:40) | yok | EKSİK(G10) |
| `ApprovalTest.test_parse_suspended` (py/tests/test_ucli_approval.py:45) | yok | EKSİK(G10) |
| `ApprovalTest.test_pending_lists_and_skips_bad_and_never_reads_suspended` (py/tests/test_ucli_approval.py:52) | T7: onay panel uçları (`/api/ucli/approvals`) | KAPSAM DIŞI |
| `ApprovalTest.test_answer_ok_and_modes` (py/tests/test_ucli_approval.py:65) | T7: onay panel uçları (`/api/ucli/approvals`) | KAPSAM DIŞI |
| `ApprovalTest.test_answer_rejections` (py/tests/test_ucli_approval.py:76) | T7: onay panel uçları (`/api/ucli/approvals`) | KAPSAM DIŞI |
| `BudgetExhaustedTest.test_failures_prefixes_answer_once` (py/tests/test_ucli_budget_exhausted.py:12) | yok | EKSİK(G10) |
| `BudgetExhaustedTest.test_unknown_reason_still_marked` (py/tests/test_ucli_budget_exhausted.py:19) | yok | EKSİK(G10) |
| `BudgetExhaustedTest.test_no_field_unchanged` (py/tests/test_ucli_budget_exhausted.py:23) | yok | EKSİK(G10) |
| `BudgetExhaustedTest.test_parse_turn_marks` (py/tests/test_ucli_budget_exhausted.py:30) | yok | EKSİK(G10) |
| `Registry.test_save_load_0600_and_dir_0700` (py/tests/test_ucli_checks_api.py:28) | yok: kayıt yükleme/biçim denetimi yok; yazım ucu T7 | EKSİK(G8) |
| `Registry.test_bad_shape_not_written` (py/tests/test_ucli_checks_api.py:35) | yok: kayıt yükleme/biçim denetimi yok; yazım ucu T7 | EKSİK(G8) |
| `Registry.test_symlink_target_refused` (py/tests/test_ucli_checks_api.py:40) | yok: kayıt yükleme/biçim denetimi yok; yazım ucu T7 | EKSİK(G8) |
| `Registry.test_delete` (py/tests/test_ucli_checks_api.py:47) | yok: kayıt yükleme/biçim denetimi yok; yazım ucu T7 | EKSİK(G8) |
| `ReplaceKeepsDoc.test_other_top_level_keys_kept` (py/tests/test_ucli_checks_api.py:55) | yok: kayıt yükleme/biçim denetimi yok; yazım ucu T7 | EKSİK(G8) |
| `Mode.test_narrow_without_confirm_and_seq_increments` (py/tests/test_ucli_checks_api.py:68) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_widen_needs_confirm` (py/tests/test_ucli_checks_api.py:77) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_above_cap_409` (py/tests/test_ucli_checks_api.py:83) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_audit_written` (py/tests/test_ucli_checks_api.py:87) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_bad_inputs` (py/tests/test_ucli_checks_api.py:94) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Mode.test_get_mode_reads_file_default_off` (py/tests/test_ucli_checks_api.py:99) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `Authz.test_actions` (py/tests/test_ucli_checks_api.py:107) | T7: `/api/ucli/checks*` uçları | KAPSAM DIŞI |
| `RealBinary.test_every_template_validates` (py/tests/test_ucli_checks_real_binary.py:24) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `RealBinary.test_save_adds_version_and_real_validation_rejects_bad` (py/tests/test_ucli_checks_real_binary.py:29) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `Unit.test_version_defaults_to_1_without_binary` (py/tests/test_ucli_checks_real_binary.py:38) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `Unit.test_validation_failure_blocks_write` (py/tests/test_ucli_checks_real_binary.py:42) | T7: kayıt yazımı ve gerçek ikili doğrulaması | KAPSAM DIŞI |
| `TestBySession.test_breakdown_sorted_and_total_matches` (py/tests/test_ucli_cost_by_session.py:18) | yok: maliyet defteri yok | EKSİK(G8) |
| `TestBySession.test_top_n_limit` (py/tests/test_ucli_cost_by_session.py:29) | yok: maliyet defteri yok | EKSİK(G8) |
| `TestBySession.test_per_session_reads_files` (py/tests/test_ucli_cost_by_session.py:39) | yok: maliyet defteri yok | EKSİK(G8) |
| `CreditTest.test_config_parse` (py/tests/test_ucli_cost_credit.py:25) | yok | EKSİK(G11) |
| `CreditTest.test_hidden_when_empty` (py/tests/test_ucli_cost_credit.py:32) | yok: maliyet defteri yok | EKSİK(G8) |
| `CreditTest.test_left_counts_old_days_too` (py/tests/test_ucli_cost_credit.py:37) | yok: maliyet defteri yok | EKSİK(G8) |
| `CreditTest.test_left_never_negative` (py/tests/test_ucli_cost_credit.py:48) | yok: maliyet defteri yok | EKSİK(G8) |
| `TestInvalidate.test_invalidate_forces_rescan` (py/tests/test_ucli_cost_invalidate.py:17) | yok: maliyet defteri yok | EKSİK(G8) |
| `RateTest.test_window_scales_rate` (py/tests/test_ucli_cost_rate.py:27) | yok: maliyet defteri yok | EKSİK(G8) |
| `RateTest.test_per_session_sums_to_total` (py/tests/test_ucli_cost_rate.py:33) | yok: maliyet defteri yok | EKSİK(G8) |
| `RateTest.test_corrupt_lines_are_skipped` (py/tests/test_ucli_cost_rate.py:40) | yok: maliyet defteri yok | EKSİK(G8) |
| `RateTest.test_missing_dir_and_bad_window` (py/tests/test_ucli_cost_rate.py:47) | yok: maliyet defteri yok | EKSİK(G8) |
| `ReleaseOnFailedStart.test_release_returns_the_reserved_share_immediately` (py/tests/test_ucli_cost_release.py:12) | yok: maliyet defteri yok | EKSİK(G8) |
| `ReserveTests.test_two_sessions_cap_two` (py/tests/test_ucli_cost_reserve.py:25) | yok: maliyet defteri yok | EKSİK(G8) |
| `ReserveTests.test_same_name_replaces` (py/tests/test_ucli_cost_reserve.py:32) | yok: maliyet defteri yok | EKSİK(G8) |
| `ReserveTests.test_release_frees_slot` (py/tests/test_ucli_cost_reserve.py:38) | yok: maliyet defteri yok | EKSİK(G8) |
| `ReserveTests.test_ttl_expiry` (py/tests/test_ucli_cost_reserve.py:46) | yok: maliyet defteri yok | EKSİK(G8) |
| `ReserveTests.test_no_cap_keeps_nothing` (py/tests/test_ucli_cost_reserve.py:51) | yok: maliyet defteri yok | EKSİK(G8) |
| `Compute.test_rss_io_children_cpu` (py/tests/test_ucli_metrics.py:44) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Compute.test_stat_comm_with_parens` (py/tests/test_ucli_metrics.py:67) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Compute.test_disk_limits` (py/tests/test_ucli_metrics.py:70) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Compute.test_disk_every_5min` (py/tests/test_ucli_metrics.py:81) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_no_sessions_no_work` (py/tests/test_ucli_metrics.py:93) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_discover_throttled` (py/tests/test_ucli_metrics.py:104) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_disabled_never_starts` (py/tests/test_ucli_metrics.py:112) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Idle.test_config_parsing` (py/tests/test_ucli_metrics.py:117) | yok | EKSİK(G11) |
| `Idle.test_settings_default_key` (py/tests/test_ucli_metrics.py:124) | rs/state: `default_settings.json` | KAPSAM DIŞI |
| `Store.test_retention` (py/tests/test_ucli_metrics.py:130) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Store.test_daily_prune_in_sampler` (py/tests/test_ucli_metrics.py:136) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Store.test_wal_and_index` (py/tests/test_ucli_metrics.py:143) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_shape_and_summary` (py/tests/test_ucli_metrics.py:160) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_since_limit` (py/tests/test_ucli_metrics.py:167) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_errors_and_empty` (py/tests/test_ucli_metrics.py:172) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_sessions` (py/tests/test_ucli_metrics.py:178) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Api.test_authz` (py/tests/test_ucli_metrics.py:182) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Cost.test_measure_cost_10_children` (py/tests/test_ucli_metrics.py:189) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `LateSessionTest.test_new_session_found_while_another_runs` (py/tests/test_ucli_metrics.py:214) | T7: metrik örnekleyici, depo ve uçlar | KAPSAM DIŞI |
| `Routing.test_routed_but_whole_settings_stays_local` (py/tests/test_usage_byok_host_routed.py:15) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Routing.test_byok_needs_admin_config` (py/tests/test_usage_byok_host_routed.py:20) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Routing.test_secret_not_sent_over_plain_http` (py/tests/test_usage_byok_host_routed.py:29) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Routing.test_https_loopback_and_status_read_pass` (py/tests/test_usage_byok_host_routed.py:34) | T5: uzak host yönlendirme | KAPSAM DIŞI |
| `Endpoint.test_set_read_clear_never_echoes_value` (py/tests/test_usage_byok_host_routed.py:51) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `Endpoint.test_rejects_bad_input_without_writing` (py/tests/test_usage_byok_host_routed.py:61) | T7: ayar yazımı ucu (`save_settings`) | KAPSAM DIŞI |
| `StartTests.test_start_ok_folds_task_and_passes_limits` (py/tests/test_web_agents.py:87) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_ask_setting_starts_child_with_ask_dir` (py/tests/test_web_agents.py:96) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_ask_edit_setting_only_for_edit_mode` (py/tests/test_web_agents.py:102) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_child_sink_called_before_register` (py/tests/test_web_agents.py:111) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_child_sink_error_does_not_block_start` (py/tests/test_web_agents.py:120) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_third_live_child_refused` (py/tests/test_web_agents.py:128) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_edit_needs_allow_edit_parent` (py/tests/test_web_agents.py:135) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_validation` (py/tests/test_web_agents.py:144) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_child_cannot_start_and_parent_must_run` (py/tests/test_web_agents.py:150) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_human_needs_parent` (py/tests/test_web_agents.py:157) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_start_failure_releases_and_forgets` (py/tests/test_web_agents.py:161) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_task_not_delivered_stops_child` (py/tests/test_web_agents.py:169) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StartTests.test_disabled` (py/tests/test_web_agents.py:175) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_models` (py/tests/test_web_agents.py:189) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_status_states` (py/tests/test_web_agents.py:193) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_waiting_input_when_child_has_pending_owner_question` (py/tests/test_web_agents.py:205) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_result_is_last_assistant_after_last_user` (py/tests/test_web_agents.py:216) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_result_readable_after_stop` (py/tests/test_web_agents.py:226) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_other_parent_cannot_see_or_touch` (py/tests/test_web_agents.py:232) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `QueryTests.test_send_folds_and_refuses_stopped` (py/tests/test_web_agents.py:240) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_parent_closed_stops_children_and_revokes` (py/tests/test_web_agents.py:249) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_reap_debounces_then_closes_orphans` (py/tests/test_web_agents.py:259) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_reap_keeps_children_when_discovery_fails` (py/tests/test_web_agents.py:267) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `LifecycleTests.test_reap_enforces_cost_cap` (py/tests/test_web_agents.py:274) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_agent_token_maps_to_parent` (py/tests/test_web_agents_glue.py:31) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_panel_token_is_human` (py/tests/test_web_agents_glue.py:34) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_bad_or_missing_token_rejected` (py/tests/test_web_agents_glue.py:37) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_agent_token_is_not_a_panel_token` (py/tests/test_web_agents_glue.py:41) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `CallerTests.test_agents_paths_are_local_only` (py/tests/test_web_agents_glue.py:46) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
| `StopHookTests.test_stop_notifies_agents_for_each_killed_session` (py/tests/test_web_agents_glue.py:52) | T7: alt ajan uçları (`web_agents`) | KAPSAM DIŞI |
