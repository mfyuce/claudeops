/**
 * Inline viewer for md/txt/html files (2026-09-05, user: "md/html/txt/text
 * bazlı dosyalar ise kendi viewer ımız olsa? ... sunucu html olarak
 * gosterse"). Fetches via `_files_read()` (capped at `MAX_VIEW_BYTES`, much
 * smaller than the download cap — this is for reading a document, not
 * shipping data). Triggered from either `FilesView.tsx`'s file rows or
 * `UrlBanner.tsx`'s terminal file-mention list; both live inside
 * `TerminalModal`, which owns the `viewingPath` state and renders this on
 * top of everything else (own portal, higher z-index than the terminal
 * modal's own overlay).
 *
 * Markdown is rendered (via `marked` + DOMPurify) since it's just prose.
 * html/htm is deliberately shown as plain escaped SOURCE TEXT, never
 * rendered live — a project's own `.html` file could contain a `<script>`,
 * and this page has no isolation between "a file someone's CLI wrote" and
 * "the panel's own origin/token" the way a real browser tab-per-origin
 * would. Markdown risks the same thing at a smaller scale (raw HTML
 * passthrough is a documented `marked` behavior) — DOMPurify.sanitize()
 * strips exactly that before it ever reaches `dangerouslySetInnerHTML`.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { getFilesRead } from "../../api/client";
import { useLang } from "../../i18n/LangContext";
import { viewerKind } from "./fileViewerKind";

// A rendered markdown document can contain its own links (relative paths,
// external URLs) — without this, clicking one navigates the WHOLE panel
// away in the same tab (2026-09-05, user: "linkler yeni sayfada açılsın bu
// viewerda"). Module-level/registered once: DOMPurify hooks are global to
// the library instance, not per-`sanitize()` call.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

interface FileViewerModalProps {
  name: string;
  path: string;
  onClose: () => void;
}

type ViewState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "text"; text: string }
  | { kind: "html"; html: string };

export function FileViewerModal({ name, path, onClose }: FileViewerModalProps) {
  const { t, lang } = useLang();
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const filename = path.split("/").pop() ?? path;

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    void (async () => {
      try {
        const d = await getFilesRead(name, lang, path);
        if (cancelled) return;
        if (!d.ok) {
          setState({ kind: "error", message: d.error });
          return;
        }
        if (viewerKind(filename) === "markdown") {
          const raw = await marked(d.text);
          setState({ kind: "html", html: DOMPurify.sanitize(raw) });
        } else {
          setState({ kind: "text", text: d.text });
        }
      } catch (e) {
        if (cancelled) return;
        setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [name, lang, path, filename]);

  const overlay = (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.75)", zIndex: 1100,
        display: "flex", alignItems: "center", justifyContent: "center", overscrollBehavior: "contain",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: "min(720px, 92vw)", maxHeight: "88vh", background: "var(--panel)",
          borderRadius: "8px", display: "flex", flexDirection: "column", padding: ".7rem", boxSizing: "border-box",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: ".4rem" }}>
          <strong style={{ overflowWrap: "anywhere" }}>{filename}</strong>
          <button type="button" style={{ fontSize: "1rem", lineHeight: 1, padding: ".2rem .55rem" }} onClick={onClose}>
            ✕
          </button>
        </div>
        <div style={{ overflow: "auto", fontSize: ".85rem", lineHeight: 1.5 }}>
          {state.kind === "loading" ? null : state.kind === "error" ? (
            <div>{t.filesLoadError}{state.message}</div>
          ) : state.kind === "html" ? (
            // eslint-disable-next-line react/no-danger -- sanitized just above via DOMPurify
            <div dangerouslySetInnerHTML={{ __html: state.html }} />
          ) : (
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: "monospace", margin: 0 }}>
              {state.text}
            </pre>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}
