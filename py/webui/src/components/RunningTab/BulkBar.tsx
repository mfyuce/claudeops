/**
 * Replaces `bulkBar()` + `bulkAct()` (web.py ~1618-1695). Owns
 * bulk-busy/message locally (`BULK_BUSY`/`BULK_MSG` were module-level
 * globals in the original — here they're this component's own
 * `useState`, which is fine: `BulkBar` itself isn't something that needs
 * to survive being unmounted, unlike `OptionsRow`/`AdoptRow`).
 *
 * Note the per-item error text in `handleBulk` deliberately does NOT go
 * through `describeApiError()` (`../../api/errors.ts`) — the original's
 * `bulkAct()` has its own, less-processed error format (bare literal
 * `"401"`, and the unexpected-response text with no `requestFailed`
 * prefix) that's different from `call()`'s alert-text convention used by
 * `OptionsRow`/`AdoptRow`. Reproduced here exactly rather than reusing the
 * other helper, since the two really are different strings in the
 * original, not an arbitrary inconsistency to "fix".
 */

import { Fragment, useState } from "react";
import { apiPost, ApiError } from "../../api/client";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import type { ApiResult, SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";

type BulkAction = "handover" | "compact" | "stop" | "close" | "retire";

interface BulkBarProps {
  tab: "running" | "registered";
  /** The current tab's full row set (not just the selected ones) — needed
   * to resolve which selected names are actually visible here (mirrors
   * the original's `rows.filter(r => SEL.has(r.name))`) and for "select
   * needs-ho". */
  rows: SessionInfo[];
  selection: SelectionControls;
}

export function BulkBar({ tab, rows, selection }: BulkBarProps) {
  const { t, lang } = useLang();
  const { refresh } = useStatusContext();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedRows = rows.filter((r) => selection.selected.has(r.name));
  const canAct = selectedRows.length > 0 && !busy;

  const labels: Record<BulkAction, string> = {
    handover: t.handoverBtn,
    compact: t.compactBtn,
    stop: t.stopBtn,
    close: t.disableBtn,
    retire: t.retireBtn,
  };
  const explanations: Record<BulkAction, string> = {
    handover: t.legendHandover,
    compact: t.legendCompact,
    stop: t.legendStop,
    close: t.legendDisable,
    retire: t.legendRetire,
  };

  async function handleBulk(action: BulkAction) {
    if (busy) return;
    let picked = selectedRows;
    let note = "";
    if (action === "close" || action === "retire") {
      // close/retire can't apply to an unregistered (proc-scan-only) row —
      // skip those, tell the user which ones (original: bulkAct()'s
      // `unreg` filter).
      const unreg = picked.filter((s) => s.registered === false).map((s) => s.name);
      if (unreg.length) {
        picked = picked.filter((s) => s.registered !== false);
        note = "\n\n" + t.bulkSkippedUnreg + unreg.join(", ");
      }
    }
    const names = picked.map((s) => s.name);
    if (!names.length) {
      if (note) window.alert(note.trim());
      return;
    }
    if (!window.confirm(t.bulkConfirm(labels[action], explanations[action], names) + note)) return;

    setBusy(true);
    const errs: string[] = [];
    let done = 0;
    for (const name of names) {
      setMessage(`${labels[action]}: ${done + 1}/${names.length} — ${name}…`);
      try {
        const res = await apiPost<ApiResult>(`/api/${action}`, { name, lang });
        if (!res.ok) errs.push(`${name}: ${res.error}`);
      } catch (e) {
        if (e instanceof ApiError) {
          if (e.status === 401) errs.push(`${name}: 401`);
          else errs.push(`${name}: ${t.unexpectedResponse(e.status)}`);
        } else {
          errs.push(`${name}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      done++;
    }
    setBusy(false);
    setMessage(t.bulkDone(names.length - errs.length, errs.length) + (errs.length ? "\n" + errs.join("\n") : ""));
    selection.replace([]);
    refresh();
  }

  function handleSelectNeedsHo() {
    // Original: `for (const s of LAST.sessions) if (s.running &&
    // s.needs_ho === true) SEL.add(s.name);` over ALL sessions — but this
    // button only renders for tab === "running", and `rows` there is
    // already exactly `sessions.filter(s => s.running)`, so filtering
    // just `needs_ho === true` over `rows` is equivalent.
    selection.replace(rows.filter((s) => s.needs_ho === true).map((s) => s.name));
  }

  const legendRows: [string, string][] =
    tab === "running"
      ? [
          [t.handoverBtn, t.legendHandover],
          [t.compactBtn, t.legendCompact],
          [t.stopBtn, t.legendStop],
          [t.disableBtn, t.legendDisable],
          [t.retireBtn, t.legendRetire],
        ]
      : [
          [t.disableBtn, t.legendDisable],
          [t.retireBtn, t.legendRetire],
        ];

  return (
    <>
      <div className="bulkbar">
        <span className="selcount">
          {t.selWord}: {selectedRows.length}
        </span>
        {tab === "running" && (
          <>
            <button
              type="button"
              className="handover"
              disabled={!canAct}
              title={t.legendHandover}
              onClick={() => void handleBulk("handover")}
            >
              {t.handoverBtn}
            </button>
            <button
              type="button"
              className="handover"
              disabled={!canAct}
              title={t.legendCompact}
              onClick={() => void handleBulk("compact")}
            >
              {t.compactBtn}
            </button>
            <button
              type="button"
              className="stop"
              disabled={!canAct}
              title={t.legendStop}
              onClick={() => void handleBulk("stop")}
            >
              {t.stopBtn}
            </button>
            <button
              type="button"
              className="closebtn"
              disabled={!canAct}
              title={t.legendDisable}
              onClick={() => void handleBulk("close")}
            >
              {t.disableBtn}
            </button>
            <button
              type="button"
              className="retire"
              disabled={!canAct}
              title={t.legendRetire}
              onClick={() => void handleBulk("retire")}
            >
              {t.retireBtn}
            </button>
            <button type="button" className="selho" disabled={busy} title={t.hoHint} onClick={handleSelectNeedsHo}>
              {t.selectNeedsHo}
            </button>
          </>
        )}
        {tab === "registered" && (
          <>
            <button
              type="button"
              className="closebtn"
              disabled={!canAct}
              title={t.legendDisable}
              onClick={() => void handleBulk("close")}
            >
              {t.disableBtn}
            </button>
            <button
              type="button"
              className="retire"
              disabled={!canAct}
              title={t.legendRetire}
              onClick={() => void handleBulk("retire")}
            >
              {t.retireBtn}
            </button>
          </>
        )}
        <span className="bulkmsg">{message}</span>
      </div>
      <div className="legend">
        {legendRows.map(([k, v], i) => (
          <Fragment key={k}>
            {i > 0 && <br />}
            <b>{k}</b> — {v}
          </Fragment>
        ))}
      </div>
    </>
  );
}
