/**
 * Değnekçi beyni için model + effort ayarı (yalnız insan; `POST /api/steward/config` brain_model / brain_effort).
 * Kaydetmek ÇALIŞAN beyni yeniden açmaz: sonraki açılış/devir yeni değeri kullanır. Boş değer = otomatik (varsayılan).
 */
import { useEffect, useState } from "react";
import { apiStewardConfig } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { showToast } from "../state/toast";

const EFFORTS = ["", "low", "medium", "high", "xhigh", "max"];

export function StewardBrainModel({ sid, model, effort, onSaved }: { sid: string; model: string; effort: string; onSaved: () => void }) {
  const { lang, t } = useLang();
  const tr = lang === "tr";
  const [m, setM] = useState(model);
  const [e, setE] = useState(effort);
  const [busy, setBusy] = useState(false);
  useEffect(() => setM(model), [model]);
  useEffect(() => setE(effort), [effort]);
  const dirty = m.trim() !== model || e !== effort;

  async function save() {
    setBusy(true);
    try {
      for (const [key, value, old] of [["brain_model", m.trim(), model], ["brain_effort", e, effort]] as const) {
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
