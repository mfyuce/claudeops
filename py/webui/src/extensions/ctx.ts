/**
 * Extension UI context, version 1 (K10 `register_ui_extension`). The contract an extension bundle's
 * `mount(el, ctx)` receives. FROZEN: adding fields keeps `uiApiVersion` 1; removing a field or changing its
 * meaning means `uiApiVersion` 2 (the host then refuses bundles whose `uiApi` differs). Extensions get ONLY this
 * surface, never core components or state.
 */
import { TOKEN, withToken } from "../api/client";
import { showToast, type ToastKind } from "../state/toast";
import type { Lang } from "../i18n/strings";

export const UI_EXTENSION_API = 1;

/** Non-2xx response from an extension call: `status` + the server's `error` text (JSON body) when present. */
export class ExtApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ExtApiError";
    this.status = status;
  }
}

export interface ExtCtxV1 {
  uiApiVersion: 1;
  lang: Lang;
  apiGet<T = unknown>(path: string): Promise<T>;
  apiPost<T = unknown>(path: string, body: object): Promise<T>;
  toast(text: string, kind?: ToastKind): void;
  openSession(host: string, name: string): void;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  if (!path.startsWith("/api/") || path.includes("..")) throw new Error(`extension api path must start with /api/: ${path}`);
  const res = await fetch(withToken(path), {
    ...init,
    headers: { "X-Cops-Ext": "1", ...(init?.headers ?? {}) },
  });
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON body: handled below by status
  }
  if (!res.ok) {
    const msg = body && typeof body === "object" && "error" in body ? String((body as { error: unknown }).error) : `http ${res.status}`;
    throw new ExtApiError(res.status, msg);
  }
  return body as T;
}

export function makeExtCtx(opts: { lang: Lang; openSession: (host: string, name: string) => void }): ExtCtxV1 {
  void TOKEN;
  return {
    uiApiVersion: 1,
    lang: opts.lang,
    apiGet: <T,>(path: string) => call<T>(path),
    apiPost: <T,>(path: string, body: object) =>
      call<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    toast: (text, kind = "info") => showToast(text, kind),
    openSession: opts.openSession,
  };
}
