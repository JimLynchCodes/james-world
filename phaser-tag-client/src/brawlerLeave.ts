/**
 * Pure helpers for the brawler → playground return path
 * (death flop, You-died popup, fade, win fade, and leave guard).
 */

export type BrawlerEnding = "none" | "dying" | "winning" | "done";

/** Death flop / fall-over length before the You-died popup appears. */
export const DEATH_ANIM_MS = 800;
/** How long the You-died popup stays up before the auto fade-out. */
export const DEATH_POPUP_HOLD_MS = 2500;
/** Fade-to-black duration after the popup (or Return click). */
export const DEATH_FADE_MS = 500;

/**
 * Start the local death sequence when we learn the local player is dead
 * and we have not already begun dying/winning.
 * Covers both the dedicated Died message and a snapshot that shows dead.
 */
export function shouldBeginDeath(opts: {
  isLocal: boolean;
  dead: boolean;
  ending: BrawlerEnding;
}): boolean {
  return opts.isLocal && opts.dead && opts.ending === "none";
}

/** Start the win sequence only once for a living local winner. */
export function shouldBeginWin(opts: {
  isLocalWinner: boolean;
  ending: BrawlerEnding;
}): boolean {
  return opts.isLocalWinner && opts.ending === "none";
}

/**
 * Leave the brawler at most once. `inBrawler` is the GameScene flag;
 * callers flip it false immediately after a successful leave.
 */
export function shouldLeaveBrawler(inBrawler: boolean): boolean {
  return inBrawler;
}

/** Keep the avatar visible during the death flop; hide once truly gone. */
export function shouldDrawBrawlerPeer(opts: {
  dead: boolean;
  ending: BrawlerEnding;
}): boolean {
  return !opts.dead || opts.ending === "dying";
}

export type DeathOverlayPhase = "anim" | "popup" | "fading" | "done";

export type DeathOverlayState = {
  phase: DeathOverlayPhase;
  showPopup: boolean;
  fadeAlpha: number;
};

/**
 * Death UI timeline.
 * - 0..animMs: flop only
 * - then popup until fade starts
 * - fade starts at animMs+holdMs, or immediately when Return is clicked (after anim)
 * - leave when fade finishes
 */
export function deathOverlayAt(opts: {
  elapsedMs: number;
  /** ms since beginDeath when Return was clicked; null if not clicked. */
  returnClickedAtMs: number | null;
  animMs?: number;
  popupHoldMs?: number;
  fadeMs?: number;
}): DeathOverlayState {
  const animMs = opts.animMs ?? DEATH_ANIM_MS;
  const holdMs = opts.popupHoldMs ?? DEATH_POPUP_HOLD_MS;
  const fadeMs = opts.fadeMs ?? DEATH_FADE_MS;
  const elapsed = Math.max(0, opts.elapsedMs);

  let fadeStart = animMs + holdMs;
  if (opts.returnClickedAtMs != null && opts.returnClickedAtMs >= animMs) {
    fadeStart = opts.returnClickedAtMs;
  } else if (opts.returnClickedAtMs != null && opts.returnClickedAtMs < animMs) {
    // Click before popup exists — start fading as soon as the flop ends.
    fadeStart = animMs;
  }

  if (elapsed < animMs) {
    return { phase: "anim", showPopup: false, fadeAlpha: 0 };
  }
  if (elapsed < fadeStart) {
    return { phase: "popup", showPopup: true, fadeAlpha: 0 };
  }
  const fadeT = fadeMs <= 0 ? 1 : (elapsed - fadeStart) / fadeMs;
  const fadeAlpha = Math.max(0, Math.min(1, fadeT));
  if (fadeAlpha >= 1) {
    return { phase: "done", showPopup: true, fadeAlpha: 1 };
  }
  return { phase: "fading", showPopup: true, fadeAlpha };
}
