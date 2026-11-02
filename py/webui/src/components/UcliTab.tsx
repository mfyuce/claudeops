/**
 * "ucli" tab (owner, 2026-11-01: ucli is an integrated part of claudeops): three sections.
 * Global = endpoint, usage-warning thresholds, web search/fetch. Start = flags and limits that reach only NEWLY started
 * sessions (limits, reasoning, stream, script layer). Run = the tmux-less ask panel (`IoAskPanel`, unchanged).
 * The settings fields moved here from the Settings tab with their behaviour unchanged.
 */

import { useState } from "react";
import { useLang } from "../i18n/LangContext";
import { IoAskPanel } from "./IoAskPanel";
import { UcliKeysPanel } from "./UcliKeysPanel";
import { UcliSpendPanel } from "./UcliSpendPanel";
import { UcliSettingsPanels } from "./UcliSettingsPanels";

type Section = "run" | "start" | "global";

export function UcliTab() {
  const { t } = useLang();
  const [section, setSection] = useState<Section>("run");
  const items: [Section, string][] = [
    ["run", t.ucliSectionRun],
    ["start", t.ucliSectionStart],
    ["global", t.ucliSectionGlobal],
  ];
  return (
    <>
      <div className="tabs">
        {items.map(([k, label]) => (
          <button key={k} type="button" className={section === k ? "active" : ""} onClick={() => setSection(k)}>
            {label}
          </button>
        ))}
      </div>
      {section === "run" && <IoAskPanel />}
      {section === "start" && <UcliSettingsPanels group="start" />}
      {section === "global" && (
        <>
          <UcliSpendPanel />
          <UcliKeysPanel />
          <UcliSettingsPanels group="global" />
        </>
      )}
    </>
  );
}
