/**
 * Replaces `newProjectForm()` + `onRegCliChange()` + `doRegister()`
 * (web.py ~1865-1917) — the "+ Register new project" form at the bottom
 * of the Registered tab. Adds the folder to the roster; does not start it
 * (matches the original — no `fresh`/mode concept here at all).
 *
 * `model` is `string | null` (not defaulted eagerly): `null` means "no
 * explicit choice yet, use the current CLI's first model" — this is what
 * makes changing the CLI dropdown re-derive the shown model the same way
 * the original's `onRegCliChange()` did by fully re-populating the
 * `<select>` (whose first `<option>` a plain, unmanipulated `<select>`
 * shows by default with no `selected` attribute needed).
 */

import { useState } from "react";
import { apiRegister } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";

const DEFAULT_CLI = "claude";

export function RegisterForm() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  const [name, setName] = useState("");
  const [cwd, setCwd] = useState("");
  const [cli, setCli] = useState(DEFAULT_CLI);
  const [model, setModel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const cliModels = data?.cli_options[cli]?.models ?? [];
  const effectiveModel = model ?? cliModels[0] ?? "";

  function handleCliChange(newCli: string) {
    setCli(newCli);
    setModel(null);
  }

  async function handleSave() {
    setBusy(true);
    try {
      const res = await apiRegister({ name: name.trim(), cwd: cwd.trim(), model: effectiveModel, cli, lang });
      if (!res.ok) window.alert(`${name}: ${res.error}`);
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
    // Original: doesn't clear the name/cwd inputs after a successful
    // save, just re-enables the button and refresh()es — matched here by
    // simply not resetting `name`/`cwd` state.
    refresh();
  }

  if (!data) return null;

  return (
    <div className="opts" style={{ marginTop: ".7rem" }}>
      <span className="opts-hint">
        <b>{t.registerTitle}</b> {t.registerDesc}
      </span>
      <label>
        {t.registerNameLabel}
        <input type="text" placeholder="myproject" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t.registerCwdLabel}
        <input
          type="text"
          placeholder="/home/user/work/myproject"
          value={cwd}
          onChange={(e) => setCwd(e.target.value)}
        />
      </label>
      <label>
        {t.cliLabel}
        <select value={cli} onChange={(e) => handleCliChange(e.target.value)}>
          {data.cli_list.map((c) => (
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
        {busy ? t.registerSaving : t.registerSave}
      </button>
    </div>
  );
}
