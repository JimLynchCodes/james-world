/**
 * One attack per fresh tag press in the brawler (no hold-repeat, no snapshot re-fire).
 *
 *   node --experimental-strip-types --test tools/check_brawler_attack.ts
 *   # or: npx tsx --test tools/check_brawler_attack.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  consumeAttackPulse,
  shouldPlayAttackAnim,
  shouldQueueBrawlerAttack,
} from "../src/brawlerAttack.ts";

test("fresh press queues; key-repeat and key-up do not", () => {
  assert.equal(
    shouldQueueBrawlerAttack({ inBrawler: true, phase: "down", repeat: false }),
    true,
  );
  assert.equal(
    shouldQueueBrawlerAttack({ inBrawler: true, phase: "down", repeat: true }),
    false,
  );
  assert.equal(
    shouldQueueBrawlerAttack({ inBrawler: true, phase: "up", repeat: false }),
    false,
  );
  assert.equal(
    shouldQueueBrawlerAttack({ inBrawler: false, phase: "down", repeat: false }),
    false,
  );
});

test("pulse is consumed once — holding cannot auto-repeat", () => {
  const state = { pulse: false };
  assert.equal(consumeAttackPulse(state), false);

  state.pulse = true;
  assert.equal(consumeAttackPulse(state), true);
  assert.equal(consumeAttackPulse(state), false);
  assert.equal(consumeAttackPulse(state), false);

  state.pulse = true;
  assert.equal(consumeAttackPulse(state), true);
  assert.equal(consumeAttackPulse(state), false);
});

test("attack anim only on rising edge of server attacking flag", () => {
  assert.equal(shouldPlayAttackAnim(true, false), true);
  assert.equal(shouldPlayAttackAnim(true, true), false);
  assert.equal(shouldPlayAttackAnim(false, true), false);
  assert.equal(shouldPlayAttackAnim(false, false), false);

  let was = false;
  const frames = [false, true, true, true, false, false, true];
  const plays: boolean[] = [];
  for (const attacking of frames) {
    plays.push(shouldPlayAttackAnim(attacking, was));
    was = attacking;
  }
  assert.deepEqual(plays, [false, true, false, false, false, false, true]);
});
