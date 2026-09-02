/**
 * TODO L53 (2026-08-25): flag `ulaksec`'s row so it doesn't get bulk-selected
 * by accident. Name-based code protection was removed 2026-08-25 — targeting
 * is by panel checkbox now, only process-based self-protection remains for
 * the session running claudeops itself ([[co-ulaksec-guard-yes-ho-no]]).
 * This is ONLY a visual nudge (a badge next to the name in Running/Registered
 * rows) — it does not block selection or any action.
 */
const PROTECTED_RE = /^ulaksec(?:\d.*)?$/;

export function isProtectedName(name: string): boolean {
  return PROTECTED_RE.test(name);
}
