/**
 * "Ayarlar"/"Settings" tab — server-side persisted user preferences (TODO
 * L73, 2026-09-02 decision): theme, default handover effort, default model
 * per CLI provider. `~/.claude/claudeops/settings.json` on the backend —
 * same across every browser/device, unlike `cops_lang`/`cops_tab`
 * (localStorage-only, per-browser, deliberately out of scope here).
 *
 * Each control auto-saves on change (no separate Save button) — matches
 * the language switcher's immediate-apply feel; `apiSaveSettings` sends
 * only the changed field as a partial patch, `save_settings()`'s merge
 * leaves every other field untouched.
 */

import { useState } from "react";
import { apiSaveSettings, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { Theme } from "../api/types";
import { applyTheme } from "../theme";

type SettingsPatch = { theme?: Theme; handover_effort?: string; default_model?: Record<string, string> };

export function SettingsTab() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [error, setError] = useState("");

  if (!data) return null;
  const settings = data.settings;

  async function save(patch: SettingsPatch) {
    setError("");
    try {
      const res = await apiSaveSettings({ ...patch, lang });
      if (!res.ok) {
        setError(res.error);
        return;
      }
      // Instant local feedback — the confirming StatusContext update (WS
      // push from this same save, or the next poll) arrives a beat later.
      if (patch.theme) applyTheme(patch.theme);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.alert(t.authErrorShort);
      else setError(describeApiError(e, t));
    }
    refresh();
  }

  // Union of every provider's effort words (order: first-seen across
  // cli_list) — providers don't share a vocabulary (claude has "xhigh",
  // agy's top is "high"), so a single global preference can only ever
  // apply where it happens to match (`default_handover_effort()`'s own
  // fallback handles the rest, same as an empty/unset override).
  const effortOptions = Array.from(new Set(Object.values(data.cli_options).flatMap((o) => o.effort_levels)));

  return (
    <>
      <div className="opts" id="settingsPanel">
        <span className="opts-hint" style={{ flexBasis: "100%" }}>
          {t.settingsDesc}
        </span>
        <label>
          {t.themeLabel}
          <select value={settings.theme} onChange={(e) => void save({ theme: e.target.value as Theme })}>
            <option value="system">{t.themeSystem}</option>
            <option value="light">{t.themeLight}</option>
            <option value="dark">{t.themeDark}</option>
          </select>
        </label>
        <label title={t.handoverEffortHint}>
          {t.handoverEffortLabel}
          <select value={settings.handover_effort} onChange={(e) => void save({ handover_effort: e.target.value })}>
            <option value="">{t.settingsAuto}</option>
            {effortOptions.map((lvl) => (
              <option key={lvl} value={lvl}>
                {lvl}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="opts" id="settingsModelPanel">
        <span className="opts-hint" style={{ flexBasis: "100%" }}>
          {t.defaultModelLabel}
        </span>
        {data.cli_list.map((cli) => (
          <label key={cli}>
            {cli}
            <select
              value={settings.default_model[cli] ?? ""}
              onChange={(e) => void save({ default_model: { [cli]: e.target.value } })}
            >
              <option value="">{t.settingsAutoModel(data.cli_options[cli]?.models[0] ?? "?")}</option>
              {(data.cli_options[cli]?.models ?? []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {error && <pre className="layout-result">✗ {error}</pre>}
    </>
  );
}
