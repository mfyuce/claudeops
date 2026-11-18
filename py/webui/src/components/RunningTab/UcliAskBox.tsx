/**
 * ucli `ask_dir` oturumunun bekleyen sorusu/onayı (POST /api/ucli/ask) ve cevap kutusu. Yalnız `ucli_flags.ask` olan
 * satırda bağlanır (yoklama başka oturumları yormaz). Seçenek varsa düğme, her zaman serbest metin.
 */
import { useCallback, useEffect, useState } from "react";
import { apiPost } from "../../api/client";
import { showToast } from "../../state/toast";
import { useLang } from "../../i18n/LangContext";

interface Q { id: number; header: string; question: string; options: string[] }

export function UcliAskBox({ name }: { name: string }) {
  const { lang } = useLang();
  const tr = lang === "tr";
  const [q, setQ] = useState<Q | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const poll = useCallback(async () => {
    try {
      const r = await apiPost<{ ok: boolean; question: Q | null }>("/api/ucli/ask", { name });
      setQ(r.ok ? r.question : null);
    } catch {
      /* geçici hata: bir sonraki yoklamada tekrar */
    }
  }, [name]);

  useEffect(() => {
    void poll();
    const h = window.setInterval(() => void poll(), 4000);
    return () => window.clearInterval(h);
  }, [poll]);

  if (!q) return null;

  const send = async (answer: string) => {
    if (busy || !answer.trim()) return;
    setBusy(true);
    try {
      await apiPost("/api/ucli/ask", { name, id: q.id, text: answer });
      setText("");
      setQ(null);
    } catch (e) {
      showToast(`${name}: ${tr ? "cevap gönderilemedi (soru değişmiş olabilir)" : "answer not sent (the question may have changed)"}`);
      void poll();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ucli-ask" style={{ marginTop: 6, padding: 6, border: "1px solid currentColor", borderRadius: 4 }}>
      <div><span className="cli-badge">{tr ? "soru bekliyor" : "waiting for answer"}</span> {q.header && <b>{q.header}</b>}</div>
      <div style={{ whiteSpace: "pre-wrap", margin: "4px 0" }}>{q.question}</div>
      {q.options.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 4 }}>
          {q.options.map((o) => (
            <button key={o} type="button" disabled={busy} onClick={() => void send(o)}>{o}</button>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 4 }}>
        <input
          type="text" value={text} disabled={busy} style={{ flex: 1, minWidth: 0 }}
          placeholder={tr ? "cevap" : "answer"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void send(text); }}
        />
        <button type="button" disabled={busy || !text.trim()} onClick={() => void send(text)}>{tr ? "Gönder" : "Send"}</button>
      </div>
    </div>
  );
}
