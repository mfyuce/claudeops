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
 * are grouped into a header + its sessions; a group collapses/expands (all
 * start expanded — nothing hidden by default, the header is mainly a label
 * + cross-tab-running badge) and pagination (TODO L74) paginates the GROUP
 * list rather than individual rows, so a page break can never split one
 * project's names across two pages.
 */

import { Fragment, useState } from "react";
import { BulkBar } from "../RunningTab/BulkBar";
import { OptionsRow } from "../RunningTab/OptionsRow";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { usePagination } from "../../hooks/usePagination";
import type { SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { CwdCell } from "../shared/CwdCell";
import { isProtectedName } from "../shared/protectedNames";
import { Pagination } from "../shared/Pagination";
import { matchesSearch } from "../shared/searchFilter";
import { RegisterForm } from "./RegisterForm";

const REGISTERED_ROW_COLSPAN = 6;

interface RegisteredTabProps {
  selection: SelectionControls;
  onSwitchTab: (tab: TabKey) => void;
  search: string;
}

interface RegisteredRowProps {
  session: SessionInfo;
  selection: SelectionControls;
  isOptionsOpen: boolean;
  onToggleOptions: () => void;
  onSwitchTab: (tab: TabKey) => void;
}

function RegisteredRow({ session, selection, isOptionsOpen, onToggleOptions, onSwitchTab }: RegisteredRowProps) {
  const { t } = useLang();
  return (
    <>
      <tr>
        <td className="selcell">
          <input
            type="checkbox"
            checked={selection.selected.has(session.name)}
            onChange={(e) => selection.toggle(session.name, e.target.checked)}
          />
        </td>
        <td>
          {session.name}
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
        <CwdCell cwd={session.cwd} />
        <td>
          <div className="actioncell">
            <button type="button" className="start" onClick={onToggleOptions}>
              {t.startBtn}
            </button>
          </div>
        </td>
      </tr>
      {isOptionsOpen && (
        <OptionsRow session={session} colspan={REGISTERED_ROW_COLSPAN} onClose={onToggleOptions} onSwitchTab={onSwitchTab} />
      )}
    </>
  );
}

interface RegisteredGroup {
  cwd: string;
  sessions: SessionInfo[];
  /** Whether ANY session (running or not) sharing this cwd is currently
   * running — cross-tab signal the user asked for ("Registered da bu
   * grupda acik olan var mi gosterelim"). */
  hasRunning: boolean;
}

/** Groups the stopped `rows` by `cwd`, in first-seen order. `allSessions`
 * (the full running+stopped set) is only used to compute `hasRunning` —
 * a project can be "registered" here via one name while a DIFFERENT name
 * sharing the same cwd is actively running (e.g. this repo's own cops+diag). */
function groupByCwd(rows: SessionInfo[], allSessions: SessionInfo[]): RegisteredGroup[] {
  const runningCwds = new Set(allSessions.filter((s) => s.running).map((s) => s.cwd));
  const order: string[] = [];
  const byCwd = new Map<string, SessionInfo[]>();
  for (const r of rows) {
    let list = byCwd.get(r.cwd);
    if (!list) {
      list = [];
      byCwd.set(r.cwd, list);
      order.push(r.cwd);
    }
    list.push(r);
  }
  return order.map((cwd) => ({ cwd, sessions: byCwd.get(cwd)!, hasRunning: runningCwds.has(cwd) }));
}

function GroupHeaderRow({
  group,
  collapsed,
  onToggle,
}: {
  group: RegisteredGroup;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { t } = useLang();
  return (
    <tr className="group-header" onClick={onToggle}>
      <td colSpan={REGISTERED_ROW_COLSPAN}>
        <span className="toggle">{collapsed ? "▸" : "▾"}</span>
        {group.cwd} ({group.sessions.length})
        {group.hasRunning && (
          <span className="unreg-badge" title={t.groupRunningBadge}>
            {t.groupRunningBadge}
          </span>
        )}
      </td>
    </tr>
  );
}

export function RegisteredTab({ selection, onSwitchTab, search }: RegisteredTabProps) {
  const { t } = useLang();
  const { data } = useStatusContext();
  const [openOptionsFor, setOpenOptionsFor] = useState<string | null>(null);
  const [collapsedCwds, setCollapsedCwds] = useState<Set<string>>(() => new Set());

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
  const groups = data ? groupByCwd(rows, data.sessions) : [];
  const { pageItems: pageGroups, page, totalPages, setPage } = usePagination(groups);

  if (!data) return null;

  const allSelected = rows.length > 0 && rows.every((s) => selection.selected.has(s.name));

  function toggleGroup(cwd: string) {
    setCollapsedCwds((prev) => {
      const next = new Set(prev);
      if (next.has(cwd)) next.delete(cwd);
      else next.add(cwd);
      return next;
    });
  }

  return (
    <>
      <BulkBar tab="registered" rows={rows} selection={selection} />
      <div className="tablewrap">
        <table className="regtab">
          <thead>
            <tr>
              <th className="selcell">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => selection.toggleMany(rows.map((s) => s.name), e.target.checked)}
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
            {pageGroups.map((g) => (
              <Fragment key={g.cwd}>
                <GroupHeaderRow group={g} collapsed={collapsedCwds.has(g.cwd)} onToggle={() => toggleGroup(g.cwd)} />
                {!collapsedCwds.has(g.cwd) &&
                  g.sessions.map((s) => (
                    <RegisteredRow
                      key={s.name}
                      session={s}
                      selection={selection}
                      isOptionsOpen={openOptionsFor === s.name}
                      onToggleOptions={() => setOpenOptionsFor((prev) => (prev === s.name ? null : s.name))}
                      onSwitchTab={onSwitchTab}
                    />
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
      <RegisterForm />
    </>
  );
}
