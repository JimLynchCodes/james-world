/**
 * Kid skins. All sheets share the same layout (30 columns: idle, walk,
 * breathing, tag, run; one row per direction), so the same animation code
 * drives every skin. Costume skins may be taller/wider (banana tip, trex
 * crest + tail), so each skin has its own frame size and feet line.
 *
 *   james  - public/assets/kid.png         (tools/slice_kid_sheet.py)
 *   banana - public/assets/kid_banana.png  (tools/make_banana_skin.py)
 *   trex   - public/assets/kid_trex.png    (tools/make_trex_skin.py)
 *
 * The id is what goes over the wire (`skin` in Join / SetSkin /
 * PlayerSnapshot); the server falls back to "james" for unknown values.
 */
export type Skin = "james" | "banana" | "trex";

export const DEFAULT_SKIN: Skin = "james";

export interface SkinSheet {
  id: Skin;
  label: string;
  /** Short note under the skins-tab card (footstep flavour, default, …). */
  note: string;
  /** Phaser texture key, also the animation key prefix. */
  texture: string;
  url: string;
  frameWidth: number;
  frameHeight: number;
  /** Feet rest on this row of every frame. */
  baselineY: number;
  /** Height of the art above the feet (top of hair / costume), frame px. */
  artHeight: number;
}

const BASE = import.meta.env.BASE_URL;

export const SKINS: Record<Skin, SkinSheet> = {
  james: {
    id: "james",
    label: "James",
    note: "Default",
    texture: "kid",
    url: `${BASE}assets/kid.png`,
    frameWidth: 80,
    frameHeight: 100,
    baselineY: 96,
    artHeight: 90,
  },
  banana: {
    id: "banana",
    label: "Banana James",
    note: "Squeaky shoes",
    texture: "kid_banana",
    url: `${BASE}assets/kid_banana.png`,
    frameWidth: 80,
    frameHeight: 120,
    baselineY: 116,
    // the stem tops out ~110px above the feet; let the name label tuck in
    // a little over it so the stack doesn't float
    artHeight: 107,
  },
  trex: {
    id: "trex",
    label: "T-rex James",
    note: "Scary stomps",
    texture: "kid_trex",
    url: `${BASE}assets/kid_trex.png`,
    frameWidth: 120,
    frameHeight: 122,
    baselineY: 112,
    // crest + spikes sit ~108px above the feet; padded sides hold the tail
    artHeight: 108,
  },
};

export const SKIN_IDS = Object.keys(SKINS) as Skin[];

/** Normalise anything (old saves, server values) to a known skin. */
export function toSkin(value: unknown): Skin {
  return SKIN_IDS.includes(value as Skin) ? (value as Skin) : DEFAULT_SKIN;
}
