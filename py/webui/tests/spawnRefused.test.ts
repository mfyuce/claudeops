/** node --experimental-strip-types --test py/webui/tests/spawnRefused.test.ts (module has type-only imports). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { describeSpawnRefused } from "../src/api/spawnRefused.ts";

test("known codes are localized and keep the raw code", () => {
  assert.match(describeSpawnRefused("login_required:codex", "", "tr"), /codex için önce.*\nlogin_required:codex$/s);
  assert.match(describeSpawnRefused("quota_sessions", "3/3", "en"), /concurrent session limit.*\nquota_sessions: 3\/3$/s);
  assert.match(describeSpawnRefused("quota_usd_day", "", "en"), /daily spend/);
  assert.match(describeSpawnRefused("quota_new_thing", "", "tr"), /kotan doldu/);
});
test("corrupt owner record explains the repair, with the session name", () => {
  assert.match(describeSpawnRefused("ownership_corrupt", "s1", "tr"), /sahip kaydı bozuk.*yönetici.*\nownership_corrupt: s1$/s);
  assert.match(describeSpawnRefused("ownership_corrupt", "s1", "en"), /owner record is corrupt.*administrator.*\nownership_corrupt: s1$/s);
});
test("corrupt owner record message also covers a refused reassignment (document corrupt)", () => {
  assert.match(describeSpawnRefused("ownership_corrupt", "s1", "tr"), /atama da reddedilirse.*elle onarılmalı/);
  assert.match(describeSpawnRefused("ownership_corrupt", "s1", "en"), /assignment is refused too.*repaired by hand/);
});
test("unknown code falls back to raw", () => {
  assert.equal(describeSpawnRefused("weird", "x", "en"), "weird: x");
  assert.equal(describeSpawnRefused("weird", "", "en"), "weird");
});
