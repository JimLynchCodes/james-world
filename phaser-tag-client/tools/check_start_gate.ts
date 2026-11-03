/**
 * Title → field start gate (instant enter vs "Starting…").
 *
 *   npx tsx --test tools/check_start_gate.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  canEnterField,
  optimisticSpawn,
  shouldShowStarting,
  type StartGateState,
} from "../src/startGate.ts";

const base: StartGateState = {
  connected: false,
  skinReady: false,
  startRequested: false,
  playing: false,
};

test("Start waits until the socket and skin are ready", () => {
  assert.equal(canEnterField(base), false);
  assert.equal(canEnterField({ ...base, connected: true }), false);
  assert.equal(canEnterField({ ...base, connected: true, skinReady: true }), true);
  assert.equal(canEnterField({ ...base, connected: true, skinReady: true, playing: true }), false);
});

test("Starting… only while Start is pending and not ready", () => {
  assert.equal(shouldShowStarting(base), false);
  assert.equal(shouldShowStarting({ ...base, startRequested: true }), true);
  assert.equal(
    shouldShowStarting({ ...base, startRequested: true, connected: true, skinReady: true }),
    false,
  );
  assert.equal(
    shouldShowStarting({
      ...base,
      startRequested: true,
      connected: true,
      skinReady: true,
      playing: true,
    }),
    false,
  );
});

test("optimistic spawn prefers the Welcome spot", () => {
  assert.deepEqual(
    optimisticSpawn({ welcomeX: 120, welcomeY: 340, fallbackX: 1, fallbackY: 2 }),
    { x: 120, y: 340 },
  );
  assert.deepEqual(
    optimisticSpawn({ welcomeX: null, welcomeY: null, fallbackX: 900, fallbackY: 700 }),
    { x: 900, y: 700 },
  );
  assert.deepEqual(
    optimisticSpawn({ welcomeX: Number.NaN, welcomeY: 10, fallbackX: 3, fallbackY: 4 }),
    { x: 3, y: 4 },
  );
});
