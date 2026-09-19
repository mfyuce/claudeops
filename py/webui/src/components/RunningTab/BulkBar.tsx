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
import { apiPost, apiStart, ApiError, type StartPayload } from "../../api/client";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { cliOptionsFor, LOCAL_HOST, rowKey } from "../../state/hosts";
import type { ApiResult, SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import { TabHint } from "../shared/TabHint";
import { DEFAULT_PERMISSION_MODE, defaultEffort } from "./cliDefaults";

type BulkAction = "start" | "handover" | "compact" | "stop" | "close" | "retire" | "reset";

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
  const { data, refresh } = useStatusContext();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedRows = rows.filter((r) => selection.selected.has(rowKey(r)));
  const canAct = selectedRows.length > 0 && !busy;

  const labels: Record<BulkAction, string> = {
    start: t.bulkStartBtn,
    handover: t.handoverBtn,
    compact: t.compactBtn,
    stop: t.stopBtn,
    close: t.disableBtn,
    retire: t.retireBtn,
    reset: t.resetBtn,
  };
  const explanations: Record<BulkAction, string> = {
    start: t.legendBulkStart,
    handover: t.legendHandover,
    compact: t.legendCompact,
    stop: t.legendStop,
    close: t.legendDisable,
    retire: t.legendRetire,
    reset: t.legendReset,
  };

  /** Mirrors `OptionsRow`'s untouched initial state (`../RunningTab/OptionsRow.tsx`)
   * — "default parameters" means exactly what opening a row and immediately
   * hitting "Devam Et" without changing anything would send: the session's
   * own roster/settings default model, `permission=auto`, the CLI's highest
   * effort level, same `cli`, resume (not fresh). */
  function startPayloadFor(s: SessionInfo): StartPayload {
    const cliOptions = cliOptionsFor(data, s.host, s.cli);
    return {
      name: s.name,
      host: s.host,
      // Settings' default_model is the aggregator's own preference — only
      // meaningful for a local session, same rule as OptionsRow.tsx.
      model: s.host === LOCAL_HOST ? (data?.settings.default_model[s.cli] ?? "") : "",
      permission_mode: DEFAULT_PERMISSION_MODE,
      effort: defaultEffort(cliOptions),
      cli: s.cli,
      lang,
    };
  }

  async function handleBulk(action: BulkAction) {
    if (busy) return;
    let picked = selectedRows;
    let note = "";
    if (action === "close" || action === "retire" || action === "reset") {
      // close/retire/reset can't apply to an unregistered (proc-scan-only)
      // row — skip those, tell the user which ones (original: bulkAct()'s
      // `unreg` filter). `reset` needs this too: its fresh-start half calls
      // `/api/start`, which requires an ACTIVE roster entry — an unregistered
      // row has none.
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
    for (const s of picked) {
      const name = s.name;
      setMessage(`${labels[action]}: ${done + 1}/${names.length} — ${name}…`);
      try {
        if (action === "reset") {
          // Deliberately `/api/stop` (kill only), NOT `/api/close`: close
          // also deactivates the roster entry (`want_active=False`), which
          // would make the immediately-following `/api/start` fail with
          // "not active" — stop leaves the roster entry alone, so the fresh
          // start right after it actually works.
          const stopRes = await apiPost<ApiResult>("/api/stop", { name, host: s.host, lang });
          if (!stopRes.ok) {
            errs.push(`${name}: ${stopRes.error}`);
          } else {
            const startRes = await apiStart({ ...startPayloadFor(s), fresh: true });
            if (!startRes.ok) errs.push(`${name}: ${startRes.error}`);
          }
        } else {
          const res =
            action === "start"
              ? await apiStart(startPayloadFor(s))
              : await apiPost<ApiResult>(`/api/${action}`, { name, host: s.host, lang });
          if (!res.ok) errs.push(`${name}: ${res.error}`);
        }
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
    selection.replace(rows.filter((s) => s.needs_ho === true).map(rowKey));
  }

  // "Dikkat gerekenleri seç" (2026-09-15, AND'e çevrildi — kullanıcı: "or
  // degil and"): idle (busy===false, EXPLICITLY not-busy — `null`/unknown
  // atlanır, needs_ho/client_count'taki AYNI "bilinmeyen ≠ güvenli-bilinen"
  // duruşu) VE AYRICA tmux'un scrollback tavanına yaklaşmış olması
  // (`history_warn_at`, Settings — varsayılan 1900, `HISTORY_LIMIT`in
  // kendisi 2000 ve sabit) — İKİSİ BİRDEN gerekir, ne salt idle ne salt
  // uzun-scrollback tek başına yeterli değil.
  function handleSelectAttention() {
    const historyWarnAt = data?.settings.history_warn_at ?? 1900;
    selection.replace(
      rows
        .filter((s) => s.busy === false && s.history_size != null && s.history_size >= historyWarnAt)
        .map(rowKey),
    );
  }

  const legendRows: [string, string][] =
    tab === "running"
      ? [
          [t.resetBtn, t.legendReset],
          [t.handoverBtn, t.legendHandover],
          [t.compactBtn, t.legendCompact],
          [t.stopBtn, t.legendStop],
          [t.disableBtn, t.legendDisable],
          [t.retireBtn, t.legendRetire],
        ]
      : [
          [t.bulkStartBtn, t.legendBulkStart],
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
              title={t.legendReset}
              onClick={() => void handleBulk("reset")}
            >
              {t.resetBtn}
            </button>
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
            <button type="button" className="selho" disabled={busy} title={t.attentionHint} onClick={handleSelectAttention}>
              {t.selectAttention}
            </button>
          </>
        )}
        {tab === "registered" && (
          <>
            <button
              type="button"
              className="start"
              disabled={!canAct}
              title={t.legendBulkStart}
              onClick={() => void handleBulk("start")}
            >
              {t.bulkStartBtn}
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
          </>
        )}
        <span className="bulkmsg">{message}</span>
      </div>
      <TabHint>
        <div className="legend">
          {legendRows.map(([k, v], i) => (
            <Fragment key={k}>
              {i > 0 && <br />}
              <b>{k}</b> — {v}
            </Fragment>
          ))}
        </div>
      </TabHint>
    </>
  );
}
