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

/** Disabled/Retired/Layout/Diagnostics are later stages (plan Sequencing
 * step 7) — stubbed so tab-switching/localStorage-persistence/counts all
 * work end-to-end even though only Running/Registered have real content
 * as of this commit. */
function PlaceholderTab({ label }: { label: string }) {
  return <div className="opts-hint">{label} — not built in this stage yet.</div>;
}

function AppShell() {
  const { t, lang, setLang } = useLang();
  const { data, error } = useStatusContext();
  const [activeTab, setActiveTabState] = useState<TabKey>(readStoredTab);
  // openTerminalFor: the state SLOT for the later terminal-modal stage
  // (plan: "just the state slot for now, no modal component yet"). Only
  // the setter is used this stage (SessionRow's terminal button calls
  // it via onToggleTerminal below) — the value itself is deliberately not
  // read/threaded past that point, so there's no binding for it here (an
  // unread `const` would fail `noUnusedLocals`, and rendering anything
  // from it would be exactly the "fake modal" the plan says not to build
  // yet — a later stage consumes it for real).
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
        {data && activeTab === "disabled" && <PlaceholderTab label={t.tabDisabled} />}
        {data && activeTab === "retired" && <PlaceholderTab label={t.tabRetired} />}
        {data && activeTab === "layout" && <PlaceholderTab label={t.tabLayout} />}
        {data && activeTab === "diag" && <PlaceholderTab label={t.tabDiag} />}
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
