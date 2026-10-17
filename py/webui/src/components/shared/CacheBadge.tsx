/**
 * Prompt-cache badge for a running claude session (`SessionInfo.cache`, see `_cache_info_cached` in the backend).
 * Monitoring only, it changes nothing. The cache lives one hour from the last REAL model request and is a cliff:
 * past it the next message rewrites the whole context at the write price (measured: ~91% of the context rewritten
 * when the gap was 60 minutes or more). Green "♨ 42 dk" = minutes left; amber "♨ <5 dk" = inside the last five
 * minutes (the same margin the handover policy treats as cold, `CACHE_WARM_MARGIN_SECONDS`); grey "❄ 3 sa" = cold,
 * with how long the session has been idle. No badge at all when the backend does not know (`cache` absent/null):
 * unknown is never shown as cold.
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionCache } from "../../api/types";

/** Keep in step with `handover.CACHE_WARM_MARGIN_SECONDS`. */
const EXPIRING_MARGIN_S = 300;

export function CacheBadge({ cache }: { cache: SessionCache }) {
  const { t } = useLang();
  const left = cache.ttl - cache.age;
  const state = left <= 0 ? "cold" : left <= EXPIRING_MARGIN_S ? "expiring" : "warm";
  const minutes = (seconds: number) => Math.max(1, Math.round(seconds / 60));
  const dur = t.cacheDur(minutes(state === "cold" ? cache.age : left));
  return (
    <span
      className={`cache-badge ${state}`}
      title={t.cacheHint(state, t.cacheDur(minutes(cache.age)), t.cacheDur(minutes(Math.max(0, left))))}
    >
      {t.cacheBadge(state, dur)}
    </span>
  );
}
