/**
 * `GET /api/term/output` — WS-primary (`/ws/term`), HTTP-poll-fallback.
 * Same overall design as `useStatus.ts` (see that file's header comment for
 * the full WS/backstop/reconnect rationale, shared here via
 * `./wsReconnect`), with one deliberate difference: `host` is NOT branched
 * client-side. `/ws/term` is always used regardless of host — the browser's
 * WS endpoint is always the LOCAL panel; when `host` is remote, the
 * backend's `/ws/term` handler internally polls `web_hosts.proxy_get()` on
 * its own server-side loop and pushes the result over that SAME WS (see
 * `web.py`'s `/ws/term` route + `web_ws.handle_ws_term`/`_term_poll_loop`).
 * So a remote session gets the same round-trip-free push a local one does,
 * even though the local↔remote hop underneath is still plain REST
 * (`web_hosts.py` has no WS-upgrade proxying, and doesn't need one for
 * this — the tunnel hop that actually hurt, browser↔local, is the one this
 * fixes).
 *
 * Backstop cadence (3s) is faster than `useStatus.ts`'s 12s — a terminal is
 * actively watched/typed into, not a background dashboard, so a stuck
 * half-open connection needs to self-heal faster. Still ~15x slower than
 * the old 200ms client poll, so it stays a backstop, not a second primary.
 *
 * Unlike `useStatus.ts`, this hook does its own blip-tolerance-free
 * delivery: it just hands `TerminalView.tsx` whatever the latest result is
 * (WS message or backstop tick, whichever landed last) and lets the view
 * decide how many consecutive `ok:false` results to tolerate before
 * treating it as a real error (`CONSECUTIVE_FAILURES_BEFORE_ERROR`,
 * unchanged from the pre-WS version) — same separation as before, just
 * fed by a different transport.
 */
import { useEffect, useRef, useState } from "react";
import { getTermOutput, TOKEN } from "../api/client";
import type { Lang } from "../i18n/strings";
import type { TermOutputResult } from "../api/types";
import { reconnectDelayMs } from "./wsReconnect";

const POLL_BACKSTOP_MS = 3_000;

function wsTermUrl(name: string, lang: Lang, host?: string): string {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  const hostQS = host && host !== "local" ? `&host=${encodeURIComponent(host)}` : "";
  return `${scheme}${location.host}/ws/term?name=${encodeURIComponent(name)}&lang=${lang}${hostQS}&token=${encodeURIComponent(TOKEN)}`;
}

export function useTermOutput(name: string, host: string | undefined, lang: Lang): TermOutputResult | null {
  const [result, setResult] = useState<TermOutputResult | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const aliveRef = useRef(true);

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
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    }

    function connect() {
      if (!aliveRef.current) return;
      const existing = wsRef.current;
      if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
        return;
      }
      let ws: WebSocket;
      try {
        ws = new WebSocket(wsTermUrl(name, lang, host));
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        if (!aliveRef.current) return;
        let parsed: { type?: string; data?: TermOutputResult };
        try {
          parsed = JSON.parse(ev.data) as { type?: string; data?: TermOutputResult };
        } catch {
          return; // malformed frame — ignore rather than crash the UI
        }
        if (parsed.type !== "term" || !parsed.data) return;
        setResult(parsed.data);
      };

      ws.onerror = () => {
        // No-op by design: `onclose` always fires right after (per the
        // WebSocket spec) — scheduling reconnect from both would double-schedule.
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (!aliveRef.current) return;
        scheduleReconnect();
      };
    }

    connect();

    // Independent backstop poll — runs for the lifetime of this mount
    // regardless of WS state, same rationale as useStatus.ts's.
    const pollId = window.setInterval(() => {
      getTermOutput(name, lang, host).then(
        (r) => {
          if (aliveRef.current) setResult(r);
        },
        () => {
          // isolated blip — the next backstop tick or a WS message will recover
        },
      );
    }, POLL_BACKSTOP_MS);

    function onVisibilityChange() {
      if (document.visibilityState !== "visible") return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reconnectAttemptRef.current = 0;
        clearReconnectTimer();
        connect();
      }
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
  }, [name, host, lang]);

  return result;
}
