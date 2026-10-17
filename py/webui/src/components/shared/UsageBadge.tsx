/**
 * Token burn badge for a running session: the process-lifetime counters of ucli's `--status-file`
 * (`SessionInfo.usage`, see `provider.live_usage()` in the backend). Rendered only when the CLI has a
 * counter and made at least one request; a CLI without one (`usage` absent/null) shows nothing, never
 * "0 tokens". The headline is input + output tokens (what Evren's board calls "Toplam token", cached
 * input included); the tooltip has the breakdown. Amber when an attempt got no usable response
 * (`unmetered`): the server still counts it, and that is the single most expensive event measured so far.
 * `warn` (backend, from the `ucli_usage_warn` thresholds on the quota-equivalent tokens, where Evren counts cached
 * input at 3%) turns the badge amber (1) or red (2) and then also prints the quota number, so the colour is
 * explained without hovering. Colour only: nothing is stopped.
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionUsage } from "../../api/types";

/** 850 -> "850", 9001 -> "9K", 466378 -> "466K", 12566622 -> "12.6M". */
function formatTokens(n: number): string {
  const trim = (s: string) => s.replace(/\.0$/, "");
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${trim((n / 1000).toFixed(n < 10_000 ? 1 : 0))}K`;
  return `${trim((n / 1_000_000).toFixed(1))}M`;
}

export function UsageBadge({ usage }: { usage: SessionUsage }) {
  const { t } = useLang();
  if (usage.requests <= 0 && usage.unmetered <= 0) return null;
  // A FLOOR: the endpoint sent no `usage` for some requests (`reported < requests`), or an attempt it
  // processed was cancelled client-side (`unmetered`), so the real burn can be higher, never lower.
  const floor = usage.unmetered > 0 || usage.reported < usage.requests;
  const warn = usage.warn ?? 0;
  const cls = `usage-badge${usage.unmetered > 0 ? " unmetered" : ""}${warn >= 2 ? " warn-2" : warn === 1 ? " warn-1" : ""}`;
  const quota = warn > 0 && usage.quota_tokens != null ? formatTokens(usage.quota_tokens) : undefined;
  return (
    <span className={cls} title={t.usageHint(usage)}>
      {t.usageBadge(formatTokens(usage.prompt_tokens + usage.completion_tokens), usage.requests, floor, quota)}
    </span>
  );
}
