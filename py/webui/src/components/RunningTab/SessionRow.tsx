/**
 * Replaces `runningRow()` (web.py ~1730-1760). Column order (`<td>`s)
 * must stay exactly as below — `global.css`'s `.runtab th:nth-child(3)`/
 * `:nth-child(7)` mobile-hiding rules depend on it (see the file header
 * comment in `styles/global.css`).
 *
 * The terminal button just flips `openTerminalFor` in `App` (via
 * `onToggleTerminal`) — no modal exists yet (plan Sequencing step 8).
 * Deliberately NOT rendering any placeholder/inline terminal UI here, per
 * the plan: "leave `openTerminalFor` truly unused downstream".
 */

import { useState } from "react";
import { apiTermOpenWindow } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import type { SessionInfo } from "../../api/types";
import type { SelectionControls } from "../../state/selection";
import type { TabKey } from "../../state/tabs";
import { CwdCell } from "../shared/CwdCell";
import { isProtectedName } from "../shared/protectedNames";
import { AdoptRow } from "./AdoptRow";
import { HoCell } from "./HoCell";
import { OptionsRow } from "./OptionsRow";

const RUNNING_ROW_COLSPAN = 10;

interface SessionRowProps {
  session: SessionInfo;
  selection: SelectionControls;
  isOptionsOpen: boolean;
  onToggleOptions: () => void;
  isAdoptOpen: boolean;
  onToggleAdopt: () => void;
  onToggleTerminal: (name: string) => void;
  onSwitchTab: (tab: TabKey) => void;
}

export function SessionRow({
  session,
  selection,
  isOptionsOpen,
  onToggleOptions,
  isAdoptOpen,
  onToggleAdopt,
  onToggleTerminal,
  onSwitchTab,
}: SessionRowProps) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [openingWindow, setOpeningWindow] = useState(false);

  const windowless = session.tmux && !!data?.diag.windowless?.includes(session.name);

  async function handleOpenWindow() {
    setOpeningWindow(true);
    try {
      const res = await apiTermOpenWindow({ name: session.name, lang });
      if (!res.ok) window.alert(`${session.name}: ${res.error}`);
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setOpeningWindow(false);
    }
    refresh();
  }

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
          {session.registered === false && (
            <span className="unreg-badge" title={t.unregHint}>
              {t.unregBadge}
            </span>
          )}
          {windowless && (
            <span className="unreg-badge" title={t.windowlessHint}>
              {t.windowlessBadge}
            </span>
          )}
        </td>
        <td>{session.model || ""}</td>
        <td>
          <span className="cli-badge">{session.cli}</span>
        </td>
        <td>
          <span className="dot on" />
          {t.pidWord}
          {session.pid}
        </td>
        <td>{session.cpu != null ? session.cpu.toFixed(1) : "—"}</td>
        <HoCell session={session} />
        <td>{session.kind || "—"}</td>
        <CwdCell cwd={session.cwd} />
        <td>
          <div className="actioncell">
            {session.registered === false ? (
              <button type="button" className="start" onClick={onToggleAdopt}>
                {t.adoptBtn}
              </button>
            ) : (
              <button type="button" className="start" onClick={onToggleOptions}>
                {t.optionsBtn}
              </button>
            )}
            {session.tmux && (
              <button type="button" className="start" onClick={() => onToggleTerminal(session.name)}>
                {t.terminalBtn}
              </button>
            )}
            {windowless && (
              <button
                type="button"
                className="start"
                disabled={openingWindow}
                title={t.windowlessHint}
                onClick={() => void handleOpenWindow()}
              >
                {openingWindow ? t.openingWindow : t.openWindowBtn}
              </button>
            )}
          </div>
        </td>
      </tr>
      {session.registered === false && isAdoptOpen && (
        <AdoptRow session={session} colspan={RUNNING_ROW_COLSPAN} onClose={onToggleAdopt} />
      )}
      {session.registered !== false && isOptionsOpen && (
        <OptionsRow session={session} colspan={RUNNING_ROW_COLSPAN} onClose={onToggleOptions} onSwitchTab={onSwitchTab} />
      )}
    </>
  );
}
