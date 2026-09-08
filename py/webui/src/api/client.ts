/**
 * Fetch layer — `withToken()` + small `apiGet`/`apiPost` wrappers, plus one
 * typed function per backend route (4 non-WS GET routes, all 16 POST
 * routes). React rewrite plan (dynamic-crunching-lemon.md), Sequencing
 * step 5.
 *
 * Deliberately dumb/generic: no i18n here (see `./errors.ts` for turning a
 * caught `ApiError`/exception into the exact localized string the original
 * `web.py` JS would have `alert()`-ed — that needs `Strings`, which this
 * module has no business importing). Every route function below just
 * mirrors its Python handler's request/response shape 1:1 — this stage
 * only wires up the ones Running/Registered actually use
 * (start/stop/retire/close/handover/adopt/register/new-chat/open-window),
 * the rest (layout/diag/term-output/term-chat/term-input/term-key) exist
 * so a later stage can call them without touching this file, per the plan.
 */

import type { Lang } from "../i18n/strings";
import type {
  AdoptResult,
  ApiResult,
  DesktopStartResult,
  DesktopStopResult,
  DiagAskResult,
  DiagLogResult,
  DiagRestartResult,
  DiagSpawnTestResult,
  EditResult,
  FilesListResult,
  FilesReadResult,
  FilesValidateResult,
  GetHostsResult,
  HandoverResult,
  LayoutResult,
  NewChatResult,
  Settings,
  SettingsResult,
  SimpleResult,
  StartResult,
  StatusPayload,
  StopResult,
  TermChatResult,
  TermOutputResult,
} from "./types";

// Exported so `hooks/useStatus.ts` can build the `/ws?token=...` URL with the
// exact same token this page loaded with, without re-reading `location.search`
// a second time (and without `useStatus.ts` needing to know this reads from
// the query string at all — same module-load-time-constant shape as before).
export const TOKEN = new URLSearchParams(location.search).get("token") || "";

/** Same shape as the original PAGE_HTML JS's `withToken()` — append the
 * page's own `?token=` (read once at module load, same as `const TOKEN =
 * ...` used to be a page-load-time constant in the vanilla version). */
export function withToken(url: string): string {
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(TOKEN);
}

/** Thrown by `apiGet`/`apiPost` for a non-2xx/non-JSON response. Callers
 * that need the original's exact three alert-text variants (401 alone /
 * "request failed: " + unexpected-response text / "request failed: " +
 * raw network error) should route the catch through `describeApiError()`
 * in `./errors.ts` rather than reading `.message` directly. */
export class ApiError extends Error {
  status: number;
  constructor(status: number) {
    super(`http ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) throw new ApiError(401);
  const ctype = res.headers.get("content-type") || "";
  if (!res.ok || !ctype.includes("application/json")) throw new ApiError(res.status);
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(withToken(path));
  return handleResponse<T>(res);
}

export async function apiPost<T>(path: string, body: object): Promise<T> {
  const res = await fetch(withToken(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<T>(res);
}

// ── GET routes ───────────────────────────────────────────────────────────

export const getStatus = (): Promise<StatusPayload> => apiGet<StatusPayload>("/api/status");

export const getDiagLog = (): Promise<DiagLogResult> => apiGet<DiagLogResult>("/api/diag/log");

export const getHosts = (): Promise<GetHostsResult> => apiGet<GetHostsResult>("/api/hosts");

/** `host` omitted (or `"local"`) leaves the URL byte-identical to before
 * remote-terminal proxying existed — only appended when actually remote. */
function hostQS(host?: string): string {
  return host && host !== "local" ? `&host=${encodeURIComponent(host)}` : "";
}

export const getTermOutput = (name: string, lang: Lang, host?: string): Promise<TermOutputResult> =>
  apiGet<TermOutputResult>(`/api/term/output?name=${encodeURIComponent(name)}&lang=${lang}${hostQS(host)}`);

export const getTermChat = (
  name: string,
  lang: Lang,
  mode: "last" | "full" = "last",
  host?: string
): Promise<TermChatResult> =>
  apiGet<TermChatResult>(`/api/term/chat?name=${encodeURIComponent(name)}&lang=${lang}&mode=${mode}${hostQS(host)}`);

export const getFilesList = (name: string, lang: Lang, path?: string, host?: string): Promise<FilesListResult> =>
  apiGet<FilesListResult>(
    `/api/files/list?name=${encodeURIComponent(name)}&lang=${lang}` +
      (path ? `&path=${encodeURIComponent(path)}` : "") +
      hostQS(host)
  );

/** Not fetched via `apiGet`/JSON — a plain URL for an `<a href>` so the
 * browser's own download UI drives it (backend sends `Content-Disposition:
 * attachment`); no JS fetch+blob dance needed. */
export const filesDownloadUrl = (name: string, lang: Lang, path: string, host?: string): string =>
  withToken(
    `/api/files/download?name=${encodeURIComponent(name)}&lang=${lang}&path=${encodeURIComponent(path)}${hostQS(host)}`
  );

export const getFilesRead = (name: string, lang: Lang, path: string, host?: string): Promise<FilesReadResult> =>
  apiGet<FilesReadResult>(
    `/api/files/read?name=${encodeURIComponent(name)}&lang=${lang}&path=${encodeURIComponent(path)}${hostQS(host)}`
  );

export const postFilesValidate = (name: string, lang: Lang, paths: string[]): Promise<FilesValidateResult> =>
  apiPost<FilesValidateResult>("/api/files/validate", { name, lang, paths });

/** `path` omitted → opens the session's project root (whole project). Only
 * useful physically at the machine (or viewing it via Uzak Masaüstü) — VS
 * Code opens a real X11 window, not something this panel can display. */
export const apiVscodeOpen = (name: string, lang: Lang, path?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/vscode/open", { name, lang, ...(path ? { path } : {}) });

// ── POST routes ──────────────────────────────────────────────────────────
// Payload interfaces mirror each `do_POST` branch's `data.get(...)` reads
// in web.py exactly (field names, which ones are required vs. defaulted).

export interface StartPayload {
  name: string;
  /** Which registered host owns this session — `web_hosts`'s proxy-guard
   * routes non-local values to that host's own `/api/start` instead of
   * running it here. */
  host: string;
  model?: string;
  permission_mode?: string;
  effort?: string;
  fresh?: boolean;
  cli?: string;
  lang: Lang;
}
export const apiStart = (p: StartPayload): Promise<StartResult> => apiPost<StartResult>("/api/start", p);

/** Shared by every simple session-scoped action (stop/retire/reactivate/
 * close/handover/term-open-window) — all 6 are in `web_hosts.HOST_ROUTED_PATHS`,
 * so `host` is required here too, same reasoning as `StartPayload.host`. */
export interface NamePayload {
  name: string;
  host: string;
  lang: Lang;
}
export const apiStop = (p: NamePayload): Promise<StopResult> => apiPost<StopResult>("/api/stop", p);
export const apiRetire = (p: NamePayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/retire", p);
export const apiReactivate = (p: NamePayload): Promise<StartResult> => apiPost<StartResult>("/api/reactivate", p);
export const apiClose = (p: NamePayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/close", p);
export const apiHandover = (p: NamePayload): Promise<HandoverResult> => apiPost<HandoverResult>("/api/handover", p);
export const apiTermOpenWindow = (p: NamePayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/term/open-window", p);

export interface NewChatPayload {
  base: string;
  host: string;
  model?: string;
  permission_mode?: string;
  effort?: string;
  cli?: string;
  lang: Lang;
}
export const apiNewChat = (p: NewChatPayload): Promise<NewChatResult> => apiPost<NewChatResult>("/api/new-chat", p);

/** `host`: the TARGET host to register the new project on — `_register_project()`'s
 * `os.path.isdir(cwd)` check must run on that host's own filesystem, so this
 * needs host-routing exactly like the session-scoped payloads above even
 * though there's no pre-existing session yet. Optional (unlike the other
 * payloads here) purely because `RegisterForm.tsx`'s host `<select>` is a
 * separate, later phase (Faz 4) — omitted means local, matching the
 * backend's own "no host field = local" default, so today's form keeps
 * compiling/working untouched until that phase adds the selector. */
export interface RegisterPayload {
  name: string;
  host?: string;
  cwd: string;
  model?: string;
  cli?: string;
  lang: Lang;
}
export const apiRegister = (p: RegisterPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/register", p);

export interface EditPayload {
  name: string;
  host?: string;
  new_name: string;
  new_cwd: string;
  new_model?: string;
  new_cli?: string;
  lang: Lang;
}
export const apiEditProject = (p: EditPayload): Promise<EditResult> => apiPost<EditResult>("/api/edit", p);

export interface AdoptPayload {
  name: string;
  host: string;
  new_name?: string;
  model?: string;
  permission_mode?: string;
  effort?: string;
  lang: Lang;
}
export const apiAdopt = (p: AdoptPayload): Promise<AdoptResult> => apiPost<AdoptResult>("/api/adopt", p);

export interface TermInputPayload {
  name: string;
  host: string;
  text: string;
  lang: Lang;
}
export const apiTermInput = (p: TermInputPayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/term/input", p);

export interface TermKeyPayload {
  name: string;
  host: string;
  key: string;
  lang: Lang;
}
export const apiTermKey = (p: TermKeyPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/term/key", p);

/** Only "default" | "acceptEdits" | "plan" | "auto" are reachable — the CLI's
 * Shift+Tab cycle (its only live mode-switch mechanism, no direct slash
 * command exists) never includes "dontAsk", and "bypassPermissions" only
 * appears when a session was started with that flag already (not attempted
 * here, backend rejects it up front). Server does the actual polling/
 * cycling (may take a few seconds — up to ~8 keypresses), this is one call. */
export interface TermSetModePayload {
  name: string;
  host: string;
  mode: "default" | "acceptEdits" | "plan" | "auto";
  lang: Lang;
}
export type TermSetModeResult = ApiResult<{ mode?: string; presses?: number }>;
export const apiTermSetMode = (p: TermSetModePayload): Promise<TermSetModeResult> =>
  apiPost<TermSetModeResult>("/api/term/set-mode", p);

export interface LayoutPayload {
  pin?: string;
  groups?: string[];
  claude_only?: boolean;
  dry_run?: boolean;
  lang: Lang;
}
export const apiLayout = (p: LayoutPayload): Promise<LayoutResult> => apiPost<LayoutResult>("/api/layout", p);

export interface DiagAskPayload {
  cli: string;
  extra_question?: string;
  lang: Lang;
}
export const apiDiagSpawnTest = (lang: Lang): Promise<DiagSpawnTestResult> =>
  apiPost<DiagSpawnTestResult>("/api/diag/spawn-test", { lang });
export const apiDiagRestartGt = (lang: Lang): Promise<DiagRestartResult> =>
  apiPost<DiagRestartResult>("/api/diag/restart-gt", { lang });
export const apiDiagAsk = (p: DiagAskPayload): Promise<DiagAskResult> => apiPost<DiagAskResult>("/api/diag/ask", p);

export const apiDesktopStart = (lang: Lang): Promise<DesktopStartResult> =>
  apiPost<DesktopStartResult>("/api/desktop/start", { lang });
export const apiDesktopStop = (lang: Lang): Promise<DesktopStopResult> =>
  apiPost<DesktopStopResult>("/api/desktop/stop", { lang });

/** Partial patch — omitted keys are left untouched server-side (`settings.save_settings`'s merge). */
export type SettingsPayload = Partial<Settings> & { lang: Lang };
export const apiSaveSettings = (p: SettingsPayload): Promise<SettingsResult> =>
  apiPost<SettingsResult>("/api/settings", p);

/** Upsert (`hosts.save_host()`): empty `token` on an already-registered
 * `name` keeps that host's stored token — only send a non-empty token when
 * actually setting/changing one. */
export interface SaveHostPayload {
  name: string;
  base_url: string;
  token: string;
  lang: Lang;
}
export const apiSaveHost = (p: SaveHostPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/hosts", p);

export interface RemoveHostPayload {
  name: string;
  lang: Lang;
}
export const apiRemoveHost = (p: RemoveHostPayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/hosts/remove", p);
