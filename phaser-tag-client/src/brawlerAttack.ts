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

/**
 * Restart the tag clip whenever the server begins a new swing (attack_seq bump),
 * including mid-animation chains when cooldown < duration.
 */
export function shouldRestartAttackAnim(opts: {
  attackSeq: number;
  wasAttackSeq: number;
  attacking: boolean;
}): boolean {
  return opts.attacking && opts.attackSeq > 0 && opts.attackSeq !== opts.wasAttackSeq;
}

/** Approximate tag clip length in seconds (must stay >= server ATTACK_COOLDOWN_S). */
export const TAG_ANIM_LENGTH_S = 0.355;

/** Keep in sync with server ATTACK_COOLDOWN_S / ATTACK_DURATION_S. */
export const BRAWLER_ATTACK_COOLDOWN_S = 0.22;
export const BRAWLER_ATTACK_DURATION_S = 0.32;
