/**
 * Replaces the original `render()`'s tab dispatch + the static shell
 * around it (topbar/lang-switch/summary line — web.py's `<body>` markup
 * + `applyStaticText()`/`setLang()`). React rewrite plan (dynamic-
 * crunching-lemon.md), Sequencing steps 5 (shell) and 6 (Running/
 * Registered, wired in below).
 *
 * `App` (default export) only sets up the two Contexts; `AppShell` is the
 * component that actually owns `activeTab`/`openTerminalFor`/the shared
 * `selectedNames` Set and consumes both Contexts — a component can't call
 * `useContext` for a Provider it renders in the very same return, so the
 * split is required, not just style.
 */

import { useCallback, useEffect, useState } from "react";
import { Banners } from "./components/Banners";
import { DiagnosticsTab } from "./components/DiagnosticsTab";
import { GroupTable } from "./components/GroupTable";
import { LayoutTab } from "./components/LayoutTab";
import { RegisteredTab } from "./components/RegisteredTab/RegisteredTab";
import { RunningTab } from "./components/RunningTab/RunningTab";
import { TabBar } from "./components/TabBar";
import { LangProvider, useLang } from "./i18n/LangContext";
import { StatusProvider, useStatusContext } from "./state/StatusContext";
import { useSelection } from "./state/selection";
import { isTabKey, TAB_STORAGE_KEY, type TabKey } from "./state/tabs";

function readStoredTab(): TabKey {
  try {
    const stored = localStorage.getItem(TAB_STORAGE_KEY);
    if (isTabKey(stored)) return stored;
  } catch {
    // ignore — same defensiveness as LangContext's detectDefaultLang()
  }
  return "running";
}

function AppShell() {
  const { t, lang, setLang } = useLang();
  const { data, error } = useStatusContext();
  const [activeTab, setActiveTabState] = useState<TabKey>(readStoredTab);
  // openTerminalFor: which session's terminal modal (if any) is open.
  // Step 7 only wires the SETTER (SessionRow's terminal button, and now
  // DiagnosticsTab's "ask" cross-tab flow below) — the value itself is
  // still deliberately unread here (an unread `const` would fail
  // `noUnusedLocals`); the terminal modal that actually consumes it is
  // step 8, built later in this same task/commit sequence.
  const [, setOpenTerminalFor] = useState<string | null>(null);
  // Shared across Running/Registered per the plan — one Set, not a third
  // Context (see state/selection.ts's doc comment).
  const selection = useSelection();

  const setActiveTab = useCallback((tab: TabKey) => {
    setActiveTabState(tab);
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab);
    } catch {
      // ignore — localStorage can throw (private browsing/storage disabled)
    }
  }, []);

  const onToggleTerminal = useCallback((name: string) => {
    setOpenTerminalFor((prev) => (prev === name ? null : name));
  }, []);

  // Original `doDiagAsk()` success: `setTab('running'); await refresh();
  // toggleTerm(d.name);` — DiagnosticsTab doesn't own either the active
  // tab or openTerminalFor, so it hands the new session's name up to this
  // one callback instead. Uses setOpenTerminalFor directly (not
  // onToggleTerminal) since this must always OPEN the freshly-created
  // session's terminal, never toggle it closed — onToggleTerminal's
  // close-if-already-open behavior is for the Running tab's terminal
  // button, not this cross-tab jump.
  const handleDiagAskSuccess = useCallback(
    (name: string) => {
      setActiveTab("running");
      setOpenTerminalFor(name);
    },
    [setActiveTab],
  );

  useEffect(() => {
    document.title = t.title;
  }, [t]);

  let summary: string;
  if (error) {
    // Matches the original refresh()'s early-return-on-error: only the
    // summary line changes, whatever tables/tabs are already showing
    // (from the last successful `data`) stay exactly as they were.
    if (error.kind === "network") summary = t.serverUnreachable + error.message;
    else if (error.kind === "unauthorized") summary = t.authError;
    else summary = t.unexpectedResponse(error.status);
  } else if (data) {
    const running = data.sessions.filter((s) => s.running).length;
    summary = `${running}/${data.sessions.length} ${t.runningWord}  ·  ${t.configWord}: ${data.config_msg}`;
  } else {
    summary = "…"; // matches the static placeholder before the first successful load
  }

  return (
    <div className="wrap">
      <div className="topbar">
        <h1>{t.title}</h1>
        <div className="langsw">
          <button type="button" className={lang === "tr" ? "active" : ""} onClick={() => setLang("tr")}>
            TR
          </button>
          <button type="button" className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>
            EN
          </button>
        </div>
      </div>
      <div className="sub">{summary}</div>
      <Banners onGoToDiagnostics={() => setActiveTab("diag")} />
      <TabBar active={activeTab} onSelect={setActiveTab} />
      <div>
        {data && activeTab === "running" && (
          <RunningTab selection={selection} onToggleTerminal={onToggleTerminal} onSwitchTab={setActiveTab} />
        )}
        {data && activeTab === "registered" && <RegisteredTab selection={selection} onSwitchTab={setActiveTab} />}
        {data && activeTab === "disabled" && <GroupTable items={data.closed} />}
        {data && activeTab === "retired" && <GroupTable items={data.retired} />}
        {data && activeTab === "layout" && <LayoutTab />}
        {data && activeTab === "diag" && <DiagnosticsTab onAskSuccess={handleDiagAskSuccess} />}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <LangProvider>
      <StatusProvider>
        <AppShell />
      </StatusProvider>
    </LangProvider>
  );
}
