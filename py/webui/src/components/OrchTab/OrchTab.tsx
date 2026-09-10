/**
 * TOBEDECIDED#15 Phase 1 — "Ekip"/Team tab: workers-only orchestration.
 * Self-contained (own local state, own `getOrchRun`/`getOrchRuns` fetches
 * only while relevant), following the `HostsSection.tsx` precedent of not
 * stuffing heavier per-tab data into `StatusContext`. The lightweight
 * `data.orch` slice (draft/active summary/last 5 runs) already rides the
 * existing WS push — this component reacts to THAT to know when to fetch
 * the fuller `OrchRun` detail, rather than polling on its own timer (plan:
 * "no new polling").
 *
 * Only one role exists in Phase 1 (worker) — no role picker, no changes to
 * `BulkBar`/`SessionRow`. Lineup entries come from whatever the user has
 * already checked in the Running tab (the SAME shared `selection` Set),
 * turned into worker rows by one button in `LineupEditor`.
 */

import { useEffect, useRef, useState } from "react";
import { apiOrchCancel, apiOrchSaveDraft, apiOrchStart, getOrchRun, getOrchRuns } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { isOrchEligible } from "../../state/orch";
import { rowKey } from "../../state/hosts";
import type { OrchDraftParticipant, OrchRun } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import { LineupEditor } from "./LineupEditor";
import { RunView } from "./RunView";

const DEFAULT_WORKER_TIMEOUT = 900;

interface OrchTabProps {
  selection: SelectionControls;
}

export function OrchTab({ selection }: OrchTabProps) {
  const { t } = useLang();
  const { data, refresh } = useStatusContext();

  // Seeded from the server-persisted draft exactly once per mount — after
  // that, this component's own edits (add/remove) are the source of truth,
  // each immediately persisted back via `apiOrchSaveDraft` so a reload (or
  // another tab/device) picks up the same lineup next time.
  const [lineup, setLineup] = useState<OrchDraftParticipant[]>([]);
  const seededRef = useRef(false);
  useEffect(() => {
    if (!seededRef.current && data) {
      setLineup(data.orch.draft);
      seededRef.current = true;
    }
  }, [data]);

  const [task, setTask] = useState("");
  const [verdictHint, setVerdictHint] = useState("");
  const [workerTimeout, setWorkerTimeout] = useState(DEFAULT_WORKER_TIMEOUT);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");

  // Live run: `activeId`/`activeStatus`/`activeCount` ride the existing WS
  // push (part of `data`); the full `OrchRun` (with per-worker result text)
  // is fetched only when one of those three actually changes.
  const activeId = data?.orch.active?.id ?? null;
  const activeStatus = data?.orch.active?.status;
  const activeCount = data?.orch.active?.result_count;
  const [activeDetail, setActiveDetail] = useState<OrchRun | null>(null);
  useEffect(() => {
    if (!activeId) {
      setActiveDetail(null);
      return;
    }
    let cancelled = false;
    void getOrchRun(activeId).then((res) => {
      if (!cancelled && res.ok) setActiveDetail(res.run);
    });
    return () => {
      cancelled = true;
    };
  }, [activeId, activeStatus, activeCount]);

  // History: a past run is finished, so its detail is fetched once on
  // click, not re-fetched reactively like the active run above.
  const [viewingRunId, setViewingRunId] = useState<string | null>(null);
  const [viewingDetail, setViewingDetail] = useState<OrchRun | null>(null);
  async function handleView(runId: string) {
    setViewingRunId(runId);
    setViewingDetail(null);
    try {
      const res = await getOrchRun(runId);
      if (res.ok) setViewingDetail(res.run);
    } catch {
      // History is a secondary panel — same non-fatal handling as
      // HostsSection.tsx's load(): leave whatever was showing before.
    }
  }

  const [fullHistory, setFullHistory] = useState<OrchRun[] | null>(null);
  async function handleShowMoreHistory() {
    try {
      const res = await getOrchRuns();
      if (res.ok) setFullHistory(res.runs);
    } catch {
      // same non-fatal handling as above
    }
  }

  function persistLineup(next: OrchDraftParticipant[]) {
    setLineup(next);
    void apiOrchSaveDraft(next);
  }

  function handleAddSelected() {
    if (!data) return;
    const selectedRows = data.sessions.filter((s) => selection.selected.has(rowKey(s)));
    if (!selectedRows.length) {
      window.alert(t.orchNoSelectionMsg);
      return;
    }
    const eligible = selectedRows.filter(isOrchEligible);
    const skipped = selectedRows.filter((s) => !isOrchEligible(s)).map((s) => s.name);
    const merged = [...lineup];
    for (const s of eligible) {
      if (!merged.some((p) => p.host === s.host && p.name === s.name)) {
        merged.push({ role: "worker", host: s.host, name: s.name, cli: s.cli });
      }
    }
    persistLineup(merged);
    selection.replace([]);
    if (skipped.length) window.alert(t.orchSkippedIneligible(skipped.join(", ")));
  }

  function handleRemove(host: string, name: string) {
    persistLineup(lineup.filter((p) => !(p.host === host && p.name === name)));
  }

  async function handleStart() {
    if (!lineup.length || !task.trim() || starting) return;
    if (!window.confirm(t.orchRunConfirm(lineup.map((p) => p.name), task.trim()))) return;
    setStarting(true);
    setStartError("");
    try {
      const res = await apiOrchStart({
        participants: lineup.map((p) => ({ role: "worker" as const, host: p.host, name: p.name })),
        task: task.trim(),
        verdict_hint: verdictHint.trim() || undefined,
        worker_timeout: workerTimeout,
      });
      if (!res.ok) setStartError(res.error);
      else setTask(""); // lineup/verdictHint/timeout stay — re-running the same team is a click away
    } catch (e) {
      setStartError(describeApiError(e, t));
    } finally {
      setStarting(false);
      refresh();
    }
  }

  async function handleCancelActive() {
    if (!activeId || !window.confirm(t.orchCancelRunConfirm)) return;
    try {
      const res = await apiOrchCancel(activeId);
      if (!res.ok) window.alert(res.error);
    } catch (e) {
      window.alert(describeApiError(e, t));
    }
    refresh();
  }

  if (!data) return null;

  const historyList = fullHistory ?? data.orch.recent;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".8rem" }}>
      <span className="opts-hint">{t.orchDesc}</span>

      {activeId ? (
        <RunView run={activeDetail} onCancel={() => void handleCancelActive()} />
      ) : viewingRunId ? (
        <>
          <button type="button" onClick={() => setViewingRunId(null)}>
            {t.orchBackBtn}
          </button>
          <RunView run={viewingDetail} />
        </>
      ) : (
        <>
          <LineupEditor lineup={lineup} selection={selection} onAddSelected={handleAddSelected} onRemove={handleRemove} />
          <div className="opts">
            <label style={{ flexBasis: "100%" }}>
              {t.orchTaskLabel}
              <textarea
                rows={3}
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder={t.orchTaskPlaceholder}
              />
            </label>
            <label>
              {t.orchVerdictHintLabel}
              <input
                type="text"
                value={verdictHint}
                onChange={(e) => setVerdictHint(e.target.value)}
                placeholder={t.orchVerdictHintPlaceholder}
              />
            </label>
            <label>
              {t.orchTimeoutLabel}
              <input
                type="text"
                inputMode="numeric"
                value={String(workerTimeout)}
                onChange={(e) => setWorkerTimeout(Number(e.target.value.replace(/\D/g, "")) || DEFAULT_WORKER_TIMEOUT)}
              />
            </label>
            {startError && (
              <div className="warn-banner">
                {t.requestFailed}
                {startError}
              </div>
            )}
            <button
              type="button"
              className="start"
              disabled={!lineup.length || !task.trim() || starting}
              onClick={() => void handleStart()}
            >
              {starting ? t.orchStarting : t.orchRunBtn}
            </button>
          </div>
        </>
      )}

      <div>
        <b>{t.orchHistoryTitle}</b>
        {historyList.length === 0 ? (
          <div className="opts-hint">{t.orchHistoryEmpty}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: ".3rem", marginTop: ".3rem" }}>
            {historyList.map((r) => (
              <div key={r.id} style={{ display: "flex", alignItems: "center", gap: ".5rem", fontSize: ".82rem" }}>
                <span style={{ color: "var(--muted)" }}>{new Date(r.created_at * 1000).toLocaleString()}</span>
                <span>{t.orchStatusLabel(r.status)}</span>
                <span
                  style={{
                    color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap", maxWidth: "260px",
                  }}
                >
                  {r.task}
                </span>
                <button type="button" onClick={() => void handleView(r.id)}>
                  {t.orchViewBtn}
                </button>
              </div>
            ))}
          </div>
        )}
        {!fullHistory && (
          <button type="button" style={{ marginTop: ".3rem" }} onClick={() => void handleShowMoreHistory()}>
            {t.orchShowMoreBtn}
          </button>
        )}
      </div>
    </div>
  );
}
