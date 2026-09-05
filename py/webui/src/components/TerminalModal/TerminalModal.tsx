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

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useLang } from "../../i18n/LangContext";
import { ChatView } from "./ChatView";
import { FilesView } from "./FilesView";
import { TerminalView } from "./TerminalView";

type SubTab = "term" | "chat" | "files";

interface TerminalModalProps {
  name: string;
  onClose: () => void;
}

/**
 * Body scroll lock, live-verified as actually needed (2026-09-01, Playwright
 * + real CDP touch dispatch): with nothing preventing it, a touch-drag
 * starting on the backdrop margin OR on any non-scrollable part of the
 * modal panel itself (the header row, the tab bar, the key-button row below
 * the terminal — none of which have their own overflow/scroll handling)
 * scrolled the PAGE BEHIND the modal instead of doing nothing — measured
 * window.scrollY moving by dozens to hundreds of px per swipe. User report:
 * "sanki popup değil de arkadaki sayfa scroll oluyor" (feels like the page
 * behind is scrolling, not the popup). Plain `overflow:hidden` on body is
 * well known to be unreliable on iOS Safari specifically, hence the
 * fixed-position + restore-scroll-offset approach instead.
 */
function useBodyScrollLock() {
  useEffect(() => {
    const scrollY = window.scrollY;
    const body = document.body;
    const prev = { position: body.style.position, top: body.style.top, width: body.style.width, overflow: body.style.overflow };
    body.style.position = "fixed";
    body.style.top = `-${scrollY}px`;
    body.style.width = "100%";
    body.style.overflow = "hidden";
    return () => {
      body.style.position = prev.position;
      body.style.top = prev.top;
      body.style.width = prev.width;
      body.style.overflow = prev.overflow;
      window.scrollTo(0, scrollY);
    };
  }, []);
}

export function TerminalModal({ name, onClose }: TerminalModalProps) {
  const { t } = useLang();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>("term");
  useBodyScrollLock();

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
        overscrollBehavior: "contain",
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
          <button
            type="button"
            className={activeSubTab === "files" ? "active" : ""}
            onClick={() => setActiveSubTab("files")}
          >
            {t.tabFilesView}
          </button>
        </div>
        <TerminalView name={name} hidden={activeSubTab !== "term"} />
        {activeSubTab === "chat" && <ChatView name={name} />}
        {activeSubTab === "files" && <FilesView name={name} />}
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
