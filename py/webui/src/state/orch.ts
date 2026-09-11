/**
 * Small pure helpers for TOBEDECIDED#15 Phase 1 (workers-only
 * orchestration) — kept out of the components, same reasoning as
 * `state/hosts.ts`'s own header comment (behavior, not types).
 */

import { rowKey } from "./hosts";
import type { SessionInfo } from "../api/types";

/** Client-side mirror of `web_orch._eligible_index()`'s triple (running +
 * tmux-backed + `has_conversation()`) — used only to pre-filter the "add
 * selected" picker so the confirm dialog doesn't list an obviously-wrong
 * pick. The backend's own `_preflight` remains the real authority (a
 * session can still go stale between a click here and the POST landing).
 * `has_conversation()` defaults `True` and is only overridden (`False`) by
 * `providers/shell_provider.py`, so `cli !== "shell"` mirrors it exactly
 * for the provider set that exists today.
 *
 * Remote-host sessions (TOBEDECIDED#20, 2026-09-11) are eligible on the
 * same terms — no `host === LOCAL_HOST` gate anymore, matching the backend
 * (`_eligible_index()` now includes them too, same `running`+`tmux` bar).
 * `has_conversation()` isn't independently re-checked for a remote row
 * here either, same tradeoff the backend makes (an extra proxy round-trip
 * per candidate isn't worth it just to pre-filter a picker whose real
 * authority is `_preflight` anyway). */
export function isOrchEligible(s: SessionInfo): boolean {
  return s.running && s.tmux && s.cli !== "shell";
}

/** The subset of `sessions` that's both checked (in the shared `selection`
 * Set every tab reads/writes) and orchestration-eligible — the exact set
 * `OrchTab`'s "add selected" button turns into worker lineup entries. */
export function eligibleSelectedSessions(sessions: SessionInfo[], selected: Set<string>): SessionInfo[] {
  return sessions.filter((s) => selected.has(rowKey(s)) && isOrchEligible(s));
}
