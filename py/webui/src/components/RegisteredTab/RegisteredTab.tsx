/**
 * Replaces `registeredTable()`/`registeredRow()` (web.py ~1762-1790) plus
 * `render()`'s `bulkBar('registered', stopped) + registeredTable(stopped,
 * d) + newProjectForm(d)` composition. `RegisteredRow` is kept private to
 * this file (the original didn't give it special treatment either — just
 * a helper function next to `registeredTable()`).
 *
 * Reuses `OptionsRow`/`BulkBar` from `../RunningTab/` exactly like the
 * original reused `unifiedOptsRow()` across both tabs (see the plan's
 * component table).
 *
 * TODO L57 (2026-09-02 decision: group by cwd, no new roster field) — rows
 * are grouped into a header + its sessions, and pagination (TODO L74)
 * paginates the GROUP list rather than individual rows, so a page break
 * can never split one project's names across two pages.
 *
 * 2026-09-14: `groupByCwd`/`GroupHeaderRow` moved to `../shared/` so
 * RunningTab/GroupTable can group the same way (user: "tree gorunumu her
 * tabda olsun") — this file now only adds its own `hasRunning` cross-tab
 * badge on top of the shared grouping. Default flipped from "all start
 * expanded" (2026-09-02) to "all start collapsed" (user: "tablarda all
 * collapsed gelsin") via `useGroupCollapse`'s empty-set-= collapsed
 * convention, and a Collapse/Expand-all control was added
 * (`CollapseControls`, user: "tablara collapse all expand all getirelim").
 */

import { Fragment, useState } from "react";
import { BulkBar } from "../RunningTab/BulkBar";
import { OptionsRow } from "../RunningTab/OptionsRow";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { usePagination } from "../../hooks/usePagination";
import { useGroupCollapse } from "../../hooks/useGroupCollapse";
import { LOCAL_HOST, rowKey } from "../../state/hosts";
import type { SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { CollapseControls } from "../shared/CollapseControls";
import { CwdCell } from "../shared/CwdCell";
import { GroupHeaderRow } from "../shared/GroupHeaderRow";
import { groupByCwd, groupKey, type CwdGroup } from "../shared/groupByCwd";
import { isProtectedName } from "../shared/protectedNames";
import { Pagination } from "../shared/Pagination";
import { matchesSearch } from "../shared/searchFilter";
import { EditRow } from "./EditRow";
import { RegisterForm } from "./RegisterForm";

const REGISTERED_ROW_COLSPAN = 6;

interface RegisteredTabProps {
  selection: SelectionControls;
  onSwitchTab: (tab: TabKey) => void;
  search: string;
  onView: (host: string, name: string) => void;
}

interface RegisteredRowProps {
  session: SessionInfo;
  selection: SelectionControls;
  isOptionsOpen: boolean;
  onToggleOptions: () => void;
  isEditOpen: boolean;
  onToggleEdit: () => void;
  onSwitchTab: (tab: TabKey) => void;
  onView: (host: string, name: string) => void;
}

function RegisteredRow({
  session,
  selection,
  isOptionsOpen,
  onToggleOptions,
  isEditOpen,
  onToggleEdit,
  onSwitchTab,
  onView,
}: RegisteredRowProps) {
  const { t } = useLang();
  return (
    <>
      <tr>
        <td className="selcell">
          <input
            type="checkbox"
            checked={selection.selected.has(rowKey(session))}
            onChange={(e) => selection.toggle(rowKey(session), e.target.checked)}
          />
        </td>
        <td>
          {session.name}
          {session.host !== LOCAL_HOST && (
            <span className="cli-badge" title={t.hostBadgeHint(session.host)}>
              {session.host}
            </span>
          )}
          {isProtectedName(session.name) && (
            <span className="unreg-badge" title={t.protectedHint}>
              {t.protectedBadge}
            </span>
          )}
        </td>
        <td>{session.model || ""}</td>
        <td>
          <span className="cli-badge">{session.cli}</span>
        </td>
        <CwdCell cwd={session.cwd} name={session.name} />
        <td>
          <div className="actioncell">
            <button type="button" className="start" onClick={onToggleOptions}>
              {t.startBtn}
            </button>
            <button type="button" title={t.editTitle} onClick={onToggleEdit}>
              {t.editBtn}
            </button>
            <button type="button" className="start" onClick={() => onView(session.host, session.name)}>
              {t.viewBtn}
            </button>
          </div>
        </td>
      </tr>
      {isOptionsOpen && (
        <OptionsRow session={session} colspan={REGISTERED_ROW_COLSPAN} onClose={onToggleOptions} onSwitchTab={onSwitchTab} />
      )}
      {isEditOpen && <EditRow session={session} colspan={REGISTERED_ROW_COLSPAN} onClose={onToggleEdit} />}
    </>
  );
}

/** Whether ANY session (running or not) sharing this group's (host, cwd)
 * is currently running — cross-tab signal the user asked for ("Registered
 * da bu grupda acik olan var mi gosterelim"). Kept local to this file
 * (unlike the grouping itself) since it needs the full running+stopped
 * session set, which only RegisteredTab has reason to compute. */
function hasRunningFor(group: CwdGroup<SessionInfo>, allSessions: SessionInfo[]): boolean {
  const key = groupKey(group.host, group.cwd);
  return allSessions.some((s) => s.running && groupKey(s.host, s.cwd) === key);
}

export function RegisteredTab({ selection, onSwitchTab, search, onView }: RegisteredTabProps) {
  const { t } = useLang();
  const { data } = useStatusContext();
  const [openOptionsFor, setOpenOptionsFor] = useState<string | null>(null);
  const [openEditFor, setOpenEditFor] = useState<string | null>(null);
  const collapse = useGroupCollapse();

  // Hooks must run unconditionally (rules-of-hooks) — computed before the
  // `!data` early return below, with empty-array fallbacks while `data`
  // hasn't loaded yet.
  //
  // Every `!s.running` session is `registered: true` by construction (see
  // api/types.ts's SessionInfo doc comment / _status_payload()'s
  // proc-scan loop, which only ever appends `running: true` rows) — this
  // tab never needs to filter registered vs. not, unlike Running's adopt
  // path.
  const allRows = data ? data.sessions.filter((s) => !s.running) : [];
  // `search` (2026-09-04) narrows before grouping, so a group with zero
  // surviving members drops out of `groups` entirely rather than rendering
  // an empty header.
  const rows = allRows.filter((s) => matchesSearch(s, search));
  const groups = groupByCwd(rows);
  const groupKeys = groups.map((g) => groupKey(g.host, g.cwd));
  const { pageItems: pageGroups, page, totalPages, setPage } = usePagination(groups);

  if (!data) return null;

  const allSelected = rows.length > 0 && rows.every((s) => selection.selected.has(rowKey(s)));

  return (
    <>
      <BulkBar tab="registered" rows={rows} selection={selection} />
      <CollapseControls groupKeys={groupKeys} isExpanded={collapse.isExpanded} onCollapseAll={collapse.collapseAll} onExpandAll={collapse.expandAll} />
      <div className="tablewrap">
        <table className="regtab">
          <thead>
            <tr>
              <th className="selcell">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => selection.toggleMany(rows.map(rowKey), e.target.checked)}
                />
              </th>
              <th style={{ width: "14%" }}>{t.colName}</th>
              <th style={{ width: "16%" }}>model</th>
              <th style={{ width: "6%" }}>{t.cliLabel}</th>
              <th>cwd</th>
              <th style={{ width: "12%" }} />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={REGISTERED_ROW_COLSPAN} style={{ color: "var(--muted)" }}>
                  {allRows.length === 0 ? t.noneRegistered : t.noSearchMatches}
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
                    colSpan={REGISTERED_ROW_COLSPAN}
                    collapsed={!expanded}
                    onToggle={() => collapse.toggle(gKey)}
                    extra={
                      hasRunningFor(g, data.sessions) && (
                        <span className="unreg-badge" title={t.groupRunningBadge}>
                          {t.groupRunningBadge}
                        </span>
                      )
                    }
                  />
                  {expanded &&
                    g.items.map((s) => (
                      <RegisteredRow
                        key={rowKey(s)}
                        session={s}
                        selection={selection}
                        isOptionsOpen={openOptionsFor === rowKey(s)}
                        onToggleOptions={() =>
                          setOpenOptionsFor((prev) => {
                            const next = prev === rowKey(s) ? null : rowKey(s);
                            if (next) setOpenEditFor(null);
                            return next;
                          })
                        }
                        isEditOpen={openEditFor === rowKey(s)}
                        onToggleEdit={() =>
                          setOpenEditFor((prev) => {
                            const next = prev === rowKey(s) ? null : rowKey(s);
                            if (next) setOpenOptionsFor(null);
                            return next;
                          })
                        }
                        onSwitchTab={onSwitchTab}
                        onView={onView}
                      />
                    ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
      <RegisterForm />
    </>
  );
}
