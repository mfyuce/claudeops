/**
 * Değnekçi "kullanım kontrolü kipi" (TBD#203): `tek` (varsayılan, yalnız panelde "Kullanımı kontrol et" basılınca) ya da
 * `tick` (değnekçi her tick'te oturumsuz okunabilenleri okur: claude, API anahtarlı sağlayıcılar; agy/copilot gibi açık oturuma
 * `/usage` yazdıranlar en fazla 30 dk'da bir). Makine geneli ayar `usage_mode` (settings.json).
 */
import { useState } from "react";
import { apiSaveSettings } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";
import { useStatusContext } from "../state/StatusContext";
import { showToast } from "../state/toast";

export function StewardUsageMode() {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [busy, setBusy] = useState(false);
  const raw = String((data?.settings as { usage_mode?: string } | undefined)?.usage_mode ?? "tek").trim().toLowerCase();
  const value = raw === "tick" ? "tick" : "tek";
  const tr = lang === "tr";

  async function save(next: string) {
    setBusy(true);
    try {
      const res = await apiSaveSettings({ lang, usage_mode: next } as Parameters<typeof apiSaveSettings>[0]);
      if (!res.ok) showToast(res.error);
      refresh();
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="opts" style={{ width: "100%", boxSizing: "border-box", marginTop: ".5rem" }}>
      <label
        title={
          tr
            ? "tek: kullanım yalnız Ayarlar > Kullanım'da 'Kullanımı kontrol et' basılınca okunur. tick: değnekçi her tick'te claude ve API anahtarlı sağlayıcıları okur; agy/copilot (açık oturuma /usage yazdırır) en fazla 30 dakikada bir."
            : "tek: usage is read only when you press 'Check usage' in Settings > Usage. tick: the steward reads claude and API-key providers every tick; agy/copilot (they type /usage into an open session) at most every 30 minutes."
        }
      >
        {tr ? "kullanım kontrolü kipi" : "usage check mode"}{" "}
        <select value={value} disabled={busy} onChange={(e) => void save(e.target.value)}>
          <option value="tek">{tr ? "tek (yalnız istenince)" : "tek (on demand only)"}</option>
          <option value="tick">{tr ? "tick (değnekçi okur)" : "tick (steward reads)"}</option>
        </select>
      </label>
    </div>
  );
}
