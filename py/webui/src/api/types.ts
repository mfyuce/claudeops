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
  model: string;
  cwd: string;
  cli: string;
  running: boolean;
  pid: number | null;
  cpu: number | null;
  kind: "fresh" | "resume" | null;
  needs_ho: boolean | null;
  registered: boolean;
  tmux: boolean;
}

export interface RosterEntry {
  name: string;
  cwd: string;
  model: string;
  cli: string;
}

export interface CliOptions {
  models: string[];
  permission_modes: string[];
  effort_levels: string[];
}

export const EMPTY_CLI_OPTIONS: CliOptions = { models: [], permission_modes: [], effort_levels: [] };

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
  config_msg: string;
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
}

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
/** `_register_project()` / `_retire()` / `_close_project()` / `_term_input()` /
 * `_term_key()` / `_open_window()` — bare `{ok: true}` on success. */
export type SimpleResult = ApiResult;
/** `_handover()`. */
export type HandoverResult = ApiResult<{ kind?: string }>;

/** `_term_output()`. */
export type TermOutputResult = ApiResult<{ text: string; cols: number | null; rows: number | null }>;
/** `_term_chat()` — `supported: false` for CLIs without a chat transcript
 * (agy/shell today), `ok: false` is a real backend error (session gone etc). */
export type TermChatResult =
  | { ok: true; supported: false }
  | { ok: true; supported: true; user: string; assistant: string }
  | ApiErr;

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

/** `_run_layout()`. */
export type LayoutResult = ApiResult<{
  total: number;
  skipped: number;
  assignments: { name: string; ws: number; x: number; y: number }[];
  applied: boolean;
}>;
