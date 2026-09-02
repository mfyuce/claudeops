/**
 * Theme application — sets `data-theme` on <html> so an explicit user
 * choice (TODO L73, 2026-09-02) overrides `prefers-color-scheme` in either
 * direction; "system" removes the attribute and leaves the CSS media query
 * in charge, matching today's (pre-Settings) behavior exactly.
 *
 * Cached in localStorage purely as a same-instant fast-path so the right
 * theme paints before the first `/api/status` response arrives (server-side
 * settings.json is the actual source of truth and needs a round-trip) —
 * mirrors `LangContext`'s own `cops_lang` cache.
 */
import type { Theme } from "./api/types";

const STORAGE_KEY = "cops_theme";

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore — same defensiveness as LangContext's setLang()
  }
}

/** Call once, as early as possible (before first paint) — applies the
 * last-known theme from localStorage so there's no flash of the wrong
 * theme while `/api/status` is still loading. */
export function applyCachedTheme(): void {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") applyTheme(stored);
  } catch {
    // ignore
  }
}
