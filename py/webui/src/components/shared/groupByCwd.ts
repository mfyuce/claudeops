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
