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

/**
 * Case- and Turkish-letter-insensitive form of a string for searching: İ/I/ı/i -> i, ş/ç/ğ/ö/ü -> s/c/g/o/u (and any other
 * combining accent dropped), so "ISIK", "ışık" and "isik" all match each other and "runic" finds "Runik"-less text the same way.
 * (`toLowerCase()` alone turns "İ" into "i" + a combining dot and leaves "ı" distinct, which is why Turkish text searched badly.)
 */
export function foldText(s: string): string {
  return s
    .replace(/İ/g, "i")
    .replace(/I/g, "i")
    .replace(/ı/g, "i")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/**
 * Free-text match for list rows that are not sessions (reading list, snapshots, steward questions ...): every whitespace-separated
 * word of the query must occur (AND, like a normal search box) in the folded concatenation of `fields`. `label:x` terms are ignored
 * here (they only mean something for session rows). Empty query matches everything.
 */
export function matchesText(fields: Array<string | number | null | undefined>, query: string): boolean {
  const words = foldText(parseQuery(query).text).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = foldText(fields.map((f) => (f == null ? "" : String(f))).join("\n"));
  return words.every((w) => hay.includes(w));
}

/** Empty/whitespace-only query matches everything (search box cleared). */
export function matchesSearch(item: Searchable, query: string): boolean {
  const parsed = parseQuery(query);
  if (parsed.labels.length && !parsed.labels.every((l) => item.labels?.includes(l))) return false;
  const q = foldText(parsed.text);
  if (!q) return true;
  return (
    foldText(item.name).includes(q) ||
    (item.title ? foldText(item.title).includes(q) : false) ||
    foldText(item.cwd).includes(q) ||
    foldText(item.model).includes(q) ||
    (item.live_model ? foldText(item.live_model).includes(q) : false) ||
    foldText(item.cli).includes(q) ||
    foldText(item.host).includes(q) ||
    (item.kind ? foldText(item.kind).includes(q) : false) ||
    (item.blueprint ? foldText(item.blueprint).includes(q) : false)
  );
}
