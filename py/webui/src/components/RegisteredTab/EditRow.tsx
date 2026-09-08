/**
 * Inline edit form for a REGISTERED (stopped) row — name/folder/model,
 * mirrors `RegisterForm`'s fields but pre-filled and PATCHing the existing
 * roster row in place (`apiEditProject`/`_edit_project()`) instead of
 * appending a new one.
 *
 * User decision (2026-09-08): editing is blocked while the session is
 * running — `RegisteredTab` only ever mounts this for `!session.running`
 * rows, and the backend independently re-checks (in case it started running
 * in the gap between page load and submit) rather than trusting the
 * frontend alone. Once stopped, the folder/name/model are NOT restricted
 * beyond basic structural validity (name syntax + uniqueness — both
 * load-bearing for session identity elsewhere in the codebase) — the
 * backend instead returns non-blocking `warnings` (target folder missing,
 * or the old folder's real conversation history becoming unreachable) that
 * this component surfaces but never uses to prevent the save.
 */

import { useState } from "react";
import { apiEditProject } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { cliListFor, cliOptionsFor } from "../../state/hosts";
import type { SessionInfo } from "../../api/types";

interface EditRowProps {
  session: SessionInfo;
  colspan: number;
  onClose: () => void;
}

export function EditRow({ session, colspan, onClose }: EditRowProps) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  const [name, setName] = useState(session.name);
  const [cwd, setCwd] = useState(session.cwd);
  const [cli, setCli] = useState(session.cli);
  const [model, setModel] = useState(session.model || "");
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState("");

  const cliList = cliListFor(data, session.host);
  const cliModels = cliOptionsFor(data, session.host, cli).models;
  const effectiveModel = model || cliModels[0] || "";

  function handleCliChange(newCli: string) {
    setCli(newCli);
    setModel("");
  }

  async function handleSave() {
    setBusy(true);
    setError("");
    setWarnings([]);
    try {
      const res = await apiEditProject({
        name: session.name,
        host: session.host,
        new_name: name.trim(),
        new_cwd: cwd.trim(),
        new_model: effectiveModel,
        new_cli: cli,
        lang,
      });
      if (!res.ok) {
        setError(res.error);
      } else {
        refresh();
        if (res.warnings.length === 0) {
          onClose();
        } else {
          setWarnings(res.warnings);
        }
      }
    } catch (e) {
      setError(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className="opts-row">
      <td colSpan={colspan}>
        <div className="opts">
          <span className="opts-hint">
            <b>{t.editTitle}</b>
          </span>
          <label>
            {t.registerNameLabel}
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            {t.registerCwdLabel}
            <input type="text" value={cwd} onChange={(e) => setCwd(e.target.value)} />
          </label>
          <label>
            {t.cliLabel}
            <select value={cli} onChange={(e) => handleCliChange(e.target.value)}>
              {cliList.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t.modelLabel}
            <select value={effectiveModel} onChange={(e) => setModel(e.target.value)}>
              {cliModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="go" disabled={busy} onClick={() => void handleSave()}>
            {busy ? t.registerSaving : t.editSave}
          </button>
          <button type="button" onClick={onClose}>
            {t.editCancel}
          </button>
          {error && <span className="opts-hint">✗ {error}</span>}
          {warnings.map((w) => (
            <div key={w} className="warn-banner">
              ⚠ {w}
            </div>
          ))}
        </div>
      </td>
    </tr>
  );
}
