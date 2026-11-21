/**
 * Pure tab-grouping logic (state/tabs.ts). The webui has no test runner configured; this file uses node:test and is
 * NOT part of the tsc project (src only). Run (Node >= 22.6): node --experimental-strip-types --test py/webui/tests/tabGroups.test.ts
 * (state/tabs.ts has no imports, so strip-types works). Not run in the session that wrote it.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { entryTabFor, groupOf, topTabOf, visibleSubs } from "../src/state/tabs.ts";

test("legacy keys map to their group", () => {
  for (const k of ["ucli", "team", "steward", "desktop", "readlist"]) assert.equal(groupOf(k), "tools");
  for (const k of ["settings", "snapshots", "diag", "metrics"]) assert.equal(groupOf(k), "settings");
  for (const k of ["running", "registered", "disabled", "retired", "history", "ext:admin"]) assert.equal(groupOf(k), null);
});

test("top-level highlight", () => {
  assert.equal(topTabOf("diag"), "settings");
  assert.equal(topTabOf("steward"), "tools");
  assert.equal(topTabOf("history"), "history");
  assert.equal(topTabOf("ext:admin"), "ext:admin");
});

test("restricted view keeps ucli only, hides settings group", () => {
  assert.deepEqual(visibleSubs("tools", { restricted: true, hasReadlist: true }), ["ucli"]);
  assert.deepEqual(visibleSubs("settings", { restricted: true }), []);
});

test("readlist only with the extension route", () => {
  assert.deepEqual(visibleSubs("tools", {}), ["ucli", "team", "steward", "desktop"]);
  assert.deepEqual(visibleSubs("tools", { hasReadlist: true }), ["ucli", "team", "steward", "desktop", "readlist"]);
  assert.deepEqual(visibleSubs("settings", {}), ["settings", "snapshots", "diag", "metrics"]);
});

test("entry tab: remembered sub, else first visible", () => {
  assert.equal(entryTabFor("tools", {}, "steward"), "steward");
  assert.equal(entryTabFor("tools", {}, "readlist"), "ucli");
  assert.equal(entryTabFor("tools", { restricted: true }, "steward"), "ucli");
  assert.equal(entryTabFor("settings", {}, null), "settings");
  assert.equal(entryTabFor("settings", { restricted: true }, null), null);
});

test("extension sub-tabs (group tools/settings) join the group row (C2)", () => {
  const extSubs = { tools: ["ext:apps"], settings: ["ext:cfg"] };
  assert.equal(groupOf("ext:apps", extSubs), "tools");
  assert.equal(groupOf("ext:cfg", extSubs), "settings");
  assert.equal(groupOf("ext:admin", extSubs), null);
  assert.equal(topTabOf("ext:apps", extSubs), "tools");
  assert.deepEqual(visibleSubs("tools", { extSubs }), ["ucli", "team", "steward", "desktop", "ext:apps"]);
  assert.deepEqual(visibleSubs("tools", { restricted: true, extSubs }), ["ucli", "ext:apps"]);
  assert.equal(entryTabFor("tools", { extSubs }, "ext:apps"), "ext:apps");
  assert.equal(entryTabFor("tools", {}, "ext:apps"), "ucli");
});
