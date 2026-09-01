/**
 * The `cwd` column's click-to-expand/collapse cell — replaces the
 * original's `onclick="this.classList.toggle('expanded')"` (web.py
 * `runningRow()`/`registeredRow()`/`groupTable()`, all three inline the
 * same pattern). Shared by `SessionRow` and `RegisteredTab`'s row now;
 * `GroupTable` (Disabled/Retired, a later stage) reuses it too.
 */

import { useState } from "react";
import { useLang } from "../../i18n/LangContext";

export function CwdCell({ cwd }: { cwd: string }) {
  const { t } = useLang();
  const [expanded, setExpanded] = useState(false);
  return (
    <td className={expanded ? "cwd expanded" : "cwd"} title={t.cwdHint} onClick={() => setExpanded((v) => !v)}>
      {cwd}
    </td>
  );
}
