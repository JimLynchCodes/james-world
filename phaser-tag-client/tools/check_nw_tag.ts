/**
 * Walk + tag northwest must select the tag clip (james and pharaoh), and a
 * Space tap that is released before the scene update must still count.
 *
 *   node --experimental-strip-types --test tools/check_nw_tag.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyPhysicalKey,
  avatarAnimKey,
  directionFromAngle,
  latchTagPress,
  movementAxes,
  noteTagKey,
} from "../src/tagging.ts";

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

const SKINS = ["kid", "kid_pharaoh", "kid_banana", "kid_trex", "kid_tuxedo", "kid_pirate"] as const;

test("arrow up+left and WASD northwest are the same axes", () => {
  assert.deepEqual(movementAxes(new Set(["ArrowUp", "ArrowLeft"])), movementAxes(new Set(["KeyW", "KeyA"])));
  const { dx, dy, running } = movementAxes(new Set(["ArrowUp", "ArrowLeft"]));
  assert.equal(dx, -1);
  assert.equal(dy, -1);
  assert.equal(running, false);
});

test("arrow keyup in the same step does not drop a keyCode-less space tap", () => {
  // Phaser indexes Key objects by keyCode. Space often arrives here as
  // code "Space" with keyCode 0 while ArrowUp/ArrowLeft still carry 38/37,
  // so the cursor-key path walked and the Space Key latch never fired.
  let held = new Set<string>();
  let queued = false;
  const step = (
    phase: "down" | "up",
    event: { code?: string; key?: string; keyCode?: number; repeat?: boolean }
  ) => {
    held = applyPhysicalKey(held, event, phase);
    queued = noteTagKey(queued, event, phase);
  };
  step("down", { code: "ArrowUp", keyCode: 38 });
  step("down", { code: "ArrowLeft", keyCode: 37 });
  step("up", { code: "ArrowUp", keyCode: 38 });
  step("down", { code: "Space", key: " ", keyCode: 0 });
  step("up", { code: "Space", key: " ", keyCode: 0 });
  step("down", { code: "ArrowUp", keyCode: 0 });
  const { dx, dy, running } = movementAxes(held);
  assert.equal(queued, true);
  assert.equal(dx, -1);
  assert.equal(dy, -1);
  const angle = Math.atan2(dy, dx);
  for (const texture of SKINS) {
    assert.equal(avatarAnimKey(texture, angle, true, running, queued), `${texture}-tag-NW`);
  }
  assert.equal(noteTagKey(true, { code: "ArrowLeft", keyCode: 37 }, "up"), true);
  assert.equal(noteTagKey(false, { code: "Space", keyCode: 0, repeat: true }, "down"), false);
  assert.equal(movementAxes(applyPhysicalKey(new Set(), { key: "ArrowUp", keyCode: 0 }, "down")).dy, -1);
});
