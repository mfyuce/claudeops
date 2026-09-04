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
 *
 * Sequencing step 8 additionally wires `<TerminalModal>` here: rendered
 * once, conditionally on `openTerminalFor`, keyed by it so switching WHICH
 * session's terminal is open forces a clean remount (see that component's
 * own header comment).
 */

import { useCallback, useEffect, useState } from "react";
import { Banners } from "./components/Banners";
import { DesktopTab } from "./components/DesktopTab";
import { DiagnosticsTab } from "./components/DiagnosticsTab";
import { GroupTable } from "./components/GroupTable";
import { LayoutTab } from "./components/LayoutTab";
import { RegisteredTab } from "./components/RegisteredTab/RegisteredTab";
import { RunningTab } from "./components/RunningTab/RunningTab";
import { SearchBox } from "./components/shared/SearchBox";
import { SettingsTab } from "./components/SettingsTab";
import { TabBar } from "./components/TabBar";
import { TerminalModal } from "./components/TerminalModal/TerminalModal";
import { LangProvider, useLang } from "./i18n/LangContext";
import { StatusProvider, useStatusContext } from "./state/StatusContext";
import { useSelection } from "./state/selection";
import { isTabKey, TAB_STORAGE_KEY, type TabKey } from "./state/tabs";
import { applyTheme } from "./theme";

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
  // openTerminalFor: which session's terminal modal (if any) is open —
  // set by SessionRow's terminal button and DiagnosticsTab's "ask"
  // cross-tab flow, consumed below by <TerminalModal>.
  const [openTerminalFor, setOpenTerminalFor] = useState<string | null>(null);
  // Shared across Running/Registered per the plan — one Set, not a third
  // Context (see state/selection.ts's doc comment).
  const selection = useSelection();
  // Search box (2026-09-04): lives above <TabBar>, not inside any one tab,
  // so it survives tab switches and scopes all 4 list tabs' rows + TabBar's
  // own counts at once. Plain local state — not persisted (localStorage/
  // settings.json), unlike activeTab/theme: a stale filter silently
  // narrowing a fresh page load would be more surprising than useful here.
  const [search, setSearch] = useState("");

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
    // Suffix (not t.title itself — that stays a faithful 1:1 port of the
    // original panel's title) so the browser tab is distinguishable at a
    // glance from the old panel's tab when both are open side by side.
    document.title = `${t.title} · React`;
  }, [t]);

  // TODO L73 (2026-09-02): keep <html data-theme> in sync with the server's
  // settings.json — covers the initial load (main.tsx's applyCachedTheme()
  // is only a same-instant guess from localStorage) AND a theme change made
  // from another open tab/device, which arrives here as an ordinary
  // StatusContext update (WS push, same as everything else in `data`).
  useEffect(() => {
    if (data?.settings.theme) applyTheme(data.settings.theme);
  }, [data?.settings.theme]);

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
    summary = `${running}/${data.sessions.length} ${t.runningWord}  ·  ${t.configWord}: ${t.configMsg(data.config_code, data.config_detail)}`;
  } else {
    summary = "…"; // matches the static placeholder before the first successful load
  }

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="topbar-title">
          <h1>{t.title}</h1>
          <span className="build-badge" title="React + TypeScript + WebSocket rewrite — feature/react-ui">
            React
          </span>
        </div>
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
      <SearchBox value={search} onChange={setSearch} />
      <TabBar active={activeTab} onSelect={setActiveTab} search={search} />
      <div>
        {data && activeTab === "running" && (
          <RunningTab selection={selection} onToggleTerminal={onToggleTerminal} onSwitchTab={setActiveTab} search={search} />
        )}
        {data && activeTab === "registered" && (
          <RegisteredTab selection={selection} onSwitchTab={setActiveTab} search={search} />
        )}
        {data && activeTab === "disabled" && <GroupTable items={data.closed} search={search} />}
        {data && activeTab === "retired" && <GroupTable items={data.retired} search={search} />}
        {data && activeTab === "layout" && <LayoutTab />}
        {data && activeTab === "desktop" && <DesktopTab />}
        {data && activeTab === "diag" && <DiagnosticsTab onAskSuccess={handleDiagAskSuccess} />}
        {data && activeTab === "settings" && <SettingsTab />}
      </div>
      {openTerminalFor && (
        <TerminalModal key={openTerminalFor} name={openTerminalFor} onClose={() => setOpenTerminalFor(null)} />
      )}
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
