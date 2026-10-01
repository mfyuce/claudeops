/**
 * TerminalView (xterm) and ChatView's "last exchange" (markdown re-render)
 * both apply each poll/WS tick by tearing down and rebuilding their DOM —
 * `term.write('\x1b[H\x1b[2J\x1b[3J' + text)` clears+redraws the whole
 * buffer, `ChatBlock` resets `html` to `null` then re-renders via
 * `dangerouslySetInnerHTML` — every time there's ANY new output, not just
 * when something the user is looking at actually changed. A browser text
 * Selection is anchored to specific DOM nodes/offsets, so either rebuild
 * silently collapses it — during active generation this can happen every
 * poll tick (as often as ~1s via the terminal's WS push), well under the
 * time it takes to select text and hit copy (2026-10-01 user report:
 * "chat history de seçiorum copy diyemeden kopy kayboluyor").
 *
 * `hasActiveSelectionWithin()` lets a view check, right before a
 * destructive rebuild, whether to hold the update back instead — the
 * caller is responsible for stashing the latest pending value and
 * re-applying it once the selection clears (see TerminalView.tsx/
 * ChatView.tsx's own `selectionchange` listeners for the exact pattern;
 * deliberately not centralized here since the two views stash/replay
 * different shapes).
 */
export function hasActiveSelectionWithin(container: HTMLElement | null): boolean {
  if (!container) return false;
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return false;
  if (!sel.toString()) return false; // some browsers report a non-collapsed empty range
  const anchor = sel.anchorNode;
  return !!anchor && container.contains(anchor);
}
