/**
 * Brawler → playground return path (death / win / leave guard).
 *
 *   node --experimental-strip-types --test tools/check_brawler_leave.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  shouldBeginDeath,
  shouldBeginWin,
  shouldDrawBrawlerPeer,
  shouldLeaveBrawler,
} from "../src/brawlerLeave.ts";

test("death starts once from Died message or dead snapshot", () => {
  assert.equal(
    shouldBeginDeath({ isLocal: true, dead: true, ending: "none" }),
    true,
  );
  assert.equal(
    shouldBeginDeath({ isLocal: true, dead: true, ending: "dying" }),
    false,
  );
  assert.equal(
    shouldBeginDeath({ isLocal: true, dead: true, ending: "done" }),
    false,
  );
  assert.equal(
    shouldBeginDeath({ isLocal: false, dead: true, ending: "none" }),
    false,
  );
  assert.equal(
    shouldBeginDeath({ isLocal: true, dead: false, ending: "none" }),
    false,
  );
});

test("win starts once for a local winner", () => {
  assert.equal(shouldBeginWin({ isLocalWinner: true, ending: "none" }), true);
  assert.equal(shouldBeginWin({ isLocalWinner: true, ending: "winning" }), false);
  assert.equal(shouldBeginWin({ isLocalWinner: false, ending: "none" }), false);
});

test("leave runs only while still marked in-brawler", () => {
  assert.equal(shouldLeaveBrawler(true), true);
  assert.equal(shouldLeaveBrawler(false), false);
});

test("dead peer stays drawn during dying flop, hidden otherwise", () => {
  assert.equal(shouldDrawBrawlerPeer({ dead: true, ending: "dying" }), true);
  assert.equal(shouldDrawBrawlerPeer({ dead: true, ending: "none" }), false);
  assert.equal(shouldDrawBrawlerPeer({ dead: false, ending: "none" }), true);
  assert.equal(shouldDrawBrawlerPeer({ dead: true, ending: "done" }), false);
});

test("death then leave is a one-shot sequence", () => {
  let ending: "none" | "dying" | "winning" | "done" = "none";
  let inBrawler = true;

  // Snapshot arrives with dead:true (or Died message) → begin death.
  assert.equal(shouldBeginDeath({ isLocal: true, dead: true, ending }), true);
  ending = "dying";
  assert.equal(shouldDrawBrawlerPeer({ dead: true, ending }), true);

  // Fade completes → leave once.
  ending = "done";
  assert.equal(shouldLeaveBrawler(inBrawler), true);
  inBrawler = false;
  assert.equal(shouldLeaveBrawler(inBrawler), false);

  // A late snapshot must not restart death or leave.
  assert.equal(shouldBeginDeath({ isLocal: true, dead: true, ending }), false);
});
