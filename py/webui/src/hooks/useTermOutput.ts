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
 * and lets the view decide how many consecutive `ok:false` results to
 * tolerate before treating it as a real error
 * (`CONSECUTIVE_FAILURES_BEFORE_ERROR`, unchanged from the pre-WS version)
 * — same separation as before, just fed by a different transport.
 *
 * 2026-10-06 fix: "whichever landed last" used to mean exactly that —
 * `setResult` ran unconditionally from both the WS handler and the
 * backstop poll's `.then()`, with no check on which one was actually
 * fresher. `useStatus.ts` gets away with that (see its header comment —
 * mostly-idempotent payloads, server-side diffing) but a terminal pane is
 * rewritten wholesale on every tick and is being actively typed into, so a
 * backstop request that was issued before — but resolves after — a WS
 * push lands as a visible flash back to up-to-`POLL_BACKSTOP_MS`-old
 * content, immediately followed by the next WS/poll tick correcting it
 * again (live user report: pane flickering old/new while typing, worst
 * right after a command like `pwd`). `lastAppliedAtRef` now timestamps
 * every applied result; a backstop response is dropped if something
 * newer was already applied after that particular request was issued.
 */
import { useEffect, useRef, useState } from "react";
import { getTermOutput, wsAuthQS } from "../api/client";
import type { Lang } from "../i18n/strings";
import type { TermOutputResult } from "../api/types";
import { openReconnectingWs } from "./wsReconnect";

const POLL_BACKSTOP_MS = 3_000;

async function wsTermUrl(name: string, lang: Lang, host: string | undefined, lite: boolean): Promise<string> {
  const scheme = location.protocol === "https:" ? "wss://" : "ws://";
  const hostQS = host && host !== "local" ? `&host=${encodeURIComponent(host)}` : "";
  const liteQS = lite ? "&lite=1" : "";
  return `${scheme}${location.host}/ws/term?name=${encodeURIComponent(name)}&lang=${lang}${hostQS}${liteQS}&${await wsAuthQS()}`;
}

/**
 * `lite` (2026-10-09): ask for visible-rows-only frames on BOTH transports (WS + backstop poll);
 * see `TermOutputResult` / `web_term_lite.py`. The caller flips it back to false only if xterm
 * failed to load (the plain-text fallback pane has no on-demand history path, so it keeps
 * getting the full scrollback like before); changing it re-runs the effect below, i.e. reconnects.
 */
export function useTermOutput(name: string, host: string | undefined, lang: Lang, lite = false): TermOutputResult | null {
  const [result, setResult] = useState<TermOutputResult | null>(null);

  const aliveRef = useRef(true);
  // Timestamp (`Date.now()`) of the most recently *applied* result, from
  // either source — lets the backstop poll detect that a WS push already
  // delivered something newer while its own request was in flight (see
  // header comment, 2026-10-06 fix).
  const lastAppliedAtRef = useRef(0);

  useEffect(() => {
    aliveRef.current = true;

    const closeWs = openReconnectingWs({
      url: () => wsTermUrl(name, lang, host, lite),
      onMessage: (frame) => {
        const parsed = frame as { type?: string; data?: TermOutputResult } | null;
        if (!parsed || parsed.type !== "term" || !parsed.data) return;
        lastAppliedAtRef.current = Date.now();
        setResult(parsed.data);
      },
    });

    // Independent backstop poll — runs for the lifetime of this mount
    // regardless of WS state, same rationale as useStatus.ts's.
    const pollId = window.setInterval(() => {
      const requestedAt = Date.now();
      getTermOutput(name, lang, host, lite).then(
        (r) => {
          if (!aliveRef.current) return;
          // A WS push already delivered something newer while this request
          // was in flight — this response is provably stale, drop it rather
          // than flash the pane backward (see header comment).
          if (lastAppliedAtRef.current > requestedAt) return;
          lastAppliedAtRef.current = Date.now();
          setResult(r);
        },
        () => {
          // isolated blip — the next backstop tick or a WS message will recover
        },
      );
    }, POLL_BACKSTOP_MS);

    return () => {
      aliveRef.current = false;
      window.clearInterval(pollId);
      closeWs();
    };
  }, [name, host, lang, lite]);

  return result;
}
