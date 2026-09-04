/**
 * Tab identity — shared by `App.tsx` (owns `activeTab`) and `TabBar.tsx`
 * (renders the tab list), split into its own module so neither has to
 * import the other just for this type (React rewrite plan, Sequencing
 * step 5).
 */

export type TabKey =
  | "running"
  | "registered"
  | "disabled"
  | "retired"
  | "layout"
  | "desktop"
  | "diag"
  | "settings";

/** Same localStorage key as the original PAGE_HTML JS's `TAB` variable. */
export const TAB_STORAGE_KEY = "cops_tab";

const ALL_TABS: readonly TabKey[] = [
  "running",
  "registered",
  "disabled",
  "retired",
  "layout",
  "desktop",
  "diag",
  "settings",
];

export function isTabKey(value: string | null): value is TabKey {
  return value !== null && (ALL_TABS as readonly string[]).includes(value);
}
