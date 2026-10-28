/**
 * Opaque cosmetic keys (same idea as Skin). The server relays whatever we
 * send; unknown values become "none". Only "crown" is drawn client-side today.
 */
import type { Skin } from "./skins";

export type Cosmetic = "none" | "crown";

export const DEFAULT_COSMETIC: Cosmetic = "none";
export const CROWN: Cosmetic = "crown";

const STORAGE_KEY = "james-world.cosmetic";

export function toCosmetic(value: unknown): Cosmetic {
  if (value === "crown") return "crown";
  return "none";
}

export function loadSavedCosmetic(): Cosmetic {
  try {
    return toCosmetic(localStorage.getItem(STORAGE_KEY));
  } catch {
    return DEFAULT_COSMETIC;
  }
}

export function saveCosmetic(cosmetic: Cosmetic) {
  try {
    if (cosmetic === "none") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, cosmetic);
  } catch {
    // private mode / quota — ignore
  }
}

/**
 * Extra world-pixel lift so the crown clears tall hair / hoods / spikes.
 * Positive moves the crown up (away from the feet).
 */
export function crownLiftPx(skin: Skin): number {
  switch (skin) {
    case "pharaoh":
      return 10;
    case "cobra":
      return 14;
    case "billy":
      return 12;
    case "wizard":
      return 8;
    case "spaceman":
      return 6;
    case "centaur":
      return 4;
    case "trex":
      return 2;
    default:
      return 4;
  }
}
