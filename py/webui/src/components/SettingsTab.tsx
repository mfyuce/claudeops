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
 *
 * 2026-09-13: gained a 2nd sub-tab ("Kullanım"/Usage, `t.tabSettingsUsage`)
 * — the original single-panel layout became "General" implicitly. Kept as
 * a SEPARATE sub-tab rather than folding into the general panel because
 * checking usage has a real side effect (see `UsagePanel`'s own comment) —
 * mixing it into the always-visible general controls would make that easy
 * to trigger by accident while just glancing at theme/model settings.
 */

import { useState } from "react";
import { apiSaveSettings, apiUsage, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { Theme, UsageResult } from "../api/types";
import { applyTheme } from "../theme";
import { HostsSection } from "./HostsSection";

type SettingsPatch = {
  theme?: Theme;
  handover_effort?: string;
  default_model?: Record<string, string>;
  provider_bin?: Record<string, string>;
};

type SettingsSubTab = "general" | "usage";

/** Renders one provider's row for the Usage sub-tab — `entries` (when
 * `available`) is provider-shaped free text (`UsageEntry.label`/`percent`/
 * `detail`, straight from `parse_usage_text()`), NOT a fixed set of fields
 * every provider fills in the same way (claude has multiple rows —
 * session + one per weekly model-group; copilot has exactly one, a flat
 * AI-Credits pool) — so this just lists whatever rows came back rather
 * than assuming a shape. */
function UsageProviderRow({ cli, result, t }: { cli: string; result: UsageResult["providers"][string]; t: ReturnType<typeof useLang>["t"] }) {
  if (!result.supported) {
    return (
      <div className="opts" style={{ width: "100%", boxSizing: "border-box" }}>
        <b>{cli}</b> <span className="opts-hint">{t.usageNotSupported}</span>
      </div>
    );
  }
  if (!result.available) {
    const reasonText =
      result.reason === "no_running_session"
        ? t.usageNoSession
        : result.reason === "send_failed"
          ? t.usageSendFailed
          : t.usageParseFailed;
    return (
      <div className="opts" style={{ width: "100%", boxSizing: "border-box" }}>
        <b>{cli}</b> <span className="opts-hint">{reasonText}</span>
      </div>
    );
  }
  return (
    <div className="opts" style={{ width: "100%", boxSizing: "border-box", flexDirection: "column", alignItems: "flex-start" }}>
      <span>
        <b>{cli}</b>{" "}
        {result.checked_via && <span className="opts-hint">{t.usageCheckedVia(result.checked_via)}</span>}
      </span>
      {(result.entries ?? []).map((e, i) => (
        <div key={i} style={{ width: "100%" }}>
          {e.label}: <b>{e.percent}%</b>
          {e.detail && <span className="opts-hint"> · {e.detail}</span>}
        </div>
      ))}
    </div>
  );
}

/** On-demand only (button, not a poll) — deliberately, see `apiUsage`'s own
 * comment: every check really does inject `/usage` into one live running
 * session per provider (briefly changing its screen, restored right after
 * for providers that need it) — a background interval doing that
 * repeatedly, unprompted, to whatever real session happens to be picked,
 * would be a much worse trade than the small friction of a manual button. */
function UsagePanel() {
  const { t, lang } = useLang();
  const [state, setState] = useState<{ kind: "idle" } | { kind: "loading" } | { kind: "ok"; data: UsageResult } | { kind: "error"; message: string }>({
    kind: "idle",
  });

  async function check() {
    setState({ kind: "loading" });
    try {
      const res = await apiUsage(lang);
      setState({ kind: "ok", data: res });
    } catch (e) {
      setState({ kind: "error", message: describeApiError(e, t) });
    }
  }

  return (
    <div className="opts" id="settingsUsagePanel">
      <div className="warn-banner" style={{ flexBasis: "100%" }}>
        {t.usageWarning}
      </div>
      <button type="button" disabled={state.kind === "loading"} onClick={() => void check()}>
        {state.kind === "loading" ? t.usageChecking : t.usageCheckBtn}
      </button>
      {state.kind === "error" && <pre className="layout-result">✗ {state.message}</pre>}
      {state.kind === "ok" &&
        Object.entries(state.data.providers).map(([cli, result]) => (
          <UsageProviderRow key={cli} cli={cli} result={result} t={t} />
        ))}
    </div>
  );
}

export function SettingsTab() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [error, setError] = useState("");
  const [subTab, setSubTab] = useState<SettingsSubTab>("general");
  // Free-text path input — auto-save-on-blur (not on every keystroke like the
  // <select> controls below, that would save a half-typed path on every char).
  // Local draft so typing doesn't fight the settings poll's own value.
  const [binDraft, setBinDraft] = useState<Record<string, string>>({});

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
      <div className="warn-banner">{t.settingsSingleUserWarning}</div>
      <div className="tabs">
        <button type="button" className={subTab === "general" ? "active" : ""} onClick={() => setSubTab("general")}>
          {t.tabSettingsGeneral}
        </button>
        <button type="button" className={subTab === "usage" ? "active" : ""} onClick={() => setSubTab("usage")}>
          {t.tabSettingsUsage}
        </button>
      </div>
      {subTab === "usage" ? (
        <UsagePanel />
      ) : (
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
              <select
                value={settings.handover_effort}
                onChange={(e) => void save({ handover_effort: e.target.value })}
              >
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
          <div className="opts" id="settingsProviderBinPanel">
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              <b>{t.providerBinLabel}</b> {t.providerBinDesc}
            </span>
            {data.cli_list.map((cli) => (
              <label key={cli}>
                {cli}
                <input
                  type="text"
                  placeholder={t.providerBinPlaceholder}
                  value={binDraft[cli] ?? settings.provider_bin[cli] ?? ""}
                  onChange={(e) => setBinDraft((prev) => ({ ...prev, [cli]: e.target.value }))}
                  onBlur={(e) => void save({ provider_bin: { [cli]: e.target.value.trim() } })}
                />
              </label>
            ))}
          </div>
          {error && <pre className="layout-result">✗ {error}</pre>}
          <HostsSection />
        </>
      )}
    </>
  );
}
