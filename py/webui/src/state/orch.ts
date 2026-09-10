/**
 * Small pure helpers for TOBEDECIDED#15 Phase 1 (workers-only
 * orchestration) — kept out of the components, same reasoning as
 * `state/hosts.ts`'s own header comment (behavior, not types).
 */

import { rowKey, LOCAL_HOST } from "./hosts";
import type { SessionInfo } from "../api/types";

/** Client-side mirror of `web_orch._eligible_index()`'s triple (running +
 * tmux-backed + `has_conversation()`) — used only to pre-filter the "add
 * selected" picker so the confirm dialog doesn't list an obviously-wrong
 * pick. The backend's own `_preflight` remains the real authority (a
 * session can still go stale between a click here and the POST landing).
 * `has_conversation()` defaults `True` and is only overridden (`False`) by
 * `providers/shell_provider.py`, so `cli !== "shell"` mirrors it exactly
 * for the provider set that exists today. */
export function isOrchEligible(s: SessionInfo): boolean {
  return s.running && s.host === LOCAL_HOST && s.tmux && s.cli !== "shell";
}

/** The subset of `sessions` that's both checked (in the shared `selection`
 * Set every tab reads/writes) and orchestration-eligible — the exact set
 * `OrchTab`'s "add selected" button turns into worker lineup entries. */
export function eligibleSelectedSessions(sessions: SessionInfo[], selected: Set<string>): SessionInfo[] {
  return sessions.filter((s) => selected.has(rowKey(s)) && isOrchEligible(s));
}
