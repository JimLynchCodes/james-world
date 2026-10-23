/**
 * Camera zoom slider: 0 is the middle (1x), ends are 0.5x and 2x, and the
 * view never grows past the world.
 *
 *   node --experimental-strip-types --test tools/check_zoom.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { WORLD_HEIGHT, WORLD_WIDTH } from "../src/world.ts";
import {
  ZOOM_KEY_STEP,
  clampZoom,
  effectiveLevel,
  levelFromZoom,
  takeWheelLevels,
  zoomFromLevel,
  zoomLevelsFromWheel,
  zoomTrackPercent,
} from "../src/zoom.ts";

test("0 is 1x and the ends are half and double", () => {
  assert.equal(zoomFromLevel(0), 1);
  assert.equal(zoomFromLevel(-100), 0.5);
  assert.equal(zoomFromLevel(100), 2);
  assert.equal(levelFromZoom(1), 0);
  assert.equal(levelFromZoom(0.5), -100);
  assert.equal(levelFromZoom(2), 100);
  assert.equal(zoomTrackPercent(0), 50);
  assert.equal(zoomTrackPercent(-100), 0);
  assert.equal(zoomTrackPercent(100), 100);
});

test("a normal window can zoom out to 0.5x without leaving the world", () => {
  const zoom = clampZoom(0.5, 1280, 720);
  assert.equal(zoom, 0.5);
  assert.ok(1280 / zoom < WORLD_WIDTH);
  assert.ok(720 / zoom < WORLD_HEIGHT);
});

test("Alt + wheel up zooms in and wheel down zooms out, in key-sized steps", () => {
  assert.equal(zoomLevelsFromWheel(-100, 0), ZOOM_KEY_STEP);
  assert.equal(zoomLevelsFromWheel(100, 0), -ZOOM_KEY_STEP);
  assert.equal(zoomLevelsFromWheel(-50, 0), ZOOM_KEY_STEP / 2);
  // A trackpad flick larger than a few notches is capped.
  assert.equal(zoomLevelsFromWheel(-800, 0), 3 * ZOOM_KEY_STEP);
  assert.equal(zoomLevelsFromWheel(0, 0), 0);
  assert.equal(zoomLevelsFromWheel(Number.NaN, 0), 0);
});

test("line-mode wheels count as notches, and trackpad fractions add up", () => {
  assert.equal(zoomLevelsFromWheel(-1, 1), ZOOM_KEY_STEP);
  assert.equal(zoomLevelsFromWheel(3, 1), -3 * ZOOM_KEY_STEP);
  assert.equal(zoomLevelsFromWheel(1, 2), -3 * ZOOM_KEY_STEP);

  let carry = takeWheelLevels(0, zoomLevelsFromWheel(-10, 0));
  assert.equal(carry.levels, 0);
  assert.ok(carry.remainder > 0);
  carry = takeWheelLevels(carry.remainder, zoomLevelsFromWheel(-10, 0));
  assert.equal(carry.levels, 1);
  // Reversing spends the leftover before a whole step the other way.
  const back = takeWheelLevels(carry.remainder, zoomLevelsFromWheel(10, 0));
  assert.equal(back.levels, 0);
  assert.ok(back.remainder < carry.remainder);
});

test("a very wide view stops before the dark margin past the map", () => {
  const viewW = 4000;
  const zoom = clampZoom(0.5, viewW, 1000);
  assert.ok(zoom > 0.5);
  assert.ok(viewW / zoom <= WORLD_WIDTH);
  assert.equal(effectiveLevel(-100, viewW, 1000), levelFromZoom(zoom));
  assert.equal(effectiveLevel(0, viewW, 1000), 0);
});
