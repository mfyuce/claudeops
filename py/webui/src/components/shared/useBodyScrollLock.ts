/**
 * Extracted from `TerminalModal.tsx` (2026-09-14) so `ReadOnlySessionModal`
 * can share it instead of duplicating — see the original's comment for why
 * it's needed at all: without it, a touch-drag starting on the backdrop
 * margin or any non-scrollable part of a fixed-position modal scrolls the
 * PAGE BEHIND it on iOS Safari instead of doing nothing (live-verified,
 * 2026-09-01, Playwright + real CDP touch dispatch). Plain `overflow:hidden`
 * on body is well known to be unreliable there, hence fixed-position +
 * restore-scroll-offset instead.
 */
import { useEffect } from "react";

export function useBodyScrollLock() {
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
