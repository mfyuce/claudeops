/**
 * "Okuma listesi" tab (claudeops-enterprise `cops reader`): the owner's open reading items (project TOBEDECIDED "SAHİP/YAZAR OKUMASI"
 * lines + weekend reading pack). Data/endpoints belong to the extension (`/readlist/api/*`); the core only renders them, and only
 * when the extension registered `/readlist/` (TabBar). Links open in a NEW tab (`target=_blank rel=noopener`): the first token-auth
 * response sets the extension session cookie, so the reader/file requests of the new tab are authorised without the token in the URL.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { describeApiError } from "../api/errors";
import { ErrorBox } from "./shared/ErrorBox";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";

interface ReadItem {
  id: string;
  project: string;
  source: string;
  path: string;
  title: string;
  kind: string;
  reader_url: string;
  tts_url: string;
  file_url: string;
  read: boolean;
  note?: string;
}
interface ReadList { ok: boolean; items: ReadItem[]; reader: boolean }

const HIDE_KEY = "cops_readlist_hide";

function Card({ it, readerOn, onRead }: { it: ReadItem; readerOn: boolean; onRead: () => void }) {
  const { t } = useLang();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await apiPost("/readlist/api/read", { id: it.id, note });
      onRead();
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
    }
  };
  const open = readerOn && !!it.reader_url;
  return (
    <div className="card" style={{ opacity: it.read ? 0.6 : 1, margin: "10px 0", padding: 12 }}>
      <div style={{ fontSize: 12, textTransform: "uppercase", opacity: 0.7 }}>{it.project || t.readlistNoProject}</div>
      <div style={{ overflowWrap: "anywhere" }}>{it.title}</div>
      <div style={{ fontFamily: "monospace", fontSize: 12, opacity: 0.7, overflowWrap: "anywhere" }}>{it.path}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
        {open && (
          <a className="btn" href={it.reader_url} target="_blank" rel="noopener noreferrer">{t.readlistOpen}</a>
        )}
        {open && (
          <a className="btn" href={it.tts_url} target="_blank" rel="noopener noreferrer">{t.readlistListen}</a>
        )}
        <a className="btn" href={it.file_url} target="_blank" rel="noopener noreferrer">{t.readlistRaw}</a>
      </div>
      {it.read ? (
        <div style={{ marginTop: 6, opacity: 0.8 }}>{t.readlistRead}{it.note ? `: ${it.note}` : ""}</div>
      ) : (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t.readlistNote}
            aria-label={t.readlistNote}
            style={{ width: "100%", minHeight: 60 }}
          />
          <button type="button" disabled={busy} onClick={() => void submit()}>{t.readlistMarkRead}</button>
        </div>
      )}
    </div>
  );
}

export function ReadlistTab() {
  const { t } = useLang();
  const [data, setData] = useState<ReadList | null>(null);
  const [error, setError] = useState("");
  const [hideRead, setHideRead] = useState(() => {
    try { return localStorage.getItem(HIDE_KEY) === "1"; } catch { return false; }
  });
  const [tick, setTick] = useState(0);
  const load = useCallback(() => setTick((n) => n + 1), []);
  useEffect(() => {
    let alive = true;
    apiGet<ReadList>("/readlist/api/list")
      .then((d) => { if (alive) { setData(d); setError(""); } })
      .catch((e) => { if (alive) setError(describeApiError(e, t)); });
    return () => { alive = false; };
  }, [tick, t]);
  const toggleHide = () => {
    const next = !hideRead;
    setHideRead(next);
    try { localStorage.setItem(HIDE_KEY, next ? "1" : "0"); } catch { /* ignore */ }
  };
  const items = data?.items ?? [];
  const shown = hideRead ? items.filter((i) => !i.read) : items;
  const unread = items.filter((i) => !i.read).length;
  return (
    <div>
      <h2>{t.readlistTitle}</h2>
      <div style={{ opacity: 0.7, marginBottom: 8 }}>
        {data ? t.readlistUnread(unread, items.length) : ""}
        {data && !data.reader ? ` · ${t.readlistReaderOff}` : ""}
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <button type="button" onClick={toggleHide}>{hideRead ? t.readlistShowRead : t.readlistHideRead}</button>
        <button type="button" onClick={load}>{t.readlistRefresh}</button>
      </div>
      {error && <ErrorBox text={error} />}
      {data && shown.length === 0 && <p style={{ opacity: 0.7 }}>{t.readlistEmpty}</p>}
      {shown.map((it) => (
        <Card key={it.id} it={it} readerOn={!!data?.reader} onRead={load} />
      ))}
    </div>
  );
}
