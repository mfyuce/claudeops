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
 *
 * 2026-09-17: "general" split further into "general"/"models"/"fleet" (user:
 * "settingsve diagnostics i tablara veya parcalara bolelim" — one panel had
 * grown to 7 unrelated topics: theme/handover-effort/history-warn/layout-
 * grid, default-model/provider-bin (per CLI), and Fleet Snapshot/Hosts).
 * `error` moved above the sub-tab switch (was inline right before
 * `<SnapshotSection />`) since `save()` is shared by controls now split
 * across "general" and "models" - a failure needs to stay visible
 * regardless of which of those two is active when it happens.
 */

import { useState } from "react";
import { apiSaveSettings, apiUsage, ApiError } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import type { FleetSort, Theme, UsageResult } from "../api/types";
import { applyTheme } from "../theme";
import { CliInstallSection } from "./CliInstallSection";
import { HostsSection } from "./HostsSection";
import { SnapshotSection } from "./SnapshotSection";
import { TabHint } from "./shared/TabHint";

type SettingsPatch = {
  theme?: Theme;
  handover_effort?: string;
  fleet_sort?: FleetSort;
  default_model?: Record<string, string>;
  provider_bin?: Record<string, string>;
  history_warn_at?: number;
  layout_grid?: number;
  /** Write-only — `Settings.byok`'un (okuma tarafı) aksine burada GERÇEK
   * değer gönderilir; backend bunu asla aynen geri yansıtmaz (bkz. o alanın
   * yorumu). Boş string bir provider'ın o ENV_VAR'ını temizler. */
  byok?: Record<string, Record<string, string>>;
  /** {max_steps, max_context_kib, max_tool_calls: string} — bkz. `Settings.ucli_limits`.
   * Boş string bir alanı preset varsayılanına döndürür. */
  ucli_limits?: Record<string, string>;
};

/** cli → bugün bilinen TEK en-önemli BYOK env değişkeni. copilot'un aslında
 * 3'ü var (COPILOT_PROVIDER_BASE_URL/_API_KEY/_MODEL, bkz. copilot_provider.py)
 * ama henüz hiçbiri UI'da yok — bu liste sadece şu an gerçekten kullanılan
 * (ucli) için, genelleştirmek ayrı bir iş. */
const BYOK_PRIMARY_ENV: Record<string, string> = { ucli: "UCLI_API_KEY" };

type SettingsSubTab = "general" | "models" | "fleet" | "usage";

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
        : result.reason === "all_sessions_busy"
          ? t.usageAllBusy
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
      <TabHint warn>{t.usageWarning}</TabHint>
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
  // Same draft-until-blur reasoning as `binDraft` — typing "1900" digit by
  // digit shouldn't fire 4 separate saves.
  const [historyWarnDraft, setHistoryWarnDraft] = useState<string | null>(null);
  // BYOK alanları hep BOŞ başlar (`Settings.byok` zaten değeri değil sadece
  // "ayarlı mı" bool'unu taşıyor, geri-doldurulacak bir şey yok) — draft
  // SADECE bu oturumda yazılanı tutar, blur'da gönderilip hemen temizlenir.
  const [byokDraft, setByokDraft] = useState<Record<string, string>>({});
  // Same draft-until-blur reasoning as `binDraft` — `provider_bin`'in aksine
  // (`isSet`/mask yok) mevcut değer doğrudan gösterilir, BYOK'un "boşsa
  // dokunma" korumasına gerek yok (sır değil).
  const [ucliLimitsDraft, setUcliLimitsDraft] = useState<Record<string, string>>({});

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
      <TabHint warn>{t.settingsSingleUserWarning}</TabHint>
      <div className="tabs">
        <button type="button" className={subTab === "general" ? "active" : ""} onClick={() => setSubTab("general")}>
          {t.tabSettingsGeneral}
        </button>
        <button type="button" className={subTab === "models" ? "active" : ""} onClick={() => setSubTab("models")}>
          {t.tabSettingsModels}
        </button>
        <button type="button" className={subTab === "fleet" ? "active" : ""} onClick={() => setSubTab("fleet")}>
          {t.tabSettingsFleet}
        </button>
        <button type="button" className={subTab === "usage" ? "active" : ""} onClick={() => setSubTab("usage")}>
          {t.tabSettingsUsage}
        </button>
      </div>
      {error && <pre className="layout-result">✗ {error}</pre>}
      {subTab === "usage" && <UsagePanel />}
      {subTab === "general" && (
        <div className="opts" id="settingsPanel">
          <TabHint>{t.settingsDesc}</TabHint>
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
          <label title={t.historyWarnHint}>
            {t.historyWarnLabel}
            <input
              type="number"
              min={1}
              value={historyWarnDraft ?? String(settings.history_warn_at)}
              onChange={(e) => setHistoryWarnDraft(e.target.value)}
              onBlur={(e) => {
                const n = Number.parseInt(e.target.value, 10);
                setHistoryWarnDraft(null);
                if (Number.isFinite(n) && n > 0) void save({ history_warn_at: n });
              }}
            />
          </label>
          <label title={t.layoutGridHint}>
            {t.layoutGridLabel}
            <select
              value={settings.layout_grid}
              onChange={(e) => void save({ layout_grid: Number(e.target.value) })}
            >
              <option value={2}>2 (2×1)</option>
              <option value={4}>4 (2×2)</option>
              <option value={8}>8 (4×2)</option>
            </select>
          </label>
          <label title={t.fleetSortHint}>
            {t.fleetSortLabel}
            <select
              value={settings.fleet_sort}
              onChange={(e) => void save({ fleet_sort: e.target.value as FleetSort })}
            >
              <option value="name">{t.fleetSortByName}</option>
              <option value="cwd">{t.fleetSortByCwd}</option>
            </select>
          </label>
        </div>
      )}
      {subTab === "models" && (
        <>
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
          <CliInstallSection />
          <div className="opts" id="settingsByokPanel">
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              <b>{t.byokLabel}</b> {t.byokDesc}
            </span>
            {data.cli_list
              .filter((cli) => BYOK_PRIMARY_ENV[cli])
              .map((cli) => {
                const envName = BYOK_PRIMARY_ENV[cli];
                const isSet = settings.byok[cli]?.[envName] === true;
                return (
                  <label key={cli}>
                    {cli} ({envName})
                    <input
                      type="password"
                      autoComplete="off"
                      placeholder={isSet ? t.byokSetPlaceholder : t.byokEmptyPlaceholder}
                      value={byokDraft[cli] ?? ""}
                      onChange={(e) => setByokDraft((prev) => ({ ...prev, [cli]: e.target.value }))}
                      onBlur={(e) => {
                        const v = e.target.value;
                        // Boş bırakıp başka yere tıklamak "temizle" DEĞİL —
                        // hiç yazılmadıysa dokunma (yanlışlıkla var olan bir
                        // anahtarı silmemek için); temizlemek isteyen "temizle"
                        // butonunu kullanır (aşağıda).
                        if (!v) return;
                        void save({ byok: { [cli]: { [envName]: v } } });
                        setByokDraft((prev) => ({ ...prev, [cli]: "" }));
                      }}
                    />
                    {isSet && (
                      <button
                        type="button"
                        className="stop"
                        onClick={() => void save({ byok: { [cli]: { [envName]: "" } } })}
                      >
                        {t.byokClearBtn}
                      </button>
                    )}
                  </label>
                );
              })}
          </div>
          {data.cli_list.includes("ucli") && (
            <div className="opts" id="settingsUcliLimitsPanel">
              <span className="opts-hint" style={{ flexBasis: "100%" }}>
                <b>{t.ucliLimitsLabel}</b> {t.ucliLimitsDesc}
              </span>
              {(
                [
                  ["max_steps", t.ucliLimitsMaxStepsLabel],
                  ["max_context_kib", t.ucliLimitsMaxContextKibLabel],
                  ["max_tool_calls", t.ucliLimitsMaxToolCallsLabel],
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
            </div>
          )}
        </>
      )}
      {subTab === "fleet" && (
        <>
          <SnapshotSection />
          <HostsSection />
        </>
      )}
    </>
  );
}
