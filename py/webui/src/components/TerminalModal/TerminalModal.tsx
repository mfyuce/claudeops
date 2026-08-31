/**
 * Replaces `termRow()`'s shell (web.py ~2020-2063) — portaled to
 * `document.body` (a fixed full-viewport overlay has no business living
 * inside the Running table's DOM it's logically triggered from). `App`
 * renders this as `<TerminalModal key={openTerminalFor} name={openTerminalFor}
 * onClose={...} />` whenever `openTerminalFor` is set — the `key` forces a
 * clean remount (fresh `TerminalView`/`ChatView` instances, fresh
 * `activeSubTab`) whenever WHICH session's terminal is open changes, and
 * is the idiomatic replacement for the original's manual
 * `xtermInstances[prev].dispose()` bookkeeping in `toggleTerm()`. Because
 * `openTerminalFor` itself only changes when the user opens/closes/
 * switches a terminal — never as a side effect of a background status
 * poll — this component is never remounted by one either.
 *
 * Owns `activeSubTab` as plain local `useState`. This is THE structural
 * fix for the chat-tab snap-back bug that motivated the whole rewrite: the
 * original's `termTab` was a module-level global that every 4s `render()`
 * call's `innerHTML=` wipe forced back to re-deriving via
 * `applyTermTabVisual(termFor, termTab)` immediately afterward — the
 * variable itself didn't reset, but the DOM node showing it did, and
 * apparently that reapplication had its own gap (the bug report this
 * fixes). Here there is no re-render to reconcile after: `StatusContext`
 * updating doesn't touch this component's props, so `activeSubTab` is
 * simply never touched by anything except the user clicking a sub-tab
 * button. Verified directly in the step-9 checkpoint (see the commit for
 * that stage), not just reasoned about.
 *
 * `TerminalView` is always mounted for as long as this modal is open,
 * regardless of `activeSubTab` (only visually hidden) — it keeps polling
 * in the background even while the chat sub-tab is showing. `ChatView`,
 * in contrast, is only mounted while `activeSubTab === 'chat'` — its
 * mount/unmount IS its poll start/stop. This asymmetry is deliberate and
 * matches the original exactly: `switchTermTab()` only ever starts/stops
 * `chatPollTimers`, it never touches `termPollTimer` (that one runs for as
 * long as `toggleTerm()`'s `termFor` is set, independent of which sub-tab
 * is visually active).
 */

import { useState } from "react";
import { createPortal } from "react-dom";
import { useLang } from "../../i18n/LangContext";
import { ChatView } from "./ChatView";
import { TerminalView } from "./TerminalView";

type SubTab = "term" | "chat";

interface TerminalModalProps {
  name: string;
  onClose: () => void;
}

export function TerminalModal({ name, onClose }: TerminalModalProps) {
  const { t } = useLang();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>("term");

  const overlay = (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.75)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      // Original: onclick="if(event.target===this) toggleTerm(name)" — only
      // close on a direct click on the backdrop itself, not a click that
      // bubbled up from something inside the panel.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          maxWidth: "95vw",
          maxHeight: "92vh",
          width: "fit-content",
          background: "var(--panel)",
          borderRadius: "8px",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          padding: ".7rem",
          boxSizing: "border-box",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: ".4rem",
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          <strong>{name}</strong>
          <button type="button" style={{ fontSize: "1rem", lineHeight: 1, padding: ".2rem .55rem" }} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="tabs" style={{ marginBottom: ".5rem", width: "100%", boxSizing: "border-box" }}>
          <button
            type="button"
            className={activeSubTab === "term" ? "active" : ""}
            onClick={() => setActiveSubTab("term")}
          >
            {t.tabTermView}
          </button>
          <button
            type="button"
            className={activeSubTab === "chat" ? "active" : ""}
            onClick={() => setActiveSubTab("chat")}
          >
            {t.tabChatView}
          </button>
        </div>
        <TerminalView name={name} hidden={activeSubTab !== "term"} />
        {activeSubTab === "chat" && <ChatView name={name} />}
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
