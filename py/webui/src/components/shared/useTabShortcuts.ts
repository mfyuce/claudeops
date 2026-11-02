/**
 * Panel keyboard shortcuts (DOM based, so they follow whatever the TabBar renders): `Alt+1..9` = nth tab,
 * `/` = focus the search box. Ignored while typing in an input/textarea/select/contenteditable or with Ctrl/Meta held.
 */
import { useEffect } from "react";

export function useTabShortcuts(): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey) return;
      const el = e.target as HTMLElement | null;
      const typing = !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
      if ((e.altKey && /^Digit[1-9]$/.test(e.code)) || (e.altKey && /^[1-9]$/.test(e.key))) {
        const n = Number(/^Digit/.test(e.code) ? e.code.slice(5) : e.key);
        const btn = document.querySelectorAll<HTMLButtonElement>(".tabs > button")[n - 1];
        if (btn) {
          e.preventDefault();
          btn.click();
        }
        return;
      }
      if (e.key === "/" && !e.altKey && !typing) {
        const input = document.querySelector<HTMLInputElement>(".searchbox input");
        if (input) {
          e.preventDefault();
          input.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
}
