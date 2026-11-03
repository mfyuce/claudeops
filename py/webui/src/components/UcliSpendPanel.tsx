/**
 * ucli spend (USD) panel: today's estimated dollar total of Claude-service ucli sessions against the daily cap
 * (`status.ucli_cost`, 30 s cached on the server; a lower bound). Shows remaining budget, a plain state line
 * (ok / near cap >=80% / cap reached) and a quick cap editor (same setting as Model keys).
 */
import { useState } from "react";
import { apiSaveSettings } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

export function UcliSpendPanel() {
  const { lang, t } = useLang();
  const { data, refresh } = useStatusContext();
  const [error, setError] = useState<string | null>(null);
  const tr = lang === "tr";
  const cost = data?.ucli_cost;
  if (!cost) return null;
  const capOn = cost.cap_usd > 0;
  const pct = capOn ? (cost.pct ?? (cost.today_usd / cost.cap_usd) * 100) : null;
  const color = pct == null ? "#2563eb" : pct >= 100 ? "#b91c1c" : pct >= 80 ? "#b45309" : "#15803d";
  const remaining = capOn ? Math.max(0, cost.cap_usd - cost.today_usd) : null;
  let state = "";
  if (pct != null) {
    if (pct >= 100) state = tr ? "Tavan doldu: yeni Claude ucli oturumu açılmaz (çalışanlara dokunulmaz)." : "Cap reached: new Claude ucli sessions are refused (running ones are untouched).";
    else if (pct >= 80) state = tr ? "Tavana yaklaşıldı." : "Close to the cap.";
  }
  return (
    <section className="ucli-spend" aria-label={tr ? "ucli harcama" : "ucli spend"} style={{ margin: "8px 0" }}>
      <h3>{tr ? "ucli harcama (USD)" : "ucli spend (USD)"}</h3>
      <div title={tr ? "Claude hizmetli ucli oturumlarının bugünkü tahmini toplamı (alt sınır)." : "Today's estimated total of Claude-service ucli sessions (a lower bound)."}>
        {tr ? "bugün" : "today"}: <strong>${cost.today_usd.toFixed(2)}</strong>
        {capOn ? ` / $${cost.cap_usd.toFixed(0)} (${(pct ?? 0).toFixed(0)}%)` : tr ? " · günlük tavan yok" : " · no daily cap"}
        {remaining != null && <span className="opts-hint"> · {tr ? "kalan" : "left"}: ${remaining.toFixed(2)}</span>}
      </div>
      {capOn && (
        <div style={{ background: "#e5e7eb", borderRadius: 4, height: 8, maxWidth: 320 }} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, pct ?? 0)}>
          <div style={{ width: `${Math.min(100, pct ?? 0)}%`, height: "100%", borderRadius: 4, background: color }} />
        </div>
      )}
      {state && <div style={{ color, fontWeight: 600 }}>{state}</div>}
      {cost.rate_1h_usd != null && (
        <div className="ucli-spend-rate" title={tr ? "Harcama hızı (USD/saat): son 1 saat ve son 15 dk" : "Spend rate (USD/hour): last hour and last 15 min"}>
          <span className="badge"><strong>~{Math.round(cost.rate_1h_usd)} USD/{tr ? "sa" : "h"}</strong></span>
          {cost.rate_15m_usd != null && <span className="opts-hint"> · 15 {tr ? "dk" : "min"}: ${cost.rate_15m_usd.toFixed(2)}/{tr ? "sa" : "h"}</span>}
        </div>
      )}
      {(cost.by_session?.length ?? 0) > 0 && (
        <details className="ucli-spend-by">
          <summary>{tr ? "kodcu başı (bugün)" : "per coder (today)"}</summary>
          <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
            {cost.by_session!.map((s) => (
              <li key={s.session}>
                {s.session}: <strong>${s.usd.toFixed(2)}</strong>
              </li>
            ))}
          </ul>
        </details>
      )}
      <label className="opts-hint" title={tr ? "0 ya da boş = tavan yok." : "0 or empty = no cap."}>
        {tr ? "günlük tavan (USD)" : "daily cap (USD)"}{" "}
        <input
          type="number"
          min={0}
          step={1}
          style={{ width: 80 }}
          key={cost.cap_usd}
          defaultValue={capOn ? cost.cap_usd : ""}
          placeholder={tr ? "tavan yok" : "no cap"}
          onBlur={(e) => {
            const v = e.target.value;
            if (v === (capOn ? String(cost.cap_usd) : "")) return;
            void (async () => {
              try {
                const res = await apiSaveSettings({ ucli_cost: { daily_cap_usd: v }, lang });
                setError(res.ok ? null : res.error);
              } catch (err) {
                setError(describeApiError(err, t));
              }
              refresh();
            })();
          }}
        />
      </label>
      {cost.credit_left_usd != null && (
        <div title={tr ? "kalan = toplam kredi - birikmiş harcama (alt sınır tahmini)" : "left = total credit - accumulated spend (lower-bound estimate)"}>
          {tr ? "kalan kredi" : "credit left"}: <strong>${cost.credit_left_usd.toFixed(2)}</strong>
          <span className="opts-hint"> / ${(cost.credit_total_usd ?? 0).toFixed(0)} · {tr ? "harcanan" : "spent"} ${(cost.spent_total_usd ?? 0).toFixed(2)}</span>
        </div>
      )}
      <label className="opts-hint" title={tr ? "Boş = kalan krediyi gösterme." : "Empty = hide remaining credit."}>
        {tr ? "toplam kredi (USD)" : "total credit (USD)"}{" "}
        <input
          type="number"
          min={0}
          step={1}
          style={{ width: 80 }}
          key={`credit-${cost.credit_total_usd ?? 0}`}
          defaultValue={cost.credit_total_usd ? cost.credit_total_usd : ""}
          placeholder={tr ? "gösterme" : "hidden"}
          onBlur={(e) => {
            const v = e.target.value;
            if (v === (cost.credit_total_usd ? String(cost.credit_total_usd) : "")) return;
            void (async () => {
              try {
                const res = await apiSaveSettings({ ucli_cost: { credit_total_usd: v }, lang });
                setError(res.ok ? null : res.error);
              } catch (err) {
                setError(describeApiError(err, t));
              }
              refresh();
            })();
          }}
        />
      </label>
      {error && <pre className="layout-result">✗ {error}</pre>}
      <span className="opts-hint">
        {tr ? `önbellek TTL: ${cost.cache_ttl || "1h"} · alt sınır tahmini` : `cache TTL: ${cost.cache_ttl || "1h"} · lower-bound estimate`}
      </span>
    </section>
  );
}
