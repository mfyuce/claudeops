/**
 * Metrikler sekmesi (Ayarlar grubu): copsd metrik deposu (`metrics.db`). Seri adı seçici + pencere + anahtar süzgeci; seçilen adın
 * her anahtarı (ör. proje) için satır içi SVG zaman serisi. `project.*` (günlük proje ilerleme: açık/biten TODO, açık TBD, DONE satırı,
 * 24 sa commit) ve `job.*` (periyodik iş süre/başarı) burada görünür. Veri YALNIZ `GET /api/metrics/names` ve `/api/metrics/series`
 * (copsd; copsd ön kapıda değilse uç yoktur, ipucu gösterilir). Yoklama 30 sn; sekme gizliyken sökülür.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { useLang } from "../i18n/LangContext";
import { Spark } from "./MetricSpark";

interface NameRow { name: string; keys: number; points: number; last_ts: number | null }
interface Point { ts: number; value: number }
interface SeriesRow { name: string; key: string; unit: string; points: Point[] }

const WINDOWS: [string, number][] = [["24 h", 86400], ["7 d", 604800], ["30 d", 2592000], ["90 d", 7776000]];
const MAX_KEYS = 40;

export function MetricsTab() {
  const { lang } = useLang();
  const tr = lang === "tr";
  const [names, setNames] = useState<NameRow[]>([]);
  const [name, setName] = useState("");
  const [win, setWin] = useState(604800);
  const [filter, setFilter] = useState("");
  const [series, setSeries] = useState<SeriesRow[]>([]);
  const [err, setErr] = useState("");

  const loadNames = useCallback(async () => {
    try {
      const r = await apiGet<{ names: NameRow[] }>("/api/metrics/names");
      setNames(r.names);
      setName((cur) => cur || (r.names.find((n) => n.name === "project.todo_open") ?? r.names[0])?.name || "");
      setErr("");
    } catch (e) { setErr(String((e as Error).message || e)); }
  }, []);

  const loadSeries = useCallback(async () => {
    if (!name) { setSeries([]); return; }
    try {
      const from = Math.floor(Date.now() / 1000) - win;
      const r = await apiGet<{ series: SeriesRow[] }>(`/api/metrics/series?name=${encodeURIComponent(name)}&from=${from}&limit=2000`);
      setSeries(r.series);
      setErr("");
    } catch (e) { setErr(String((e as Error).message || e)); }
  }, [name, win]);

  useEffect(() => {
    void loadNames();
    const h = window.setInterval(() => void loadNames(), 30000);
    return () => window.clearInterval(h);
  }, [loadNames]);
  useEffect(() => {
    void loadSeries();
    const h = window.setInterval(() => void loadSeries(), 30000);
    return () => window.clearInterval(h);
  }, [loadSeries]);

  const last = (s: SeriesRow) => (s.points.length ? s.points[s.points.length - 1].value : 0);
  const f = filter.trim().toLowerCase();
  const shown = series.filter((s) => !f || s.key.toLowerCase().includes(f)).sort((a, b) => last(b) - last(a));
  const unit = shown[0]?.unit || "";

  return (
    <section aria-label={tr ? "metrikler" : "metrics"} style={{ margin: "8px 0" }}>
      <h3>{tr ? "Metrikler" : "Metrics"}</h3>
      {names.length === 0 ? (
        <div className="opts-hint">
          {err
            ? (tr ? "Metrik uçları yanıt vermiyor (copsd ön kapıda değil ya da henüz yeniden başlatılmadı): " : "Metric endpoints are not answering (copsd is not the front door or has not been restarted yet): ") + err
            : (tr ? "Henüz metrik yok: günlük proje ilerleme işi ve periyodik işler yazınca burada görünür." : "No metrics yet: they appear once the daily project-progress job and periodic jobs write.")}
        </div>
      ) : (
        <>
          <div className="opts" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select value={name} onChange={(e) => setName(e.target.value)} aria-label={tr ? "seri" : "series"} style={{ maxWidth: "100%" }}>
              {names.map((n) => <option key={n.name} value={n.name}>{n.name} ({n.keys}/{n.points})</option>)}
            </select>
            <select value={win} onChange={(e) => setWin(Number(e.target.value))} aria-label={tr ? "pencere" : "window"}>
              {WINDOWS.map(([l, s]) => <option key={s} value={s}>{l}</option>)}
            </select>
            <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={tr ? "anahtar süz (proje/iş)" : "filter key (project/job)"} aria-label={tr ? "anahtar süz" : "filter key"} style={{ maxWidth: "100%" }} />
            <button type="button" className="btn" onClick={() => { void loadNames(); void loadSeries(); }}>{tr ? "Yenile" : "Refresh"}</button>
          </div>
          {err && <div className="opts-hint">{err}</div>}
          <div className="opts-hint">
            {tr ? "anahtar" : "keys"}: {shown.length}{shown.length > MAX_KEYS ? ` (${tr ? "ilk" : "first"} ${MAX_KEYS})` : ""}{unit ? ` · ${unit}` : ""} · {tr ? "son değere göre sıralı" : "sorted by latest value"}
          </div>
          {shown.length === 0 && <div className="opts-hint">{tr ? "Bu pencerede nokta yok." : "No points in this window."}</div>}
          {shown.slice(0, MAX_KEYS).map((s) => (
            <Spark key={s.key} label={s.key || "-"} values={s.points.map((p) => p.value)} fmt={(v) => (Number.isInteger(v) ? String(v) : v.toFixed(1))} />
          ))}
        </>
      )}
    </section>
  );
}
