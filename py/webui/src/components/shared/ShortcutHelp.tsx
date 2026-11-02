/**
 * `?` opens a small keyboard-shortcut list; Escape / click outside / the button closes it. Same typing guard as
 * `useTabShortcuts` (ignored inside inputs). Text is inline TR/EN to avoid widening the strings table.
 */
import { useEffect, useState } from "react";
import { useLang } from "../../i18n/LangContext";
import { useEscapeKey } from "./useEscapeKey";

export function ShortcutHelp() {
  const { lang } = useLang();
  const [open, setOpen] = useState(false);
  useEscapeKey(open ? () => setOpen(false) : undefined);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey || e.key !== "?") return;
      const el = e.target as HTMLElement | null;
      if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
      e.preventDefault();
      setOpen((o) => !o);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;
  const tr = lang === "tr";
  const rows: [string, string][] = [
    ["Alt+1…9", tr ? "soldan n'inci sekmeye geç" : "switch to the nth tab"],
    ["/", tr ? "arama kutusuna odaklan" : "focus the search box"],
    ["?", tr ? "bu listeyi aç/kapat" : "toggle this list"],
    ["Esc", tr ? "açık pencereyi kapat" : "close the open dialog"],
  ];
  return (
    <div
      role="dialog"
      aria-label={tr ? "Klavye kısayolları" : "Keyboard shortcuts"}
      onClick={() => setOpen(false)}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--panel, var(--bg, #222))", color: "inherit", border: "1px solid var(--border)", borderRadius: 8, padding: "1rem 1.25rem", minWidth: 260, maxWidth: "90vw" }}
      >
        <h3 style={{ marginTop: 0 }}>{tr ? "Klavye kısayolları" : "Keyboard shortcuts"}</h3>
        <table>
          <tbody>
            {rows.map(([k, d]) => (
              <tr key={k}>
                <td style={{ paddingRight: 16 }}>
                  <kbd>{k}</kbd>
                </td>
                <td>{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" style={{ marginTop: 10 }} onClick={() => setOpen(false)}>
          {tr ? "kapat" : "close"}
        </button>
      </div>
    </div>
  );
}
