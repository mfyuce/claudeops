/**
 * Değnekçi "Kota bekçisi" bloğu (TBD#116): mod (off/manual/auto), eşikler (manual/shutdown/final, yoklama dk), son okuma + karar.
 * Makine geneli (kimlik seçmez); okuma `GET /api/steward/quota`, yazma `POST /api/steward/quota` (yalnız insan). Kendi zamanlayıcısı
 * YOK: açılışta ve her kayıttan sonra bir kez okur.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { NumberSetting } from "./shared/NumberSetting";
import { showToast } from "../state/toast";

interface QuotaState {
  at?: number;
  usage?: { week_pct?: number };
  decision?: { action?: string; cap?: number; reason?: string };
  stopped?: boolean;
}
interface QuotaResult {
  ok: boolean;
  error?: string;
  config?: Record<string, string | undefined>;
  modes?: string[];
  state?: QuotaState | null;
}

const NUM_KEYS: { key: string; tr: string; en: string; fallback: number }[] = [
  { key: "manual_limit", tr: "manual (drain) %", en: "manual (drain) %", fallback: 0 },
  { key: "shutdown_limit", tr: "kapatma %", en: "shutdown %", fallback: 0 },
  { key: "final_limit", tr: "final (hard) %", en: "final (hard) %", fallback: 0 },
  { key: "poll_minutes", tr: "yoklama dk", en: "poll min", fallback: 0 },
];

export function StewardQuota() {
  const { lang, t } = useLang();
  const tr = lang === "tr";
  const [data, setData] = useState<QuotaResult | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await apiGet<QuotaResult>("/api/steward/quota");
      if (r.ok) {
        setData(r);
        setError("");
      } else setError(r.error || "error");
    } catch (e) {
      setError(describeApiError(e, t));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(key: string, value: string | number) {
    try {
      const r = await apiPost<{ ok: boolean; error?: string }>("/api/steward/quota", { key, value });
      if (!r.ok) showToast(r.error || "error");
      else showToast(tr ? "Kaydedildi" : "Saved", "success");
    } catch (e) {
      showToast(describeApiError(e, t));
    }
    await load();
  }

  const cfg = data?.config || {};
  const st = data?.state;
  const mode = cfg.mode || "off";
  const when = st?.at ? new Date(st.at * 1000).toLocaleString() : "";
  return (
    <details>
      <summary className="legend" style={{ cursor: "pointer", margin: 0 }}>{tr ? "Kota bekçisi" : "Quota guard"}</summary>
      <div className="opts" style={{ marginTop: ".4rem" }}>
        {error && <span className="opts-hint">{error}</span>}
        <label className="opts-hint" style={{ display: "inline-flex", gap: ".3rem", alignItems: "center" }}>
          {tr ? "mod" : "mode"}
          <select value={mode} onChange={(e) => void save("mode", e.target.value)}>
            {(data?.modes || ["off", "manual", "auto"]).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>
        {NUM_KEYS.map((f) => (
          <NumberSetting
            key={f.key}
            label={tr ? f.tr : f.en}
            value={Number(cfg[f.key] ?? f.fallback)}
            onSave={(n) => void save(f.key, n)}
          />
        ))}
      </div>
      <div className="opts-hint" style={{ marginTop: ".3rem" }}>
        {st
          ? `${tr ? "Son okuma" : "Last read"}: ${when} · ${tr ? "kullanılan" : "used"} %${st.usage?.week_pct ?? "?"} · ` +
            `${tr ? "karar" : "decision"}: ${st.decision?.action ?? "?"}${st.decision?.cap != null ? ` (${tr ? "tavan" : "cap"} ${st.decision.cap})` : ""}` +
            `${st.decision?.reason ? ` ${st.decision.reason}` : ""}${st.stopped ? (tr ? " · DURDURULDU" : " · STOPPED") : ""}`
          : tr ? "Henüz okuma yok (servis okuyunca görünür)." : "No reading yet."}
      </div>
    </details>
  );
}
