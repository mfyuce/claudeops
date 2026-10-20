/**
 * Context-size badge for a running claude session (`SessionInfo.context`, see `_context_info_cached` in the backend).
 * Monitoring only. Every turn re-reads the whole context, so its size is the main cost driver. Grey = below 70% of the
 * steward's handover threshold, amber = 70% or more, red = at or past it (the steward hands the session over).
 * No badge when the backend does not know (`context` absent/null).
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionContext } from "../../api/types";

export function ContextBadge({ context }: { context: SessionContext }) {
  const { t } = useLang();
  const { tokens, warn } = context;
  const state = !warn ? "ok" : tokens >= warn ? "over" : tokens >= warn * 0.7 ? "near" : "ok";
  const k = Math.round(tokens / 1000);
  return (
    <span className={`context-badge ${state}`} title={t.ctxBadgeHint(tokens, warn)}>
      {`ctx ${k}K`}
    </span>
  );
}
