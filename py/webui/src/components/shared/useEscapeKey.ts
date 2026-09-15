/**
 * Closes the nearest open popup on Escape (2026-09-15) — shared by
 * TerminalModal/ReadOnlySessionModal/FileViewerModal, same extraction
 * rationale as `useBodyScrollLock`.
 *
 * Pass `undefined` instead of a callback to disable it: TerminalModal/
 * ReadOnlySessionModal do this while their own `viewingPath` (nested
 * FileViewerModal) is set, so a single Escape closes the file viewer first
 * rather than both popups at once — a second Escape then closes the parent.
 */
import { useEffect } from "react";

export function useEscapeKey(onEscape: (() => void) | undefined) {
  useEffect(() => {
    if (!onEscape) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onEscape!();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onEscape]);
}
