/**
 * ucli spend (USD) panel: today's estimated dollar total of Claude-service ucli sessions against the daily cap
 * (`status.ucli_cost`, 30 s cached on the server; a lower bound). Read-only; the cap itself is edited in Model keys.
 */
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

export function UcliSpendPanel() {
  const { lang } = useLang();
  const { data } = useStatusContext();
  const tr = lang === "tr";
  const cost = data?.ucli_cost;
  if (!cost) return null;
  const pct = cost.pct;
  const color = pct == null ? "#2563eb" : pct >= 100 ? "#b91c1c" : pct >= 80 ? "#b45309" : "#15803d";
  return (
    <section className="ucli-spend" aria-label={tr ? "ucli harcama" : "ucli spend"} style={{ margin: "8px 0" }}>
      <h3>{tr ? "ucli harcama (USD)" : "ucli spend (USD)"}</h3>
      <div title={tr ? "Claude hizmetli ucli oturumlarının bugünkü tahmini toplamı (alt sınır)." : "Today's estimated total of Claude-service ucli sessions (a lower bound)."}>
        {tr ? "bugün" : "today"}: <strong>${cost.today_usd.toFixed(2)}</strong>
        {cost.cap_usd > 0 ? ` / $${cost.cap_usd.toFixed(0)}${pct != null ? ` (${pct.toFixed(0)}%)` : ""}` : tr ? " · günlük tavan yok" : " · no daily cap"}
      </div>
      {cost.cap_usd > 0 && (
        <div style={{ background: "#e5e7eb", borderRadius: 4, height: 8, maxWidth: 320 }} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, pct ?? 0)}>
          <div style={{ width: `${Math.min(100, pct ?? 0)}%`, height: "100%", borderRadius: 4, background: color }} />
        </div>
      )}
      <span className="opts-hint">
        {tr ? `önbellek TTL: ${cost.cache_ttl || "1h"} · tavan: Model anahtarları bölümünde` : `cache TTL: ${cost.cache_ttl || "1h"} · cap: set in Model keys`}
      </span>
    </section>
  );
}
