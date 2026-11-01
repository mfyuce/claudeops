/**
 * "Model keys" of the ucli tab (owner, 2026-11-01: ucli's model keys also live in claudeops). One write-only password
 * field per model service. The values go to `settings.json` (mode 0600) under `byok.ucli.<ENV_VAR>` and NEVER come back
 * to the browser: the status payload carries only "is it set" booleans (`web._mask_byok`), so a field starts empty and
 * shows "set" instead of the value. A blur on an empty field does nothing (it must not wipe a key by accident); only the
 * clear button removes one.
 *
 * Scope today: STORAGE and entry. Evren's key (`UCLI_API_KEY`) is also what new ucli sessions already use; the other
 * three are kept ready for session start (endpoint + `--provider` + `--api-key-env` per service is the next step).
 * The reviewer's Anthropic key is still its own file (`anthropic_review_key`), not this field.
 */

import { useState } from "react";
import { apiSaveSettings, ApiError } from "../api/client";
import type { UcliServiceDef } from "../api/types";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

function hintOf(d: UcliServiceDef): string {
  return `${d.wire || "chat-completions"} · ${d.endpoint || "endpoint: ucli_endpoint"}`;
}

export function UcliKeysPanel() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [add, setAdd] = useState({ id: "", label: "", endpoint: "", env: "", anthropic: false });
  if (!data) return null;
  const services = data.settings.ucli_services ?? [];
  const byok = data.settings.byok?.ucli ?? {};
  const cost = data.ucli_cost;

  async function save(env: string, value: string) {
    setError("");
    try {
      const res = await apiSaveSettings({ byok: { ucli: { [env]: value } }, lang });
      if (!res.ok) setError(res.error);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) showToast(t.authErrorShort);
      else setError(describeApiError(e, t));
    }
    setDraft((p) => ({ ...p, [env]: "" }));
    refresh();
  }

  /** The service list lives in settings.json as ONE list: every edit sends the whole thing. */
  async function saveServices(next: UcliServiceDef[]) {
    setError("");
    try {
      const res = await apiSaveSettings({ ucli_services: next, lang });
      if (!res.ok) setError(res.error);
    } catch (e) {
      setError(describeApiError(e, t));
    }
    refresh();
  }
  const patchService = (id: string, p: Partial<UcliServiceDef>) =>
    void saveServices(services.map((d) => (d.id === id ? { ...d, ...p } : d)));

  return (
    <div className="opts" id="ucliKeysPanel">
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.ucliKeysTitle}</b> {t.ucliKeysDesc}
      </span>
      {services.map((s) => {
        const isSet = byok[s.env] === true;
        return (
          <label key={s.id} title={hintOf(s)}>
            {s.label} ({s.env})
            <input
              type="password"
              autoComplete="off"
              placeholder={isSet ? t.byokSetPlaceholder : t.byokEmptyPlaceholder}
              value={draft[s.env] ?? ""}
              onChange={(e) => setDraft((p) => ({ ...p, [s.env]: e.target.value }))}
              onBlur={(e) => {
                if (e.target.value) void save(s.env, e.target.value);
              }}
            />
            {isSet && (
              <button type="button" className="stop" onClick={() => void save(s.env, "")}>
                {t.byokClearBtn}
              </button>
            )}
            <span className="opts-hint">{hintOf(s)}</span>
            <input
              type="text"
              key={s.models.join(",")}
              defaultValue={s.models.join(", ")}
              placeholder={lang === "tr" ? "modeller (virgülle; canlı liste yoksa yedek)" : "models (comma separated; fallback when no live list)"}
              onBlur={(e) => {
                const models = e.target.value.split(",").map((x) => x.trim()).filter(Boolean);
                if (models.join(",") !== s.models.join(",")) patchService(s.id, { models });
              }}
            />
            {s.id !== "evren" && (
              <button type="button" className="stop" onClick={() => void saveServices(services.filter((d) => d.id !== s.id))}>
                {lang === "tr" ? "hizmeti kaldır" : "remove service"}
              </button>
            )}
          </label>
        );
      })}
      <div className="opts" style={{ flexBasis: "100%" }}>
        <span className="opts-hint">{lang === "tr" ? "Hizmet ekle (OpenAI uyumlu uç):" : "Add a service (OpenAI-compatible endpoint):"}</span>
        <input type="text" size={8} placeholder="id (groq2)" value={add.id} onChange={(e) => setAdd({ ...add, id: e.target.value })} />
        <input type="text" size={14} placeholder={lang === "tr" ? "etiket" : "label"} value={add.label} onChange={(e) => setAdd({ ...add, label: e.target.value })} />
        <input type="text" size={26} placeholder="https://host/v1" value={add.endpoint} onChange={(e) => setAdd({ ...add, endpoint: e.target.value })} />
        <input type="text" size={16} placeholder="API_KEY_ENV" value={add.env} onChange={(e) => setAdd({ ...add, env: e.target.value })} />
        <label><input type="checkbox" checked={add.anthropic} onChange={(e) => setAdd({ ...add, anthropic: e.target.checked })} /> anthropic-messages</label>
        <button
          type="button"
          className="start"
          disabled={!add.id.trim() || !add.endpoint.trim() || !add.env.trim()}
          onClick={() => {
            void saveServices([...services, { id: add.id.trim().toLowerCase(), label: add.label.trim(), wire: add.anthropic ? "anthropic-messages" : "", endpoint: add.endpoint.trim(), env: add.env.trim(), models: [] }]);
            setAdd({ id: "", label: "", endpoint: "", env: "", anthropic: false });
          }}
        >
          {lang === "tr" ? "ekle" : "add"}
        </button>
      </div>
      <label title={lang === "tr" ? "0 ya da boş = tavan yok. Aşılınca YENİ Claude oturumu açılmaz, çalışanlara dokunulmaz." : "0 or empty = no cap. Over the cap NEW Claude sessions are refused; running ones are untouched."}>
        {lang === "tr" ? "Claude günlük tavan (USD)" : "Claude daily cap (USD)"}
        <input
          type="number"
          min={0}
          step={1}
          key={cost?.cap_usd ?? 0}
          defaultValue={cost && cost.cap_usd > 0 ? cost.cap_usd : ""}
          placeholder={lang === "tr" ? "tavan yok" : "no cap"}
          onBlur={(e) => {
            void (async () => {
              try {
                const res = await apiSaveSettings({ ucli_cost: { daily_cap_usd: e.target.value }, lang });
                if (!res.ok) setError(res.error);
              } catch (err) {
                setError(describeApiError(err, t));
              }
              refresh();
            })();
          }}
        />
        <span className="opts-hint">
          {lang === "tr" ? "bugün" : "today"}: ${cost ? cost.today_usd.toFixed(2) : "0.00"}
          {cost && cost.pct !== null ? ` (%${cost.pct})` : ""} · {lang === "tr" ? "alt sınır tahmini; önbellek" : "lower-bound estimate; cache"} {cost?.cache_ttl ?? "1h"}
        </span>
      </label>
      {error && <pre className="layout-result">✗ {error}</pre>}
    </div>
  );
}
