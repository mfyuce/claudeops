/**
 * Replaces the original `render()`'s `tabs.map(...)` block (web.py
 * ~1537-1546). Reads counts from `StatusContext` directly rather than
 * getting them as props, per the plan.
 */

import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { TabKey } from "../state/tabs";

interface TabBarProps {
  active: TabKey;
  onSelect: (tab: TabKey) => void;
}

export function TabBar({ active, onSelect }: TabBarProps) {
  const { t } = useLang();
  const { data } = useStatusContext();

  if (!data) return <div className="tabs" />;

  const running = data.sessions.filter((s) => s.running).length;
  const registered = data.sessions.filter((s) => !s.running).length;

  const tabs: [TabKey, string][] = [
    ["running", `${t.tabRunning} (${running})`],
    ["registered", `${t.tabRegistered} (${registered})`],
    ["disabled", `${t.tabDisabled} (${data.closed.length})`],
    ["retired", `${t.tabRetired} (${data.retired.length})`],
    ["layout", t.tabLayout],
    ["diag", t.tabDiag],
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
