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
 */

import { useState } from "react";
import { apiReactivate } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { usePagination } from "../hooks/usePagination";
import type { RosterEntry } from "../api/types";
import { CwdCell } from "./shared/CwdCell";
import { Pagination } from "./shared/Pagination";
import { matchesSearch } from "./shared/searchFilter";

interface GroupTableProps {
  items: RosterEntry[];
  search: string;
}

function ReactivateRow({ item }: { item: RosterEntry }) {
  const { t, lang } = useLang();
  const { refresh } = useStatusContext();
  const [busy, setBusy] = useState(false);

  async function handleReactivate() {
    setBusy(true);
    try {
      const res = await apiReactivate({ name: item.name, lang });
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
      <td style={{ width: "14%" }}>{item.name}</td>
      <td style={{ width: "18%" }}>{item.model || ""}</td>
      <td style={{ width: "6%" }}>
        <span className="cli-badge">{item.cli}</span>
      </td>
      <CwdCell cwd={item.cwd} />
      <td style={{ width: "16%" }}>
        <button type="button" className="reactivate" disabled={busy} onClick={() => void handleReactivate()}>
          {busy ? t.starting : t.reactivateBtn}
        </button>
      </td>
    </tr>
  );
}

export function GroupTable({ items, search }: GroupTableProps) {
  const { t } = useLang();
  const filtered = items.filter((it) => matchesSearch(it, search));
  const { pageItems, page, totalPages, setPage } = usePagination(filtered);

  if (!filtered.length) return <div className="opts-hint">{items.length === 0 ? t.empty : t.noSearchMatches}</div>;

  return (
    <div className="tablewrap">
      <table>
        <tbody>
          {pageItems.map((it) => (
            <ReactivateRow key={it.name} item={it} />
          ))}
        </tbody>
      </table>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  );
}
