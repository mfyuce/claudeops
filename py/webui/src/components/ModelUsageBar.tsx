/**
 * Last-hour token use per model family (`StatusData.model_usage`, see `model_usage.py`). Monitoring only. Fable is the
 * priciest model and has its own weekly quota, so it is the headline; the tooltip lists the other families and the top
 * Fable consumers (main sessions and sub-agents). Hidden until the backend has a first scan.
 */

import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n));

export function ModelUsageBar() {
  const { t } = useLang();
  const { data } = useStatusContext();
  const mu = data?.model_usage;
  if (!mu) return null;
  const f = mu.families.fable ?? { calls: 0, fresh: 0, read: 0, out: 0 };
  const others = Object.entries(mu.families)
    .filter(([k]) => k !== "fable")
    .map(([k, v]) => `${k}: ${v.calls} · ${fmt(v.read)} / ${fmt(v.fresh)}`);
  const top = mu.fable_top.map((x) => `${x.label}: ${x.calls} · ${fmt(x.read)} / ${fmt(x.fresh)}`);
  const title = [t.modelUsageHint(mu.window_minutes), ...others, ...(top.length ? ["Fable:", ...top] : [])].join("\n");
  return (
    <div className="model-usage-bar" title={title}>
      {t.modelUsageLabel(mu.window_minutes, f.calls, fmt(f.read), fmt(f.fresh))}
    </div>
  );
}
