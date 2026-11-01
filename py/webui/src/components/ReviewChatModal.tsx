/**
 * Read-only chat view of one review run (History): the persisted `.io.jsonl` converted server-side to chat
 * messages (user prompt, assistant text, folded tool/system rows). Polls every 3 s ONLY while the modal is open
 * AND the run is still running; auto-scrolls to the bottom while following.
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getReviewChat, getReviewIo } from "../api/client";
import { describeApiError } from "../api/errors";
import type { ChatMessage, ReviewIoEvent, ReviewRun } from "../api/types";
import { useLang } from "../i18n/LangContext";
import { ChatMessageList } from "./TerminalModal/ChatView";
import { useBodyScrollLock } from "./shared/useBodyScrollLock";
import { useEscapeKey } from "./shared/useEscapeKey";

const POLL_MS = 3000;

export function ReviewChatModal({ run, onClose }: { run: ReviewRun; onClose: () => void }) {
  const { t } = useLang();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [running, setRunning] = useState(run.running);
  const [status, setStatus] = useState(run.status);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"chat" | "raw">("chat");
  const [raw, setRaw] = useState<ReviewIoEvent[]>([]);
  const offRef = useRef(0);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const followRef = useRef(true);
  useBodyScrollLock();
  useEscapeKey(onClose);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      let again = true;
      try {
        const r = await getReviewChat(run.sid, run.io);
        if (cancelled) return;
        if (!r.ok) {
          setError(r.error || t.requestFailed);
        } else {
          setError("");
          setMessages(r.messages ?? []);
          setRunning(!!r.running);
          if (r.status) setStatus(r.status);
          again = !!r.running;
        }
      } catch (e) {
        if (cancelled) return;
        setError(describeApiError(e, t));
      }
      if (!cancelled && again) timer = setTimeout(() => void tick(), POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [run.sid, run.io, t]);

  // Ham akış: `.io.jsonl` olayları, bayt ofsetiyle artımlı; yalnız sekme açıkken ve koşu sürerken yoklanır.
  useEffect(() => {
    if (tab !== "raw") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      let again = true;
      try {
        const r = await getReviewIo(run.sid, run.io, offRef.current);
        if (cancelled) return;
        if (!r.ok) setError(r.error || t.requestFailed);
        else {
          setError("");
          offRef.current = r.offset ?? offRef.current;
          setRaw((prev) => (r.reset ? [] : prev).concat(r.events ?? []).slice(-2000));
          again = running;
        }
      } catch (e) {
        if (cancelled) return;
        setError(describeApiError(e, t));
      }
      if (!cancelled && again) timer = setTimeout(() => void tick(), POLL_MS);
    };
    offRef.current = 0;
    setRaw([]);
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [tab, run.sid, run.io, running, t]);

  useEffect(() => {
    const el = boxRef.current;
    if (el && followRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, raw, tab]);

  const overlay = (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.75)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div style={{ width: "min(720px, 95vw)", maxHeight: "92dvh", background: "var(--panel)", borderRadius: 8, display: "flex", flexDirection: "column", padding: ".7rem", boxSizing: "border-box" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: ".5rem", marginBottom: ".4rem" }}>
          <strong style={{ overflowWrap: "anywhere" }}>
            <span className="cli-badge">{t.hReviewBadge}</span> {run.title}
          </strong>
          <button type="button" style={{ fontSize: "1rem", lineHeight: 1, padding: ".2rem .55rem" }} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="opts-hint" style={{ marginBottom: ".4rem" }}>
          {status}
          {running ? " …" : ""} · {t.hReviewHint}
        </div>
        <div className="opts" style={{ marginBottom: ".4rem" }}>
          <button type="button" className={tab === "chat" ? "go" : ""} onClick={() => setTab("chat")}>{t.rvTabChat}</button>
          <button type="button" className={tab === "raw" ? "go" : ""} onClick={() => setTab("raw")}>{t.rvTabRaw}</button>
        </div>
        {error && <div className="warn-banner">{error}</div>}
        <div
          ref={boxRef}
          style={{ overflow: "auto", maxHeight: "calc(92dvh - 120px)" }}
          onScroll={(e) => {
            const el = e.currentTarget;
            followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
        >
          {tab === "chat" ? (
            <ChatMessageList messages={messages} t={t} />
          ) : (
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", margin: 0, fontSize: ".78rem" }}>
              {raw.map((e) => `[${e.role ?? "?"}${e.kind ? "/" + e.kind : ""}] ${e.text ?? ""}`).join("\n")}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
  return createPortal(overlay, document.body);
}
