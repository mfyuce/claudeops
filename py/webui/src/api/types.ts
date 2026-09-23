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
  /** 2026-09-17, "son snapshot" — snapshot GEÇMİŞİNİN (bkz. `SnapshotListResult`)
   * en son kaydının meta özeti (tam session listesi DEĞİL, sadece ne-zaman/
   * kaç-session/hangi-tür — Settings panelinin "Son snapshot: X, N session"
   * gösterimi için). `orch` gibi local-only, `web_hosts.merge_status`'a hiç
   * girmez (bu makinenin KENDİ fleet'inin anlık görüntüsü, uzak host'unkiyle
   * karışmaz). `kind`, 2026-09-21: panel süreci SIGTERM alınca (servis
   * stop/restart/gerçek shutdown) OTOMATİK eklenen "closing" kaydı, kullanıcının
   * elle bastığı "manual"dan ayırt edilsin diye — `null` hiç kayıt yokken. */
  snapshot: { saved_at: number | null; kind: "manual" | "closing" | null; count: number };
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
 * `history-limit` is reached; null only when the pane size itself couldn't be read. */
export type TermOutputResult = ApiResult<{
  text: string;
  cols: number | null;
  rows: number | null;
  history_size: number | null;
  masked: boolean;
  mode: string | null;
}>;
/** One message in `_term_chat(mode="full")`'s `full_history()`-backed history. */
export interface ChatMessage {
  role: "user" | "assistant";
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
export type SnapshotSaveResult = ApiResult<{ saved_at: number; count: number }>;
/** `_snapshot_resume()` — one row per snapshot entry; `error` only present
 * when `status === "failed"` (register or start failed for that name — the
 * rest of the batch still ran, this is NOT an all-or-nothing operation). */
export type SnapshotResumeResult = ApiResult<{
  results: { name: string; status: "started" | "already_running" | "failed"; error?: string }[];
  started: number;
  already_running: number;
  failed: number;
}>;
/** `_snapshot_list()` — metadata-only history, newest first (2026-09-21, see
 * `snapshot.py`'s module docstring for why this replaced the old single-record
 * `last_snapshot.json`). Each row's `saved_at` is what `apiSnapshotResume`'s
 * optional `savedAt` param targets to resume THAT specific past snapshot
 * instead of the newest one. */
export type SnapshotListResult = ApiResult<{
  snapshots: { saved_at: number; kind: "manual" | "closing"; count: number }[];
}>;
