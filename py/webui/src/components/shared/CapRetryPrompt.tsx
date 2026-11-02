/**
 * "Günlük ucli USD tavanı aşıldı" istemi: ortak bileşen (Kayıtlı, Geçmiş, Çalışanlar, toplu işlem). Sayı alanı
 * (önerilen tavanla dolu) + "tavanı X USD yap ve tekrar dene": `ucli_cost.daily_cap_usd` apiSaveSettings ile yazılır,
 * ardından reddedilen başlatma AYNEN yeniden gönderilir. Durum `state/capRetry.ts`'te; App'te bir kez bağlanır.
 */

import { useEffect, useState } from "react";
import { apiSaveSettings } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { dismissCapRetry, isCapRefusal, subscribeCapRetry, suggestCap, type CapPrompt } from "../../state/capRetry";
import { showToast } from "../../state/toast";

export function CapRetryPrompt() {
  const { t, lang } = useLang();
  const { refresh } = useStatusContext();
  const [prompt, setPrompt] = useState<CapPrompt | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => subscribeCapRetry(setPrompt), []);
  useEffect(() => {
    if (prompt) setValue(String(suggestCap(prompt.todayUsd, prompt.capUsd)));
  }, [prompt?.id, prompt?.todayUsd, prompt?.capUsd]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!prompt) return null;
  const tr = lang === "tr";
  const usd = Number(value.replace(",", "."));
  const valid = Number.isFinite(usd) && usd > 0;

  async function raiseAndRetry(p: CapPrompt) {
    setBusy(true);
    try {
      const saved = await apiSaveSettings({ ucli_cost: { daily_cap_usd: String(usd) }, lang });
      if (!saved.ok) {
        showToast(saved.error);
        return;
      }
      const res = await p.retry();
      if (res.ok) {
        dismissCapRetry();
      } else if (isCapRefusal(res)) {
        // still over the new cap: keep the prompt with the fresh numbers
        setPrompt({ ...p, error: res.error, todayUsd: res.today_usd ?? p.todayUsd, capUsd: res.cap_usd ?? usd });
      } else {
        dismissCapRetry();
        showToast(`${p.name}: ${res.error ?? ""}`);
      }
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  return (
    <div className="cap-retry" role="alertdialog" aria-live="assertive">
      <div className="cap-retry-text">
        <b>{prompt.name}</b>:{" "}
        {tr
          ? `ucli günlük USD tavanı aşıldı (${prompt.todayUsd.toFixed(2)} / ${prompt.capUsd.toFixed(2)}); başlatma reddedildi.`
          : `ucli daily USD cap reached (${prompt.todayUsd.toFixed(2)} / ${prompt.capUsd.toFixed(2)}); start refused.`}
      </div>
      <div className="cap-retry-row">
        <input
          type="number"
          min={0}
          step="any"
          aria-label="ucli_cost.daily_cap_usd"
          value={value}
          disabled={busy}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="button" className="start" disabled={busy || !valid} onClick={() => void raiseAndRetry(prompt)}>
          {busy
            ? t.starting
            : tr
              ? `tavanı ${valid ? usd : "?"} USD yap ve tekrar dene`
              : `set cap to ${valid ? usd : "?"} USD and retry`}
        </button>
        <button type="button" className="stop" disabled={busy} onClick={dismissCapRetry}>
          {tr ? "vazgeç" : "cancel"}
        </button>
      </div>
    </div>
  );
}
