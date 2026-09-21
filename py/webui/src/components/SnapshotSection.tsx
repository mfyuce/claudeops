/**
 * "Ayarlar" tab's Fleet Snapshot section (TODO.md 2026-09-16/17, geçmiş
 * listesi 2026-09-21) — save the currently-running fleet, later reopen
 * whatever isn't already running with the EXACT model/effort/permission-
 * mode/cli each session was captured with (not roster.tsv's "next launch"
 * default — `_snapshot_save()` reads the live proc's own cmdline via
 * `find_sessions()`, see web.py's comment).
 *
 * On-demand "manual" saves via the button below, PLUS an automatic "closing"
 * entry the backend appends whenever the panel process is stopped (systemd
 * stop/restart, real shutdown) and the fleet differs from the last saved
 * entry (unchanged → no duplicate — see `snapshot.py`'s module docstring for
 * why: the user forgot to save manually one day and the last save no longer
 * matched what was actually open at shutdown). No periodic/background
 * polling otherwise — matches [[feedback-manual-fleet-control]]'s "guard
 * kasıtlı kapalı" stance (same reasoning as `UsagePanel`'s own
 * button-not-poll comment in SettingsTab).
 *
 * `hidden` defaults to false (windows open, today's normal Start behavior) —
 * user explicitly asked for windows-by-default with hidden as an opt-in
 * checkbox, not the other way around.
 */

import { useCallback, useEffect, useState } from "react";
import { apiSnapshotList, apiSnapshotResume, apiSnapshotSave, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { SnapshotListResult, SnapshotResumeResult } from "../api/types";

export function SnapshotSection() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [saving, setSaving] = useState(false);
  const [resumingAt, setResumingAt] = useState<number | "latest" | null>(null);
  const [hidden, setHidden] = useState(false);
  const [result, setResult] = useState<Extract<SnapshotResumeResult, { ok: true }> | null>(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Extract<SnapshotListResult, { ok: true }>["snapshots"] | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiSnapshotList(lang);
      if (res.ok) setHistory(res.snapshots);
      else setError(res.error);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return; // sekme henüz görünmüyor olabilir — auth uyarısını burada gösterme
      setError(describeApiError(e, t));
    }
  }, [lang, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data) return null;
  const snap = data.snapshot;

  function handleAuthOrError(e: unknown) {
    if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
    else setError(describeApiError(e, t));
  }

  async function handleSave() {
    setSaving(true);
    setError("");
    setResult(null);
    try {
      const res = await apiSnapshotSave(lang);
      if (!res.ok) setError(res.error);
    } catch (e) {
      handleAuthOrError(e);
    }
    setSaving(false);
    refresh();
    void load();
  }

  async function handleResume(savedAt?: number) {
    setResumingAt(savedAt ?? "latest");
    setError("");
    setResult(null);
    try {
      const res = await apiSnapshotResume(hidden, lang, savedAt);
      if (res.ok) setResult(res);
      else setError(res.error);
    } catch (e) {
      handleAuthOrError(e);
    }
    setResumingAt(null);
    refresh();
  }

  const failedRows = result?.results.filter((r) => r.status === "failed") ?? [];
  const resuming = resumingAt !== null;
  const fmtWhen = (savedAt: number) => new Date(savedAt * 1000).toLocaleString(lang === "tr" ? "tr-TR" : "en-US");

  return (
    <div className="opts" id="settingsSnapshotPanel" style={{ flexDirection: "column", alignItems: "flex-start" }}>
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.snapshotLabel}</b> {t.snapshotDesc}
      </span>
      <span>
        {snap.saved_at !== null && snap.kind !== null
          ? t.snapshotInfo(snap.count, fmtWhen(snap.saved_at), snap.kind)
          : t.snapshotNone}
      </span>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" disabled={saving} onClick={() => void handleSave()}>
          {saving ? t.snapshotSaving : t.snapshotSaveBtn}
        </button>
        <button type="button" disabled={resuming || snap.saved_at === null} onClick={() => void handleResume()}>
          {resumingAt === "latest" ? t.snapshotResuming : t.snapshotResumeBtn}
        </button>
        <label className="fresh-toggle">
          <input type="checkbox" checked={hidden} onChange={(e) => setHidden(e.target.checked)} /> {t.snapshotHiddenLabel}
        </label>
      </div>
      {error && <pre className="layout-result">✗ {error}</pre>}
      {result && (
        <pre className="layout-result">
          {t.snapshotResultSummary(result.started, result.already_running, result.failed)}
          {failedRows.map((r) => `\n  ✗ ${r.name}: ${r.error ?? ""}`).join("")}
        </pre>
      )}
      {history && history.length > 1 && (
        <div style={{ flexBasis: "100%" }}>
          <span className="opts-hint">
            <b>{t.snapshotHistoryLabel}</b>
          </span>
          <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
            {history.slice(1).map((h) => (
              <li key={h.saved_at} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span>
                  [{h.kind === "closing" ? t.snapshotKindClosing : t.snapshotKindManual}]{" "}
                  {t.snapshotHistoryRow(h.count, fmtWhen(h.saved_at))}
                </span>
                <button type="button" disabled={resuming} onClick={() => void handleResume(h.saved_at)}>
                  {resumingAt === h.saved_at ? t.snapshotResuming : t.snapshotHistoryResumeBtn}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {history && history.length <= 1 && <span className="opts-hint">{t.snapshotHistoryEmpty}</span>}
    </div>
  );
}
