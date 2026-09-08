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
import { LOCAL_HOST, rowKey } from "../../state/hosts";
import type { SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { CwdCell } from "../shared/CwdCell";
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
}

interface RegisteredRowProps {
  session: SessionInfo;
  selection: SelectionControls;
  isOptionsOpen: boolean;
  onToggleOptions: () => void;
  isEditOpen: boolean;
  onToggleEdit: () => void;
  onSwitchTab: (tab: TabKey) => void;
}

function RegisteredRow({
  session,
  selection,
  isOptionsOpen,
  onToggleOptions,
  isEditOpen,
  onToggleEdit,
  onSwitchTab,
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
        <CwdCell cwd={session.cwd} />
        <td>
          <div className="actioncell">
            <button type="button" className="start" onClick={onToggleOptions}>
              {t.startBtn}
            </button>
            <button type="button" title={t.editTitle} onClick={onToggleEdit}>
              {t.editBtn}
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

interface RegisteredGroup {
  host: string;
  cwd: string;
  sessions: SessionInfo[];
  /** Whether ANY session (running or not) sharing this (host, cwd) is
   * currently running — cross-tab signal the user asked for ("Registered da
   * bu grupda acik olan var mi gosterelim"). */
  hasRunning: boolean;
}

/** Composite group identity — two different hosts can genuinely have a
 * project checked out at the same absolute path; grouping those together
 * under one header would misleadingly imply they're the same project. */
function groupKey(host: string, cwd: string): string {
  return `${host}:${cwd}`;
}

/** Groups the stopped `rows` by `(host, cwd)`, in first-seen order.
 * `allSessions` (the full running+stopped set) is only used to compute
 * `hasRunning` — a project can be "registered" here via one name while a
 * DIFFERENT name sharing the same (host, cwd) is actively running (e.g.
 * this repo's own cops+diag). */
function groupByCwd(rows: SessionInfo[], allSessions: SessionInfo[]): RegisteredGroup[] {
  const runningKeys = new Set(allSessions.filter((s) => s.running).map((s) => groupKey(s.host, s.cwd)));
  const order: string[] = [];
  const byKey = new Map<string, SessionInfo[]>();
  for (const r of rows) {
    const key = groupKey(r.host, r.cwd);
    let list = byKey.get(key);
    if (!list) {
      list = [];
      byKey.set(key, list);
      order.push(key);
    }
    list.push(r);
  }
  return order.map((key) => {
    const sessions = byKey.get(key)!;
    return { host: sessions[0].host, cwd: sessions[0].cwd, sessions, hasRunning: runningKeys.has(key) };
  });
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
        {group.host !== LOCAL_HOST && (
          <span className="cli-badge" title={t.hostBadgeHint(group.host)}>
            {group.host}
          </span>
        )}
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
  const [openEditFor, setOpenEditFor] = useState<string | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());

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

  const allSelected = rows.length > 0 && rows.every((s) => selection.selected.has(rowKey(s)));

  function toggleGroup(key: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
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
              return (
                <Fragment key={gKey}>
                  <GroupHeaderRow group={g} collapsed={collapsedGroups.has(gKey)} onToggle={() => toggleGroup(gKey)} />
                  {!collapsedGroups.has(gKey) &&
                    g.sessions.map((s) => (
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
