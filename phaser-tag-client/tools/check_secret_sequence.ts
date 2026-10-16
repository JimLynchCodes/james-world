/**
 * Secret-tree sequence matcher.
 *
 *   node --experimental-strip-types --test tools/check_secret_sequence.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SecretSequence,
  SECRET_STEP_TIMEOUT_MS,
  nearSecretTree,
  pickSecretTree,
  predominantDirection,
  secretGate,
} from "../src/secretSequence.ts";

const bench = { x: 1300, y: 3900 };

test("exact tag tag tag left right tag completes once", () => {
  const seq = new SecretSequence();
  let t = 1000;
  assert.equal(seq.tag(t), false);
  assert.equal(seq.tag((t += 200)), false);
  assert.equal(seq.tag((t += 200)), false);
  assert.equal(seq.move("left", (t += 200)), false);
  assert.equal(seq.move("right", (t += 200)), false);
  assert.equal(seq.tag((t += 200)), true);
  assert.equal(seq.inProgress, false);
  // It does not stay completed; the next tag only starts it again.
  assert.equal(seq.tag(t + 200), false);
  assert.equal(seq.inProgress, true);
});

test("repeated left while held does not consume the right step", () => {
  const seq = new SecretSequence();
  seq.tag(0);
  seq.tag(100);
  seq.tag(200);
  seq.move("left", 300);
  seq.move("left", 350);
  seq.move("left", 400);
  assert.equal(seq.move("right", 500), false);
  assert.equal(seq.tag(600), true);
});

test("left released and pressed again is a second left and resets", () => {
  const seq = new SecretSequence();
  seq.tag(0);
  seq.tag(100);
  seq.tag(200);
  seq.move("left", 300);
  seq.move("none", 400);
  seq.move("left", 500); // wrong: expected right, sequence cleared
  assert.equal(seq.inProgress, false);
  assert.equal(seq.tag(600), false);
  assert.equal(seq.inProgress, true); // that tag started over
});

test("going straight from left to right counts as the right step", () => {
  const seq = new SecretSequence();
  seq.tag(0);
  seq.tag(50);
  seq.tag(100);
  seq.move("left", 150);
  assert.equal(seq.move("right", 200), false);
  assert.equal(seq.tag(250), true);
});

test("wrong input resets", () => {
  const seq = new SecretSequence();
  seq.tag(0);
  seq.tag(100);
  assert.equal(seq.move("right", 200), false);
  assert.equal(seq.inProgress, false);
  seq.tag(300);
  seq.tag(400);
  seq.tag(500);
  assert.equal(seq.move("other", 600), false);
  assert.equal(seq.inProgress, false);
});

test("a late step times out and does not finish the sequence", () => {
  const seq = new SecretSequence();
  seq.tag(0);
  seq.tag(100);
  seq.tag(200);
  const late = 200 + SECRET_STEP_TIMEOUT_MS + 50;
  assert.equal(seq.move("left", late), false);
  assert.equal(seq.inProgress, false);
  assert.equal(seq.tag(late + 10), false);
  assert.equal(seq.inProgress, true);
});

test("tag when left was expected restarts on that tag", () => {
  const seq = new SecretSequence();
  seq.tag(0);
  seq.tag(100);
  seq.tag(200);
  seq.tag(300); // not a left; counts as the first tag of a new attempt
  assert.equal(seq.inProgress, true);
  seq.tag(400);
  seq.tag(500);
  seq.move("left", 600);
  seq.move("right", 700);
  assert.equal(seq.tag(800), true);
});

test("predominant direction treats diagonals and deadzone", () => {
  assert.equal(predominantDirection(0, 0), "none");
  assert.equal(predominantDirection(0.1, -0.05), "none");
  assert.equal(predominantDirection(-1, 0), "left");
  assert.equal(predominantDirection(1, 0.2), "right");
  assert.equal(predominantDirection(-0.7, -0.4), "left");
  assert.equal(predominantDirection(0.4, 0.9), "other");
  assert.equal(predominantDirection(-0.5, 0.5), "left");
});

test("nearSecretTree covers the trunk and the canopy", () => {
  const tree = { x: 1400, y: 4000 };
  assert.equal(nearSecretTree(1400, 4000, tree), true);
  assert.equal(nearSecretTree(1480, 3960, tree), true);
  assert.equal(nearSecretTree(1400, 4000 - 70, tree), true);
  assert.equal(nearSecretTree(1400, 4300, tree), false);
  assert.equal(nearSecretTree(1800, 4000, tree), false);
});

test("pickSecretTree is the tree directly below the right bench", () => {
  const trees = [
    { id: "above", x: 1300, y: 3700 },
    { id: "far", x: 1900, y: 4000 },
    { id: "secret", x: 1415, y: 4053 },
    { id: "further-below", x: 1531, y: 4304 },
    { id: "left-bench", x: 700, y: 4100 },
  ];
  assert.equal(pickSecretTree(trees, bench)?.id, "secret");
});

test("gate ignores input away from the tree until a sequence is in progress", () => {
  const idle = secretGate({ awayAt: null }, false, false, 1000);
  assert.equal(idle.accept, false);
  assert.equal(idle.reset, false);

  const inside = secretGate({ awayAt: 5 }, true, true, 1000);
  assert.equal(inside.accept, true);
  assert.equal(inside.gate.awayAt, null);

  const grace = secretGate({ awayAt: null }, false, true, 1000);
  assert.equal(grace.accept, true);
  assert.equal(grace.reset, false);
  assert.equal(grace.gate.awayAt, 1000);

  const still = secretGate(grace.gate, false, true, 1000 + 400);
  assert.equal(still.accept, true);

  const expired = secretGate(grace.gate, false, true, 1000 + 800);
  assert.equal(expired.accept, false);
  assert.equal(expired.reset, true);
});
