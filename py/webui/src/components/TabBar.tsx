/**
 * Replaces the original `render()`'s `tabs.map(...)` block (web.py
 * ~1537-1546). Reads counts from `StatusContext` directly rather than
 * getting them as props, per the plan.
 *
 * `search` (2026-09-04) narrows these counts the same way it narrows each
 * tab's own rows — `matchesSearch` returns true for everyone on an empty
 * query, so the counts are exactly today's totals until the box is used.
 */

import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { matchesSearch } from "./shared/searchFilter";
import type { TabKey } from "../state/tabs";

interface TabBarProps {
  active: TabKey;
  onSelect: (tab: TabKey) => void;
  search: string;
}

export function TabBar({ active, onSelect, search }: TabBarProps) {
  const { t } = useLang();
  const { data } = useStatusContext();

  if (!data) return <div className="tabs" />;

  const running = data.sessions.filter((s) => s.running && matchesSearch(s, search)).length;
  const registered = data.sessions.filter((s) => !s.running && matchesSearch(s, search)).length;
  const disabled = data.closed.filter((r) => matchesSearch(r, search)).length;
  const retired = data.retired.filter((r) => matchesSearch(r, search)).length;

  const tabs: [TabKey, string][] = [
    ["running", `${t.tabRunning} (${running})`],
    ["registered", `${t.tabRegistered} (${registered})`],
    ["disabled", `${t.tabDisabled} (${disabled})`],
    ["retired", `${t.tabRetired} (${retired})`],
    ["layout", t.tabLayout],
    // Running indicator (not a count) — this daemon captures the screen
    // continuously while active, worth a glance even from other tabs.
    ["desktop", data.remote_desktop.running ? `${t.tabDesktop} ●` : t.tabDesktop],
    ["diag", t.tabDiag],
    ["settings", t.tabSettings],
  ];

  return (
    <div className="tabs">
      {tabs.map(([key, label]) => (
        <button key={key} type="button" className={active === key ? "active" : ""} onClick={() => onSelect(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}
