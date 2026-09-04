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
 */

import { useState } from "react";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { usePagination } from "../../hooks/usePagination";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { matchesSearch } from "../shared/searchFilter";
import { Pagination } from "../shared/Pagination";
import { BulkBar } from "./BulkBar";
import { SessionRow } from "./SessionRow";

const RUNNING_ROW_COLSPAN = 10;

interface RunningTabProps {
  selection: SelectionControls;
  onToggleTerminal: (name: string) => void;
  onSwitchTab: (tab: TabKey) => void;
  search: string;
}

export function RunningTab({ selection, onToggleTerminal, onSwitchTab, search }: RunningTabProps) {
  const { t } = useLang();
  const { data } = useStatusContext();
  const [openOptionsFor, setOpenOptionsFor] = useState<string | null>(null);
  const [openAdoptFor, setOpenAdoptFor] = useState<string | null>(null);
  // Hooks must run unconditionally (rules-of-hooks) — computed before the
  // `!data` early return below, with an empty-array fallback while `data`
  // hasn't loaded yet.
  const allRows = data ? data.sessions.filter((s) => s.running) : [];
  // `search` (2026-09-04) narrows `rows` itself, same as the running/!running
  // split above it — everything below (select-all, BulkBar, pagination)
  // already treats `rows` as "the current tab's full set", so it needs no
  // separate search-awareness.
  const rows = allRows.filter((s) => matchesSearch(s, search));
  // Select-all/bulk actions stay scoped to the FULL (unpaginated) `rows` —
  // only which rows are individually RENDERED is paginated.
  const { pageItems, page, totalPages, setPage } = usePagination(rows);

  if (!data) return null;

  const allSelected = rows.length > 0 && rows.every((s) => selection.selected.has(s.name));

  return (
    <>
      <BulkBar tab="running" rows={rows} selection={selection} />
      <div className="tablewrap">
        <table className="runtab">
          <thead>
            <tr>
              <th className="selcell">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => selection.toggleMany(rows.map((s) => s.name), e.target.checked)}
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
            {pageItems.map((s) => (
              <SessionRow
                key={s.name}
                session={s}
                selection={selection}
                isOptionsOpen={openOptionsFor === s.name}
                onToggleOptions={() => setOpenOptionsFor((prev) => (prev === s.name ? null : s.name))}
                isAdoptOpen={openAdoptFor === s.name}
                onToggleAdopt={() => setOpenAdoptFor((prev) => (prev === s.name ? null : s.name))}
                onToggleTerminal={onToggleTerminal}
                onSwitchTab={onSwitchTab}
              />
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </>
  );
}
