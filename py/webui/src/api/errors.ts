/**
 * Turns a caught exception from `apiGet`/`apiPost` into the exact alert
 * text the original `web.py` JS produced, plus the generic "fire an
 * action, alert() on failure" loop shared by several call sites
 * (`doAction`'s non-newchat branch, `doReactivate`, `doOpenWindow` in the
 * original — all three went through the same `call()` helper).
 *
 * The original's three message shapes, reproduced exactly here:
 *  - `r.status === 401`: bare `t('authErrorShort')`, no prefix — handled by
 *    an early explicit branch in `call()`/`doAdopt()`/`doRegister()`
 *    BEFORE `safeJson()` is even called, so it never goes through the
 *    generic catch.
 *  - non-ok / non-JSON response: `safeJson()` throws
 *    `new Error(t('unexpectedResponse')(status))`, which propagates to the
 *    caller's outer `catch (e) { alert(t('requestFailed') + e.message) }`
 *    — i.e. the composed text is `requestFailed` PREFIXED onto
 *    `unexpectedResponse(status)` (double-wrapped, verified by reading
 *    both `safeJson()` and every one of its callers in web.py).
 *  - a genuine network/fetch exception: same outer catch, `e.message` is
 *    the raw browser error text (e.g. "Failed to fetch").
 */

import { ApiError } from "./client";
import type { Strings } from "../i18n/strings";

export function describeApiError(err: unknown, t: Strings): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return t.authErrorShort;
    return t.requestFailed + t.unexpectedResponse(err.status);
  }
  const message = err instanceof Error ? err.message : String(err);
  return t.requestFailed + message;
}

/**
 * Replaces the original's `call(action, payload)`. Fires `fn`, and on a
 * result with `ok: false` either hands the message to `onFailure` (used
 * for the `/api/start` route only, whose failure path offers to switch to
 * the Diagnostics tab — see `runDiagAfterFailure` in web.py) or falls back
 * to a plain `alert()` (every other action). A thrown exception always
 * alerts via `describeApiError`, matching the original's shared `catch`.
 */
export async function callAction<T extends { ok: boolean; error?: string }>(
  fn: () => Promise<T>,
  name: string,
  t: Strings,
  onFailure?: (message: string) => void,
): Promise<void> {
  try {
    const res = await fn();
    if (!res.ok) {
      const msg = `${name}: ${res.error ?? ""}`;
      if (onFailure) onFailure(msg);
      else window.alert(msg);
    }
  } catch (e) {
    window.alert(describeApiError(e, t));
  }
}
