/**
 * Hidden tree quest: the input sequence and which tree it belongs to.
 *
 * The sequence is tag, tag, tag, left, right, tag. Movement steps are
 * direction edges (a hold, or a stream of the same direction, is one step).
 * Callers map keyboard, joystick, and tap-to-move onto these steps.
 */

export type SecretStep = "tag" | "left" | "right";

/** A movement sample. "other" is a predominantly vertical input (wrong). */
export type MoveDir = "left" | "right" | "other" | "none";

export const SECRET_SEQUENCE: readonly SecretStep[] = ["tag", "tag", "tag", "left", "right", "tag"];

/** Silence longer than this between accepted steps resets the sequence. */
export const SECRET_STEP_TIMEOUT_MS = 4500;

/**
 * After the sequence has started, stepping just outside the tree still
 * accepts input for this long so a short left/right shuffle can finish.
 */
export const SECRET_LEAVE_GRACE_MS = 700;

/**
 * How close a player centre must be to count as standing in the secret tree.
 * Covers the trunk footprint and the canopy, with a little extra so a kid
 * overlapping the leaves still counts.
 */
export const SECRET_TREE_RADIUS = 108;

/** Minimum |axis| before a movement sample counts as a direction. */
const MOVE_DEADZONE = 0.22;

export function predominantDirection(dx: number, dy: number): MoveDir {
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  if (ax < MOVE_DEADZONE && ay < MOVE_DEADZONE) return "none";
  if (ax >= ay && ax >= MOVE_DEADZONE) return dx < 0 ? "left" : "right";
  if (ay > ax && ay >= MOVE_DEADZONE) return "other";
  return "none";
}

/**
 * True when the player is overlapping the trunk or the canopy.
 * `tree` is the prop's ground point (the image anchor).
 */
export function nearSecretTree(px: number, py: number, tree: { x: number; y: number }): boolean {
  if (Math.hypot(px - tree.x, py - tree.y) <= SECRET_TREE_RADIUS) return true;
  // Canopy disk sits above the trunk (see schoolyard treeTexture).
  const canopyY = tree.y - 70;
  return Math.hypot(px - tree.x, py - canopyY) <= 78;
}

export type SecretGate = {
  /** scene time when the player left the tree mid-sequence, or null */
  awayAt: number | null;
};

/**
 * Whether the next sample should be fed to the matcher.
 * `reset` means the grace expired and the sequence should be cleared.
 */
export function secretGate(
  gate: SecretGate,
  near: boolean,
  inProgress: boolean,
  now: number,
  grace = SECRET_LEAVE_GRACE_MS
): { accept: boolean; reset: boolean; gate: SecretGate } {
  if (near) return { accept: true, reset: false, gate: { awayAt: null } };
  if (!inProgress) return { accept: false, reset: false, gate: { awayAt: null } };
  const awayAt = gate.awayAt ?? now;
  if (now - awayAt > grace) return { accept: false, reset: true, gate: { awayAt: null } };
  return { accept: true, reset: false, gate: { awayAt } };
}

/**
 * The tree directly below a bench: south of it, not far to the side, closest.
 * Used for the right-hand bench under the baseball diamond.
 */
export function pickSecretTree<T extends { x: number; y: number }>(
  trees: readonly T[],
  bench: { x: number; y: number }
): T | null {
  let best: T | null = null;
  let bestD = Infinity;
  for (const tree of trees) {
    if (tree.y < bench.y + 24) continue;
    if (Math.abs(tree.x - bench.x) > 280) continue;
    const d = Math.hypot(tree.x - bench.x, tree.y - bench.y);
    if (d < bestD) {
      best = tree;
      bestD = d;
    }
  }
  return best;
}

export class SecretSequence {
  private index = 0;
  private lastAt = 0;
  private held: MoveDir = "none";

  get inProgress(): boolean {
    return this.index > 0;
  }

  reset() {
    this.index = 0;
    this.lastAt = 0;
    this.held = "none";
  }

  /** A fresh tag press (not a key repeat). True when the full sequence completes. */
  tag(now: number): boolean {
    return this.push("tag", now);
  }

  /**
   * One movement sample. Holding the same direction, or repeating it while
   * it stays held, counts as a single step. Releasing (none) arms the next
   * press. A new left / right / vertical edge is one step.
   */
  move(dir: MoveDir, now: number): boolean {
    if (dir === "none") {
      this.held = "none";
      return false;
    }
    if (dir === this.held) return false;
    this.held = dir;
    if (dir === "other") return this.reject(now);
    return this.push(dir, now);
  }

  private reject(now: number): boolean {
    this.index = 0;
    this.lastAt = now;
    return false;
  }

  private push(step: SecretStep, now: number): boolean {
    if (this.index > 0 && now - this.lastAt > SECRET_STEP_TIMEOUT_MS) {
      this.index = 0;
    }
    const expect = SECRET_SEQUENCE[this.index];
    if (step !== expect) {
      this.index = 0;
      // A tag that isn't the expected step can start the sequence over.
      if (step !== SECRET_SEQUENCE[0]) return false;
    }
    this.index += 1;
    this.lastAt = now;
    if (this.index >= SECRET_SEQUENCE.length) {
      this.reset();
      return true;
    }
    return false;
  }
}
