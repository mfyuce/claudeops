/**
 * Replaces the original `hoCell(s)` (web.py ~1703-1707). Only
 * `runningRow()` used this — `registeredRow()`/`groupTable()` don't show
 * a needs-ho column.
 */

import { useLang } from "../../i18n/LangContext";
import type { SessionInfo } from "../../api/types";

export function HoCell({ session }: { session: SessionInfo }) {
  const { t } = useLang();
  if (session.needs_ho === true) {
    return (
      <td className="hocell">
        <span className="ho-yes" title={t.hoHint}>
          ho!
        </span>
      </td>
    );
  }
  if (session.needs_ho === false) {
    return (
      <td className="hocell">
        <span className="ho-no" title={t.hoHint}>
          —
        </span>
      </td>
    );
  }
  return (
    <td className="hocell">
      <span className="ho-no" title={t.hoHint}>
        {t.hoUnknown}
      </span>
    </td>
  );
}
