/**
 * Replaces `renderLayoutBox()` + `doLayout()` (web.py ~2520-2573).
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
import { apiLayout, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

export function LayoutTab() {
  const { t, lang } = useLang();
  const { data } = useStatusContext();

  const [pin, setPin] = useState("");
  const [groups, setGroups] = useState("");
  const [claudeOnly, setClaudeOnly] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  if (!data) return null;
  const missing = data.layout_missing_deps;

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
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
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
          <span className="opts-hint">({t.layoutDesc})</span>
        )}
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
