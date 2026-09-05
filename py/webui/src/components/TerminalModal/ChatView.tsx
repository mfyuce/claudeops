/**
 * Replaces `pollChat()`/`renderChatView()` (web.py ~2342-2380). Mounted
 * only while `TerminalModal`'s `activeSubTab === 'chat'` (see that file) —
 * mount/unmount here IS the poll start/stop, replacing the original's
 * explicit `chatPollTimers[name]` set/clear inside `switchTermTab()`. This
 * is the OPPOSITE lifecycle from `TerminalView`, which polls continuously
 * for as long as the modal is open regardless of which sub-tab is
 * visually active — matches the original exactly: `switchTermTab()` only
 * ever starts/stops `chatPollTimers`, it never touches `termPollTimer`.
 *
 * 2026-09-01 addition (user request, TODO.md): a `mode` toggle between the
 * original single last-exchange view and the full conversation history
 * (`_term_chat(mode="full")` → `CliProvider.full_history()`). Switching
 * mode resets `state` to `loading` and the poll effect (keyed on `mode`)
 * restarts cleanly — same one-poll-loop-per-mount shape as before, just
 * re-mounted logically on toggle rather than trying to reconcile two
 * different response shapes inside one running loop.
 */

import { useEffect, useState, type CSSProperties } from "react";
import { getTermChat } from "../../api/client";
import type { ChatMessage } from "../../api/types";
import { useLang } from "../../i18n/LangContext";
import type { Strings } from "../../i18n/strings";

const CHAT_POLL_INTERVAL_MS = 2500;

interface ChatViewProps {
  name: string;
}

type ChatMode = "last" | "full";

type ChatState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "unsupported" }
  | { kind: "ok-last"; user: string; assistant: string }
  | { kind: "ok-full"; messages: ChatMessage[] };

const BOX_STYLE: CSSProperties = {
  width: "min(560px, 85vw)",
  maxHeight: "calc(92vh - 160px)",
  overflow: "auto",
  boxSizing: "border-box",
};

export function ChatView({ name }: ChatViewProps) {
  const { t, lang } = useLang();
  const [mode, setMode] = useState<ChatMode>("last");
  const [state, setState] = useState<ChatState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const d = await getTermChat(name, lang, mode);
        if (cancelled) return;
        if (!d.ok) setState({ kind: "error", message: d.error });
        else if (!d.supported) setState({ kind: "unsupported" });
        else if ("messages" in d) setState({ kind: "ok-full", messages: d.messages });
        else setState({ kind: "ok-last", user: d.user, assistant: d.assistant });
      } catch (e) {
        if (cancelled) return;
        setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      }
    };
    void poll();
    const id = setInterval(() => void poll(), CHAT_POLL_INTERVAL_MS);
    // Same fix as TerminalView.tsx (2026-09-05) — an immediate poll on
    // foreground so a backgrounded tab's stale chat view doesn't wait for
    // the next throttled interval tick.
    function onVisible() {
      if (document.visibilityState === "visible") void poll();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [name, lang, mode]);

  // Reset from the event that causes the mode change (not synchronously
  // inside the poll effect) — the effect above re-runs because `mode` is in
  // its dependency array, but state resets here, right where the change is
  // decided, not as a side effect of that re-run.
  function switchMode(next: ChatMode) {
    if (next === mode) return;
    setMode(next);
    setState({ kind: "loading" });
  }

  return (
    <div style={BOX_STYLE}>
      <div className="tabs" style={{ marginBottom: ".5rem" }}>
        <button type="button" className={mode === "last" ? "active" : ""} onClick={() => switchMode("last")}>
          {t.chatModeLast}
        </button>
        <button type="button" className={mode === "full" ? "active" : ""} onClick={() => switchMode("full")}>
          {t.chatModeFull}
        </button>
      </div>
      <ChatBody state={state} t={t} />
    </div>
  );
}

function ChatBody({ state, t }: { state: ChatState; t: Strings }) {
  if (state.kind === "loading") return null;
  if (state.kind === "error") return <div>{t.chatLoadError}{state.message}</div>;
  if (state.kind === "unsupported") return <div>{t.chatUnsupported}</div>;
  if (state.kind === "ok-last") {
    return (
      <>
        <ChatBlock label={t.chatYou} text={state.user} emptyLabel={t.chatEmpty} />
        <ChatBlock label={t.chatAssistant} text={state.assistant} emptyLabel={t.chatEmpty} />
      </>
    );
  }
  // ok-full — empty transcript is a legitimate state (fresh/idle session), not an error.
  if (state.messages.length === 0) return <div>{t.chatEmpty}</div>;
  return (
    <>
      {state.messages.map((m, i) => (
        <ChatBlock key={i} label={m.role === "user" ? t.chatYou : t.chatAssistant} text={m.text} emptyLabel={t.chatEmpty} />
      ))}
    </>
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
