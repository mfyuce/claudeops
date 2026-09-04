/**
 * Shared name/cwd filter for the SearchBox (üstüne arama kutusu, 2026-09-04
 * request) — one predicate reused by TabBar's counts and all 4 list tabs'
 * row sets, so a session always counts as a "match" exactly where it's
 * also rendered. Matches `SessionInfo` and `RosterEntry` alike (only
 * `name`/`cwd` are read, both interfaces have them — see api/types.ts).
 */

export interface Searchable {
  name: string;
  cwd: string;
}

/** Empty/whitespace-only query matches everything (search box cleared). */
export function matchesSearch(item: Searchable, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return item.name.toLowerCase().includes(q) || item.cwd.toLowerCase().includes(q);
}
