/**
 * Pure helpers for the brawler life bar and hit feedback.
 * Keeps HUD math out of the Phaser scene so checks can pin the behaviour.
 */

export const HP_FILL_W = 196;
export const HP_FILL_H = 14;

/** Arcade life-bar colours: green → yellow → red as HP drops. */
export function hpBarColor(ratio: number): number {
  if (ratio > 0.45) return 0x33cc55;
  if (ratio > 0.2) return 0xe6c200;
  return 0xcc3344;
}

/** Clamp hp/max into a 0..1 fill ratio. */
export function hpBarRatio(hp: number, maxHp: number): number {
  if (!(maxHp > 0) || !Number.isFinite(hp) || !Number.isFinite(maxHp)) return 0;
  return Math.max(0, Math.min(1, hp / maxHp));
}

/** Pixel width of the fill for a given ratio (never collapses to 0 while alive-ish). */
export function hpBarFillWidth(ratio: number, fullWidth = HP_FILL_W): number {
  if (ratio <= 0) return 0;
  return Math.max(2, fullWidth * ratio);
}

/** True when the local player just took damage (HP dropped). */
export function shouldFlashHit(prevHp: number, nextHp: number): boolean {
  return Number.isFinite(prevHp) && Number.isFinite(nextHp) && nextHp < prevHp - 0.01;
}

/**
 * Ease displayed HP toward the authoritative value.
 * `rate` is roughly "fraction of the gap closed per second" (higher = snappier).
 */
export function smoothHpStep(displayed: number, target: number, dtSec: number, rate = 14): number {
  if (!Number.isFinite(displayed)) return target;
  if (!Number.isFinite(target)) return displayed;
  if (dtSec <= 0) return displayed;
  // Damage snaps faster than healing so hits feel immediate.
  const catchUp = target < displayed ? rate * 1.8 : rate;
  const t = 1 - Math.exp(-catchUp * dtSec);
  return displayed + (target - displayed) * t;
}
