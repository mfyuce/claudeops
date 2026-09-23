/**
 * History tab: stopped instances (instances.json), fetched from every host's
 * `/api/instances` rather than the status payload (the list grows with every
 * new chat; pushing it on each status tick would be wasteful). Grouped by
 * (host, cwd) like GroupTable; instances share their blueprint's cwd, so a
 * group is effectively one blueprint.
 */

import { Fragment, useCallback, useEffect, useState } from "react";
import { apiForgetInstance, apiStart, getInstances } from "../api/client";
import { describeApiError } from "../api/errors";
import type { InstanceRecord } from "../api/types";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { usePagination } from "../hooks/usePagination";
import { useGroupCollapse } from "../hooks/useGroupCollapse";
import { LOCAL_HOST, rowKey } from "../state/hosts";
import { CollapseControls } from "./shared/CollapseControls";
import { CwdCell } from "./shared/CwdCell";
import { GroupHeaderRow } from "./shared/GroupHeaderRow";
import { groupByCwd, groupKey } from "./shared/groupByCwd";
import { Pagination } from "./shared/Pagination";
import { matchesSearch } from "./shared/searchFilter";
import { TabHint } from "./shared/TabHint";

const HISTORY_COLSPAN = 7;

function fmtDate(ts: number | null): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

interface HistoryRowProps {
  item: InstanceRecord;
  onView: (host: string, name: string) => void;
  onChanged: () => void;
}

function HistoryRow({ item, onView, onChanged }: HistoryRowProps) {
  const { t, lang } = useLang();
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<{ ok: boolean; error?: string }>) {
    setBusy(true);
    try {
      const res = await action();
      if (!res.ok) window.alert(`${item.name}: ${res.error}`);
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
    onChanged();
  }

  function handleForget() {
    if (!window.confirm(t.historyForgetConfirm(item.name))) return;
    void run(() => apiForgetInstance({ name: item.name, host: item.host, lang }));
  }

  return (
    <tr>
      <td style={{ width: "16%" }}>
        {item.name}
        {item.host !== LOCAL_HOST && (
          <span className="cli-badge" title={t.hostBadgeHint(item.host)}>
            {item.host}
          </span>
        )}
      </td>
      <td style={{ width: "10%" }}>{item.blueprint ?? t.historyNoBlueprint}</td>
      <td style={{ width: "14%" }}>{item.model || ""}</td>
      <td style={{ width: "6%" }}>
        <span className="cli-badge">{item.cli}</span>
      </td>
      <td style={{ width: "8%", whiteSpace: "nowrap" }}>{fmtDate(item.last_started_at ?? item.created_at)}</td>
      <CwdCell cwd={item.cwd} name={item.name} />
      <td style={{ width: "20%" }}>
        <div className="actioncell">
          <button
            type="button"
            className="reactivate"
            disabled={busy}
            onClick={() => void run(() => apiStart({ name: item.name, host: item.host, lang }))}
          >
            {busy ? t.starting : t.historyResumeBtn}
          </button>
          <button type="button" className="start" onClick={() => onView(item.host, item.name)}>
            {t.viewBtn}
          </button>
          <button type="button" className="stop" disabled={busy} onClick={handleForget}>
            {t.historyForgetBtn}
          </button>
        </div>
      </td>
    </tr>
  );
}

export function HistoryTab({ search, onView }: { search: string; onView: (host: string, name: string) => void }) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const collapse = useGroupCollapse();
  const [items, setItems] = useState<InstanceRecord[] | null>(null);
  const [hostErrors, setHostErrors] = useState<string[]>([]);

  const hostsKey = [LOCAL_HOST, ...(data?.hosts ?? []).map((h) => h.name)].join("\n");
  // Refetch when the set of running sessions changes (an instance stopped or resumed elsewhere).
  const runningKey = (data?.sessions ?? [])
    .filter((s) => s.running)
    .map(rowKey)
    .sort()
    .join("\n");

  const load = useCallback(async () => {
    const hosts = hostsKey.split("\n");
    const results = await Promise.allSettled(hosts.map((h) => getInstances(lang, h)));
    const merged: InstanceRecord[] = [];
    const errors: string[] = [];
    results.forEach((r, i) => {
      if (r.status === "rejected") errors.push(t.historyHostError(hosts[i], describeApiError(r.reason, t)));
      else if (!r.value.ok) errors.push(t.historyHostError(hosts[i], r.value.error));
      else merged.push(...r.value.instances);
    });
    setItems(merged);
    setHostErrors(errors);
  }, [hostsKey, lang, t]);

  useEffect(() => {
    void load();
  }, [load, runningKey]);

  const onChanged = useCallback(() => {
    refresh();
    void load();
  }, [refresh, load]);

  const stopped = (items ?? []).filter((it) => !it.running);
  const filtered = stopped.filter((it) => matchesSearch(it, search));
  const groups = groupByCwd(filtered);
  const groupKeys = groups.map((g) => groupKey(g.host, g.cwd));
  const { pageItems: pageGroups, page, totalPages, setPage } = usePagination(groups);

  return (
    <>
      <TabHint>{t.historyDesc}</TabHint>
      {hostErrors.map((msg) => (
        <div key={msg} className="warn-banner">
          {msg}
        </div>
      ))}
      {items === null ? (
        <div className="opts-hint">…</div>
      ) : !filtered.length ? (
        <div className="opts-hint">{stopped.length === 0 ? t.empty : t.noSearchMatches}</div>
      ) : (
        <div className="tablewrap">
          <div className="opts-hint">{t.historyCount(filtered.length)}</div>
          <CollapseControls
            groupKeys={groupKeys}
            isExpanded={collapse.isExpanded}
            onCollapseAll={collapse.collapseAll}
            onExpandAll={collapse.expandAll}
          />
          <table className="historytab">
            <tbody>
              {pageGroups.map((g) => {
                const gKey = groupKey(g.host, g.cwd);
                const expanded = collapse.isExpanded(gKey);
                return (
                  <Fragment key={gKey}>
                    <GroupHeaderRow
                      host={g.host}
                      cwd={g.cwd}
                      name={g.items[0]?.blueprint ?? g.items[0]?.name}
                      count={g.items.length}
                      colSpan={HISTORY_COLSPAN}
                      collapsed={!expanded}
                      onToggle={() => collapse.toggle(gKey)}
                    />
                    {expanded &&
                      g.items.map((it) => <HistoryRow key={rowKey(it)} item={it} onView={onView} onChanged={onChanged} />)}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        </div>
      )}
    </>
  );
}
