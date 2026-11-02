/**
 * Generic (host, cwd) grouping — extracted from `RegisteredTab.tsx`'s
 * original `groupByCwd()`/`groupKey()` (2026-09-02 decision) so
 * `RunningTab.tsx`/`GroupTable.tsx` can reuse the same grouping instead of
 * staying flat tables. Deliberately generic over `T` rather than tied to
 * `SessionInfo`: `GroupTable.tsx` groups `RosterEntry[]`, which has no
 * `running`/`registered` fields — only `host`/`cwd` are required here.
 *
 * `hasRunning` (RegisteredTab's cross-tab "something in this group is
 * running" badge) is deliberately NOT part of this generic shape — it
 * needs the full running+stopped `SessionInfo[]` set, which only
 * RegisteredTab has reason to compute. Callers that want it compute it
 * themselves from this function's output (see RegisteredTab.tsx).
 */
export interface HasHostCwd {
  host: string;
  cwd: string;
}

export interface CwdGroup<T> {
  host: string;
  cwd: string;
  items: T[];
}

/** Composite group identity — two different hosts can genuinely have a
 * project checked out at the same absolute path; grouping those together
 * under one header would misleadingly imply they're the same project. */
export function groupKey(host: string, cwd: string): string {
  return `${host}:${cwd}`;
}

/** Group-key choices for the Running tab's selector (WEBUI-TODO 40). `cwd` = the default (host, cwd) grouping. */
export type GroupMode = "cwd" | "cli" | "host" | "none";
export const GROUP_MODES: GroupMode[] = ["cwd", "cli", "host", "none"];

/** Groups rows by a chosen field. `cwd` delegates to `groupByCwd`; `cli`/`host` produce one group per value
 * (group's `cwd` field carries the label, `host` is `localHost` so no host badge is drawn); `none` is one group. */
export function groupRowsBy<T extends HasHostCwd & { cli?: string }>(rows: T[], mode: GroupMode, localHost: string): CwdGroup<T>[] {
  if (mode === "cwd") return groupByCwd(rows);
  if (mode === "none") return rows.length ? [{ host: localHost, cwd: "", items: rows }] : [];
  const order: string[] = [];
  const byKey = new Map<string, T[]>();
  for (const r of rows) {
    const key = (mode === "cli" ? r.cli : r.host) || "?";
    let list = byKey.get(key);
    if (!list) {
      list = [];
      byKey.set(key, list);
      order.push(key);
    }
    list.push(r);
  }
  return order.map((key) => ({ host: localHost, cwd: key, items: byKey.get(key)! }));
}

/** Groups `rows` by `(host, cwd)`, in first-seen order. */
export function groupByCwd<T extends HasHostCwd>(rows: T[]): CwdGroup<T>[] {
  const order: string[] = [];
  const byKey = new Map<string, T[]>();
  for (const r of rows) {
    const key = groupKey(r.host, r.cwd);
    let list = byKey.get(key);
    if (!list) {
      list = [];
      byKey.set(key, list);
      order.push(key);
    }
    list.push(r);
  }
  return order.map((key) => {
    const items = byKey.get(key)!;
    return { host: items[0].host, cwd: items[0].cwd, items };
  });
}
