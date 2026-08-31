/**
 * Replaces `pollChat()`/`renderChatView()` (web.py ~2342-2380). Mounted
 * only while `TerminalModal`'s `activeSubTab === 'chat'` (see that file) —
 * mount/unmount here IS the poll start/stop, replacing the original's
 * explicit `chatPollTimers[name]` set/clear inside `switchTermTab()`. This
 * is the OPPOSITE lifecycle from `TerminalView`, which polls continuously
 * for as long as the modal is open regardless of which sub-tab is
 * visually active — matches the original exactly: `switchTermTab()` only
 * ever starts/stops `chatPollTimers`, it never touches `termPollTimer`.
 */

import { useEffect, useState, type CSSProperties } from "react";
import { getTermChat } from "../../api/client";
import { useLang } from "../../i18n/LangContext";

const CHAT_POLL_INTERVAL_MS = 2500;

interface ChatViewProps {
  name: string;
}

type ChatState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "unsupported" }
  | { kind: "ok"; user: string; assistant: string };

const BOX_STYLE: CSSProperties = {
  width: "min(560px, 85vw)",
  maxHeight: "calc(92vh - 130px)",
  overflow: "auto",
  boxSizing: "border-box",
};

export function ChatView({ name }: ChatViewProps) {
  const { t, lang } = useLang();
  const [state, setState] = useState<ChatState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const d = await getTermChat(name, lang);
        if (cancelled) return;
        if (!d.ok) setState({ kind: "error", message: d.error });
        else if (!d.supported) setState({ kind: "unsupported" });
        else setState({ kind: "ok", user: d.user, assistant: d.assistant });
      } catch (e) {
        if (cancelled) return;
        setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      }
    };
    void poll();
    const id = setInterval(() => void poll(), CHAT_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [name, lang]);

  if (state.kind === "loading") return <div style={BOX_STYLE} />;
  if (state.kind === "error")
    return (
      <div style={BOX_STYLE}>
        {t.chatLoadError}
        {state.message}
      </div>
    );
  if (state.kind === "unsupported") return <div style={BOX_STYLE}>{t.chatUnsupported}</div>;

  return (
    <div style={BOX_STYLE}>
      <ChatBlock label={t.chatYou} text={state.user} emptyLabel={t.chatEmpty} />
      <ChatBlock label={t.chatAssistant} text={state.assistant} emptyLabel={t.chatEmpty} />
    </div>
  );
}

function ChatBlock({ label, text, emptyLabel }: { label: string; text: string; emptyLabel: string }) {
  return (
    <div style={{ marginBottom: ".7rem" }}>
      <div style={{ fontWeight: 600, fontSize: ".75rem", opacity: 0.7, marginBottom: ".2rem" }}>{label}</div>
      <div
        style={{
          whiteSpace: "pre-wrap",
          fontSize: ".85rem",
          lineHeight: 1.45,
          background: "var(--panel2)",
          border: "1px solid var(--border)",
          borderRadius: "6px",
          padding: ".5rem",
        }}
      >
        {text || emptyLabel}
      </div>
    </div>
  );
}
