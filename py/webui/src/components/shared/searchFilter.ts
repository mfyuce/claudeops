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

/** Field terms (TODO 1166): `model:opus*`, `cli:agy`, `host:ulak_31`, `name:`, `cwd:`/`path:`, `kind:`, `blueprint:`. */
export const SEARCH_FIELDS = ["model", "cli", "host", "name", "cwd", "path", "kind", "blueprint"] as const;
export type SearchField = (typeof SEARCH_FIELDS)[number];
const FIELD_TERM = new RegExp(`^(${SEARCH_FIELDS.join("|")}):(.+)$`);

export interface FieldTerm {
  field: SearchField;
  /** folded value; `*` = any characters (then the whole field must match), otherwise substring */
  value: string;
}

/** Splits a query into `label:x` terms (lower-cased; several = AND), `field:value` terms (AND) and the remaining free text. */
export function parseQuery(query: string): { labels: string[]; fields: FieldTerm[]; text: string } {
  const labels: string[] = [];
  const fields: FieldTerm[] = [];
  const rest: string[] = [];
  for (const tok of query.trim().split(/\s+/)) {
    const lower = tok.toLowerCase();
    const m = LABEL_TERM.exec(lower);
    const f = m ? null : FIELD_TERM.exec(lower);
    if (m) labels.push(m[1]);
    else if (f) fields.push({ field: f[1] as SearchField, value: foldText(f[2]) });
    else if (tok) rest.push(tok);
  }
  return { labels, fields, text: rest.join(" ") };
}

/** Field-name completions for the last (partial) token of a query: `mo` -> `model:`. Empty when it already has a colon. */
export function fieldSuggestions(query: string): string[] {
  const last = query.split(/\s+/).pop()?.toLowerCase() ?? "";
  if (last.length < 1 || last.includes(":")) return [];
  return SEARCH_FIELDS.filter((f) => f.startsWith(last) && f !== last).map((f) => `${f}:`);
}

/**
 * Value completions (TODO 2859) for a last token `model:x`, `cli:x`, `host:x`, `kind:x`, `blueprint:x`: the distinct values of
 * that field in `rows` that contain the typed part (folded), excluding an exact match; sorted, at most 8. Empty for other fields.
 */
export function valueSuggestions(query: string, rows: Searchable[]): string[] {
  const last = query.split(/\s+/).pop() ?? "";
  const m = /^(model|cli|host|kind|blueprint):(.*)$/i.exec(last);
  if (!m || m[2].includes("*")) return [];
  const field = m[1].toLowerCase() as SearchField;
  const typed = foldText(m[2]);
  const seen = new Set<string>();
  for (const r of rows) for (const v of fieldHay(r, field)) if (v) seen.add(v);
  return [...seen]
    .filter((v) => foldText(v).includes(typed) && foldText(v) !== typed)
    .sort()
    .slice(0, 8)
    .map((v) => `${field}:${v}`);
}

function fieldMatches(value: string, hay: string): boolean {
  if (!value.includes("*")) return hay.includes(value);
  const re = new RegExp("^" + value.split("*").map((x) => x.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$");
  return re.test(hay);
}

function fieldHay(item: Searchable, field: SearchField): string[] {
  switch (field) {
    case "model": return [item.model, item.live_model ?? ""];
    case "cli": return [item.cli];
    case "host": return [item.host];
    case "name": return [item.name, item.title ?? ""];
    case "cwd":
    case "path": return [item.cwd];
    case "kind": return [item.kind ?? ""];
    case "blueprint": return [item.blueprint ?? ""];
  }
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
  // `field:x` terms mean something only for session rows; here they stay ordinary words (old behaviour).
  const plain = query.trim().split(/\s+/).filter((tok) => !LABEL_TERM.test(tok.toLowerCase()));
  const words = foldText(plain.join(" ")).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = foldText(fields.map((f) => (f == null ? "" : String(f))).join("\n"));
  return words.every((w) => hay.includes(w));
}

/** Empty/whitespace-only query matches everything (search box cleared). */
export function matchesSearch(item: Searchable, query: string): boolean {
  const parsed = parseQuery(query);
  if (parsed.labels.length && !parsed.labels.every((l) => item.labels?.includes(l))) return false;
  if (parsed.fields.length && !parsed.fields.every((t) => fieldHay(item, t.field).some((h) => fieldMatches(t.value, foldText(h))))) return false;
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
