/**
 * The shared `selectedNames` Set — owned by `App` (per the plan's
 * component table) and threaded down as props to `RunningTab`/
 * `RegisteredTab`/`BulkBar`/`SessionRow`, NOT a third Context (the plan is
 * explicit: exactly two Contexts, `LangContext` and `StatusContext`;
 * everything else is ordinary local `useState` owned by whichever
 * component needs it — here that's `App`).
 *
 * Replaces the original's module-level `const SEL = new Set()` +
 * `toggleSel`/`toggleSelAll`/`selectNeedsHo` free functions. A `Set` held
 * in `useState` must be replaced (not mutated in place) for React to
 * notice the change — every method below does a full copy.
 */

import { useCallback, useState } from "react";

export interface SelectionControls {
  selected: Set<string>;
  /** Replaces `toggleSel(name, on)`. */
  toggle: (name: string, on: boolean) => void;
  /** Replaces `toggleSelAll(on)` (called with the current tab's row
   * names — the original read `CUR_TAB_NAMES`, a side-effect global set by
   * whichever table last rendered; here the caller just passes its own
   * rows). */
  toggleMany: (names: string[], on: boolean) => void;
  /** Replaces `SEL.clear(); for (...) SEL.add(...)` in `selectNeedsHo()` —
   * also handy as `replace([])` to clear the selection outright (used
   * after a bulk action completes, matching the original's `SEL.clear()`
   * at the end of `bulkAct()`). */
  replace: (names: string[]) => void;
}

export function useSelection(): SelectionControls {
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const toggle = useCallback((name: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  }, []);

  const toggleMany = useCallback((names: string[], on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const n of names) {
        if (on) next.add(n);
        else next.delete(n);
      }
      return next;
    });
  }, []);

  const replace = useCallback((names: string[]) => {
    setSelected(new Set(names));
  }, []);

  return { selected, toggle, toggleMany, replace };
}
