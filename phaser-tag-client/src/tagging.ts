/**
 * Facing and tag-input decisions shared by the avatar and the tests.
 *
 * Directions are the sprite-sheet rows: clockwise from east, y down.
 * `directionFromAngle` uses atan2(dy, dx) in screen coordinates.
 */

export const DIRECTIONS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"] as const;
export type Direction = (typeof DIRECTIONS)[number];

/** Map a facing angle in radians (atan2(dy, dx), screen coords) to a direction. */
export function directionFromAngle(angle: number): Direction {
  const octant = Math.round(angle / (Math.PI / 4));
  return DIRECTIONS[((octant % 8) + 8) % 8];
}

/**
 * Clip the avatar should show. A tag swing wins over walk / run, including
 * while the kid is still moving — northwest included.
 */
export function avatarAnimKey(
  texture: string,
  angle: number,
  moving: boolean,
  running: boolean,
  tagging: boolean
): string {
  const dir = directionFromAngle(angle);
  const name = tagging ? "tag" : moving ? (running ? "run" : "walk") : "breathe";
  return `${texture}-${name}-${dir}`;
}

/**
 * Space went down or up since the last scene step.
 *
 * Phaser's JustDown misses a tap whose keyup is processed in the same step
 * as the keydown: Key.onUp clears `_justDown` before the scene reads it, so
 * the swing never starts (no animation, no sound). Up+Left+Space is the
 * chord that often arrives as that same-step blip. Remember the keydown;
 * keyup must not forget it.
 */
export function latchTagPress(queued: boolean, event: "down" | "up"): boolean {
  if (event === "down") return true;
  return queued;
}
