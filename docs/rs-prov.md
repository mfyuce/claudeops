# İz rs/prov: `cops-providers` (W1-pre sağlayıcılar)

Durum (26 Kas 2026, devir): **BİRLEŞTİRMEYE HAZIR DEĞİL.** Kod derleniyor, `cargo clippy -p cops-providers --all-targets -- -D warnings`
temiz, `cargo test -p cops-providers` 2/2 (yalnız `pyfmt`). **Python paritesi HİÇ sınanmadı.**

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
1. `tests/parity.rs`: tek python3 süreci, sahte ikili yardım metinleri, `provider_bin` ayarı; komut dizgisi, yazılan dosyalar ve diag olayları karşılaştırılır.
2. Eşleme tablosunu doldur; eksikleri taşı. Ders listesini karşıla.
3. `cargo fmt --check` şu an farklı (rustfmt.toml yok; satır genişliği elle 120): diğer crate'lerin biçimine bak, karar ver.
4. `lib.rs` testleri: effort, with_block, validate_opts, sır argv'de yok.

## Parite testinde bakılacak bilinen farklar / şüpheler
- `serde_json` anahtar sırası: `ucli_services[].efforts` eşit uzunlukta iki anahtar eşleşirse Python ekleme sırası, Rust alfabetik; 20 üstü kırpma da sıraya bağlı.
  `byok.copilot` env dosyasındaki satır sırası da aynı sebeple farklı olabilir (`preserve_order` açılırsa tüm workspace etkilenir; cops-state ile eşgüdüm).
- `re:` komut desenleri `fancy-regex`: Python `re` hata metni ve bazı sözdizimi farklı.
- `ucli_mcp_registered` diag olayı ve `register_mcp` hata alanları Rust'ta çağırana bırakıldı/eksik.
- Mutasyonlar `Effect` olduğundan Python'da yazım hatasının komutu değiştirdiği dallar (anahtar dosyası yazılamazsa istisna, metrics mkdir hatası = bayrak yok) çağıran sözleşmesine kaldı.
- `str(dict/list)` Python repr yerine JSON metni (yalnız bozuk ayarda).
- `_MCP_TOOL_RE` Python `$` sondaki satır sonunu kabul eder, Rust etmez: Python hatası? (sor).
- Henüz taşınmayan: `_dry_run` dışı `spawn.py` akışı (gnome fallback/watchdog, hayalet oturum), `sync_global_files` dosya işlemleri (yalnız karar `sync_plan`).

## Sır / argv notları (Python'a dokunulmadı)
- `spawn.py`: `env_overrides` + kanca ortamı `KEY=VAL` olarak komut satırına gömülür (tmux argv). Kanca bir API anahtarı döndürürse argv'ye girer;
  yalnız dry-run satırı maskeliyor. Bugünkü sağlayıcı override'ları sır içermiyor. Sorulacak/izlenecek.
- ucli anahtarı argv'de değil (`$(cat dosya)`); ancak `UCLI_API_KEY="$(cat {_API_KEY_FILE})"` yolunda tırnaklama yok (boşluklu HOME'da kırılır): Python hatası?
- copilot BYOK: dosya source edilir, argv temiz.

## EŞLEME TABLOSU (iskelet; ast ile üretildi, hepsi AÇIK)

`settings.py`, `ucli_client.py`, `ucli_cost/ask/agents/checks/metrics`, `paths.py`, `steward.main_session_model_effort` içinden kullanılan işlevlerin satırları da eklenecek (burada yok).

| Python (dosya:satır) | Rust karşılığı | parite testi | durum |
|---|---|---|---|
| `DEFAULT_CLI` (py/claudeops/providers/__init__.py:14) | | | AÇIK |
| `PROVIDERS` (py/claudeops/providers/__init__.py:16) | | | AÇIK |
| `get_provider` (py/claudeops/providers/__init__.py:26) | | | AÇIK |
| `CONVERSATIONS_CACHE` (py/claudeops/providers/agy_provider.py:84) | | | AÇIK |
| `CONVERSATIONS_DIR` (py/claudeops/providers/agy_provider.py:85) | | | AÇIK |
| `AGY_SIDS_JSON` (py/claudeops/providers/agy_provider.py:94) | | | AÇIK |
| `_STEP_TYPE_USER` (py/claudeops/providers/agy_provider.py:98) | | | AÇIK |
| `_STEP_TYPE_ASSISTANT` (py/claudeops/providers/agy_provider.py:99) | | | AÇIK |
| `_STEP_TYPE_CHECKPOINT` (py/claudeops/providers/agy_provider.py:101) | | | AÇIK |
| `_read_varint` (py/claudeops/providers/agy_provider.py:104) | | | AÇIK |
| `_iter_fields` (py/claudeops/providers/agy_provider.py:116) | | | AÇIK |
| `_get_bytes_field` (py/claudeops/providers/agy_provider.py:144) | | | AÇIK |
| `_get_text_field` (py/claudeops/providers/agy_provider.py:160) | | | AÇIK |
| `_step_user_text` (py/claudeops/providers/agy_provider.py:165) | | | AÇIK |
| `_step_assistant_text` (py/claudeops/providers/agy_provider.py:172) | | | AÇIK |
| `_conversation_ids` (py/claudeops/providers/agy_provider.py:179) | | | AÇIK |
| `PERMISSION_MODES` (py/claudeops/providers/agy_provider.py:187) | | | AÇIK |
| `EFFORT_LEVELS` (py/claudeops/providers/agy_provider.py:188) | | | AÇIK |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/agy_provider.py:195) | | | AÇIK |
| `_PERMISSION_FLAGS` (py/claudeops/providers/agy_provider.py:197) | | | AÇIK |
| `_MODELS_TTL` (py/claudeops/providers/agy_provider.py:203) | | | AÇIK |
| `_load_agy_sids` (py/claudeops/providers/agy_provider.py:206) | | | AÇIK |
| `_remember_agy_sid` (py/claudeops/providers/agy_provider.py:215) | | | AÇIK |
| `_sid_claimed_by_other` (py/claudeops/providers/agy_provider.py:230) | | | AÇIK |
| `AgyProvider` (py/claudeops/providers/agy_provider.py:237) | | | AÇIK |
| `AgyProvider.name` (py/claudeops/providers/agy_provider.py:238) | | | AÇIK |
| `AgyProvider.__init__` (py/claudeops/providers/agy_provider.py:240) | | | AÇIK |
| `AgyProvider.resolve_resume_id` (py/claudeops/providers/agy_provider.py:244) | | | AÇIK |
| `AgyProvider.build_inner_command` (py/claudeops/providers/agy_provider.py:271) | | | AÇIK |
| `AgyProvider.env_overrides` (py/claudeops/providers/agy_provider.py:320) | | | AÇIK |
| `AgyProvider.mcp_setup_command` (py/claudeops/providers/agy_provider.py:323) | | | AÇIK |
| `AgyProvider.matches_proc` (py/claudeops/providers/agy_provider.py:333) | | | AÇIK |
| `AgyProvider.extract_name` (py/claudeops/providers/agy_provider.py:336) | | | AÇIK |
| `AgyProvider.extract_info` (py/claudeops/providers/agy_provider.py:343) | | | AÇIK |
| `AgyProvider._fetch_models` (py/claudeops/providers/agy_provider.py:380) | | | AÇIK |
| `AgyProvider.model_choices` (py/claudeops/providers/agy_provider.py:394) | | | AÇIK |
| `AgyProvider.permission_modes` (py/claudeops/providers/agy_provider.py:411) | | | AÇIK |
| `AgyProvider.effort_levels` (py/claudeops/providers/agy_provider.py:414) | | | AÇIK |
| `AgyProvider.model_effort_levels` (py/claudeops/providers/agy_provider.py:417) | | | AÇIK |
| `AgyProvider.busy_status_pattern` (py/claudeops/providers/agy_provider.py:430) | | | AÇIK |
| `AgyProvider.usage_command` (py/claudeops/providers/agy_provider.py:433) | | | AÇIK |
| `AgyProvider.usage_fresh_argv` (py/claudeops/providers/agy_provider.py:444) | | | AÇIK |
| `AgyProvider.usage_auth_missing` (py/claudeops/providers/agy_provider.py:449) | | | AÇIK |
| `AgyProvider.parse_fresh_usage` (py/claudeops/providers/agy_provider.py:454) | | | AÇIK |
| `AgyProvider.usage_needs_dismiss` (py/claudeops/providers/agy_provider.py:457) | | | AÇIK |
| `AgyProvider.parse_usage_text` (py/claudeops/providers/agy_provider.py:467) | | | AÇIK |
| `AgyProvider._transcript_steps` (py/claudeops/providers/agy_provider.py:498) | | | AÇIK |
| `AgyProvider._steps_desc` (py/claudeops/providers/agy_provider.py:528) | | | AÇIK |
| `AgyProvider.last_exchange` (py/claudeops/providers/agy_provider.py:554) | | | AÇIK |
| `AgyProvider.full_history` (py/claudeops/providers/agy_provider.py:573) | | | AÇIK |
| `AgyProvider.sid_for_stopped_session` (py/claudeops/providers/agy_provider.py:591) | | | AÇIK |
| `AgyProvider.snapshot_for_live_sid` (py/claudeops/providers/agy_provider.py:601) | | | AÇIK |
| `AgyProvider.discover_live_sid` (py/claudeops/providers/agy_provider.py:611) | | | AÇIK |
| `cmd_arg` (py/claudeops/providers/base.py:20) | | | AÇIK |
| `OneshotError` (py/claudeops/providers/base.py:28) | | | AÇIK |
| `McpServerSpec` (py/claudeops/providers/base.py:33) | | | AÇIK |
| `McpServerSpec.name` (py/claudeops/providers/base.py:44) | | | AÇIK |
| `McpServerSpec.command` (py/claudeops/providers/base.py:45) | | | AÇIK |
| `McpServerSpec.args` (py/claudeops/providers/base.py:46) | | | AÇIK |
| `McpServerSpec.allowed_tools` (py/claudeops/providers/base.py:49) | | | AÇIK |
| `CliProvider` (py/claudeops/providers/base.py:52) | | | AÇIK |
| `CliProvider.name` (py/claudeops/providers/base.py:53) | | | AÇIK |
| `CliProvider.accepts_cli_opts` (py/claudeops/providers/base.py:57) | | | AÇIK |
| `CliProvider.mcp_needs_cwd` (py/claudeops/providers/base.py:61) | | | AÇIK |
| `CliProvider.validate_cli_opts` (py/claudeops/providers/base.py:63) | | | AÇIK |
| `CliProvider.resolve_resume_id` (py/claudeops/providers/base.py:70) | | | AÇIK |
| `CliProvider.build_inner_command` (py/claudeops/providers/base.py:92) | | | AÇIK |
| `CliProvider.has_conversation` (py/claudeops/providers/base.py:113) | | | AÇIK |
| `CliProvider.wants_handover_wrapup` (py/claudeops/providers/base.py:121) | | | AÇIK |
| `CliProvider.wants_stuck_recovery` (py/claudeops/providers/base.py:125) | | | AÇIK |
| `CliProvider.last_exchange` (py/claudeops/providers/base.py:129) | | | AÇIK |
| `CliProvider.full_history` (py/claudeops/providers/base.py:138) | | | AÇIK |
| `CliProvider.sid_for_stopped_session` (py/claudeops/providers/base.py:147) | | | AÇIK |
| `CliProvider.last_message_role` (py/claudeops/providers/base.py:162) | | | AÇIK |
| `CliProvider.handover_model_downgrade` (py/claudeops/providers/base.py:175) | | | AÇIK |
| `CliProvider.apply_live_model_switch` (py/claudeops/providers/base.py:185) | | | AÇIK |
| `CliProvider.handover_effort_downgrade` (py/claudeops/providers/base.py:193) | | | AÇIK |
| `CliProvider.apply_live_effort_switch` (py/claudeops/providers/base.py:200) | | | AÇIK |
| `CliProvider.prompt_cache_ttl_seconds` (py/claudeops/providers/base.py:206) | | | AÇIK |
| `CliProvider.last_request_epoch` (py/claudeops/providers/base.py:218) | | | AÇIK |
| `CliProvider.effort_switch_keeps_cache` (py/claudeops/providers/base.py:226) | | | AÇIK |
| `CliProvider.dismiss_stray_dialog` (py/claudeops/providers/base.py:233) | | | AÇIK |
| `CliProvider.input_settle_delay` (py/claudeops/providers/base.py:252) | | | AÇIK |
| `CliProvider.prepare_input` (py/claudeops/providers/base.py:264) | | | AÇIK |
| `CliProvider.compact_command` (py/claudeops/providers/base.py:269) | | | AÇIK |
| `CliProvider.usage_fresh_argv` (py/claudeops/providers/base.py:284) | | | AÇIK |
| `CliProvider.usage_fresh_tui_argv` (py/claudeops/providers/base.py:290) | | | AÇIK |
| `CliProvider.usage_auth_missing` (py/claudeops/providers/base.py:295) | | | AÇIK |
| `CliProvider.parse_fresh_usage` (py/claudeops/providers/base.py:299) | | | AÇIK |
| `CliProvider.usage_command` (py/claudeops/providers/base.py:303) | | | AÇIK |
| `CliProvider.parse_usage_text` (py/claudeops/providers/base.py:319) | | | AÇIK |
| `CliProvider.context_command` (py/claudeops/providers/base.py:330) | | | AÇIK |
| `CliProvider.parse_context_text` (py/claudeops/providers/base.py:344) | | | AÇIK |
| `CliProvider.context_needs_dismiss` (py/claudeops/providers/base.py:356) | | | AÇIK |
| `CliProvider.usage_needs_dismiss` (py/claudeops/providers/base.py:367) | | | AÇIK |
| `CliProvider.extra_file_roots` (py/claudeops/providers/base.py:379) | | | AÇIK |
| `CliProvider.env_overrides` (py/claudeops/providers/base.py:394) | | | AÇIK |
| `CliProvider.mcp_launch_args` (py/claudeops/providers/base.py:410) | | | AÇIK |
| `CliProvider.mcp_setup_command` (py/claudeops/providers/base.py:421) | | | AÇIK |
| `CliProvider.oneshot_argv` (py/claudeops/providers/base.py:433) | | | AÇIK |
| `CliProvider.oneshot` (py/claudeops/providers/base.py:440) | | | AÇIK |
| `CliProvider.matches_proc` (py/claudeops/providers/base.py:464) | | | AÇIK |
| `CliProvider.extract_name` (py/claudeops/providers/base.py:468) | | | AÇIK |
| `CliProvider.extract_info` (py/claudeops/providers/base.py:473) | | | AÇIK |
| `CliProvider.model_choices` (py/claudeops/providers/base.py:485) | | | AÇIK |
| `CliProvider.refresh_stored_model` (py/claudeops/providers/base.py:488) | | | AÇIK |
| `CliProvider.permission_modes` (py/claudeops/providers/base.py:497) | | | AÇIK |
| `CliProvider.effort_levels` (py/claudeops/providers/base.py:501) | | | AÇIK |
| `CliProvider.model_effort_levels` (py/claudeops/providers/base.py:504) | | | AÇIK |
| `CliProvider.effort_levels_for` (py/claudeops/providers/base.py:514) | | | AÇIK |
| `CliProvider.default_permission_mode` (py/claudeops/providers/base.py:520) | | | AÇIK |
| `CliProvider.preferred_default_model` (py/claudeops/providers/base.py:525) | | | AÇIK |
| `CliProvider.default_effort` (py/claudeops/providers/base.py:530) | | | AÇIK |
| `CliProvider.resolve_effort` (py/claudeops/providers/base.py:536) | | | AÇIK |
| `CliProvider.mode_status_patterns` (py/claudeops/providers/base.py:548) | | | AÇIK |
| `CliProvider.busy_status_pattern` (py/claudeops/providers/base.py:555) | | | AÇIK |
| `CliProvider.background_work` (py/claudeops/providers/base.py:565) | | | AÇIK |
| `CliProvider.live_busy` (py/claudeops/providers/base.py:571) | | | AÇIK |
| `CliProvider.live_tools` (py/claudeops/providers/base.py:584) | | | AÇIK |
| `CliProvider.live_context` (py/claudeops/providers/base.py:589) | | | AÇIK |
| `CliProvider.live_usage` (py/claudeops/providers/base.py:596) | | | AÇIK |
| `CliProvider.live_failed_turns` (py/claudeops/providers/base.py:606) | | | AÇIK |
| `CliProvider.live_phase` (py/claudeops/providers/base.py:611) | | | AÇIK |
| `CliProvider.cyclable_modes` (py/claudeops/providers/base.py:620) | | | AÇIK |
| `CliProvider.snapshot_for_live_sid` (py/claudeops/providers/base.py:629) | | | AÇIK |
| `CliProvider.discover_live_sid` (py/claudeops/providers/base.py:650) | | | AÇIK |
| `MODEL_CHOICES` (py/claudeops/providers/claude_provider.py:18) | | | AÇIK |
| `PERMISSION_MODES` (py/claudeops/providers/claude_provider.py:24) | | | AÇIK |
| `EFFORT_LEVELS` (py/claudeops/providers/claude_provider.py:25) | | | AÇIK |
| `_SONNET_PIN_RE` (py/claudeops/providers/claude_provider.py:29) | | | AÇIK |
| `_sonnet_version` (py/claudeops/providers/claude_provider.py:32) | | | AÇIK |
| `_USAGE_HEADER_RE` (py/claudeops/providers/claude_provider.py:39) | | | AÇIK |
| `_USAGE_PERCENT_RE` (py/claudeops/providers/claude_provider.py:40) | | | AÇIK |
| `_USAGE_RESETS_RE` (py/claudeops/providers/claude_provider.py:41) | | | AÇIK |
| `_USAGE_FRESH_RE` (py/claudeops/providers/claude_provider.py:43) | | | AÇIK |
| `_CONTEXT_TOTAL_RE` (py/claudeops/providers/claude_provider.py:48) | | | AÇIK |
| `_CONTEXT_CATEGORY_RE` (py/claudeops/providers/claude_provider.py:49) | | | AÇIK |
| `MODE_STATUS_PATTERNS` (py/claudeops/providers/claude_provider.py:61) | | | AÇIK |
| `CYCLABLE_MODES` (py/claudeops/providers/claude_provider.py:73) | | | AÇIK |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/claude_provider.py:80) | | | AÇIK |
| `_encode_cwd` (py/claudeops/providers/claude_provider.py:83) | | | AÇIK |
| `_safe_mtime` (py/claudeops/providers/claude_provider.py:102) | | | AÇIK |
| `jsonl_path_for` (py/claudeops/providers/claude_provider.py:110) | | | AÇIK |
| `find_latest_jsonl` (py/claudeops/providers/claude_provider.py:125) | | | AÇIK |
| `_LAST_MODEL_CHUNK_BYTES` (py/claudeops/providers/claude_provider.py:143) | | | AÇIK |
| `_LAST_MODEL_MAX_BYTES` (py/claudeops/providers/claude_provider.py:144) | | | AÇIK |
| `_row_epoch` (py/claudeops/providers/claude_provider.py:147) | | | AÇIK |
| `_last_assistant_value` (py/claudeops/providers/claude_provider.py:158) | | | AÇIK |
| `last_assistant_model` (py/claudeops/providers/claude_provider.py:208) | | | AÇIK |
| `last_assistant_effort` (py/claudeops/providers/claude_provider.py:214) | | | AÇIK |
| `PROMPT_CACHE_TTL_SECONDS` (py/claudeops/providers/claude_provider.py:228) | | | AÇIK |
| `_real_request_epoch` (py/claudeops/providers/claude_provider.py:231) | | | AÇIK |
| `last_real_request_epoch` (py/claudeops/providers/claude_provider.py:254) | | | AÇIK |
| `session_file_sid` (py/claudeops/providers/claude_provider.py:260) | | | AÇIK |
| `_EFFORT_BUSTS_CACHE_RE` (py/claudeops/providers/claude_provider.py:293) | | | AÇIK |
| `live_or_spawn_model` (py/claudeops/providers/claude_provider.py:296) | | | AÇIK |
| `live_or_spawn_effort` (py/claudeops/providers/claude_provider.py:315) | | | AÇIK |
| `_META_HEAD_LINES` (py/claudeops/providers/claude_provider.py:331) | | | AÇIK |
| `_RESUME_SCAN_LIMIT` (py/claudeops/providers/claude_provider.py:334) | | | AÇIK |
| `_jsonl_meta` (py/claudeops/providers/claude_provider.py:337) | | | AÇIK |
| `_same_path` (py/claudeops/providers/claude_provider.py:364) | | | AÇIK |
| `_META_CACHE` (py/claudeops/providers/claude_provider.py:372) | | | AÇIK |
| `_META_CACHE_MAX` (py/claudeops/providers/claude_provider.py:373) | | | AÇIK |
| `_jsonl_meta_cached` (py/claudeops/providers/claude_provider.py:376) | | | AÇIK |
| `_STUB_MAX_BYTES` (py/claudeops/providers/claude_provider.py:391) | | | AÇIK |
| `_has_chat_rows` (py/claudeops/providers/claude_provider.py:394) | | | AÇIK |
| `MCP_CONFIG_PATH` (py/claudeops/providers/claude_provider.py:414) | | | AÇIK |
| `_mcp_config_path` (py/claudeops/providers/claude_provider.py:417) | | | AÇIK |
| `_write_mcp_config_file` (py/claudeops/providers/claude_provider.py:431) | | | AÇIK |
| `_extract_text` (py/claudeops/providers/claude_provider.py:440) | | | AÇIK |
| `_is_real_user_text` (py/claudeops/providers/claude_provider.py:452) | | | AÇIK |
| `_HELP_CACHE` (py/claudeops/providers/claude_provider.py:466) | | | AÇIK |
| `_HELP_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:467) | | | AÇIK |
| `claude_help_text` (py/claudeops/providers/claude_provider.py:470) | | | AÇIK |
| `claude_supports_flag` (py/claudeops/providers/claude_provider.py:492) | | | AÇIK |
| `ClaudeProvider` (py/claudeops/providers/claude_provider.py:498) | | | AÇIK |
| `ClaudeProvider.name` (py/claudeops/providers/claude_provider.py:499) | | | AÇIK |
| `ClaudeProvider.resolve_resume_id` (py/claudeops/providers/claude_provider.py:501) | | | AÇIK |
| `ClaudeProvider.build_inner_command` (py/claudeops/providers/claude_provider.py:545) | | | AÇIK |
| `ClaudeProvider.oneshot_argv` (py/claudeops/providers/claude_provider.py:586) | | | AÇIK |
| `ClaudeProvider.mcp_launch_args` (py/claudeops/providers/claude_provider.py:602) | | | AÇIK |
| `ClaudeProvider.compact_command` (py/claudeops/providers/claude_provider.py:610) | | | AÇIK |
| `ClaudeProvider.usage_command` (py/claudeops/providers/claude_provider.py:613) | | | AÇIK |
| `ClaudeProvider.usage_needs_dismiss` (py/claudeops/providers/claude_provider.py:616) | | | AÇIK |
| `ClaudeProvider.parse_usage_text` (py/claudeops/providers/claude_provider.py:624) | | | AÇIK |
| `ClaudeProvider.usage_fresh_argv` (py/claudeops/providers/claude_provider.py:666) | | | AÇIK |
| `ClaudeProvider.parse_fresh_usage` (py/claudeops/providers/claude_provider.py:669) | | | AÇIK |
| `ClaudeProvider.context_command` (py/claudeops/providers/claude_provider.py:678) | | | AÇIK |
| `ClaudeProvider.context_needs_dismiss` (py/claudeops/providers/claude_provider.py:681) | | | AÇIK |
| `ClaudeProvider.parse_context_text` (py/claudeops/providers/claude_provider.py:687) | | | AÇIK |
| `ClaudeProvider.handover_model_downgrade` (py/claudeops/providers/claude_provider.py:744) | | | AÇIK |
| `ClaudeProvider._MODEL_SWITCH_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:761) | | | AÇIK |
| `ClaudeProvider._MODEL_SWITCH_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:762) | | | AÇIK |
| `ClaudeProvider.apply_live_model_switch` (py/claudeops/providers/claude_provider.py:764) | | | AÇIK |
| `ClaudeProvider.handover_effort_downgrade` (py/claudeops/providers/claude_provider.py:824) | | | AÇIK |
| `ClaudeProvider.prompt_cache_ttl_seconds` (py/claudeops/providers/claude_provider.py:837) | | | AÇIK |
| `ClaudeProvider.last_request_epoch` (py/claudeops/providers/claude_provider.py:840) | | | AÇIK |
| `ClaudeProvider.effort_switch_keeps_cache` (py/claudeops/providers/claude_provider.py:859) | | | AÇIK |
| `ClaudeProvider._EFFORT_SWITCH_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:862) | | | AÇIK |
| `ClaudeProvider._EFFORT_SWITCH_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:863) | | | AÇIK |
| `ClaudeProvider._EFFORT_SWITCH_DONE_MARKERS` (py/claudeops/providers/claude_provider.py:864) | | | AÇIK |
| `ClaudeProvider.apply_live_effort_switch` (py/claudeops/providers/claude_provider.py:867) | | | AÇIK |
| `ClaudeProvider._STRAY_DIALOG_TIMEOUT_SECONDS` (py/claudeops/providers/claude_provider.py:926) | | | AÇIK |
| `ClaudeProvider._STRAY_DIALOG_POLL_SECONDS` (py/claudeops/providers/claude_provider.py:927) | | | AÇIK |
| `ClaudeProvider.dismiss_stray_dialog` (py/claudeops/providers/claude_provider.py:929) | | | AÇIK |
| `ClaudeProvider.matches_proc` (py/claudeops/providers/claude_provider.py:970) | | | AÇIK |
| `ClaudeProvider.extract_name` (py/claudeops/providers/claude_provider.py:975) | | | AÇIK |
| `ClaudeProvider.extract_info` (py/claudeops/providers/claude_provider.py:978) | | | AÇIK |
| `ClaudeProvider.preferred_default_model` (py/claudeops/providers/claude_provider.py:986) | | | AÇIK |
| `ClaudeProvider.default_effort` (py/claudeops/providers/claude_provider.py:992) | | | AÇIK |
| `ClaudeProvider.model_choices` (py/claudeops/providers/claude_provider.py:995) | | | AÇIK |
| `ClaudeProvider.refresh_stored_model` (py/claudeops/providers/claude_provider.py:1010) | | | AÇIK |
| `ClaudeProvider.permission_modes` (py/claudeops/providers/claude_provider.py:1029) | | | AÇIK |
| `ClaudeProvider.effort_levels` (py/claudeops/providers/claude_provider.py:1032) | | | AÇIK |
| `ClaudeProvider.mode_status_patterns` (py/claudeops/providers/claude_provider.py:1035) | | | AÇIK |
| `ClaudeProvider.background_work` (py/claudeops/providers/claude_provider.py:1038) | | | AÇIK |
| `ClaudeProvider.busy_status_pattern` (py/claudeops/providers/claude_provider.py:1048) | | | AÇIK |
| `ClaudeProvider.cyclable_modes` (py/claudeops/providers/claude_provider.py:1051) | | | AÇIK |
| `ClaudeProvider._transcript_lines` (py/claudeops/providers/claude_provider.py:1054) | | | AÇIK |
| `ClaudeProvider.last_exchange` (py/claudeops/providers/claude_provider.py:1080) | | | AÇIK |
| `ClaudeProvider.extra_file_roots` (py/claudeops/providers/claude_provider.py:1110) | | | AÇIK |
| `ClaudeProvider.full_history` (py/claudeops/providers/claude_provider.py:1115) | | | AÇIK |
| `ClaudeProvider.sid_for_stopped_session` (py/claudeops/providers/claude_provider.py:1144) | | | AÇIK |
| `CODEX_HOME` (py/claudeops/providers/codex_provider.py:42) | | | AÇIK |
| `SESSIONS_DIR` (py/claudeops/providers/codex_provider.py:43) | | | AÇIK |
| `MODELS_CACHE` (py/claudeops/providers/codex_provider.py:44) | | | AÇIK |
| `PERMISSION_MODES` (py/claudeops/providers/codex_provider.py:46) | | | AÇIK |
| `EFFORT_LEVELS` (py/claudeops/providers/codex_provider.py:47) | | | AÇIK |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/codex_provider.py:58) | | | AÇIK |
| `FALLBACK_MODELS` (py/claudeops/providers/codex_provider.py:62) | | | AÇIK |
| `_NON_SESSION_SUBCOMMANDS` (py/claudeops/providers/codex_provider.py:77) | | | AÇIK |
| `_PERMISSION_FLAGS` (py/claudeops/providers/codex_provider.py:84) | | | AÇIK |
| `_MODELS_TTL` (py/claudeops/providers/codex_provider.py:91) | | | AÇIK |
| `_ROLLOUT_UUID_RE` (py/claudeops/providers/codex_provider.py:92) | | | AÇIK |
| `_MAX_ROLLOUT_SCAN` (py/claudeops/providers/codex_provider.py:93) | | | AÇIK |
| `_config_value` (py/claudeops/providers/codex_provider.py:96) | | | AÇIK |
| `_safe_mtime` (py/claudeops/providers/codex_provider.py:104) | | | AÇIK |
| `_session_meta` (py/claudeops/providers/codex_provider.py:111) | | | AÇIK |
| `_codex_text` (py/claudeops/providers/codex_provider.py:125) | | | AÇIK |
| `_is_real_codex_user_text` (py/claudeops/providers/codex_provider.py:139) | | | AÇIK |
| `CodexProvider` (py/claudeops/providers/codex_provider.py:148) | | | AÇIK |
| `CodexProvider.name` (py/claudeops/providers/codex_provider.py:149) | | | AÇIK |
| `CodexProvider.__init__` (py/claudeops/providers/codex_provider.py:151) | | | AÇIK |
| `CodexProvider.resolve_resume_id` (py/claudeops/providers/codex_provider.py:155) | | | AÇIK |
| `CodexProvider.build_inner_command` (py/claudeops/providers/codex_provider.py:178) | | | AÇIK |
| `CodexProvider.mcp_launch_args` (py/claudeops/providers/codex_provider.py:196) | | | AÇIK |
| `CodexProvider.env_overrides` (py/claudeops/providers/codex_provider.py:207) | | | AÇIK |
| `CodexProvider.matches_proc` (py/claudeops/providers/codex_provider.py:210) | | | AÇIK |
| `CodexProvider.extract_name` (py/claudeops/providers/codex_provider.py:218) | | | AÇIK |
| `CodexProvider.extract_info` (py/claudeops/providers/codex_provider.py:225) | | | AÇIK |
| `CodexProvider.model_choices` (py/claudeops/providers/codex_provider.py:246) | | | AÇIK |
| `CodexProvider.permission_modes` (py/claudeops/providers/codex_provider.py:265) | | | AÇIK |
| `CodexProvider.effort_levels` (py/claudeops/providers/codex_provider.py:268) | | | AÇIK |
| `CodexProvider.model_effort_levels` (py/claudeops/providers/codex_provider.py:271) | | | AÇIK |
| `CodexProvider.busy_status_pattern` (py/claudeops/providers/codex_provider.py:292) | | | AÇIK |
| `CodexProvider.input_settle_delay` (py/claudeops/providers/codex_provider.py:295) | | | AÇIK |
| `CodexProvider.background_work` (py/claudeops/providers/codex_provider.py:306) | | | AÇIK |
| `CodexProvider._rollout_path` (py/claudeops/providers/codex_provider.py:317) | | | AÇIK |
| `CodexProvider._transcript_lines` (py/claudeops/providers/codex_provider.py:336) | | | AÇIK |
| `CodexProvider.live_context` (py/claudeops/providers/codex_provider.py:358) | | | AÇIK |
| `CodexProvider.last_exchange` (py/claudeops/providers/codex_provider.py:385) | | | AÇIK |
| `CodexProvider.full_history` (py/claudeops/providers/codex_provider.py:410) | | | AÇIK |
| `SESSION_STORE_DB` (py/claudeops/providers/copilot_provider.py:107) | | | AÇIK |
| `_BYOK_ENV_FILE` (py/claudeops/providers/copilot_provider.py:119) | | | AÇIK |
| `_BYOK_ENV_MANAGED_MARKER` (py/claudeops/providers/copilot_provider.py:120) | | | AÇIK |
| `_sync_byok_env_file` (py/claudeops/providers/copilot_provider.py:123) | | | AÇIK |
| `MODEL_CHOICES` (py/claudeops/providers/copilot_provider.py:157) | | | AÇIK |
| `PERMISSION_MODES` (py/claudeops/providers/copilot_provider.py:176) | | | AÇIK |
| `EFFORT_LEVELS` (py/claudeops/providers/copilot_provider.py:177) | | | AÇIK |
| `MODE_STATUS_PATTERNS` (py/claudeops/providers/copilot_provider.py:183) | | | AÇIK |
| `BUSY_STATUS_PATTERN` (py/claudeops/providers/copilot_provider.py:187) | | | AÇIK |
| `_PERMISSION_FLAGS` (py/claudeops/providers/copilot_provider.py:189) | | | AÇIK |
| `_RESUME_SCAN_LIMIT` (py/claudeops/providers/copilot_provider.py:196) | | | AÇIK |
| `_USAGE_PLAN_RE` (py/claudeops/providers/copilot_provider.py:205) | | | AÇIK |
| `_USAGE_FRACTION_RE` (py/claudeops/providers/copilot_provider.py:206) | | | AÇIK |
| `_USAGE_RESET_RE` (py/claudeops/providers/copilot_provider.py:207) | | | AÇIK |
| `trust_folder` (py/claudeops/providers/copilot_provider.py:210) | | | AÇIK |
| `_connect_ro` (py/claudeops/providers/copilot_provider.py:232) | | | AÇIK |
| `CopilotProvider` (py/claudeops/providers/copilot_provider.py:239) | | | AÇIK |
| `CopilotProvider.name` (py/claudeops/providers/copilot_provider.py:240) | | | AÇIK |
| `CopilotProvider.resolve_resume_id` (py/claudeops/providers/copilot_provider.py:242) | | | AÇIK |
| `CopilotProvider.build_inner_command` (py/claudeops/providers/copilot_provider.py:270) | | | AÇIK |
| `CopilotProvider.env_overrides` (py/claudeops/providers/copilot_provider.py:297) | | | AÇIK |
| `CopilotProvider.matches_proc` (py/claudeops/providers/copilot_provider.py:303) | | | AÇIK |
| `CopilotProvider.extract_name` (py/claudeops/providers/copilot_provider.py:322) | | | AÇIK |
| `CopilotProvider.extract_info` (py/claudeops/providers/copilot_provider.py:329) | | | AÇIK |
| `CopilotProvider.model_choices` (py/claudeops/providers/copilot_provider.py:345) | | | AÇIK |
| `CopilotProvider.permission_modes` (py/claudeops/providers/copilot_provider.py:348) | | | AÇIK |
| `CopilotProvider.effort_levels` (py/claudeops/providers/copilot_provider.py:351) | | | AÇIK |
| `CopilotProvider.mode_status_patterns` (py/claudeops/providers/copilot_provider.py:354) | | | AÇIK |
| `CopilotProvider.busy_status_pattern` (py/claudeops/providers/copilot_provider.py:357) | | | AÇIK |
| `CopilotProvider.usage_command` (py/claudeops/providers/copilot_provider.py:360) | | | AÇIK |
| `CopilotProvider.parse_usage_text` (py/claudeops/providers/copilot_provider.py:369) | | | AÇIK |
| `CopilotProvider.usage_fresh_tui_argv` (py/claudeops/providers/copilot_provider.py:380) | | | AÇIK |
| `CopilotProvider._turns` (py/claudeops/providers/copilot_provider.py:384) | | | AÇIK |
| `CopilotProvider.live_context` (py/claudeops/providers/copilot_provider.py:407) | | | AÇIK |
| `CopilotProvider.last_exchange` (py/claudeops/providers/copilot_provider.py:425) | | | AÇIK |
| `CopilotProvider.full_history` (py/claudeops/providers/copilot_provider.py:434) | | | AÇIK |
| `PROC_TAG` (py/claudeops/providers/shell_provider.py:31) | | | AÇIK |
| `_SENTINEL` (py/claudeops/providers/shell_provider.py:38) | | | AÇIK |
| `ShellProvider` (py/claudeops/providers/shell_provider.py:41) | | | AÇIK |
| `ShellProvider.name` (py/claudeops/providers/shell_provider.py:42) | | | AÇIK |
| `ShellProvider.has_conversation` (py/claudeops/providers/shell_provider.py:44) | | | AÇIK |
| `ShellProvider.resolve_resume_id` (py/claudeops/providers/shell_provider.py:47) | | | AÇIK |
| `ShellProvider.build_inner_command` (py/claudeops/providers/shell_provider.py:51) | | | AÇIK |
| `ShellProvider.env_overrides` (py/claudeops/providers/shell_provider.py:58) | | | AÇIK |
| `ShellProvider.matches_proc` (py/claudeops/providers/shell_provider.py:61) | | | AÇIK |
| `ShellProvider.extract_name` (py/claudeops/providers/shell_provider.py:64) | | | AÇIK |
| `ShellProvider.extract_info` (py/claudeops/providers/shell_provider.py:70) | | | AÇIK |
| `ShellProvider.model_choices` (py/claudeops/providers/shell_provider.py:73) | | | AÇIK |
| `ShellProvider.permission_modes` (py/claudeops/providers/shell_provider.py:76) | | | AÇIK |
| `ShellProvider.effort_levels` (py/claudeops/providers/shell_provider.py:79) | | | AÇIK |
| `_EFFORT_LIMITS` (py/claudeops/providers/ucli_provider.py:153) | | | AÇIK |
| `_EFFORT_LEVELS` (py/claudeops/providers/ucli_provider.py:157) | | | AÇIK |
| `_REQUEST_TIMEOUT_SECS` (py/claudeops/providers/ucli_provider.py:167) | | | AÇIK |
| `_MAX_HISTORY_KIB` (py/claudeops/providers/ucli_provider.py:173) | | | AÇIK |
| `_USAGE_FIELDS` (py/claudeops/providers/ucli_provider.py:178) | | | AÇIK |
| `_PHASE_INT_FIELDS` (py/claudeops/providers/ucli_provider.py:182) | | | AÇIK |
| `_READ_ONLY` (py/claudeops/providers/ucli_provider.py:187) | | | AÇIK |
| `_ALLOW_EDIT` (py/claudeops/providers/ucli_provider.py:188) | | | AÇIK |
| `_ALLOW_CREATE` (py/claudeops/providers/ucli_provider.py:192) | | | AÇIK |
| `_PERMISSION_MODES` (py/claudeops/providers/ucli_provider.py:193) | | | AÇIK |
| `_MODEL_CHOICES` (py/claudeops/providers/ucli_provider.py:201) | | | AÇIK |
| `DEFAULT_ENDPOINT` (py/claudeops/providers/ucli_provider.py:202) | | | AÇIK |
| `_ENDPOINT` (py/claudeops/providers/ucli_provider.py:203) | | | AÇIK |
| `endpoint` (py/claudeops/providers/ucli_provider.py:206) | | | AÇIK |
| `_MODELS_TTL` (py/claudeops/providers/ucli_provider.py:221) | | | AÇIK |
| `_LIVE_MODEL_CACHE` (py/claudeops/providers/ucli_provider.py:222) | | | AÇIK |
| `_LIVE_MODEL_CACHE_TS` (py/claudeops/providers/ucli_provider.py:223) | | | AÇIK |
| `_LIVE_CAPS` (py/claudeops/providers/ucli_provider.py:226) | | | AÇIK |
| `_fetch_live_models` (py/claudeops/providers/ucli_provider.py:229) | | | AÇIK |
| `_live_models` (py/claudeops/providers/ucli_provider.py:266) | | | AÇIK |
| `reasoning_effort_for` (py/claudeops/providers/ucli_provider.py:283) | | | AÇIK |
| `_API_KEY_FILE` (py/claudeops/providers/ucli_provider.py:307) | | | AÇIK |
| `_API_KEY_MANAGED_MARKER` (py/claudeops/providers/ucli_provider.py:313) | | | AÇIK |
| `_sync_api_key_file` (py/claudeops/providers/ucli_provider.py:316) | | | AÇIK |
| `_web_args` (py/claudeops/providers/ucli_provider.py:345) | | | AÇIK |
| `_script_args` (py/claudeops/providers/ucli_provider.py:383) | | | AÇIK |
| `_stream_args` (py/claudeops/providers/ucli_provider.py:397) | | | AÇIK |
| `_reasoning_display_args` (py/claudeops/providers/ucli_provider.py:409) | | | AÇIK |
| `_metrics_file_args` (py/claudeops/providers/ucli_provider.py:420) | | | AÇIK |
| `_interactive_args` (py/claudeops/providers/ucli_provider.py:442) | | | AÇIK |
| `_state_dir_args` (py/claudeops/providers/ucli_provider.py:451) | | | AÇIK |
| `_timeout_args` (py/claudeops/providers/ucli_provider.py:468) | | | AÇIK |
| `_history_args` (py/claudeops/providers/ucli_provider.py:478) | | | AÇIK |
| `_effort_args` (py/claudeops/providers/ucli_provider.py:495) | | | AÇIK |
| `_set_flag_value` (py/claudeops/providers/ucli_provider.py:513) | | | AÇIK |
| `_service_key_file` (py/claudeops/providers/ucli_provider.py:525) | | | AÇIK |
| `_INSTRUCTIONS_MAX_BYTES` (py/claudeops/providers/ucli_provider.py:529) | | | AÇIK |
| `_instructions_too_big` (py/claudeops/providers/ucli_provider.py:532) | | | AÇIK |
| `instructions_check` (py/claudeops/providers/ucli_provider.py:543) | | | AÇIK |
| `_claude_service_flags` (py/claudeops/providers/ucli_provider.py:564) | | | AÇIK |
| `_PRICED_MODELS` (py/claudeops/providers/ucli_provider.py:597) | | | AÇIK |
| `_default_session_cap` (py/claudeops/providers/ucli_provider.py:600) | | | AÇIK |
| `_max_cost_args` (py/claudeops/providers/ucli_provider.py:609) | | | AÇIK |
| `_MCP_NAME_BAD` (py/claudeops/providers/ucli_provider.py:624) | | | AÇIK |
| `_MCP_TOOL_RE` (py/claudeops/providers/ucli_provider.py:625) | | | AÇIK |
| `_MCP_ADD_TIMEOUT` (py/claudeops/providers/ucli_provider.py:626) | | | AÇIK |
| `mcp_server_name` (py/claudeops/providers/ucli_provider.py:629) | | | AÇIK |
| `mcp_add_argv` (py/claudeops/providers/ucli_provider.py:633) | | | AÇIK |
| `register_mcp` (py/claudeops/providers/ucli_provider.py:642) | | | AÇIK |
| `_apply_cli_opts` (py/claudeops/providers/ucli_provider.py:672) | | | AÇIK |
| `_agent_setup` (py/claudeops/providers/ucli_provider.py:845) | | | AÇIK |
| `UcliProvider` (py/claudeops/providers/ucli_provider.py:867) | | | AÇIK |
| `UcliProvider.name` (py/claudeops/providers/ucli_provider.py:868) | | | AÇIK |
| `UcliProvider.prepare_input` (py/claudeops/providers/ucli_provider.py:870) | | | AÇIK |
| `UcliProvider.has_conversation` (py/claudeops/providers/ucli_provider.py:878) | | | AÇIK |
| `UcliProvider.wants_handover_wrapup` (py/claudeops/providers/ucli_provider.py:881) | | | AÇIK |
| `UcliProvider.resolve_resume_id` (py/claudeops/providers/ucli_provider.py:884) | | | AÇIK |
| `UcliProvider.accepts_cli_opts` (py/claudeops/providers/ucli_provider.py:888) | | | AÇIK |
| `UcliProvider.mcp_needs_cwd` (py/claudeops/providers/ucli_provider.py:889) | | | AÇIK |
| `UcliProvider.validate_cli_opts` (py/claudeops/providers/ucli_provider.py:891) | | | AÇIK |
| `UcliProvider.mcp_launch_args` (py/claudeops/providers/ucli_provider.py:894) | | | AÇIK |
| `UcliProvider.build_inner_command` (py/claudeops/providers/ucli_provider.py:917) | | | AÇIK |
| `UcliProvider.oneshot` (py/claudeops/providers/ucli_provider.py:997) | | | AÇIK |
| `UcliProvider.env_overrides` (py/claudeops/providers/ucli_provider.py:1017) | | | AÇIK |
| `UcliProvider.matches_proc` (py/claudeops/providers/ucli_provider.py:1022) | | | AÇIK |
| `UcliProvider._parse_session` (py/claudeops/providers/ucli_provider.py:1027) | | | AÇIK |
| `UcliProvider.extract_name` (py/claudeops/providers/ucli_provider.py:1033) | | | AÇIK |
| `UcliProvider.extract_info` (py/claudeops/providers/ucli_provider.py:1036) | | | AÇIK |
| `UcliProvider.model_choices` (py/claudeops/providers/ucli_provider.py:1072) | | | AÇIK |
| `UcliProvider.default_permission_mode` (py/claudeops/providers/ucli_provider.py:1075) | | | AÇIK |
| `UcliProvider.permission_modes` (py/claudeops/providers/ucli_provider.py:1080) | | | AÇIK |
| `UcliProvider.effort_levels` (py/claudeops/providers/ucli_provider.py:1083) | | | AÇIK |
| `UcliProvider.full_history` (py/claudeops/providers/ucli_provider.py:1086) | | | AÇIK |
| `UcliProvider.sid_for_stopped_session` (py/claudeops/providers/ucli_provider.py:1091) | | | AÇIK |
| `UcliProvider.live_busy` (py/claudeops/providers/ucli_provider.py:1097) | | | AÇIK |
| `UcliProvider.background_work` (py/claudeops/providers/ucli_provider.py:1112) | | | AÇIK |
| `UcliProvider.live_tools` (py/claudeops/providers/ucli_provider.py:1127) | | | AÇIK |
| `UcliProvider.live_context` (py/claudeops/providers/ucli_provider.py:1141) | | | AÇIK |
| `UcliProvider.live_usage` (py/claudeops/providers/ucli_provider.py:1156) | | | AÇIK |
| `UcliProvider.live_failed_turns` (py/claudeops/providers/ucli_provider.py:1173) | | | AÇIK |
| `UcliProvider.live_phase` (py/claudeops/providers/ucli_provider.py:1196) | | | AÇIK |
| `UcliProvider.last_exchange` (py/claudeops/providers/ucli_provider.py:1226) | | | AÇIK |
| `BUNDLED_PATH` (py/claudeops/routing.py:21) | | | AÇIK |
| `OVERRIDE_PATH` (py/claudeops/routing.py:22) | | | AÇIK |
| `BLOCK_BEGIN` (py/claudeops/routing.py:23) | | | AÇIK |
| `BLOCK_END` (py/claudeops/routing.py:24) | | | AÇIK |
| `CODEX_AGENTS` (py/claudeops/routing.py:25) | | | AÇIK |
| `AGY_GEMINI` (py/claudeops/routing.py:26) | | | AÇIK |
| `routing_text` (py/claudeops/routing.py:29) | | | AÇIK |
| `claude_guidance_path` (py/claudeops/routing.py:41) | | | AÇIK |
| `_with_block` (py/claudeops/routing.py:66) | | | AÇIK |
| `_sync_one` (py/claudeops/routing.py:81) | | | AÇIK |
| `sync_global_files` (py/claudeops/routing.py:109) | | | AÇIK |
| `_DANGEROUS_ENV_NAMES` (py/claudeops/spawn.py:36) | | | AÇIK |
| `FALLBACK_ATTEMPT_WAIT_SECONDS` (py/claudeops/spawn.py:50) | | | AÇIK |
| `FALLBACK_RETRY_COUNT` (py/claudeops/spawn.py:51) | | | AÇIK |
| `_filter_env_overrides` (py/claudeops/spawn.py:54) | | | AÇIK |
| `DRY_RUN_PREVIEW_MAX` (py/claudeops/spawn.py:59) | | | AÇIK |
| `_SECRET_ENV_RE` (py/claudeops/spawn.py:60) | | | AÇIK |
| `_dry_run_preview` (py/claudeops/spawn.py:63) | | | AÇIK |
| `detect_display` (py/claudeops/spawn.py:71) | | | AÇIK |
| `_ids_held_by_others` (py/claudeops/spawn.py:83) | | | AÇIK |
| `SESSION_USD_CAP_KEY` (py/claudeops/spawn.py:110) | | | AÇIK |
| `_apply_hook_session_cap` (py/claudeops/spawn.py:113) | | | AÇIK |
| `BRAIN_NAME_PREFIXES` (py/claudeops/spawn.py:138) | | | AÇIK |
| `spawn_priority_prefix` (py/claudeops/spawn.py:141) | | | AÇIK |
| `spawn_session` (py/claudeops/spawn.py:163) | | | AÇIK |
| `_launch_gnome_terminal` (py/claudeops/spawn.py:325) | | | AÇIK |
| `_reclaim_ghost_session` (py/claudeops/spawn.py:366) | | | AÇIK |
| `_fallback_watchdog` (py/claudeops/spawn.py:384) | | | AÇIK |
| `open_window` (py/claudeops/spawn.py:409) | | | AÇIK |
| `open_mirror_window` (py/claudeops/spawn.py:425) | | | AÇIK |
| `EFFORT_LADDER` (py/claudeops/effort.py:19) | | | AÇIK |
| `_RANK` (py/claudeops/effort.py:20) | | | AÇIK |
| `_ID_TIERS` (py/claudeops/effort.py:25) | | | AÇIK |
| `effort_rank` (py/claudeops/effort.py:28) | | | AÇIK |
| `split_tier` (py/claudeops/effort.py:33) | | | AÇIK |
| `sort_levels` (py/claudeops/effort.py:45) | | | AÇIK |
| `nearest_effort` (py/claudeops/effort.py:56) | | | AÇIK |
| `ENV_NAME_RE` (py/claudeops/envnames.py:7) | | | AÇIK |
| `is_safe_env_name` (py/claudeops/envnames.py:10) | | | AÇIK |
| `services` (py/claudeops/ucli_session_opts.py:21) | | | AÇIK |
| `effort_levels_for` (py/claudeops/ucli_session_opts.py:27) | | | AÇIK |
| `FORBIDDEN_CMDS` (py/claudeops/ucli_session_opts.py:40) | | | AÇIK |
| `_FORBIDDEN_RE` (py/claudeops/ucli_session_opts.py:54) | | | AÇIK |
| `is_forbidden_cmd` (py/claudeops/ucli_session_opts.py:57) | | | AÇIK |
| `_FORBIDDEN_LOWER` (py/claudeops/ucli_session_opts.py:62) | | | AÇIK |
| `_CMD_RE` (py/claudeops/ucli_session_opts.py:64) | | | AÇIK |
| `_GLOB_RE` (py/claudeops/ucli_session_opts.py:65) | | | AÇIK |
| `MAX_CMDS` (py/claudeops/ucli_session_opts.py:66) | | | AÇIK |
| `MAX_EXPANDED` (py/claudeops/ucli_session_opts.py:67) | | | AÇIK |
| `_PATTERN_CHARS` (py/claudeops/ucli_session_opts.py:68) | | | AÇIK |
| `MAX_GLOBS` (py/claudeops/ucli_session_opts.py:69) | | | AÇIK |
| `MAX_BINDS` (py/claudeops/ucli_session_opts.py:70) | | | AÇIK |
| `_BIND_RE` (py/claudeops/ucli_session_opts.py:71) | | | AÇIK |
| `TIMEOUT_RANGE` (py/claudeops/ucli_session_opts.py:72) | | | AÇIK |
| `MAX_COST_USD` (py/claudeops/ucli_session_opts.py:73) | | | AÇIK |
| `INT_LIMITS` (py/claudeops/ucli_session_opts.py:75) | | | AÇIK |
| `PRICE_MAX` (py/claudeops/ucli_session_opts.py:83) | | | AÇIK |
| `BROAD_GLOBS` (py/claudeops/ucli_session_opts.py:86) | | | AÇIK |
| `_is_glob` (py/claudeops/ucli_session_opts.py:89) | | | AÇIK |
| `_items` (py/claudeops/ucli_session_opts.py:93) | | | AÇIK |
| `validate_opts` (py/claudeops/ucli_session_opts.py:101) | | | AÇIK |
| `DEFAULT_MAX_SESSION_USD` (py/claudeops/ucli_session_opts.py:305) | | | AÇIK |
| `default_max_session_usd` (py/claudeops/ucli_session_opts.py:308) | | | AÇIK |
| `path_executables` (py/claudeops/ucli_session_opts.py:323) | | | AÇIK |
| `expand_exec_cmds` (py/claudeops/ucli_session_opts.py:343) | | | AÇIK |
| `_rustup_default_toolchain` (py/claudeops/ucli_session_opts.py:368) | | | AÇIK |
| `rust_toolchain` (py/claudeops/ucli_session_opts.py:381) | | | AÇIK |
| `exec_flags` (py/claudeops/ucli_session_opts.py:410) | | | AÇIK |
| `_MODELS_CACHE` (py/claudeops/ucli_session_opts.py:446) | | | AÇIK |
| `_MODELS_TTL` (py/claudeops/ucli_session_opts.py:447) | | | AÇIK |
| `service_models` (py/claudeops/ucli_session_opts.py:450) | | | AÇIK |

## TEST EŞLEME TABLOSU (aday dosyalar: kapsam modüllerini içe aktaran py/tests; gözden geçirilecek)

| Python testi (dosya:satır) | Rust testi / neden gereksiz | durum |
|---|---|---|
| `AgyBinaryTest.test_inner_command_quotes_a_path_with_spaces` (py/tests/test_agy_binary_resolution.py:14) | | AÇIK |
| `AgyBinaryTest.test_model_choices_uses_the_resolved_binary` (py/tests/test_agy_binary_resolution.py:19) | | AÇIK |
| `AgyCompactionViewTests.test_checkpoint_becomes_boundary_and_plain_type23_is_ignored` (py/tests/test_agy_compaction_view.py:21) | | AÇIK |
| `AgyLastExchange.test_last_pair_skips_empty_assistant_steps` (py/tests/test_agy_last_exchange.py:33) | | AÇIK |
| `AgyLastExchange.test_empty_conversation_and_no_assistant` (py/tests/test_agy_last_exchange.py:37) | | AÇIK |
| `AgyLastExchange.test_checkpoint_between_does_not_break_pairing` (py/tests/test_agy_last_exchange.py:41) | | AÇIK |
| `AgyLastExchange.test_missing_db_is_empty` (py/tests/test_agy_last_exchange.py:45) | | AÇIK |
| `AgyModelsSwr.test_cold_blocks_then_stale_returns_old_immediately_and_refreshes_in_background` (py/tests/test_agy_models_swr.py:19) | | AÇIK |
| `AgySidsStoreTest.test_db_ready` (py/tests/test_agy_sids_store.py:31) | | AÇIK |
| `AgySidsStoreTest.test_remember_writes_db_and_mirror` (py/tests/test_agy_sids_store.py:34) | | AÇIK |
| `AgySidsStoreTest.test_unchanged_value_does_not_rewrite` (py/tests/test_agy_sids_store.py:42) | | AÇIK |
| `AgySidsStoreTest.test_concurrent_remembers_lose_nothing` (py/tests/test_agy_sids_store.py:48) | | AÇIK |
| `RoutingSymlink.test_symlink_kept_and_target_written_with_mode` (py/tests/test_atomic_users_symlink.py:13) | | AÇIK |
| `TokenFile.test_token_file_0600_atomic` (py/tests/test_atomic_users_symlink.py:30) | | AÇIK |
| `OrphanMarker.test_orphan_begin_does_not_eat_user_text` (py/tests/test_atomic_users_symlink.py:41) | | AÇIK |
| `OrphanMarker.test_normal_block_replaced_and_removed` (py/tests/test_atomic_users_symlink.py:50) | | AÇIK |
| `DefaultsTest.test_no_hooks_is_noop` (py/tests/test_authz.py:27) | | AÇIK |
| `DefaultsTest.test_every_web_path_has_an_action` (py/tests/test_authz.py:34) | | AÇIK |
| `DefaultsTest.test_uzakgoz_freshness_is_read_only_mapped` (py/tests/test_authz.py:40) | | AÇIK |
| `DefaultsTest.test_unknown_path_unmapped` (py/tests/test_authz.py:43) | | AÇIK |
| `DefaultsTest.test_fail_closed` (py/tests/test_authz.py:48) | | AÇIK |
| `DefaultsTest.test_public_route_only_auth_prefix` (py/tests/test_authz.py:60) | | AÇIK |
| `HttpTest.test_legacy_token_unchanged_without_hooks` (py/tests/test_authz.py:87) | | AÇIK |
| `HttpTest.test_authenticator_replaces_token_and_401` (py/tests/test_authz.py:91) | | AÇIK |
| `HttpTest.test_agents_cookie_human_gated_on_get_and_post` (py/tests/test_authz.py:96) | | AÇIK |
| `HttpTest.test_agent_bearer_token_works_in_multi_user_mode` (py/tests/test_authz.py:110) | | AÇIK |
| `HttpTest.test_authorizer_denies_403_and_audits` (py/tests/test_authz.py:130) | | AÇIK |
| `HttpTest.test_resource_from_body_name` (py/tests/test_authz.py:141) | | AÇIK |
| `HttpTest.test_post_gate_sees_body_resource_once` (py/tests/test_authz.py:149) | | AÇIK |
| `HttpTest.test_ticket_gives_panel_cookie_only_to_admin_in_multi_user` (py/tests/test_authz.py:169) | | AÇIK |
| `HttpTest.test_ticket_keeps_panel_cookie_in_single_user` (py/tests/test_authz.py:177) | | AÇIK |
| `HttpTest.test_orch_get_names_query_denied_if_any_name_denied` (py/tests/test_authz.py:180) | | AÇIK |
| `HttpTest.test_files_without_name_is_400_even_when_global_allowed` (py/tests/test_authz.py:187) | | AÇIK |
| `HttpTest.test_ws_handshake_filters_status_for_principal` (py/tests/test_authz.py:199) | | AÇIK |
| `HttpTest.test_status_filter_applied` (py/tests/test_authz.py:218) | | AÇIK |
| `HttpTest.test_public_route_skips_auth_but_other_ext_routes_need_admin` (py/tests/test_authz.py:224) | | AÇIK |
| `HttpTest.test_ui_extension_list_and_files` (py/tests/test_authz.py:236) | | AÇIK |
| `HttpTest.test_session_event_emitted_on_success` (py/tests/test_authz.py:253) | | AÇIK |
| `HttpTest.test_new_chat_and_adopt_event_use_real_instance_name` (py/tests/test_authz.py:264) | | AÇIK |
| `HttpTest.test_session_event_emitted_before_response` (py/tests/test_authz.py:279) | | AÇIK |
| `SpawnHookTest.test_no_hook_empty_and_threadlocal` (py/tests/test_authz.py:296) | | AÇIK |
| `SpawnHookTest.test_hook_env_refusal_and_fail_closed` (py/tests/test_authz.py:307) | | AÇIK |
| `SpawnHookTest.test_spawn_session_dry_run_gets_env` (py/tests/test_authz.py:320) | | AÇIK |
| `SpawnHookTest.test_hook_session_usd_cap_min_with_default_and_popped_from_env` (py/tests/test_authz.py:330) | | AÇIK |
| `SpawnHookTest.test_refusal_formatting` (py/tests/test_authz.py:351) | | AÇIK |
| `TicketAndQuestionTest.test_ws_ticket_bound_to_principal` (py/tests/test_authz.py:358) | | AÇIK |
| `TicketAndQuestionTest.test_ticket_replaces_cookie_for_ws_only` (py/tests/test_authz.py:368) | | AÇIK |
| `TicketAndQuestionTest.test_steward_resource_uses_sid_not_project_name` (py/tests/test_authz.py:382) | | AÇIK |
| `TicketAndQuestionTest.test_question_page_access_check` (py/tests/test_authz.py:388) | | AÇIK |
| `ResourcesTest.test_multi_resources` (py/tests/test_authz.py:405) | | AÇIK |
| `ResourcesTest.test_names_query_and_body_each_a_resource` (py/tests/test_authz.py:413) | | AÇIK |
| `ResourcesTest.test_files_path_never_becomes_a_resource` (py/tests/test_authz.py:420) | | AÇIK |
| `ResourcesTest.test_event_sink_error_swallowed` (py/tests/test_authz.py:428) | | AÇIK |
| `ResourcesTest.test_doc_prefix` (py/tests/test_authz.py:436) | | AÇIK |
| `ResourcesTest.test_ws_client_view` (py/tests/test_authz.py:445) | | AÇIK |
| `ExtensionCommandTest.test_register_and_dispatch` (py/tests/test_authz.py:470) | | AÇIK |
| `ExtensionCommandTest.test_core_name_not_overridden_and_no_load_for_core` (py/tests/test_authz.py:479) | | AÇIK |
| `ExtensionCommandTest.test_bad_name` (py/tests/test_authz.py:488) | | AÇIK |
| `ExtActionTableTest.test_action_for_reads_ext_table_longest_first` (py/tests/test_authz.py:498) | | AÇIK |
| `ExtActionTableTest.test_register_action_prefix_restricted` (py/tests/test_authz.py:508) | | AÇIK |
| `ExtActionTableTest.test_ui_extension_title_en` (py/tests/test_authz.py:512) | | AÇIK |
| `ScreenFixture.test_busy_screens` (py/tests/test_bg_work.py:39) | | AÇIK |
| `ScreenFixture.test_idle_screen_with_prose_numbers` (py/tests/test_bg_work.py:43) | | AÇIK |
| `TranscriptFixture.test_pending_without_notification` (py/tests/test_bg_work.py:69) | | AÇIK |
| `TranscriptFixture.test_completed_by_tool_use_id_or_task_id` (py/tests/test_bg_work.py:72) | | AÇIK |
| `TranscriptFixture.test_foreground_and_stale` (py/tests/test_bg_work.py:77) | | AÇIK |
| `TranscriptFixture.test_errored_call_is_not_pending` (py/tests/test_bg_work.py:81) | | AÇIK |
| `TranscriptFixture.test_one_of_two_pending` (py/tests/test_bg_work.py:87) | | AÇIK |
| `SubagentActiveForUsesBoth.test_screen_makes_active_even_without_subagent_files` (py/tests/test_bg_work.py:92) | | AÇIK |
| `SubagentActiveForUsesBoth.test_transcript_pending_makes_active` (py/tests/test_bg_work.py:98) | | AÇIK |
| `ProviderBackgroundWork.test_base_unknown_and_claude_counts` (py/tests/test_bg_work.py:113) | | AÇIK |
| `UcliBackgroundWork.test_reads_status_field_never_guesses` (py/tests/test_bg_work.py:126) | | AÇIK |
| `CodexBackgroundWork.test_screen_and_rollout` (py/tests/test_bg_work.py:150) | | AÇIK |
| `CodexBackgroundWork.test_provider_sums_screen_and_missing_rollout` (py/tests/test_bg_work.py:157) | | AÇIK |
| `BrainPermission.test_default_allow_edit_is_a_valid_ucli_mode` (py/tests/test_brain_permission_ucli.py:11) | | AÇIK |
| `BrainPermission.test_applied_only_for_ucli` (py/tests/test_brain_permission_ucli.py:15) | | AÇIK |
| `CompactionViewTests.test_boundary_and_summary_roles_keep_pre_compaction_messages` (py/tests/test_chat_compaction_view.py:21) | | AÇIK |
| `CompactionViewTests.test_no_boundary_unchanged` (py/tests/test_chat_compaction_view.py:34) | | AÇIK |
| `CompactionViewTests.test_sidechain_summary_ignored` (py/tests/test_chat_compaction_view.py:38) | | AÇIK |
| `ClaudeModelsStoreTest.test_is_db_ready` (py/tests/test_claude_models_store.py:32) | | AÇIK |
| `ClaudeModelsStoreTest.test_write_goes_to_db_and_mirror_and_reads_from_db` (py/tests/test_claude_models_store.py:35) | | AÇIK |
| `ClaudeModelsStoreTest.test_db_wins_over_corrupt_or_missing_file` (py/tests/test_claude_models_store.py:42) | | AÇIK |
| `ClaudeModelsStoreTest.test_fallback_to_hardcoded_when_empty` (py/tests/test_claude_models_store.py:50) | | AÇIK |
| `TrustFolder.test_adds_and_keeps_comments` (py/tests/test_copilot_trust.py:14) | | AÇIK |
| `TrustFolder.test_empty_list` (py/tests/test_copilot_trust.py:21) | | AÇIK |
| `TrustFolder.test_keeps_private_mode` (py/tests/test_copilot_trust.py:26) | | AÇIK |
| `TrustFolder.test_idempotent_and_missing` (py/tests/test_copilot_trust.py:34) | | AÇIK |
| `FindSessionsSidTests.test_a_fresh_session_gets_the_live_sid_from_the_json_entry` (py/tests/test_discovery_sid.py:77) | | AÇIK |
| `FindSessionsSidTests.test_a_resumed_session_keeps_its_sid_and_stays_resumed` (py/tests/test_discovery_sid.py:85) | | AÇIK |
| `FindSessionsSidTests.test_the_live_json_sid_wins_over_a_stale_cmdline_sid` (py/tests/test_discovery_sid.py:92) | | AÇIK |
| `FindSessionsSidTests.test_without_a_json_entry_the_cmdline_value_is_used_exactly_as_before` (py/tests/test_discovery_sid.py:101) | | AÇIK |
| `FindSessionsSidTests.test_a_json_entry_without_a_sid_never_blanks_the_cmdline_sid` (py/tests/test_discovery_sid.py:106) | | AÇIK |
| `FindSessionsSidTests.test_a_tui_renamed_session_is_listed_once_under_its_spawn_name` (py/tests/test_discovery_sid.py:110) | | AÇIK |
| `FindSessionsSidTests.test_each_session_gets_its_own_sid_by_pid` (py/tests/test_discovery_sid.py:116) | | AÇIK |
| `FindSessionsSidTests.test_a_json_entry_of_another_cli_never_donates_its_sid` (py/tests/test_discovery_sid.py:121) | | AÇIK |
| `FindSessionsSidTests.test_a_non_claude_cli_keeps_its_cmdline_sid_and_its_old_is_fresh` (py/tests/test_discovery_sid.py:129) | | AÇIK |
| `IsFreshTests.test_flag_unknown_falls_back_to_the_sid` (py/tests/test_discovery_sid.py:138) | | AÇIK |
| `IsFreshTests.test_flag_known_wins_over_the_sid` (py/tests/test_discovery_sid.py:143) | | AÇIK |
| `SplitTierTests.test_tiered_ids` (py/tests/test_effort_by_model.py:56) | | AÇIK |
| `SplitTierTests.test_untiered_ids_are_untouched` (py/tests/test_effort_by_model.py:62) | | AÇIK |
| `SplitTierTests.test_non_string` (py/tests/test_effort_by_model.py:66) | | AÇIK |
| `SortAndNearestTests.test_sort_levels_orders_dedupes_keeps_unknown_last` (py/tests/test_effort_by_model.py:71) | | AÇIK |
| `SortAndNearestTests.test_requested_in_levels_is_returned_as_is` (py/tests/test_effort_by_model.py:75) | | AÇIK |
| `SortAndNearestTests.test_too_high_goes_to_the_top_supported` (py/tests/test_effort_by_model.py:78) | | AÇIK |
| `SortAndNearestTests.test_prefers_below_over_equally_near_above` (py/tests/test_effort_by_model.py:81) | | AÇIK |
| `SortAndNearestTests.test_nothing_below_takes_lowest_above` (py/tests/test_effort_by_model.py:85) | | AÇIK |
| `SortAndNearestTests.test_empty_request_uses_default` (py/tests/test_effort_by_model.py:88) | | AÇIK |
| `SortAndNearestTests.test_unknown_request_falls_back_via_default_rank` (py/tests/test_effort_by_model.py:92) | | AÇIK |
| `SortAndNearestTests.test_empty_levels` (py/tests/test_effort_by_model.py:95) | | AÇIK |
| `SortAndNearestTests.test_all_unknown_level_names` (py/tests/test_effort_by_model.py:98) | | AÇIK |
| `AgyEffortTests.test_tier_in_id_fixes_the_levels` (py/tests/test_effort_by_model.py:103) | | AÇIK |
| `AgyEffortTests.test_untiered_non_gemini_has_no_info` (py/tests/test_effort_by_model.py:109) | | AÇIK |
| `AgyEffortTests.test_base_name_uses_live_siblings` (py/tests/test_effort_by_model.py:114) | | AÇIK |
| `AgyEffortTests.test_base_name_without_siblings_is_unknown` (py/tests/test_effort_by_model.py:118) | | AÇIK |
| `AgyEffortTests.test_empty_model` (py/tests/test_effort_by_model.py:122) | | AÇIK |
| `AgyEffortTests.test_panel_default_max_no_longer_conflicts_with_tiered_id` (py/tests/test_effort_by_model.py:127) | | AÇIK |
| `AgyEffortTests.test_empty_effort_no_longer_defaults_to_medium_against_a_high_id` (py/tests/test_effort_by_model.py:134) | | AÇIK |
| `AgyEffortTests.test_requested_effort_follows_the_id_not_the_other_way` (py/tests/test_effort_by_model.py:140) | | AÇIK |
| `AgyEffortTests.test_matching_effort_is_unchanged` (py/tests/test_effort_by_model.py:145) | | AÇIK |
| `AgyEffortTests.test_non_gemini_still_gets_no_effort_flag` (py/tests/test_effort_by_model.py:151) | | AÇIK |
| `AgyEffortTests.test_argon_ids_are_consistent_with_their_tier` (py/tests/test_effort_by_model.py:159) | | AÇIK |
| `AgyEffortTests.test_gemini_base_name_clamps_to_live_tiers` (py/tests/test_effort_by_model.py:166) | | AÇIK |
| `AgyEffortTests.test_gemini_base_name_without_info_keeps_old_behaviour` (py/tests/test_effort_by_model.py:171) | | AÇIK |
| `CodexEffortTests.test_reads_per_model_levels` (py/tests/test_effort_by_model.py:195) | | AÇIK |
| `CodexEffortTests.test_unknown_model_or_empty_list_is_no_info` (py/tests/test_effort_by_model.py:199) | | AÇIK |
| `CodexEffortTests.test_missing_or_corrupt_cache_is_no_info` (py/tests/test_effort_by_model.py:204) | | AÇIK |
| `CodexEffortTests.test_unsupported_effort_is_clamped_supported_is_untouched` (py/tests/test_effort_by_model.py:211) | | AÇIK |
| `CodexEffortTests.test_model_missing_from_cache_passes_through` (py/tests/test_effort_by_model.py:216) | | AÇIK |
| `OtherProvidersPassThroughTests.test_fleet_values_pass_through_unchanged` (py/tests/test_effort_by_model.py:237) | | AÇIK |
| `OtherProvidersPassThroughTests.test_unknown_values_are_not_rewritten_either` (py/tests/test_effort_by_model.py:244) | | AÇIK |
| `OtherProvidersPassThroughTests.test_only_agy_and_codex_override_model_levels` (py/tests/test_effort_by_model.py:249) | | AÇIK |
| `SpawnWiringTests.test_adjusted_effort_reaches_the_command_and_is_logged` (py/tests/test_effort_by_model.py:268) | | AÇIK |
| `SpawnWiringTests.test_unchanged_effort_is_not_logged` (py/tests/test_effort_by_model.py:275) | | AÇIK |
| `SpawnWiringTests.test_resolver_failure_never_blocks_the_spawn` (py/tests/test_effort_by_model.py:280) | | AÇIK |
| `EnvNames.test_valid_and_invalid` (py/tests/test_envnames.py:9) | | AÇIK |
| `EnvNames.test_spawn_filters_newline_and_dangerous` (py/tests/test_envnames.py:15) | | AÇIK |
| `McpHook.test_validation` (py/tests/test_extensions_mcp.py:22) | | AÇIK |
| `McpHook.test_stdio_roundtrip` (py/tests/test_extensions_mcp.py:34) | | AÇIK |
| `McpHook.test_unknown_server_exit_2` (py/tests/test_extensions_mcp.py:51) | | AÇIK |
| `SessionAttach.test_attach_predicate_and_spec` (py/tests/test_extensions_mcp.py:68) | | AÇIK |
| `SessionAttach.test_claude_config_path_per_ext_and_spawn_wiring` (py/tests/test_extensions_mcp.py:82) | | AÇIK |
| `SessionAttach.test_spawn_attaches_only_matching_cwd_and_claude` (py/tests/test_extensions_mcp.py:89) | | AÇIK |
| `LastRealRequestEpochTests.test_returns_the_time_of_the_latest_real_request` (py/tests/test_handover_cache_policy.py:76) | | AÇIK |
| `LastRealRequestEpochTests.test_synthetic_placeholder_after_a_real_request_does_not_refresh_the_cache` (py/tests/test_handover_cache_policy.py:80) | | AÇIK |
| `LastRealRequestEpochTests.test_subagent_rows_are_a_separate_context_and_do_not_count` (py/tests/test_handover_cache_policy.py:86) | | AÇIK |
| `LastRealRequestEpochTests.test_rows_without_any_usage_tokens_do_not_count` (py/tests/test_handover_cache_policy.py:90) | | AÇIK |
| `LastRealRequestEpochTests.test_user_rows_are_ignored_and_no_assistant_means_unknown` (py/tests/test_handover_cache_policy.py:96) | | AÇIK |
| `LastRealRequestEpochTests.test_missing_file_is_unknown` (py/tests/test_handover_cache_policy.py:100) | | AÇIK |
| `LastRealRequestEpochTests.test_large_file_is_read_from_the_tail` (py/tests/test_handover_cache_policy.py:103) | | AÇIK |
| `ClaudeProviderCacheHookTests.test_ttl_is_one_hour` (py/tests/test_handover_cache_policy.py:110) | | AÇIK |
| `ClaudeProviderCacheHookTests.test_last_request_epoch_reads_only_the_exact_sid_file` (py/tests/test_handover_cache_policy.py:113) | | AÇIK |
| `ClaudeProviderCacheHookTests.test_no_sid_or_no_matching_file_is_unknown_never_the_newest_sibling` (py/tests/test_handover_cache_policy.py:123) | | AÇIK |
| `ClaudeProviderCacheHookTests.test_effort_switch_keeps_cache_by_model` (py/tests/test_handover_cache_policy.py:135) | | AÇIK |
| `ClaudeProviderCacheHookTests.test_other_providers_keep_the_old_behaviour` (py/tests/test_handover_cache_policy.py:148) | | AÇIK |
| `SessionFileSidTests.test_verified_file_gives_the_session_id` (py/tests/test_handover_cache_policy.py:177) | | AÇIK |
| `SessionFileSidTests.test_a_reused_pid_is_rejected_by_proc_start` (py/tests/test_handover_cache_policy.py:182) | | AÇIK |
| `SessionFileSidTests.test_unverifiable_or_inconsistent_files_are_not_trusted` (py/tests/test_handover_cache_policy.py:186) | | AÇIK |
| `SessionFileSidTests.test_dead_process_and_missing_file_and_no_pid` (py/tests/test_handover_cache_policy.py:202) | | AÇIK |
| `LastRequestEpochByPidTests.test_fresh_session_without_cmdline_sid_is_found_through_its_pid` (py/tests/test_handover_cache_policy.py:234) | | AÇIK |
| `LastRequestEpochByPidTests.test_without_a_pid_the_sidless_session_stays_unknown` (py/tests/test_handover_cache_policy.py:239) | | AÇIK |
| `LastRequestEpochByPidTests.test_the_newest_request_of_the_two_candidate_files_wins` (py/tests/test_handover_cache_policy.py:245) | | AÇIK |
| `LastRequestEpochByPidTests.test_a_missing_candidate_file_falls_back_to_the_other_one` (py/tests/test_handover_cache_policy.py:255) | | AÇIK |
| `LastRequestEpochByPidTests.test_a_sibling_session_in_the_same_directory_is_never_picked_up` (py/tests/test_handover_cache_policy.py:260) | | AÇIK |
| `LastRequestEpochByPidTests.test_empty_conversation_file_is_unknown` (py/tests/test_handover_cache_policy.py:266) | | AÇIK |
| `PromptCacheIsWarmTests.test_margin_is_five_minutes` (py/tests/test_handover_cache_policy.py:288) | | AÇIK |
| `PromptCacheIsWarmTests.test_fresh_request_is_warm` (py/tests/test_handover_cache_policy.py:291) | | AÇIK |
| `PromptCacheIsWarmTests.test_boundary_and_older_is_cold` (py/tests/test_handover_cache_policy.py:296) | | AÇIK |
| `PromptCacheIsWarmTests.test_future_timestamp_from_clock_skew_counts_as_warm` (py/tests/test_handover_cache_policy.py:301) | | AÇIK |
| `PromptCacheIsWarmTests.test_unknown_when_provider_has_no_ttl_or_no_transcript` (py/tests/test_handover_cache_policy.py:304) | | AÇIK |
| `PromptCacheIsWarmTests.test_now_defaults_to_the_wall_clock` (py/tests/test_handover_cache_policy.py:309) | | AÇIK |
| `PromptCacheIsWarmTests.test_the_process_id_reaches_the_provider` (py/tests/test_handover_cache_policy.py:314) | | AÇIK |
| `ModelDowngradeTests.test_warm_opus_keeps_its_model_but_still_lowers_effort` (py/tests/test_handover_cache_policy.py:373) | | AÇIK |
| `ModelDowngradeTests.test_cold_opus_goes_down_to_sonnet_then_effort_in_that_order` (py/tests/test_handover_cache_policy.py:385) | | AÇIK |
| `ModelDowngradeTests.test_fable_follows_the_same_rule` (py/tests/test_handover_cache_policy.py:395) | | AÇIK |
| `ModelDowngradeTests.test_boundary_is_the_ttl_minus_margin` (py/tests/test_handover_cache_policy.py:403) | | AÇIK |
| `ModelDowngradeTests.test_models_that_are_not_downgrade_candidates_never_get_a_model_command` (py/tests/test_handover_cache_policy.py:411) | | AÇIK |
| `ModelDowngradeTests.test_unknown_warmth_keeps_the_old_always_downgrade_behaviour` (py/tests/test_handover_cache_policy.py:420) | | AÇIK |
| `ModelDowngradeTests.test_a_failing_cache_probe_never_blocks_the_wrap_up` (py/tests/test_handover_cache_policy.py:427) | | AÇIK |
| `ModelDowngradeTests.test_escape_hatch_restores_the_old_behaviour_and_never_probes` (py/tests/test_handover_cache_policy.py:434) | | AÇIK |
| `ModelDowngradeTests.test_missing_setting_defaults_to_cache_aware` (py/tests/test_handover_cache_policy.py:442) | | AÇIK |
| `ModelDowngradeTests.test_provider_without_a_cache_ttl_keeps_the_old_behaviour` (py/tests/test_handover_cache_policy.py:448) | | AÇIK |
| `EffortDowngradeTests.test_warm_sonnet_55_gets_the_cache_safe_effort_drop` (py/tests/test_handover_cache_policy.py:459) | | AÇIK |
| `EffortDowngradeTests.test_warm_sonnet_5_skips_the_effort_drop_that_would_rewrite_the_cache` (py/tests/test_handover_cache_policy.py:466) | | AÇIK |
| `EffortDowngradeTests.test_cold_sonnet_5_gets_the_effort_drop_because_the_cache_is_gone_anyway` (py/tests/test_handover_cache_policy.py:476) | | AÇIK |
| `EffortDowngradeTests.test_unknown_warmth_on_sonnet_5_keeps_the_old_behaviour` (py/tests/test_handover_cache_policy.py:482) | | AÇIK |
| `EffortDowngradeTests.test_effort_already_at_or_below_the_target_is_left_alone` (py/tests/test_handover_cache_policy.py:487) | | AÇIK |
| `EffortDowngradeTests.test_effort_command_failure_is_swallowed` (py/tests/test_handover_cache_policy.py:493) | | AÇIK |
| `EffortDowngradeTests.test_public_wrapper_keeps_its_old_positional_signature` (py/tests/test_handover_cache_policy.py:500) | | AÇIK |
| `CallSiteWiringTests.test_cli_path_calls_the_shared_policy_once_per_target` (py/tests/test_handover_cache_policy.py:520) | | AÇIK |
| `CallSiteWiringTests.test_web_path_calls_the_shared_policy_with_the_spawn_time_values` (py/tests/test_handover_cache_policy.py:534) | | AÇIK |
| `CallSiteWiringTests.test_web_path_targets_the_resolved_session_for_unique_base` (py/tests/test_handover_cache_policy.py:547) | | AÇIK |
| `CallSiteWiringTests.test_real_policy_runs_end_to_end_through_the_web_path` (py/tests/test_handover_cache_policy.py:564) | | AÇIK |
| `LastAssistantSinceTests.test_since_returns_only_rows_written_after_the_process_started` (py/tests/test_live_model_effort.py:62) | | AÇIK |
| `LastAssistantSinceTests.test_only_previous_incarnation_rows_means_unknown` (py/tests/test_live_model_effort.py:68) | | AÇIK |
| `LastAssistantSinceTests.test_without_since_behaviour_is_unchanged` (py/tests/test_live_model_effort.py:74) | | AÇIK |
| `LastAssistantSinceTests.test_row_without_timestamp_is_not_treated_as_old` (py/tests/test_live_model_effort.py:79) | | AÇIK |
| `LastAssistantSinceTests.test_scan_stops_at_the_first_older_row` (py/tests/test_live_model_effort.py:84) | | AÇIK |
| `LiveModelEffortTests.test_live_values_written_by_this_process_replace_cmdline_values` (py/tests/test_live_model_effort.py:107) | | AÇIK |
| `LiveModelEffortTests.test_fresh_resume_without_a_turn_keeps_cmdline_values` (py/tests/test_live_model_effort.py:111) | | AÇIK |
| `LiveModelEffortTests.test_effort_missing_in_live_rows_falls_back_per_field` (py/tests/test_live_model_effort.py:115) | | AÇIK |
| `LiveModelEffortTests.test_another_sessions_file_is_ignored` (py/tests/test_live_model_effort.py:119) | | AÇIK |
| `LiveModelEffortTests.test_non_claude_and_sidless_sessions_never_touch_the_file` (py/tests/test_live_model_effort.py:123) | | AÇIK |
| `LiveModelEffortTests.test_unknown_process_start_falls_back` (py/tests/test_live_model_effort.py:129) | | AÇIK |
| `LiveModelEffortTests.test_unchanged_file_is_not_reread_and_changed_file_is_` (py/tests/test_live_model_effort.py:133) | | AÇIK |
| `LiveModelEffortTests.test_read_error_falls_back_and_does_not_raise` (py/tests/test_live_model_effort.py:151) | | AÇIK |
| `LiveModelEndpointTests.test_live_model_ignores_previous_incarnation` (py/tests/test_live_model_effort.py:168) | | AÇIK |
| `LiveModelEndpointTests.test_live_effort_ignores_previous_incarnation` (py/tests/test_live_model_effort.py:175) | | AÇIK |
| `LiveModelEndpointTests.test_neighbour_transcript_is_not_reported` (py/tests/test_live_model_effort.py:183) | | AÇIK |
| `EffortSwitchNoBlindEnter.test_no_dialog_no_enter` (py/tests/test_live_model_effort.py:215) | | AÇIK |
| `NoteMirrorTests.test_records_the_pid_under_the_spec` (py/tests/test_mirror_marker.py:47) | | AÇIK |
| `NoteMirrorTests.test_same_spec_accumulates_pids` (py/tests/test_mirror_marker.py:52) | | AÇIK |
| `NoteMirrorTests.test_anything_else_leaves_the_dict_alone` (py/tests/test_mirror_marker.py:58) | | AÇIK |
| `FindSessionsMirrorsOutTests.test_viewers_are_collected_in_the_same_pass` (py/tests/test_mirror_marker.py:91) | | AÇIK |
| `FindSessionsMirrorsOutTests.test_viewers_are_not_sessions_and_fleet_result_is_unchanged` (py/tests/test_mirror_marker.py:97) | | AÇIK |
| `FindSessionsMirrorsOutTests.test_default_does_not_collect_anything` (py/tests/test_mirror_marker.py:104) | | AÇIK |
| `FindSessionsMirrorsOutTests.test_a_real_viewer_process_is_seen_by_the_real_scan` (py/tests/test_mirror_marker.py:110) | | AÇIK |
| `MergeStatusMarkerTests.test_open_and_closed_are_stamped_per_remote_row` (py/tests/test_mirror_marker.py:148) | | AÇIK |
| `MergeStatusMarkerTests.test_same_name_on_two_hosts_is_told_apart` (py/tests/test_mirror_marker.py:155) | | AÇIK |
| `MergeStatusMarkerTests.test_match_is_exact_not_a_prefix` (py/tests/test_mirror_marker.py:162) | | AÇIK |
| `MergeStatusMarkerTests.test_cached_rows_are_copied_not_mutated` (py/tests/test_mirror_marker.py:169) | | AÇIK |
| `MergeStatusMarkerTests.test_stale_value_from_upstream_is_overwritten` (py/tests/test_mirror_marker.py:177) | | AÇIK |
| `MergeStatusMarkerTests.test_no_marker_at_all_when_the_state_is_unknown` (py/tests/test_mirror_marker.py:182) | | AÇIK |
| `MergeStatusMarkerTests.test_empty_set_means_known_and_closed` (py/tests/test_mirror_marker.py:187) | | AÇIK |
| `MergeStatusMarkerTests.test_local_closed_and_retired_rows_are_not_stamped` (py/tests/test_mirror_marker.py:192) | | AÇIK |
| `MergeStatusMarkerTests.test_a_dict_works_as_the_container_like_find_sessions_hands_it_over` (py/tests/test_mirror_marker.py:201) | | AÇIK |
| `MergeStatusMarkerTests.test_unpolled_host_adds_no_rows_and_no_crash` (py/tests/test_mirror_marker.py:206) | | AÇIK |
| `StatusPayloadWiringTests.test_remote_rows_carry_the_marker_from_the_fleet_scan` (py/tests/test_mirror_marker.py:243) | | AÇIK |
| `StatusPayloadWiringTests.test_exactly_one_scan_carries_the_collector` (py/tests/test_mirror_marker.py:249) | | AÇIK |
| `StatusPayloadWiringTests.test_a_closed_window_flips_the_marker_on_the_next_tick` (py/tests/test_mirror_marker.py:259) | | AÇIK |
| `SpecFromCmdlineTests.test_host_and_name` (py/tests/test_mirror_window.py:33) | | AÇIK |
| `SpecFromCmdlineTests.test_bare_name_is_local` (py/tests/test_mirror_window.py:36) | | AÇIK |
| `SpecFromCmdlineTests.test_flags_before_or_after_the_target` (py/tests/test_mirror_window.py:39) | | AÇIK |
| `SpecFromCmdlineTests.test_value_of_a_flag_is_not_mistaken_for_the_target` (py/tests/test_mirror_window.py:44) | | AÇIK |
| `SpecFromCmdlineTests.test_once_is_not_a_window` (py/tests/test_mirror_window.py:47) | | AÇIK |
| `SpecFromCmdlineTests.test_other_commands_do_not_match` (py/tests/test_mirror_window.py:50) | | AÇIK |
| `SpecFromCmdlineTests.test_watch_without_a_target` (py/tests/test_mirror_window.py:56) | | AÇIK |
| `SpecFromCmdlineTests.test_empty_parts` (py/tests/test_mirror_window.py:60) | | AÇIK |
| `RunningMirrorsTests.test_collects_pids_per_spec` (py/tests/test_mirror_window.py:78) | | AÇIK |
| `RunningMirrorsTests.test_other_users_processes_are_ignored` (py/tests/test_mirror_window.py:83) | | AÇIK |
| `RunningMirrorsTests.test_unreadable_processes_are_skipped` (py/tests/test_mirror_window.py:86) | | AÇIK |
| `RunningMirrorsTests.test_default_uid_is_the_current_user` (py/tests/test_mirror_window.py:89) | | AÇIK |
| `RunningMirrorsTests.test_a_process_vanishing_mid_scan_is_skipped` (py/tests/test_mirror_window.py:94) | | AÇIK |
| `FocusWindowTests.test_uses_exact_title_matching_and_the_given_display` (py/tests/test_mirror_window.py:104) | | AÇIK |
| `FocusWindowTests.test_failures_are_false_not_exceptions` (py/tests/test_mirror_window.py:117) | | AÇIK |
| `OpenMirrorWindowSpawnTests.test_gnome_terminal_argv` (py/tests/test_mirror_window.py:138) | | AÇIK |
| `OpenMirrorWindowSpawnTests.test_the_command_runs_cops_watch_against_this_panels_port` (py/tests/test_mirror_window.py:145) | | AÇIK |
| `OpenMirrorWindowSpawnTests.test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it` (py/tests/test_mirror_window.py:151) | | AÇIK |
| `OpenMirrorWindowSpawnTests.test_arguments_are_shell_quoted` (py/tests/test_mirror_window.py:158) | | AÇIK |
| `OpenMirrorWindowSpawnTests.test_environment` (py/tests/test_mirror_window.py:162) | | AÇIK |
| `OpenMirrorWindowSpawnTests.test_popen_failure_is_false` (py/tests/test_mirror_window.py:170) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_success_spawns_once_with_the_panels_port` (py/tests/test_mirror_window.py:211) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_local_sessions_are_rejected` (py/tests/test_mirror_window.py:215) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_bad_characters_never_reach_the_command_line` (py/tests/test_mirror_window.py:222) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_unknown_host` (py/tests/test_mirror_window.py:229) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_session_must_be_in_the_hosts_last_known_state` (py/tests/test_mirror_window.py:234) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_a_session_without_tmux_has_no_terminal_to_mirror` (py/tests/test_mirror_window.py:245) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_no_x11_display` (py/tests/test_mirror_window.py:250) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_an_open_mirror_is_focused_not_duplicated` (py/tests/test_mirror_window.py:257) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_force_opens_a_second_one` (py/tests/test_mirror_window.py:263) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_another_sessions_mirror_does_not_count` (py/tests/test_mirror_window.py:269) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_launch_failure` (py/tests/test_mirror_window.py:274) | | AÇIK |
| `OpenMirrorWindowBackendTests.test_messages_follow_the_language` (py/tests/test_mirror_window.py:280) | | AÇIK |
| `MirrorRouteHttpTests.test_route_is_declared_local_only` (py/tests/test_mirror_window.py:323) | | AÇIK |
| `MirrorRouteHttpTests.test_post_with_a_remote_host_field_is_handled_locally` (py/tests/test_mirror_window.py:326) | | AÇIK |
| `MirrorRouteHttpTests.test_force_flag_is_passed_through` (py/tests/test_mirror_window.py:331) | | AÇIK |
| `MirrorRouteHttpTests.test_name_is_required` (py/tests/test_mirror_window.py:335) | | AÇIK |
| `MirrorRouteHttpTests.test_token_is_required` (py/tests/test_mirror_window.py:340) | | AÇIK |
| `LayoutRecognisesMirrorWindowsTests.test_a_mirror_window_is_tiled_once_its_spec_is_known` (py/tests/test_mirror_window.py:355) | | AÇIK |
| `LayoutRecognisesMirrorWindowsTests.test_without_the_spec_it_is_skipped_as_before` (py/tests/test_mirror_window.py:360) | | AÇIK |
| `LayoutRecognisesMirrorWindowsTests.test_title_from_the_viewer_survives_list_windows_cleaning` (py/tests/test_mirror_window.py:365) | | AÇIK |
| `WebNeedsHoCachedTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` (py/tests/test_needs_ho_transcript.py:64) | | AÇIK |
| `WebNeedsHoCachedTests.test_without_a_sid_or_a_matching_file_it_falls_back_to_the_newest_file` (py/tests/test_needs_ho_transcript.py:68) | | AÇIK |
| `HandoverBatchTests.test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd` (py/tests/test_needs_ho_transcript.py:89) | | AÇIK |
| `HandoverBatchTests.test_without_a_sid_it_falls_back_to_the_newest_file` (py/tests/test_needs_ho_transcript.py:93) | | AÇIK |
| `MatchesProcTest.test_repl_is_fleet` (py/tests/test_proc07_io_ucli_not_fleet.py:15) | | AÇIK |
| `MatchesProcTest.test_oneshot_and_reviewer_are_not_fleet` (py/tests/test_proc07_io_ucli_not_fleet.py:18) | | AÇIK |
| `IoAskLiveNameTest.test_rejects_live_same_name` (py/tests/test_proc07_io_ucli_not_fleet.py:28) | | AÇIK |
| `IoAskLiveNameTest.test_other_name_goes_through` (py/tests/test_proc07_io_ucli_not_fleet.py:36) | | AÇIK |
| `NoBlindEnterTest.test_permission_dialog_is_not_confirmed` (py/tests/test_proc08_model_switch_no_blind_enter.py:33) | | AÇIK |
| `NoBlindEnterTest.test_switch_dialog_confirmed_once` (py/tests/test_proc08_model_switch_no_blind_enter.py:36) | | AÇIK |
| `NoBlindEnterTest.test_applied_without_dialog` (py/tests/test_proc08_model_switch_no_blind_enter.py:39) | | AÇIK |
| `TestBase.test_default_and_unsupported_are_none` (py/tests/test_provider_live_context.py:23) | | AÇIK |
| `TestCodex.test_last_token_count_input_tokens` (py/tests/test_provider_live_context.py:43) | | AÇIK |
| `TestCodex.test_no_token_event_or_no_file_is_none` (py/tests/test_provider_live_context.py:47) | | AÇIK |
| `TestCodex.test_null_info_is_none` (py/tests/test_provider_live_context.py:52) | | AÇIK |
| `TestCopilot.test_latest_main_agent_row` (py/tests/test_provider_live_context.py:75) | | AÇIK |
| `TestCopilot.test_unknown_session_or_no_db_is_none` (py/tests/test_provider_live_context.py:78) | | AÇIK |
| `TestStatusRow.test_context_info_uses_provider_hook_and_hides_unknown` (py/tests/test_provider_live_context.py:89) | | AÇIK |
| `WantsSplitTests.test_ucli_no_wrapup_but_has_conversation_and_stuck` (py/tests/test_provider_wants_split.py:15) | | AÇIK |
| `WantsSplitTests.test_claude_defaults_follow_has_conversation` (py/tests/test_provider_wants_split.py:21) | | AÇIK |
| `WantsSplitTests.test_shell_wants_nothing` (py/tests/test_provider_wants_split.py:26) | | AÇIK |
| `DefaultsTest.test_claude_defaults_to_newest_sonnet_medium` (py/tests/test_routing_guidance.py:32) | | AÇIK |
| `DefaultsTest.test_provider_without_model_choices_gives_empty_default` (py/tests/test_routing_guidance.py:38) | | AÇIK |
| `DefaultsTest.test_override_wins_and_invalid_override_falls_back` (py/tests/test_routing_guidance.py:44) | | AÇIK |
| `DefaultsTest.test_other_providers_keep_old_top_level_effort` (py/tests/test_routing_guidance.py:53) | | AÇIK |
| `GuidanceTest.test_enabled_by_default_and_bundled_path_used` (py/tests/test_routing_guidance.py:60) | | AÇIK |
| `GuidanceTest.test_off_disables_flag` (py/tests/test_routing_guidance.py:65) | | AÇIK |
| `GuidanceTest.test_override_text_is_written_and_used` (py/tests/test_routing_guidance.py:71) | | AÇIK |
| `GuidanceTest.test_guidance_failure_never_breaks_spawn` (py/tests/test_routing_guidance.py:80) | | AÇIK |
| `CodexSyncTest.test_agy_file_is_created_with_only_the_block_and_removed_with_it` (py/tests/test_routing_guidance.py:90) | | AÇIK |
| `CodexSyncTest.test_existing_agy_file_keeps_user_text` (py/tests/test_routing_guidance.py:98) | | AÇIK |
| `CodexSyncTest.test_missing_file_is_not_created` (py/tests/test_routing_guidance.py:117) | | AÇIK |
| `CodexSyncTest.test_write_is_idempotent_keeps_rest_and_backs_up` (py/tests/test_routing_guidance.py:122) | | AÇIK |
| `CodexSyncTest.test_text_change_replaces_block_and_off_removes_it` (py/tests/test_routing_guidance.py:131) | | AÇIK |
| `RustToolchainPickTest.test_single_toolchain_without_env` (py/tests/test_rust_toolchain_pick.py:30) | | AÇIK |
| `RustToolchainPickTest.test_prefix_match` (py/tests/test_rust_toolchain_pick.py:35) | | AÇIK |
| `RustToolchainPickTest.test_mismatch_is_error_not_fallback` (py/tests/test_rust_toolchain_pick.py:40) | | AÇIK |
| `RustToolchainDefaultTest.test_single_toolchain_without_env` (py/tests/test_rust_toolchain_pick.py:59) | | AÇIK |
| `RustToolchainDefaultTest.test_default_toolchain_picks_one` (py/tests/test_rust_toolchain_pick.py:64) | | AÇIK |
| `RustToolchainDefaultTest.test_short_default_name` (py/tests/test_rust_toolchain_pick.py:70) | | AÇIK |
| `RustToolchainDefaultTest.test_env_still_wins` (py/tests/test_rust_toolchain_pick.py:76) | | AÇIK |
| `ServiceModelsCache.test_ttl_is_24h` (py/tests/test_service_models_cache.py:28) | | AÇIK |
| `ServiceModelsCache.test_success_cached_for_a_day` (py/tests/test_service_models_cache.py:31) | | AÇIK |
| `ServiceModelsCache.test_failure_returns_empty_and_retries_after_60s` (py/tests/test_service_models_cache.py:48) | | AÇIK |
| `DetectDisplayTest.test_socket_only_x0` (py/tests/test_spawn_detect_display_socket.py:25) | | AÇIK |
| `DetectDisplayTest.test_lock_still_works` (py/tests/test_spawn_detect_display_socket.py:28) | | AÇIK |
| `DetectDisplayTest.test_prefers_1_over_0` (py/tests/test_spawn_detect_display_socket.py:31) | | AÇIK |
| `DetectDisplayTest.test_nothing_defaults_1` (py/tests/test_spawn_detect_display_socket.py:34) | | AÇIK |
| `DetectDisplayTest.test_env_wins` (py/tests/test_spawn_detect_display_socket.py:37) | | AÇIK |
| `EnvFilter.test_filters` (py/tests/test_spawn_env_filter.py:11) | | AÇIK |
| `GhostDetectTest.test_old_bare_bash_is_ghost` (py/tests/test_spawn_ghost_reclaim.py:25) | | AÇIK |
| `GhostDetectTest.test_live_cli_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:28) | | AÇIK |
| `GhostDetectTest.test_young_session_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:31) | | AÇIK |
| `GhostDetectTest.test_bash_with_child_is_not_ghost` (py/tests/test_spawn_ghost_reclaim.py:34) | | AÇIK |
| `GhostDetectTest.test_no_session_or_garbage` (py/tests/test_spawn_ghost_reclaim.py:37) | | AÇIK |
| `GhostDetectTest.test_mixed_panes` (py/tests/test_spawn_ghost_reclaim.py:42) | | AÇIK |
| `ReclaimTest.test_ghost_killed_and_tail_logged` (py/tests/test_spawn_ghost_reclaim.py:57) | | AÇIK |
| `ReclaimTest.test_shell_provider_untouched` (py/tests/test_spawn_ghost_reclaim.py:63) | | AÇIK |
| `ReclaimTest.test_not_ghost_untouched` (py/tests/test_spawn_ghost_reclaim.py:66) | | AÇIK |
| `ReclaimTest.test_error_never_raises` (py/tests/test_spawn_ghost_reclaim.py:69) | | AÇIK |
| `SpawnPriority.test_default_and_exempt_and_off` (py/tests/test_spawn_priority.py:17) | | AÇIK |
| `SpawnPriority.test_child_inherits_nice` (py/tests/test_spawn_priority.py:27) | | AÇIK |
| `TestDefaultClaudeMdGolden.test_default_output_is_byte_identical_to_pre_p5` (py/tests/test_steward_brain.py:62) | | AÇIK |
| `TestDefaultClaudeMdGolden.test_identity_section_only_for_non_default` (py/tests/test_steward_brain.py:71) | | AÇIK |
| `TestWorkspace.test_default_workspace_claude_md_is_unchanged_and_not_rewritten` (py/tests/test_steward_brain.py:144) | | AÇIK |
| `TestWorkspace.test_default_persona_override_still_applies` (py/tests/test_steward_brain.py:157) | | AÇIK |
| `TestWorkspace.test_identity_workspace_is_separate_with_identity_and_model_rule` (py/tests/test_steward_brain.py:163) | | AÇIK |
| `TestWorkspace.test_identity_persona_falls_back_to_shared` (py/tests/test_steward_brain.py:180) | | AÇIK |
| `TestBrainMcp.test_verify_uses_connect_heartbeat` (py/tests/test_steward_brain.py:193) | | AÇIK |
| `TestBrainMcp.test_start_without_mcp_restarts_once_then_gives_up` (py/tests/test_steward_brain.py:201) | | AÇIK |
| `TestBrainMcp.test_start_defaults_to_new_conversation` (py/tests/test_steward_brain.py:216) | | AÇIK |
| `TestBrainMcp.test_close_note_written_without_model_turn` (py/tests/test_steward_brain.py:223) | | AÇIK |
| `TestBrainMcp.test_notools_verdict_pure` (py/tests/test_steward_brain.py:231) | | AÇIK |
| `TestBrainMcp.test_recover_restarts_once_with_cooldown` (py/tests/test_steward_brain.py:249) | | AÇIK |
| `TestBrainMcp.test_mcp_server_heartbeat_hook` (py/tests/test_steward_brain.py:265) | | AÇIK |
| `TestBrainMcp.test_touch_records_call_and_connect` (py/tests/test_steward_brain.py:274) | | AÇIK |
| `TestBrainStart.test_brain_spec_default_is_the_old_command_line` (py/tests/test_steward_brain.py:282) | | AÇIK |
| `TestBrainStart.test_disabled_identity_never_starts_a_brain` (py/tests/test_steward_brain.py:289) | | AÇIK |
| `TestBrainStart.test_enabled_identity_starts_its_own_brain` (py/tests/test_steward_brain.py:306) | | AÇIK |
| `TestBrainStart.test_default_brain_start_is_unchanged` (py/tests/test_steward_brain.py:324) | | AÇIK |
| `TestBrainStart.test_running_brain_is_not_started_twice` (py/tests/test_steward_brain.py:338) | | AÇIK |
| `TestBrainStart.test_brain_stop_uses_only_the_act_stop_path_with_the_exact_name` (py/tests/test_steward_brain.py:345) | | AÇIK |
| `TestClaudeMcpConfigFile.test_identity_gets_its_own_config_file` (py/tests/test_steward_brain.py:353) | | AÇIK |
| `TestMcpIdentity.test_default_server_adds_nothing` (py/tests/test_steward_brain.py:379) | | AÇIK |
| `TestMcpIdentity.test_identity_server_adds_it_to_every_call_and_the_brain_cannot_change_it` (py/tests/test_steward_brain.py:390) | | AÇIK |
| `TestMcpIdentity.test_run_validates_the_identity_and_sets_it` (py/tests/test_steward_brain.py:420) | | AÇIK |
| `TestMcpIdentity.test_cli_parses_the_flag` (py/tests/test_steward_brain.py:433) | | AÇIK |
| `TestCtxFor.test_resolution` (py/tests/test_steward_brain.py:445) | | AÇIK |
| `TestCtxFor.test_unknown_identity_is_an_explicit_error_and_writes_nothing` (py/tests/test_steward_brain.py:456) | | AÇIK |
| `TestCtxFor.test_no_param_means_default_and_old_callers_work` (py/tests/test_steward_brain.py:467) | | AÇIK |
| `TestCtxFor.test_requests_reach_the_right_store` (py/tests/test_steward_brain.py:475) | | AÇIK |
| `TestCtxFor.test_manual_tick_and_note_and_skip_use_the_identity` (py/tests/test_steward_brain.py:501) | | AÇIK |
| `TestHumanGate.test_human_in_default_context_is_unrestricted` (py/tests/test_steward_brain.py:532) | | AÇIK |
| `TestHumanGate.test_human_in_other_context_only_own_projects_and_brain` (py/tests/test_steward_brain.py:542) | | AÇIK |
| `TestHumanGate.test_brain_in_identity_context` (py/tests/test_steward_brain.py:554) | | AÇIK |
| `TestHumanGate.test_reads_are_limited_to_own_projects_outside_default` (py/tests/test_steward_brain.py:563) | | AÇIK |
| `StoreTest.test_project_roundtrip_and_validation` (py/tests/test_steward_core_a.py:56) | | AÇIK |
| `StoreTest.test_defer_answer_keeps_question_open` (py/tests/test_steward_core_a.py:67) | | AÇIK |
| `StoreTest.test_questions_dedup_answer_deliver` (py/tests/test_steward_core_a.py:76) | | AÇIK |
| `StoreTest.test_ideas_and_log` (py/tests/test_steward_core_a.py:88) | | AÇIK |
| `StoreTest.test_persona_override_and_bundled` (py/tests/test_steward_core_a.py:99) | | AÇIK |
| `MarkerTest.test_scan_markers_ask_ending_with_colon_takes_following_lines` (py/tests/test_steward_core_a.py:105) | | AÇIK |
| `MarkerTest.test_scan_markers_ignores_writing_examples` (py/tests/test_steward_core_a.py:117) | | AÇIK |
| `MarkerTest.test_scan_markers_ignores_inline_code_mention_in_prose` (py/tests/test_steward_core_a.py:126) | | AÇIK |
| `MarkerTest.test_scan_markers_job_line` (py/tests/test_steward_core_a.py:135) | | AÇIK |
| `MarkerTest.test_scan_markers` (py/tests/test_steward_core_a.py:152) | | AÇIK |
| `PromptTest.test_directive_by_phase_and_answer` (py/tests/test_steward_core_a.py:167) | | AÇIK |
| `PromptTest.test_tour_prompt_lists_items_and_end_marker` (py/tests/test_steward_core_a.py:182) | | AÇIK |
| `PromptTest.test_workspace_claude_md` (py/tests/test_steward_core_a.py:192) | | AÇIK |
| `RulesTest.test_handover_then_respawn` (py/tests/test_steward_core_a.py:206) | | AÇIK |
| `RulesTest.test_handover_grace_expiry_and_gone_session` (py/tests/test_steward_core_a.py:222) | | AÇIK |
| `RulesTest.test_markers_once_per_reply` (py/tests/test_steward_core_a.py:230) | | AÇIK |
| `RulesTest.test_done_marker_stops_session` (py/tests/test_steward_core_a.py:240) | | AÇIK |
| `RulesTest.test_done_confirmed_with_open_owner_question_pauses_not_done` (py/tests/test_steward_core_a.py:244) | | AÇIK |
| `RulesTest.test_done_marker_ignored_when_project_notes_have_no_done_tag` (py/tests/test_steward_core_a.py:255) | | AÇIK |
| `RulesTest.test_due_projects_respect_slots_priority_and_cadence` (py/tests/test_steward_core_a.py:261) | | AÇIK |
| `RulesTest.test_todo_change_opens_active_project_without_waiting_cadence` (py/tests/test_steward_core_a.py:274) | | AÇIK |
| `RulesTest.test_todo_change_reopens_done_project_to_planned` (py/tests/test_steward_core_a.py:292) | | AÇIK |
| `RulesTest.test_todo_change_paused_project_asks_owner_once_per_day` (py/tests/test_steward_core_a.py:303) | | AÇIK |
| `RulesTest.test_first_observation_done_project_with_open_work_goes_planned` (py/tests/test_steward_core_a.py:318) | | AÇIK |
| `RulesTest.test_daily_sweep_done_project_with_unchanged_sha` (py/tests/test_steward_core_a.py:327) | | AÇIK |
| `RulesTest.test_daily_sweep_paused_asks_once` (py/tests/test_steward_core_a.py:339) | | AÇIK |
| `RulesTest.test_only_fable_cila_open_work_does_not_trigger` (py/tests/test_steward_core_a.py:347) | | AÇIK |
| `RulesTest.test_drain_starts_nothing_but_keeps_answers_and_running` (py/tests/test_steward_core_a.py:354) | | AÇIK |
| `RulesTest.test_slot_pressure_stops_idle_session` (py/tests/test_steward_core_a.py:361) | | AÇIK |
| `RulesTest.test_answer_delivery_running_busy_or_stopped` (py/tests/test_steward_core_a.py:372) | | AÇIK |
| `RulesTest.test_adhoc_session_answer_goes_to_asking_session_only_if_running` (py/tests/test_steward_core_a.py:382) | | AÇIK |
| `RulesTest.test_instance_sessions_map_to_blueprint_project` (py/tests/test_steward_core_a.py:394) | | AÇIK |
| `RulesTest.test_tour_only_when_brain_idle_and_due` (py/tests/test_steward_core_a.py:400) | | AÇIK |
| `RulesTest.test_phase_model_effort` (py/tests/test_steward_core_a.py:416) | | AÇIK |
| `CardCoreTest.test_build_raw_card_reads_doc_heads_and_git` (py/tests/test_steward_core_a.py:424) | | AÇIK |
| `CardCoreTest.test_raw_card_without_git_or_docs` (py/tests/test_steward_core_a.py:440) | | AÇIK |
| `CardCoreTest.test_parse_card_json_variants` (py/tests/test_steward_core_a.py:452) | | AÇIK |
| `CardCoreTest.test_make_card_falls_back_to_raw_fields` (py/tests/test_steward_core_a.py:465) | | AÇIK |
| `CardCoreTest.test_refresh_reason_matrix_and_failure_backoff` (py/tests/test_steward_core_a.py:483) | | AÇIK |
| `CardCoreTest.test_store_stale_and_listing` (py/tests/test_steward_core_a.py:506) | | AÇIK |
| `CardCoreTest.test_model_pick_prompt_and_tour_rendering` (py/tests/test_steward_core_a.py:517) | | AÇIK |
| `OneshotProviderTest.test_claude_argv_shape_and_unsupported_default` (py/tests/test_steward_core_a.py:534) | | AÇIK |
| `OneshotProviderTest.test_ucli_oneshot_uses_chat_once_without_key_in_argv` (py/tests/test_steward_core_a.py:560) | | AÇIK |
| `OneshotProviderTest.test_oneshot_runs_argv_and_reports_failures` (py/tests/test_steward_core_a.py:579) | | AÇIK |
| `SimilarAnswersTest.test_ranks_by_similarity_and_excludes_self` (py/tests/test_steward_core_a.py:604) | | AÇIK |
| `SimilarAnswersTest.test_open_or_unanswered_ignored_and_prompt_renders` (py/tests/test_steward_core_a.py:613) | | AÇIK |
| `RosterGateTest.test_active_phase_needs_roster_but_idea_does_not` (py/tests/test_steward_core_a.py:622) | | AÇIK |
| `ScanCacheTest.test_scan_is_cached_inside_a_scope_and_invalidated_by_start` (py/tests/test_steward_core_a.py:636) | | AÇIK |
| `EngineSmallsTest.test_fail_logged_is_pruned_and_thread_safe` (py/tests/test_steward_core_a.py:663) | | AÇIK |
| `EngineSmallsTest.test_shutdown_blockers_survive_corrupt_jobs_file` (py/tests/test_steward_core_a.py:673) | | AÇIK |
| `ShutdownOnlyLeavesPausedTest.test_done_records_left_paused_and_warns` (py/tests/test_steward_core_a.py:685) | | AÇIK |
| `BrainCannotPauseTest.test_brain_cannot_pause_or_done_but_owner_can` (py/tests/test_steward_core_a.py:705) | | AÇIK |
| `ShutdownPlanTest.test_waits_for_quiet_then_handover_then_stop_then_brain` (py/tests/test_steward_core_a.py:721) | | AÇIK |
| `ShutdownPlanTest.test_subagent_blocks_and_timeouts_leave_session_open` (py/tests/test_steward_core_a.py:749) | | AÇIK |
| `ShutdownPlanTest.test_stale_ready_text_before_handover_does_not_count` (py/tests/test_steward_core_a.py:762) | | AÇIK |
| `ReviewFindings20261029Test.test_job_requests_for_different_files_are_not_merged` (py/tests/test_steward_core_a.py:773) | | AÇIK |
| `ReviewFindings20261029Test.test_done_and_plan_ready_in_prose_are_ignored` (py/tests/test_steward_core_a.py:779) | | AÇIK |
| `ReviewFindings20261029Test.test_owner_only_false_positives` (py/tests/test_steward_core_a.py:787) | | AÇIK |
| `OpenQuestionMergeTest.test_paraphrased_open_question_is_merged` (py/tests/test_steward_core_a.py:798) | | AÇIK |
| `OpenQuestionMergeTest.test_other_project_or_topic_not_merged` (py/tests/test_steward_core_a.py:808) | | AÇIK |
| `OpenQuestionMergeTest.test_short_distinct_questions_not_merged` (py/tests/test_steward_core_a.py:814) | | AÇIK |
| `OpenQuestionMergeTest.test_routine_question_promoted_when_asked_to_owner` (py/tests/test_steward_core_a.py:819) | | AÇIK |
| `OpenQuestionMergeTest.test_answered_question_not_merged_into_open_path` (py/tests/test_steward_core_a.py:834) | | AÇIK |
| `TopicMergeTest.test_topic_tokens` (py/tests/test_steward_core_a.py:851) | | AÇIK |
| `TopicMergeTest.test_generic_names_alone_do_not_match` (py/tests/test_steward_core_a.py:856) | | AÇIK |
| `TopicMergeTest.test_open_question_rephrased_is_merged_and_keeps_old_text` (py/tests/test_steward_core_a.py:861) | | AÇIK |
| `TopicMergeTest.test_hold_answer_suppresses_same_topic` (py/tests/test_steward_core_a.py:873) | | AÇIK |
| `TopicMergeTest.test_non_hold_answer_lets_new_decision_open` (py/tests/test_steward_core_a.py:880) | | AÇIK |
| `TopicMergeTest.test_old_open_question_outside_window_not_merged` (py/tests/test_steward_core_a.py:887) | | AÇIK |
| `TopicMergeTest.test_other_project_not_merged` (py/tests/test_steward_core_a.py:895) | | AÇIK |
| `SalientReaskTest.test_paraphrased_same_topic_is_duplicate` (py/tests/test_steward_core_a.py:905) | | AÇIK |
| `SalientReaskTest.test_different_topic_not_duplicate` (py/tests/test_steward_core_a.py:910) | | AÇIK |
| `DoneDeferralTest.test_done_deferred_while_subagent_then_applied` (py/tests/test_steward_core_a.py:916) | | AÇIK |
| `DoneDeferralTest.test_deferred_done_dropped_when_no_done_tag_added_later` (py/tests/test_steward_core_a.py:927) | | AÇIK |
| `DoneDeferralTest.test_done_immediate_without_subagent` (py/tests/test_steward_core_a.py:938) | | AÇIK |
| `AnswerStartPhaseTest.test_active_phase_starts` (py/tests/test_steward_core_a.py:952) | | AÇIK |
| `AnswerStartPhaseTest.test_owner_answer_reopens_paused_and_done_project` (py/tests/test_steward_core_a.py:955) | | AÇIK |
| `NegativeAnswerTest.test_is_negative_answer` (py/tests/test_steward_core_a.py:963) | | AÇIK |
| `NegativeAnswerTest.test_negative_answer_does_not_reopen` (py/tests/test_steward_core_a.py:975) | | AÇIK |
| `NegativeAnswerTest.test_hold_answers_real_texts_do_not_reopen` (py/tests/test_steward_core_a.py:980) | | AÇIK |
| `NegativeAnswerTest.test_sweep_question_has_options` (py/tests/test_steward_core_a.py:991) | | AÇIK |
| `HeldInstructionAnswerTest.test_long_owner_instruction_reaches_brain` (py/tests/test_steward_core_a.py:1018) | | AÇIK |
| `HeldInstructionAnswerTest.test_second_held_instruction_gets_its_own_item` (py/tests/test_steward_core_a.py:1027) | | AÇIK |
| `HeldInstructionAnswerTest.test_later_question_does_not_overwrite_held_item` (py/tests/test_steward_core_a.py:1032) | | AÇIK |
| `HeldInstructionAnswerTest.test_short_hold_brain_and_routine_answers_stay_silent` (py/tests/test_steward_core_a.py:1039) | | AÇIK |
| `DoneHandoverTest.test_done_hands_over_then_stops_never_respawns` (py/tests/test_steward_core_a.py:1063) | | AÇIK |
| `DoneHandoverTest.test_session_gone_during_done_handover_is_not_respawned` (py/tests/test_steward_core_a.py:1074) | | AÇIK |
| `DoneHandoverTest.test_grace_expiry_still_stops` (py/tests/test_steward_core_a.py:1080) | | AÇIK |
| `DoneHandoverTest.test_small_context_skips_handover` (py/tests/test_steward_core_a.py:1087) | | AÇIK |
| `DoneHandoverTest.test_switch_off_is_old_direct_stop` (py/tests/test_steward_core_a.py:1095) | | AÇIK |
| `DoneHandoverTest.test_owner_answer_stops_reasking_and_bitti_closes` (py/tests/test_steward_core_a.py:1101) | | AÇIK |
| `DoneHandoverTest.test_unknown_open_work_symlinked_worktree_accepts_proof` (py/tests/test_steward_core_a.py:1115) | | AÇIK |
| `DoneHandoverTest.test_unanswered_conflict_still_asks` (py/tests/test_steward_core_a.py:1122) | | AÇIK |
| `DoneConfirmTest.test_plain_done_asks_for_confirmation_and_keeps_phase` (py/tests/test_steward_core_a.py:1139) | | AÇIK |
| `DoneConfirmTest.test_second_plain_done_does_not_spam_but_ttl_reasks` (py/tests/test_steward_core_a.py:1147) | | AÇIK |
| `DoneConfirmTest.test_confirmed_with_evidence_sets_done_and_stops` (py/tests/test_steward_core_a.py:1155) | | AÇIK |
| `DoneConfirmTest.test_confirmed_without_evidence_is_not_done` (py/tests/test_steward_core_a.py:1160) | | AÇIK |
| `DoneConfirmTest.test_confirmed_but_local_open_work_asks_owner_not_done` (py/tests/test_steward_core_a.py:1166) | | AÇIK |
| `DoneConfirmTest.test_no_steward_done_tag_ignores_both_markers` (py/tests/test_steward_core_a.py:1178) | | AÇIK |
| `DoneConfirmTest.test_confirm_marker_is_not_plain_done_and_placeholder_ignored` (py/tests/test_steward_core_a.py:1184) | | AÇIK |
| `DoneConfirmTest.test_subagent_active_defers_confirmed` (py/tests/test_steward_core_a.py:1192) | | AÇIK |
| `DoneConfirmTest.test_open_work_of_counts_local_todo` (py/tests/test_steward_core_a.py:1197) | | AÇIK |
| `DoneConfirmTest.test_open_tbd_of_falls_back_to_main_worktree` (py/tests/test_steward_core_a.py:1212) | | AÇIK |
| `TourQuietTest.test_skipped_unchanged_item_stays_out_until_state_changes_or_ttl` (py/tests/test_steward_core_a.py:1242) | | AÇIK |
| `TourQuietTest.test_plan_tick_records_tour_sig_and_honors_skip_seen` (py/tests/test_steward_core_a.py:1256) | | AÇIK |
| `TourQuietTest.test_stale_undelivered_answer_closed_not_toured` (py/tests/test_steward_core_a.py:1270) | | AÇIK |
| `TourQuietTest.test_projectless_answer_closes_when_brain_never_runs` (py/tests/test_steward_core_a.py:1285) | | AÇIK |
| `TourQuietTest.test_brain_question_answer_goes_to_live_session_named_by_project` (py/tests/test_steward_core_a.py:1299) | | AÇIK |
| `TourQuietTest.test_keepwarm_ok_does_not_change_the_item_signature_and_routine_carries_age` (py/tests/test_steward_core_a.py:1309) | | AÇIK |
| `TourQuietTest.test_observe_tour_does_not_burn_blocked_tour_budget` (py/tests/test_steward_core_a.py:1323) | | AÇIK |
| `TourQuietTest.test_pending_count_is_the_full_list_even_when_a_tour_is_sent` (py/tests/test_steward_core_a.py:1339) | | AÇIK |
| `TourQuietTest.test_count_open_tbd_new_format_needs_an_AÇIK_heading` (py/tests/test_steward_core_a.py:1350) | | AÇIK |
| `TourQuietTest.test_shutdown_unknown_activity_waits_unless_idle` (py/tests/test_steward_core_a.py:1356) | | AÇIK |
| `TourQuietTest.test_blocked_item_closed_after_max_tours_not_urgent_again` (py/tests/test_steward_core_a.py:1364) | | AÇIK |
| `IdleSkipTest.test_no_idle_item_for_waiting_or_done_projects` (py/tests/test_steward_core_a.py:1389) | | AÇIK |
| `MergedAnswersTest.test_planner_merges_same_session_answers_in_one_action` (py/tests/test_steward_core_a.py:1405) | | AÇIK |
| `MergedAnswersTest.test_answer_waits_while_subagent_active` (py/tests/test_steward_core_a.py:1413) | | AÇIK |
| `MergedAnswersTest.test_subagent_active_for_reads_mtime` (py/tests/test_steward_core_a.py:1421) | | AÇIK |
| `MergedAnswersTest.test_compact_answer_directive_drops_preamble` (py/tests/test_steward_core_a.py:1438) | | AÇIK |
| `MergedAnswersTest.test_directive_contains_all_answers` (py/tests/test_steward_core_a.py:1454) | | AÇIK |
| `ScanTicksTest.test_leading_code_tick_in_question_kept` (py/tests/test_steward_core_b.py:56) | | AÇIK |
| `ScanTicksTest.test_wrapped_marker_and_wrapped_body` (py/tests/test_steward_core_b.py:60) | | AÇIK |
| `PlanMarkersTest.test_records_asks_and_ideas_only` (py/tests/test_steward_core_b.py:71) | | AÇIK |
| `PlanMarkersTest.test_same_reply_not_rescanned_and_routine_needs_question_mark` (py/tests/test_steward_core_b.py:77) | | AÇIK |
| `PlanMarkersTest.test_matches_plan_tick_marker_actions` (py/tests/test_steward_core_b.py:84) | | AÇIK |
| `ObserveCoreTest.test_filter_act_passes_everything_and_clears_traces` (py/tests/test_steward_core_b.py:93) | | AÇIK |
| `ObserveCoreTest.test_filter_observe_splits_dedups_and_prunes` (py/tests/test_steward_core_b.py:100) | | AÇIK |
| `ObserveCoreTest.test_observed_visit_paces_due_projects_across_ticks` (py/tests/test_steward_core_b.py:117) | | AÇIK |
| `SummaryCoreTest.test_daily_summary_counts_and_filters_by_date` (py/tests/test_steward_core_b.py:138) | | AÇIK |
| `SummaryCoreTest.test_summary_due` (py/tests/test_steward_core_b.py:171) | | AÇIK |
| `SummaryCoreTest.test_log_reader_and_summary_text` (py/tests/test_steward_core_b.py:179) | | AÇIK |
| `SummaryCoreTest.test_compact_log_folds_ticks_and_keeps_summary_identical` (py/tests/test_steward_core_b.py:195) | | AÇIK |
| `SummaryCoreTest.test_missed_summary_dates_and_catch_up` (py/tests/test_steward_core_b.py:236) | | AÇIK |
| `RoutineQuestionTest.test_marker_scan_and_session_reply_opens_routine_ask` (py/tests/test_steward_core_b.py:277) | | AÇIK |
| `RoutineQuestionTest.test_routine_goes_to_brain_tour_not_phone_and_escalates_late` (py/tests/test_steward_core_b.py:288) | | AÇIK |
| `RoutineQuestionTest.test_brain_answer_is_delivered_like_any_answer` (py/tests/test_steward_core_b.py:313) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_finished_handover_of_second_session_stops_it_instead_of_respawn` (py/tests/test_steward_core_b.py:320) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_economy_rules_only_touch_managed_sessions` (py/tests/test_steward_core_b.py:333) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_brain_respawn_after_handover_is_a_new_conversation` (py/tests/test_steward_core_b.py:346) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_context_tokens_trigger_handover` (py/tests/test_steward_core_b.py:354) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_line_count_is_only_a_fallback_and_ignores_young_sessions` (py/tests/test_steward_core_b.py:369) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_workspace_claude_md_carries_the_permanent_model_rule` (py/tests/test_steward_core_b.py:392) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_fable_sessions_use_the_lower_context_threshold` (py/tests/test_steward_core_b.py:401) | | AÇIK |
| `OneLiveSessionPerProjectTest.test_context_tokens_from_transcript_tail` (py/tests/test_steward_core_b.py:417) | | AÇIK |
| `StuckBrainTest.test_status_sentence_is_not_a_routine_question_and_tour_is_capped` (py/tests/test_steward_core_b.py:436) | | AÇIK |
| `StuckBrainTest.test_two_failed_tours_restart_the_brain` (py/tests/test_steward_core_b.py:449) | | AÇIK |
| `StuckBrainTest.test_undeliverable_adhoc_answer_is_given_up` (py/tests/test_steward_core_b.py:464) | | AÇIK |
| `DeliveryTargetTest.test_prefers_asking_session_then_main_over_experiment_sessions` (py/tests/test_steward_core_b.py:477) | | AÇIK |
| `ReaskTest.test_similar_answered_question_is_redelivered_not_reopened` (py/tests/test_steward_core_b.py:500) | | AÇIK |
| `ReaskTest.test_repeat_cap_other_project_old_and_clarification_open_new` (py/tests/test_steward_core_b.py:510) | | AÇIK |
| `ReaskTest.test_answered_routine_question_asked_to_owner_opens_new` (py/tests/test_steward_core_b.py:521) | | AÇIK |
| `ReaskTest.test_directive_lists_earlier_answers` (py/tests/test_steward_core_b.py:531) | | AÇIK |
| `QuestionOptionsTest.test_options_normalize_resolve_and_key` (py/tests/test_steward_core_b.py:542) | | AÇIK |
| `QuestionOptionsTest.test_notification_text_and_page_html` (py/tests/test_steward_core_b.py:571) | | AÇIK |
| `SettingsTest.test_defaults_parse_and_clamp` (py/tests/test_steward_core_b.py:596) | | AÇIK |
| `McpTest.test_tools_list_and_dispatch_cover_each_other` (py/tests/test_steward_core_b.py:619) | | AÇIK |
| `McpTest.test_tool_calls_hit_expected_endpoints` (py/tests/test_steward_core_b.py:631) | | AÇIK |
| `JobMarkerParseTest.test_hyphenated_kind_and_malformed_body_are_not_dropped` (py/tests/test_steward_core_b.py:653) | | AÇIK |
| `JobMarkerParseTest.test_prose_mentions_and_placeholders_still_ignored` (py/tests/test_steward_core_b.py:659) | | AÇIK |
| `QuestionPageHttpTest.test_question_page_round_trip` (py/tests/test_steward_core_b.py:693) | | AÇIK |
| `QuestionPageHttpTest.test_notify_phone_sets_click_header` (py/tests/test_steward_core_b.py:716) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_non_routine_question_is_owner_only` (py/tests/test_steward_core_b.py:743) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_routine_owner_only_topics` (py/tests/test_steward_core_b.py:749) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_commit_push_merge_build_deploy_are_not_owner_only` (py/tests/test_steward_core_b.py:756) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_blocked_marker_goes_to_brain_not_owner` (py/tests/test_steward_core_b.py:763) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_rules_text_no_longer_reserves_commit_push_for_owner` (py/tests/test_steward_core_b.py:768) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_readonly_job_request_not_owner_only` (py/tests/test_steward_core_b.py:773) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_plain_routine_is_answerable` (py/tests/test_steward_core_b.py:784) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_defer_reason` (py/tests/test_steward_core_b.py:788) | | AÇIK |
| `BrainAuthorityAndDeferTest.test_tour_retry_gap_after_deferral` (py/tests/test_steward_core_b.py:794) | | AÇIK |
| `TourDeliveryTest.test_short_tour_inline` (py/tests/test_steward_core_b.py:799) | | AÇIK |
| `TourDeliveryTest.test_long_tour_goes_to_file_and_old_files_pruned` (py/tests/test_steward_core_b.py:805) | | AÇIK |
| `ShutdownKeepModeTest.test_keep_does_not_stop` (py/tests/test_steward_core_b.py:831) | | AÇIK |
| `ShutdownKeepModeTest.test_default_stops` (py/tests/test_steward_core_b.py:836) | | AÇIK |
| `ShutdownOnlyTest.test_only_closes_selected_project_and_leaves_rest` (py/tests/test_steward_core_b.py:845) | | AÇIK |
| `ShutdownBlockersTest.test_quiet_session_without_blocker_gets_handover` (py/tests/test_steward_core_b.py:868) | | AÇIK |
| `ShutdownBlockersTest.test_blocked_session_waits_and_records_reason` (py/tests/test_steward_core_b.py:872) | | AÇIK |
| `ShutdownBlockersTest.test_blocked_session_left_open_after_wait_max` (py/tests/test_steward_core_b.py:879) | | AÇIK |
| `SmartTickTest.test_count_open_tbd` (py/tests/test_steward_core_b.py:893) | | AÇIK |
| `SmartTickTest.test_routine_question_skips_tour_interval` (py/tests/test_steward_core_b.py:898) | | AÇIK |
| `SmartTickTest.test_done_confirmed_with_open_tbd_asks_owner` (py/tests/test_steward_core_b.py:913) | | AÇIK |
| `SmartTickTest.test_tbd_only_project_not_started_owner_asked_once` (py/tests/test_steward_core_b.py:925) | | AÇIK |
| `SmartTickTest.test_brain_stopped_project_not_restarted_by_cadence_until_cooldown` (py/tests/test_steward_core_b.py:935) | | AÇIK |
| `SmartTickTest.test_idle_session_without_open_todo_not_nudged` (py/tests/test_steward_core_b.py:947) | | AÇIK |
| `AskStatusLineTests.test_status_lines_do_not_open_records` (py/tests/test_steward_core_b.py:960) | | AÇIK |
| `AskBaseTests.test_dated_session_name_collapses_to_base` (py/tests/test_steward_core_b.py:970) | | AÇIK |
| `DeferAnswerTests.test_is_defer_answer` (py/tests/test_steward_core_b.py:981) | | AÇIK |
| `DeferAnswerTests.test_digest_hides_deferred_until_expiry` (py/tests/test_steward_core_b.py:987) | | AÇIK |
| `StartDecisionEventTests.test_event_shape` (py/tests/test_steward_core_b.py:995) | | AÇIK |
| `ExpiredHandoverNoteTest.test_note_helper` (py/tests/test_steward_core_b.py:1007) | | AÇIK |
| `ExpiredHandoverNoteTest.test_expired_without_marker_carries_note` (py/tests/test_steward_core_b.py:1021) | | AÇIK |
| `ExpiredHandoverNoteTest.test_ready_marker_has_no_card_note` (py/tests/test_steward_core_b.py:1026) | | AÇIK |
| `UcliStuckLadderTest.test_shorten_helper` (py/tests/test_steward_core_b.py:1040) | | AÇIK |
| `UcliStuckLadderTest.test_ladder` (py/tests/test_steward_core_b.py:1047) | | AÇIK |
| `RemoteRespawnNoteTest.test_note_reaches_directive` (py/tests/test_steward_core_b.py:1074) | | AÇIK |
| `RemoteRespawnNoteTest.test_no_note_keeps_empty_directive` (py/tests/test_steward_core_b.py:1079) | | AÇIK |
| `ContextQuestionTest.test_classifier` (py/tests/test_steward_ctx.py:71) | | AÇIK |
| `ContextQuestionTest.test_low_context_continues_without_handover` (py/tests/test_steward_ctx.py:76) | | AÇIK |
| `ContextQuestionTest.test_high_context_hands_over` (py/tests/test_steward_ctx.py:86) | | AÇIK |
| `ContextQuestionTest.test_unknown_context_or_disabled_leaves_question` (py/tests/test_steward_ctx.py:95) | | AÇIK |
| `ContextQuestionTest.test_over_threshold_single_handover` (py/tests/test_steward_ctx.py:101) | | AÇIK |
| `PausedProjectNoContextHandoverTest.test_paused_over_threshold_sends_no_handover_on_any_tick` (py/tests/test_steward_ctx.py:119) | | AÇIK |
| `PausedProjectNoContextHandoverTest.test_done_project_also_gets_no_threshold_handover` (py/tests/test_steward_ctx.py:127) | | AÇIK |
| `PausedProjectNoContextHandoverTest.test_planned_project_still_hands_over_at_threshold` (py/tests/test_steward_ctx.py:131) | | AÇIK |
| `PausedProjectNoContextHandoverTest.test_context_question_on_paused_project_does_not_start_a_handover` (py/tests/test_steward_ctx.py:136) | | AÇIK |
| `HandoverDeferTest.test_pure_decision` (py/tests/test_steward_ctx.py:158) | | AÇIK |
| `HandoverDeferTest.test_subagent_active_defers_then_hands_over_when_quiet` (py/tests/test_steward_ctx.py:172) | | AÇIK |
| `HandoverDeferTest.test_busy_and_unknown_defer` (py/tests/test_steward_ctx.py:195) | | AÇIK |
| `HandoverDeferTest.test_history_fallback_defers_too` (py/tests/test_steward_ctx.py:206) | | AÇIK |
| `HandoverDeferTest.test_force_by_ratio` (py/tests/test_steward_ctx.py:212) | | AÇIK |
| `HandoverDeferTest.test_force_by_time` (py/tests/test_steward_ctx.py:222) | | AÇIK |
| `HandoverDeferTest.test_defer_disabled_keeps_old_behaviour` (py/tests/test_steward_ctx.py:234) | | AÇIK |
| `HandoverDeferTest.test_below_threshold_drops_deferral` (py/tests/test_steward_ctx.py:240) | | AÇIK |
| `HandoverDeferTest.test_brain_same_rule` (py/tests/test_steward_ctx.py:246) | | AÇIK |
| `HandoverDeferTest.test_no_second_action_while_deferred` (py/tests/test_steward_ctx.py:257) | | AÇIK |
| `HandoverDeferTest.test_context_question_path_defers` (py/tests/test_steward_ctx.py:267) | | AÇIK |
| `HandoverDeferTest.test_engine_logs_deferral` (py/tests/test_steward_ctx.py:282) | | AÇIK |
| `HttpTest.test_idea_export_project_todo_hides_idea_and_keeps_record` (py/tests/test_steward_http.py:99) | | AÇIK |
| `HttpTest.test_idea_export_all_tbd_and_idempotent` (py/tests/test_steward_http.py:113) | | AÇIK |
| `HttpTest.test_idea_export_appends_under_existing_heading_and_validates` (py/tests/test_steward_http.py:123) | | AÇIK |
| `HttpTest.test_running_names_resolve_digit_in_project_name` (py/tests/test_steward_http.py:143) | | AÇIK |
| `HttpTest.test_project_ask_answer_idea_note` (py/tests/test_steward_http.py:156) | | AÇIK |
| `HttpTest.test_ask_with_options_notifies_with_link_once` (py/tests/test_steward_http.py:177) | | AÇIK |
| `HttpTest.test_question_page_auth_and_answer_flow` (py/tests/test_steward_http.py:201) | | AÇIK |
| `HttpTest.test_register_creates_folder_goal_and_roster` (py/tests/test_steward_http.py:229) | | AÇIK |
| `HttpTest.test_tick_applies_actions_with_mocked_views` (py/tests/test_steward_http.py:252) | | AÇIK |
| `HttpTest.test_refresh_card_writes_summary_and_logs` (py/tests/test_steward_http.py:290) | | AÇIK |
| `HttpTest.test_refresh_card_failure_keeps_old_card_or_writes_raw` (py/tests/test_steward_http.py:303) | | AÇIK |
| `HttpTest.test_refresh_due_cards_rules` (py/tests/test_steward_http.py:326) | | AÇIK |
| `HttpTest.test_tick_runs_card_step_unless_disabled` (py/tests/test_steward_http.py:349) | | AÇIK |
| `HttpTest.test_respawn_marks_card_stale` (py/tests/test_steward_http.py:365) | | AÇIK |
| `HttpTest.test_cards_in_context_projects_and_api` (py/tests/test_steward_http.py:378) | | AÇIK |
| `HttpTest.test_observe_tick_records_would_and_touches_nothing` (py/tests/test_steward_http.py:421) | | AÇIK |
| `HttpTest.test_observe_still_runs_questions_ideas_and_phase_changes` (py/tests/test_steward_http.py:443) | | AÇIK |
| `HttpTest.test_act_mode_applies_and_logs_actions` (py/tests/test_steward_http.py:461) | | AÇIK |
| `HttpTest.test_brain_calls_are_dry_in_observe_but_cli_calls_apply` (py/tests/test_steward_http.py:470) | | AÇIK |
| `HttpTest.test_brain_cannot_touch_unregistered_session` (py/tests/test_steward_http.py:502) | | AÇIK |
| `HttpTest.test_brain_may_touch_brain_and_registered_projects` (py/tests/test_steward_http.py:529) | | AÇIK |
| `HttpTest.test_apply_gate_denies_engine_actions_on_unregistered_sessions` (py/tests/test_steward_http.py:545) | | AÇIK |
| `HttpTest.test_daily_summary_runs_once_after_hour_and_notifies` (py/tests/test_steward_http.py:558) | | AÇIK |
| `HttpTest.test_summary_api_and_cli` (py/tests/test_steward_http.py:584) | | AÇIK |
| `HttpTest.test_handover_route_marks_pending` (py/tests/test_steward_http.py:609) | | AÇIK |
| `JobRequestGateTest.test_gate_pure` (py/tests/test_steward_http.py:622) | | AÇIK |
| `JobRequestGateTest.test_brain_bare_devam_rejected_owner_allowed` (py/tests/test_steward_http.py:634) | | AÇIK |
| `JobRequestGateTest.test_brain_red_closes_and_opens_owner_question` (py/tests/test_steward_http.py:642) | | AÇIK |
| `JobRequestGateTest.test_red_feedback_to_project_session_and_no_repeat_owner_question` (py/tests/test_steward_http.py:654) | | AÇIK |
| `JobRequestGateTest.test_job_kinds_list_shapes` (py/tests/test_steward_http.py:678) | | AÇIK |
| `JobRequestGateTest.test_brain_answer_after_submit_ok` (py/tests/test_steward_http.py:686) | | AÇIK |
| `SkipMemoryHttpTest.test_skip_records_signature_from_last_tour` (py/tests/test_steward_http.py:693) | | AÇIK |
| `SkipMemoryHttpTest.test_close_stale_answer_action_marks_delivered` (py/tests/test_steward_http.py:701) | | AÇIK |
| `ActionJournalTest.test_crash_between_state_save_and_apply_replays_once` (py/tests/test_steward_http.py:716) | | AÇIK |
| `ActionJournalTest.test_normal_tick_leaves_no_journal_and_no_duplicates` (py/tests/test_steward_http.py:734) | | AÇIK |
| `ActionJournalTest.test_replay_skips_duplicate_idea` (py/tests/test_steward_http.py:743) | | AÇIK |
| `DryReportTest.test_report_counts_and_window` (py/tests/test_steward_http.py:765) | | AÇIK |
| `DryReportTest.test_ask_due_only_known_kip_after_72h_once` (py/tests/test_steward_http.py:777) | | AÇIK |
| `DryReportTest.test_maybe_dry_ask_opens_one_question_and_not_again` (py/tests/test_steward_http.py:788) | | AÇIK |
| `DryReportTest.test_no_ask_when_kip_already_act` (py/tests/test_steward_http.py:798) | | AÇIK |
| `BrainWakeGateTest.test_brain_directive_capped_per_day_separately_from_due` (py/tests/test_steward_http.py:808) | | AÇIK |
| `BrainWakeGateTest.test_brain_gate_dry_logs_would_and_sends` (py/tests/test_steward_http.py:820) | | AÇIK |
| `WakeGateTest.test_first_send_never_gated_then_repeat_dry_logs_but_sends_act_skips` (py/tests/test_steward_http.py:836) | | AÇIK |
| `WakeGateTest.test_gate_is_skipped_when_the_directive_just_opened_the_session` (py/tests/test_steward_http.py:847) | | AÇIK |
| `WakeGateTest.test_other_text_other_reason_answer_off_and_window` (py/tests/test_steward_http.py:869) | | AÇIK |
| `BigResumeTest.test_oversized_detection` (py/tests/test_steward_http.py:904) | | AÇIK |
| `BigResumeTest.test_small_unknown_other_cli_and_off_keep_resume` (py/tests/test_steward_http.py:908) | | AÇIK |
| `BigResumeTest.test_ensure_running_starts_fresh_for_big_context` (py/tests/test_steward_http.py:919) | | AÇIK |
| `WakeCapPanicTest.test_daily_cap_dry_and_act_and_reset_on_answer` (py/tests/test_steward_http.py:935) | | AÇIK |
| `WakeCapPanicTest.test_panic_flag_forces_observe_and_blocks_brain_directive` (py/tests/test_steward_http.py:952) | | AÇIK |
| `BlockedEscalationTest.test_blocked_waits_four_hours_routine_thirty_minutes` (py/tests/test_steward_http.py:982) | | AÇIK |
| `BlockedEscalationTest.test_owner_only_denial_escalates_routine_immediately` (py/tests/test_steward_http.py:989) | | AÇIK |
| `BlockedEscalationTest.test_owner_only_denial_blocks_brain_directive_until_answered` (py/tests/test_steward_http.py:997) | | AÇIK |
| `BlockedEscalationTest.test_owner_pending_block_pure` (py/tests/test_steward_http.py:1016) | | AÇIK |
| `BlockedEscalationTest.test_protocol_and_guide_derive_from_owner_topics` (py/tests/test_steward_http.py:1023) | | AÇIK |
| `UcliSendTest.test_ucli_text_folded_not_truncated` (py/tests/test_steward_ucli_send.py:31) | | AÇIK |
| `UcliSendTest.test_non_ucli_untouched_and_no_recheck` (py/tests/test_steward_ucli_send.py:41) | | AÇIK |
| `UcliSendTest.test_claude_trust_dialog_blocks_send` (py/tests/test_steward_ucli_send.py:48) | | AÇIK |
| `UcliSendTest.test_text_left_in_box_sends_one_more_enter` (py/tests/test_steward_ucli_send.py:56) | | AÇIK |
| `UcliSendTest.test_still_stuck_logs_error` (py/tests/test_steward_ucli_send.py:66) | | AÇIK |
| `UcliSendTest.test_stuck_event_uses_caller_sid` (py/tests/test_steward_ucli_send.py:74) | | AÇIK |
| `UcliSendTest.test_every_steward_send_call_passes_sid` (py/tests/test_steward_ucli_send.py:82) | | AÇIK |
| `UcliSendTest.test_late_drawn_text_gets_enter` (py/tests/test_steward_ucli_send.py:92) | | AÇIK |
| `UcliSendTest.test_empty_box_no_extra_enter` (py/tests/test_steward_ucli_send.py:103) | | AÇIK |
| `BoxTextTest.test_prefixed_empty_prompt` (py/tests/test_steward_ucli_send.py:118) | | AÇIK |
| `BoxTextTest.test_prefixed_with_text` (py/tests/test_steward_ucli_send.py:121) | | AÇIK |
| `BoxTextTest.test_text_wrapped_over_two_lines` (py/tests/test_steward_ucli_send.py:124) | | AÇIK |
| `BoxTextTest.test_waiting_for_response_is_empty` (py/tests/test_steward_ucli_send.py:128) | | AÇIK |
| `BoxTextTest.test_turn_output_after_prompt_is_empty` (py/tests/test_steward_ucli_send.py:131) | | AÇIK |
| `BoxTextTest.test_last_prompt_line_wins` (py/tests/test_steward_ucli_send.py:134) | | AÇIK |
| `BoxTextTest.test_no_prompt` (py/tests/test_steward_ucli_send.py:137) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_own_conversation_wins_over_a_newer_sibling_stub` (py/tests/test_stopped_session_chat.py:80) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_each_sibling_resolves_to_its_own_file` (py/tests/test_stopped_session_chat.py:86) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_same_title_prefers_the_real_conversation_over_a_newer_stub` (py/tests/test_stopped_session_chat.py:95) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_same_title_picks_the_newest_real_conversation_even_when_it_is_the_smaller_one` (py/tests/test_stopped_session_chat.py:101) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_all_stubs_returns_the_newest_one` (py/tests/test_stopped_session_chat.py:107) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_a_large_file_counts_as_real_without_being_scanned` (py/tests/test_stopped_session_chat.py:112) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_no_title_match_returns_none` (py/tests/test_stopped_session_chat.py:119) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_title_is_an_exact_match_not_a_prefix` (py/tests/test_stopped_session_chat.py:123) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_untitled_files_never_match` (py/tests/test_stopped_session_chat.py:127) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_missing_project_dir_and_empty_name_return_none` (py/tests/test_stopped_session_chat.py:131) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_file_recording_a_different_cwd_is_ignored` (py/tests/test_stopped_session_chat.py:136) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_finds_a_file_older_than_the_resume_scan_limit` (py/tests/test_stopped_session_chat.py:141) | | AÇIK |
| `ClaudeSidForStoppedSessionTests.test_unchanged_files_are_not_reread_but_changed_ones_are` (py/tests/test_stopped_session_chat.py:149) | | AÇIK |
| `TermChatWiringTests.test_stopped_session_shows_its_own_full_history_not_the_newest_stub` (py/tests/test_stopped_session_chat.py:177) | | AÇIK |
| `TermChatWiringTests.test_stopped_session_last_exchange_is_its_own` (py/tests/test_stopped_session_chat.py:182) | | AÇIK |
| `TermChatWiringTests.test_incremental_since_still_works_on_the_resolved_conversation` (py/tests/test_stopped_session_chat.py:186) | | AÇIK |
| `TermChatWiringTests.test_unmatched_stopped_session_keeps_the_old_newest_in_cwd_behavior` (py/tests/test_stopped_session_chat.py:192) | | AÇIK |
| `TermChatWiringTests.test_live_session_never_consults_the_name_lookup` (py/tests/test_stopped_session_chat.py:200) | | AÇIK |
| `TermChatWiringTests.test_live_session_without_sid_is_left_alone_too` (py/tests/test_stopped_session_chat.py:207) | | AÇIK |
| `TermChatWiringTests.test_unsupported_cli_still_reports_supported_false` (py/tests/test_stopped_session_chat.py:214) | | AÇIK |
| `OtherProvidersTests.test_default_providers_do_not_guess` (py/tests/test_stopped_session_chat.py:220) | | AÇIK |
| `OtherProvidersTests.test_agy_uses_the_learned_name_to_sid_map_when_the_db_exists` (py/tests/test_stopped_session_chat.py:224) | | AÇIK |
| `OtherProvidersTests.test_ucli_sid_is_the_session_name` (py/tests/test_stopped_session_chat.py:237) | | AÇIK |
| `UcliChatTests.test_schema_header_row_is_skipped` (py/tests/test_stopped_session_chat.py:258) | | AÇIK |
| `UcliChatTests.test_header_only_file_means_no_messages_yet_not_unsupported` (py/tests/test_stopped_session_chat.py:263) | | AÇIK |
| `UcliChatTests.test_old_files_without_a_header_still_parse` (py/tests/test_stopped_session_chat.py:267) | | AÇIK |
| `UcliChatTests.test_corrupt_files_are_still_reported_as_unreadable` (py/tests/test_stopped_session_chat.py:271) | | AÇIK |
| `UcliChatTests.test_missing_file_is_an_empty_history` (py/tests/test_stopped_session_chat.py:277) | | AÇIK |
| `UcliChatTests.test_stopped_ucli_instance_chat_is_served_through_term_chat` (py/tests/test_stopped_session_chat.py:280) | | AÇIK |
| `RecoverStuckTest.test_uses_parent_aware_kill` (py/tests/test_stuck_kills_parent.py:13) | | AÇIK |
| `RecoverStuckTest.test_unknown_permission_uses_provider_default` (py/tests/test_stuck_kills_parent.py:28) | | AÇIK |
| `RecoverStuckTest.test_dry_run_kills_nothing` (py/tests/test_stuck_kills_parent.py:40) | | AÇIK |
| `RecoverStuckTest.test_recovery_uses_live_model_and_effort_not_spawn_argv` (py/tests/test_stuck_kills_parent.py:46) | | AÇIK |
| `TokenTests.test_concurrent_issue_keeps_file_and_digest_consistent` (py/tests/test_ucli_agents.py:29) | | AÇIK |
| `TokenTests.test_issue_writes_0600_file_and_only_hash_in_registry` (py/tests/test_ucli_agents.py:48) | | AÇIK |
| `TokenTests.test_reissue_invalidates_old_token_and_revoke_clears` (py/tests/test_ucli_agents.py:56) | | AÇIK |
| `TokenTests.test_children_get_no_token_and_garbage_rejected` (py/tests/test_ucli_agents.py:65) | | AÇIK |
| `TokenTests.test_revoke_unsafe_name_does_not_touch_files` (py/tests/test_ucli_agents.py:71) | | AÇIK |
| `ReserveTests.test_limit_two_live_and_names_sequential` (py/tests/test_ucli_agents.py:80) | | AÇIK |
| `ReserveTests.test_taken_names_skipped_and_depth_one` (py/tests/test_ucli_agents.py:91) | | AÇIK |
| `ReserveTests.test_fold_text` (py/tests/test_ucli_agents.py:97) | | AÇIK |
| `SettingsTests.test_defaults` (py/tests/test_ucli_agents.py:108) | | AÇIK |
| `SettingsTests.test_off_and_cost` (py/tests/test_ucli_agents.py:113) | | AÇIK |
| `ProviderSetupTests.test_no_port_or_child_or_off_gives_nothing` (py/tests/test_ucli_agents.py:136) | | AÇIK |
| `ProviderSetupTests.test_unsupported_binary_gives_nothing` (py/tests/test_ucli_agents.py:145) | | AÇIK |
| `ProviderSetupTests.test_enabled_returns_flag_and_env_without_token_value` (py/tests/test_ucli_agents.py:151) | | AÇIK |
| `ProviderSetupTests.test_build_inner_command_keeps_token_out_of_argv` (py/tests/test_ucli_agents.py:161) | | AÇIK |
| `ApprovalExecTest.test_suspended_registered` (py/tests/test_ucli_approval_exec.py:34) | | AÇIK |
| `ApprovalExecTest.test_75_without_suspended_line_is_error` (py/tests/test_ucli_approval_exec.py:45) | | AÇIK |
| `ApprovalExecTest.test_bad_run_key` (py/tests/test_ucli_approval_exec.py:49) | | AÇIK |
| `ApprovalExecTest.test_opts_validation` (py/tests/test_ucli_approval_exec.py:53) | | AÇIK |
| `ResumeTest.test_resume_done_and_argv_from_record` (py/tests/test_ucli_approval_exec.py:71) | | AÇIK |
| `ResumeTest.test_resume_chain_and_double_resume` (py/tests/test_ucli_approval_exec.py:83) | | AÇIK |
| `ResumeTest.test_resume_error_recorded` (py/tests/test_ucli_approval_exec.py:93) | | AÇIK |
| `ResumeTest.test_list_runs_owner_filter_hides_argv` (py/tests/test_ucli_approval_exec.py:100) | | AÇIK |
| `ResumeTest.test_recover_resuming` (py/tests/test_ucli_approval_exec.py:106) | | AÇIK |
| `ResumeTest.test_authz_resource_and_action` (py/tests/test_ucli_approval_exec.py:114) | | AÇIK |
| `AskDirTest.test_opts_default_off_and_ambiguous` (py/tests/test_ucli_ask_dir.py:27) | | AÇIK |
| `AskDirTest.test_argv_has_private_dir_outside_workspace` (py/tests/test_ucli_ask_dir.py:33) | | AÇIK |
| `AskDirTest.test_unsupported_binary_or_no_name_is_error` (py/tests/test_ucli_ask_dir.py:40) | | AÇIK |
| `AskDirTest.test_pending_and_answer_roundtrip_and_stale_id` (py/tests/test_ucli_ask_dir.py:46) | | AÇIK |
| `AskDirTest.test_bad_names_rejected` (py/tests/test_ucli_ask_dir.py:58) | | AÇIK |
| `AskDirTest.test_broken_question_file_is_none` (py/tests/test_ucli_ask_dir.py:63) | | AÇIK |
| `ValidateMaxCostTests.test_valid_values` (py/tests/test_ucli_brain_mcp.py:53) | | AÇIK |
| `ValidateMaxCostTests.test_zero_or_empty_drops_the_key` (py/tests/test_ucli_brain_mcp.py:59) | | AÇIK |
| `ValidateMaxCostTests.test_invalid_values_rejected` (py/tests/test_ucli_brain_mcp.py:63) | | AÇIK |
| `MaxCostArgsTests.test_priced_model_gets_the_flag_once` (py/tests/test_ucli_brain_mcp.py:89) | | AÇIK |
| `MaxCostArgsTests.test_unpriced_model_is_skipped_and_logged` (py/tests/test_ucli_brain_mcp.py:95) | | AÇIK |
| `MaxCostArgsTests.test_binary_without_flag_is_skipped` (py/tests/test_ucli_brain_mcp.py:100) | | AÇIK |
| `McpRegisterTests.test_server_name_follows_ucli_rule` (py/tests/test_ucli_brain_mcp.py:113) | | AÇIK |
| `McpRegisterTests.test_add_argv_shape` (py/tests/test_ucli_brain_mcp.py:118) | | AÇIK |
| `McpRegisterTests.test_launch_args_register_then_with_mcp` (py/tests/test_ucli_brain_mcp.py:124) | | AÇIK |
| `McpRegisterTests.test_failed_add_means_no_with_mcp` (py/tests/test_ucli_brain_mcp.py:144) | | AÇIK |
| `McpRegisterTests.test_nothing_runs_without_tools_workspace_or_flag` (py/tests/test_ucli_brain_mcp.py:152) | | AÇIK |
| `McpRegisterTests.test_symlinked_state_dir_is_refused` (py/tests/test_ucli_brain_mcp.py:165) | | AÇIK |
| `McpRegisterTests.test_steward_spec_allowlists_exactly_the_steward_tools` (py/tests/test_ucli_brain_mcp.py:176) | | AÇIK |
| `BuildWithMcpTests.test_only_with_mcp_is_taken_from_extra_args` (py/tests/test_ucli_brain_mcp.py:204) | | AÇIK |
| `BuildWithMcpTests.test_claude_service_with_cost_cap_and_mcp` (py/tests/test_ucli_brain_mcp.py:210) | | AÇIK |
| `SpawnCwdWiringTests.test_cwd_only_for_providers_that_ask` (py/tests/test_ucli_brain_mcp.py:245) | | AÇIK |
| `SpawnCwdWiringTests.test_dry_run_preview_shows_env_and_command_not_priority_prefix` (py/tests/test_ucli_brain_mcp.py:265) | | AÇIK |
| `SpawnCwdWiringTests.test_dry_run_preview_masks_secret_env_values` (py/tests/test_ucli_brain_mcp.py:271) | | AÇIK |
| `SpawnCwdWiringTests.test_dry_run_preview_caps_very_long_command` (py/tests/test_ucli_brain_mcp.py:277) | | AÇIK |
| `BrainUcliTests.test_default_claude_brain_passes_no_cli_opts` (py/tests/test_ucli_brain_mcp.py:284) | | AÇIK |
| `BrainUcliTests.test_ucli_brain_uses_claude_service_and_cost_cap` (py/tests/test_ucli_brain_mcp.py:291) | | AÇIK |
| `BrainUcliTests.test_settings_override_service_model_and_cap` (py/tests/test_ucli_brain_mcp.py:303) | | AÇIK |
| `BrainUcliTests.test_defaults` (py/tests/test_ucli_brain_mcp.py:312) | | AÇIK |
| `BrainUcliTests.test_unknown_service_refuses_without_spawn` (py/tests/test_ucli_brain_mcp.py:319) | | AÇIK |
| `BrainUcliTests.test_spawn_refusal_is_reported_not_raised` (py/tests/test_ucli_brain_mcp.py:326) | | AÇIK |
| `BrainUcliTests.test_claude_brain_value_error_still_raises` (py/tests/test_ucli_brain_mcp.py:332) | | AÇIK |
| `BroadGlobTests.test_broad_rejected_without_accept` (py/tests/test_ucli_broad_glob_and_instr_check.py:19) | | AÇIK |
| `BroadGlobTests.test_broad_accepted_with_accept` (py/tests/test_ucli_broad_glob_and_instr_check.py:26) | | AÇIK |
| `BroadGlobTests.test_narrow_glob_has_no_accept_flag` (py/tests/test_ucli_broad_glob_and_instr_check.py:33) | | AÇIK |
| `BroadGlobTests.test_always_rejected_even_when_accepted` (py/tests/test_ucli_broad_glob_and_instr_check.py:38) | | AÇIK |
| `BroadGlobTests.test_forbidden_cmds_never_open` (py/tests/test_ucli_broad_glob_and_instr_check.py:42) | | AÇIK |
| `BroadGlobTests.test_grant_logged_in_apply` (py/tests/test_ucli_broad_glob_and_instr_check.py:46) | | AÇIK |
| `InstructionsCheckTests.test_sizes` (py/tests/test_ucli_broad_glob_and_instr_check.py:62) | | AÇIK |
| `InstructionsCheckTests.test_exact_limit_not_over` (py/tests/test_ucli_broad_glob_and_instr_check.py:71) | | AÇIK |
| `InstructionsCheckTests.test_no_files_and_bad_cwd` (py/tests/test_ucli_broad_glob_and_instr_check.py:76) | | AÇIK |
| `InstructionsCheckTests.test_symlink_escape_ignored` (py/tests/test_ucli_broad_glob_and_instr_check.py:82) | | AÇIK |
| `InstructionsCheckTests.test_no_content_returned` (py/tests/test_ucli_broad_glob_and_instr_check.py:88) | | AÇIK |
| `CapabilityFlagsTest.test_default_off` (py/tests/test_ucli_capability_flags.py:27) | | AÇIK |
| `CapabilityFlagsTest.test_image_scholar_independent_of_exec` (py/tests/test_ucli_capability_flags.py:36) | | AÇIK |
| `CapabilityFlagsTest.test_false_values_dropped` (py/tests/test_ucli_capability_flags.py:43) | | AÇIK |
| `CapabilityFlagsTest.test_invalid_value_is_error` (py/tests/test_ucli_capability_flags.py:48) | | AÇIK |
| `CapabilityFlagsTest.test_net_and_unbounded_exec_own_not_offered` (py/tests/test_ucli_capability_flags.py:54) | | AÇIK |
| `CapabilityFlagsTest.test_ask_edit_needs_write` (py/tests/test_ucli_capability_flags.py:62) | | AÇIK |
| `CapabilityFlagsTest.test_exec_argv` (py/tests/test_ucli_capability_flags.py:69) | | AÇIK |
| `CapabilityFlagsTest.test_unsupported_binary_refuses` (py/tests/test_ucli_capability_flags.py:76) | | AÇIK |
| `CapabilityFlagsTest.test_unsupported_but_off_no_error` (py/tests/test_ucli_capability_flags.py:84) | | AÇIK |
| `AskEditWithoutExecTest.test_ask_edit_added_only_with_allow_edit` (py/tests/test_ucli_capability_flags.py:96) | | AÇIK |
| `CheckpointFlagTest.test_default_off` (py/tests/test_ucli_checkpoint_flag.py:21) | | AÇIK |
| `CheckpointFlagTest.test_false_values_dropped` (py/tests/test_ucli_checkpoint_flag.py:27) | | AÇIK |
| `CheckpointFlagTest.test_true_accepted` (py/tests/test_ucli_checkpoint_flag.py:33) | | AÇIK |
| `CheckpointFlagTest.test_ambiguous_is_error` (py/tests/test_ucli_checkpoint_flag.py:38) | | AÇIK |
| `CheckpointFlagTest.test_argv_added_once` (py/tests/test_ucli_checkpoint_flag.py:42) | | AÇIK |
| `CheckpointFlagTest.test_unsupported_binary_skipped_not_rejected` (py/tests/test_ucli_checkpoint_flag.py:46) | | AÇIK |
| `Validate.test_off_by_default_and_dropped` (py/tests/test_ucli_checks_opts.py:19) | | AÇIK |
| `Validate.test_restricted_ok_max_defaults_to_mode` (py/tests/test_ucli_checks_opts.py:24) | | AÇIK |
| `Validate.test_errors` (py/tests/test_ucli_checks_opts.py:29) | | AÇIK |
| `Validate.test_full_needs_accept_risk` (py/tests/test_ucli_checks_opts.py:33) | | AÇIK |
| `Registry.test_missing_loose_mode_and_shape` (py/tests/test_ucli_checks_opts.py:55) | | AÇIK |
| `Registry.test_symlink_rejected` (py/tests/test_ucli_checks_opts.py:66) | | AÇIK |
| `Apply.test_flags_added` (py/tests/test_ucli_checks_opts.py:90) | | AÇIK |
| `Apply.test_full_adds_accept_risk` (py/tests/test_ucli_checks_opts.py:97) | | AÇIK |
| `Apply.test_full_refused_when_binary_only_knows_restricted` (py/tests/test_ucli_checks_opts.py:101) | | AÇIK |
| `Apply.test_unsupported_binary_refused` (py/tests/test_ucli_checks_opts.py:111) | | AÇIK |
| `Apply.test_needs_state_dir_and_registry` (py/tests/test_ucli_checks_opts.py:115) | | AÇIK |
| `RefusalTests.test_cap_refusal_has_code_and_amounts` (py/tests/test_ucli_cost_cap_refusal.py:13) | | AÇIK |
| `RefusalTests.test_plain_value_error_has_no_code` (py/tests/test_ucli_cost_cap_refusal.py:18) | | AÇIK |
| `ProviderRaisesTests.test_claude_service_flags_raises_over_cap` (py/tests/test_ucli_cost_cap_refusal.py:25) | | AÇIK |
| `DefaultPermissionMode.test_ucli_panel_default_is_allow_edit_and_listed` (py/tests/test_ucli_default_permission_mode.py:12) | | AÇIK |
| `DefaultPermissionMode.test_ucli_server_internal_default_stays_read_only` (py/tests/test_ucli_default_permission_mode.py:17) | | AÇIK |
| `DefaultPermissionMode.test_other_providers_keep_auto` (py/tests/test_ucli_default_permission_mode.py:21) | | AÇIK |
| `ReasoningModeTests.test_unset_empty_and_unknown_values_mean_auto` (py/tests/test_ucli_effort.py:105) | | AÇIK |
| `ReasoningModeTests.test_off_words_switch_it_off` (py/tests/test_ucli_effort.py:111) | | AÇIK |
| `ReasoningModeTests.test_a_named_level_forces_that_level_case_insensitively` (py/tests/test_ucli_effort.py:116) | | AÇIK |
| `ReasoningModeTests.test_a_non_dict_ucli_limits_is_tolerated` (py/tests/test_ucli_effort.py:121) | | AÇIK |
| `ReasoningModeTests.test_it_does_not_leak_into_the_numeric_overrides` (py/tests/test_ucli_effort.py:125) | | AÇIK |
| `CatalogTests.test_only_chat_models_are_listed_and_their_capabilities_kept` (py/tests/test_ucli_effort.py:147) | | AÇIK |
| `CatalogTests.test_a_failed_or_empty_fetch_keeps_the_previous_map` (py/tests/test_ucli_effort.py:155) | | AÇIK |
| `CatalogTests.test_without_a_key_nothing_is_fetched` (py/tests/test_ucli_effort.py:164) | | AÇIK |
| `CatalogTests.test_model_choices_and_the_effort_gate_share_one_fetch` (py/tests/test_ucli_effort.py:170) | | AÇIK |
| `ReasoningEffortForTests.test_a_model_that_declares_support_gets_the_level` (py/tests/test_ucli_effort.py:186) | | AÇIK |
| `ReasoningEffortForTests.test_gemma_which_rejects_the_field_gets_nothing` (py/tests/test_ucli_effort.py:190) | | AÇIK |
| `ReasoningEffortForTests.test_an_unknown_model_or_an_empty_catalog_gets_nothing` (py/tests/test_ucli_effort.py:195) | | AÇIK |
| `ReasoningEffortForTests.test_a_malformed_capabilities_entry_is_tolerated` (py/tests/test_ucli_effort.py:200) | | AÇIK |
| `ReasoningEffortForTests.test_an_allowed_values_list_restricts_the_level_unless_aliased` (py/tests/test_ucli_effort.py:208) | | AÇIK |
| `EffortArgsTests.test_a_capable_model_and_a_new_binary_get_the_session_preset` (py/tests/test_ucli_effort.py:219) | | AÇIK |
| `EffortArgsTests.test_off_is_silent_and_sends_nothing` (py/tests/test_ucli_effort.py:225) | | AÇIK |
| `EffortArgsTests.test_a_named_level_overrides_the_preset_but_not_the_model_gate` (py/tests/test_ucli_effort.py:231) | | AÇIK |
| `EffortArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` (py/tests/test_ucli_effort.py:237) | | AÇIK |
| `EffortArgsTests.test_a_model_that_rejects_the_field_is_skipped_and_logged` (py/tests/test_ucli_effort.py:243) | | AÇIK |
| `EffortArgsTests.test_no_model_and_a_missing_binary_give_nothing_instead_of_raising` (py/tests/test_ucli_effort.py:249) | | AÇIK |
| `BuildInnerCommandTests.test_the_preset_name_rides_along_as_the_last_flag` (py/tests/test_ucli_effort.py:280) | | AÇIK |
| `BuildInnerCommandTests.test_an_unknown_or_empty_effort_falls_back_to_medium_for_the_flag_too` (py/tests/test_ucli_effort.py:284) | | AÇIK |
| `BuildInnerCommandTests.test_gemma_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:290) | | AÇIK |
| `BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:294) | | AÇIK |
| `BuildInnerCommandTests.test_off_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_effort.py:298) | | AÇIK |
| `BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` (py/tests/test_ucli_effort.py:302) | | AÇIK |
| `BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` (py/tests/test_ucli_effort.py:308) | | AÇIK |
| `BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` (py/tests/test_ucli_effort.py:318) | | AÇIK |
| `RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` (py/tests/test_ucli_effort.py:325) | | AÇIK |
| `UcliEndpointTest.test_default_is_evren` (py/tests/test_ucli_endpoint.py:23) | | AÇIK |
| `UcliEndpointTest.test_custom_valid_endpoint_wins_and_trailing_slash_dropped` (py/tests/test_ucli_endpoint.py:27) | | AÇIK |
| `UcliEndpointTest.test_invalid_endpoint_falls_back_and_empty_clears` (py/tests/test_ucli_endpoint.py:31) | | AÇIK |
| `UcliEndpointTest.test_model_list_fetch_uses_configured_endpoint` (py/tests/test_ucli_endpoint.py:40) | | AÇIK |
| `EvrenNoDefaultCapTest.test_evren_has_no_default_cap` (py/tests/test_ucli_evren_no_default_cap.py:18) | | AÇIK |
| `EvrenNoDefaultCapTest.test_explicit_cap_on_evren_still_passes` (py/tests/test_ucli_evren_no_default_cap.py:22) | | AÇIK |
| `ExecToolchainTests.test_only_rust_is_accepted` (py/tests/test_ucli_exec_toolchain.py:17) | | AÇIK |
| `ExecToolchainTests.test_missing_toolchain_is_an_error_not_a_silent_skip` (py/tests/test_ucli_exec_toolchain.py:22) | | AÇIK |
| `ExecToolchainTests.test_flags_use_real_binaries_and_only_allowed_env` (py/tests/test_ucli_exec_toolchain.py:28) | | AÇIK |
| `ExecToolchainTests.test_no_toolchain_means_old_flags_unchanged` (py/tests/test_ucli_exec_toolchain.py:46) | | AÇIK |
| `ExecToolchainTests.test_path_in_exec_cmds_is_still_rejected` (py/tests/test_ucli_exec_toolchain.py:53) | | AÇIK |
| `FailedTurnsTests.test_no_directory_or_no_record_is_none_not_zero` (py/tests/test_ucli_failed_turns.py:28) | | AÇIK |
| `FailedTurnsTests.test_counts_this_session_only_and_reports_the_newest_error` (py/tests/test_ucli_failed_turns.py:33) | | AÇIK |
| `FailedTurnsTests.test_a_broken_or_errorless_record_still_counts` (py/tests/test_ucli_failed_turns.py:42) | | AÇIK |
| `FailedTurnsTests.test_dict_error_uses_its_message` (py/tests/test_ucli_failed_turns.py:46) | | AÇIK |
| `FailedTurnsTests.test_no_sid_is_none` (py/tests/test_ucli_failed_turns.py:50) | | AÇIK |
| `FailedTurnsTests.test_web_wrapper_never_raises` (py/tests/test_ucli_failed_turns.py:53) | | AÇIK |
| `FailedTurnsTests.test_other_cli_has_no_failed_turns` (py/tests/test_ucli_failed_turns.py:58) | | AÇIK |
| `ForbiddenCmds.test_interpreters_rejected_by_name` (py/tests/test_ucli_forbidden_cmds.py:10) | | AÇIK |
| `ForbiddenCmds.test_is_forbidden_cmd` (py/tests/test_ucli_forbidden_cmds.py:16) | | AÇIK |
| `ArchiveTest.test_moves_history_and_status_keeps_others` (py/tests/test_ucli_fresh_handover.py:31) | | AÇIK |
| `ArchiveTest.test_second_archive_does_not_overwrite` (py/tests/test_ucli_fresh_handover.py:43) | | AÇIK |
| `ArchiveTest.test_nothing_to_move_and_bad_names` (py/tests/test_ucli_fresh_handover.py:50) | | AÇIK |
| `StartFreshTest.test_fresh_ucli_archives` (py/tests/test_ucli_fresh_handover.py:72) | | AÇIK |
| `StartFreshTest.test_not_fresh_or_not_ucli_or_running_does_not` (py/tests/test_ucli_fresh_handover.py:75) | | AÇIK |
| `HandoverGateTest.test_ucli_handover_sends_message` (py/tests/test_ucli_fresh_handover.py:82) | | AÇIK |
| `ValidateTests.test_default_off` (py/tests/test_ucli_git_flags.py:21) | | AÇIK |
| `ValidateTests.test_on_independent_of_each_other_and_exec` (py/tests/test_ucli_git_flags.py:26) | | AÇIK |
| `ValidateTests.test_garbage_is_error` (py/tests/test_ucli_git_flags.py:32) | | AÇIK |
| `ArgvTests.test_no_flags_by_default` (py/tests/test_ucli_git_flags.py:39) | | AÇIK |
| `ArgvTests.test_only_requested_flag` (py/tests/test_ucli_git_flags.py:44) | | AÇIK |
| `ArgvTests.test_both_no_duplicates` (py/tests/test_ucli_git_flags.py:52) | | AÇIK |
| `ArgvTests.test_unsupported_binary_refuses` (py/tests/test_ucli_git_flags.py:57) | | AÇIK |
| `ArgvTests.test_unsupported_irrelevant_when_off` (py/tests/test_ucli_git_flags.py:61) | | AÇIK |
| `InstructionsFlagsTest.test_default_off` (py/tests/test_ucli_instructions_flags.py:21) | | AÇIK |
| `InstructionsFlagsTest.test_valid` (py/tests/test_ucli_instructions_flags.py:30) | | AÇIK |
| `InstructionsFlagsTest.test_zero_and_empty_dropped` (py/tests/test_ucli_instructions_flags.py:36) | | AÇIK |
| `InstructionsFlagsTest.test_invalid` (py/tests/test_ucli_instructions_flags.py:42) | | AÇIK |
| `InstructionsFlagsTest.test_argv` (py/tests/test_ucli_instructions_flags.py:49) | | AÇIK |
| `InstructionsFlagsTest.test_unsupported_binary_skips` (py/tests/test_ucli_instructions_flags.py:54) | | AÇIK |
| `InteractiveArgsTest.test_supported_adds_flag` (py/tests/test_ucli_interactive_flag.py:12) | | AÇIK |
| `InteractiveArgsTest.test_unsupported_skips_and_logs` (py/tests/test_ucli_interactive_flag.py:16) | | AÇIK |
| `UcliKeyPathTest.test_default_and_service` (py/tests/test_ucli_key_path.py:14) | | AÇIK |
| `UcliKeyPathTest.test_callers_share_helper` (py/tests/test_ucli_key_path.py:19) | | AÇIK |
| `LastExchangePairingTest.test_pending_user_turn_has_empty_assistant` (py/tests/test_ucli_last_exchange_pairing.py:17) | | AÇIK |
| `LastExchangePairingTest.test_answered_turn_pairs_normally` (py/tests/test_ucli_last_exchange_pairing.py:22) | | AÇIK |
| `LastExchangePairingTest.test_assistant_only_and_empty` (py/tests/test_ucli_last_exchange_pairing.py:26) | | AÇIK |
| `ValidateTests.test_empty_and_zero_drop_key` (py/tests/test_ucli_limit_flags.py:30) | | AÇIK |
| `ValidateTests.test_ints_accepted` (py/tests/test_ucli_limit_flags.py:36) | | AÇIK |
| `ValidateTests.test_ints_invalid_are_errors` (py/tests/test_ucli_limit_flags.py:41) | | AÇIK |
| `ValidateTests.test_bools` (py/tests/test_ucli_limit_flags.py:48) | | AÇIK |
| `ValidateTests.test_price_two_and_four` (py/tests/test_ucli_limit_flags.py:55) | | AÇIK |
| `ValidateTests.test_price_invalid` (py/tests/test_ucli_limit_flags.py:59) | | AÇIK |
| `ArgvTests.test_nothing_by_default` (py/tests/test_ucli_limit_flags.py:67) | | AÇIK |
| `ArgvTests.test_int_flags_with_values` (py/tests/test_ucli_limit_flags.py:74) | | AÇIK |
| `ArgvTests.test_price_and_bools` (py/tests/test_ucli_limit_flags.py:80) | | AÇIK |
| `ArgvTests.test_unsupported_flag_is_skipped_not_fatal` (py/tests/test_ucli_limit_flags.py:86) | | AÇIK |
| `ArgvTests.test_only_supported_ones_added` (py/tests/test_ucli_limit_flags.py:90) | | AÇIK |
| `LiveContext.test_bytes_over_four` (py/tests/test_ucli_live_context.py:16) | | AÇIK |
| `LiveContext.test_zero_is_zero` (py/tests/test_ucli_live_context.py:19) | | AÇIK |
| `LiveContext.test_unknown_cases_are_none` (py/tests/test_ucli_live_context.py:22) | | AÇIK |
| `LiveContext.test_reader_error_is_none` (py/tests/test_ucli_live_context.py:30) | | AÇIK |
| `MaxSessionUsd.test_valid_kept_as_float` (py/tests/test_ucli_max_session_usd.py:10) | | AÇIK |
| `MaxSessionUsd.test_zero_and_empty_dropped` (py/tests/test_ucli_max_session_usd.py:14) | | AÇIK |
| `MaxSessionUsd.test_invalid_rejected` (py/tests/test_ucli_max_session_usd.py:18) | | AÇIK |
| `MaxSessionUsd.test_independent_of_per_turn_cap` (py/tests/test_ucli_max_session_usd.py:24) | | AÇIK |
| `DefaultCap.test_default_is_8_and_configurable` (py/tests/test_ucli_max_session_usd.py:35) | | AÇIK |
| `DefaultCap.test_provider_uses_default_when_record_has_none` (py/tests/test_ucli_max_session_usd.py:43) | | AÇIK |
| `MetricsFileArgs.test_on_and_supported` (py/tests/test_ucli_metrics_file_arg.py:22) | | AÇIK |
| `MetricsFileArgs.test_off_unsupported_nameless` (py/tests/test_ucli_metrics_file_arg.py:27) | | AÇIK |
| `MetricsFileArgs.test_name_sanitised` (py/tests/test_ucli_metrics_file_arg.py:32) | | AÇIK |
| `FlattenTest.test_ucli_flattens` (py/tests/test_ucli_multiline_flatten.py:15) | | AÇIK |
| `FlattenTest.test_ucli_single_line_unchanged` (py/tests/test_ucli_multiline_flatten.py:19) | | AÇIK |
| `FlattenTest.test_ucli_trailing_newline` (py/tests/test_ucli_multiline_flatten.py:23) | | AÇIK |
| `FlattenTest.test_ucli_tab_single_line` (py/tests/test_ucli_multiline_flatten.py:26) | | AÇIK |
| `FlattenTest.test_ucli_long_text_not_truncated` (py/tests/test_ucli_multiline_flatten.py:29) | | AÇIK |
| `FlattenTest.test_single_fold_point_in_callers` (py/tests/test_ucli_multiline_flatten.py:37) | | AÇIK |
| `FlattenTest.test_other_providers_untouched` (py/tests/test_ucli_multiline_flatten.py:44) | | AÇIK |
| `LivePhaseTests.test_a_streaming_phase_comes_through` (py/tests/test_ucli_phase.py:36) | | AÇIK |
| `LivePhaseTests.test_the_last_write_time_of_the_file_comes_through_as_last_unix` (py/tests/test_ucli_phase.py:41) | | AÇIK |
| `LivePhaseTests.test_a_missing_or_garbage_last_activity_is_left_out_not_zeroed` (py/tests/test_ucli_phase.py:46) | | AÇIK |
| `LivePhaseTests.test_a_retry_phase_keeps_its_reason` (py/tests/test_ucli_phase.py:54) | | AÇIK |
| `LivePhaseTests.test_no_phase_a_null_phase_or_an_older_binary_mean_none` (py/tests/test_ucli_phase.py:60) | | AÇIK |
| `LivePhaseTests.test_a_phase_without_a_usable_name_is_ignored` (py/tests/test_ucli_phase.py:67) | | AÇIK |
| `LivePhaseTests.test_bad_numbers_are_dropped_never_turned_into_an_invented_zero` (py/tests/test_ucli_phase.py:73) | | AÇIK |
| `LivePhaseTests.test_text_is_trimmed_and_capped` (py/tests/test_ucli_phase.py:79) | | AÇIK |
| `LivePhaseTests.test_a_future_phase_name_passes_through_so_the_badge_does_not_go_silent` (py/tests/test_ucli_phase.py:85) | | AÇIK |
| `LivePhaseTests.test_only_the_known_fields_are_returned` (py/tests/test_ucli_phase.py:89) | | AÇIK |
| `LivePhaseTests.test_no_status_file_no_sid_or_a_broken_file_mean_none` (py/tests/test_ucli_phase.py:93) | | AÇIK |
| `LivePhaseTests.test_every_other_provider_has_no_phase` (py/tests/test_ucli_phase.py:101) | | AÇIK |
| `LivePhaseHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` (py/tests/test_ucli_phase.py:122) | | AÇIK |
| `LivePhaseHelperTests.test_waiting_for_the_response_turns_amber_then_red_on_the_thresholds` (py/tests/test_ucli_phase.py:127) | | AÇIK |
| `LivePhaseHelperTests.test_retries_and_rate_limits_are_always_amber` (py/tests/test_ucli_phase.py:133) | | AÇIK |
| `LivePhaseHelperTests.test_a_model_that_is_thinking_or_writing_is_progress_not_a_warning` (py/tests/test_ucli_phase.py:139) | | AÇIK |
| `LivePhaseHelperTests.test_a_stream_that_goes_quiet_turns_amber_then_red_and_progress_stays_green` (py/tests/test_ucli_phase.py:145) | | AÇIK |
| `LivePhaseHelperTests.test_a_long_running_stream_that_keeps_writing_is_not_a_warning` (py/tests/test_ucli_phase.py:154) | | AÇIK |
| `LivePhaseHelperTests.test_idle_is_reported_but_does_not_decide_the_waiting_colour` (py/tests/test_ucli_phase.py:159) | | AÇIK |
| `LivePhaseHelperTests.test_without_a_last_write_time_a_stream_has_no_idle_and_no_warning` (py/tests/test_ucli_phase.py:163) | | AÇIK |
| `LivePhaseHelperTests.test_the_internal_last_unix_is_not_leaked_to_the_wire` (py/tests/test_ucli_phase.py:167) | | AÇIK |
| `LivePhaseHelperTests.test_the_providers_dict_is_not_mutated` (py/tests/test_ucli_phase.py:171) | | AÇIK |
| `LivePhaseHelperTests.test_a_missing_since_unix_means_no_elapsed_and_no_warning` (py/tests/test_ucli_phase.py:176) | | AÇIK |
| `LivePhaseHelperTests.test_a_since_in_the_future_never_gives_a_negative_elapsed` (py/tests/test_ucli_phase.py:180) | | AÇIK |
| `LivePhaseHelperTests.test_no_phase_means_none` (py/tests/test_ucli_phase.py:184) | | AÇIK |
| `LivePhaseHelperTests.test_a_failing_provider_never_breaks_the_panel` (py/tests/test_ucli_phase.py:188) | | AÇIK |
| `StatusPayloadPhaseTests.test_a_registered_running_ucli_row_carries_its_phase` (py/tests/test_ucli_phase.py:226) | | AÇIK |
| `StatusPayloadPhaseTests.test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait` (py/tests/test_ucli_phase.py:231) | | AÇIK |
| `StatusPayloadPhaseTests.test_a_frozen_stream_row_goes_amber_from_the_file_write_time` (py/tests/test_ucli_phase.py:235) | | AÇIK |
| `StatusPayloadPhaseTests.test_a_stopped_row_and_a_phaseless_provider_have_no_phase` (py/tests/test_ucli_phase.py:242) | | AÇIK |
| `LimitOverridesTests.test_the_timeout_is_a_valid_override_as_a_string_or_a_number` (py/tests/test_ucli_request_timeout.py:62) | | AÇIK |
| `LimitOverridesTests.test_unset_empty_and_invalid_values_fall_back_to_the_default` (py/tests/test_ucli_request_timeout.py:66) | | AÇIK |
| `LimitOverridesTests.test_the_other_overrides_are_unaffected` (py/tests/test_ucli_request_timeout.py:72) | | AÇIK |
| `TimeoutArgsTests.test_a_binary_that_knows_the_flag_gets_the_600_second_default` (py/tests/test_ucli_request_timeout.py:78) | | AÇIK |
| `TimeoutArgsTests.test_the_settings_override_replaces_the_default` (py/tests/test_ucli_request_timeout.py:84) | | AÇIK |
| `TimeoutArgsTests.test_an_old_binary_gets_nothing_and_the_log_says_why` (py/tests/test_ucli_request_timeout.py:88) | | AÇIK |
| `TimeoutArgsTests.test_a_missing_binary_gets_nothing_instead_of_raising` (py/tests/test_ucli_request_timeout.py:94) | | AÇIK |
| `BuildInnerCommandTests.test_the_default_command_ends_with_the_600_second_timeout` (py/tests/test_ucli_request_timeout.py:123) | | AÇIK |
| `BuildInnerCommandTests.test_the_settings_override_reaches_the_command` (py/tests/test_ucli_request_timeout.py:126) | | AÇIK |
| `BuildInnerCommandTests.test_an_old_binary_gets_the_command_byte_identical_to_before` (py/tests/test_ucli_request_timeout.py:132) | | AÇIK |
| `BuildInnerCommandTests.test_the_api_key_wrapper_keeps_the_flag` (py/tests/test_ucli_request_timeout.py:136) | | AÇIK |
| `BuildInnerCommandTests.test_every_effort_preset_still_round_trips_through_the_running_command` (py/tests/test_ucli_request_timeout.py:142) | | AÇIK |
| `BuildInnerCommandTests.test_the_command_is_still_recognised_as_a_ucli_process` (py/tests/test_ucli_request_timeout.py:152) | | AÇIK |
| `RealBinaryTests.test_the_delivered_binary_knows_the_flag_when_it_is_new_enough` (py/tests/test_ucli_request_timeout.py:159) | | AÇIK |
| `OwnCopyLocationTests.test_own_copy_lives_in_the_repo_bin_directory_and_is_named_ucli` (py/tests/test_ucli_resolve_binary.py:32) | | AÇIK |
| `OwnCopyLocationTests.test_a_session_started_from_the_own_copy_is_still_recognised_as_ucli` (py/tests/test_ucli_resolve_binary.py:38) | | AÇIK |
| `ResolveBinaryTests.test_own_copy_beats_path_and_the_sibling_builds` (py/tests/test_ucli_resolve_binary.py:79) | | AÇIK |
| `ResolveBinaryTests.test_path_beats_the_sibling_builds_when_there_is_no_own_copy` (py/tests/test_ucli_resolve_binary.py:85) | | AÇIK |
| `ResolveBinaryTests.test_sibling_release_is_preferred_over_sibling_debug` (py/tests/test_ucli_resolve_binary.py:90) | | AÇIK |
| `ResolveBinaryTests.test_sibling_debug_is_the_fallback_when_there_is_no_sibling_release` (py/tests/test_ucli_resolve_binary.py:94) | | AÇIK |
| `ResolveBinaryTests.test_sibling_release_alone_is_used` (py/tests/test_ucli_resolve_binary.py:98) | | AÇIK |
| `ResolveBinaryTests.test_no_build_raises_a_clear_error_that_names_the_installer` (py/tests/test_ucli_resolve_binary.py:102) | | AÇIK |
| `ResolveBinaryTests.test_overrides_beat_the_own_copy_so_debug_can_be_forced` (py/tests/test_ucli_resolve_binary.py:109) | | AÇIK |
| `ResolveBinaryTests.test_settings_override_beats_env_and_env_beats_the_own_copy` (py/tests/test_ucli_resolve_binary.py:123) | | AÇIK |
| `ScriptModeSettingTests.test_default_and_garbage_mean_off` (py/tests/test_ucli_script.py:42) | | AÇIK |
| `ScriptModeSettingTests.test_read_and_full_in_any_spelling` (py/tests/test_ucli_script.py:47) | | AÇIK |
| `ScriptModeSettingTests.test_default_settings_carry_the_key` (py/tests/test_ucli_script.py:52) | | AÇIK |
| `BuildCommandTests.test_off_leaves_the_command_exactly_as_before` (py/tests/test_ucli_script.py:75) | | AÇIK |
| `BuildCommandTests.test_read_and_full_append_one_equals_form_flag` (py/tests/test_ucli_script.py:79) | | AÇIK |
| `BuildCommandTests.test_old_binary_without_the_flag_is_not_given_it` (py/tests/test_ucli_script.py:84) | | AÇIK |
| `BuildCommandTests.test_allow_create_mode_passes_only_that_flag` (py/tests/test_ucli_script.py:90) | | AÇIK |
| `BuildCommandTests.test_allow_create_on_a_binary_that_lacks_it_opens_read_only` (py/tests/test_ucli_script.py:95) | | AÇIK |
| `BuildCommandTests.test_permission_modes_list_and_round_trip_from_the_running_command` (py/tests/test_ucli_script.py:102) | | AÇIK |
| `SaveScriptSettingTests.test_mode_round_trips_and_an_empty_one_switches_the_layer_off` (py/tests/test_ucli_script.py:122) | | AÇIK |
| `SaveScriptSettingTests.test_saving_the_mode_leaves_the_other_ucli_panels_alone` (py/tests/test_ucli_script.py:131) | | AÇIK |
| `SaveScriptSettingTests.test_a_hand_edited_non_dict_value_degrades_to_off` (py/tests/test_ucli_script.py:139) | | AÇIK |
| `SaveScriptSettingTests.test_the_panel_endpoint_returns_the_field_on_the_wire` (py/tests/test_ucli_script.py:144) | | AÇIK |
| `SearchTokenEnvTest.test_default_absent` (py/tests/test_ucli_search_token_env.py:21) | | AÇIK |
| `SearchTokenEnvTest.test_valid_name` (py/tests/test_ucli_search_token_env.py:27) | | AÇIK |
| `SearchTokenEnvTest.test_empty_means_not_sent` (py/tests/test_ucli_search_token_env.py:32) | | AÇIK |
| `SearchTokenEnvTest.test_invalid_names_error` (py/tests/test_ucli_search_token_env.py:36) | | AÇIK |
| `SearchTokenEnvTest.test_argv_with_search_url` (py/tests/test_ucli_search_token_env.py:42) | | AÇIK |
| `SearchTokenEnvTest.test_skipped_without_search_url` (py/tests/test_ucli_search_token_env.py:47) | | AÇIK |
| `SearchTokenEnvTest.test_unsupported_binary_skips` (py/tests/test_ucli_search_token_env.py:50) | | AÇIK |
| `ServicesTests.test_defaults_when_empty` (py/tests/test_ucli_services_settings.py:18) | | AÇIK |
| `ServicesTests.test_groq_label` (py/tests/test_ucli_services_settings.py:23) | | AÇIK |
| `ServicesTests.test_invalid_dropped_evren_always_present` (py/tests/test_ucli_services_settings.py:27) | | AÇIK |
| `ServicesTests.test_services_map_follows_settings` (py/tests/test_ucli_services_settings.py:39) | | AÇIK |
| `ServicesTests.test_effort_follows_model` (py/tests/test_ucli_services_settings.py:46) | | AÇIK |
| `SettingTests.test_default_off_and_words` (py/tests/test_ucli_show_reasoning.py:24) | | AÇIK |
| `BuildTests.test_flag_added_only_when_enabled_and_supported` (py/tests/test_ucli_show_reasoning.py:43) | | AÇIK |
| `BuildTests.test_old_binary_never_gets_the_flag_and_it_is_logged` (py/tests/test_ucli_show_reasoning.py:47) | | AÇIK |
| `ValidateTests.test_empty_is_ok_and_empty` (py/tests/test_ucli_start_opts.py:29) | | AÇIK |
| `ValidateTests.test_unknown_service_rejected` (py/tests/test_ucli_start_opts.py:33) | | AÇIK |
| `ValidateTests.test_shells_and_wrappers_rejected` (py/tests/test_ucli_start_opts.py:36) | | AÇIK |
| `ValidateTests.test_glob_needs_cmds_and_must_be_narrow` (py/tests/test_ucli_start_opts.py:40) | | AÇIK |
| `ValidateTests.test_timeout_range_and_requires_cmds` (py/tests/test_ucli_start_opts.py:48) | | AÇIK |
| `BuildTests.test_no_opts_is_identical_to_before` (py/tests/test_ucli_start_opts.py:80) | | AÇIK |
| `BuildTests.test_max_history_kib_is_passed_only_when_the_binary_knows_it_and_the_setting_wins` (py/tests/test_ucli_start_opts.py:84) | | AÇIK |
| `BuildTests.test_claude_service_swaps_endpoint_once_and_key_stays_out_of_argv` (py/tests/test_ucli_start_opts.py:98) | | AÇIK |
| `BuildTests.test_claude_service_gets_team_flags_and_is_refused_over_the_daily_cap` (py/tests/test_ucli_start_opts.py:116) | | AÇIK |
| `BuildTests.test_groq_service_uses_groq_endpoint_and_key_env` (py/tests/test_ucli_start_opts.py:145) | | AÇIK |
| `BuildTests.test_service_models_fetches_live_list_with_correct_auth` (py/tests/test_ucli_start_opts.py:153) | | AÇIK |
| `BuildTests.test_claude_service_skips_instructions_auto_when_file_over_16kib` (py/tests/test_ucli_start_opts.py:177) | | AÇIK |
| `BuildTests.test_missing_service_key_refuses_spawn` (py/tests/test_ucli_start_opts.py:202) | | AÇIK |
| `BuildTests.test_evren_service_changes_nothing` (py/tests/test_ucli_start_opts.py:206) | | AÇIK |
| `BuildTests.test_exec_flags_appended_and_gated_by_binary` (py/tests/test_ucli_start_opts.py:209) | | AÇIK |
| `BuildTests.test_exec_bind_ro` (py/tests/test_ucli_start_opts.py:219) | | AÇIK |
| `BuildTests.test_star_expands_on_path_and_write_adds_allow_edit` (py/tests/test_ucli_start_opts.py:227) | | AÇIK |
| `BuildTests.test_patterns_validate` (py/tests/test_ucli_start_opts.py:241) | | AÇIK |
| `BuildTests.test_star_never_opens_forbidden` (py/tests/test_ucli_start_opts.py:249) | | AÇIK |
| `BuildTests.test_write_permission_default_off` (py/tests/test_ucli_start_opts.py:259) | | AÇIK |
| `WiringTests.test_only_ucli_accepts_cli_opts` (py/tests/test_ucli_start_opts.py:267) | | AÇIK |
| `WiringTests.test_spawn_never_passes_cli_opts_to_other_providers` (py/tests/test_ucli_start_opts.py:273) | | AÇIK |
| `WiringTests.test_start_rejects_opts_for_non_ucli_and_invalid_opts` (py/tests/test_ucli_start_opts.py:280) | | AÇIK |
| `WiringTests.test_new_chat_rejects_before_recording_an_instance` (py/tests/test_ucli_start_opts.py:293) | | AÇIK |
| `WiringTests.test_new_chat_lock_timeout_forgets_instance` (py/tests/test_ucli_start_opts.py:328) | | AÇIK |
| `WiringTests.test_new_chat_timeout_after_spawn_keeps_instance` (py/tests/test_ucli_start_opts.py:334) | | AÇIK |
| `WiringTests.test_new_chat_unexpected_error_before_spawn_forgets_instance` (py/tests/test_ucli_start_opts.py:340) | | AÇIK |
| `CostCapTests.test_today_sums_only_today_and_uses_the_task_model` (py/tests/test_ucli_start_opts.py:370) | | AÇIK |
| `CostCapTests.test_cap_zero_means_off_and_cap_blocks_when_reached` (py/tests/test_ucli_start_opts.py:380) | | AÇIK |
| `CostCapTests.test_config_parsing_is_safe` (py/tests/test_ucli_start_opts.py:391) | | AÇIK |
| `CostCapTests.test_credit_total_parsing_is_safe` (py/tests/test_ucli_start_opts.py:403) | | AÇIK |
| `TokioThreadsEnvTests.test_env_overrides_limits_tokio_workers` (py/tests/test_ucli_start_opts.py:414) | | AÇIK |
| `TestSetting.test_default_off_and_words` (py/tests/test_ucli_state_dir.py:42) | | AÇIK |
| `TestChatOnce.test_state_dir_passed_only_when_on_supported_and_session` (py/tests/test_ucli_state_dir.py:67) | | AÇIK |
| `TestPaths.test_dir_is_per_root_and_stable_and_outside_the_repo` (py/tests/test_ucli_state_dir.py:79) | | AÇIK |
| `TestPaths.test_off_reads_only_legacy_until_the_new_dir_exists` (py/tests/test_ucli_state_dir.py:88) | | AÇIK |
| `TestPaths.test_on_prefers_new_then_falls_back_to_legacy_for_files` (py/tests/test_ucli_state_dir.py:95) | | AÇIK |
| `TestSpawnArgv.test_off_by_default_adds_nothing` (py/tests/test_ucli_state_dir.py:118) | | AÇIK |
| `TestSpawnArgv.test_on_adds_flag_for_new_session_only_when_binary_knows_it` (py/tests/test_ucli_state_dir.py:122) | | AÇIK |
| `TestSpawnArgv.test_session_with_legacy_history_keeps_the_legacy_dir` (py/tests/test_ucli_state_dir.py:127) | | AÇIK |
| `TestSpawnArgv.test_session_already_in_new_dir_keeps_it_even_if_setting_turned_off` (py/tests/test_ucli_state_dir.py:133) | | AÇIK |
| `StreamSettingTests.test_the_shipped_default_is_on` (py/tests/test_ucli_stream.py:38) | | AÇIK |
| `StreamSettingTests.test_an_untouched_install_asks_for_the_stream_and_off_still_wins` (py/tests/test_ucli_stream.py:43) | | AÇIK |
| `StreamSettingTests.test_missing_empty_and_garbage_fall_back_to_the_default` (py/tests/test_ucli_stream.py:49) | | AÇIK |
| `StreamSettingTests.test_on_words_enable_in_any_spelling` (py/tests/test_ucli_stream.py:56) | | AÇIK |
| `StreamSettingTests.test_off_words_disable_even_when_the_default_is_on` (py/tests/test_ucli_stream.py:61) | | AÇIK |
| `StreamSettingTests.test_the_stream_key_is_not_mistaken_for_a_numeric_limit` (py/tests/test_ucli_stream.py:67) | | AÇIK |
| `SaveStreamSettingTests.test_it_round_trips_and_an_empty_value_goes_back_to_the_default` (py/tests/test_ucli_stream.py:82) | | AÇIK |
| `SaveStreamSettingTests.test_it_does_not_disturb_the_other_limit_fields` (py/tests/test_ucli_stream.py:90) | | AÇIK |
| `SaveStreamSettingTests.test_a_hand_edited_non_dict_value_degrades_to_the_default` (py/tests/test_ucli_stream.py:98) | | AÇIK |
| `BuildCommandTests.test_off_leaves_the_command_without_the_flag` (py/tests/test_ucli_stream.py:124) | | AÇIK |
| `BuildCommandTests.test_on_adds_exactly_one_bare_flag` (py/tests/test_ucli_stream.py:129) | | AÇIK |
| `BuildCommandTests.test_an_old_binary_without_the_flag_is_not_given_it_and_the_skip_is_logged` (py/tests/test_ucli_stream.py:134) | | AÇIK |
| `LiveUsageTests.test_the_counters_come_through_as_written` (py/tests/test_ucli_usage.py:50) | | AÇIK |
| `LiveUsageTests.test_a_binary_without_usage_means_unknown_not_zero` (py/tests/test_ucli_usage.py:54) | | AÇIK |
| `LiveUsageTests.test_a_usage_that_is_not_an_object_means_unknown` (py/tests/test_ucli_usage.py:58) | | AÇIK |
| `LiveUsageTests.test_no_status_file_no_sid_or_a_broken_file_mean_unknown` (py/tests/test_ucli_usage.py:64) | | AÇIK |
| `LiveUsageTests.test_the_unmetered_fields_of_an_older_binary_count_as_zero` (py/tests/test_ucli_usage.py:72) | | AÇIK |
| `LiveUsageTests.test_garbage_values_become_zero_never_an_invented_number` (py/tests/test_ucli_usage.py:78) | | AÇIK |
| `LiveUsageTests.test_only_the_known_counters_are_returned` (py/tests/test_ucli_usage.py:86) | | AÇIK |
| `LiveUsageTests.test_every_other_provider_has_no_counter` (py/tests/test_ucli_usage.py:92) | | AÇIK |
| `LiveUsageHelperTests.test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid` (py/tests/test_ucli_usage.py:104) | | AÇIK |
| `LiveUsageHelperTests.test_a_failing_provider_never_breaks_the_panel` (py/tests/test_ucli_usage.py:112) | | AÇIK |
| `StatusPayloadUsageTests.test_a_registered_running_ucli_row_carries_its_counters` (py/tests/test_ucli_usage.py:148) | | AÇIK |
| `StatusPayloadUsageTests.test_an_unregistered_running_ucli_row_carries_its_counters` (py/tests/test_ucli_usage.py:153) | | AÇIK |
| `StatusPayloadUsageTests.test_a_stopped_row_and_a_counterless_provider_have_no_usage` (py/tests/test_ucli_usage.py:157) | | AÇIK |
| `UcliWebConfigTests.test_empty_unset_and_garbage_mean_the_defaults_search_via_the_managed_searxng` (py/tests/test_ucli_web.py:75) | | AÇIK |
| `UcliWebConfigTests.test_search_docker_can_be_turned_off_in_every_spelling` (py/tests/test_ucli_web.py:80) | | AÇIK |
| `UcliWebConfigTests.test_search_docker_stays_on_for_on_values_and_for_empty_or_null` (py/tests/test_ucli_web.py:86) | | AÇIK |
| `UcliWebConfigTests.test_an_explicit_address_wins_and_switches_the_managed_one_off` (py/tests/test_ucli_web.py:91) | | AÇIK |
| `UcliWebConfigTests.test_a_filled_but_invalid_address_does_not_fall_back_to_the_managed_searxng` (py/tests/test_ucli_web.py:96) | | AÇIK |
| `UcliWebConfigTests.test_valid_searxng_address_defaults_the_flavor` (py/tests/test_ucli_web.py:104) | | AÇIK |
| `UcliWebConfigTests.test_https_and_explicit_flavor_in_any_case` (py/tests/test_ucli_web.py:109) | | AÇIK |
| `UcliWebConfigTests.test_brave_is_not_supported_yet_and_fails_closed` (py/tests/test_ucli_web.py:113) | | AÇIK |
| `UcliWebConfigTests.test_invalid_addresses_keep_search_off` (py/tests/test_ucli_web.py:118) | | AÇIK |
| `UcliWebConfigTests.test_whitespace_around_the_address_is_trimmed_not_rejected` (py/tests/test_ucli_web.py:125) | | AÇIK |
| `UcliWebConfigTests.test_domains_are_split_lowercased_and_deduplicated_in_order` (py/tests/test_ucli_web.py:129) | | AÇIK |
| `UcliWebConfigTests.test_domains_accept_a_list_too` (py/tests/test_ucli_web.py:134) | | AÇIK |
| `UcliWebConfigTests.test_invalid_domains_are_dropped_not_fixed` (py/tests/test_ucli_web.py:138) | | AÇIK |
| `UcliWebConfigTests.test_whitespace_is_a_separator_not_part_of_a_name` (py/tests/test_ucli_web.py:144) | | AÇIK |
| `UcliWebConfigTests.test_single_label_hosts_are_valid` (py/tests/test_ucli_web.py:148) | | AÇIK |
| `UcliWebConfigTests.test_domain_count_is_capped` (py/tests/test_ucli_web.py:152) | | AÇIK |
| `UcliWebConfigTests.test_fetch_domains_do_not_need_a_search_address` (py/tests/test_ucli_web.py:157) | | AÇIK |
| `SaveSettingsTests.test_defaults_are_off_and_cache_aware` (py/tests/test_ucli_web.py:172) | | AÇIK |
| `SaveSettingsTests.test_ucli_web_merges_per_field_and_empty_removes_the_field` (py/tests/test_ucli_web.py:177) | | AÇIK |
| `SaveSettingsTests.test_a_boolean_search_docker_round_trips_and_false_does_not_mean_remove` (py/tests/test_ucli_web.py:185) | | AÇIK |
| `SaveSettingsTests.test_the_off_switch_does_not_disturb_the_other_fields` (py/tests/test_ucli_web.py:196) | | AÇIK |
| `SaveSettingsTests.test_a_list_value_is_stored_as_a_comma_separated_string` (py/tests/test_ucli_web.py:201) | | AÇIK |
| `SaveSettingsTests.test_other_dict_settings_are_unaffected_by_the_list_handling` (py/tests/test_ucli_web.py:206) | | AÇIK |
| `SaveSettingsTests.test_a_non_dict_stored_value_degrades_to_empty` (py/tests/test_ucli_web.py:212) | | AÇIK |
| `SaveSettingsTests.test_the_escape_hatch_persists` (py/tests/test_ucli_web.py:218) | | AÇIK |
| `BinaryFlagProbeTests.test_exact_flag_matching` (py/tests/test_ucli_web.py:225) | | AÇIK |
| `BinaryFlagProbeTests.test_a_longer_flag_does_not_count_as_its_prefix` (py/tests/test_ucli_web.py:232) | | AÇIK |
| `BinaryFlagProbeTests.test_old_binary_supports_neither` (py/tests/test_ucli_web.py:237) | | AÇIK |
| `BinaryFlagProbeTests.test_probe_runs_once_per_binary_version_and_again_after_a_new_delivery` (py/tests/test_ucli_web.py:242) | | AÇIK |
| `BinaryFlagProbeTests.test_missing_or_non_executable_binary_is_false_and_not_cached` (py/tests/test_ucli_web.py:252) | | AÇIK |
| `BinaryFlagProbeTests.test_empty_help_output_is_not_cached` (py/tests/test_ucli_web.py:262) | | AÇIK |
| `BinaryFlagProbeTests.test_the_real_delivered_binary_knows_the_web_flags_when_it_is_new_enough` (py/tests/test_ucli_web.py:267) | | AÇIK |
| `WebArgsTests.test_everything_switched_off_adds_nothing_and_never_probes` (py/tests/test_ucli_web.py:292) | | AÇIK |
| `WebArgsTests.test_auto_search_uses_the_managed_searxng_address_and_names_the_session` (py/tests/test_ucli_web.py:300) | | AÇIK |
| `WebArgsTests.test_auto_search_not_ready_opens_the_session_without_search_and_without_error` (py/tests/test_ucli_web.py:307) | | AÇIK |
| `WebArgsTests.test_auto_search_with_an_old_binary_never_touches_docker` (py/tests/test_ucli_web.py:313) | | AÇIK |
| `WebArgsTests.test_an_explicit_address_never_starts_the_managed_one` (py/tests/test_ucli_web.py:321) | | AÇIK |
| `WebArgsTests.test_a_filled_invalid_address_neither_searches_nor_starts_docker` (py/tests/test_ucli_web.py:325) | | AÇIK |
| `WebArgsTests.test_a_crash_in_the_managed_searxng_never_breaks_the_spawn` (py/tests/test_ucli_web.py:329) | | AÇIK |
| `WebArgsTests.test_auto_search_and_fetch_domains_combine` (py/tests/test_ucli_web.py:335) | | AÇIK |
| `WebArgsTests.test_both_capabilities_on_a_new_binary` (py/tests/test_ucli_web.py:341) | | AÇIK |
| `WebArgsTests.test_search_only_adds_no_fetch_flags` (py/tests/test_ucli_web.py:348) | | AÇIK |
| `WebArgsTests.test_fetch_only_adds_no_search_flags` (py/tests/test_ucli_web.py:352) | | AÇIK |
| `WebArgsTests.test_a_binary_that_only_has_fetch_drops_search_and_says_so` (py/tests/test_ucli_web.py:356) | | AÇIK |
| `WebArgsTests.test_an_old_binary_gets_no_web_flags_at_all_so_spawn_cannot_crash` (py/tests/test_ucli_web.py:362) | | AÇIK |
| `BuildInnerCommandTests.test_default_command_is_byte_identical_to_before_when_no_search_backend_is_ready` (py/tests/test_ucli_web.py:394) | | AÇIK |
| `BuildInnerCommandTests.test_default_command_gets_the_managed_search_flags_when_the_backend_is_ready` (py/tests/test_ucli_web.py:398) | | AÇIK |
| `BuildInnerCommandTests.test_web_flags_are_appended_after_everything_else` (py/tests/test_ucli_web.py:405) | | AÇIK |
| `BuildInnerCommandTests.test_url_metacharacters_survive_shell_quoting` (py/tests/test_ucli_web.py:415) | | AÇIK |
| `BuildInnerCommandTests.test_read_only_sessions_get_web_too_and_no_allow_edit` (py/tests/test_ucli_web.py:420) | | AÇIK |
| `BuildInnerCommandTests.test_api_key_wrapper_keeps_the_flags_and_no_secret_enters_argv` (py/tests/test_ucli_web.py:425) | | AÇIK |
| `BuildInnerCommandTests.test_running_command_parsing_is_unaffected_by_the_new_flags` (py/tests/test_ucli_web.py:433) | | AÇIK |
| `BuildInnerCommandTests.test_every_effort_preset_round_trips_through_the_running_command` (py/tests/test_ucli_web.py:445) | | AÇIK |
| `BuildInnerCommandTests.test_effort_stays_unknown_when_a_limit_was_changed_by_hand_or_is_missing` (py/tests/test_ucli_web.py:458) | | AÇIK |
| `AutoContextTests.test_deriving_binary_gets_no_context_flag_and_effort_round_trips` (py/tests/test_ucli_web.py:495) | | AÇIK |
| `AutoContextTests.test_old_binary_keeps_preset_context` (py/tests/test_ucli_web.py:502) | | AÇIK |
| `AutoContextTests.test_explicit_setting_still_wins` (py/tests/test_ucli_web.py:506) | | AÇIK |
| `AutoContextTests.test_legacy_session_with_other_context_value_is_unknown` (py/tests/test_ucli_web.py:511) | | AÇIK |
| `FreshParse.test_parse_one_line_format` (py/tests/test_usage_fresh.py:21) | | AÇIK |
| `FreshParse.test_parse_falls_back_to_tui_format` (py/tests/test_usage_fresh.py:27) | | AÇIK |
| `FreshParse.test_other_providers_have_no_fresh_path` (py/tests/test_usage_fresh.py:32) | | AÇIK |
| `FreshParse.test_agy_fresh_argv_and_tsv_parse` (py/tests/test_usage_fresh.py:37) | | AÇIK |
| `FreshRun.test_fresh_ok_without_any_session` (py/tests/test_usage_fresh.py:52) | | AÇIK |
| `FreshRun.test_fresh_failure_returns_none` (py/tests/test_usage_fresh.py:60) | | AÇIK |
| `FreshRun.test_signed_out_agy_is_auth_required_not_read_failed` (py/tests/test_usage_fresh.py:66) | | AÇIK |
| `FreshRun.test_missing_binary_is_not_installed` (py/tests/test_usage_fresh.py:77) | | AÇIK |
| `FreshRun.test_usage_all_prefers_fresh_and_skips_sessions` (py/tests/test_usage_fresh.py:84) | | AÇIK |
| `FreshRun.test_usage_never_injects_into_live_sessions` (py/tests/test_usage_fresh.py:94) | | AÇIK |
| `FreshRun.test_api_balance_failure_does_not_break_usage` (py/tests/test_usage_fresh.py:110) | | AÇIK |
| `NoUsageRows.test_codex_and_ucli_explain_instead_of_unsupported` (py/tests/test_usage_fresh.py:123) | | AÇIK |
| `NoUsageRows.test_note_follows_request_language_without_mutating_state` (py/tests/test_usage_fresh.py:131) | | AÇIK |
| `PruneTranscripts.test_only_pure_usage_command_files_after_since_are_removed` (py/tests/test_usage_fresh.py:144) | | AÇIK |
| `ResolvedBinaryFallback.test_claude_found_outside_path` (py/tests/test_usage_fresh.py:162) | | AÇIK |
| `ResolvedBinaryFallback.test_provider_bin_override_used_by_usage_fresh_argv` (py/tests/test_usage_fresh.py:175) | | AÇIK |
| `P.test_parse_percent_fraction_reset` (py/tests/test_usage_fresh_tui.py:21) | | AÇIK |
| `P.test_parse_without_reset_unchanged` (py/tests/test_usage_fresh_tui.py:25) | | AÇIK |
| `P.test_argv_and_no_print_mode` (py/tests/test_usage_fresh_tui.py:29) | | AÇIK |
| `Ttl.test_ttl_cache_and_stale` (py/tests/test_usage_fresh_tui.py:40) | | AÇIK |
| `IsolatedNoRealRead.test_isolated_panel_does_not_launch_real_cli` (py/tests/test_usage_fresh_tui.py:52) | | AÇIK |
| `IsolatedNoRealRead.test_default_dir_is_not_isolated` (py/tests/test_usage_fresh_tui.py:57) | | AÇIK |
| `RealTmuxTrustDialog.test_dialog_accepted_before_command_in_private_cwd` (py/tests/test_usage_fresh_tui.py:78) | | AÇIK |
| `Sweep.test_dead_pid_socket_closed_and_unlinked` (py/tests/test_usage_fresh_tui.py:125) | | AÇIK |
| `Sweep.test_own_fresh_socket_untouched_but_own_old_one_closed` (py/tests/test_usage_fresh_tui.py:131) | | AÇIK |
| `Sweep.test_live_other_pid_fresh_untouched_old_closed` (py/tests/test_usage_fresh_tui.py:140) | | AÇIK |
| `Sweep.test_other_sockets_ignored_and_missing_dir_ok` (py/tests/test_usage_fresh_tui.py:147) | | AÇIK |
| `TestEvren.test_argv_safe_and_key_in_env_only` (py/tests/test_web_review_runner.py:118) | | AÇIK |
| `TestEvren.test_no_io_flag_when_unsupported` (py/tests/test_web_review_runner.py:133) | | AÇIK |
| `TestEvren.test_claude_env_filtered` (py/tests/test_web_review_runner.py:137) | | AÇIK |
| `TestEvren.test_redact_applied_and_answer_extracted` (py/tests/test_web_review_runner.py:145) | | AÇIK |
| `TestEvren.test_timeout_writes_partial` (py/tests/test_web_review_runner.py:153) | | AÇIK |
| `TestEvren.test_effort_always_sent_unless_model_rejects_it` (py/tests/test_web_review_runner.py:172) | | AÇIK |
| `TestEvren.test_partial_file_flag_added_only_when_supported` (py/tests/test_web_review_runner.py:187) | | AÇIK |
| `TestEvren.test_partial_file_path_is_symlink_free` (py/tests/test_web_review_runner.py:196) | | AÇIK |
| `TestEvren.test_killed_run_is_recovered_from_partial_file_masked` (py/tests/test_web_review_runner.py:208) | | AÇIK |
| `TestEvren.test_partial_without_report_heading_is_not_a_report` (py/tests/test_web_review_runner.py:223) | | AÇIK |
| `TestEvren.test_partial_turn_in_error_json_is_recovered` (py/tests/test_web_review_runner.py:231) | | AÇIK |
| `TestEvren.test_failed_run_keeps_error_log_masked_0600` (py/tests/test_web_review_runner.py:240) | | AÇIK |
| `TestEvren.test_successful_run_has_no_error_log` (py/tests/test_web_review_runner.py:253) | | AÇIK |
| `TestEvren.test_nonzero_no_output_is_error` (py/tests/test_web_review_runner.py:257) | | AÇIK |
| `TestEvren.test_busy_lock` (py/tests/test_web_review_runner.py:261) | | AÇIK |
| `TestEvren.test_missing_key_errors_and_releases_lock` (py/tests/test_web_review_runner.py:267) | | AÇIK |
| `TestCancel.test_cancel_kills_own_group_and_marks_partial` (py/tests/test_web_review_runner.py:276) | | AÇIK |
| `TestCancel.test_cancel_before_process_exists_is_not_swallowed` (py/tests/test_web_review_runner.py:300) | | AÇIK |
| `TestCancel.test_cancelled_before_spawn_kills_new_process` (py/tests/test_web_review_runner.py:312) | | AÇIK |
| `TestAgy.test_isolated_home_with_readonly_allow_list` (py/tests/test_web_review_runner.py:345) | | AÇIK |
| `TestAgy.test_bwrap_jail_wraps_argv_when_available` (py/tests/test_web_review_runner.py:361) | | AÇIK |
| `TestAgy.test_no_bwrap_or_jail_off_falls_back_to_allow_list` (py/tests/test_web_review_runner.py:376) | | AÇIK |
| `TestAgy.test_agy_model_quota_blocks_only_that_model_until_reset` (py/tests/test_web_review_runner.py:394) | | AÇIK |
| `TestAgy.test_tmpdir_is_writable_home_tmp_and_stale_entries_pruned` (py/tests/test_web_review_runner.py:413) | | AÇIK |
| `TestAgy.test_allow_override_and_off` (py/tests/test_web_review_runner.py:427) | | AÇIK |
| `TestAgy.test_ok_done_and_argv` (py/tests/test_web_review_runner.py:458) | | AÇIK |
| `TestAgy.test_label_mismatch_is_model_fallback_but_file_kept` (py/tests/test_web_review_runner.py:470) | | AÇIK |
| `TestAgy.test_no_log_is_model_fallback` (py/tests/test_web_review_runner.py:476) | | AÇIK |
| `TestAgy.test_old_log_not_taken_for_new_run` (py/tests/test_web_review_runner.py:480) | | AÇIK |
| `TestAgy.test_no_effort_for_non_gemini` (py/tests/test_web_review_runner.py:489) | | AÇIK |
| `TestAgy.test_model_not_in_agy_list` (py/tests/test_web_review_runner.py:493) | | AÇIK |
| `TestBannerLimit.test_monthly_quota_banner_with_rc0_is_limit_not_done` (py/tests/test_web_review_runner.py:508) | | AÇIK |
| `TestBannerLimit.test_real_report_mentioning_quota_stays_done` (py/tests/test_web_review_runner.py:516) | | AÇIK |
| `TestBannerLimit.test_month_start_helper` (py/tests/test_web_review_runner.py:526) | | AÇIK |
| `TestBodyless.test_failed_run_with_junk_body_is_error` (py/tests/test_web_review_runner.py:551) | | AÇIK |
| `TestBodyless.test_successful_exit_with_junk_body_is_error` (py/tests/test_web_review_runner.py:555) | | AÇIK |
| `TestBodyless.test_report_bodyless_rule` (py/tests/test_web_review_runner.py:559) | | AÇIK |
| `TestRecover.test_recover_on_start` (py/tests/test_web_review_runner.py:570) | | AÇIK |
| `TestRecover.test_recover_on_start_salvages_draft_report` (py/tests/test_web_review_runner.py:578) | | AÇIK |
| `TestRecover.test_recover_on_start_salvages_report_from_io_log` (py/tests/test_web_review_runner.py:590) | | AÇIK |
| `TestRecover.test_recover_on_start_no_report_head_keeps_file_empty` (py/tests/test_web_review_runner.py:608) | | AÇIK |
| `TestDetached.test_findings_are_saved_before_pair_turns_done` (py/tests/test_web_review_runner.py:647) | | AÇIK |
| `TestDetached.test_detached_run_writes_files_and_finishes` (py/tests/test_web_review_runner.py:664) | | AÇIK |
| `TestDetached.test_restart_adopts_live_run_and_finishes_it` (py/tests/test_web_review_runner.py:689) | | AÇIK |
| `TestDetached.test_run_finished_while_service_down_is_processed` (py/tests/test_web_review_runner.py:704) | | AÇIK |
| `TestDetached.test_pid_reuse_is_not_adopted_as_alive` (py/tests/test_web_review_runner.py:712) | | AÇIK |
| `TestDetached.test_adopt_keeps_pre_restart_io_log` (py/tests/test_web_review_runner.py:717) | | AÇIK |
| `TestDetached.test_adopt_failure_marks_partial_not_stuck_running` (py/tests/test_web_review_runner.py:728) | | AÇIK |
| `TestDetached.test_without_cfg_old_behavior_partial` (py/tests/test_web_review_runner.py:739) | | AÇIK |
