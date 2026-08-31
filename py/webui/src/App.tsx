/**
 * Replaces the original `render()`'s tab dispatch + the static shell
 * around it (topbar/lang-switch/summary line — web.py's `<body>` markup
 * + `applyStaticText()`/`setLang()`). React rewrite plan (dynamic-
 * crunching-lemon.md), Sequencing step 5.
 *
 * `App` (default export) only sets up the two Contexts; `AppShell` is the
 * component that actually owns `activeTab` (and, once step 6 lands in the
 * next commit, `openTerminalFor`/the shared selection Set — both only
 * make sense once something downstream actually consumes them) and
 * consumes both Contexts — a component can't call `useContext` for a
 * Provider it renders in the very same return, so the split is required,
 * not just style.
 */

import { useCallback, useEffect, useState } from "react";
import { Banners } from "./components/Banners";
import { TabBar } from "./components/TabBar";
import { LangProvider, useLang } from "./i18n/LangContext";
import { StatusProvider, useStatusContext } from "./state/StatusContext";
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

/** All six tabs are stubbed this commit — Running/Registered get real
 * content in the very next commit (plan Sequencing step 6), Disabled/
 * Retired/Layout/Diagnostics later still (step 7). Stubbing all of them
 * for now proves tab-switching + localStorage persistence + counts all
 * work end-to-end before any tab has real content. */
function PlaceholderTab({ label }: { label: string }) {
  return <div className="opts-hint">{label} — not built in this stage yet.</div>;
}

function AppShell() {
  const { t, lang, setLang } = useLang();
  const { data, error } = useStatusContext();
  const [activeTab, setActiveTabState] = useState<TabKey>(readStoredTab);

  const setActiveTab = useCallback((tab: TabKey) => {
    setActiveTabState(tab);
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab);
    } catch {
      // ignore — localStorage can throw (private browsing/storage disabled)
    }
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
        {data && activeTab === "running" && <PlaceholderTab label={t.tabRunning} />}
        {data && activeTab === "registered" && <PlaceholderTab label={t.tabRegistered} />}
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
