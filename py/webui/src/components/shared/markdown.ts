/**
 * Shared safe-markdown-to-HTML helper (`marked` parse + DOMPurify sanitize) —
 * extracted from `FileViewerModal.tsx` (2026-09-05, its original sole user)
 * when `ChatView.tsx`'s `ChatBlock` became a second one (2026-09-24, ucli
 * provider's answers are markdown-heavy and were rendering as raw `**`/`##`
 * literal text). Both render prose a CLI/agent produced, not this app's own
 * trusted content — raw HTML passthrough is a documented `marked` behavior,
 * so DOMPurify.sanitize() strips it before anything reaches
 * `dangerouslySetInnerHTML`. The link-target hook is registered HERE, once,
 * module-level (DOMPurify hooks are global to the library instance, not
 * per-`sanitize()` call) — duplicating it per-caller would just double-run
 * harmlessly, but one shared registration is cleaner.
 */
import DOMPurify from "dompurify";
import { marked } from "marked";

// A rendered document can contain its own links — without this, clicking
// one navigates the WHOLE panel away in the same tab (2026-09-05, user:
// "linkler yeni sayfada açılsın bu viewerda").
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

export async function renderMarkdownSafe(text: string): Promise<string> {
  const raw = await marked(text);
  return DOMPurify.sanitize(raw);
}
