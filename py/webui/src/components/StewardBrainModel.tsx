/**
 * Değnekçi beyni için CLI + model + effort ayarı (yalnız insan; `POST /api/steward/config` brain_cli / brain_model / brain_effort,
 * ucli'de ayrıca brain_service (claude = Anthropic API kredisi) ve brain_max_cost_usd (tur başına USD tavanı)).
 * Beyin ucli'deyken kota bekçisi (Claude Code sayacı) tüm değnekçiyi değil yalnız claude CLI projelerini tutar.
 * Kaydetmek ÇALIŞAN beyni yeniden açmaz: sonraki açılış/devir yeni değeri kullanır. Boş değer = otomatik (varsayılan).
 */
import { useEffect, useState } from "react";
import { apiStewardConfig } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { showToast } from "../state/toast";

const EFFORTS = ["", "low", "medium", "high", "xhigh", "max"];

type BrainProps = {
  sid: string; model: string; effort: string; cli?: string; service?: string; maxCost?: string; onSaved: () => void;
};

export function StewardBrainModel({ sid, model, effort, cli = "claude", service = "", maxCost = "", onSaved }: BrainProps) {
  const { lang, t } = useLang();
  const tr = lang === "tr";
  const [m, setM] = useState(model);
  const [e, setE] = useState(effort);
  const [c, setC] = useState(cli || "claude");
  const [sv, setSv] = useState(service);
  const [mc, setMc] = useState(maxCost);
  const [busy, setBusy] = useState(false);
  useEffect(() => setM(model), [model]);
  useEffect(() => setE(effort), [effort]);
  useEffect(() => setC(cli || "claude"), [cli]);
  useEffect(() => setSv(service), [service]);
  useEffect(() => setMc(maxCost), [maxCost]);
  const dirty = m.trim() !== model || e !== effort || c !== (cli || "claude") || sv.trim() !== service || mc.trim() !== maxCost;

  async function save() {
    setBusy(true);
    try {
      const fields: (readonly [string, string, string])[] = [
        ["brain_cli", c, cli || "claude"], ["brain_model", m.trim(), model], ["brain_effort", e, effort],
        ["brain_service", sv.trim(), service], ["brain_max_cost_usd", mc.trim(), maxCost],
      ];
      for (const [key, value, old] of fields) {
        if (value === old) continue;
        const r = await apiStewardConfig(key, value, sid);
        if (!r.ok) {
          showToast(r.error || "error");
          return;
        }
      }
      showToast(tr ? "Kaydedildi; sonraki beyin açılışı/devri kullanır" : "Saved; the next brain start/handover uses it", "success");
      onSaved();
    } catch (err) {
      showToast(describeApiError(err, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="opts" style={{ marginTop: ".4rem" }}>
      <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}
        title={tr ? "ucli: beyin Anthropic API kredisiyle (ya da seçilen hizmetle) çalışır; Claude Code sayacı dolunca yalnız claude projeleri durur." : "ucli: the brain runs on the Anthropic API credit (or the chosen service); when the Claude Code meter is full only claude projects pause."}>
        {tr ? "beyin CLI" : "brain CLI"}
        <select value={c} onChange={(ev) => setC(ev.target.value)}>
          <option value="claude">claude ({tr ? "abonelik" : "subscription"})</option>
          <option value="ucli">ucli (API)</option>
        </select>
      </label>
      {c === "ucli" && (
        <>
          <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}>
            {tr ? "hizmet" : "service"}
            <input value={sv} placeholder="claude" onChange={(ev) => setSv(ev.target.value)} style={{ width: "7rem" }} spellCheck={false} />
          </label>
          <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}
            title={tr ? "Beyin turu başına USD tavanı (0 = yok)." : "USD cap per brain turn (0 = none)."}>
            {tr ? "tur tavanı $" : "turn cap $"}
            <input type="number" min={0} max={50} step={0.5} value={mc} placeholder="1" onChange={(ev) => setMc(ev.target.value)} style={{ width: "5rem" }} />
          </label>
        </>
      )}
      <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}>
        {tr ? "beyin modeli" : "brain model"}
        <input
          value={m}
          placeholder={tr ? "otomatik" : "auto"}
          onChange={(ev) => setM(ev.target.value)}
          style={{ width: "14rem" }}
          spellCheck={false}
        />
      </label>
      <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}>
        effort
        <select value={e} onChange={(ev) => setE(ev.target.value)}>
          {EFFORTS.map((x) => (
            <option key={x} value={x}>{x || (tr ? "otomatik" : "auto")}</option>
          ))}
        </select>
      </label>
      <button type="button" disabled={busy || !dirty} onClick={() => void save()}>{tr ? "Kaydet" : "Save"}</button>
      <span className="opts-hint">
        {tr ? "Çalışan beyni yeniden açmaz; sonraki açılış/devir kullanır." : "Does not reopen the running brain; the next start/handover uses it."}
      </span>
    </div>
  );
}
