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
import { cliListFor, cliOptionsFor, LOCAL_HOST } from "../../state/hosts";

const DEFAULT_CLI = "claude";

export function RegisterForm() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();

  const [name, setName] = useState("");
  const [cwd, setCwd] = useState("");
  const [host, setHost] = useState(LOCAL_HOST);
  const [cli, setCli] = useState(DEFAULT_CLI);
  const [model, setModel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Success was previously silent (form just stayed as-is, refresh() ran in
  // the background) — a live user hit this exact confusion (2026-09-07,
  // registered "shell" on a remote host successfully but had no way to tell
  // apart from a failure, since neither showed anything). Now explicit.
  const [message, setMessage] = useState("");

  const cliList = cliListFor(data, host);
  const cliModels = cliOptionsFor(data, host, cli).models;
  const effectiveModel = model ?? cliModels[0] ?? "";

  function handleHostChange(newHost: string) {
    setHost(newHost);
    // A different host's CLI list may not even include the currently-chosen
    // `cli` (or may order models differently) — reset both, same reasoning
    // as `handleCliChange` below.
    setCli(DEFAULT_CLI);
    setModel(null);
  }

  function handleCliChange(newCli: string) {
    setCli(newCli);
    setModel(null);
  }

  async function handleSave() {
    setBusy(true);
    setMessage("");
    try {
      const savedName = name.trim();
      const res = await apiRegister({
        name: savedName,
        cwd: cwd.trim(),
        host,
        model: effectiveModel,
        cli,
        lang,
      });
      if (!res.ok) {
        window.alert(`${name}: ${res.error}`);
      } else {
        setMessage(t.registerSuccess(savedName));
        setName("");
        setCwd("");
      }
    } catch (e) {
      window.alert(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
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
      {data.hosts.length > 0 && (
        <label>
          {t.hostNameLabel}
          <select value={host} onChange={(e) => handleHostChange(e.target.value)}>
            <option value={LOCAL_HOST}>{t.hostLocalLabel}</option>
            {data.hosts.map((h) => (
              <option key={h.name} value={h.name}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
      )}
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
        {busy ? t.registerSaving : t.registerSave}
      </button>
      {message && <span className="opts-hint">{message}</span>}
    </div>
  );
}
