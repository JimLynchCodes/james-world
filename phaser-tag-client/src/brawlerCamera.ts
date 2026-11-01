/**
 * Arcade beat-'em-up camera helpers (Simpsons / TMNT style).
 * Pure functions — easy to unit-test without Phaser.
 */

export type CamPlayer = { x: number; y: number; dead?: boolean };

export type CameraLock = {
  /** Never scroll the view left of this world x (cleared progress fence). */
  scrollMin: number;
  lockLeft: number | null;
  lockRight: number | null;
  worldW: number;
  viewW: number;
  /** Vertical center of the playfield (lane mid). */
  viewCenterY: number;
};

export type CameraTarget = { x: number; y: number };

/**
 * Focus on the living group's centroid. Falls back to `fallbackX` when alone/empty.
 * Biases slightly ahead (to the right) so the fight reads in front of the team.
 */
export function groupFocusX(players: CamPlayer[], fallbackX: number, leadBias = 40): number {
  const living = players.filter(p => !p.dead);
  if (living.length === 0) return fallbackX;
  const sum = living.reduce((s, p) => s + p.x, 0);
  const mean = sum / living.length;
  const lead = living.reduce((m, p) => Math.max(m, p.x), -Infinity);
  // Blend mean with lead so stragglers don't yank the camera left hard.
  return mean * 0.55 + lead * 0.45 + leadBias;
}

export function groupFocusY(players: CamPlayer[], fallbackY: number): number {
  const living = players.filter(p => !p.dead);
  if (living.length === 0) return fallbackY;
  return living.reduce((s, p) => s + p.y, 0) / living.length;
}

/**
 * Soft deadzone: if the focus is within `deadzone` of the current camera center,
 * keep the current center (avoids micro-jitter).
 */
export function applyDeadzone(current: number, focus: number, deadzone: number): number {
  if (Math.abs(focus - current) <= deadzone) return current;
  // Pull only the excess past the deadzone edge (arcade feel).
  return focus > current ? focus - deadzone : focus + deadzone;
}

/**
 * Clamp a desired camera *center* so the view stays inside the world and
 * respects scroll_min + optional fight lock band.
 */
export function clampCameraCenterX(desired: number, lock: CameraLock): number {
  const half = lock.viewW / 2;
  let minCenter = lock.scrollMin + half;
  let maxCenter = lock.worldW - half;

  if (lock.lockLeft != null && lock.lockRight != null) {
    const lockMin = lock.lockLeft + half;
    const lockMax = lock.lockRight - half;
    if (lockMax >= lockMin) {
      minCenter = Math.max(minCenter, lockMin);
      maxCenter = Math.min(maxCenter, lockMax);
    } else {
      // View wider than the lock band — pin to the band midpoint.
      return (lock.lockLeft + lock.lockRight) / 2;
    }
  }

  if (maxCenter < minCenter) return (minCenter + maxCenter) / 2;
  return Math.min(maxCenter, Math.max(minCenter, desired));
}

/** Frame-rate independent lerp. `rate` ≈ fraction toward target per second. */
export function lerpCamera(current: number, target: number, dtSec: number, rate = 6): number {
  const t = 1 - Math.exp(-rate * Math.max(0, dtSec));
  return current + (target - current) * t;
}

/**
 * One-shot camera step used by the brawler scene each frame.
 */
export function stepBrawlerCamera(opts: {
  currentX: number;
  currentY: number;
  players: CamPlayer[];
  fallbackX: number;
  fallbackY: number;
  lock: CameraLock;
  dtSec: number;
  deadzoneX?: number;
  rate?: number;
}): { x: number; y: number } {
  const focusX = groupFocusX(opts.players, opts.fallbackX);
  const focusY = groupFocusY(opts.players, opts.fallbackY);
  const dz = opts.deadzoneX ?? 36;
  const softened = applyDeadzone(opts.currentX, focusX, dz);
  const clamped = clampCameraCenterX(softened, opts.lock);
  const x = lerpCamera(opts.currentX, clamped, opts.dtSec, opts.rate ?? 6.5);
  // Keep Y mostly on the lane; gentle drift toward group.
  const yTarget = opts.lock.viewCenterY * 0.85 + focusY * 0.15;
  const y = lerpCamera(opts.currentY, yTarget, opts.dtSec, 4);
  return { x, y };
}

/** Parallax tile offsets from camera scroll (scrollX = center - viewW/2). */
export function parallaxOffsets(camCenterX: number, viewW: number): {
  far: number;
  mid: number;
  near: number;
} {
  const scrollX = camCenterX - viewW / 2;
  return {
    far: scrollX * 0.15,
    mid: scrollX * 0.4,
    near: scrollX * 0.75,
  };
}
