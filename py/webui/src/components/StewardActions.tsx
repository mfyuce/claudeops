/** Değnekçi sekmesi: proje başına elle eylem (direktif/devir/yeniden başlat/durdur) + olay günlüğü. Her eylem sunucuda
 *  aynı kapılardan (`_gate`/`_target`) geçer; panel yalnız CLI'nin `steward api ...` karşılığıdır. */
import { useCallback, useState } from "react";
import { apiStewardProjectAction, getStewardLog } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { showToast } from "../state/toast";

export function StewardActions({ sid, projects }: { sid: string; projects: Array<{ name: string; running: boolean }> }) {
  const { t } = useLang();
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<Array<Record<string, unknown>> | null>(null);

  const sel = projects.find((p) => p.name === name);

  async function go(action: "directive" | "handover" | "stop" | "restart", confirm: boolean) {
    if (busy || !name) return;
    if (confirm && !window.confirm(t.stewardActConfirm)) return;
    setBusy(true);
    try {
      const r = await apiStewardProjectAction(action, name, text.trim(), sid);
      if (!r.ok) showToast(r.error || t.requestFailed);
      else {
        showToast(t.stewardActDone, "success");
        if (action === "directive" || action === "restart") setText("");
      }
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  }

  const loadLog = useCallback(async () => {
    try {
      const r = await getStewardLog(80, sid);
      if (r.ok) setLog((r.entries ?? []).slice().reverse());
    } catch (e) {
      showToast(describeApiError(e, t));
    }
  }, [sid, t]);

  const line = (e: Record<string, unknown>) => {
    const { ts, event, ...rest } = e;
    const extra = Object.entries(rest).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ");
    return `${String(ts ?? "")} ${String(event ?? "")} ${extra}`.slice(0, 300);
  };

  return (
    <>
      <details>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardActTitle}</summary>
        <div className="opts" style={{ marginTop: ".4rem", flexDirection: "column", alignItems: "flex-start", gap: ".4rem" }}>
          <span className="opts-hint">{t.stewardActHint}</span>
          <select value={name} onChange={(e) => setName(e.target.value)} aria-label="project">
            <option value="">—</option>
            {projects.map((p) => (
              <option key={p.name} value={p.name}>{p.name}{p.running ? " ●" : ""}</option>
            ))}
          </select>
          <textarea style={{ width: "100%" }} rows={3} value={text} placeholder={t.stewardActText} onChange={(e) => setText(e.target.value)} />
          <span>
            <button type="button" disabled={busy || !name || !text.trim()} onClick={() => void go("directive", false)}>{t.stewardActDirective}</button>{" "}
            <button type="button" disabled={busy || !name || !sel?.running} onClick={() => void go("handover", true)}>{t.stewardActHandover}</button>{" "}
            <button type="button" disabled={busy || !name} onClick={() => void go("restart", true)}>{t.stewardActRestart}</button>{" "}
            <button type="button" className="retire" disabled={busy || !name || !sel?.running} onClick={() => void go("stop", true)}>{t.stewardActStop}</button>
          </span>
        </div>
      </details>
      <details onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) void loadLog(); }}>
        <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{t.stewardLogTitle}</summary>
        <div className="opts" style={{ marginTop: ".4rem", flexDirection: "column", alignItems: "flex-start", gap: ".2rem" }}>
          <button type="button" onClick={() => void loadLog()}>{t.stewardLogRefresh}</button>
          {log && log.length === 0 && <span className="opts-hint">{t.stewardLogNone}</span>}
          {log?.map((e, i) => (
            <code key={i} style={{ fontSize: ".75rem", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{line(e)}</code>
          ))}
        </div>
      </details>
    </>
  );
}
