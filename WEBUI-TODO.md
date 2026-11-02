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
14. [x] `ucli_flags` over gRPC: `host_bridge.proto` SessionRow fields 19-21 (`ucli_write`, `ucli_exec`, `ucli_max_cost_usd`); `web_grpc.py` maps them both ways, guarded by `_PB_HAS_UCLI_FLAGS`. OWNER: regenerate `host_bridge_pb2.py` (protoc not available to the assistant); until then remote rows have no badges, nothing breaks. No unittest for the mapping yet.
15. [ ] SKIPPED (cannot be done here): ucli service badge. The service is not in the cmdline, and it needs ucli to record it in the session record first.

Round 2 (picked from `claudeops-TODO-ui.md`; short):
16. [x] `friendlyError` 5xx rule matched any 5xx number; now only "http 5xx"/"status 5xx"/"bad gateway"... (`ucliErrors.ts`).
17. [x] GroupTable reactivate: "already active" shows as info toast, not an error, no double name.
18. [x] ReviewPanel "Only this": enable target first, then disable others; a mid-way failure says what is left half-done.
19. [x] Start window exec hint rewritten in plain words (built-in tools first, exec last resort). The bind-dirs field already existed.
20. [x] RunningTab toasts (SessionRow, OptionsRow, AdoptRow) use `friendlyError` for thrown errors.
21. [x] Backend `ucli_cost_watch` (`web_steward.py`): warn/stop flags reset when the cap changes, so raising the cap re-arms the watch. Tests: `py/tests/test_ucli_cost_watch.py` (existing file, +2 tests; not run).
22. [x] `web.py` SIGTERM handler: cloudflared tunnel is terminated before `os._exit` (was left orphaned). `_TUNNEL_PROC` + `_terminate_tunnel()`; tests `py/tests/test_web_sigterm_tunnel.py` (not run).
23. [x] `web_orch.py` push key now `(run_id, host, name)`; `http_result` takes optional `host`; without it a push is accepted only if exactly one waiting match exists. Tests `py/tests/test_web_orch_push_key.py` (not run). Optional: MCP `cops_result_push` could send `host`.

Round 3 (P2 review findings; all tests in `py/tests/test_p2_atomic_writes.py`, NOT run):
24. [x] New `atomic_json.atomic_write_text` (per-thread tmp, O_EXCL, fsync). `web_review.py`: `_write_lesson` (was fixed `path.tmp`, now `file_lock` + atomic) and the draft redaction rewrite (also fixed `dp.tmp`).
25. [x] `close.py` models.tsv: read-modify-write now under `file_lock` + atomic write (was bare open/write). Note: `web.py` `_atomic_write_text` still does not take that lock.
26. [x] `files.write_text`: fsync before `os.replace`.
27. [x] `steward_quota.py`: `_parse_reset` returned/raised ValueError on bad day or Feb 29 rollover -> now None; `_num` rejects nan/inf. (The TODO's :123/:49 line numbers were stale; I fixed what the current code showed. Check against the original finding text.)
28. [x] 22 (SIGTERM tunnel) already done with its test.
29. [x] `py/tests/test_web_grpc_ucli_flags.py`: mapping test for 14 (flag round-trip tests skip until pb2 is regenerated).

## Resume point
Next: nothing open for the assistant. Owner: item 9 (also `tsc`, py tests: test_p2_atomic_writes, test_web_grpc_ucli_flags, test_web_sigterm_tunnel, test_web_orch_push_key, test_ucli_cost_watch), regenerate `host_bridge_pb2.py` (14). 15 has no UI work left: it needs ucli to record the service in the session record first.

## Done log
- friendlyError applied to 6 tabs; effort badge on ucli rows.
- ucli_flags backend + badges; mobile CSS block.
