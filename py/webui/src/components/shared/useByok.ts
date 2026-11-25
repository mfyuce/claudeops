/**
 * BYOK anahtarlarının seçili makinedeki durumu + tek alan yazımı. Yerel: durum yoklamasındaki bool'lar + `/api/settings`.
 * Uzak: yalnız dar uç `/api/settings/byok` (ayar blobunun tamamı uzağa yazılmaz). `byok === null` = durum henüz bilinmiyor.
 */
import { useEffect, useState } from "react";
import { apiByok, apiSaveSettings } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { LOCAL_HOST } from "../../state/hosts";

export function useByok(host: string) {
  const { t, lang } = useLang();
  const { data, refresh } = useStatusContext();
  const [remote, setRemote] = useState<{ host: string; byok: Record<string, Record<string, boolean>> | null; error: string }>({
    host: LOCAL_HOST,
    byok: null,
    error: "",
  });
  const [localError, setLocalError] = useState("");
  const local = host === LOCAL_HOST;

  /** Eski sürümdeki host yolu tanımaz (404): "host güncel değil" diye söyle. */
  const explain = (e: unknown) => {
    const msg = describeApiError(e, t);
    return /not found|404/i.test(msg) ? `${msg} (${t.hostOutdated})` : msg;
  };

  useEffect(() => {
    if (local) return;
    let alive = true;
    setRemote({ host, byok: null, error: "" });
    apiByok({ host, lang })
      .then((res) => {
        if (alive) setRemote({ host, byok: res.ok ? res.byok : null, error: res.ok ? "" : res.error });
      })
      .catch((e) => {
        if (alive) setRemote({ host, byok: null, error: explain(e) });
      });
    return () => {
      alive = false;
    };
    // explain yalnız `t`ye bağlı: dil değişimi `lang` ile zaten yeniden okur
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host, lang, local]);

  async function setKey(cli: string, env: string, value: string) {
    setLocalError("");
    try {
      if (local) {
        const res = await apiSaveSettings({ byok: { [cli]: { [env]: value } }, lang });
        if (!res.ok) setLocalError(res.error);
        refresh();
        return;
      }
      const res = await apiByok({ host, cli, env, value, lang });
      setRemote((cur) => (cur.host !== host ? cur : res.ok ? { host, byok: res.byok, error: "" } : { ...cur, error: res.error }));
    } catch (e) {
      if (local) setLocalError(explain(e));
      else setRemote((cur) => (cur.host === host ? { ...cur, error: explain(e) } : cur));
    }
  }

  const current = !local && remote.host === host;
  return {
    byok: local ? (data?.settings.byok ?? {}) : current ? remote.byok : null,
    error: local ? localError : current ? remote.error : "",
    setKey,
  };
}
