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

/**
 * Tab grouping (TODO "Panel sekme gruplama"): the stored/active key stays the LEGACY key (ucli, team, steward, desktop,
 * readlist, snapshots, diag, settings), so localStorage values, `onSwitchTab("diag")` calls and old links keep working.
 * Only the tab BAR groups them: top-level "tools" (Araçlar) and "settings" own a sub-tab row.
 */
export type TabGroup = "tools" | "settings";

export const TOOLS_SUBS: readonly TabKey[] = ["ucli", "team", "steward", "desktop", "readlist"];
export const SETTINGS_SUBS: readonly TabKey[] = ["settings", "snapshots", "diag"];

/** Keys hidden for a filtered (non-admin) view: same set the old flat bar hid. */
export const RESTRICTED_HIDE: readonly string[] = ["team", "steward", "desktop", "snapshots", "readlist", "diag", "settings"];

/** Group a key belongs to, or null for a top-level tab (running, registered, ..., ext:<id>). */
export function groupOf(key: string): TabGroup | null {
  if ((TOOLS_SUBS as readonly string[]).includes(key)) return "tools";
  if ((SETTINGS_SUBS as readonly string[]).includes(key)) return "settings";
  return null;
}

/** Visible sub-tabs of a group (restricted views lose the admin ones; readlist only when the extension registered it). */
export function visibleSubs(group: TabGroup, opts: { restricted?: boolean; hasReadlist?: boolean }): TabKey[] {
  const base = group === "tools" ? TOOLS_SUBS : SETTINGS_SUBS;
  return base.filter(
    (k) => !(opts.restricted && RESTRICTED_HIDE.includes(k)) && !(k === "readlist" && !opts.hasReadlist),
  );
}

/** Which top-level button is highlighted for the active key. */
export function topTabOf(active: TabKey): TabKey | TabGroup {
  return groupOf(active) ?? active;
}

/** Key to open when a group's top-level button is clicked: the remembered sub when still visible, else the first visible. */
export function entryTabFor(group: TabGroup, opts: { restricted?: boolean; hasReadlist?: boolean }, last?: string | null): TabKey | null {
  const subs = visibleSubs(group, opts);
  if (last && (subs as readonly string[]).includes(last)) return last as TabKey;
  return subs[0] ?? null;
}

export function isTabKey(value: string | null): value is TabKey {
  return value !== null && ((ALL_TABS as readonly string[]).includes(value) || isExtTab(value));
}
