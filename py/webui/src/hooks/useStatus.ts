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
import { ApiError, getStatus, TOKEN } from "../api/client";
import type { StatusPayload } from "../api/types";

/** Backstop REST poll — deliberately much slower than the old 4s poller,
 * since WS is primary now; this only needs to catch what WS misses. Plan:
 * "independent slow (10-15s) background fetch(...) poll". */
const POLL_BACKSTOP_MS = 12_000;

const WS_RECONNECT_BASE_MS = 1_000;
const WS_RECONNECT_CAP_MS = 20_000;

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

function wsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  return `${scheme}${location.host}/ws?token=${encodeURIComponent(TOKEN)}`;
}

/** "Equal jitter" around an exponential-backoff delay: half fixed, half
 * random — `attempt` 0 → 0.5-1s, doubling each retry up to a 10-20s spread
 * once the exponential part saturates the cap (plan: "~1s → cap ~20s,
 * jittered"). Never near-zero (unlike "full jitter", `random(0, cap)`),
 * which matters here since the far more common case than a real outage is
 * a normal server-restart during a `npm run dev` / redeploy — a fixed
 * floor avoids every open tab hammering the not-yet-listening port in a
 * tight loop, while the random half still avoids every tab retrying in
 * lockstep once it does come back. */
function reconnectDelayMs(attempt: number): number {
  const exp = Math.min(WS_RECONNECT_CAP_MS, WS_RECONNECT_BASE_MS * 2 ** attempt);
  return exp / 2 + Math.random() * (exp / 2);
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
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
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

    function clearReconnectTimer() {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }

    function scheduleReconnect() {
      if (!aliveRef.current || reconnectTimerRef.current !== null) return;
      const delay = reconnectDelayMs(reconnectAttemptRef.current);
      reconnectAttemptRef.current += 1;
      // `connect` is a `function` declaration further down in this same
      // block — hoisted, so calling it here (textually above its
      // definition) is valid: `scheduleReconnect`/`connect` are mutually
      // recursive by design (that's the whole reconnect loop).
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    }

    function connect() {
      if (!aliveRef.current) return;
      // Already have a live/connecting socket — don't open a second one
      // (can happen if a foreground visibilitychange races a reconnect
      // timer that was about to fire anyway).
      const existing = wsRef.current;
      if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
        return;
      }
      let ws: WebSocket;
      try {
        ws = new WebSocket(wsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptRef.current = 0; // a fresh handshake succeeded — the network path works again
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        if (!aliveRef.current) return;
        let parsed: { type?: string; data?: StatusPayload };
        try {
          parsed = JSON.parse(ev.data) as { type?: string; data?: StatusPayload };
        } catch {
          return; // malformed frame — ignore rather than crash the UI
        }
        if (parsed.type !== "status" || !parsed.data) return;
        applyData(parsed.data);
        setLoading(false);
      };

      ws.onerror = () => {
        // No-op by design: a failed/dropped connection always also fires
        // `onclose` right after (per the WebSocket spec), which is the
        // single place reconnect is scheduled — scheduling from both would
        // double-schedule.
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (!aliveRef.current) return;
        // The very first close of this mount (nothing has ever connected
        // yet, reconnectAttemptRef is still at its initial 0) gets one
        // immediate REST probe alongside the usual backoff reconnect. Not
        // needed for the ongoing-outage case (the 12s backstop poll already
        // covers that per the header comment) -- this is specifically so a
        // bad/missing token, or WS being categorically unreachable (e.g. a
        // proxy stripping Upgrade) from the very start of a page load,
        // surfaces its 401/error near-instantly instead of silently sitting
        // on the loading placeholder for up to POLL_BACKSTOP_MS.
        if (reconnectAttemptRef.current === 0) void doFetch();
        scheduleReconnect();
      };
    }

    connect();

    // Independent slow backstop poll — runs for the lifetime of the
    // component regardless of WS state (see header comment). First tick
    // fires after POLL_BACKSTOP_MS, not immediately — see header comment
    // on why an immediate mount-time fetch was deliberately dropped.
    const pollId = window.setInterval(() => void doFetch(), POLL_BACKSTOP_MS);

    function onVisibilityChange() {
      if (document.visibilityState !== "visible") return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reconnectAttemptRef.current = 0; // foregrounding is a strong signal the network may have changed — try promptly
        clearReconnectTimer();
        connect();
      }
      void doFetch(); // per plan: fire one immediate REST fetch regardless of WS state
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      aliveRef.current = false;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.clearInterval(pollId);
      clearReconnectTimer();
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
      }
    };
  }, [doFetch, applyData]);

  return { data, error, loading, refresh };
}
