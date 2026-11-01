/**
 * Brawler life bar + hit flash helpers.
 *
 *   npx tsx --test tools/check_brawler_hud.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HP_FILL_W,
  hpBarColor,
  hpBarFillWidth,
  hpBarRatio,
  shouldFlashHit,
  smoothHpStep,
} from "../src/brawlerHud.ts";

test("hp ratio clamps and scales against max", () => {
  assert.equal(hpBarRatio(100, 100), 1);
  assert.equal(hpBarRatio(50, 100), 0.5);
  assert.equal(hpBarRatio(0, 100), 0);
  assert.equal(hpBarRatio(-10, 100), 0);
  assert.equal(hpBarRatio(100, 0), 0);
  assert.equal(hpBarRatio(Number.NaN, 100), 0);
});

test("fill width shrinks with HP and collapses at zero", () => {
  assert.equal(hpBarFillWidth(1), HP_FILL_W);
  assert.equal(hpBarFillWidth(0.5), HP_FILL_W * 0.5);
  assert.equal(hpBarFillWidth(0), 0);
  assert.ok(hpBarFillWidth(0.01) >= 2);
});

test("bar turns yellow then red as HP gets low", () => {
  assert.equal(hpBarColor(1), 0x33cc55);
  assert.equal(hpBarColor(0.5), 0x33cc55);
  assert.equal(hpBarColor(0.4), 0xe6c200);
  assert.equal(hpBarColor(0.1), 0xcc3344);
});

test("hit flash only when HP drops", () => {
  assert.equal(shouldFlashHit(100, 92), true);
  assert.equal(shouldFlashHit(92, 92), false);
  assert.equal(shouldFlashHit(80, 90), false);
  assert.equal(shouldFlashHit(Number.NaN, 50), false);
});

test("smoothed HP catches down quickly after a hit", () => {
  let shown = 100;
  shown = smoothHpStep(shown, 84, 1 / 30);
  assert.ok(shown < 100 && shown > 84, `expected mid value, got ${shown}`);
  for (let i = 0; i < 40; i++) shown = smoothHpStep(shown, 84, 1 / 30);
  assert.ok(Math.abs(shown - 84) < 0.05, `should settle near 84, got ${shown}`);
});
