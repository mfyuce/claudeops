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
  DesktopStartResult,
  DesktopStopResult,
  DiagAskResult,
  DiagLogResult,
  DiagRestartResult,
  DiagSpawnTestResult,
  FilesListResult,
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

export const getTermOutput = (name: string, lang: Lang): Promise<TermOutputResult> =>
  apiGet<TermOutputResult>(`/api/term/output?name=${encodeURIComponent(name)}&lang=${lang}`);

export const getTermChat = (name: string, lang: Lang, mode: "last" | "full" = "last"): Promise<TermChatResult> =>
  apiGet<TermChatResult>(`/api/term/chat?name=${encodeURIComponent(name)}&lang=${lang}&mode=${mode}`);

export const getFilesList = (name: string, lang: Lang, path?: string): Promise<FilesListResult> =>
  apiGet<FilesListResult>(
    `/api/files/list?name=${encodeURIComponent(name)}&lang=${lang}` +
      (path ? `&path=${encodeURIComponent(path)}` : "")
  );

/** Not fetched via `apiGet`/JSON — a plain URL for an `<a href>` so the
 * browser's own download UI drives it (backend sends `Content-Disposition:
 * attachment`); no JS fetch+blob dance needed. */
export const filesDownloadUrl = (name: string, lang: Lang, path: string): string =>
  withToken(`/api/files/download?name=${encodeURIComponent(name)}&lang=${lang}&path=${encodeURIComponent(path)}`);

// ── POST routes ──────────────────────────────────────────────────────────
// Payload interfaces mirror each `do_POST` branch's `data.get(...)` reads
// in web.py exactly (field names, which ones are required vs. defaulted).

export interface StartPayload {
  name: string;
  model?: string;
  permission_mode?: string;
  effort?: string;
  fresh?: boolean;
  cli?: string;
  lang: Lang;
}
export const apiStart = (p: StartPayload): Promise<StartResult> => apiPost<StartResult>("/api/start", p);

export interface NamePayload {
  name: string;
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
  model?: string;
  permission_mode?: string;
  effort?: string;
  cli?: string;
  lang: Lang;
}
export const apiNewChat = (p: NewChatPayload): Promise<NewChatResult> => apiPost<NewChatResult>("/api/new-chat", p);

export interface RegisterPayload {
  name: string;
  cwd: string;
  model?: string;
  cli?: string;
  lang: Lang;
}
export const apiRegister = (p: RegisterPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/register", p);

export interface AdoptPayload {
  name: string;
  new_name?: string;
  model?: string;
  permission_mode?: string;
  effort?: string;
  lang: Lang;
}
export const apiAdopt = (p: AdoptPayload): Promise<AdoptResult> => apiPost<AdoptResult>("/api/adopt", p);

export interface TermInputPayload {
  name: string;
  text: string;
  lang: Lang;
}
export const apiTermInput = (p: TermInputPayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/term/input", p);

export interface TermKeyPayload {
  name: string;
  key: string;
  lang: Lang;
}
export const apiTermKey = (p: TermKeyPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/term/key", p);

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
