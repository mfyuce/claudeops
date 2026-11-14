/**
 * Tab identity — shared by `App.tsx` (owns `activeTab`) and `TabBar.tsx`
 * (renders the tab list), split into its own module so neither has to
 * import the other just for this type (React rewrite plan, Sequencing
 * step 5).
 */

/** Extension tab (K10, claudeops-enterprise "Yönetim" etc.): `ext:<id>`, id registered server-side. */
export type ExtTabKey = `ext:${string}`;

export type TabKey =
  | ExtTabKey
  | "running"
  | "registered"
  | "ucli"
  | "disabled"
  | "retired"
  | "history"
  | "team"
  | "steward"
  | "desktop"
  | "snapshots"
  | "readlist"
  | "diag"
  | "settings";

/** Same localStorage key as the original PAGE_HTML JS's `TAB` variable. */
export const TAB_STORAGE_KEY = "cops_tab";

const ALL_TABS: readonly TabKey[] = [
  "running",
  "registered",
  "ucli",
  "disabled",
  "retired",
  "history",
  "team",
  "steward",
  "desktop",
  "snapshots",
  "readlist",
  "diag",
  "settings",
];

const EXT_TAB_RE = /^ext:[a-z0-9_-]{1,40}$/;

export function isExtTab(key: string): key is ExtTabKey {
  return EXT_TAB_RE.test(key);
}

/** `ext:admin` -> `admin`; "" for a non-extension key. */
export function extIdOf(key: string): string {
  return isExtTab(key) ? key.slice(4) : "";
}

export function isTabKey(value: string | null): value is TabKey {
  return value !== null && ((ALL_TABS as readonly string[]).includes(value) || isExtTab(value));
}
