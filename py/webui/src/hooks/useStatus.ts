/**
 * `GET /api/status` — WS-primary, HTTP-poll-fallback (React rewrite plan,
 * dynamic-crunching-lemon.md, Sequencing step 10; this hook was a plain 4s
 * `setInterval` poller through step 9 — see git history for that version).
 *
 * Design, per the plan's "WebSocket design" section:
 * - Connect to `/ws?token=...` (protocol switches `ws:`/`wss:` with
 *   `location.protocol` — the tunnel is `https:`, mixed content would
 *   otherwise silently block the connection).
 * - On message: `setData(parsed.data)` unconditionally. No client-side
 *   dedup/diff — React's reconciler already only touches what changed, so
 *   porting the old `comparableKey`/`LAST_JSON` client-side would be pure
 *   waste (the *server* still diffs, in `web_ws.py`, so most ticks with no
 *   real change never even reach here).
 * - On close/error: exponential backoff reconnect (~1s → cap ~20s,
 *   jittered) *plus* an independent slow (10-15s) background REST poll
 *   that runs the whole time, even while WS is nominally OPEN — a
 *   correctness backstop for a silently half-open TCP connection after a
 *   network transition (WS looks connected, no more frames ever arrive).
 * - `visibilitychange`: on foreground, reconnect immediately if not
 *   `OPEN`, and fire one immediate REST fetch regardless of WS state.
 *
 * Deliberately NOT done: an immediate REST fetch at mount. The original
 * (and the step-5..9 plain-poller version of this hook) fired one
 * immediately, but keeping that here would make the WS connect path
 * untestable from the outside (data would show up from the REST call
 * whether or not WS is doing anything) — see the plan's verification
 * checklist item "initial connect shows data without waiting for a
 * fallback poll tick". The backstop poll's first tick fires after
 * `POLL_BACKSTOP_MS`, same as every tick after it; WS (which dials
 * immediately on mount, and gets one immediate push back from the server
 * per-connection per `web_ws.py`) is what's expected to supply the first
 * paint in the overwhelmingly common case.
 *
 * External interface (`{data, error, loading, refresh}`) is unchanged from
 * the plain-poller version — no consumer (`StatusContext.tsx` or any
 * component reading `useStatusContext()`) needed to change for this
 * upgrade. `refresh()` keeps its original meaning (force one REST fetch
 * right now, out of band) rather than e.g. becoming a WS reconnect — it's
 * called by every mutating-action component right after a POST resolves,
 * and the server-side `notify_status_changed()` push (typically arriving
 * within the broadcaster's ~2s tick, often faster) makes it largely
 * redundant now, but it's a harmless, independent extra correctness path
 * for exactly the cases WS is weakest (e.g. a reconnect in flight right
 * when the action completes) — no concrete reason found to change or drop
 * it, so it stays.
 *
 * 2026-08-31 addition: every payload (WS or REST) carries `server_started_at`
 * (the serving process's start time — see `_status_payload()`). `applyData`
 * is the single choke point both delivery paths funnel through; it pins the
 * first value it sees per mount and hard-reloads the page if a later payload
 * reports a different one — i.e. the backend process restarted (a redeploy),
 * so any already-open tab picks up the new build without a manual refresh.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getStatus, wsAuthQS } from "../api/client";
import type { StatusPayload } from "../api/types";
import { openReconnectingWs } from "./wsReconnect";

/** Backstop REST poll — deliberately much slower than the old 4s poller,
 * since WS is primary now; this only needs to catch what WS misses. Plan:
 * "independent slow (10-15s) background fetch(...) poll". */
const POLL_BACKSTOP_MS = 12_000;

export type StatusError =
  | { kind: "network"; message: string }
  | { kind: "unauthorized" }
  | { kind: "unexpected"; status: number };

function toStatusError(err: unknown): StatusError {
  if (err instanceof ApiError) {
    if (err.status === 401) return { kind: "unauthorized" };
    return { kind: "unexpected", status: err.status };
  }
  return { kind: "network", message: err instanceof Error ? err.message : String(err) };
}

async function wsUrl(): Promise<string> {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  return `${scheme}${location.host}/ws?${await wsAuthQS()}`;
}

export interface UseStatusResult {
  data: StatusPayload | null;
  error: StatusError | null;
  loading: boolean;
  /** Force an out-of-band REST fetch right now, in addition to whatever
   * WS/backstop-poll traffic is already happening — see header comment. */
  refresh: () => void;
}

export function useStatus(): UseStatusResult {
  const [data, setData] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<StatusError | null>(null);
  const [loading, setLoading] = useState(true);

  // Mutable, doesn't need to trigger a re-render, and needs to be visible
  // to timer/socket callbacks scheduled outside React's render cycle.
  const aliveRef = useRef(true); // false after cleanup — guards every async/timer callback below
  const serverStartedAtRef = useRef<number | null>(null); // pinned to the first payload's value per mount

  // Single choke point for BOTH delivery paths (REST `doFetch` and WS
  // `onmessage`) — see header comment. Reload takes priority over updating
  // state: no point rendering a frame with a payload from the new process
  // when the page is about to reload anyway.
  const applyData = useCallback((d: StatusPayload) => {
    if (serverStartedAtRef.current === null) {
      serverStartedAtRef.current = d.server_started_at;
    } else if (d.server_started_at !== serverStartedAtRef.current) {
      window.location.reload();
      return;
    }
    setData(d);
    setError(null);
  }, []);

  const doFetch = useCallback(async () => {
    try {
      const d = await getStatus();
      if (!aliveRef.current) return;
      applyData(d);
    } catch (e) {
      if (!aliveRef.current) return;
      setError(toStatusError(e));
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, [applyData]);

  const refresh = useCallback(() => {
    void doFetch();
  }, [doFetch]);

  useEffect(() => {
    aliveRef.current = true;

    const closeWs = openReconnectingWs({
      url: wsUrl,
      onMessage: (frame) => {
        const parsed = frame as { type?: string; data?: StatusPayload } | null;
        if (!parsed || parsed.type !== "status" || !parsed.data) return;
        applyData(parsed.data);
        setLoading(false);
      },
      // The very first close of this mount (nothing has ever connected yet) gets one immediate REST probe alongside the
      // usual backoff reconnect, so a bad/missing token or WS being unreachable from page load surfaces its 401/error
      // near-instantly instead of sitting on the loading placeholder for up to POLL_BACKSTOP_MS.
      onFirstClose: () => void doFetch(),
      onForeground: () => void doFetch(), // per plan: one immediate REST fetch regardless of WS state
    });

    // Independent slow backstop poll — runs for the lifetime of the
    // component regardless of WS state (see header comment). First tick
    // fires after POLL_BACKSTOP_MS, not immediately — see header comment
    // on why an immediate mount-time fetch was deliberately dropped.
    const pollId = window.setInterval(() => void doFetch(), POLL_BACKSTOP_MS);

    return () => {
      aliveRef.current = false;
      window.clearInterval(pollId);
      closeWs();
    };
  }, [doFetch, applyData]);

  return { data, error, loading, refresh };
}
