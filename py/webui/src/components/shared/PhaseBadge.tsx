/**
 * What a running ucli session's current model call is doing right now (`SessionInfo.phase`, see `_live_phase` in the
 * backend, fed by ucli's `--status-file` `phase`): waiting for the response, thinking, writing, or waiting to retry.
 * Before this the panel showed the LAST call but not what the session was doing NOW, so a stuck or retrying call looked
 * the same as a slow one. Rendered only while a call is in flight (`phase` absent/null otherwise, also for a CLI or a
 * ucli binary without phases): never a placeholder. Green = progress (the model is thinking or writing, bytes are
 * arriving); amber = a retry or rate-limit wait, or a response that has not come for 5+ minutes; red = 10+ minutes
 * without a response. Colour only, nothing is stopped. `thinking`/`writing` need the session to run with `--stream`.
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionPhase } from "../../api/types";

export function PhaseBadge({ phase }: { phase: SessionPhase }) {
  const { t } = useLang();
  const warn = phase.warn ?? 0;
  const live = phase.name === "thinking" || phase.name === "writing";
  const cls = `phase-badge${warn >= 2 ? " warn-2" : warn === 1 ? " warn-1" : live ? " live" : ""}`;
  return (
    <span className={cls} title={t.phaseHint(phase)}>
      {t.phaseBadge(phase)}
    </span>
  );
}
