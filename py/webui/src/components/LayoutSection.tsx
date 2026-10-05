/**
 * Replaces `renderLayoutBox()` + `doLayout()` (web.py ~2520-2573). Originally
 * its own top-level "Layout" tab; moved into Settings 2026-10-05 (user: fits
 * better here, reads as one coherent settings UI rather than a lone action
 * tab) — same component, just mounted as a Settings sub-tab now (see
 * `SettingsTab.tsx`'s header comment). `layout_grid` moved in with it: it
 * used to live in Settings' "general" panel even though it's the exact same
 * feature as the pin/groups/apply controls below, just split across two
 * places — this component now owns the save for it directly via
 * `apiSaveSettings`, the same pattern `SettingsTab.tsx`'s own `save()` uses.
 *
 * `doLayout()`'s error handling is more layered than a first read
 * suggests, and reproduced exactly here rather than just calling
 * `describeApiError()` uniformly:
 *  - a 401 response: bare `alert(t('authErrorShort'))` — the result `<pre>`
 *    is left exactly as it was (cleared, since it's wiped right before the
 *    request fires) — NOT written into the result box like every other
 *    failure. `ApiError.status === 401` is special-cased below to match.
 *  - a non-401 unexpected response (`safeJson()` throwing) or a genuine
 *    network exception: both funnel into the same outer `catch` in the
 *    original, composing `'✗ ' + t('requestFailed') + e.message` — this is
 *    exactly what `describeApiError()` already produces for a non-401
 *    `ApiError` or a plain exception, so it's reused here with a `'✗ '`
 *    prefix added for the result-box display.
 *  - a well-formed `{ok:false, error}` business response (HTTP 200, valid
 *    JSON, action itself failed): bare `'✗ ' + d.error`, no `requestFailed`
 *    wrapping — matches `res.ok === false` below.
 */

import { useState } from "react";
import { apiLayout, apiSaveSettings, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { TabHint } from "./shared/TabHint";

export function LayoutSection() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  const [pin, setPin] = useState("");
  const [groups, setGroups] = useState("");
  const [claudeOnly, setClaudeOnly] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  if (!data) return null;
  const missing = data.layout_missing_deps;

  async function handleGridChange(grid: number) {
    try {
      const res = await apiSaveSettings({ layout_grid: grid, lang });
      if (!res.ok) setResult(`✗ ${res.error}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) showToast(t.authErrorShort);
      else setResult(`✗ ${describeApiError(e, t)}`);
    }
    refresh();
  }

  async function handleApply() {
    setBusy(true);
    setResult("");
    const groupList = groups
      .split("|")
      .map((g) => g.trim())
      .filter((g) => g);
    try {
      const res = await apiLayout({ pin: pin.trim(), groups: groupList, claude_only: claudeOnly, dry_run: dryRun, lang });
      if (res.ok) {
        const lines = [`${dryRun ? "[dry-run] " : ""}${res.total} ${t.windowsWord}, ${res.skipped} ${t.skippedWord}`];
        for (const a of res.assignments) lines.push(`  ${a.name} → ws${a.ws} (${a.x},${a.y})`);
        setResult(lines.join("\n"));
      } else {
        setResult(`✗ ${res.error}`);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) showToast(t.authErrorShort);
      else setResult(`✗ ${describeApiError(e, t)}`);
    }
    setBusy(false);
  }

  return (
    <>
      <div className="opts" id="layoutPanel">
        {missing.length ? (
          <span className="opts-hint" style={{ color: "var(--red)" }}>
            {t.layoutMissingPrefix}
            {missing.join(", ")}
            {t.layoutMissingSuffix}
            {missing.join(" ")}
          </span>
        ) : (
          <TabHint>{t.layoutDesc}</TabHint>
        )}
        <label title={t.layoutGridHint}>
          {t.layoutGridLabel}
          <select value={data.settings.layout_grid} onChange={(e) => void handleGridChange(Number(e.target.value))}>
            <option value={2}>2 (2×1)</option>
            <option value={4}>4 (2×2)</option>
            <option value={8}>8 (4×2)</option>
          </select>
        </label>
        <label>
          {t.layoutPinLabel}
          <input type="text" placeholder="co,rustrino,anomaly,iggy" value={pin} onChange={(e) => setPin(e.target.value)} />
        </label>
        <label>
          {t.layoutGroupsLabel}
          <input
            type="text"
            placeholder="hc,hcr,evolvi | vc,vrk"
            value={groups}
            onChange={(e) => setGroups(e.target.value)}
          />
        </label>
        <label className="fresh-toggle">
          <input type="checkbox" checked={claudeOnly} onChange={(e) => setClaudeOnly(e.target.checked)} />{" "}
          {t.layoutClaudeOnly}
        </label>
        <label className="fresh-toggle">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> {t.layoutDryRun}
        </label>
        <button type="button" className="go" disabled={busy || missing.length > 0} onClick={() => void handleApply()}>
          {busy ? t.layoutApplying : t.layoutApply}
        </button>
      </div>
      <pre className="layout-result">{result}</pre>
    </>
  );
}
