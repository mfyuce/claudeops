/**
 * Shared jittered exponential-backoff formula for the two WS-primary hooks
 * (`useStatus.ts`, `useTermOutput.ts`) — extracted so the same reconnect
 * behavior doesn't drift into two copies (both need it identically, and
 * this session already hit a real bug elsewhere caused by exactly that
 * kind of drift — a backend kill-mechanism duplicated instead of shared).
 */

export const WS_RECONNECT_BASE_MS = 1_000;
export const WS_RECONNECT_CAP_MS = 20_000;

/** "Equal jitter" around an exponential-backoff delay: half fixed, half
 * random — `attempt` 0 → 0.5-1s, doubling each retry up to a 10-20s spread
 * once the exponential part saturates the cap. Never near-zero (unlike
 * "full jitter", `random(0, cap)`), which matters since the far more common
 * case than a real outage is a normal server-restart during a `npm run dev`
 * / redeploy — a fixed floor avoids every open tab hammering the
 * not-yet-listening port in a tight loop, while the random half still
 * avoids every tab retrying in lockstep once it does come back. */
export function reconnectDelayMs(attempt: number): number {
  const exp = Math.min(WS_RECONNECT_CAP_MS, WS_RECONNECT_BASE_MS * 2 ** attempt);
  return exp / 2 + Math.random() * (exp / 2);
}
