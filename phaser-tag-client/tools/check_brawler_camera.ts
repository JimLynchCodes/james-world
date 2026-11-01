/**
 * Brawler arcade camera: group focus, deadzone, lock, scroll_min, parallax.
 *
 *   node --experimental-strip-types --test tools/check_brawler_camera.ts
 *   # or: npx tsx --test tools/check_brawler_camera.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyDeadzone,
  clampCameraCenterX,
  groupFocusX,
  lerpCamera,
  parallaxOffsets,
  stepBrawlerCamera,
} from "../src/brawlerCamera.ts";

test("group focus blends mean and lead, biases forward", () => {
  const x = groupFocusX(
    [
      { x: 100, y: 200 },
      { x: 200, y: 200 },
    ],
    0,
    40,
  );
  // mean=150, lead=200 → 150*0.55+200*0.45+40 = 82.5+90+40 = 212.5
  assert.ok(x > 200 && x < 230);
});

test("deadzone suppresses micro jitter", () => {
  assert.equal(applyDeadzone(100, 110, 20), 100);
  assert.equal(applyDeadzone(100, 130, 20), 110);
  assert.equal(applyDeadzone(100, 70, 20), 90);
});

test("clamp respects scroll_min and fight lock", () => {
  const base = {
    scrollMin: 0,
    lockLeft: null as number | null,
    lockRight: null as number | null,
    worldW: 7000,
    viewW: 640,
    viewCenterY: 180,
  };
  assert.equal(clampCameraCenterX(100, base), 320); // half view
  assert.equal(clampCameraCenterX(8000, base), 7000 - 320);

  const locked = { ...base, lockLeft: 300, lockRight: 660 };
  // View 640, band 360 → pin to midpoint
  assert.equal(clampCameraCenterX(500, locked), 480);

  const wide = { ...base, viewW: 200, lockLeft: 300, lockRight: 700, scrollMin: 250 };
  // half=100; minCenter=max(250+100, 300+100)=400; maxCenter=min(7000-100,700-100)=600
  assert.equal(clampCameraCenterX(350, wide), 400);
  assert.equal(clampCameraCenterX(550, wide), 550);
  assert.equal(clampCameraCenterX(800, wide), 600);
});

test("lerp moves toward target without overshooting on small dt", () => {
  const a = lerpCamera(0, 100, 0.016, 6);
  assert.ok(a > 0 && a < 20);
  const b = lerpCamera(0, 100, 10, 6);
  assert.ok(b > 99);
});

test("step never scrolls left of scroll_min and stays in lock", () => {
  const out = stepBrawlerCamera({
    currentX: 500,
    currentY: 180,
    players: [{ x: 100, y: 200 }], // would pull left hard
    fallbackX: 100,
    fallbackY: 200,
    lock: {
      scrollMin: 400,
      lockLeft: 400,
      lockRight: 760,
      worldW: 7000,
      viewW: 640,
      viewCenterY: 180,
    },
    dtSec: 1,
    deadzoneX: 0,
    rate: 20,
  });
  // half=320; lock band 360 wide → pin ~580; scrollMin forces minCenter >= 720? 
  // lockMin = 400+320=720, lockMax=760-320=440 → lockMax < lockMin → midpoint (400+760)/2 = 580
  assert.ok(Math.abs(out.x - 580) < 0.01);
});

test("parallax far < mid < near", () => {
  const o = parallaxOffsets(1000, 640);
  assert.ok(o.far < o.mid && o.mid < o.near);
});
