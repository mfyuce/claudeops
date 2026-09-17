/**
 * The `cwd` column's click-to-expand/collapse cell — replaces the
 * original's `onclick="this.classList.toggle('expanded')"` (web.py
 * `runningRow()`/`registeredRow()`/`groupTable()`, all three inline the
 * same pattern). Shared by `SessionRow`, `RegisteredTab`'s row, and
 * `GroupTable`'s row (Disabled/Retired).
 *
 * `name` (2026-09-17, user: "expand rowlarda full path var. aslinda
 * registered isim + full path olmali") — collapsed stays cwd-only (the
 * row's own name column is right there, and the collapsed cell is
 * truncated to almost nothing anyway, see `global.css`'s `max-width:1px`);
 * expanded prefixes the registered name, since an expanded path can wrap
 * across several lines (`word-break:break-all`) and with more than one
 * row expanded at once, a wall of similar-looking paths is otherwise hard
 * to trace back to which session it belongs to. Optional (all 3 current
 * callers pass it) so this cell degrades gracefully if a future caller
 * genuinely has no name.
 */

import { useState } from "react";
import { useLang } from "../../i18n/LangContext";

export function CwdCell({ cwd, name }: { cwd: string; name?: string }) {
  const { t } = useLang();
  const [expanded, setExpanded] = useState(false);
  return (
    <td className={expanded ? "cwd expanded" : "cwd"} title={t.cwdHint} onClick={() => setExpanded((v) => !v)}>
      {expanded && name ? `${name}: ${cwd}` : cwd}
    </td>
  );
}
