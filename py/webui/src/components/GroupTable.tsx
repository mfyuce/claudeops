/**
 * Replaces `groupTable()` (web.py ~1792-1803) — shared by the Disabled and
 * Retired tabs (both just pass a different `RosterEntry[]`: `d.closed`/
 * `d.retired`). Reactivate button wired to `/api/reactivate`
 * (`doReactivate()` in the original), moving a row back to Running.
 *
 * Two things reproduced exactly from the original, easy to lose in a
 * naive port:
 *  - `groupTable()` renders NO `<thead>` at all (a bare `<table><tbody>`,
 *    unlike `runningTable()`/`registeredTable()`) — matched below.
 *  - when `items` is empty, the original returns ONLY the `.opts-hint`
 *    empty-state div, not even an empty `<table>` wrapper — matched via
 *    the early return before the `.tablewrap` div.
 *
 * `ReactivateRow` owns its own `busy` state (mirroring the original's
 * `btn.disabled=true; btn.textContent=t('starting')` DOM mutation) — no
 * shadow dict needed here since a closed/retired row has no in-progress
 * form to survive a refresh, unlike `OptionsRow`/`AdoptRow`.
 *
 * `search` (2026-09-04): filtered here (not by the caller) so the two
 * call sites (App.tsx's Disabled/Retired tabs) stay one-liners, same as
 * every other prop this component already takes.
 *
 * 2026-09-14: grouped by (host, cwd) like RegisteredTab/RunningTab, same
 * `../shared/groupByCwd`/`GroupHeaderRow`/`useGroupCollapse` (user: "tree
 * gorunumu her tabda olsun") — starts all-collapsed, `CollapseControls`
 * added. `RosterEntry` (unlike `SessionInfo`) has no `running` field, so
 * there's no RegisteredTab-style "hasRunning" badge to compute here.
 * Pagination switched from per-row to per-group, same reasoning as the
 * other two tabs.
 *
 * 2026-09-14 (2): `ReactivateRow` gains a "View" button (`onView`, threaded
 * from `App.tsx` same as `RunningTab`'s `onToggleTerminal`) opening
 * `ReadOnlySessionModal` — TODO.md's "terminal olmayan, salt-okunur
 * sohbet+dosyalar popup'ı". Enabled for BOTH tabs this component serves
 * (Disabled AND Retired) — a retired session's history is just as worth
 * reviewing as a disabled one's, and `GroupTable` has no way to tell the two
 * apart from within `items: RosterEntry[]` alone (no per-tab prop existed
 * before this), so there was no reason to single one out.
 */

import { Fragment, useState } from "react";
import { apiReactivate } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { usePagination } from "../hooks/usePagination";
import { useGroupCollapse } from "../hooks/useGroupCollapse";
import { LOCAL_HOST, rowKey } from "../state/hosts";
import type { RosterEntry } from "../api/types";
import { CollapseControls } from "./shared/CollapseControls";
import { CwdCell } from "./shared/CwdCell";
import { GroupHeaderRow } from "./shared/GroupHeaderRow";
import { groupByCwd, groupKey } from "./shared/groupByCwd";
import { Pagination } from "./shared/Pagination";
import { matchesSearch } from "./shared/searchFilter";

const GROUP_TABLE_COLSPAN = 5;

interface GroupTableProps {
  items: RosterEntry[];
  search: string;
  onView: (host: string, name: string) => void;
}

function ReactivateRow({ item, onView }: { item: RosterEntry; onView: (host: string, name: string) => void }) {
  const { t, lang } = useLang();
  const { refresh } = useStatusContext();
  const [busy, setBusy] = useState(false);

  async function handleReactivate() {
    setBusy(true);
    try {
      const res = await apiReactivate({ name: item.name, host: item.host, lang });
      if (!res.ok) window.alert(`${item.name}: ${res.error}`);
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
    refresh();
  }

  return (
    <tr>
      <td style={{ width: "14%" }}>
        {item.name}
        {item.host !== LOCAL_HOST && (
          <span className="cli-badge" title={t.hostBadgeHint(item.host)}>
            {item.host}
          </span>
        )}
      </td>
      <td style={{ width: "18%" }}>{item.model || ""}</td>
      <td style={{ width: "6%" }}>
        <span className="cli-badge">{item.cli}</span>
      </td>
      <CwdCell cwd={item.cwd} name={item.name} />
      <td style={{ width: "16%" }}>
        <div className="actioncell">
          <button type="button" className="reactivate" disabled={busy} onClick={() => void handleReactivate()}>
            {busy ? t.starting : t.reactivateBtn}
          </button>
          <button type="button" className="start" onClick={() => onView(item.host, item.name)}>
            {t.viewBtn}
          </button>
        </div>
      </td>
    </tr>
  );
}

export function GroupTable({ items, search, onView }: GroupTableProps) {
  const { t } = useLang();
  const collapse = useGroupCollapse();
  const filtered = items.filter((it) => matchesSearch(it, search));
  const groups = groupByCwd(filtered);
  const groupKeys = groups.map((g) => groupKey(g.host, g.cwd));
  const { pageItems: pageGroups, page, totalPages, setPage } = usePagination(groups);

  if (!filtered.length) return <div className="opts-hint">{items.length === 0 ? t.empty : t.noSearchMatches}</div>;

  return (
    <div className="tablewrap">
      <CollapseControls groupKeys={groupKeys} isExpanded={collapse.isExpanded} onCollapseAll={collapse.collapseAll} onExpandAll={collapse.expandAll} />
      <table className="grouptab">
        <tbody>
          {pageGroups.map((g) => {
            const gKey = groupKey(g.host, g.cwd);
            const expanded = collapse.isExpanded(gKey);
            return (
              <Fragment key={gKey}>
                <GroupHeaderRow
                  host={g.host}
                  cwd={g.cwd}
                  name={g.items[0]?.name}
                  count={g.items.length}
                  colSpan={GROUP_TABLE_COLSPAN}
                  collapsed={!expanded}
                  onToggle={() => collapse.toggle(gKey)}
                />
                {expanded && g.items.map((it) => <ReactivateRow key={rowKey(it)} item={it} onView={onView} />)}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  );
}
