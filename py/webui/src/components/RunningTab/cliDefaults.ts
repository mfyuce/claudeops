/**
 * Small shared defaults used by both `OptionsRow` and `AdoptRow` when
 * initializing their local form state — matches `renderCliFields()`'s
 * defaulting logic in the original (web.py ~1934-1943).
 */

import type { CliOptions } from "../../api/types";

/** Original: `m === (saved.pm || 'auto')` — the literal string "auto",
 * not "first item in the CLI's permission_modes list". */
export const DEFAULT_PERMISSION_MODE = "auto";

/** Original: `opts.effort_levels[opts.effort_levels.length - 1]` — the
 * LAST entry in the list (every provider's list ends with its highest
 * effort level, e.g. "max"). */
export function defaultEffort(opts: CliOptions): string {
  return opts.effort_levels[opts.effort_levels.length - 1] ?? "";
}
