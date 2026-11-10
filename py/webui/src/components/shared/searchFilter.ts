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
  /** Çalışan session'ın GERÇEK modeli (Running tablosu bunu gösterir); aramada da bulunsun. */
  live_model?: string | null;
  cli: string;
  host: string;
  kind?: "fresh" | "resume" | null;
  blueprint?: string | null;
  /** History rows: backend-computed readable title (review / steward). */
  title?: string;
  /** Project labels (`label:x` search terms match these exactly). */
  labels?: string[];
}

const LABEL_TERM = /^label:([a-z0-9_-]+)$/;

/** Splits a query into `label:x` terms (lower-cased; several = AND) and the remaining free text (old behaviour). */
export function parseQuery(query: string): { labels: string[]; text: string } {
  const labels: string[] = [];
  const rest: string[] = [];
  for (const tok of query.trim().split(/\s+/)) {
    const m = LABEL_TERM.exec(tok.toLowerCase());
    if (m) labels.push(m[1]);
    else if (tok) rest.push(tok);
  }
  return { labels, text: rest.join(" ") };
}

/** Empty/whitespace-only query matches everything (search box cleared). */
export function matchesSearch(item: Searchable, query: string): boolean {
  const parsed = parseQuery(query);
  if (parsed.labels.length && !parsed.labels.every((l) => item.labels?.includes(l))) return false;
  const q = parsed.text.toLowerCase();
  if (!q) return true;
  return (
    item.name.toLowerCase().includes(q) ||
    (item.title?.toLowerCase().includes(q) ?? false) ||
    item.cwd.toLowerCase().includes(q) ||
    item.model.toLowerCase().includes(q) ||
    (item.live_model?.toLowerCase().includes(q) ?? false) ||
    item.cli.toLowerCase().includes(q) ||
    item.host.toLowerCase().includes(q) ||
    (item.kind?.toLowerCase().includes(q) ?? false) ||
    (item.blueprint?.toLowerCase().includes(q) ?? false)
  );
}
