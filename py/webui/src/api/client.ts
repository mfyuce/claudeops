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
  ContextResult,
  GetCliStatusResult,
  DesktopStartResult,
  DesktopStopResult,
  DiagAskResult,
  DiagLogResult,
  DiagRestartResult,
  DiagSpawnTestResult,
  EditResult,
  FilesDeleteResult,
  FilesListResult,
  FilesMkdirResult,
  FilesReadResult,
  FilesRenameResult,
  FilesUploadResult,
  FilesValidateResult,
  FilesWriteResult,
  GetHostsResult,
  GetOrchRunResult,
  GetOrchRunsResult,
  HandoverResult,
  InstancesResult,
  LayoutResult,
  LiveEffortResult,
  LiveModelResult,
  NewChatResult,
  OrchDraftParticipant,
  OrchStartResult,
  Settings,
  SettingsResult,
  MirrorWindowResult,
  SimpleResult,
  SnapshotListResult,
  SnapshotResumeResult,
  SnapshotSaveResult,
  StartResult,
  StatusPayload,
  StewardAnswerResult,
  StewardAskResult,
  StewardListResult,
  StewardStateResult,
  StewardDigestsResult,
  StewardDigestFileResult,
  StewardTickResult,
  StopResult,
  IoAskResult,
  IoHistoryResult,
  ReviewChatResult,
  ReviewRun,
  IoProvidersResult,
  IoSessionsResult,
  TermChatResult,
  TermOutputResult,
  UsageResult,
  TestHostResult,
  ReviewStateResult,
  ReviewFinding,
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

export const getInstances = (lang: Lang, host?: string): Promise<InstancesResult> =>
  apiGet<InstancesResult>(`/api/instances?lang=${lang}${hostQS(host)}`);

/** `lite` asks for visible rows only (+ server-extracted URL/path lists); without it the
 * response is the full scrollback capture (used by the terminal's on-demand history load and
 * "copy"). */
export const getTermOutput = (name: string, lang: Lang, host?: string, lite = false): Promise<TermOutputResult> =>
  apiGet<TermOutputResult>(
    `/api/term/output?name=${encodeURIComponent(name)}&lang=${lang}${hostQS(host)}${lite ? "&lite=1" : ""}`,
  );

/** `since` (2026-09-17): how many messages the caller already has, for
 * `mode="full"`'s incremental fetch — see `_term_chat()`'s own comment.
 * Omitted (or 0) for `mode="last"`, which has nothing to accumulate. */
export const getTermChat = (
  name: string,
  lang: Lang,
  mode: "last" | "full" = "last",
  host?: string,
  since?: number
): Promise<TermChatResult> =>
  apiGet<TermChatResult>(
    `/api/term/chat?name=${encodeURIComponent(name)}&lang=${lang}&mode=${mode}${hostQS(host)}${since ? `&since=${since}` : ""}`
  );

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

/** `/api/files/upload` — unlike every other write route, the body is the
 * raw file bytes, not JSON (no multipart/base64 wrapper either — cheapest
 * possible transfer, see `files.py`/`_handle_files_upload`'s docstrings for
 * why), so this bypasses `apiPost` entirely and uses `XMLHttpRequest`
 * (not `fetch`) purely for `upload.onprogress` — the one write path where a
 * caller actually wants live progress for a potentially large/slow
 * transfer. `dirPath` omitted uploads into the session's first root. */
export function apiFilesUpload(
  name: string,
  lang: Lang,
  dirPath: string | undefined,
  file: File,
  opts: { host?: string; overwrite?: boolean; onProgress?: (fraction: number) => void } = {}
): Promise<FilesUploadResult> {
  const qs =
    `name=${encodeURIComponent(name)}&lang=${lang}&filename=${encodeURIComponent(file.name)}` +
    (dirPath ? `&path=${encodeURIComponent(dirPath)}` : "") +
    (opts.overwrite ? "&overwrite=1" : "") +
    hostQS(opts.host);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", withToken(`/api/files/upload?${qs}`));
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    if (opts.onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) opts.onProgress!(e.loaded / e.total);
      };
    }
    xhr.onerror = () => reject(new ApiError(0));
    xhr.onload = () => {
      if (xhr.status === 401) {
        reject(new ApiError(401));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as FilesUploadResult);
      } catch {
        reject(new ApiError(xhr.status));
      }
    };
    xhr.send(file);
  });
}

/** `/api/files/delete` — files AND directories (recursive). No undo/trash;
 * `FilesView.tsx` gets a `window.confirm` before calling this. */
export const apiFilesDelete = (name: string, lang: Lang, path: string, host?: string): Promise<FilesDeleteResult> =>
  apiPost<FilesDeleteResult>("/api/files/delete", { name, lang, path, host: host || "local" });

/** `/api/files/rename` — same-directory rename only (not a cross-directory
 * move), `newName` is stripped to its basename server-side regardless. */
export const apiFilesRename = (
  name: string,
  lang: Lang,
  path: string,
  newName: string,
  host?: string
): Promise<FilesRenameResult> =>
  apiPost<FilesRenameResult>("/api/files/rename", { name, lang, path, new_name: newName, host: host || "local" });

/** `/api/files/mkdir` — `dirPath` omitted creates inside the session's
 * first root. */
export const apiFilesMkdir = (
  name: string,
  lang: Lang,
  dirPath: string | undefined,
  folderName: string,
  host?: string
): Promise<FilesMkdirResult> =>
  apiPost<FilesMkdirResult>("/api/files/mkdir", {
    name, lang, folder_name: folderName, host: host || "local", ...(dirPath ? { path: dirPath } : {}),
  });

/** `/api/files/write` — overwrites an EXISTING file's content (no create,
 * that's `apiFilesUpload`'s job); same-size cap as `getFilesRead`
 * (`MAX_VIEW_BYTES`, server-enforced either way). */
export const apiFilesWrite = (
  name: string,
  lang: Lang,
  path: string,
  content: string,
  host?: string
): Promise<FilesWriteResult> =>
  apiPost<FilesWriteResult>("/api/files/write", { name, lang, path, content, host: host || "local" });

/** `path` omitted → opens the session's project root (whole project). Only
 * useful physically at the machine (or viewing it via Uzak Masaüstü) — VS
 * Code opens a real X11 window, not something this panel can display. */
export const apiVscodeOpen = (name: string, lang: Lang, path?: string, host?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/vscode/open", { name, lang, host: host || "local", ...(path ? { path } : {}) });

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
/** Opens a live read-only `cops watch` window for a REMOTE session on THIS machine's desktop. Unlike
 * `apiTermOpenWindow` this route is LOCAL-only (NOT in `web_hosts.HOST_ROUTED_PATHS`): `host` here is
 * the session's host, not a routing target — routing it would open the window on the remote desktop. */
export const apiTermMirrorWindow = (p: NamePayload): Promise<MirrorWindowResult> =>
  apiPost<MirrorWindowResult>("/api/term/mirror-window", p);
/** Hides the instance from History (its name stays reserved); conversation files are untouched. */
export const apiForgetInstance = (p: NamePayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/instances/forget", p);

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

/** Live typing (Terminal view's opt-in "type straight into the black area"
 * mode): xterm's own `onData` stream — single keystrokes, control sequences
 * (`\x1b[A`, `\x03`), a pasted block — forwarded to the pane VERBATIM.
 * Unlike `apiTermInput` it appends NO Enter (Enter arrives as `\r` in the
 * data itself), and unlike `apiTermKey` it isn't limited to a fixed key
 * list. The backend caps one call at 8192 chars (`MAX_TERM_RAW_CHARS`) —
 * `TerminalView` slices its own buffer to the same size, so a big paste
 * goes out as several ordered calls rather than one rejected one. */
export interface TermRawPayload {
  name: string;
  host: string;
  data: string;
  lang: Lang;
}
export const apiTermRaw = (p: TermRawPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/term/raw", p);

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

export const getIoProviders = (): Promise<IoProvidersResult> => apiGet<IoProvidersResult>("/api/io/providers");

export const getIoSessions = (provider: string, cwd: string): Promise<IoSessionsResult> =>
  apiGet<IoSessionsResult>(`/api/io/sessions?provider=${encodeURIComponent(provider)}&cwd=${encodeURIComponent(cwd)}`);

export const getIoHistory = (provider: string, cwd: string, session: string): Promise<IoHistoryResult> =>
  apiGet<IoHistoryResult>(
    `/api/io/history?provider=${encodeURIComponent(provider)}&cwd=${encodeURIComponent(cwd)}&session=${encodeURIComponent(session)}`,
  );

export interface IoAskPayload {
  provider: string;
  cwd: string;
  session: string;
  prompt: string;
  fields: Record<string, string>;
}
export const apiIoAsk = (p: IoAskPayload): Promise<IoAskResult> => apiPost<IoAskResult>("/api/io/ask", p);

export const apiDesktopStart = (lang: Lang): Promise<DesktopStartResult> =>
  apiPost<DesktopStartResult>("/api/desktop/start", { lang });
export const apiDesktopStop = (lang: Lang): Promise<DesktopStopResult> =>
  apiPost<DesktopStopResult>("/api/desktop/stop", { lang });

/** Partial patch — omitted keys are left untouched server-side (`settings.save_settings`'s merge).
 * `byok` is Omit+re-added rather than inherited from `Settings`: that type's `byok` is the
 * READ shape (redacted to booleans, `has_token`-style, never the real value — see `Settings.byok`'s
 * own comment) while a save sends the REAL string value to set. Same field name, deliberately
 * different shape for write vs. read, like `HostRecord.token` (write) vs. `has_token` (read). */
export type SettingsPayload = Omit<Partial<Settings>, "byok"> & {
  lang: Lang;
  byok?: Record<string, Record<string, string>>;
};
export const apiSaveSettings = (p: SettingsPayload): Promise<SettingsResult> =>
  apiPost<SettingsResult>("/api/settings", p);

/** Her çağrı, provider başına GERÇEKTEN ÇALIŞAN bir session'a `/usage`
 * enjekte eder (bkz. `web.py`'nin `_usage_all()` docstring'i) — bu yüzden
 * SettingsTab'ın Kullanım sekmesi bunu bir poll DEĞİL, kullanıcının bastığı
 * bir "Kontrol et" butonuyla çağırır (`onDemand`, otomatik interval YOK). */
export const apiUsage = (lang: Lang): Promise<UsageResult> => apiPost<UsageResult>("/api/usage", { lang });

/** `/api/usage`'ın aksine İSİM gerekir — TEK, o an Terminal'de açık olan
 * session'ın kendi context-window'u (`_context()`, `/context` enjekte eder).
 * Aynı "poll değil, buton" gerekçesi: her çağrı gerçekten o session'a
 * yazıyor. `host` bugün YOK SAYILIYOR (`/api/usage` gibi `/api/context` da
 * 2026-10-06'da `web_hosts.HOST_ROUTED_PATHS`'e eklendi, `host` artık uzak
 * bir host'un Terminal'inde de doğru çalışıyor (önceki not bayattı). */
export const apiContext = (p: NamePayload): Promise<ContextResult> => apiPost<ContextResult>("/api/context", p);

/** `_live_model()`'in aksine (bkz. `LiveModelResult`) enjeksiyon YOK, salt
 * dosya okuma — bu yüzden `apiContext`'in "poll değil buton" gerekçesi
 * burada GEÇERSİZ, `TerminalView` bunu mount'ta (ve session değişince)
 * kendiliğinden çağırır. `host` 2026-10-08'e kadar BURADA DA yok sayılıyordu
 * (`HOST_ROUTED_PATHS`'te değildi, `/api/context`'in 2026-10-06 öncesi AYNI
 * boşluğu) — artık host-routed, uzak session'larda da canlı değeri okur. */
export const apiLiveModel = (p: NamePayload): Promise<LiveModelResult> => apiPost<LiveModelResult>("/api/live-model", p);

/** `apiLiveModel`'in effort karşılığı, bkz. `LiveEffortResult`. */
export const apiLiveEffort = (p: NamePayload): Promise<LiveEffortResult> => apiPost<LiveEffortResult>("/api/live-effort", p);

/** Upsert (`hosts.save_host()`): empty `token` on an already-registered
 * `name` keeps that host's stored token — only send a non-empty token when
 * actually setting/changing one. */
export interface SaveHostPayload {
  name: string;
  base_url: string;
  token: string;
  /** Comma/newline-separated fallback URLs (`hosts.save_host()`'s `extra_urls`
   * param) — like `grpc_url`, empty clears it rather than preserving. */
  extra_urls?: string;
  lang: Lang;
}
export const apiSaveHost = (p: SaveHostPayload): Promise<SimpleResult> => apiPost<SimpleResult>("/api/hosts", p);

/** `cli_install.py` — per-backend (claude/codex/copilot/agy) install status +
 * one-shot install action. Synchronous like `/api/hosts/test`: `npm install`
 * usually takes a few seconds, no job/polling layer for this. Host-routed
 * (`web_hosts.GET_HOST_ROUTED_PATHS`/`HOST_ROUTED_PATHS`) — omit `host` (or
 * pass "local") for this machine, or a registered host name to install
 * there instead; the remote host runs the exact same `cli_install.py`
 * locally, no shell/SSH involved. */
export const getCliStatus = (host: string, lang: Lang): Promise<GetCliStatusResult> =>
  apiGet<GetCliStatusResult>(`/api/cli/status?host=${encodeURIComponent(host)}&lang=${lang}`);
export interface InstallCliPayload {
  cli: string;
  host: string;
  lang: Lang;
}
export const apiInstallCli = (p: InstallCliPayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/cli/install", p);

export interface RemoveHostPayload {
  name: string;
  lang: Lang;
}
export const apiRemoveHost = (p: RemoveHostPayload): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/hosts/remove", p);

export interface TestHostPayload {
  name: string;
  lang: Lang;
}
export const apiTestHost = (p: TestHostPayload): Promise<TestHostResult> =>
  apiPost<TestHostResult>("/api/hosts/test", p);

// ── TOBEDECIDED#15 Phase 1 — workers-only orchestration ─────────────────
// Local-only (no `host`-routing, no `lang` — `web_orch.http_{start,cancel,
// draft}()` never read a `lang` field, unlike every other POST route above;
// this frontend doesn't send one they'd ignore). Errors these routes return
// are raw, permanently-English backend text (same principle as `_v1_error`,
// see `orchestration.py`'s own docstring) — shown via `t.requestFailed`
// like any other un-processed backend string, never looked up in `Strings`.

export const getOrchRuns = (): Promise<GetOrchRunsResult> => apiGet<GetOrchRunsResult>("/api/orch/runs");
export const getOrchRun = (runId: string): Promise<GetOrchRunResult> =>
  apiGet<GetOrchRunResult>(`/api/orch/run?id=${encodeURIComponent(runId)}`);

export interface OrchStartParticipant {
  role: string;
  host: string;
  name: string;
}
export interface OrchStartPayload {
  participants: OrchStartParticipant[];
  task: string;
  verdict_hint?: string;
  worker_timeout: number;
}
export const apiOrchStart = (p: OrchStartPayload): Promise<OrchStartResult> =>
  apiPost<OrchStartResult>("/api/orch/start", p);

export const apiOrchCancel = (runId: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/orch/cancel", { run_id: runId });

export const apiOrchSaveDraft = (participants: OrchDraftParticipant[]): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/orch/draft", { participants });

/** `_snapshot_save()` — o an çalışan TÜM session'ları (`name`/`cwd`/GERÇEK
 * canlı `model`/`permission_mode`/`effort`/`cli`) snapshot GEÇMİŞİNE yeni bir
 * "manual" girdi olarak ekler (`snapshots.json`, bkz. `snapshot.py`). Sonucun
 * `count`/`saved_at`'i ANINDA gelir — güncel `snapshot` alanı ayrıca
 * `_json_notify`'ın tetiklediği bir sonraki `/api/status` push'uyla da
 * yenilenir. */
export const apiSnapshotSave = (lang: Lang): Promise<SnapshotSaveResult> =>
  apiPost<SnapshotSaveResult>("/api/snapshot/save", { lang });

/** `_snapshot_list()` — 2026-09-21, geçmişteki TÜM kayıtların meta'sı (en yeni
 * önce) — `SnapshotHistory`'nin liste görünümü için. */
export const apiSnapshotList = (lang: Lang): Promise<SnapshotListResult> =>
  apiPost<SnapshotListResult>("/api/snapshot/list", { lang });

/** `_snapshot_resume()` — kaydedilmiş bir snapshot'taki (varsayılan: EN SON
 * kayıt; `savedAt` verilirse geçmişten O belirli kayıt, `SnapshotHistory`'nin
 * satır bazlı "geri yükle" düğmesi için) her ismi (zaten çalışmıyorsa) kayıt
 * ANINDAKİ gerçek parametreleriyle geri açar. `hidden=true` → pencere
 * AÇMADAN tmux-arkaplanda başlatır (sonradan normal "pencere aç" ile telafi
 * edilebilir); varsayılan `false` = pencereler açık (kullanıcı: "pencereler
 * açılsın default ama istenirse gizli açılsın"). */
export const apiSnapshotResume = (hidden: boolean, lang: Lang, savedAt?: number): Promise<SnapshotResumeResult> =>
  apiPost<SnapshotResumeResult>("/api/snapshot/resume", { hidden, lang, ...(savedAt !== undefined ? { saved_at: savedAt } : {}) });

// ── Değnekçi (steward) — `/api/steward/*`, local-only like `/api/orch/*` ──
/** Selected steward identity -> request field. `default`/empty adds NOTHING (URLs and bodies stay as before P7). */
const stewardQs = (sid?: string): string => (sid && sid !== "default" ? `?steward=${encodeURIComponent(sid)}` : "");
const stewardBody = (sid?: string): { steward?: string } => (sid && sid !== "default" ? { steward: sid } : {});

export const getStewardList = (): Promise<StewardListResult> => apiGet<StewardListResult>("/api/steward/list");
export const getStewardState = (sid?: string): Promise<StewardStateResult> =>
  apiGet<StewardStateResult>(`/api/steward/state${stewardQs(sid)}`);
export const getStewardDigests = (sid?: string): Promise<StewardDigestsResult> =>
  apiGet<StewardDigestsResult>(`/api/steward/digests${stewardQs(sid)}`);
export const getStewardDigestFile = (kind: "daily" | "tours", name: string, sid?: string): Promise<StewardDigestFileResult> =>
  apiGet<StewardDigestFileResult>(
    `/api/steward/digest/file?kind=${kind}&name=${encodeURIComponent(name)}${sid && sid !== "default" ? `&steward=${encodeURIComponent(sid)}` : ""}`,
  );
/** `answer` may be an option number ("2"), an option text or free text — the backend resolves it. */
export const apiStewardAnswer = (id: string, answer: string, sid?: string): Promise<StewardAnswerResult> =>
  apiPost<StewardAnswerResult>("/api/steward/answer", { id, answer, ...stewardBody(sid) });
export const apiStewardAsk = (project: string, text: string, options: string[], sid?: string): Promise<StewardAskResult> =>
  apiPost<StewardAskResult>("/api/steward/ask", { project, text, options, source: "panel", ...stewardBody(sid) });
export const apiStewardIdea = (text: string, sid?: string): Promise<SimpleResult & { id?: string }> =>
  apiPost<SimpleResult & { id?: string }>("/api/steward/idea", { text, source: "panel", ...stewardBody(sid) });
export const apiStewardIdeaUpdate = (id: string, status: string, sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/idea", { id, status, ...stewardBody(sid) });
export const apiStewardIdeaExport = (id: string, kind: "todo" | "tbd", target: "project" | "all", sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/idea/export", { id, kind, target, ...stewardBody(sid) });
export const apiStewardTick = (sid?: string): Promise<StewardTickResult> =>
  apiPost<StewardTickResult>("/api/steward/tick", { ...stewardBody(sid) });
export const apiStewardEnable = (enabled: boolean, sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/enable", { enabled, ...stewardBody(sid) });
export const apiStewardConfig = (key: string, value: string | number, sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/config", { key, value, ...stewardBody(sid) });
export const apiStewardUp = (sid?: string): Promise<SimpleResult & { restored?: string[] }> =>
  apiPost<SimpleResult & { restored?: string[] }>("/api/steward/up", { ...stewardBody(sid) });
export const apiStewardBrain = (action: "start" | "stop", sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/brain", { action, ...stewardBody(sid) });
export const apiStewardTour = (sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/tour", { ...stewardBody(sid) });
export const apiStewardShutdown = (sid?: string, keep: string[] = [], only: string[] = []): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/shutdown", {
    ...(only.length ? { only } : {}),
    ...(keep.length ? { modes: Object.fromEntries(keep.map((n) => [n, "keep"])) } : {}),
    ...stewardBody(sid),
  });
export const apiStewardIdentityCreate = (target: string, label = "", role = "steward"): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/identity/create", { target, label, ...(role !== "steward" ? { role } : {}) });
export const apiStewardIdentityRemove = (target: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/identity/remove", { target });
export const apiStewardIdentityTransfer = (project: string, to: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/identity/transfer", { project, to });
export interface StewardServiceRow {
  name: string; url: string; match: string; label: string; token_file: string;
  token_present: boolean; token_warning: string; open_jobs: number; default: boolean;
}
export interface StewardJobRow {
  id: string | number; service: string; project?: string; kind?: string; state?: string; created_at?: number;
  delivered?: boolean; result_summary?: string; approval_state?: string; error?: string; open: boolean; note?: string;
}
export const getStewardServices = (): Promise<SimpleResult & { services?: StewardServiceRow[] }> =>
  apiGet<SimpleResult & { services?: StewardServiceRow[] }>("/api/steward/services");
export const getStewardJobs = (sid?: string, state = "all", refresh = false): Promise<SimpleResult & { jobs?: StewardJobRow[] }> =>
  apiGet<SimpleResult & { jobs?: StewardJobRow[] }>(
    `/api/steward/jobs?state=${encodeURIComponent(state)}${refresh ? "&refresh=1" : ""}${sid && sid !== "default" ? `&steward=${encodeURIComponent(sid)}` : ""}`,
  );
export const getStewardJobKinds = (sid?: string): Promise<SimpleResult & { kinds?: unknown }> =>
  apiGet<SimpleResult & { kinds?: unknown }>(`/api/steward/jobs?kinds=1${sid && sid !== "default" ? `&steward=${encodeURIComponent(sid)}` : ""}`);
export const apiStewardServiceAdd = (name: string, url: string, token_file: string, match: string): Promise<SimpleResult & { warning?: string }> =>
  apiPost<SimpleResult & { warning?: string }>("/api/steward/service/add", { name, url, token_file, match });
export const apiStewardServiceRm = (name: string): Promise<SimpleResult> => apiPost<SimpleResult>("/api/steward/service/rm", { name });
export const apiStewardJobAck = (id: string | number, service: string, sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/job/ack", { id, service, ...stewardBody(sid) });
export const apiStewardJobSubmit = (
  body: { project: string; kind: string; files: string[]; params: Record<string, unknown>; spec_text: string },
  sid?: string,
): Promise<SimpleResult & { awaiting_approval?: boolean }> =>
  apiPost<SimpleResult & { awaiting_approval?: boolean }>("/api/steward/job/submit", { ...body, ...stewardBody(sid) });
export const getStewardLog = (n = 80, sid?: string): Promise<SimpleResult & { entries?: Array<Record<string, unknown>> }> =>
  apiGet<SimpleResult & { entries?: Array<Record<string, unknown>> }>(`/api/steward/log?n=${n}${sid && sid !== "default" ? `&steward=${encodeURIComponent(sid)}` : ""}`);
export const apiStewardProjectAction = (
  action: "directive" | "handover" | "stop" | "restart",
  name: string,
  text: string,
  sid?: string,
): Promise<SimpleResult> =>
  apiPost<SimpleResult>(`/api/steward/${action}`, { name, text, reason: "panel", ...stewardBody(sid) });
export const apiStewardProjectSet = (name: string, fields: Record<string, string | number>, sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/project", { name, ...fields, ...stewardBody(sid) });
export const apiStewardProjectRemove = (name: string, sid?: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/project/remove", { name, ...stewardBody(sid) });


// ── Reviewer ──
const rvQs = (sid: string, extra: Record<string, string> = {}): string => {
  const q = new URLSearchParams({ steward: sid });
  for (const [k, v] of Object.entries(extra)) if (v) q.set(k, v);
  return `?${q.toString()}`;
};
export const getReviewState = (sid: string): Promise<ReviewStateResult> =>
  apiGet<ReviewStateResult>(`/api/steward/review/state${rvQs(sid)}`);
export const getReviewFile = (sid: string, path: string): Promise<SimpleResult & { path?: string; text?: string; truncated?: boolean }> =>
  apiGet<SimpleResult & { path?: string; text?: string; truncated?: boolean }>(`/api/steward/review/file${rvQs(sid, { path })}`);
export const getReviewRuns = (): Promise<{ ok: boolean; error?: string; runs?: ReviewRun[] }> =>
  apiGet<{ ok: boolean; error?: string; runs?: ReviewRun[] }>("/api/steward/review/runs");
export const getReviewChat = (sid: string, path: string): Promise<ReviewChatResult> =>
  apiGet<ReviewChatResult>(`/api/steward/review/chat${rvQs(sid, { path })}`);
export const getReviewFindings = (sid: string, project = "", state = ""): Promise<SimpleResult & { findings?: ReviewFinding[] }> =>
  apiGet<SimpleResult & { findings?: ReviewFinding[] }>(`/api/steward/review/findings${rvQs(sid, { project, state })}`);
export const apiReviewPool = (sid: string, action: "add" | "remove" | "enable" | "disable", project: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/pool", { steward: sid, action, project });
export const apiReviewWhere = (sid: string, project: string, where: string, local_path = ""): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/where", { steward: sid, project, where, local_path });
export const apiReviewRun = (sid: string, project: string, mode: string, model: string): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/run", { steward: sid, project, mode, model });
export const apiReviewCancel = (sid: string, project = ""): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/cancel", { steward: sid, project });
export const apiReviewVerify = (sid: string, project: string, fids: string[]): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/verify", { steward: sid, project, fids });
export const apiReviewFinding = (sid: string, id: string, action: "approve" | "reject"): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/finding", { steward: sid, id, action });
export const apiReviewExport = (sid: string, project: string, kind: "todo" | "tbd"): Promise<SimpleResult> =>
  apiPost<SimpleResult>("/api/steward/review/export", { steward: sid, project, kind });
