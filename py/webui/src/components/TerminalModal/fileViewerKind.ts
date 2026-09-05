/** Shared by `FilesView.tsx` (folder browser) and `UrlBanner.tsx` (terminal
 * file-mention list) — both need to decide whether a file gets a "view"
 * action at all, and `FileViewerModal.tsx` needs to know how to render what
 * it fetched. Deliberately narrow (2026-09-05, user: "md/html/txt/text
 * bazlı dosyalar") rather than "any text-ish extension" — expanding the list
 * is a one-line change here whenever actually needed.
 */
const VIEWABLE_EXTENSIONS = new Set(["md", "markdown", "txt", "text", "html", "htm"]);

function extOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : "";
}

export function isViewable(filename: string): boolean {
  return VIEWABLE_EXTENSIONS.has(extOf(filename));
}

/** "markdown" gets rendered (via `marked` + DOMPurify); everything else
 * viewable (txt/html/htm) is shown as plain escaped source text — html/htm
 * is deliberately NOT rendered live (a project file could contain a
 * `<script>`, which would run in the panel's own origin if injected as
 * markup; showing it as inert text avoids that entirely). */
export function viewerKind(filename: string): "markdown" | "source" {
  const ext = extOf(filename);
  return ext === "md" || ext === "markdown" ? "markdown" : "source";
}
