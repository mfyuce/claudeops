/**
 * TOBEDECIDED#15 Phase 2 — "Ekip"/Team tab: controller/worker/decider
 * orchestration. Self-contained (own local state, own `getOrchRun`/
 * `getOrchRuns` fetches only while relevant), following the
 * `HostsSection.tsx` precedent of not stuffing heavier per-tab data into
 * `StatusContext`. The lightweight `data.orch` slice (draft/active
 * summary/last 5 runs) already rides the existing WS push — this
 * component reacts to THAT to know when to fetch the fuller `OrchRun`
 * detail, rather than polling on its own timer (plan: "no new polling").
 *
 * Lineup entries come from whatever the user has already checked in the
 * Running tab (the SAME shared `selection` Set), added as "worker" by
 * default — promoting one to controller/decider is a per-row pick in
 * `LineupEditor`, enforced here as ≤1-each (picking a role that's already
 * taken demotes the previous holder back to "worker"). No `BulkBar`/
 * `SessionRow` changes needed.
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

  // Persists to the server whenever the lineup changes locally, decoupled
  // from the state update itself so every mutator below can use React's
  // functional `setLineup(prev => ...)` form safely — same reasoning as
  // `state/selection.ts`'s own Set mutations, which never compute the next
  // value from a closed-over variable either (a mutator that instead reads
  // the outer `lineup` directly can silently lose an update if two calls
  // fire before React re-renders between them, e.g. rapid consecutive
  // clicks). Fires once redundantly right after the initial server-seed
  // effect below (re-POSTs what it just loaded) — harmless, not worth
  // guarding against for one extra small write per mount.
  useEffect(() => {
    if (seededRef.current) void apiOrchSaveDraft(lineup);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineup]);

  function handleAddSelected() {
    if (!data) return;
    const selectedRows = data.sessions.filter((s) => selection.selected.has(rowKey(s)));
    if (!selectedRows.length) {
      window.alert(t.orchNoSelectionMsg);
      return;
    }
    const eligible = selectedRows.filter(isOrchEligible);
    const skipped = selectedRows.filter((s) => !isOrchEligible(s)).map((s) => s.name);
    setLineup((prev) => {
      const merged = [...prev];
      for (const s of eligible) {
        if (!merged.some((p) => p.host === s.host && p.name === s.name)) {
          merged.push({ role: "worker", host: s.host, name: s.name, cli: s.cli });
        }
      }
      return merged;
    });
    selection.replace([]);
    if (skipped.length) window.alert(t.orchSkippedIneligible(skipped.join(", ")));
  }

  function handleRemove(host: string, name: string) {
    setLineup((prev) => prev.filter((p) => !(p.host === host && p.name === name)));
  }

  /** ≤1 controller/≤1 decider — picking one of those roles demotes whoever
   * held it before back to "worker" (mirrors the backend's own `_preflight`
   * cap, checked proactively here so the confirm dialog never shows two). */
  function handleRoleChange(host: string, name: string, role: string) {
    setLineup((prev) =>
      prev.map((p) => {
        if (p.host === host && p.name === name) return { ...p, role };
        if ((role === "controller" || role === "decider") && p.role === role) return { ...p, role: "worker" };
        return p;
      }),
    );
  }

  const hasWorker = lineup.some((p) => p.role === "worker");

  async function handleStart() {
    if (!hasWorker || !task.trim() || starting) return;
    const labeled = lineup.map((p) => `${p.name} (${t.orchRoleLabel(p.role)})`);
    if (!window.confirm(t.orchRunConfirm(labeled, task.trim()))) return;
    setStarting(true);
    setStartError("");
    try {
      const res = await apiOrchStart({
        participants: lineup.map((p) => ({ role: p.role, host: p.host, name: p.name })),
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
          <LineupEditor
            lineup={lineup}
            selection={selection}
            onAddSelected={handleAddSelected}
            onRemove={handleRemove}
            onRoleChange={handleRoleChange}
          />
          {lineup.length > 0 && !hasWorker && <div className="warn-banner">{t.orchNeedsWorkerMsg}</div>}
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
              disabled={!hasWorker || !task.trim() || starting}
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
