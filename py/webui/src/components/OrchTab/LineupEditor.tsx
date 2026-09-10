/**
 * TOBEDECIDED#15 Phase 1 — the "Ekip"/Team tab's lineup picker. Reads the
 * SAME shared `selection` Set the Running tab's checkboxes already fill
 * (`state/selection.ts`, threaded down from `App` exactly like
 * `RunningTab`/`RegisteredTab` receive it) — one button here turns
 * "whatever's checked in the Running tab right now" into worker lineup
 * entries. No `BulkBar`/`SessionRow` changes needed: Phase 1 has only one
 * role, so there's nothing for a role-picker to pick yet.
 */

import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { eligibleSelectedSessions } from "../../state/orch";
import type { OrchDraftParticipant } from "../../api/types";
import type { SelectionControls } from "../../state/selection";

interface LineupEditorProps {
  lineup: OrchDraftParticipant[];
  selection: SelectionControls;
  onAddSelected: () => void;
  onRemove: (host: string, name: string) => void;
}

export function LineupEditor({ lineup, selection, onAddSelected, onRemove }: LineupEditorProps) {
  const { t } = useLang();
  const { data } = useStatusContext();

  const selectedCount = data ? eligibleSelectedSessions(data.sessions, selection.selected).length : 0;

  return (
    <div className="opts" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.orchLineupTitle}</b> — {t.orchAddSelectedHint}
      </span>
      <button type="button" className="start" disabled={selectedCount === 0} onClick={onAddSelected}>
        {t.orchAddSelectedBtn}
        {selectedCount > 0 ? ` (${selectedCount})` : ""}
      </button>
      {lineup.length === 0 ? (
        <span className="opts-hint">{t.orchLineupEmpty}</span>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: ".3rem", flexBasis: "100%", marginTop: ".3rem" }}>
          {lineup.map((p) => (
            <div key={`${p.host}:${p.name}`} style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
              <span>{p.name}</span>
              <span className="cli-badge">{p.cli}</span>
              <button type="button" className="closebtn" onClick={() => onRemove(p.host, p.name)}>
                {t.orchRemoveBtn}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
