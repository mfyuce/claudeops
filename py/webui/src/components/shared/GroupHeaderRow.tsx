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
  /** The group's registered/blueprint name (callers derive it from their
   * own item shape — instance rows carry it as `blueprint`, a roster row's
   * own `name` already IS it — see the 4 call sites). Optional/falsy is
   * handled gracefully (just the count, no name prefix) since a future
   * caller may genuinely have no such concept. */
  name?: string | null;
  count: number;
  colSpan: number;
  collapsed: boolean;
  onToggle: () => void;
  extra?: ReactNode;
  /** CLIs of the group's rows. Shown (one badge each) only when the group MIXES two or more, so a project's claude
   * session and its ucli trial sessions that share a cwd are told apart at a glance (TODO 2026-10-20 (4)). */
  clis?: string[];
}

export function GroupHeaderRow({ host, cwd, name, count, colSpan, collapsed, onToggle, extra, clis }: GroupHeaderRowProps) {
  const { t } = useLang();
  const mixed = Array.from(new Set((clis ?? []).filter(Boolean))).sort();
  return (
    <tr className="group-header" onClick={onToggle}>
      <td colSpan={colSpan}>
        <div className="group-header-inner">
          <span className="toggle">{collapsed ? "▸" : "▾"}</span>
          <span className="group-name">{name ? `${name} (${count}):` : `(${count})`}</span>
          <span className="group-cwd" title={cwd}>
            {cwd}
          </span>
          {host !== LOCAL_HOST && (
            <span className="cli-badge" title={t.hostBadgeHint(host)}>
              {host}
            </span>
          )}
          {mixed.length >= 2 &&
            mixed.map((c) => (
              <span key={c} className="cli-badge" title={t.mixedCliBadgeHint(c)}>
                {c}
              </span>
            ))}
          {extra}
        </div>
      </td>
    </tr>
  );
}
