/**
 * Shared collapsible group-header `<tr>` — extracted from
 * `RegisteredTab.tsx`'s original `GroupHeaderRow` so `RunningTab.tsx`/
 * `GroupTable.tsx` can reuse it. `extra` is an escape hatch for
 * RegisteredTab's cross-tab "something in this group is running" badge,
 * which needs data (the full running+stopped session set) this generic
 * component has no reason to know about.
 */
import type { ReactNode } from "react";
import { useLang } from "../../i18n/LangContext";
import { LOCAL_HOST } from "../../state/hosts";

interface GroupHeaderRowProps {
  host: string;
  cwd: string;
  count: number;
  colSpan: number;
  collapsed: boolean;
  onToggle: () => void;
  extra?: ReactNode;
}

export function GroupHeaderRow({ host, cwd, count, colSpan, collapsed, onToggle, extra }: GroupHeaderRowProps) {
  const { t } = useLang();
  return (
    <tr className="group-header" onClick={onToggle}>
      <td colSpan={colSpan}>
        <span className="toggle">{collapsed ? "▸" : "▾"}</span>
        {cwd} ({count})
        {host !== LOCAL_HOST && (
          <span className="cli-badge" title={t.hostBadgeHint(host)}>
            {host}
          </span>
        )}
        {extra}
      </td>
    </tr>
  );
}
