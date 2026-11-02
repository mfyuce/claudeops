/**
 * ucli settings, moved out of the Settings tab into the "ucli" tab (owner, 2026-11-01: "ucli artık claudeops'un entegre
 * bir yapısı"). Two groups: `global` (endpoint, usage-warning thresholds, web search/fetch) and `start` (limits, reasoning,
 * stream and the script layer: flags that only reach NEWLY started sessions). The fields, their drafts-until-blur and the
 * `save` semantics are the Settings tab's own, unchanged.
 */

import { useState } from "react";
import { apiSaveSettings, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import { friendlyUcliError } from "../api/ucliErrors";
import { useStatusContext } from "../state/StatusContext";

import type { SettingsPatch } from "./SettingsTab";

/** `settings.py`'nin `_OFF_WORDS`i: `ucli_web.search_docker` ve `ucli_limits.stream` için "kapalı" sayılan değerler. */
const OFF_WORDS = new Set(["off", "0", "false", "no", "n", "hayir", "hayır", "kapali", "kapalı", "disabled", "none"]);

/** settings.json elle düzenlenebildiği için bir alan string yerine liste/boş olabilir. */
function asText(v: unknown): string {
  return Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v);
}

/** `settings.py`'nin `_valid_http_url`inin istemci karşılığı: yalnız İPUCU için (karar backend'in). */
function isValidHttpUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return (u.protocol === "http:" || u.protocol === "https:") && u.hostname !== "";
  } catch {
    return false;
  }
}

export function UcliSettingsPanels({ group }: { group: "global" | "start" }) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [error, setError] = useState("");
  const [ucliLimitsDraft, setUcliLimitsDraft] = useState<Record<string, string>>({});
  const [ucliWebDraft, setUcliWebDraft] = useState<Record<string, string>>({});
  const [ucliEndpointDraft, setUcliEndpointDraft] = useState<string | null>(null);
  const [ucliWarnDraft, setUcliWarnDraft] = useState<Record<string, string>>({});

  if (!data) return null;
  const settings = data.settings;
  const webCfg = settings.ucli_web ?? {};
  const webSearchUrl = (ucliWebDraft.search_url ?? asText(webCfg.search_url)).trim();
  const webDockerOff = OFF_WORDS.has(asText(webCfg.search_docker).trim().toLowerCase());
  const webFetchDomains = (ucliWebDraft.allow_fetch_domains ?? asText(webCfg.allow_fetch_domains)).trim();
  const rawScriptMode = asText(settings.ucli_script?.mode).trim().toLowerCase();
  const scriptMode = rawScriptMode === "read" || rawScriptMode === "full" ? rawScriptMode : "";
  const streamOff = OFF_WORDS.has(asText(settings.ucli_limits?.stream).trim().toLowerCase());

  async function save(patch: SettingsPatch) {
    setError("");
    try {
      const res = await apiSaveSettings({ ...patch, lang });
      if (!res.ok) {
        setError(res.error);
        return;
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) showToast(t.authErrorShort);
      else setError(describeApiError(e, t));
    }
    refresh();
  }

  if (!data.cli_list.includes("ucli")) return <p className="opts-hint">{t.ucliTabNoCli}</p>;

  return (
    <>
      {error && <pre className="layout-result">✗ {friendlyUcliError(error, lang)}</pre>}
      {group === "global" && (
        <>
          <div className="opts" id="settingsUcliEndpointPanel">
            <label title={t.ucliEndpointHint} style={{ flexBasis: "100%" }}>
              {t.ucliEndpointLabel}
              <input
                type="text"
                placeholder={t.ucliEndpointPlaceholder}
                value={ucliEndpointDraft ?? asText(settings.ucli_endpoint)}
                onChange={(e) => setUcliEndpointDraft(e.target.value)}
                onBlur={(e) => {
                  void save({ ucli_endpoint: e.target.value.trim() });
                  setUcliEndpointDraft(null);
                }}
              />
            </label>
          </div>
          <div className="opts" id="settingsUcliUsageWarnPanel">
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              <b>{t.ucliUsageWarnLabel}</b> {t.ucliUsageWarnDesc}
            </span>
            {(
              [
                ["amber", t.ucliUsageWarnAmberLabel, "1M"],
                ["red", t.ucliUsageWarnRedLabel, "3M"],
              ] as const
            ).map(([field, label, def]) => (
              <label key={field}>
                {label}
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder={t.ucliUsageWarnPlaceholder(def)}
                  value={ucliWarnDraft[field] ?? settings.ucli_usage_warn?.[field] ?? ""}
                  onChange={(e) => setUcliWarnDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                  onBlur={(e) => void save({ ucli_usage_warn: { [field]: e.target.value.trim() } })}
                />
              </label>
            ))}
          </div>
          <div className="opts" id="settingsUcliWebPanel">
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              <b>{t.ucliWebLabel}</b> {t.ucliWebDesc}
            </span>
            <label title={t.ucliWebSearchUrlHint}>
              {t.ucliWebSearchUrlLabel}
              <input
                type="text"
                placeholder={t.ucliWebSearchUrlPlaceholder}
                value={ucliWebDraft.search_url ?? asText(webCfg.search_url)}
                onChange={(e) => setUcliWebDraft((prev) => ({ ...prev, search_url: e.target.value }))}
                onBlur={(e) => void save({ ucli_web: { search_url: e.target.value.trim() } })}
              />
            </label>
            <label title={t.ucliWebDockerHint}>
              {t.ucliWebDockerLabel}
              <select
                value={webDockerOff ? "off" : ""}
                disabled={webSearchUrl !== ""}
                onChange={(e) => void save({ ucli_web: { search_docker: e.target.value } })}
              >
                <option value="">{t.ucliWebDockerAuto}</option>
                <option value="off">{t.ucliWebDockerOff}</option>
              </select>
            </label>
            <label title={t.ucliWebFetchHint}>
              {t.ucliWebFetchLabel}
              <input
                type="text"
                placeholder={t.ucliWebFetchPlaceholder}
                value={ucliWebDraft.allow_fetch_domains ?? asText(webCfg.allow_fetch_domains)}
                onChange={(e) => setUcliWebDraft((prev) => ({ ...prev, allow_fetch_domains: e.target.value }))}
                onBlur={(e) => void save({ ucli_web: { allow_fetch_domains: e.target.value.trim() } })}
              />
            </label>
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              {webSearchUrl
                ? isValidHttpUrl(webSearchUrl)
                  ? t.ucliWebStateUrl(webSearchUrl)
                  : t.ucliWebStateUrlInvalid
                : webDockerOff
                  ? t.ucliWebStateOff
                  : t.ucliWebStateAuto}
              {" · "}
              {webFetchDomains ? t.ucliWebFetchOn : t.ucliWebFetchOff}
            </span>
          </div>
        </>
      )}
      {group === "start" && (
        <>
          <div className="opts" id="settingsUcliLimitsPanel">
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              <b>{t.ucliLimitsLabel}</b> {t.ucliLimitsDesc}
            </span>
            {(
              [
                ["max_steps", t.ucliLimitsMaxStepsLabel],
                ["max_context_kib", t.ucliLimitsMaxContextKibLabel],
                ["max_tool_calls", t.ucliLimitsMaxToolCallsLabel],
                ["max_output_tokens", t.ucliLimitsMaxOutputTokensLabel],
                ["request_timeout_secs", t.ucliLimitsRequestTimeoutLabel],
              ] as const
            ).map(([field, label]) => (
              <label key={field}>
                {label}
                <input
                  type="number"
                  min={1}
                  placeholder={t.ucliLimitsPlaceholderAuto}
                  value={ucliLimitsDraft[field] ?? settings.ucli_limits[field] ?? ""}
                  onChange={(e) => setUcliLimitsDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                  onBlur={(e) => void save({ ucli_limits: { [field]: e.target.value.trim() } })}
                />
              </label>
            ))}
            <label title={t.ucliLimitsReasoningHint}>
              {t.ucliLimitsReasoningLabel}
              <select
                value={settings.ucli_limits.reasoning_effort ?? ""}
                onChange={(e) => void save({ ucli_limits: { reasoning_effort: e.target.value } })}
              >
                <option value="">{t.ucliLimitsReasoningAuto}</option>
                <option value="off">{t.ucliLimitsReasoningOff}</option>
                {["low", "medium", "high", "max"].map((lvl) => (
                  <option key={lvl} value={lvl}>
                    {lvl}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.ucliLimitsStreamLabel}
              <select
                value={streamOff ? "off" : ""}
                onChange={(e) => void save({ ucli_limits: { stream: e.target.value } })}
              >
                <option value="">{t.ucliLimitsStreamOn}</option>
                <option value="off">{t.ucliLimitsStreamOff}</option>
              </select>
            </label>
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              {t.ucliLimitsStreamHint}
            </span>
          </div>
          <div className="opts" id="settingsUcliScriptPanel">
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              <b>{t.ucliScriptLabel}</b> {t.ucliScriptDesc}
            </span>
            <label>
              {t.ucliScriptModeLabel}
              <select value={scriptMode} onChange={(e) => void save({ ucli_script: { mode: e.target.value } })}>
                <option value="">{t.ucliScriptOff}</option>
                <option value="read">{t.ucliScriptRead}</option>
                <option value="full">{t.ucliScriptFull}</option>
              </select>
            </label>
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              {t.ucliScriptModeHint}
            </span>
          </div>
        </>
      )}
    </>
  );
}
