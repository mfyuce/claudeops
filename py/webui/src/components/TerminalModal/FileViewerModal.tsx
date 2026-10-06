/**
 * Inline viewer/editor for md/txt/html files (2026-09-05, user: "md/html/txt/text
 * bazlı dosyalar ise kendi viewer ımız olsa? ... sunucu html olarak
 * gosterse"). Fetches via `_files_read()` (capped at `MAX_VIEW_BYTES`, much
 * smaller than the download cap — this is for reading a document, not
 * shipping data). Triggered from either `FilesView.tsx`'s file rows or
 * `UrlBanner.tsx`'s terminal file-mention list; both live inside
 * `TerminalModal`, which owns the `viewingPath` state and renders this on
 * top of everything else (own portal, higher z-index than the terminal
 * modal's own overlay).
 *
 * Markdown is rendered (via the shared `renderMarkdownSafe`, `marked` +
 * DOMPurify) since it's just prose. html/htm is deliberately shown as plain
 * escaped SOURCE TEXT, never rendered live — a project's own `.html` file
 * could contain a `<script>`, and this page has no isolation between "a
 * file someone's CLI wrote" and "the panel's own origin/token" the way a
 * real browser tab-per-origin would. Markdown risks the same thing at a
 * smaller scale (raw HTML passthrough is a documented `marked` behavior) —
 * `renderMarkdownSafe`'s DOMPurify.sanitize() strips exactly that before it
 * ever reaches `dangerouslySetInnerHTML`.
 *
 * 2026-10-06: gained a plain-textarea edit mode (`apiFilesWrite` →
 * `/api/files/write`, same viewable-extension whitelist as read — no
 * separate "which files are editable" decision to make). Markdown's "html"
 * state now also carries the raw source (`raw`) so editing starts from the
 * actual text, not the rendered output; saving re-renders it the same way
 * the initial fetch did. Deliberately no dirty-check on Cancel/close — a
 * simple editor, not a full one (user: "çok basit bir editor").
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFilesWrite, getFilesRead } from "../../api/client";
import { useLang } from "../../i18n/LangContext";
import { renderMarkdownSafe } from "../shared/markdown";
import { useEscapeKey } from "../shared/useEscapeKey";
import { viewerKind } from "./fileViewerKind";

interface FileViewerModalProps {
  name: string;
  host: string;
  path: string;
  onClose: () => void;
}

type ViewState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "text"; text: string }
  | { kind: "html"; html: string; raw: string };

export function FileViewerModal({ name, host, path, onClose }: FileViewerModalProps) {
  const { t, lang } = useLang();
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const filename = path.split("/").pop() ?? path;
  useEscapeKey(onClose);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    setEditing(false);
    setSaveError(null);
    void (async () => {
      try {
        const d = await getFilesRead(name, lang, path, host);
        if (cancelled) return;
        if (!d.ok) {
          setState({ kind: "error", message: d.error });
          return;
        }
        if (viewerKind(filename) === "markdown") {
          setState({ kind: "html", html: await renderMarkdownSafe(d.text), raw: d.text });
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
  }, [name, host, lang, path, filename]);

  function startEditing() {
    setDraft(state.kind === "text" ? state.text : state.kind === "html" ? state.raw : "");
    setSaveError(null);
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await apiFilesWrite(name, lang, path, draft, host);
      if (!res.ok) {
        setSaveError(res.error);
        return;
      }
      if (viewerKind(filename) === "markdown") {
        setState({ kind: "html", html: await renderMarkdownSafe(draft), raw: draft });
      } else {
        setState({ kind: "text", text: draft });
      }
      setEditing(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const canEdit = state.kind === "text" || state.kind === "html";

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
          <div style={{ display: "flex", gap: ".35rem" }}>
            {!editing && canEdit && (
              <button type="button" style={{ fontSize: "1rem", lineHeight: 1, padding: ".2rem .55rem" }} onClick={startEditing}>
                {t.filesEdit}
              </button>
            )}
            <button type="button" style={{ fontSize: "1rem", lineHeight: 1, padding: ".2rem .55rem" }} onClick={onClose}>
              ✕
            </button>
          </div>
        </div>
        <div style={{ overflow: "auto", fontSize: ".85rem", lineHeight: 1.5 }}>
          {editing ? (
            <div>
              <textarea
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                style={{
                  width: "100%", minHeight: "50vh", fontFamily: "monospace", fontSize: ".85rem",
                  boxSizing: "border-box", resize: "vertical",
                }}
              />
              {saveError && <div>{t.filesSaveError}{saveError}</div>}
              <div style={{ display: "flex", gap: ".4rem", marginTop: ".4rem" }}>
                <button type="button" onClick={() => void save()} disabled={saving}>{t.filesSave}</button>
                <button type="button" onClick={() => setEditing(false)} disabled={saving}>{t.editCancel}</button>
              </div>
            </div>
          ) : state.kind === "loading" ? null : state.kind === "error" ? (
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
