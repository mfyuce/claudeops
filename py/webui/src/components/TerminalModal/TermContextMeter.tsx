/**
 * Terminal popup header: context-window fill for the open session, local AND remote. Polls `GET /api/session/facts`
 * (host-routed, `context_tokens` + `context_warn`; an older host sends no `context_warn`, then only the size shows).
 * Monitoring only; shows nothing while unknown (not claude, no turn yet, fetch failed).
 */

import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";
import { useLang } from "../../i18n/LangContext";

interface FactsResult {
  sessions?: Record<string, { running?: boolean; context_tokens?: number | null; context_warn?: number }>;
}

const POLL_MS = 20000;
// Boş/başarısız okuma (uzak proxy zaman aşımı, geçici null) son iyi değeri silmez; yalnız oturum kapandıysa ya da bu kadar
// süredir hiç okunamıyorsa rozet kalkar.
const STALE_MS = 600000;

export function TermContextMeter({ name, host }: { name: string; host: string }) {
  const { t } = useLang();
  const [ctx, setCtx] = useState<{ tokens: number; warn: number } | null>(null);

  useEffect(() => {
    let alive = true;
    let lastOk = 0;
    const tick = async () => {
      try {
        const r = await apiGet<FactsResult>(
          `/api/session/facts?names=${encodeURIComponent(name)}&host=${encodeURIComponent(host)}`,
        );
        const f = r.sessions?.[name];
        if (!alive) return;
        if (f?.context_tokens) {
          lastOk = Date.now();
          setCtx({ tokens: f.context_tokens, warn: f.context_warn ?? 0 });
        } else if (f?.running === false || Date.now() - lastOk > STALE_MS) {
          setCtx(null);
        }
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
