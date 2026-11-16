/**
 * Replaces the original `render()`'s `tabs.map(...)` block (web.py
 * ~1537-1546). Reads counts from `StatusContext` directly rather than
 * getting them as props, per the plan.
 *
 * `search` (2026-09-04) narrows these counts the same way it narrows each
 * tab's own rows — `matchesSearch` returns true for everyone on an empty
 * query, so the counts are exactly today's totals until the box is used.
 */

import { useRef } from "react";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { matchesSearch } from "./shared/searchFilter";
import { useTabShortcuts } from "./shared/useTabShortcuts";
import type { UiExtension } from "../api/types";
import { entryTabFor, groupOf, topTabOf, visibleSubs, type TabGroup, type TabKey } from "../state/tabs";

interface TabBarProps {
  active: TabKey;
  onSelect: (tab: TabKey) => void;
  search: string;
  /** K10 extension tabs (server-filtered by the caller's role); empty when none. */
  extensions?: UiExtension[];
}

export function TabBar({ active, onSelect, search, extensions = [] }: TabBarProps) {
  const { t, lang } = useLang();
  const { data } = useStatusContext();
  useTabShortcuts();
  const lastSub = useRef<Partial<Record<TabGroup, string>>>({});

  if (!data) return <div className="tabs" />;

  const running = data.sessions.filter((s) => s.running && matchesSearch(s, search)).length;
  const registered = data.sessions.filter((s) => !s.running && matchesSearch(s, search)).length;
  const disabled = data.closed.filter((r) => matchesSearch(r, search)).length;
  const retired = data.retired.filter((r) => matchesSearch(r, search)).length;

  // Total over all identities (`stewards` slice); a payload without it = the default's count.
  const stewardOpen = data.stewards?.length
    ? data.stewards.reduce((a, x) => a + (x.open_questions || 0), 0)
    : data.steward?.open_questions ?? 0;

  const gopts = { restricted: !!data.restricted, hasReadlist: (data.ext_routes ?? []).includes("/readlist/") };
  const toolsSubs = visibleSubs("tools", gopts);
  const settingsSubs = visibleSubs("settings", gopts);

  // Sub-tab labels (legacy keys). Indicators/counts are kept on the sub buttons and mirrored on the "Araçlar" button.
  const subLabel: Record<string, string> = {
    // No count: tmux'suz IoProvider sessions live in per-project `.ucli/chat/*.jsonl` files (bkz. IoAskPanel.tsx).
    ucli: t.tabUcli,
    // Running indicator (not a count); TOBEDECIDED#15 Phase 1 allows only one active run fleet-wide.
    team: data.orch.active ? `${t.tabTeam} ●` : t.tabTeam,
    // Open-question count: the one number the owner acts on from this tab (answers unblock sessions).
    steward: stewardOpen ? `${t.tabSteward} (${stewardOpen})` : t.tabSteward,
    // Running indicator: this daemon captures the screen continuously while active.
    desktop: data.remote_desktop.running ? `${t.tabDesktop} ●` : t.tabDesktop,
    readlist: t.tabReadlist,
    settings: t.tabSettings,
    snapshots: t.tabSnapshots,
    diag: t.tabDiag,
  };
  // Hidden sub-tabs still surface their signals on the group button (open questions / running run / capture).
  const toolsBadge = toolsSubs.includes("steward") && stewardOpen ? ` (${stewardOpen})` : "";
  const toolsDot = (toolsSubs.includes("team") && data.orch.active) || (toolsSubs.includes("desktop") && data.remote_desktop.running) ? " ●" : "";

  const tabs: [TabKey | TabGroup, string][] = [
    ["running", `${t.tabRunning} (${running})`],
    ["registered", `${t.tabRegistered} (${registered})`],
    ["disabled", `${t.tabDisabled} (${disabled})`],
    ["retired", `${t.tabRetired} (${retired})`],
    // No count: history comes from its own endpoint, not the status payload.
    ["history", t.tabHistory],
    ...(toolsSubs.length ? ([["tools", `${t.tabTools}${toolsBadge}${toolsDot}`]] as [TabGroup, string][]) : []),
    ...extensions.map((e): [TabKey, string] => [`ext:${e.id}`, lang === "en" ? e.title_en || e.title : e.title]),
    ...(settingsSubs.length ? ([["settings", t.tabSettings]] as [TabKey, string][]) : []),
  ];

  const topActive = topTabOf(active);
  const group = groupOf(active);
  const subs = group === "tools" ? toolsSubs : group === "settings" ? settingsSubs : [];
  if (group && subs.includes(active)) lastSub.current[group] = active;

  function selectTop(key: TabKey | TabGroup) {
    if (key === "tools" || key === "settings") {
      const entry = entryTabFor(key, gopts, lastSub.current[key]);
      if (entry) onSelect(entry);
      return;
    }
    onSelect(key);
  }

  return (
    <>
      <div className="tabs">
        {tabs.map(([key, label]) => (
          <button key={key} type="button" className={topActive === key ? "active" : ""} onClick={() => selectTop(key)}>
            {label}
          </button>
        ))}
      </div>
      {subs.length > 1 && (
        <div className="subtabs">
          {subs.map((k) => (
            <button key={k} type="button" className={active === k ? "active" : ""} onClick={() => onSelect(k)}>
              {subLabel[k]}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
