/**
 * `uzakgoz` settings (remote-desktop daemon, its own repo like ucli): source dir, ready-made binary, port. Auto-save on
 * blur (free text, a half-typed path must not be saved per keystroke); an empty field removes the key (= default).
 * The backend validates (`settings.uzakgoz_config()`: dir needs a Cargo.toml, bin must be executable, port 1024-65535)
 * and silently skips an invalid value, so the hint below says what is used when a field is left empty.
 */

import { useState } from "react";
import { apiSaveSettings, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

const FIELDS = ["dir", "bin", "port"] as const;

export function UzakgozSettings() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  if (!data) return null;
  const cfg = data.settings.uzakgoz ?? {};
  const label: Record<(typeof FIELDS)[number], string> = {
    dir: t.uzakgozDirLabel,
    bin: t.uzakgozBinLabel,
    port: t.uzakgozPortLabel,
  };

  async function save(field: string, value: string) {
    setError("");
    try {
      const res = await apiSaveSettings({ uzakgoz: { [field]: value.trim() }, lang });
      if (!res.ok) setError(res.error);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) showToast(t.authErrorShort);
      else setError(describeApiError(e, t));
    }
    setDraft((p) => {
      const n = { ...p };
      delete n[field];
      return n;
    });
    refresh();
  }

  return (
    <details className="opts" id="desktopUzakgozSettings">
      <summary>{t.uzakgozSettingsTitle}</summary>
      {FIELDS.map((f) => (
        <label key={f}>
          {label[f]}
          <input
            type={f === "port" ? "number" : "text"}
            placeholder={t.uzakgozPlaceholderAuto}
            value={draft[f] ?? cfg[f] ?? ""}
            onChange={(e) => setDraft((p) => ({ ...p, [f]: e.target.value }))}
            onBlur={(e) => void save(f, e.target.value)}
          />
        </label>
      ))}
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        {t.uzakgozSettingsHint}
      </span>
      {error && <pre className="layout-result">✗ {error}</pre>}
    </details>
  );
}
