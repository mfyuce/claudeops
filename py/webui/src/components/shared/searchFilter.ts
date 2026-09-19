/**
 * Shared filter for the SearchBox (üstüne arama kutusu, 2026-09-04 request;
 * widened 2026-09-19, user: "arama yaparken herşeyi arasın model tip path"
 * then "yani tabloda ne varsa arasın") — one predicate reused by TabBar's
 * counts and all 4 list tabs' row sets, so a session always counts as a
 * "match" exactly where it's also rendered. Matches `SessionInfo`,
 * `RosterEntry` and `InstanceRecord` alike — see api/types.ts. Every
 * STRING/categorical column a row can show is covered (name, path, model,
 * cli badge, host badge, fresh/resume kind, blueprint); `kind`/`blueprint`
 * are optional here since `RosterEntry` (Disabled/Retired) carries neither
 * and plain `RosterEntry`-shaped rows just never match on them. Deliberately
 * NOT covering pid/cpu/history_size/running/busy/needs_ho/dates — those are
 * numeric/boolean state with their own dedicated selection UI already
 * (BulkBar's "select needs-ho"/"select attention"), not free-text fields.
 */

export interface Searchable {
  name: string;
  cwd: string;
  model: string;
  cli: string;
  host: string;
  kind?: "fresh" | "resume" | null;
  blueprint?: string | null;
}

/** Empty/whitespace-only query matches everything (search box cleared). */
export function matchesSearch(item: Searchable, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    item.name.toLowerCase().includes(q) ||
    item.cwd.toLowerCase().includes(q) ||
    item.model.toLowerCase().includes(q) ||
    item.cli.toLowerCase().includes(q) ||
    item.host.toLowerCase().includes(q) ||
    (item.kind?.toLowerCase().includes(q) ?? false) ||
    (item.blueprint?.toLowerCase().includes(q) ?? false)
  );
}
