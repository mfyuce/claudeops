/**
 * Per-tab group expand/collapse state, shared by RegisteredTab/RunningTab/
 * GroupTable now that all three group by (host, cwd).
 *
 * Tracks EXPANDED keys (not collapsed ones) so the empty-set default means
 * "everything starts collapsed" — the 2026-09-14 decision reversing
 * RegisteredTab's original 2026-09-02 "all start expanded" default
 * (user: "tablarda all collapsed gelsin"). `expandAll` needs the current
 * key list handed to it (this hook doesn't know the tab's data), same
 * reason `usePagination` takes its items as an argument each render rather
 * than owning them.
 */
import { useState } from "react";

export function useGroupCollapse() {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  function isExpanded(key: string): boolean {
    return expanded.has(key);
  }

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function collapseAll() {
    setExpanded(new Set());
  }

  function expandAll(keys: string[]) {
    setExpanded(new Set(keys));
  }

  return { isExpanded, toggle, collapseAll, expandAll };
}
