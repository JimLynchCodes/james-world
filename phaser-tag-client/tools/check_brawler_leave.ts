/**
 * Brawler → playground return path (death / win / leave guard / You-died popup).
 *
 *   npx tsx --test tools/check_brawler_leave.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEATH_ANIM_MS,
  DEATH_FADE_MS,
  DEATH_POPUP_HOLD_MS,
  deathOverlayAt,
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

test("You-died popup appears after the flop, then auto-fades home", () => {
  const midFlop = deathOverlayAt({ elapsedMs: DEATH_ANIM_MS / 2, returnClickedAtMs: null });
  assert.equal(midFlop.phase, "anim");
  assert.equal(midFlop.showPopup, false);
  assert.equal(midFlop.fadeAlpha, 0);

  const popup = deathOverlayAt({
    elapsedMs: DEATH_ANIM_MS + 100,
    returnClickedAtMs: null,
  });
  assert.equal(popup.phase, "popup");
  assert.equal(popup.showPopup, true);
  assert.equal(popup.fadeAlpha, 0);

  const fading = deathOverlayAt({
    elapsedMs: DEATH_ANIM_MS + DEATH_POPUP_HOLD_MS + DEATH_FADE_MS / 2,
    returnClickedAtMs: null,
  });
  assert.equal(fading.phase, "fading");
  assert.equal(fading.showPopup, true);
  assert.ok(fading.fadeAlpha > 0.4 && fading.fadeAlpha < 0.9);

  const done = deathOverlayAt({
    elapsedMs: DEATH_ANIM_MS + DEATH_POPUP_HOLD_MS + DEATH_FADE_MS + 10,
    returnClickedAtMs: null,
  });
  assert.equal(done.phase, "done");
  assert.equal(done.fadeAlpha, 1);
});

test("Return button skips the hold and fades out immediately", () => {
  const clickAt = DEATH_ANIM_MS + 200;
  const rightAfterClick = deathOverlayAt({
    elapsedMs: clickAt + 10,
    returnClickedAtMs: clickAt,
  });
  assert.equal(rightAfterClick.phase, "fading");
  assert.equal(rightAfterClick.showPopup, true);

  const afterFade = deathOverlayAt({
    elapsedMs: clickAt + DEATH_FADE_MS + 10,
    returnClickedAtMs: clickAt,
  });
  assert.equal(afterFade.phase, "done");
});

test("death then leave is a one-shot sequence including last-player death", () => {
  let ending: "none" | "dying" | "winning" | "done" = "none";
  let inBrawler = true;

  // Snapshot / Died for the local (and only) player.
  assert.equal(shouldBeginDeath({ isLocal: true, dead: true, ending }), true);
  ending = "dying";
  assert.equal(shouldDrawBrawlerPeer({ dead: true, ending }), true);

  const popup = deathOverlayAt({
    elapsedMs: DEATH_ANIM_MS + 50,
    returnClickedAtMs: null,
  });
  assert.equal(popup.showPopup, true);

  // Auto or button finishes → leave once (works when they were the last player).
  ending = "done";
  assert.equal(shouldLeaveBrawler(inBrawler), true);
  inBrawler = false;
  assert.equal(shouldLeaveBrawler(inBrawler), false);
  assert.equal(shouldBeginDeath({ isLocal: true, dead: true, ending }), false);
});
