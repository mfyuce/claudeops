/**
 * `StatusPayload` and friends — 1:1 port of `_status_payload()`'s return
 * shape in the original `web.py` (React rewrite plan, dynamic-crunching-
 * lemon.md, Sequencing step 5).
 *
 * Cross-checked field-by-field against the REAL `_status_payload()` in
 * `/home/fatihyuce/work/projects/tmp/claudeops/py/claudeops/commands/web.py`
 * (lines 768-853 as of this port), not just the plan's prose — the plan
 * itself warns its own type block could have drifted from the real source
 * (same class of staleness the i18n port found in the key count). Result:
 * no drift found here — every field name/optionality below matches the
 * live backend exactly. Notable confirmations while checking:
 *   - `SessionInfo.registered`/`tmux` are always-present booleans (never
 *     missing) in both the registered-row loop and the proc-scan
 *     "unregistered" loop in `_status_payload()`.
 *   - `needs_ho` is `_needs_ho_cached(s)` which returns `Optional[bool]` —
 *     `boolean | null`, not just `boolean`.
 *   - `diag.fallback_alert_window_minutes` is a Python float constant
 *     (`FALLBACK_ALERT_WINDOW_MINUTES = 15.0`) — `number` is correct.
 */

export interface SessionInfo {
  name: string;
  /** Which registered host this session lives on — `"local"` (the
   * aggregator's own machine, `hosts.py`'s `LOCAL_HOST_NAME`) for every
   * session until a remote host is actually registered in Settings.
   * Identity across the whole app is the `(host, name)` pair, never bare
   * `name` alone — two different hosts can have a same-named session. */
  host: string;
  model: string;
  cwd: string;
  cli: string;
  running: boolean;
  pid: number | null;
  cpu: number | null;
  kind: "fresh" | "resume" | null;
  needs_ho: boolean | null;
  /** Session gerçekten bir tur işliyor mu (thinking/tool-çalışırken), yoksa
   * prompt'ta bekliyor mu — `cpu%`'nun aksine güvenilir (network-bound
   * beklerken CPU düşük kalabilir). `null` = bu CLI'da/bu durumda bilinmiyor
   * (`false`'la KARIŞTIRMA — "boşta" değil "bilinmiyor" demek). */
  busy: boolean | null;
  /** Pane'in gerçek tmux scrollback satır sayısı (`tmux_backend.HISTORY_LIMIT`=2000'de
   * tavan yapar, tmux o noktadan sonra en eski satırları siler) — `_history_size_cached`,
   * 30s cache. tmux-backed değilse/ölçülemiyorsa `null`. 2026-09-15, "1900-2000
   * olanları... seç" bulk-butonu için eklendi. */
  history_size: number | null;
  registered: boolean;
  tmux: boolean;
  /** `model` is what claudeops has RECORDED for the name (models.tsv — what the
   * next start would use, filled in even for stopped rows). These two come from
   * the RUNNING process's own command line instead, so the panel can show what a
   * session actually started with: the panel can start a session with a one-off
   * model WITHOUT rewriting models.tsv, so the two legitimately diverge. `null`
   * when the session isn't running (or the CLI takes no such flag). */
  live_model: string | null;
  live_effort: string | null;
  /** An instances.json instance (a dated chat spawned from a blueprint), not a
   * roster row. Optional: a remote host on older code doesn't send it. */
  instance?: boolean;
  /** Blueprint this row belongs to — its own name for a blueprint row, the
   * parent for an instance, `null` for diag/foreign sessions. */
  blueprint?: string | null;
  /** REMOTE rows only: is a `cops watch` mirror window for this session open on
   * THIS machine's desktop right now? Stamped by the aggregating panel from the
   * process scan fleet discovery already does, i.e. the same check the "open on
   * desktop" button's own already-open branch uses, so the two cannot disagree.
   * Absent = unknown (local rows, or a backend older than this field): never
   * treat it as `false` ("closed"). */
  mirror_open?: boolean;
  /** Process-lifetime token/request counters of the running session (`provider.live_usage()`, today only
   * ucli's `--status-file` `usage`). Absent/`null` = this CLI has no counter, or it could not be read
   * (also every REMOTE row: the gRPC host bridge does not carry it yet): show no badge, it does NOT mean
   * "0 tokens". */
  usage?: SessionUsage | null;
  /** What a running ucli session's current MODEL CALL is doing right now (`web._live_phase`, from ucli's `--status-file`
   * `phase`, unified-cli 1778f34): waiting for the response, thinking, writing, waiting to retry. Absent/`null` = no
   * call in flight, a CLI without phases, or a binary older than that commit: show no badge. `thinking`/`writing` exist
   * only when the session runs with `--stream`. Local rows only (the gRPC host bridge does not carry it). */
  phase?: SessionPhase | null;
  /** Prompt-cache life of a running claude session (`web._cache_info_cached`, monitoring only): `age` = seconds since
   * the last REAL model request, `ttl` = the cache lifetime (3600). Absent/`null` = unknown (a CLI without a cache
   * lifetime, or no matching transcript, e.g. a resumed session that has not had a turn yet): show no badge, it does
   * NOT mean cold. Local rows only (the gRPC host bridge does not carry it). */
  cache?: SessionCache | null;
  /** Context size of a running claude session (`web._context_info_cached`, monitoring only): `tokens` = the last
   * assistant turn's input + cache tokens (re-read on every turn), `warn` = the steward's handover threshold
   * (`steward.context_warn_tokens`, 0 = off). Absent/`null` = unknown (not claude, no turn yet): show no badge. */
  context?: SessionContext | null;
  /** CUMULATIVE token spend of a local claude session (`web._usage_total`, monitoring only; transcript-derived, one
   * turn counted once). Main-session totals plus a separate sub-agent total and a per-family breakdown. Absent/`null` =
   * unknown (not claude, no transcript, or the first background computation has not finished): show no badge.
   * Local rows only; codex/agy/copilot usage is unknown. */
  usage_total?: SessionUsageTotal | null;
}

export interface UsageParts {
  in: number;
  out: number;
  cache_write: number;
  cache_read: number;
}

export interface SessionUsageTotal extends UsageParts {
  turns: number;
  subagents: UsageParts & { n: number; turns: number };
  by_family: Record<string, UsageParts & { turns: number }>;
}

export interface SessionContext {
  tokens: number;
  warn: number;
}

export interface SessionCache {
  age: number;
  ttl: number;
}

/** ucli `.status.json` `phase` plus the two fields `web._live_phase` adds. `name` is `waiting_response`, `thinking`,
 * `writing`, `retry_backoff` or `rate_limited`; an unknown name (a newer ucli) still arrives and is shown as-is. */
export interface SessionPhase {
  name: string;
  /** Unix seconds when this phase began. */
  since_unix?: number;
  /** Seconds in this phase by the SERVER's clock (the browser's clock may differ); `null` without `since_unix`. */
  elapsed?: number | null;
  /** Seconds since ucli last wrote its status file (it rewrites at most every 2 s while a stream makes progress), by
   * the server's clock; `null` when unknown. For `thinking`/`writing` this is "how long since the last bytes". */
  idle?: number | null;
  /** 1-based attempt of the model call and its retry budget. */
  attempt?: number;
  max_attempts?: number;
  /** `retry_backoff` / `rate_limited`: the planned wait, seconds. */
  wait_secs?: number;
  /** `retry_backoff`: why the last attempt failed (a label). */
  detail?: string;
  /** `thinking` / `writing`: raw SSE bytes received so far (not tokens). */
  streamed_bytes?: number;
  /** 0 none, 1 amber, 2 red (`web._live_phase`): a retry or rate-limit wait is amber, a response that has not come for a
   * long time amber then red. Colour only, nothing is stopped. */
  warn?: number;
}

/** ucli `.status.json` `usage`: the sum over ALL tasks since the process started, failed ones included.
 * `prompt_tokens` includes the cached part; `reasoning_tokens` is a subset of `completion_tokens`. When
 * `reported < requests` (the endpoint sent no `usage` for some requests) or `unmetered > 0` (an attempt that
 * got no usable response, e.g. a timeout the server still processed) the token totals are a FLOOR. */
export interface SessionUsage {
  requests: number;
  reported: number;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  request_bytes: number;
  unmetered: number;
  unmetered_bytes: number;
  /** Evren QUOTA-equivalent tokens (`ucli_client.quota_equivalent_tokens`: cached input counts 3%, unlike the
   * board's raw "Toplam token"); a floor like the totals. Absent on a backend older than this field. */
  quota_tokens?: number;
  /** Colour level of `quota_tokens` against the `ucli_usage_warn` thresholds: 0 none, 1 amber, 2 red. Colour only,
   * nothing is stopped. */
  warn?: number;
}

/** One `GET /api/instances` row (History tab). */
export interface InstanceRecord {
  name: string;
  host: string;
  blueprint: string | null;
  cwd: string;
  cli: string;
  model: string;
  permission_mode: string;
  effort: string;
  created_at: number | null;
  last_started_at: number | null;
  origin: string;
  running: boolean;
}

export interface RosterEntry {
  name: string;
  /** See `SessionInfo.host`. */
  host: string;
  cwd: string;
  model: string;
  cli: string;
}

/** One registered remote host's live status, as fanned-out/merged server-side
 * by `web_hosts.merge_status()` — never fetched or computed in the browser.
 * `cli_list`/`cli_options`/`dups` are that host's OWN values (never the
 * aggregator's) — some CLIs (e.g. agy) fetch their model list live per host,
 * so these must not be assumed identical across hosts. */
export interface HostStatus {
  name: string;
  ok: boolean;
  error: string | null;
  cli_list: string[];
  cli_options: Record<string, CliOptions>;
  dups: string[];
}

/** One row in `/api/hosts`'s registry listing (Settings' Hosts section) —
 * NOT the same object as `HostStatus` above: this is registry metadata
 * (`base_url`, whether a token is saved) for the add/remove UI, `HostStatus`
 * is the operational status embedded in `/api/status`'s hot poll path.
 * `token` itself is NEVER present here or anywhere in a browser-visible
 * response — `has_token` is the only signal the UI ever gets. */
export interface HostRecord {
  name: string;
  base_url: string;
  has_token: boolean;
  ok: boolean;
  error: string | null;
  /** Fallback candidates, tried in order by the poller when `base_url` fails;
   * a working one gets silently promoted to `base_url` (see hosts.py's
   * `promote_base_url`). Not a secret, unlike `token`. */
  extra_urls?: string[];
}

/** `/api/cli/status` (GET) entry — `cli_install.py`'s `cli_status()` shape,
 * one per backend (claude/codex/copilot/agy). */
export interface CliInstallStatus {
  cli: string;
  found: boolean;
  path: string | null;
  managed_by_claudeops: boolean;
  installable: boolean;
  manual_url: string | null;
}

/** `/api/cli/status` (GET) — keyed by cli name, matching `cli_install.all_cli_status()`. */
export interface GetCliStatusResult {
  ok: true;
  clis: Record<string, CliInstallStatus>;
}

/** `/api/hosts` (GET) — a bare "just read local state" shape like
 * `DiagLogResult`, not `ApiResult`-wrapped: listing the registry has no
 * meaningful failure mode once auth already passed. */
export interface GetHostsResult {
  hosts: HostRecord[];
}

/** `/api/hosts/test` (POST) — on-demand check, bypassing the background
 * poller's ~3s cadence (`web_hosts.test_now()`). `ok` is "did the check
 * itself run" (always true once the host name resolves — the underlying
 * fetch never throws), NOT "is the host reachable" — that's `host_ok`, since
 * a host being offline is a normal/expected result, not a request failure. */
export type TestHostResult = ApiResult<{ host_ok: boolean; error: string | null }>;

export interface CliOptions {
  models: string[];
  permission_modes: string[];
  effort_levels: string[];
  /** The NARROW subset of `permission_modes` a session can be switched to while
   * it's running (the CLI's own Shift+Tab cycle). Empty = this CLI has no live
   * mode switching at all, so the Terminal view shows no mode picker. */
  cyclable_modes: string[];
  /** Prefill for the new-session form (Settings override, else the provider's
   * preference; claude: newest Sonnet + medium). Absent on remote (gRPC) rows:
   * callers fall back to `models[0]` / the last effort level. */
  default_model?: string;
  default_effort?: string;
}

export const EMPTY_CLI_OPTIONS: CliOptions = { models: [], permission_modes: [], effort_levels: [], cyclable_modes: [] };

export type Theme = "system" | "light" | "dark";

/** Primary sort key for groups in the Running/Registered/Disabled/Retired
 * tables. "name" (default, 2026-09-23) sorts by the short display name;
 * "cwd" sorts by the project's full folder path (keeps sessions in the same
 * folder next to each other) — the 2026-09-21 default until a same-day
 * follow-up complaint showed cwd-order doesn't track the visible name (e.g.
 * the "urartian" folder is `U_urartian_corpus_nlp`), so it became a
 * preference instead of staying hardcoded. */
export type FleetSort = "name" | "cwd";

/** Server-side persisted user settings (`~/.claude/claudeops/settings.json`,
 * TODO L73) — same across every browser/device. "" for `handover_effort` or
 * a missing `default_model[cli]` entry both mean "no override, use the
 * built-in default". */
export interface Settings {
  theme: Theme;
  handover_effort: string;
  fleet_sort: FleetSort;
  default_model: Record<string, string>;
  /** `{cli: effort}` override; missing entry = the provider's own default (`default_effort_for`). */
  default_effort: Record<string, string>;
  /** "on" | "off" — routing guidance for NEWLY opened sessions (`routing_guidance_enabled()`). */
  routing_guidance: string;
  /** "" = bundled `data/routing.md`; otherwise this text replaces it. */
  routing_guidance_text: string;
  /** {cli: mutlak binary yolu} — PATH'te bulunamayan (ör. proje-yerel bir
   * node_modules/.bin kurulumu) bir CLI için elle override. Boş/eksik = PATH
   * araması (mevcut davranış, değişmez). `settings.py`'nin `resolved_binary()`. */
  provider_bin: Record<string, string>;
  /** tmux scrollback (sabit `HISTORY_LIMIT`=2000) bu sayıya yaklaşınca Terminal
   * görünümünün sayaç rengi + ana tablonun "dikkat gerekenleri seç" butonu bunu
   * eşik alır — varsayılan 1900. `HISTORY_LIMIT`'in KENDİSİ burada YOK, o tmux'un
   * sabit yapılandırması, kullanıcı-tercihi değil. */
  history_warn_at: number;
  /** `py/cops layout`/"Yerleşim" sekmesinin desktop başına pencere sayısı —
   * `layout.py`'nin `_GRID_LAYOUTS`'una göre (cols,rows)'a çevrilir (2→2x1,
   * 4→2x2 [varsayılan], 8→4x2). */
  layout_grid: number;
  /** {cli: {ENV_VAR: set?}} — bir provider'ın BYOK env değişkenlerinin
   * (ör. ucli'nin `UCLI_API_KEY`'i) SADECE "ayarlı mı" durumu, `true`/eksik.
   * GERÇEK DEĞER asla buraya gelmez (`web.py`'nin `_redact_settings_for_wire`'ı
   * `/api/settings` POST'una giden ham `Record<string,string>`'i BOOLEAN'a
   * çevirir) — write-only alan, `has_token` (`HostRecord`) ile aynı desen. */
  byok: Record<string, Record<string, boolean>>;
  /** {max_steps, max_context_kib, max_tool_calls, max_output_tokens: string}
   * (4. alan 2026-09-28 eklendi) — ucli'nin effort preset'lerinin
   * (`_EFFORT_LIMITS`, provider tarafında, medium/high) üstüne binen
   * alan-bazlı override. Boş/eksik alan = preset'in kendi varsayılanı
   * (`provider_bin` ile aynı "boş=otomatik" dili). `default_model`/
   * `provider_bin` gibi {cli: ...} DEĞİL — bu numerik "effort" kavramı bugün
   * SADECE ucli'de var, `settings.py`'nin `ucli_limit_overrides()`'ı okur. */
  ucli_limits: Record<string, string>;
  /** {search_url, search_docker, allow_fetch_domains: string} (+ `search_flavor`,
   * UI'da yok, yalnız "searxng") — ucli'nin web araçları (TODO.md 2026-10-16,
   * TBD#88). Hepsi isteğe bağlı ham string, eksik anahtar = varsayılan: arama
   * claudeops'un yönettiği yerel SearXNG ile AÇIK, `fetch_url` KAPALI. Geçerlilik
   * kararı backend'in (`settings.py`'nin `ucli_web_config()`'i); settings.json elle
   * düzenlenebildiği için `allow_fetch_domains` çalışma anında liste de olabilir. */
  ucli_web: Record<string, string>;
  /** ucli's OpenAI-compatible endpoint (2026-10-20): http(s) address; empty/invalid = the Evren default. Not a secret
   * (the API key stays in `byok`). New ucli sessions + the model-list fetch read it; running sessions are unaffected. */
  ucli_endpoint: string;
  /** {mode: string} (2026-10-18) — ucli's embedded Lua script layer (`chat --allow-script[=read|full]`, unified-cli
   * 119c8e5): empty/missing/"off" = off (the DEFAULT), "read" = scripts may call read-only tools, "full" = scripts may
   * call everything the session already gives the model (writes only with allow-edit/allow-create, fetch_url,
   * web_search, MCP; the gates are the model's own). Passed only to a binary that knows the flag, to NEW sessions.
   * `settings.py`'s `ucli_script_mode()`; any other value counts as off. Optional on the wire: a backend older than
   * this field omits it. */
  ucli_script?: Record<string, string>;
  /** {amber, red: string} (2026-10-17) — per-session Evren quota-equivalent token thresholds for the ucli badge colour;
   * empty/missing = built-in 1M / 3M, "off" or "0" = that level disabled. `settings.py`'s `ucli_usage_warn_thresholds()`. */
  ucli_usage_warn: Record<string, string>;
  /** "on" (default) | "off" — the tunnel health watchdog of `run-tunnel.sh` (2026-10-17): when the public tunnel
   * address answers HTTP 530 three checks in a row, cloudflared is restarted (the URL changes, ntfy goes out).
   * Read by the script every check, so a change applies without restarting the tunnel. `settings.py`'s
   * `tunnel_watch_enabled()`; any `off`-word ("0", "false", "no", ...) counts as off. */
  tunnel_watch: string;
}

/** `web.py`'nin `_usage_all()`'ının tek bir satırı — `provider.parse_usage_text()`'in
 * çıktısı, aynen ("label"/"percent"/"detail" hepsi zaten insan-okunur metin). */
export interface UsageEntry {
  label: string;
  percent: string;
  detail: string;
}

/** `supported:false` = bu CLI için `usage_command()` yok (bugün: agy/codex/shell,
 * canlı doğrulanıp icat edilmedi, [[TODO#usage]]) — `available`/`reason`/`entries`
 * hiç yok, ayrım burada biter. `supported:true` iken `available:false` ise
 * `reason` ("no_running_session"|"all_sessions_busy"|"send_failed"|"parse_failed")
 * neden çekilemediğini söyler — `all_sessions_busy` (2026-09-14 eklendi): bu CLI'nın
 * çalışan session'ları var ama hepsi ya bir turn işliyor ya da parola bekliyor,
 * kontrol için hiçbiri güvenle kullanılamadı (bkz. web.py `_usage_all`); `available:true`
 * iken `entries` doludur. */
export interface UsageProviderResult {
  supported: boolean;
  available?: boolean;
  reason?: string;
  checked_via?: string;
  entries?: UsageEntry[];
}

export interface UsageResult {
  ok: boolean;
  providers: Record<string, UsageProviderResult>;
}

/** `web.py`'nin `_context()`'i — `UsageProviderResult` ile AYNI şekil ama
 * hesap değil TEK, isimle hedeflenen session (`/api/context`, name gerekir).
 * `reason` ("unsupported"|"no_tmux"|"busy"|"masked"|"send_failed"|
 * "parse_failed") `ok:true, available:false` iken dolu; `checked_via`/
 * `supported` yok, o kavramlar "provider başına rastgele seç" hesap-modeline
 * özgü. `ok:false` (name yok/session yok/isim belirsiz — `_err()`'in HER
 * ZAMANKİ şekli, `ApiResult` ile aynı) iken `error` zaten seçili dilde
 * hazır metin, `reason` YOK — ikisi karıştırılmasın. */
export interface ContextResult {
  ok: boolean;
  error?: string;
  available?: boolean;
  reason?: string;
  entries?: UsageEntry[];
}

/** `web.py`'nin `_live_model()`'i — `ContextResult` ile AYNI `ok`/`available`/
 * `reason` iskeleti ama `entries` yerine `model` (tek string). Salt dosya
 * okuma (jsonl'ın son `message.model`'i), session'a hiçbir şey enjekte
 * etmez — `reason` bugün ("unsupported"|"no_jsonl"|"no_assistant_turn"),
 * `busy`/`masked`/`send_failed` YOK (o kısıtlar sadece enjeksiyon yapan
 * `_context()`'e özgü). */
export interface LiveModelResult {
  ok: boolean;
  error?: string;
  available?: boolean;
  reason?: string;
  model?: string;
}

/** `web.py`'nin `_live_effort()`'ü — `LiveModelResult` ile AYNI iskelet,
 * `model` yerine `effort`. TODO.md 2026-10-07: `session.live_effort` spawn
 * anındaki `--effort`'ta donuyor, terminale yazılan bir `/effort` hiçbir
 * yerde yansımıyordu. */
export interface LiveEffortResult {
  ok: boolean;
  error?: string;
  available?: boolean;
  reason?: string;
  effort?: string;
}

export interface DiagInfo {
  web_pid: number;
  web_uptime_seconds: number;
  gt: { pid: number; uptime_seconds: number } | null;
  windowless: string[] | null;
  recent_fallback_count: number;
  fallback_alert: boolean;
  fallback_alert_window_minutes: number;
}

export interface StatusPayload {
  config_ok: boolean;
  config_code: string;
  config_detail: string;
  dups: string[];
  sessions: SessionInfo[];
  closed: RosterEntry[];
  retired: RosterEntry[];
  cli_list: string[];
  cli_options: Record<string, CliOptions>;
  layout_missing_deps: string[];
  diag: DiagInfo;
  /** Unix seconds the serving process started — changes on every server
   * restart (redeploy). `useStatus.ts` compares this against the value it
   * first saw and reloads the page when it changes. */
  server_started_at: number;
  /** The wrap-up prompt text `_handover()` sends, in both languages — so it
   * can be shown/copied from the UI without actually running a handover. */
  handover_msg: { tr: string; en: string };
  settings: Settings;
  /** `remote_desktop.status()` — "Uzak Masaüstü" tab's on-demand screen-share
   * daemon (2026-09-04, `rust/screenshare`). `port` is always the internal
   * proxy target, never exposed to the browser directly — it connects
   * through `/ws/desktop` (same token auth as everything else) regardless. */
  remote_desktop: { running: boolean; port: number | null };
  /** Read-only — `py/cops service install`'ın yazdığı `tunnel_url.txt`/
   * `tunnel_label.txt` (varsa). İkisi de dosya yoksa `null` (quick-tunnel'da
   * URL cloudflared'ın kendi log'undan gelir, `service install` hiç
   * çalışmamışsa hiçbiri yoktur) — asla hata değil. */
  tunnel: { url: string | null; label: string | null };
  /** Every registered remote host's live status — always present (possibly
   * `[]`), never optional; `web_hosts.merge_status()` guarantees this key.
   * `sessions`/`closed`/`retired` above already carry each row's own `host`
   * tag — this array is metadata ABOUT each host (reachability, its own
   * `cli_list`/`cli_options`/`dups`), not another copy of its rows. */
  hosts: HostStatus[];
  /** TOBEDECIDED#15 Phase 1 — workers-only orchestration. Local-only (never
   * merged across hosts, unlike `sessions`/`hosts` above — `commands/
   * web_orch.py` refuses any `host != "local"` participant). */
  orch: OrchState;
  /** Değnekçi (steward, 2026-10-19) — `web_steward.summary()`: local-only, 5 s cached light slice
   * (counts + last tick + brain). The full picture (`/api/steward/state`) is fetched by `StewardTab`
   * only while that tab is open, keyed on the counts here changing (no extra polling). */
  steward: StewardSummary;
  /** Multi-steward (P6): one light row per identity; `steward` above stays the default's. Absent on older backends. */
  stewards?: StewardIdentity[];
  /** Token use per model family over the last `window_minutes` (`model_usage.summary()`, monitoring only, refreshed in the
   * background; `null` until the first scan finishes). `fresh` = input + cache-write tokens, `read` = cache-read tokens. */
  model_usage?: ModelUsage | null;
  /** 2026-09-17, "son snapshot" — snapshot GEÇMİŞİNİN (bkz. `SnapshotListResult`)
   * en son kaydının meta özeti (tam session listesi DEĞİL, sadece ne-zaman/
   * kaç-session/hangi-tür — Settings panelinin "Son snapshot: X, N session"
   * gösterimi için). `orch` gibi local-only, `web_hosts.merge_status`'a hiç
   * girmez (bu makinenin KENDİ fleet'inin anlık görüntüsü, uzak host'unkiyle
   * karışmaz). `kind`, 2026-09-21: panel süreci SIGTERM alınca (servis
   * stop/restart/gerçek shutdown) OTOMATİK eklenen "closing" kaydı, kullanıcının
   * elle bastığı "manual"dan ayırt edilsin diye — `null` hiç kayıt yokken. */
  snapshot: { saved_at: number | null; kind: "manual" | "closing" | null; count: number; mirrors?: number };
}

// ── TOBEDECIDED#15 Phase 1 — workers-only orchestration ─────────────────
// `orchestration.py`'s dataclasses (`dataclasses.asdict` output). Phase 1
// only ever produces role:"worker" participants (`web_orch._preflight`
// rejects controller/decider outright), so the frontend builds no role
// picker yet — `role` stays a plain `string` (not a union) since the
// backend's own type is `str`, not an enum, and Phase 2 will add values
// this build can't see.

export interface OrchParticipant {
  role: string;
  host: string;
  name: string;
  cli: string;
}

/** One worker's outcome (`orchestration.RunResult`). A worker with no entry
 * yet in a `"working"` run simply hasn't finished — the frontend treats
 * that gap as a synthetic "pending" status, never a value the backend
 * itself sends. */
export interface OrchResultItem {
  seq: number;
  kind: string;
  role: string;
  host: string;
  name: string;
  cli: string;
  created_at: number;
  status: "ok" | "timeout" | "cancelled" | "send_failed" | "no_envelope" | "unreachable";
  verdict: string;
  verdict_key: string;
  text: string;
  elapsed: number;
}

export interface OrchTallyEntry {
  verdict_key: string;
  votes: number;
  voters: string[];
}

export interface OrchAbstainedEntry {
  name: string;
  status: string;
}

/** `note` is emitted by the backend's `resolve_outcome()` as a fixed
 * Turkish sentence regardless of the run's own `lang` (a pre-existing
 * backend quirk, not something this frontend patches over) — shown as-is,
 * same "backend text stays as-is" treatment as `_v1_error`'s messages. */
export interface OrchOutcome {
  method: "decider" | "unanimous" | "majority" | "single_worker" | "no_consensus" | "none";
  final: string;
  by: { host: string; name: string; cli: string } | null;
  tally: OrchTallyEntry[];
  abstained: OrchAbstainedEntry[];
  note: string;
}

export interface OrchRun {
  id: string;
  created_at: number;
  updated_at: number;
  status: "briefing" | "working" | "deciding" | "done" | "needs_human" | "failed" | "cancelled";
  lang: string;
  task: string;
  verdict_hint: string;
  worker_timeout: number;
  participants: OrchParticipant[];
  results: OrchResultItem[];
  outcome: OrchOutcome | null;
  error: string | null;
  /** Controller's briefing-phase output, once parsed — the ACTUAL text sent
   * to workers when a controller is assigned and cooperates; "" if no
   * controller, or the controller didn't produce a usable brief (raw `task`
   * was used instead, same as when no controller exists at all). */
  brief: string;
}

/** `_status_payload()`'s lightweight `orch.active` view (`web_orch.
 * active_summary()`) — no result text, rides the existing 2s WS/poll
 * cadence. `OrchTab` fetches the fuller `OrchRun` via `getOrchRun()` only
 * when this summary signals a change (status/result_count), rather than
 * polling on its own timer. */
export interface OrchActiveSummary {
  id: string;
  status: string;
  task_head: string;
  participants: OrchParticipant[];
  result_count: number;
}

/** A saved draft lineup entry — `orch_store.save_draft`/`load_draft` persist
 * whatever shape the client posts, unvalidated; this frontend always
 * saves/reads exactly this shape. */
export interface OrchDraftParticipant {
  role: string;
  host: string;
  name: string;
  cli: string;
}

export interface OrchState {
  draft: OrchDraftParticipant[];
  active: OrchActiveSummary | null;
  recent: OrchRun[];
}

/** `web_orch.http_start()`. */
export type OrchStartResult = ApiResult<{ run_id: string }>;
/** `web_orch.http_runs()`. */
export type GetOrchRunsResult = ApiResult<{ runs: OrchRun[] }>;
/** `web_orch.http_run()`. */
export type GetOrchRunResult = ApiResult<{ run: OrchRun }>;

// ── POST-route result shapes ────────────────────────────────────────────
// Every `_xxx()` backend action returns `{ok: false, error: string}` (via
// `_err()`) on failure; success shapes vary per action. Not part of the
// plan's explicit type block (that one only covers the GET /api/status
// shape) — added here so `api/client.ts` can type all 16 POST routes per
// this stage's brief, cross-checked against each handler's real `return`
// statements in web.py.

export interface ApiErr {
  ok: false;
  error: string;
}

/** `T` is the extra fields present only on the success branch. */
export type ApiResult<T extends object = Record<string, never>> = ({ ok: true } & T) | ApiErr;

/** `_start()` / `_reactivate_and_start()` (delegates to `_start`). */
export type StartResult = ApiResult<{ kind?: string }>;
/** `_stop()`. */
export type StopResult = ApiResult<{ result: string[] }>;
/** `_new_chat()`. */
export type NewChatResult = ApiResult<{ name: string; kind: string }>;
/** `_adopt()`. */
export type AdoptResult = ApiResult<{ kind: string; new_name: string }>;
/** `_edit_project()`. `warnings` — non-blocking notices (target folder doesn't
 * exist yet, or the old folder's conversation history becomes unreachable);
 * the edit still applies (`ok: true`) even when this is non-empty. */
export type EditResult = ApiResult<{ name: string; warnings: string[] }>;
/** `_register_project()` / `_retire()` / `_close_project()` / `_term_input()` /
 * `_term_key()` / `_open_window()` — bare `{ok: true}` on success. */
export type SimpleResult = ApiResult;
/** `_open_mirror_window()`. `already_open`: a mirror for this session was already running, so none was
 * spawned; `focused` (only then): whether the existing window could be raised (`wmctrl`, best-effort). */
export type MirrorWindowResult = ApiResult<{ already_open: boolean; focused?: boolean }>;
/** `_instances_list()`. */
export type InstancesResult = ApiResult<{ instances: InstanceRecord[] }>;
/** `_handover()`. */
export type HandoverResult = ApiResult<{ kind?: string }>;
/** `_compact()` — same shape as `_handover()` (kill + resume). */
export type CompactResult = ApiResult<{ kind?: string }>;
/** `_save_settings()`. */
export type SettingsResult = ApiResult<{ settings: Settings }>;

/** `_term_output()`. `masked` — pane is currently in getpass/sudo-style hidden-input
 * mode (icanon-on + echo-off termios signature), see `pane_is_masked_input()`.
 * `mode` — the permission mode the pane's status bar is CURRENTLY showing
 * (`_detect_mode_in_text`), or null when this CLI has no live mode concept or
 * nothing recognizable is on screen yet. Both ride along on the text this poll
 * already fetched; neither costs an extra tmux call. `history_size` (2026-09-14) —
 * the pane's real tmux scrollback line count, riding along on the SAME
 * `list-panes` call as `cols`/`rows` — caps at `HISTORY_LIMIT` (2000, see
 * tmux_backend.py) since tmux evicts the oldest lines once its own
 * `history-limit` is reached; null only when the pane size itself couldn't be read.
 * `alternate_screen` (2026-09-29) — same `list-panes` call's `#{alternate_on}`: true
 * while the pane is in the alternate screen buffer (vim/htop/less, and Claude/agy/
 * codex's normal interactive TUI). tmux never adds alternate-screen output to
 * scrollback, so `history_size` is structurally frozen near 0 whenever this is true,
 * independent of real conversation/work volume — the UI should hide or reinterpret
 * the counter rather than show a permanently-misleading "0/2000".
 * `lite` / `urls` / `paths` (2026-10-09, TODO.md "Terminal karesi çok büyük"): present only
 * when the request carried `lite=1` AND the backend knows it (`web_term_lite.py`; an older
 * backend ignores the flag and sends a full frame, so `lite !== true` always means "legacy
 * full frame"). A lite frame's `text` is just the visible `rows` lines; the scrollback is
 * fetched on demand with an ordinary (non-lite) request, and `urls`/`paths` are what
 * `UrlBanner` used to extract from the full text on the client. */
export type TermOutputResult = ApiResult<{
  text: string;
  cols: number | null;
  rows: number | null;
  history_size: number | null;
  alternate_screen: boolean | null;
  masked: boolean;
  mode: string | null;
  lite?: boolean;
  urls?: string[];
  paths?: string[];
}>;
/** One message in `_term_chat(mode="full")`'s `full_history()`-backed history. */
export interface ChatMessage {
  /** `boundary` = compaction marker (`text` "trigger, preTokens"), `summary` = the compaction
   * summary the CLI injected as a user turn; both only from claude, older hosts never send them. */
  role: "user" | "assistant" | "boundary" | "summary";
  text: string;
}

/** `_term_chat()` — `supported: false` for CLIs without a chat transcript
 * (agy/codex/shell today — only `claude` overrides `last_exchange`/`full_history`,
 * see TODO.md's 2026-09-04 provider-parity audit), `ok: false` is a real backend
 * error (session gone etc).
 * `mode="last"` (default) returns `user`/`assistant`; `mode="full"` returns
 * `messages` instead — same supported:false contract either way.
 * `total` (2026-09-17, incremental fetch): the FULL transcript's message
 * count. When a request sent `since`, `messages` is only the tail after that
 * cursor — `messages.length === total` is the signal that the server sent
 * everything (either `since` was 0, or it clamped a stale/too-large `since`
 * back to 0 after a reset), telling the caller to replace its local list
 * instead of appending to it. See `ChatView.tsx`. */
export type TermChatResult =
  | { ok: true; supported: false }
  | { ok: true; supported: true; user: string; assistant: string }
  | { ok: true; supported: true; messages: ChatMessage[]; total: number }
  | ApiErr;

/** One entry in `_files_list()`'s directory listing (`files.list_dir()`). */
export interface FileEntry {
  name: string;
  is_dir: boolean;
  size: number;
  mtime: number; // epoch seconds
}

/** One allowed root for a session's file browser (`files.roots_for_session()`
 * — always at least "project"; claude sessions also get "claude-transcripts"). */
export interface FileRoot {
  key: string;
  path: string;
}

/** `_files_list()` — `path` omitted in the request lists the session's first
 * (default/project) root. */
export type FilesListResult = ApiResult<{ roots: FileRoot[]; path: string; entries: FileEntry[] }>;

/** `_files_read()` — inline viewer content (capped at `MAX_VIEW_BYTES`,
 * much smaller than the download cap). */
export type FilesReadResult = ApiResult<{ text: string }>;

/** `_handle_files_upload()` — the destination path actually written. */
export type FilesUploadResult = ApiResult<{ path: string }>;

/** `_files_delete()` — no extra data, just ok/error. */
export type FilesDeleteResult = SimpleResult;

/** `_files_write()` — no extra data, just ok/error (same shape as delete). */
export type FilesWriteResult = SimpleResult;

/** `_files_rename()`/`_files_mkdir()` — the resulting real path (renamed-to
 * or newly-created), so the caller could jump straight to it if it wanted. */
export type FilesRenameResult = ApiResult<{ path: string }>;
export type FilesMkdirResult = ApiResult<{ path: string }>;

/** `_files_validate()` — candidate path strings (regex-matched out of raw
 * terminal text) filtered down to ones that resolve to a real, allowed
 * file; `valid` is absolute paths, deduplicated, in input order. */
export type FilesValidateResult = ApiResult<{ valid: string[] }>;

/** `/api/diag/log` (GET, not a POST route). */
export interface DiagLogResult {
  lines: string[];
}

/** `_diag_spawn_test()` — the two early-return failure shapes
 * (gnome-terminal missing / hung) skip `_err()` and hand-roll their own
 * dict, so `ok: false` here does NOT always carry `error` the way every
 * other route's failure does. */
export type DiagSpawnTestResult =
  | { ok: true; stderr: string; window_found: boolean }
  | ApiErr
  | { ok: false; stderr: string; window_found: false; detail: string };
/** `_diag_restart_gt()`. */
export type DiagRestartResult = ApiResult<{ result: string; pid: number }>;
/** `_diag_ask()`. */
export type DiagAskResult = ApiResult<{ name: string; kind: string }>;

/** `io_providers/base.py::FormField`, flattened by `_io_providers_meta()` —
 * lets the UI draw a form for ANY tmux-less provider without knowing its
 * name ahead of time (TOBEDECIDED#44, "shell/tmux olmadan provider ekleme
 * yöntemi"). `type` is `"text"` or `"password"`. */
export interface IoFormField {
  key: string;
  label: string;
  type: string;
  placeholder: string;
  required: boolean;
}
/** `_io_providers_meta()`. */
export type IoProvidersResult = ApiResult<{ providers: Record<string, { fields: IoFormField[] }> }>;
/** `_io_ask()` — synchronous, no fleet session (not a CliProvider). */
export type IoAskResult = ApiResult<{ answer: string; model_rounds: number; tool_calls: number }>;
/** `_io_sessions()` — existing session names for a provider+cwd, most-recently-used first. */
export type IoSessionsResult = ApiResult<{ sessions: string[] }>;
/** `_io_history()` — same `{role, text}` shape as `CliProvider.full_history`. */
export type IoHistoryResult = ApiResult<{ turns: { role: string; text: string }[] }>;

/** `remote_desktop.start()`/`.stop()` — `already_running`/`already_stopped`
 * are informational only (still `ok: true`), matching the backend's own
 * idempotent-no-op shape. */
export type DesktopStartResult = ApiResult<{ port?: number; already_running?: boolean }>;
export type DesktopStopResult = ApiResult<{ already_stopped?: boolean }>;

/** `_run_layout()`. */
export type LayoutResult = ApiResult<{
  total: number;
  skipped: number;
  assignments: { name: string; ws: number; x: number; y: number }[];
  applied: boolean;
}>;

/** `_snapshot_save()` — always appends a NEW "manual" entry to the history. */
export type SnapshotSaveResult = ApiResult<{ saved_at: number; count: number; mirrors?: number }>;
/** `_snapshot_resume()` — one row per snapshot entry; `error` only present
 * when `status === "failed"` (register or start failed for that name — the
 * rest of the batch still ran, this is NOT an all-or-nothing operation). */
export type SnapshotResumeResult = ApiResult<{
  results: { name: string; status: "started" | "already_running" | "failed"; error?: string }[];
  started: number;
  already_running: number;
  failed: number;
  /** Open `cops watch` mirror windows saved with the snapshot (TBD#74 phase 3), reopened AFTER the sessions
   * started. A remote session that is not running is NOT started (the snapshot is this machine's fleet);
   * its window opens anyway and waits. `skipped_hidden`: "start hidden" opens no windows. Absent on a
   * panel that predates mirror snapshots. */
  mirrors?: { host: string; name: string; status: "opened" | "already_open" | "failed" | "skipped_hidden"; error?: string }[];
  mirrors_opened?: number;
  mirrors_already_open?: number;
  mirrors_failed?: number;
  mirrors_skipped?: number;
}>;
/** `_snapshot_list()` — metadata-only history, newest first (2026-09-21, see
 * `snapshot.py`'s module docstring for why this replaced the old single-record
 * `last_snapshot.json`). Each row's `saved_at` is what `apiSnapshotResume`'s
 * optional `savedAt` param targets to resume THAT specific past snapshot
 * instead of the newest one. */
export type SnapshotListResult = ApiResult<{
  snapshots: { saved_at: number; kind: "manual" | "closing"; count: number; mirrors?: number }[];
}>;

// ── Değnekçi (steward) — `py/claudeops/steward.py` dataclasses via `dataclasses.asdict` ──

export interface StewardSummary {
  enabled: boolean;
  mode: string;
  tick_seconds: number;
  projects: Record<string, number>;
  open_questions: number;
  ideas_new: number;
  pending_items: number;
  last_tick: { at?: number; trigger?: string; actions?: number; dry?: number; error?: string };
  last_tour: number;
  brain: { name: string; running: boolean };
  recent: StewardRecent[];
}

export interface StewardIdentity {
  id: string;
  label: string;
  enabled: boolean;
  mode: string;
  projects: Record<string, number>;
  project_count: number;
  open_questions: number;
  ideas_new: number;
  pending_items: number;
  brain: { name: string; running: boolean };
  ownership_conflicts?: unknown;
}

export interface StewardListResult {
  ok: boolean;
  stewards: StewardIdentity[];
}

export interface StewardRecent {
  ts: number;
  kind: string;
  name: string;
  reason?: string;
  ok?: boolean;
  dry?: boolean;
  detail?: string;
  /** Remote host the action targeted (only present for remote projects). */
  host?: string;
}

/** Cached health of a remote host (`remote_health`): ok = fresh, down = unreachable/stale, backoff = paused after repeated failures. */
export interface StewardHostHealth {
  state: "ok" | "down" | "backoff";
  /** Capability api version (0 = old host), null = not probed yet. */
  api: number | null;
  /** Seconds since the last successful poll, null = never. */
  age: number | null;
}

export interface StewardQuestion {
  id: string;
  project: string;
  text: string;
  created_at: number;
  status: string;
  answer: string;
  answered_at: number;
  delivered_at: number;
  source: string;
  /** Short choices (≤6); empty = free-text question. The answer may still be free text. */
  options?: string[];
  notified_at?: number;
  /** Remote host of the question's project (only present for remote projects). */
  host?: string;
}

export interface StewardProject {
  name: string;
  phase: string;
  kind: string;
  goal: string;
  priority: number;
  cadence_minutes: number;
  notes: string;
  model: string;
  effort: string;
  last_visit: number;
  last_directive?: string;
  running?: boolean;
  /** One line from the project card (`card_one_liner`), "" when no card yet. */
  next_step: string;
  card_updated_at: number;
  /** Remote host (`hosts.json` name); "" or absent = local. */
  host?: string;
  /** The project's running session (terminal target); absent when none is running. */
  session?: { name: string; host: string };
}

export interface StewardPendingItem {
  kind: string;
  name: string;
  text: string;
}

export interface StewardIdea {
  id: string;
  text: string;
  created_at: number;
  status: string;
  project: string;
  source: string;
}

export interface StewardStateResult {
  ok: boolean;
  config: Record<string, unknown>;
  summary: StewardSummary;
  projects: StewardProject[];
  running: { name: string; cwd: string; cli: string; model: string; host?: string }[];
  questions: StewardQuestion[];
  ideas: StewardIdea[];
  recent: StewardRecent[];
  /** Items the engine will hand the brain on the next tour (last computed tick; may be absent on older backends). */
  pending?: StewardPendingItem[];
  /** Present only when a controlled shutdown has been started for this identity. */
  shutdown?: { started?: number; done?: number | null; cancelled: boolean; items: Record<string, { stage: string; blocked: string }> };
  /** Present only when the identity has remote projects. */
  remote_hosts?: Record<string, StewardHostHealth>;
}

export interface StewardAnswerResult {
  ok: boolean;
  error?: string;
  question?: StewardQuestion;
}

export interface StewardAskResult {
  ok: boolean;
  error?: string;
  id?: string;
  notified?: boolean;
  link?: string;
  dup?: boolean;
}

export interface StewardTickResult {
  ok: boolean;
  error: string;
  actions: { kind: string; name: string; reason: string; ok: boolean; detail: string }[];
  dry: { kind: string; name: string; reason: string; dry: boolean }[];
  mode: string;
  at: number;
}


export interface ModelUsageFamily {
  calls: number;
  fresh: number;
  read: number;
  out: number;
}

export interface ModelUsage {
  window_minutes: number;
  at: number;
  families: Record<string, ModelUsageFamily>;
  fable_top: { label: string; calls: number; fresh: number; read: number }[];
}
