/**
 * Rising-edge helpers for the co-op brawler attack / tag button.
 * One press → one swing; holding must never auto-repeat.
 */

/** Consume a one-shot pulse. Returns true exactly once per set. */
export function consumeAttackPulse(state: { pulse: boolean }): boolean {
  if (!state.pulse) return false;
  state.pulse = false;
  return true;
}

/** Fresh Space/T / Tag tap while in the brawler (ignores key-repeat and key-up). */
export function shouldQueueBrawlerAttack(opts: {
  inBrawler: boolean;
  phase: "down" | "up";
  repeat: boolean;
}): boolean {
  return opts.inBrawler && opts.phase === "down" && !opts.repeat;
}

/**
 * Start the local attack animation only when the server flag rises.
 * Snapshots that keep `attacking: true` after the clip ends must not re-trigger.
 */
export function shouldPlayAttackAnim(attacking: boolean, wasAttacking: boolean): boolean {
  return attacking && !wasAttacking;
}
