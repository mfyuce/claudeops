/**
 * Ayarlar > "Periyodik" (chats adım 7, 2026-11-06): periyodik işlerin listesi, son sonuç, aç/kapa, zamanlama düzenleme,
 * kullanıcı tanımlı iş ekle/sil, "şimdi çalıştır" (önce plan, sonra uygula). Sunucu: /api/periodic (periodic.py).
 * Yedek işi (chat_backup) yerleşiktir: silinmez, yalnız enabled=off yapılır. Yalnız insan eylemi (sunucu ajanı 403'ler).
 * Metinler bu bileşende iki dilli (strings.ts arayüzüne dokunmadan).
 */

import { useCallback, useEffect, useState } from "react";
import { apiPeriodicAction, apiPeriodicOverview, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { ErrorBox } from "./shared/ErrorBox";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import type { PeriodicJob } from "../api/types";

const TXT = {
  tr: {
    title: "Periyodik işler",
    help: "Zamanlama: 'schedule' beş alanlı cron (dk saat gün ay haftagünü, örn. 30 3 * * * = her gün 03:30) ya da boşsa 'start' + 'interval_hours' (>=24: günde bir). Yeni işler KAPALI başlar.",
    none: "Hiç iş yok.",
    last: "Son",
    never: "hiç çalışmadı",
    ok: "tamam",
    fail: "HATA",
    due: "zamanı geldi",
    on: "açık",
    off: "kapalı",
    toggle: "Aç/Kapat",
    plan: "Plan (yazmaz)",
    run: "Şimdi çalıştır",
    confirmRun: "Gerçekten çalıştır?",
    save: "Kaydet",
    del: "Sil",
    add: "İş ekle",
    id: "kimlik (a-z0-9_)",
    kind: "tür",
    command: "komut (argv, kabuksuz)",
    prompt: "istem (claude -p)",
    saved: "Kaydedildi",
    builtin: "yerleşik",
    schedule: "schedule (cron)",
    start: "start (SS:DD)",
    interval: "interval_hours",
    running: "çalışıyor…",
  },
  en: {
    title: "Periodic jobs",
    help: "Schedule: 'schedule' is a 5-field cron (min hour day month weekday, e.g. 30 3 * * * = daily 03:30), or when empty 'start' + 'interval_hours' (>=24: once a day). New jobs start OFF.",
    none: "No jobs.",
    last: "Last",
    never: "never ran",
    ok: "ok",
    fail: "FAILED",
    due: "due",
    on: "on",
    off: "off",
    toggle: "Toggle",
    plan: "Plan (dry run)",
    run: "Run now",
    confirmRun: "Really run?",
    save: "Save",
    del: "Delete",
    add: "Add job",
    id: "id (a-z0-9_)",
    kind: "kind",
    command: "command (argv, no shell)",
    prompt: "prompt (claude -p)",
    saved: "Saved",
    builtin: "built-in",
    schedule: "schedule (cron)",
    start: "start (HH:MM)",
    interval: "interval_hours",
    running: "running…",
  },
} as const;

const isOn = (v: unknown): boolean => ["on", "1", "true", "yes"].includes(String(v ?? "").toLowerCase());
const fmt = (ts?: number): string => (ts ? new Date(ts * 1000).toLocaleString() : "");

function JobRow({ id, job, onChanged }: { id: string; job: PeriodicJob; onChanged: () => void }) {
  const { lang } = useLang();
  const x = TXT[lang === "en" ? "en" : "tr"];
  const cfg = job.config;
  const [schedule, setSchedule] = useState(String(cfg.schedule ?? ""));
  const [start, setStart] = useState(String(cfg.start ?? ""));
  const [interval, setIntervalH] = useState(String(cfg.interval_hours ?? ""));
  const [busy, setBusy] = useState(false);
  const [armed, setArmed] = useState(false);
  const [out, setOut] = useState("");

  const act = async (body: Parameters<typeof apiPeriodicAction>[0], okMsg?: string) => {
    setBusy(true);
    setOut(x.running);
    try {
      const res = await apiPeriodicAction(body);
      setOut(res.ok ? res.msg ?? "" : res.error ?? "");
      if (okMsg && res.ok) showToast(okMsg, "success");
    } catch (e) {
      setOut(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
      setArmed(false);
      onChanged();
    }
  };

  const st = job.state;
  const on = isOn(cfg.enabled);
  return (
    <div className="card" style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong>{id}</strong>
        {job.builtin && <span className="muted">({x.builtin})</span>}
        <span>{on ? x.on : x.off}</span>
        {job.due && <span className="muted">{x.due}</span>}
        <span className="muted">
          {x.last}: {st.last_end ? `${fmt(st.last_end)} ${st.last_ok ? x.ok : x.fail}` : x.never}
        </span>
      </div>
      {st.last_msg && <div className="muted" style={{ wordBreak: "break-word" }}>{st.last_msg}</div>}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
        <input value={schedule} onChange={(e) => setSchedule(e.target.value)} placeholder={x.schedule} aria-label={x.schedule} />
        <input value={start} onChange={(e) => setStart(e.target.value)} placeholder={x.start} aria-label={x.start} size={7} />
        <input value={interval} onChange={(e) => setIntervalH(e.target.value)} placeholder={x.interval} aria-label={x.interval} size={5} />
        <button type="button" disabled={busy} onClick={() => act({ action: "set", id, fields: { schedule, start, interval_hours: Number(interval) || 24 } }, x.saved)}>
          {x.save}
        </button>
        <button type="button" disabled={busy} onClick={() => act({ action: "set", id, fields: { enabled: on ? "off" : "on" } }, x.saved)}>
          {x.toggle}
        </button>
        <button type="button" disabled={busy} onClick={() => act({ action: "run", id, apply: false })}>{x.plan}</button>
        <button type="button" disabled={busy} onClick={() => (armed ? act({ action: "run", id, apply: true }) : setArmed(true))}>
          {armed ? x.confirmRun : x.run}
        </button>
        {!job.builtin && (
          <button type="button" disabled={busy} onClick={() => act({ action: "remove", id })}>{x.del}</button>
        )}
      </div>
      {out && <pre className="muted" style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{out}</pre>}
    </div>
  );
}

function AddForm({ onChanged }: { onChanged: () => void }) {
  const { lang } = useLang();
  const x = TXT[lang === "en" ? "en" : "tr"];
  const [id, setId] = useState("");
  const [kind, setKind] = useState<"command" | "prompt">("command");
  const [body, setBody] = useState("");
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    try {
      const fields: Record<string, string | number> = { kind, [kind]: body };
      const res = await apiPeriodicAction({ action: "add", id, fields });
      if (!res.ok) setError(res.error ?? "");
      else {
        setId("");
        setBody("");
        showToast(x.saved, "success");
        onChanged();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div className="card">
      <strong>{x.add}</strong>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder={x.id} aria-label={x.id} />
        <select value={kind} onChange={(e) => setKind(e.target.value as "command" | "prompt")} aria-label={x.kind}>
          <option value="command">command</option>
          <option value="prompt">prompt</option>
        </select>
        <input value={body} onChange={(e) => setBody(e.target.value)} placeholder={kind === "command" ? x.command : x.prompt} style={{ flex: 1, minWidth: 220 }} />
        <button type="button" disabled={!id || !body} onClick={submit}>{x.add}</button>
      </div>
      {error && <ErrorBox text={error} />}
    </div>
  );
}

export function PeriodicSection() {
  const { t, lang } = useLang();
  const x = TXT[lang === "en" ? "en" : "tr"];
  const [jobs, setJobs] = useState<Record<string, PeriodicJob> | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiPeriodicOverview();
      setJobs(res.jobs);
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return;
      setError(describeApiError(e, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section>
      <h3>{x.title}</h3>
      <p className="muted">{x.help}</p>
      {error && <ErrorBox text={error} />}
      {jobs && Object.keys(jobs).length === 0 && <p>{x.none}</p>}
      {jobs && Object.entries(jobs).map(([id, job]) => <JobRow key={id} id={id} job={job} onChanged={() => void load()} />)}
      <AddForm onChanged={() => void load()} />
    </section>
  );
}
