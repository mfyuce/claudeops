/**
 * "Ayarlar" tab's Fleet Snapshot section (TODO.md 2026-09-16/17) — save the
 * currently-running fleet, later reopen whatever isn't already running with
 * the EXACT model/effort/permission-mode/cli each session was captured with
 * (not roster.tsv's "next launch" default — `_snapshot_save()` reads the
 * live proc's own cmdline via `find_sessions()`, see web.py's comment).
 *
 * Manual/on-demand only, no auto-save — matches
 * [[feedback-manual-fleet-control]]'s "guard kasıtlı kapalı" stance (same
 * reasoning as `UsagePanel`'s own button-not-poll comment in SettingsTab).
 *
 * `hidden` defaults to false (windows open, today's normal Start behavior) —
 * user explicitly asked for windows-by-default with hidden as an opt-in
 * checkbox, not the other way around.
 */

import { useState } from "react";
import { apiSnapshotResume, apiSnapshotSave, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { SnapshotResumeResult } from "../api/types";

export function SnapshotSection() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [saving, setSaving] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [result, setResult] = useState<Extract<SnapshotResumeResult, { ok: true }> | null>(null);
  const [error, setError] = useState("");

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
  }

  async function handleResume() {
    setResuming(true);
    setError("");
    setResult(null);
    try {
      const res = await apiSnapshotResume(hidden, lang);
      if (res.ok) setResult(res);
      else setError(res.error);
    } catch (e) {
      handleAuthOrError(e);
    }
    setResuming(false);
    refresh();
  }

  const failedRows = result?.results.filter((r) => r.status === "failed") ?? [];

  return (
    <div className="opts" id="settingsSnapshotPanel" style={{ flexDirection: "column", alignItems: "flex-start" }}>
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.snapshotLabel}</b> {t.snapshotDesc}
      </span>
      <span>
        {snap.saved_at !== null
          ? t.snapshotInfo(snap.count, new Date(snap.saved_at * 1000).toLocaleString(lang === "tr" ? "tr-TR" : "en-US"))
          : t.snapshotNone}
      </span>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" disabled={saving} onClick={() => void handleSave()}>
          {saving ? t.snapshotSaving : t.snapshotSaveBtn}
        </button>
        <button type="button" disabled={resuming || snap.saved_at === null} onClick={() => void handleResume()}>
          {resuming ? t.snapshotResuming : t.snapshotResumeBtn}
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
    </div>
  );
}
