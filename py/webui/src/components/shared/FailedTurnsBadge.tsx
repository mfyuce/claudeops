/**
 * "N failed turns" badge of a ucli session (`SessionInfo.failed_turns`, see `_live_failed_turns` in the backend): turns
 * that reached the model and then died with an error leave a record in `.ucli/chat/failed/`, which the panel's
 * `turns: 0` never showed. Rendered only when at least one record exists; the tooltip carries the newest error. Red,
 * information only, nothing is stopped.
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionFailedTurns } from "../../api/types";

export function FailedTurnsBadge({ failed }: { failed: SessionFailedTurns }) {
  const { t } = useLang();
  if (!failed.count) return null;
  return (
    <span className="failed-badge" title={t.failedTurnsHint(failed.count, failed.last_error ?? "")}>
      {t.failedTurnsBadge(failed.count)}
    </span>
  );
}
