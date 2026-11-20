/**
 * Çalışan ucli oturumunun run_checks modu (satır seçici): `GET /api/ucli/checks-mode?name=` etkin modu + tavanı verir;
 * `POST /api/ucli/checks-mode {name, mode, confirm?}` mod dosyasını yazar. Daraltma onaysız, GENİŞLETME açık onay penceresi ister
 * (sahip kararı TBD#260 2a: genişletme yalnız panelden), tavanı aşan seçenek sunulmaz (sunucu da 409 döner).
 * Yalnız `ucli_flags.checks` olan yerel satırda bağlanır.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { showToast } from "../../state/toast";
import { useLang } from "../../i18n/LangContext";

const RANK: Record<string, number> = { off: 0, restricted: 1, full: 2 };
interface ModeInfo { ok: boolean; enabled: boolean; mode?: string; max?: string }

export function UcliChecksMode({ name }: { name: string }) {
  const { lang, t } = useLang();
  const tr = lang === "tr";
  const [info, setInfo] = useState<ModeInfo | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<ModeInfo>(`/api/ucli/checks-mode?name=${encodeURIComponent(name)}`));
    } catch {
      /* geçici hata: sonraki yüklemede */
    }
  }, [name]);
  useEffect(() => { void load(); }, [load]);

  if (!info?.enabled) return null;
  const cur = info.mode ?? "off";
  const cap = info.max ?? "restricted";

  async function change(next: string) {
    const widen = RANK[next] > RANK[cur];
    if (widen && !window.confirm(tr
      ? `Kontrol modu ${cur} -> ${next} genişletilsin mi? (full: yorumlayıcı programlar kafeste serbest olur; denetim kaydına yazılır)`
      : `Widen checks mode ${cur} -> ${next}? (full lets interpreter programs run in the cage; audited)`)) {
      return;
    }
    setBusy(true);
    try {
      const r = await apiPost<{ ok: boolean; error?: string }>("/api/ucli/checks-mode", { name, mode: next, ...(widen ? { confirm: true } : {}) });
      if (!r.ok) showToast(r.error || "error");
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      await load();
    }
  }

  return (
    <label className="cli-badge" title={tr ? "run_checks modu (daraltma anında, genişletme onaylı; tavan " + cap + ")" : "run_checks mode (narrow instantly, widen with confirmation; ceiling " + cap + ")"}>
      {tr ? "kontrol" : "checks"}{" "}
      <select value={cur} disabled={busy} onChange={(e) => void change(e.target.value)}>
        {["off", "restricted", "full"].filter((m) => RANK[m] <= RANK[cap]).map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
    </label>
  );
}
