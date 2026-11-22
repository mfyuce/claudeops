import assert from "node:assert/strict";
import { test } from "node:test";
import { fieldSuggestions, matchesSearch, matchesText } from "../src/components/shared/searchFilter.ts";

const row = { name: "wg_zk_pqs", cwd: "/home/x/wg", model: "claude-opus-4", cli: "claude", host: "ulak_31" };

test("field terms: substring, wildcard, AND, folding", () => {
  assert.ok(matchesSearch(row, "model:opus"));
  assert.ok(matchesSearch(row, "model:claude-opus*"));
  assert.ok(!matchesSearch(row, "model:opus*")); // wildcard anchors the whole field
  assert.ok(matchesSearch(row, "cli:claude host:ULAK_31"));
  assert.ok(!matchesSearch(row, "cli:agy"));
  assert.ok(matchesSearch(row, "path:/home/x model:opus wg_zk"));
});

test("unknown prefix stays free text; matchesText keeps field words as text", () => {
  assert.ok(!matchesSearch(row, "foo:bar"));
  assert.ok(matchesText(["model:opus here"], "model:opus"));
});

test("field name suggestions", () => {
  assert.deepEqual(fieldSuggestions("mo"), ["model:"]);
  assert.deepEqual(fieldSuggestions("cli:agy mo"), ["model:"]);
  assert.deepEqual(fieldSuggestions("model:o"), []);
  assert.deepEqual(fieldSuggestions(""), []);
});
