import { WORLD_HEIGHT, WORLD_WIDTH } from "./world.ts";

/**
 * Camera zoom as a slider level. 0 sits in the middle and is the game's
 * normal zoom (1x). Negative zooms out (more of the map, smaller sprites);
 * positive zooms in. The ends are half and double that normal view.
 */
export const ZOOM_LEVEL_MIN = -100;
export const ZOOM_LEVEL_MAX = 100;

/** One tap of Alt + an up/down zoom key. Holding the keys keeps going. */
export const ZOOM_KEY_STEP = 6;

/**
 * Alt + mouse wheel, in the same slider steps as the keys.
 * Pixel deltas (trackpads, and a typical desktop notch of ~100px) add up:
 * 100px moves the slider by one key step. A single event is capped at a
 * few notches so one wild trackpad flick can't slam the zoom to the end.
 * Line mode (Firefox's mouse wheel) treats one line as one notch.
 */
export const ZOOM_WHEEL_PX_PER_NOTCH = 100;
const ZOOM_WHEEL_MAX_NOTCHES = 3;

/**
 * Slider levels for one wheel event, before leftover accumulation.
 * Positive zooms in (wheel up, negative deltaY). Not a whole number for
 * a trackpad's small pixel ticks — the caller keeps the fraction.
 */
export function zoomLevelsFromWheel(deltaY: number, deltaMode = 0): number {
  if (!Number.isFinite(deltaY) || deltaY === 0) return 0;
  // 0 pixels, 1 lines, 2 pages. Page mode is rare; treat it as the cap.
  const pixels =
    deltaMode === 1 ? deltaY * ZOOM_WHEEL_PX_PER_NOTCH
    : deltaMode === 2 ? Math.sign(deltaY) * ZOOM_WHEEL_MAX_NOTCHES * ZOOM_WHEEL_PX_PER_NOTCH
    : deltaY;
  const notches = Math.min(ZOOM_WHEEL_MAX_NOTCHES, Math.abs(pixels) / ZOOM_WHEEL_PX_PER_NOTCH);
  const sign = pixels > 0 ? -1 : 1;
  return sign * notches * ZOOM_KEY_STEP;
}

/**
 * Turn a running fraction of slider levels into whole steps.
 * The leftover stays so trackpad ticks smaller than one level still add up,
 * and reversing direction spends that fraction before stepping back.
 */
export function takeWheelLevels(
  remainder: number,
  delta: number
): { levels: number; remainder: number } {
  const carry = Number.isFinite(remainder) ? remainder : 0;
  if (!Number.isFinite(delta) || delta === 0) return { levels: 0, remainder: carry };
  const sum = carry + delta;
  // trunc(-0.4) is -0, and -0 === 0, but strict checks and JSON keep the sign.
  const levels = Math.trunc(sum) || 0;
  return { levels, remainder: sum - levels };
}

export function clampLevel(level: number): number {
  if (!Number.isFinite(level)) return 0;
  return Math.round(Math.min(ZOOM_LEVEL_MAX, Math.max(ZOOM_LEVEL_MIN, level)));
}

/** Level -100..100 → zoom 0.5x..2x, with 0 at 1x. Each step is the same ratio. */
export function zoomFromLevel(level: number): number {
  return 2 ** (clampLevel(level) / 100);
}

export function levelFromZoom(zoom: number): number {
  if (!Number.isFinite(zoom) || zoom <= 0) return 0;
  const clamped = Math.min(2, Math.max(0.5, zoom));
  return clampLevel(Math.round(Math.log2(clamped) * 100));
}

/**
 * Keep the camera inside the world. The visible area is screen / zoom, so
 * zooming out too far on a large display would show the dark margin past
 * the map. 0.5x still fits a normal window; a very wide one stops early.
 */
export function clampZoom(zoom: number, viewWidth: number, viewHeight: number): number {
  const wanted = Math.min(2, Math.max(0.5, Number.isFinite(zoom) && zoom > 0 ? zoom : 1));
  if (!(viewWidth > 0) || !(viewHeight > 0)) return wanted;
  // A couple of pixels inside the world so a rounding seam never shows.
  const minFit = Math.max((viewWidth + 2) / WORLD_WIDTH, (viewHeight + 2) / WORLD_HEIGHT);
  const minZoom = Math.min(2, Math.max(0.5, minFit));
  return Math.min(2, Math.max(minZoom, wanted));
}

/** Slider level that the camera can actually show on this view. */
export function effectiveLevel(level: number, viewWidth: number, viewHeight: number): number {
  return levelFromZoom(clampZoom(zoomFromLevel(level), viewWidth, viewHeight));
}

/** 0 at the out end, 50 in the middle, 100 at the in end. */
export function zoomTrackPercent(level: number): number {
  const span = ZOOM_LEVEL_MAX - ZOOM_LEVEL_MIN;
  return ((clampLevel(level) - ZOOM_LEVEL_MIN) / span) * 100;
}
