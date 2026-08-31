/**
 * `GET /api/status` poller — THIS STAGE is a plain `setInterval`, matching
 * today's 4s behavior exactly (React rewrite plan, Sequencing step 5: "as
 * a plain REST poller first ... isolates UI correctness from transport
 * correctness", WS wiring is a later stage, step 10).
 *
 * External interface (`{data, error, loading, refresh}`) is deliberately
 * the whole contract a consumer gets — a later stage swaps this hook's
 * internals for WS-primary/poll-fallback/reconnect without touching
 * `StatusContext.tsx` or any component that calls `useStatusContext()`.
 *
 * Behavioral parity with the original `refresh()`/`render()` pair that's
 * easy to lose in a naive port: on a FAILED poll, `data` is left exactly
 * as it was (last known good) — only `error` changes. The original never
 * clears `LAST`/re-runs `render()` on a failed `refresh()`; it just
 * overwrites `#summary`'s text and returns early, leaving the already-
 * rendered tables alone. Callers (`App`) should show `error` in place of
 * the running-count summary line while still rendering tabs/tables from
 * whatever `data` last held.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, getStatus } from "../api/client";
import type { StatusPayload } from "../api/types";

const POLL_INTERVAL_MS = 4000;

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

export interface UseStatusResult {
  data: StatusPayload | null;
  error: StatusError | null;
  loading: boolean;
  /** Force an out-of-band fetch right now, in addition to the interval —
   * replaces the original's `LAST_JSON = null; refresh();` pattern used
   * after every mutating action so the UI reflects it within milliseconds
   * instead of waiting for the next tick. */
  refresh: () => void;
}

export function useStatus(): UseStatusResult {
  const [data, setData] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<StatusError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => {
    setTick((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const d = await getStatus();
        if (cancelled) return;
        setData(d);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(toStatusError(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `tick` is bumped by `refresh()` purely to re-run this effect on
    // demand — it carries no other meaning, so it's fine that it's the
    // only reason this effect re-fires between scheduled polls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  useEffect(() => {
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { data, error, loading, refresh };
}
