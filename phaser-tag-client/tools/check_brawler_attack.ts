/**
 * One attack per fresh tag press in the brawler (no hold-repeat, no snapshot re-fire).
 * Cooldown must not exceed the tag anim; seq bumps restart the clip.
 *
 *   node --experimental-strip-types --test tools/check_brawler_attack.ts
 *   # or: npx tsx --test tools/check_brawler_attack.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BRAWLER_ATTACK_COOLDOWN_S,
  BRAWLER_ATTACK_DURATION_S,
  TAG_ANIM_LENGTH_S,
  consumeAttackPulse,
  shouldPlayAttackAnim,
  shouldQueueBrawlerAttack,
  shouldRestartAttackAnim,
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

test("cooldown is at most anim length and shorter than duration for chaining", () => {
  assert.ok(
    BRAWLER_ATTACK_COOLDOWN_S <= TAG_ANIM_LENGTH_S,
    `cooldown ${BRAWLER_ATTACK_COOLDOWN_S} > anim ${TAG_ANIM_LENGTH_S}`,
  );
  assert.ok(
    BRAWLER_ATTACK_COOLDOWN_S <= BRAWLER_ATTACK_DURATION_S,
    `cooldown ${BRAWLER_ATTACK_COOLDOWN_S} > duration ${BRAWLER_ATTACK_DURATION_S}`,
  );
});

test("attack_seq bump restarts anim even while already attacking", () => {
  assert.equal(
    shouldRestartAttackAnim({ attackSeq: 1, wasAttackSeq: 0, attacking: true }),
    true,
  );
  assert.equal(
    shouldRestartAttackAnim({ attackSeq: 1, wasAttackSeq: 1, attacking: true }),
    false,
  );
  assert.equal(
    shouldRestartAttackAnim({ attackSeq: 2, wasAttackSeq: 1, attacking: true }),
    true,
  );
  assert.equal(
    shouldRestartAttackAnim({ attackSeq: 2, wasAttackSeq: 1, attacking: false }),
    false,
  );
  // Simulate rapid chain: attacking stays true, seq bumps each swing.
  let wasSeq = 0;
  const swings = [
    { seq: 1, attacking: true },
    { seq: 1, attacking: true },
    { seq: 2, attacking: true },
    { seq: 2, attacking: true },
    { seq: 3, attacking: true },
  ];
  const restarts: boolean[] = [];
  for (const s of swings) {
    restarts.push(
      shouldRestartAttackAnim({
        attackSeq: s.seq,
        wasAttackSeq: wasSeq,
        attacking: s.attacking,
      }),
    );
    wasSeq = s.seq;
  }
  assert.deepEqual(restarts, [true, false, true, false, true]);
});
