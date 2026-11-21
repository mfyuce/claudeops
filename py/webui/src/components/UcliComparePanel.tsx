/**
 * ucli maliyet + kaynak karşılaştırması (GET /api/ucli/compare): model başına özet ve oturum başına satırlar
 * (USD/saat, USD/istek, token, azami RSS, ortalama CPU, G/Ç). Claude dışı modelde USD yok ("-" gösterilir).
 * Yoklama yok (elle Yenile); pencere `since` ile sınırlanır. Veri yalnız sayı/metin olarak çizilir.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { useLang } from "../i18n/LangContext";
import { Pagination } from "./shared/Pagination";
import { usePagination } from "../hooks/usePagination";
import { fmtBytes } from "./MetricSpark";

interface Res { rss_max_kib: number; cpu_avg: number; io_r: number; io_w: number; n: number }
interface Tokens { in: number; out: number; cache_read: number; cache_write: number }
interface Row {
  session: string; source: string; model: string; requests: number; tokens: Tokens; span_s: number;
  usd: number | null; usd_per_hour: number | null; usd_per_request: number | null; res: Res | null;
}
interface ModelRow {
  model: string; source: string; sessions: number; requests: number; tokens: Tokens; usd: number | null;
  usd_per_request: number | null; rss_max_kib_avg: number | null; cpu_avg: number | null;
}

const WINDOWS: [string, number][] = [["24 h", 86400], ["7 d", 604800], ["30 d", 2592000], ["all", 0]];
const usd = (v: number | null) => (v == null ? "-" : v >= 1 ? "$" + v.toFixed(2) : "$" + v.toFixed(4));
const tok = (t: Tokens) => String(Math.round((t.in + t.out + t.cache_read + t.cache_write) / 1000)) + "k";

export function UcliComparePanel() {
  const { lang } = useLang();
  const tr = lang === "tr";
  const [win, setWin] = useState(604800);
  const [rows, setRows] = useState<Row[]>([]);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [err, setErr] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const since = win ? Math.floor(Date.now() / 1000) - win : 0;
      const r = await apiGet<{ ok: boolean; rows: Row[]; by_model: ModelRow[]; error?: string }>(`/api/ucli/compare?since=${since}`);
      if (r.ok) { setRows(r.rows); setModels(r.by_model); setErr(""); } else setErr(r.error || "error");
    } catch (e) { setErr(String((e as Error).message || e)); }
    setLoaded(true);
  }, [win]);
  useEffect(() => { void load(); }, [load]);

  const sorted = [...rows].sort((a, b) => (b.usd ?? -1) - (a.usd ?? -1) || a.session.localeCompare(b.session));
  const mp = usePagination(models, 10);
  const rp = usePagination(sorted, 20);
  const th: React.CSSProperties = { textAlign: "left", padding: "2px 8px", whiteSpace: "nowrap" };
  const td: React.CSSProperties = { padding: "2px 8px", whiteSpace: "nowrap" };
  const wrap: React.CSSProperties = { overflowX: "auto", maxWidth: "100%" };

  return (
    <section aria-label={tr ? "ucli karşılaştırma" : "ucli comparison"} style={{ margin: "8px 0" }}>
      <h3>{tr ? "ucli maliyet ve kaynak karşılaştırması" : "ucli cost and resource comparison"}</h3>
      <div className="opts" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select value={win} onChange={(e) => setWin(Number(e.target.value))} aria-label={tr ? "pencere" : "window"}>
          {WINDOWS.map(([l, s]) => <option key={s} value={s}>{l}</option>)}
        </select>
        <button type="button" className="btn" onClick={() => void load()}>{tr ? "Yenile" : "Refresh"}</button>
      </div>
      {err && <div className="opts-hint">{err}</div>}
      {loaded && rows.length === 0 && !err ? (
        <div className="opts-hint">{tr ? "Bu pencerede ucli oturumu yok." : "No ucli sessions in this window."}</div>
      ) : (
        <>
          <h4>{tr ? "Model başına" : "Per model"}</h4>
          <div style={wrap}>
            <table>
              <thead><tr>
                <th style={th}>{tr ? "model" : "model"}</th><th style={th}>{tr ? "kaynak" : "source"}</th><th style={th}>{tr ? "oturum" : "sessions"}</th>
                <th style={th}>{tr ? "istek" : "requests"}</th><th style={th}>USD</th><th style={th}>USD/{tr ? "istek" : "req"}</th>
                <th style={th}>token</th><th style={th}>RSS {tr ? "ort" : "avg"}</th><th style={th}>CPU {tr ? "ort" : "avg"}</th>
              </tr></thead>
              <tbody>{mp.pageItems.map((m) => (
                <tr key={m.model + "|" + m.source}>
                  <td style={td}>{m.model}</td><td style={td}>{m.source}</td><td style={td}>{m.sessions}</td><td style={td}>{m.requests}</td>
                  <td style={td}>{usd(m.usd)}</td><td style={td}>{usd(m.usd_per_request)}</td><td style={td}>{tok(m.tokens)}</td>
                  <td style={td}>{m.rss_max_kib_avg == null ? "-" : fmtBytes(m.rss_max_kib_avg * 1024)}</td>
                  <td style={td}>{m.cpu_avg == null ? "-" : m.cpu_avg.toFixed(1) + "%"}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <Pagination page={mp.page} totalPages={mp.totalPages} onChange={mp.setPage} />
          <h4>{tr ? "Oturum başına" : "Per session"}</h4>
          <div style={wrap}>
            <table>
              <thead><tr>
                <th style={th}>{tr ? "oturum" : "session"}</th><th style={th}>model</th><th style={th}>{tr ? "istek" : "requests"}</th>
                <th style={th}>USD</th><th style={th}>USD/{tr ? "sa" : "h"}</th><th style={th}>USD/{tr ? "istek" : "req"}</th><th style={th}>token</th>
                <th style={th}>RSS max</th><th style={th}>CPU {tr ? "ort" : "avg"}</th><th style={th}>{tr ? "okuma/yazma" : "read/write"}</th>
              </tr></thead>
              <tbody>{rp.pageItems.map((r) => (
                <tr key={r.source + "|" + r.session}>
                  <td style={td}>{r.session}</td><td style={td}>{r.model || "?"}</td><td style={td}>{r.requests}</td>
                  <td style={td}>{usd(r.usd)}</td><td style={td}>{usd(r.usd_per_hour)}</td><td style={td}>{usd(r.usd_per_request)}</td><td style={td}>{tok(r.tokens)}</td>
                  <td style={td}>{r.res ? fmtBytes(r.res.rss_max_kib * 1024) : "-"}</td>
                  <td style={td}>{r.res ? r.res.cpu_avg.toFixed(1) + "%" : "-"}</td>
                  <td style={td}>{r.res ? fmtBytes(r.res.io_r) + " / " + fmtBytes(r.res.io_w) : "-"}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <Pagination page={rp.page} totalPages={rp.totalPages} onChange={rp.setPage} />
        </>
      )}
    </section>
  );
}
