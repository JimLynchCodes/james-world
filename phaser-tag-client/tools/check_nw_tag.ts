/**
 * Walk + tag northwest must select the tag clip (james and pharaoh), and a
 * Space tap that is released before the scene update must still count.
 *
 *   node --experimental-strip-types --test tools/check_nw_tag.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { avatarAnimKey, directionFromAngle, latchTagPress } from "../src/tagging.ts";

const DIRS: [number, number, string][] = [
  [1, 0, "E"],
  [1, 1, "SE"],
  [0, 1, "S"],
  [-1, 1, "SW"],
  [-1, 0, "W"],
  [-1, -1, "NW"],
  [0, -1, "N"],
  [1, -1, "NE"],
];

test("exact northwest angle is the NW row", () => {
  assert.equal(directionFromAngle(Math.atan2(-1, -1)), "NW");
  assert.equal(directionFromAngle((-3 * Math.PI) / 4), "NW");
});

test("walk+tag northwest plays the tag clip for james and pharaoh", () => {
  const angle = Math.atan2(-1, -1);
  for (const texture of ["kid", "kid_pharaoh"]) {
    assert.equal(avatarAnimKey(texture, angle, true, false, true), `${texture}-tag-NW`);
    assert.equal(avatarAnimKey(texture, angle, true, true, true), `${texture}-tag-NW`);
  }
});

test("walk+tag in every direction plays that direction's tag clip", () => {
  for (const [dx, dy, dir] of DIRS) {
    const angle = Math.atan2(dy, dx);
    for (const texture of ["kid", "kid_pharaoh"]) {
      assert.equal(avatarAnimKey(texture, angle, true, false, true), `${texture}-tag-${dir}`);
      assert.equal(avatarAnimKey(texture, angle, true, false, false), `${texture}-walk-${dir}`);
    }
  }
});

test("space keyup does not swallow a same-step tag press", () => {
  let queued = false;
  queued = latchTagPress(queued, "down");
  queued = latchTagPress(queued, "up");
  assert.equal(queued, true);
  assert.equal(latchTagPress(false, "up"), false);
});
