/**
 * Pure helpers for the brawler → playground return path
 * (death fade, win fade, and leave guard).
 */

export type BrawlerEnding = "none" | "dying" | "winning" | "done";

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
