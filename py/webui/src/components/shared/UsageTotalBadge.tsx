/**
 * Cumulative token spend of a local claude session (`SessionInfo.usage_total`, see `_usage_total` in the backend).
 * Monitoring only: `Σ 12.4M` = input + output + cache write + cache read (main session + sub-agents); the tooltip splits
 * them. No badge when the backend does not know (`usage_total` absent/null).
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionUsageTotal, UsageParts } from "../../api/types";

function short(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function parts(p: UsageParts): string {
  return `in ${short(p.in)} · out ${short(p.out)} · cache w ${short(p.cache_write)} · cache r ${short(p.cache_read)}`;
}

export function UsageTotalBadge({ usage }: { usage: SessionUsageTotal }) {
  const { t } = useLang();
  const s = usage.subagents;
  const sum = (p: UsageParts) => p.in + p.out + p.cache_write + p.cache_read;
  return (
    <span className="usage-total-badge" title={t.usageTotalHint(parts(usage), parts(s), s.n)}>
      {`Σ ${short(sum(usage) + sum(s))}`}
    </span>
  );
}
