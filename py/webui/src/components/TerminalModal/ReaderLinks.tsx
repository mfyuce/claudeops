/**
 * "Reader'da oku" / "Sesli oku" actions for one file (Files view row + file viewer). Only rendered when the extension registered
 * `/reader/` (`ext_routes`) and the file type is readable there. The click opens a NEW tab (popup opened synchronously inside the click so
 * mobile browsers allow it), asks the backend for a short-lived signed READ link (`/api/files/ticket`: no panel token in any URL; remote-host
 * files go through the files proxy) and points the tab at `/reader/?fs=1&file-url=|text-url=<link>[&mode=tts]`.
 */
import { useState } from "react";
import { apiFilesTicket } from "../../api/client";
import { describeApiError } from "../../api/errors";
import { showToast } from "../../state/toast";
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { readerKind } from "./fileViewerKind";

export function readerUrl(kind: "file-url" | "text-url", ticketUrl: string, tts: boolean): string {
  return `/reader/?fs=1&${kind}=${encodeURIComponent(ticketUrl)}${tts ? "&mode=tts" : ""}`;
}

export function ReaderLinks({ name, host, path }: { name: string; host: string; path: string }) {
  const { t, lang } = useLang();
  const { data } = useStatusContext();
  const [busy, setBusy] = useState(false);
  const filename = path.split("/").pop() ?? path;
  const kind = readerKind(filename);
  if (!kind || !(data?.ext_routes ?? []).includes("/reader/")) return null;
  const open = async (tts: boolean) => {
    const w = window.open("about:blank", "_blank");
    if (w) { try { w.opener = null; } catch { /* cross-origin guard, ignore */ } }
    setBusy(true);
    try {
      const r = await apiFilesTicket(name, lang, path, host);
      const url = readerUrl(kind, r.url, tts);
      if (w) w.location.href = url; else window.location.assign(url);
    } catch (e) {
      if (w) w.close();
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" disabled={busy} title={t.filesReaderRead} style={{ whiteSpace: "nowrap" }} onClick={() => void open(false)}>
        📖
      </button>
      <button type="button" disabled={busy} title={t.filesReaderListen} style={{ whiteSpace: "nowrap" }} onClick={() => void open(true)}>
        🔊
      </button>
    </>
  );
}
