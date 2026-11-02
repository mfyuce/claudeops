# WEBUI-TODO (panel developer experience)

Scope: whole worktree (`py/webui/src`, `py/claudeops`). No commits from the assistant; `tsc` is run by the owner.
Status: [ ] open, [x] done.

1. [x] Empty states: GroupTable + HistoryTab `emptyHint`; Review/ucli lists keep their own text.
2. [x] Error messages: `friendlyUcliError` + generic `friendlyError` in `api/ucliErrors.ts`; applied to Diagnostics, Layout, Snapshot, Settings, Orch, Review. Open: toast-only call sites (GroupTable, HostsSection, StewardTab...) still raw.
3. [x] Keyboard shortcuts: Alt+1..9, `/` (`shared/useTabShortcuts.ts`). `?` help: `shared/ShortcutHelp.tsx` (inline TR/EN, mounted in App.tsx).
4. [x] Loading states: first status fetch (App.tsx). Added "…" loading rows in ReviewPanel and StewardTab (state null). Busy buttons were already everywhere (`disabled={busy}`), no change needed.
5. [x] Mobile layout: appended block at end of `styles/global.css` (36px tap targets, wrapping). Not verified in a browser; the cli column (with badges) is hidden <=640px by the existing query.
6. [x] ucli session row info: effort badge + write (✎) / exec / `≤$cap` badges. Backend: `web.py` `_ucli_flags(s)` (cmdline parse, per-pid cache) -> `ucli_flags` on sessions (local host only; gRPC remote rows don't carry it). No unittest yet.

7. [x] unittest for `_ucli_flags`: `py/tests/test_web_ucli_flags.py` (not run by the assistant).
8. [x] toast-only call sites (GroupTable, HostsSection, StewardTab) now use `friendlyError`.
9. [ ] Owner: verify mobile CSS + ucli badges <=640px in a browser; run `tsc` and `python3 py/tests/test_web_ucli_flags.py -v`.
10. [x] ucli badges (effort/✎/exec/≤$) moved from the cli cell into the name cell of `RunningTab/SessionRow.tsx`, so they show <=640px.
11. [x] Expandable error detail + copy: `shared/ErrorBox.tsx` (first line visible, raw message in <details>, copy button). Used in ReviewPanel.
12. [x] `ErrorBox` in Review, Steward, Settings, Snapshot, Orch. Layout/Diagnostics left as-is on purpose: their `<pre>` strings mix success and failure results.
13. [x] Copy buttons: `CwdCell` (shown when expanded) copies path and name. ucli session id: checked `ucli_provider.py` (~l.864): for ucli `sid` = the session name itself, so the "copy name" button already covers it; no new field needed.
14. [ ] SKIPPED (needs gRPC/proto field): `ucli_flags` on remote-host rows (web_grpc `_OPTIONAL_SESSION_FIELDS` + proto).
15. [ ] SKIPPED (needs backend/gRPC): ucli service badge; needs service recorded in the session record, not cmdline.

## Resume point
Next: nothing open for the assistant (12 and 13 done). 9 is owner's. 14/15 wait for a gRPC change.

## Done log
- friendlyError applied to 6 tabs; effort badge on ucli rows.
- ucli_flags backend + badges; mobile CSS block.
