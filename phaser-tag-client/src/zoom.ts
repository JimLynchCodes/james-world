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
