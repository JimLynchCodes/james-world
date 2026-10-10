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

/** Tag clip for a facing angle. Movement does not choose this row. */
export function tagClipKey(texture: string, facing: number): string {
  return `${texture}-tag-${directionFromAngle(facing)}`;
}

/**
 * Clip to show this frame. A tag swing stays on the facing it started with
 * for the whole clip, even if the kid is walking or turning.
 */
export function nextAvatarAnim(opts: {
  texture: string;
  facing: number;
  moving: boolean;
  running: boolean;
  tagging: boolean;
  /** Facing locked when the swing started. */
  tagFacing?: number | null;
}): string {
  if (opts.tagging) return tagClipKey(opts.texture, opts.tagFacing ?? opts.facing);
  return avatarAnimKey(opts.texture, opts.facing, opts.moving, opts.running, false);
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

/**
 * Codes that steer or tag. Arrows and WASD share the movement set.
 * Tag is Space or T (KeyT / keyCode 84). Phaser indexes each Key by
 * `keyCode`: cursor keys for the arrows, and the Space Key (keyCode 32) for
 * the old latch. A Space event whose `keyCode` is 0 still has `code: "Space"`,
 * so that latch never ran, while ArrowUp/ArrowLeft (keyCodes 38/37) kept the
 * walk going. WASD+Space kept working when that Space event still carried
 * keyCode 32. T is the other tag key when a keyboard drops Space in an
 * arrow chord.
 */
const GAME_CODES = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "KeyW",
  "KeyA",
  "KeyS",
  "KeyD",
  "ShiftLeft",
  "ShiftRight",
  "Shift",
  "Space",
  "KeyT",
]);

/** `KeyboardEvent.key` when `code` was left blank. */
const FROM_KEY: Readonly<Record<string, string>> = {
  ArrowUp: "ArrowUp",
  ArrowDown: "ArrowDown",
  ArrowLeft: "ArrowLeft",
  ArrowRight: "ArrowRight",
  w: "KeyW",
  W: "KeyW",
  a: "KeyA",
  A: "KeyA",
  s: "KeyS",
  S: "KeyS",
  d: "KeyD",
  D: "KeyD",
  t: "KeyT",
  T: "KeyT",
  Shift: "Shift",
};

const CODE_FROM_KEYCODE: Readonly<Record<number, string>> = {
  32: "Space",
  84: "KeyT",
  37: "ArrowLeft",
  38: "ArrowUp",
  39: "ArrowRight",
  40: "ArrowDown",
  65: "KeyA",
  68: "KeyD",
  83: "KeyS",
  87: "KeyW",
  16: "Shift",
};

export type DomKeyEvent = {
  code?: string;
  key?: string;
  keyCode?: number;
  repeat?: boolean;
};

/** Physical key, preferring `code` so a missing `keyCode` still counts. */
export function physicalCode(event: DomKeyEvent): string | null {
  if (event.code && GAME_CODES.has(event.code)) return event.code;
  if (event.key === " " || event.key === "Spacebar") return "Space";
  if (event.key && FROM_KEY[event.key]) return FROM_KEY[event.key];
  if (event.keyCode && CODE_FROM_KEYCODE[event.keyCode]) return CODE_FROM_KEYCODE[event.keyCode];
  return null;
}

/** Space and T both tag. Either code reaches the same latch. */
export function isTagKey(event: DomKeyEvent): boolean {
  const code = physicalCode(event);
  return code === "Space" || code === "KeyT";
}

/**
 * Remember a tag press. Arrow (or WASD) keyup in the same step must not
 * clear it: only Space and T are consulted, and their keyup keeps the press.
 * Repeats are ignored so holding either key doesn't swing every key-repeat.
 */
export function noteTagKey(queued: boolean, event: DomKeyEvent, phase: "down" | "up"): boolean {
  if (!isTagKey(event)) return queued;
  if (phase === "down" && event.repeat) return queued;
  return latchTagPress(queued, phase);
}

/** Movement from the physical keys currently held. Arrows and WASD share this. */
export function movementAxes(held: ReadonlySet<string>): { dx: number; dy: number; running: boolean } {
  let dx = 0;
  let dy = 0;
  if (held.has("ArrowLeft") || held.has("KeyA")) dx -= 1;
  if (held.has("ArrowRight") || held.has("KeyD")) dx += 1;
  if (held.has("ArrowUp") || held.has("KeyW")) dy -= 1;
  if (held.has("ArrowDown") || held.has("KeyS")) dy += 1;
  const running =
    (held.has("ShiftLeft") || held.has("ShiftRight") || held.has("Shift")) && (dx !== 0 || dy !== 0);
  return { dx, dy, running };
}

/** Track a movement key. Space and T are not movement keys; the tag latch handles them. */
export function applyPhysicalKey(
  held: ReadonlySet<string>,
  event: DomKeyEvent,
  phase: "down" | "up"
): Set<string> {
  const code = physicalCode(event);
  if (!code || code === "Space" || code === "KeyT") return new Set(held);
  const next = new Set(held);
  if (phase === "down") next.add(code);
  else next.delete(code);
  return next;
}
