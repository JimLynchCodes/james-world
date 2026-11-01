/**
 * Walkable floor band spans most of the brawler screen; fight band is wide.
 *
 *   node --experimental-strip-types --test tools/check_brawler_lane.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { BRAWLER_LAYOUT } from "../src/brawlerLayout.ts";

test("lane covers most of world height, under HUD to bottom edge", () => {
  const { h, laneTop, laneBottom, groundY } = BRAWLER_LAYOUT;
  const span = laneBottom - laneTop;
  assert.ok(span >= h * 0.75, `lane span ${span} vs h ${h}`);
  assert.ok(laneTop <= 90, "lane top just under HUD/horizon");
  assert.ok(laneBottom + 30 >= h, "lane reaches near bottom edge");
  assert.ok(groundY > laneTop && groundY < laneBottom);
});

test("world size and fight band allow near-edge walk in camera view", () => {
  assert.ok(BRAWLER_LAYOUT.h >= 500);
  assert.ok(BRAWLER_LAYOUT.w >= 7000);
  assert.ok(
    BRAWLER_LAYOUT.fightWidth >= 900,
    "fight lock should span nearly a typical camera width",
  );
});
