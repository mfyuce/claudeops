/**
 * Replaces `runningTable()`/`runningRow()`'s table shell (web.py
 * ~1709-1728) plus `render()`'s `bulkBar('running', running) +
 * runningTable(running, d)` composition.
 *
 * Owns `openOptionsFor`/`openAdoptFor` — "which row's options/adopt panel
 * is open" — as its own local `useState` (single value each, so opening
 * one row's panel closes any other, matching the original's single
 * shared `optsFor`/`adoptFor` pointers). One deliberate, minor deviation
 * from the original noted here: the original's `optsFor` was ONE
 * variable shared across both the Running and Registered tables (a
 * session can only be in one or the other, so in practice this was mostly
 * inconsequential); here each tab owns its own pointer instead of
 * threading one more piece of shared state down from `App`. No observable
 * difference to a user, since only one tab is ever visible at a time.
 *
 * 2026-09-14: grouped by (host, cwd) like RegisteredTab, using the same
 * `../shared/groupByCwd`/`GroupHeaderRow`/`useGroupCollapse` (user: "tree
 * gorunumu her tabda olsun") — starts all-collapsed, with a Collapse/
 * Expand-all control (`CollapseControls`). Pagination switched from
 * per-row to per-GROUP for the same "never split a project across pages"
 * reason RegisteredTab already had. No cross-tab "hasRunning" badge here
 * (unlike RegisteredTab) — every row in THIS tab is already running, the
 * badge would be true for every group and say nothing.
 */

import { Fragment, useState } from "react";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { usePagination } from "../../hooks/usePagination";
import { useGroupCollapse } from "../../hooks/useGroupCollapse";
import { rowKey } from "../../state/hosts";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { CollapseControls } from "../shared/CollapseControls";
import { GroupHeaderRow } from "../shared/GroupHeaderRow";
import { groupByCwd, groupKey } from "../shared/groupByCwd";
import { matchesSearch } from "../shared/searchFilter";
import { Pagination } from "../shared/Pagination";
import { BulkBar } from "./BulkBar";
import { SessionRow } from "./SessionRow";

const RUNNING_ROW_COLSPAN = 10;

interface RunningTabProps {
  selection: SelectionControls;
  onToggleTerminal: (host: string, name: string) => void;
  onSwitchTab: (tab: TabKey) => void;
  search: string;
}

export function RunningTab({ selection, onToggleTerminal, onSwitchTab, search }: RunningTabProps) {
  const { t } = useLang();
  const { data } = useStatusContext();
  // Composite `host:name` strings (rowKey) — never a bare session name, two
  // different hosts can share one (see state/hosts.ts).
  const [openOptionsFor, setOpenOptionsFor] = useState<string | null>(null);
  const [openAdoptFor, setOpenAdoptFor] = useState<string | null>(null);
  const collapse = useGroupCollapse();
  // Hooks must run unconditionally (rules-of-hooks) — computed before the
  // `!data` early return below, with an empty-array fallback while `data`
  // hasn't loaded yet.
  const allRows = data ? data.sessions.filter((s) => s.running) : [];
  // `search` (2026-09-04) narrows `rows` itself, same as the running/!running
  // split above it — everything below (select-all, BulkBar, pagination)
  // already treats `rows` as "the current tab's full set", so it needs no
  // separate search-awareness.
  const rows = allRows.filter((s) => matchesSearch(s, search));
  const groups = groupByCwd(rows);
  const groupKeys = groups.map((g) => groupKey(g.host, g.cwd));
  // Select-all/bulk actions stay scoped to the FULL (unpaginated) `rows` —
  // only which GROUPS are RENDERED on the current page is paginated (same
  // "never split a project's rows across pages" reasoning as
  // RegisteredTab).
  const { pageItems: pageGroups, page, totalPages, setPage } = usePagination(groups);

  if (!data) return null;

  const allSelected = rows.length > 0 && rows.every((s) => selection.selected.has(rowKey(s)));

  return (
    <>
      <BulkBar tab="running" rows={rows} selection={selection} />
      <CollapseControls groupKeys={groupKeys} isExpanded={collapse.isExpanded} onCollapseAll={collapse.collapseAll} onExpandAll={collapse.expandAll} />
      <div className="tablewrap">
        <table className="runtab">
          <thead>
            <tr>
              <th className="selcell">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => selection.toggleMany(rows.map(rowKey), e.target.checked)}
                />
              </th>
              <th style={{ width: "12%" }}>{t.colName}</th>
              <th style={{ width: "14%" }}>model</th>
              <th style={{ width: "6%" }}>{t.cliLabel}</th>
              <th style={{ width: "9%" }}>{t.colStatus}</th>
              <th style={{ width: "6%" }}>cpu%</th>
              <th style={{ width: "5%" }} title={t.hoHint}>
                {t.hoCol}
              </th>
              <th style={{ width: "8%" }}>{t.colKind}</th>
              <th>cwd</th>
              <th style={{ width: "10%" }} />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={RUNNING_ROW_COLSPAN} style={{ color: "var(--muted)" }}>
                  {allRows.length === 0 ? t.nothingRunning : t.noSearchMatches}
                </td>
              </tr>
            )}
            {pageGroups.map((g) => {
              const gKey = groupKey(g.host, g.cwd);
              const expanded = collapse.isExpanded(gKey);
              return (
                <Fragment key={gKey}>
                  <GroupHeaderRow
                    host={g.host}
                    cwd={g.cwd}
                    count={g.items.length}
                    colSpan={RUNNING_ROW_COLSPAN}
                    collapsed={!expanded}
                    onToggle={() => collapse.toggle(gKey)}
                  />
                  {expanded &&
                    g.items.map((s) => (
                      <SessionRow
                        key={rowKey(s)}
                        session={s}
                        selection={selection}
                        isOptionsOpen={openOptionsFor === rowKey(s)}
                        onToggleOptions={() => setOpenOptionsFor((prev) => (prev === rowKey(s) ? null : rowKey(s)))}
                        isAdoptOpen={openAdoptFor === rowKey(s)}
                        onToggleAdopt={() => setOpenAdoptFor((prev) => (prev === rowKey(s) ? null : rowKey(s)))}
                        onToggleTerminal={onToggleTerminal}
                        onSwitchTab={onSwitchTab}
                      />
                    ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </>
  );
}
