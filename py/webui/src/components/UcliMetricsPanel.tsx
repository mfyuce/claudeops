/**
 * ucli kaynak metrikleri (ucli_metrics.py): oturum seçici + zaman penceresi, özet (azami RSS, ortalama CPU, pencere içi G/Ç artışı)
 * ve satır içi SVG zaman serileri (RSS, CPU, disk yazma/okuma hızı, disk kullanımı). GET /api/ucli/metrics/sessions ve /api/ucli/metrics.
 * Yoklama 15 sn; sekme gizliyken yoklanmaz (bileşen sökülür). Veri yalnız sayı olarak çizilir.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { useLang } from "../i18n/LangContext";
import { Spark, fmtBytes } from "./MetricSpark";

interface Sample { ts: number; rss_kib: number | null; cpu_pct: number | null; io_r: number | null; io_w: number | null; procs: number | null; disk_b: number | null }
interface Summary { rss_max_kib: number; cpu_avg: number; io_r: number; io_w: number; n: number }
interface SessionRow { name: string; last_ts: number; n: number }

const WINDOWS: [string, number][] = [["1 h", 3600], ["6 h", 21600], ["24 h", 86400], ["7 d", 604800]];

export function UcliMetricsPanel() {
  const { lang } = useLang();
  const tr = lang === "tr";
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [name, setName] = useState("");
  const [win, setWin] = useState(3600);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [err, setErr] = useState("");

  const loadSessions = useCallback(async () => {
    try {
      const r = await apiGet<{ ok: boolean; sessions: SessionRow[] }>("/api/ucli/metrics/sessions");
      const list = r.ok ? r.sessions : [];
      setSessions(list);
      setName((cur) => cur || (list[0] ? list[0].name : ""));
    } catch { /* sonraki yoklamada */ }
  }, []);

  const loadSamples = useCallback(async () => {
    if (!name) { setSamples([]); setSummary(null); return; }
    try {
      const since = Math.floor(Date.now() / 1000) - win;
      const r = await apiGet<{ ok: boolean; samples: Sample[]; summary: Summary; error?: string }>(
        `/api/ucli/metrics?name=${encodeURIComponent(name)}&since=${since}&limit=2000`);
      if (r.ok) { setSamples(r.samples); setSummary(r.summary); setErr(""); } else setErr(r.error || "error");
    } catch (e) { setErr(String((e as Error).message || e)); }
  }, [name, win]);

  useEffect(() => {
    void loadSessions();
    const h = window.setInterval(() => void loadSessions(), 15000);
    return () => window.clearInterval(h);
  }, [loadSessions]);
  useEffect(() => {
    void loadSamples();
    const h = window.setInterval(() => void loadSamples(), 15000);
    return () => window.clearInterval(h);
  }, [loadSamples]);

  // G/Ç hızı: art arda örnekler arası bayt farkı / saniye (sayaç düşerse = süreç değişti: 0)
  const rate = (key: "io_r" | "io_w") => samples.map((s, i) => {
    if (i === 0) return null;
    const a = samples[i - 1][key], b = s[key], dt = s.ts - samples[i - 1].ts;
    return a == null || b == null || dt <= 0 ? null : Math.max(0, b - a) / dt;
  });

  return (
    <section aria-label={tr ? "ucli metrikleri" : "ucli metrics"} style={{ margin: "8px 0" }}>
      <h3>{tr ? "ucli kaynak metrikleri" : "ucli resource metrics"}</h3>
      {sessions.length === 0 ? (
        <div className="opts-hint">{tr ? "Henüz metrik yok: çalışan bir ucli oturumu örneklendiğinde burada görünür." : "No metrics yet: they appear here once a running ucli session is sampled."}</div>
      ) : (
        <>
          <div className="opts" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select value={name} onChange={(e) => setName(e.target.value)} aria-label={tr ? "oturum" : "session"} style={{ maxWidth: "100%" }}>
              {sessions.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.n})</option>)}
            </select>
            <select value={win} onChange={(e) => setWin(Number(e.target.value))} aria-label={tr ? "pencere" : "window"}>
              {WINDOWS.map(([l, s]) => <option key={s} value={s}>{l}</option>)}
            </select>
            <button type="button" className="btn" onClick={() => void loadSamples()}>{tr ? "Yenile" : "Refresh"}</button>
          </div>
          {err && <div className="opts-hint">{err}</div>}
          {summary && summary.n > 0 ? (
            <>
              <div style={{ margin: "6px 0" }}>
                {tr ? "örnek" : "samples"}: <strong>{summary.n}</strong> · RSS max: <strong>{fmtBytes(summary.rss_max_kib * 1024)}</strong> · CPU {tr ? "ort" : "avg"}:{" "}
                <strong>{summary.cpu_avg.toFixed(1)}%</strong> · {tr ? "okuma" : "read"}: <strong>{fmtBytes(summary.io_r)}</strong> · {tr ? "yazma" : "write"}: <strong>{fmtBytes(summary.io_w)}</strong>
              </div>
              <Spark label="RSS" values={samples.map((s) => (s.rss_kib == null ? null : s.rss_kib * 1024))} fmt={fmtBytes} />
              <Spark label="CPU %" values={samples.map((s) => s.cpu_pct)} fmt={(v) => v.toFixed(1) + "%"} />
              <Spark label={tr ? "disk okuma/sn" : "disk read/s"} values={rate("io_r")} fmt={(v) => fmtBytes(v) + "/s"} />
              <Spark label={tr ? "disk yazma/sn" : "disk write/s"} values={rate("io_w")} fmt={(v) => fmtBytes(v) + "/s"} />
              <Spark label={tr ? "çalışma dizini boyutu" : "workdir size"} values={samples.map((s) => s.disk_b)} fmt={fmtBytes} />
              <Spark label={tr ? "süreç sayısı" : "processes"} values={samples.map((s) => s.procs)} fmt={(v) => String(Math.round(v))} />
            </>
          ) : (
            <div className="opts-hint">{tr ? "Bu pencerede örnek yok." : "No samples in this window."}</div>
          )}
        </>
      )}
    </section>
  );
}
