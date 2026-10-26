/**
 * Terminal popup header: context-window fill for the open session, local AND remote. Polls `GET /api/session/facts`
 * (host-routed, `context_tokens` + `context_warn`; an older host sends no `context_warn`, then only the size shows).
 * Monitoring only; shows nothing while unknown (not claude, no turn yet, fetch failed).
 */

import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";
import { useLang } from "../../i18n/LangContext";

interface FactsResult {
  sessions?: Record<string, { context_tokens?: number | null; context_warn?: number }>;
}

const POLL_MS = 20000;

export function TermContextMeter({ name, host }: { name: string; host: string }) {
  const { t } = useLang();
  const [ctx, setCtx] = useState<{ tokens: number; warn: number } | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiGet<FactsResult>(
          `/api/session/facts?names=${encodeURIComponent(name)}&host=${encodeURIComponent(host)}`,
        );
        const f = r.sessions?.[name];
        if (alive) setCtx(f?.context_tokens ? { tokens: f.context_tokens, warn: f.context_warn ?? 0 } : null);
      } catch {
        /* keep the last value */
      }
    };
    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [name, host]);

  if (!ctx) return null;
  const { tokens, warn } = ctx;
  const pct = warn ? Math.min(100, Math.round((tokens / warn) * 100)) : 0;
  const state = !warn ? "ok" : tokens >= warn ? "over" : tokens >= warn * 0.7 ? "near" : "ok";
  const k = (n: number) => `${Math.round(n / 1000)}K`;
  return (
    <span className={`context-badge ${state}`} title={t.ctxBadgeHint(tokens, warn)} style={{ marginLeft: ".6rem" }}>
      {warn ? `ctx ${k(tokens)} / ${k(warn)} · %${pct}` : `ctx ${k(tokens)}`}
    </span>
  );
}
