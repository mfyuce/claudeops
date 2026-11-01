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
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";

/** id, label, the env var `ucli --api-key-env` reads, the wire protocol and typical endpoint (hint only, not enforced). */
const KEY_SERVICES = [
  { id: "evren", label: "Evren", env: "UCLI_API_KEY", hint: "chat-completions · endpoint: ucli_endpoint" },
  { id: "claude", label: "Claude (Anthropic)", env: "ANTHROPIC_API_KEY", hint: "anthropic-messages · https://api.anthropic.com" },
  { id: "grok", label: "Grok (xAI)", env: "XAI_API_KEY", hint: "chat-completions · https://api.x.ai/v1" },
  { id: "openrouter", label: "OpenRouter", env: "OPENROUTER_API_KEY", hint: "chat-completions · https://openrouter.ai/api/v1" },
  { id: "groq", label: "Groq", env: "GROQ_API_KEY", hint: "chat-completions · https://api.groq.com/openai/v1" },
] as const;

export function UcliKeysPanel() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  if (!data) return null;
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

  return (
    <div className="opts" id="ucliKeysPanel">
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{t.ucliKeysTitle}</b> {t.ucliKeysDesc}
      </span>
      {KEY_SERVICES.map((s) => {
        const isSet = byok[s.env] === true;
        return (
          <label key={s.id} title={s.hint}>
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
            <span className="opts-hint">{s.hint}</span>
          </label>
        );
      })}
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
