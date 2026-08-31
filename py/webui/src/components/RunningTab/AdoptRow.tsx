/**
 * Replaces `adoptOptsRow()` (web.py ~1815-1831) — same "local `useState`,
 * no shadow dict" treatment as `OptionsRow` (mirrors the original's
 * `adoptChoice` dict, which existed for exactly the same reason
 * `optsChoice` did and is eliminated the same way: this component only
 * ever exists mounted while its row is open, so plain `useState`
 * initialized on mount already survives every background `StatusContext`
 * update).
 *
 * CLI is NOT editable here (unlike `OptionsRow`) — shown as a read-only
 * badge, matching the original's comment: an adopted process's CLI is its
 * identity (`_adopt()` never lets the caller override it; "devral" only
 * ever means "attach remote-control to what's already running").
 */

import { useState } from "react";
import { apiAdopt } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { EMPTY_CLI_OPTIONS, type SessionInfo } from "../../api/types";
import { CliFields, OTHER_MODEL_VALUE } from "./CliFields";
import { DEFAULT_PERMISSION_MODE, defaultEffort } from "./cliDefaults";

interface AdoptRowProps {
  session: SessionInfo;
  colspan: number;
  onClose: () => void;
}

export function AdoptRow({ session, colspan, onClose }: AdoptRowProps) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  const cliOptions = data?.cli_options[session.cli] ?? EMPTY_CLI_OPTIONS;

  const [newName, setNewName] = useState(session.name);
  const [model, setModel] = useState("");
  const [modelOther, setModelOther] = useState("");
  const [permissionMode, setPermissionMode] = useState(DEFAULT_PERMISSION_MODE);
  const [effort, setEffort] = useState(() => defaultEffort(cliOptions));
  const [busy, setBusy] = useState(false);

  async function handleAdopt() {
    if (!window.confirm(t.adoptWarn(session.name))) return;
    setBusy(true);
    const resolvedModel = model === OTHER_MODEL_VALUE ? modelOther : model;
    try {
      const res = await apiAdopt({
        name: session.name,
        new_name: newName.trim(),
        model: resolvedModel,
        permission_mode: permissionMode,
        effort,
        lang,
      });
      if (res.ok) window.alert(t.adopted + res.new_name);
      else window.alert(`${session.name}: ${res.error}`);
    } catch (e) {
      window.alert(describeApiError(e, t));
    }
    // Original: unconditionally closes + refreshes after the request
    // settles (`adoptFor = null; adoptChoice[oldName] = null; refresh();`).
    onClose();
    refresh();
  }

  return (
    <tr className="opts-row">
      <td colSpan={colspan}>
        <div className="opts">
          <span className="opts-hint">{t.adoptWarn(session.name)}</span>
          <label>
            {t.adoptNameLabel}
            <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </label>
          <label>
            {t.cliLabel}
            <span className="cli-badge">{session.cli}</span>
          </label>
          <CliFields
            currentModelLabel={session.model || cliOptions.models[0] || ""}
            model={model}
            modelOther={modelOther}
            permissionMode={permissionMode}
            effort={effort}
            cliOptions={cliOptions}
            onModelChange={setModel}
            onModelOtherChange={setModelOther}
            onPermissionModeChange={setPermissionMode}
            onEffortChange={setEffort}
          />
          <button type="button" className="go" disabled={busy} onClick={() => void handleAdopt()}>
            {busy ? t.adopting : t.adoptBtn}
          </button>
          <button type="button" onClick={onClose}>
            {t.cancelBtn}
          </button>
        </div>
      </td>
    </tr>
  );
}
