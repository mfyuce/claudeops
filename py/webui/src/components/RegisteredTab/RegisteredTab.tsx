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
 */

import { useState } from "react";
import { BulkBar } from "../RunningTab/BulkBar";
import { OptionsRow } from "../RunningTab/OptionsRow";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import type { SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { CwdCell } from "../shared/CwdCell";
import { RegisterForm } from "./RegisterForm";

const REGISTERED_ROW_COLSPAN = 6;

interface RegisteredTabProps {
  selection: SelectionControls;
  onSwitchTab: (tab: TabKey) => void;
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
        <td>{session.name}</td>
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

export function RegisteredTab({ selection, onSwitchTab }: RegisteredTabProps) {
  const { t } = useLang();
  const { data } = useStatusContext();
  const [openOptionsFor, setOpenOptionsFor] = useState<string | null>(null);

  if (!data) return null;

  // Every `!s.running` session is `registered: true` by construction (see
  // api/types.ts's SessionInfo doc comment / _status_payload()'s
  // proc-scan loop, which only ever appends `running: true` rows) — this
  // tab never needs to filter registered vs. not, unlike Running's adopt
  // path.
  const rows = data.sessions.filter((s) => !s.running);
  const allSelected = rows.length > 0 && rows.every((s) => selection.selected.has(s.name));

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
                  {t.noneRegistered}
                </td>
              </tr>
            )}
            {rows.map((s) => (
              <RegisteredRow
                key={s.name}
                session={s}
                selection={selection}
                isOptionsOpen={openOptionsFor === s.name}
                onToggleOptions={() => setOpenOptionsFor((prev) => (prev === s.name ? null : s.name))}
                onSwitchTab={onSwitchTab}
              />
            ))}
          </tbody>
        </table>
      </div>
      <RegisterForm />
    </>
  );
}
