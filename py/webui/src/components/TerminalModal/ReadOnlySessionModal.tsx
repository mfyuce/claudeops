/**
 * Read-only Chat+Files popup for a STOPPED session (Disabled/Devre Dışı or
 * Retired/Emekli) — TODO.md (2026-09-11, user: "disabled larda terminal
 * benzeri ama terminal olmayan bir pup iup ve readonly, chat i files ...").
 *
 * Deliberately NOT `TerminalModal` with a new prop: that component's whole
 * structure (`TerminalView` always-mounted, polling every 200ms, live-typing,
 * mode/model pickers) assumes a live tmux pane as its anchor — none of that
 * applies here, there is no pane. This is a smaller, separate modal that
 * only ever mounts `ChatView`/`FilesView`, both of which already work off
 * disk (`provider.last_exchange()`/`full_history()`, `roots_for_session()`)
 * rather than a live process — confirmed by extending `_files_resolve()`
 * (`commands/web.py`) to fall back to a synthetic `Session(pid=0, ...)` built
 * from `_fleet_status()`'s roster record when no live proc is found, and
 * pointing `_term_chat()` at that same resolver instead of the tmux-only
 * `_term_resolve()`. Live-verified against real closed roster entries
 * (`mamut`, `saseppr`) before this component was written.
 *
 * No Terminal sub-tab (nothing to attach to), no "Bilgi" sub-tab (no live
 * mode/model/URL for a session that isn't running), no message box, no
 * live-typing, no mode/model pickers — `ChatView`/`FilesView` are already
 * read-only in practice (chat has no send box; files only view/download),
 * so reusing them as-is needed no prop changes at all.
 */
import { useState } from "react";
import { createPortal } from "react-dom";
import { useLang } from "../../i18n/LangContext";
import { useBodyScrollLock } from "../shared/useBodyScrollLock";
import { useEscapeKey } from "../shared/useEscapeKey";
import { ChatView } from "./ChatView";
import { FileViewerModal } from "./FileViewerModal";
import { FilesView } from "./FilesView";

type ReadOnlySubTab = "chat" | "files";

interface ReadOnlySessionModalProps {
  name: string;
  host: string;
  onClose: () => void;
}

export function ReadOnlySessionModal({ name, host, onClose }: ReadOnlySessionModalProps) {
  const { t } = useLang();
  const [activeSubTab, setActiveSubTab] = useState<ReadOnlySubTab>("chat");
  const [viewingPath, setViewingPath] = useState<string | null>(null);
  useBodyScrollLock();
  // Nested FileViewerModal (below) owns Escape while it's open — see useEscapeKey's docstring.
  useEscapeKey(viewingPath ? undefined : onClose);

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
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          maxWidth: "95vw",
          maxHeight: "92dvh",
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
        <div className="opts-hint" style={{ width: "100%", boxSizing: "border-box", marginBottom: ".4rem" }}>
          {t.readOnlySessionHint}
        </div>
        <div className="tabs" style={{ marginBottom: ".5rem", width: "100%", boxSizing: "border-box" }}>
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
        {activeSubTab === "chat" && <ChatView name={name} host={host} />}
        {activeSubTab === "files" && <FilesView name={name} host={host} onView={setViewingPath} />}
      </div>
      {viewingPath && (
        <FileViewerModal name={name} host={host} path={viewingPath} onClose={() => setViewingPath(null)} />
      )}
    </div>
  );

  return createPortal(overlay, document.body);
}
