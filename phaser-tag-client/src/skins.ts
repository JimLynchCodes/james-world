/**
 * Kid skins. All sheets share the same layout (30 columns: idle, walk,
 * breathing, tag, run; one row per direction), so the same animation code
 * drives every skin. Costume skins may be taller/wider (banana tip, trex
 * crest + tail), so each skin has its own frame size and feet line.
 *
 *   james  - public/assets/kid.png         (tools/slice_kid_sheet.py)
 *   banana - public/assets/kid_banana.png  (tools/make_banana_skin.py)
 *   trex   - public/assets/kid_trex.png    (tools/make_trex_skin.py)
 *   tuxedo - public/assets/kid_tuxedo.png  (tools/make_tuxedo_skin.py)
 *   pirate - public/assets/kid_pirate.png  (tools/make_pirate_skin.py)
 *   pharaoh - public/assets/kid_pharaoh.png (tools/make_pharaoh_skin.py)
 *   spaceman - public/assets/kid_spaceman.png (tools/make_spaceman_skin.py)
 *   wizard   - public/assets/kid_wizard.png   (tools/make_wizard_skin.py)
 *   centaur  - public/assets/kid_centaur.png + kid_centaur_b.png  (tools/make_centaur_skin.py)
 *   tennis   - public/assets/kid_tennis.png   (tools/make_tennis_skin.py)
 *   cobra    - public/assets/kid_cobra.png    (tools/make_cobra_skin.py)
 *   billy    - public/assets/kid_billy.png    (tools/make_billy_skin.py) - James's friend
 *   boxer   - public/assets/kid_boxer.png   (tools/make_boxer_skin.py)
 *
 * The id is what goes over the wire (`skin` in Join / SetSkin /
 * PlayerSnapshot). The server treats it as an opaque key (1-32 chars of
 * [a-z0-9_-], else "james") and relays it as-is, so a new skin is a
 * client-only change; clients that don't know a key draw the default kid.
 */
export type Skin = "james" | "banana" | "trex" | "tuxedo" | "pirate" | "pharaoh" | "spaceman" | "wizard" | "centaur" | "tennis" | "cobra" | "billy" | "boxer";

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
  /**
   * Sheets drawn finer than the James pixels. The game shows them at
   * 1/pixelScale so the character stays the same size, with linear filtering.
   */
  pixelScale?: number;
  /**
   * How many columns of the shared 30-column layout live in `url`.
   * Defaults to 30. The rest, when a single image would pass 4096px, are `extra`.
   */
  columns?: number;
  extra?: {
    texture: string;
    url: string;
    columns: number;
    /** First logical column stored in this second sheet. */
    columnStart: number;
  };
}

const BASE = import.meta.env.BASE_URL;

export const SKINS: Record<Skin, SkinSheet> = {
  james: {
    id: "james",
    label: "James",
    note: "Regular James",
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
    note: "Lickity Split!",
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
    label: "Dino James",
    note: "T-Rex Tag!",
    texture: "kid_trex",
    url: `${BASE}assets/kid_trex.png`,
    frameWidth: 120,
    frameHeight: 122,
    baselineY: 112,
    // crest + spikes sit ~108px above the feet; padded sides hold the tail
    artHeight: 118,
  },
  tuxedo: {
    id: "tuxedo",
    label: "Tuxedo James",
    note: "Dressed To Impress!",
    texture: "kid_tuxedo",
    url: `${BASE}assets/kid_tuxedo.png`,
    // a re-colour of the kid's own clothes: same frames and feet line
    frameWidth: 80,
    frameHeight: 100,
    baselineY: 96,
    artHeight: 90,
  },
  pirate: {
    id: "pirate",
    label: "Pirate James",
    note: "Arrr, You're It!",
    texture: "kid_pirate",
    url: `${BASE}assets/kid_pirate.png`,
    // padded: 20px each side for the cutlass, 12px on top for the tricorn
    frameWidth: 120,
    frameHeight: 112,
    baselineY: 108,
    // hat top ~96px above the feet (the feather a touch higher)
    artHeight: 96,
  },
  pharaoh: {
    id: "pharaoh",
    label: "Pharaoh James",
    note: "Walk Like An Egyptian!",
    texture: "kid_pharaoh",
    url: `${BASE}assets/kid_pharaoh.png`,
    // padded: 15px each side for the cape, 20px on top for the tall nemes crown.
    // 110×120 keeps the skins-card scale (1.2) on whole pixels.
    frameWidth: 110,
    frameHeight: 120,
    baselineY: 116,
    // striped crown tops out ~106px above the feet
    artHeight: 106,
  },
  spaceman: {
    id: "spaceman",
    label: "Spaceman James",
    note: "One small step...",
    texture: "kid_spaceman",
    url: `${BASE}assets/kid_spaceman.png`,
    // 2× James, in two textures so neither side passes 4096px. Drawn at 1/2.
    // The first sheet is idle, walk and breathe (columns 0–15). Tag and run
    // are kid_spaceman_b.png.
    frameWidth: 160,
    frameHeight: 200,
    baselineY: 192,
    artHeight: 186,
    pixelScale: 2,
    columns: 16,
    extra: {
      texture: "kid_spaceman_b",
      url: `${BASE}assets/kid_spaceman_b.png`,
      columns: 14,
      columnStart: 16,
    },
  },
  wizard: {
    id: "wizard",
    label: "Wizard James",
    note: "Tag-ulus Totalus!",
    texture: "kid_wizard",
    url: `${BASE}assets/kid_wizard.png`,
    // padded like the pirate: 20px each side for the wand, 12px on top for
    // the sparkle burst when the wand flicks up
    frameWidth: 120,
    frameHeight: 112,
    baselineY: 108,
    // same head as James: hair top ~90px above the feet
    artHeight: 90,
  },
  centaur: {
    id: "centaur",
    label: "Centaur James",
    note: "Four legs, zero chill!",
    texture: "kid_centaur",
    url: `${BASE}assets/kid_centaur.png`,
    // a whole horse under him: wide frames for the body and the tail, the
    // anchor is the middle of the horse on the ground
    frameWidth: 152,
    frameHeight: 150,
    baselineY: 134,
    // James's head rides on a horse: hair top ~118px above the hooves
    artHeight: 118,
    // two textures so neither side passes 4096px (mobile WebGL): idle, walk
    // and breathe here, tag and run in kid_centaur_b.png
    columns: 16,
    extra: {
      texture: "kid_centaur_b",
      url: `${BASE}assets/kid_centaur_b.png`,
      columns: 14,
      columnStart: 16,
    },
  },
  tennis: {
    id: "tennis",
    label: "Tennis James",
    note: "Forehand — you're it!",
    texture: "kid_tennis",
    url: `${BASE}assets/kid_tennis.png`,
    // padded 24px each side and 14px on top so the racket fits through the
    // whole forehand swing
    frameWidth: 128,
    frameHeight: 114,
    baselineY: 110,
    artHeight: 90,
  },
  cobra: {
    id: "cobra",
    label: "Cobra James",
    note: "Hiss-terically fast. You're it!",
    texture: "kid_cobra",
    url: `${BASE}assets/kid_cobra.png`,
    // wide frame for the hood, the trailing coils and the tag strike
    frameWidth: 136,
    frameHeight: 124,
    baselineY: 110,
    artHeight: 90,
  },
  billy: {
    id: "billy",
    label: "Billy",
    note: "James's Friend",
    texture: "kid_billy",
    url: `${BASE}assets/kid_billy.png`,
    // a grown-up on the kid rig: taller frame, iced coffee in hand
    frameWidth: 128,
    frameHeight: 124,
    baselineY: 118,
    artHeight: 103,
  },
  boxer: {
    id: "boxer",
    label: "Boxer James",
    note: "Float like a butterfly, tag like a bee.",
    texture: "kid_boxer",
    url: `${BASE}assets/kid_boxer.png`,
    // padded 28px each side and 10px on top so the jab glove fits
    frameWidth: 136,
    frameHeight: 110,
    baselineY: 106,
    artHeight: 90,
  },
};

export const SKIN_IDS = Object.keys(SKINS) as Skin[];

/** Normalise anything (old saves, server values) to a known skin. */
export function toSkin(value: unknown): Skin {
  return SKIN_IDS.includes(value as Skin) ? (value as Skin) : DEFAULT_SKIN;
}
