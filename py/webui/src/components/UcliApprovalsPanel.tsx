/**
 * ucli kalıcı onaylar (docs/ucli-approval-design.md S4): `suspended` koşuların bekleyen `pending/*.json` kartları.
 * GET /api/ucli/approvals 5 sn'de bir; düğmeler POST {run_key, id, decision}. Düzenle = edited_arguments JSON alanı.
 * Süresi dolanlar soluk ve düğmesiz. Bekleyen yoksa hiçbir şey çizilmez.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";

interface Pending { id: string; kind: string; tool: string; summary: string; expires_at?: number; expired: boolean }
interface Run { run_key: string; session?: string; state: string; pending?: Pending[] }

export function UcliApprovalsPanel() {
  const { lang } = useLang();
  const tr = lang === "tr";
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<string>("");
  const [json, setJson] = useState("{}");
  const [note, setNote] = useState("");

  const poll = useCallback(async () => {
    try {
      const r = await apiGet<{ ok: boolean; runs: Run[] }>("/api/ucli/approvals");
      setRuns(r.ok ? r.runs : []);
    } catch {
      /* geçici hata: sonraki yoklamada */
    }
  }, []);

  useEffect(() => {
    void poll();
    const h = window.setInterval(() => void poll(), 5000);
    return () => window.clearInterval(h);
  }, [poll]);

  const cards = runs.filter((r) => r.state === "suspended").flatMap((r) => (r.pending || []).map((p) => ({ r, p })));
  if (cards.length === 0) return null;

  const send = async (run_key: string, id: string, decision: string, edited?: object) => {
    const key = run_key + "/" + id;
    if (busy) return;
    setBusy(key);
    try {
      await apiPost("/api/ucli/approvals", { run_key, id, decision, ...(edited ? { edited_arguments: edited } : {}), ...(note.trim() ? { note: note.trim() } : {}) });
      setEditing("");
      setNote("");
      void poll();
    } catch {
      showToast(tr ? "onay gönderilemedi (bayat ya da süresi dolmuş olabilir)" : "approval not sent (stale or expired?)");
      void poll();
    } finally {
      setBusy("");
    }
  };

  const submitEdit = (run_key: string, id: string) => {
    let obj: unknown;
    try { obj = JSON.parse(json); } catch { showToast(tr ? "geçersiz JSON" : "invalid JSON"); return; }
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) { showToast(tr ? "JSON nesne olmalı" : "JSON must be an object"); return; }
    void send(run_key, id, "edit", obj as object);
  };

  return (
    <section className="ucli-approvals" style={{ marginBottom: 10 }}>
      <h3>{tr ? "Bekleyen onaylar" : "Pending approvals"} <span className="cli-badge">{cards.length}</span></h3>
      {cards.map(({ r, p }) => {
        const key = r.run_key + "/" + p.id;
        return (
          <div key={key} style={{ margin: "6px 0", padding: 6, border: "1px solid currentColor", borderRadius: 4, opacity: p.expired ? 0.5 : 1 }}>
            <div>
              <b>{r.session || r.run_key}</b> · {p.kind === "check" && <span className="cli-badge">{tr ? "kontrol" : "check"}</span>} {p.tool || p.kind}
              {p.expired && <span className="cli-badge" style={{ marginLeft: 6 }}>{tr ? "süresi doldu" : "expired"}</span>}
            </div>
            <div style={{ whiteSpace: "pre-wrap", margin: "4px 0" }}>{p.summary}</div>
            {!p.expired && (
              <>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 4 }}>
                  <button type="button" disabled={!!busy} onClick={() => void send(r.run_key, p.id, "approve")}>{tr ? "Onayla" : "Approve"}</button>
                  <button type="button" disabled={!!busy} onClick={() => void send(r.run_key, p.id, "approve_session")}>{tr ? "Bu oturum için onayla" : "Approve for session"}</button>
                  <button type="button" disabled={!!busy} onClick={() => void send(r.run_key, p.id, "reject")}>{tr ? "Reddet" : "Reject"}</button>
                  <button type="button" disabled={!!busy} onClick={() => setEditing(editing === key ? "" : key)}>{tr ? "Düzenle" : "Edit"}</button>
                </div>
                {editing === key && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <textarea rows={4} value={json} style={{ width: "100%", boxSizing: "border-box", fontFamily: "monospace" }}
                      onChange={(e) => setJson(e.target.value)} placeholder={tr ? "düzenlenmiş araç argümanları (JSON)" : "edited tool arguments (JSON)"} />
                    <button type="button" disabled={!!busy} onClick={() => submitEdit(r.run_key, p.id)}>{tr ? "Düzenlenmişi gönder" : "Send edited"}</button>
                  </div>
                )}
                <input type="text" value={note} style={{ width: "100%", boxSizing: "border-box", marginTop: 4 }}
                  placeholder={tr ? "not (isteğe bağlı)" : "note (optional)"} onChange={(e) => setNote(e.target.value)} />
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}
