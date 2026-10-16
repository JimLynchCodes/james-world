/**
 * Secret cave. Original pixel room (not ripped tiles): black floor, rocky
 * brown walls, an old man in a red robe between two flickering fires, a
 * sword on the floor, and a door gap in the bottom wall.
 *
 * The player is locked until the two-line message finishes revealing.
 * Walls, both fires, and the old man are solid. The sword is not: touching
 * it opens a full-screen blue error page. Walking out the bottom door, or
 * dismissing that page, returns to the schoolyard.
 */
import Phaser from "phaser";
import type { GameAudio } from "./audio";
import { KidAvatar } from "./kid";
import type { ControlMode } from "./settings";
import { SKINS, type Skin } from "./skins";

export const CAVE = {
  w: 256,
  h: 180,
  wall: 20,
  doorW: 40,
  /** Player collision radius in cave pixels. */
  playerR: 9,
} as const;

/** A bit under full-bleed so the cave reads as a room, not a close-up. */
const CAVE_ZOOM = 0.86;
/** Kid height as a fraction of the room. Small enough to stand under the sword. */
const PLAYER_ROOM_FRACTION = 0.11;

const DOOR_X = (CAVE.w - CAVE.doorW) / 2;

export type CaveRect = { x: number; y: number; w: number; h: number };

/** Feet for the man and the fires; sword x/y is the sprite center. */
const MAN = { x: 128, y: 84, w: 18, h: 22 };
const FIRE_L = { x: 74, y: 86, w: 14, h: 14 };
const FIRE_R = { x: 182, y: 86, w: 14, h: 14 };
const SWORD = { x: 128, y: 104, w: 20, h: 14 };
/** Feet in the bottom doorway, well below the sword. */
const SPAWN = { x: CAVE.w / 2, y: CAVE.h - 24 };

/** Solid rectangles in cave pixels (the sword is deliberately not here). */
export function caveSolids(): CaveRect[] {
  const { w, h, wall, doorW } = CAVE;
  const doorX = (w - doorW) / 2;
  return [
    { x: 0, y: 0, w, h: wall },
    { x: 0, y: 0, w: wall, h },
    { x: w - wall, y: 0, w: wall, h },
    { x: 0, y: h - wall, w: doorX, h: wall },
    { x: doorX + doorW, y: h - wall, w: w - (doorX + doorW), h: wall },
    { x: MAN.x - MAN.w / 2, y: MAN.y - MAN.h, w: MAN.w, h: MAN.h },
    { x: FIRE_L.x - FIRE_L.w / 2, y: FIRE_L.y - FIRE_L.h, w: FIRE_L.w, h: FIRE_L.h },
    { x: FIRE_R.x - FIRE_R.w / 2, y: FIRE_R.y - FIRE_R.h, w: FIRE_R.w, h: FIRE_R.h },
  ];
}

export function caveSword(): CaveRect {
  return {
    x: SWORD.x - SWORD.w / 2 - 1,
    y: SWORD.y - SWORD.h / 2 - 1,
    w: SWORD.w + 2,
    h: SWORD.h + 2,
  };
}

export type DungeonHooks = {
  skin: Skin;
  readMove: () => { dx: number; dy: number; mode: ControlMode };
  audio: GameAudio | null;
  onExit: () => void;
};

const LINES = ["MASTER USING IT AND", "YOU CAN HAVE THIS."] as const;
const GLYPH_W = 5;
const GLYPH_H = 7;
const GLYPH_GAP = 1;
const LETTER_MS = 78;
const SPACE_MS = 42;
const LINE_PAUSE_MS = 320;

/** 5x7 chunky glyphs. '1' is ink. */
const FONT: Record<string, readonly string[]> = {
  A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
  C: ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
  D: ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
  E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
  G: ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
  H: ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
  I: ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
  M: ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
  N: ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
  O: ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
  R: ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
  S: ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
  T: ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
  U: ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
  V: ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
  Y: ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
  ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
  " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
};

const OLD_MAN = [
  "......WW..........WW......",
  ".....WWW..........WWW.....",
  "......W.PPPPPPPP.W........",
  ".....W.PPPPPPPPPP.W.......",
  ".....W.PP.EEEE.PP.W.......",
  ".....W.PPPPPPPPPP.W.......",
  "......W.WWWWWWWW.W........",
  ".......WWWWWWWWWW.........",
  "......WWWWWWWWWWWW........",
  "...ooo............ooo.....",
  "..oooo.oooooooooo.oooo....",
  "..ooo.OOOOOOOOOOOO.ooo....",
  "......OOOOOOOOOOOO........",
  ".....rRRRRRRRRRRRRr.......",
  "....rRRRRRRRRRRRRRRr......",
  "...rRRRRRRRRRRRRRRRRr.....",
  "..rRRRRRRRRRRRRRRRRRRr....",
  "..RRRRRRRRRRRRRRRRRRRR....",
  ".RRRRRRRRRRRRRRRRRRRRRR...",
  ".RRRrRRRRRRRRRRRRrRRRRR...",
  "..RRRRRRRRRRRRRRRRRRRR....",
  "...RRRRRRRRRRRRRRRRRR.....",
  "....RRRR........RRRR......",
  "....DDDD........DDDD......",
  ".....DD..........DD.......",
];

const FIRE_A = [
  ".......yy.......",
  "......yYYy......",
  ".....yYOOYy.....",
  "....yyOOOOyy....",
  "...yOOORROOYy...",
  "..yOOORRRROOYy..",
  "..OOORRRRRRROO..",
  ".oOORRRRRRRRROo.",
  ".oORRRRRRRRRRRo.",
  "..RRRRRRRRRRRR..",
  "...RRRRRRRRRR...",
  "....RRRRRRRR....",
  ".....RRRRRR.....",
  "......RRRR......",
  ".......RR.......",
];

const FIRE_B = [
  "........yy......",
  ".......yYYy.....",
  "......yYOOYy....",
  ".....yyOOOOyy...",
  "....yOOORROOyy..",
  "...yOORRRRRROy..",
  "..oOORRRRRRROo..",
  "..oORRRRRRRRRo..",
  "...RRRRRRRRRR...",
  "....RRRRRRRRR...",
  ".....RRRRRRR....",
  "......RRRRR.....",
  ".......RRR......",
  "........R.......",
  "................",
];

/** Blade points up-left; the hilt sits down-right. Rows stay the same width. */
const SWORD_ART = [
  "WW..................",
  "WWW.................",
  ".WWW................",
  "..WWW...............",
  "...WWW..............",
  "....WWW.............",
  ".....WWW............",
  "......WWW...........",
  ".......oGGG.........",
  "........GGGo........",
  ".........HHH........",
  "..........HHH.......",
  "...........HH.......",
  "............H.......",
];

type RGB = [number, number, number];

const INK: Record<string, RGB | null> = {
  ".": null,
  " ": null,
  P: [244, 190, 142],
  E: [28, 16, 14],
  W: [250, 250, 246],
  R: [186, 32, 32],
  r: [214, 48, 36],
  O: [228, 104, 32],
  o: [246, 156, 56],
  D: [92, 46, 26],
  y: [255, 246, 190],
  Y: [255, 214, 72],
  G: [196, 108, 40],
  H: [112, 58, 28],
};

const BSOD_TEXT = `A problem has been detected and James World has been shut down to prevent damage
to your computer.

Error: Quest Not Implemented.

If this is the first time you've seen this Stop error screen,
restart your computer. If this screen appears again, follow
these steps:

Check to make sure any new hardware or software is properly installed.
If this is a new installation, ask your hardware or software manufacturer
for any James World updates you might need.

If problems continue, disable or remove any newly installed hardware
or software. Disable BIOS memory options such as caching or shadowing.
If you need to use Safe Mode to remove or disable components, restart
your computer, press F8 to select Advanced Startup Options, and then
select Safe Mode.

Technical information:

*** STOP: 0x0000007B (0xC0000034, 0x00000000, 0x00000000, 0x00000000)


Press any key or tap to continue `;

function hash(x: number, y: number): number {
  let n = (x * 374761393 + y * 668265263) | 0;
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return (n ^ (n >>> 16)) >>> 0;
}

function blit(
  ctx: CanvasRenderingContext2D,
  rows: readonly string[],
  x: number,
  y: number,
  palette: Record<string, RGB | null> = INK
) {
  rows.forEach((row, iy) => {
    for (let ix = 0; ix < row.length; ix++) {
      const rgb = palette[row[ix]];
      if (!rgb) continue;
      ctx.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
      ctx.fillRect(x + ix, y + iy, 1, 1);
    }
  });
}

function circleHits(x: number, y: number, r: number, rect: CaveRect): boolean {
  const cx = Math.max(rect.x, Math.min(x, rect.x + rect.w));
  const cy = Math.max(rect.y, Math.min(y, rect.y + rect.h));
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy < r * r;
}

function makeCanvas(scene: Phaser.Scene, key: string, w: number, h: number, draw: (ctx: CanvasRenderingContext2D) => void) {
  const existing = scene.textures.exists(key) ? (scene.textures.get(key) as Phaser.Textures.CanvasTexture) : null;
  const tex = existing ?? scene.textures.createCanvas(key, w, h);
  if (!tex) throw new Error(`could not create texture ${key}`);
  const ctx = tex.getContext();
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, tex.width, tex.height);
  draw(ctx);
  tex.refresh();
  tex.setFilter(Phaser.Textures.FilterMode.NEAREST);
  return tex;
}

function paintArt(scene: Phaser.Scene, key: string, rows: readonly string[]) {
  const w = Math.max(...rows.map(row => row.length));
  const h = rows.length;
  return makeCanvas(scene, key, w, h, ctx => {
    rows.forEach((row, iy) => blit(ctx, [row], Math.floor((w - row.length) / 2), iy));
  });
}

function drawRocks(ctx: CanvasRenderingContext2D) {
  const { w, h, wall } = CAVE;
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, w, h);
  const stones: RGB[] = [
    [122, 76, 42],
    [98, 60, 32],
    [146, 94, 52],
    [78, 48, 26],
    [164, 110, 62],
    [88, 54, 30],
  ];
  const inWall = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= w || y >= h) return false;
    const outer = x < wall || y < wall || x >= w - wall || y >= h - wall;
    if (!outer) return false;
    if (y >= h - wall && x >= DOOR_X && x < DOOR_X + CAVE.doorW) return false;
    return true;
  };
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!inWall(x, y)) continue;
      const sx = Math.floor(x / 5);
      const sy = Math.floor(y / 4);
      const base = stones[hash(sx, sy) % stones.length];
      let shade = 0;
      if (x % 5 === 0 || y % 4 === 0) shade = -32;
      else if (x % 5 === 1 || y % 4 === 1) shade = 22;
      else if (x % 5 === 4 || y % 4 === 3) shade = -16;
      if (hash(x, y) % 19 === 0) shade -= 18;
      const inner = x === wall || y === wall || x === w - wall - 1 || (y === h - wall - 1 && (x < DOOR_X || x >= DOOR_X + CAVE.doorW));
      if (inner) shade -= 24;
      const jamb = y >= h - wall && (x === DOOR_X - 1 || x === DOOR_X + CAVE.doorW);
      if (jamb) shade += 28;
      const r = Math.max(0, Math.min(255, base[0] + shade));
      const g = Math.max(0, Math.min(255, base[1] + shade));
      const b = Math.max(0, Math.min(255, base[2] + Math.round(shade * 0.7)));
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(x, y, 1, 1);
    }
  }
}

function glyphWidth(text: string): number {
  if (text.length === 0) return 0;
  return text.length * (GLYPH_W + GLYPH_GAP) - GLYPH_GAP;
}

export class SecretDungeonScene extends Phaser.Scene {
  private hooks!: DungeonHooks;
  private avatar: KidAvatar | null = null;
  private roomImage!: Phaser.GameObjects.Image;
  private textImage!: Phaser.GameObjects.Image;
  private textTex!: Phaser.Textures.CanvasTexture;
  private man!: Phaser.GameObjects.Image;
  private sword!: Phaser.GameObjects.Image;
  private fires: Phaser.GameObjects.Image[] = [];
  private solids: CaveRect[] = caveSolids();
  private fit = { scale: 1, ox: 0, oy: 0 };
  /** Feet, in cave pixels. */
  private lx = SPAWN.x;
  private ly = SPAWN.y;
  private facing = -Math.PI / 2;
  private revealed = 0;
  private nextRevealAt = 0;
  private locked = true;
  private startedAt = 0;
  private tapTarget: { x: number; y: number } | null = null;
  private left = false;
  private bsodEl: HTMLElement | null = null;
  private readonly onBsodKey = (event: KeyboardEvent) => {
    if (event.repeat || !this.bsodEl) return;
    event.preventDefault();
    event.stopPropagation();
    this.leave();
  };

  constructor() {
    super({ key: "SecretDungeon", active: false });
  }

  init(hooks: DungeonHooks) {
    this.hooks = hooks;
    this.left = false;
    this.revealed = 0;
    this.locked = true;
    this.tapTarget = null;
    this.startedAt = 0;
    this.lx = SPAWN.x;
    this.ly = SPAWN.y;
    this.facing = -Math.PI / 2;
    this.bsodEl = null;
  }

  create() {
    this.cameras.main.setBackgroundColor("#000000");
    this.cameras.main.setRoundPixels(true);

    makeCanvas(this, "dungeon-room", CAVE.w, CAVE.h, drawRocks);
    this.textTex = makeCanvas(this, "dungeon-text", CAVE.w, CAVE.h, () => {});
    paintArt(this, "dungeon-man", OLD_MAN);
    paintArt(this, "dungeon-sword", SWORD_ART);
    paintArt(this, "dungeon-fire-0", FIRE_A);
    paintArt(this, "dungeon-fire-1", FIRE_B);

    this.roomImage = this.add.image(0, 0, "dungeon-room").setOrigin(0, 0).setDepth(0);
    this.sword = this.add.image(0, 0, "dungeon-sword").setOrigin(0.5, 0.5).setDepth(2);
    this.man = this.add.image(0, 0, "dungeon-man").setOrigin(0.5, 1).setDepth(3);
    this.fires = [0, 1].map(() => this.add.image(0, 0, "dungeon-fire-0").setOrigin(0.5, 1).setDepth(3));
    this.textImage = this.add.image(0, 0, "dungeon-text").setOrigin(0, 0).setDepth(80);

    this.avatar = new KidAvatar(this, 0, 0, 0, "");
    this.avatar.setSkin(this.hooks.skin);
    this.avatar.setLabels({ name: "", you: false, it: false });
    this.avatar.setRole("self");
    this.avatar.facing = this.facing;
    // Radius 0 puts the feet on y; the display scale is set in layout().
    this.avatar.update();

    this.layout();
    this.scale.on(Phaser.Scale.Events.RESIZE, this.layout, this);

    this.input.on(Phaser.Input.Events.POINTER_DOWN, (pointer: Phaser.Input.Pointer) => {
      if (this.locked || this.bsodEl || this.left) return;
      if (this.hooks.readMove().mode !== "mobile") return;
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      const lx = (world.x - this.fit.ox) / this.fit.scale;
      const ly = (world.y - this.fit.oy) / this.fit.scale;
      if (lx < 0 || ly < 0 || lx > CAVE.w || ly > CAVE.h) return;
      this.tapTarget = { x: lx, y: ly };
    });

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.layout, this);
      this.teardownBsod();
      this.avatar?.destroy();
      this.avatar = null;
      if (import.meta.env.DEV) {
        const w = window as unknown as { __dungeon?: SecretDungeonScene };
        if (w.__dungeon === this) delete w.__dungeon;
      }
    });

    if (import.meta.env.DEV) {
      (window as unknown as { __dungeon?: SecretDungeonScene }).__dungeon = this;
    }
  }

  /**
   * Cave state for the browser test (dev builds). Not shown to players.
   */
  get debug() {
    return {
      revealed: this.revealed,
      total: LINES[0].length + LINES[1].length,
      locked: this.locked,
      x: this.lx,
      y: this.ly,
      bsod: this.bsodEl != null,
      solids: this.solids,
      sword: caveSword(),
      playerR: CAVE.playerR,
    };
  }

  private readonly layout = () => {
    const viewW = this.scale.width;
    const viewH = this.scale.height;
    const scale = Math.min(viewW / CAVE.w, viewH / CAVE.h) * CAVE_ZOOM;
    const ox = (viewW - CAVE.w * scale) / 2;
    const oy = (viewH - CAVE.h * scale) / 2;
    this.fit = { scale, ox, oy };
    this.cameras.main.setSize(viewW, viewH);
    this.roomImage.setPosition(ox, oy).setScale(scale);
    this.textImage.setPosition(ox, oy).setScale(scale);
    const placeFeet = (img: Phaser.GameObjects.Image, x: number, y: number) => {
      img.setPosition(ox + x * scale, oy + y * scale).setScale(scale);
    };
    placeFeet(this.man, MAN.x, MAN.y);
    placeFeet(this.fires[0], FIRE_L.x, FIRE_L.y);
    placeFeet(this.fires[1], FIRE_R.x, FIRE_R.y);
    this.sword.setPosition(ox + SWORD.x * scale, oy + SWORD.y * scale).setScale(scale);
    this.placeAvatar();
  };

  private placeAvatar() {
    const avatar = this.avatar;
    if (!avatar) return;
    const { scale, ox, oy } = this.fit;
    const sheet = SKINS[this.hooks.skin];
    const targetH = CAVE.h * scale * PLAYER_ROOM_FRACTION;
    avatar.sprite.setScale(targetH / sheet.frameHeight);
    avatar.shadow.setSize(targetH * 0.42, targetH * 0.12);
    avatar.x = ox + this.lx * scale;
    avatar.y = oy + this.ly * scale;
    avatar.facing = this.facing;
    avatar.update();
  }

  update(time: number, delta: number) {
    if (this.left) return;
    if (this.startedAt === 0) {
      this.startedAt = time;
      this.nextRevealAt = time + 420;
    }
    this.reveal(time);
    this.flicker(time);
    if (this.locked || this.bsodEl) {
      if (this.avatar) {
        this.avatar.moving = false;
        this.avatar.running = false;
        this.placeAvatar();
      }
      return;
    }
    this.walk(delta);
    if (this.left) return;
    if (circleHits(this.lx, this.ly, CAVE.playerR, caveSword())) this.showBsod();
  }

  private reveal(time: number) {
    const total = LINES[0].length + LINES[1].length;
    if (this.revealed >= total) return;
    if (time < this.nextRevealAt) {
      this.drawText(time);
      return;
    }
    const flat = LINES[0] + LINES[1];
    const ch = flat[this.revealed] ?? " ";
    this.revealed += 1;
    if (ch !== " ") this.hooks.audio?.playSfx("blip", 0.7);
    const pause = this.revealed === LINES[0].length ? LINE_PAUSE_MS : ch === " " ? SPACE_MS : LETTER_MS;
    this.nextRevealAt = time + pause;
    if (this.revealed >= total) this.locked = false;
    this.drawText(time);
  }

  private drawText(time: number) {
    const ctx = this.textTex.getContext();
    ctx.clearRect(0, 0, CAVE.w, CAVE.h);
    const shown = [LINES[0].slice(0, this.revealed), LINES[1].slice(0, Math.max(0, this.revealed - LINES[0].length))];
    const top = CAVE.wall + 6;
    shown.forEach((line, i) => {
      const x = Math.round((CAVE.w - glyphWidth(LINES[i])) / 2);
      const y = top + i * (GLYPH_H + 5);
      for (let c = 0; c < line.length; c++) {
        const glyph = FONT[line[c]] ?? FONT[" "];
        glyph.forEach((row, gy) => {
          for (let gx = 0; gx < row.length; gx++) {
            if (row[gx] !== "1") continue;
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(x + c * (GLYPH_W + GLYPH_GAP) + gx, y + gy, 1, 1);
          }
        });
      }
    });
    if (this.locked && this.revealed > 0 && Math.floor(time / 240) % 2 === 0) {
      const lineIndex = this.revealed <= LINES[0].length ? 0 : 1;
      const count = lineIndex === 0 ? this.revealed : this.revealed - LINES[0].length;
      const x = Math.round((CAVE.w - glyphWidth(LINES[lineIndex])) / 2) + count * (GLYPH_W + GLYPH_GAP);
      const y = top + lineIndex * (GLYPH_H + 5);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(x, y, 4, GLYPH_H);
    }
    this.textTex.refresh();
  }

  private flicker(time: number) {
    this.fires.forEach((fire, i) => {
      const frame = Math.floor(time / 110 + i) % 2;
      const key = frame === 0 ? "dungeon-fire-0" : "dungeon-fire-1";
      if (fire.texture.key !== key) fire.setTexture(key);
      const feet = i === 0 ? FIRE_L.y : FIRE_R.y;
      fire.setDepth(this.groundDepth(feet));
    });
    this.man.setDepth(this.groundDepth(MAN.y));
    // Sort with the hilt, the sword's lowest point, so a kid standing
    // under it (the door) draws in front and a kid behind it does not
    // cover the blade.
    this.sword.setDepth(this.groundDepth(SWORD.y + SWORD.h / 2));
  }

  private groundDepth(caveY: number): number {
    return 10 + (this.fit.oy + caveY * this.fit.scale) / 10;
  }

  private walk(delta: number) {
    const move = this.hooks.readMove();
    let dx = 0;
    let dy = 0;
    if (move.dx !== 0 || move.dy !== 0) {
      this.tapTarget = null;
      dx = move.dx;
      dy = move.dy;
    } else if (move.mode === "mobile" && this.tapTarget) {
      const tx = this.tapTarget.x - this.lx;
      const ty = this.tapTarget.y - this.ly;
      const d = Math.hypot(tx, ty);
      if (d < 4) this.tapTarget = null;
      else {
        dx = tx / d;
        dy = ty / d;
      }
    }
    const len = Math.hypot(dx, dy);
    if (len > 1) {
      dx /= len;
      dy /= len;
    }
    const moving = len > 0.05;
    if (moving) {
      const step = (64 * delta) / 1000;
      const nx = this.lx + dx * step;
      const ny = this.ly + dy * step;
      if (!this.blocked(nx, this.ly)) this.lx = nx;
      if (!this.blocked(this.lx, ny)) this.ly = ny;
      this.facing = Math.atan2(dy, dx);
    }
    if (this.avatar) {
      this.avatar.moving = moving;
      this.avatar.running = false;
      this.placeAvatar();
    }
    const inDoor = this.lx > DOOR_X + 4 && this.lx < DOOR_X + CAVE.doorW - 4;
    if (inDoor && this.ly > CAVE.h - 8) this.leave();
  }

  private blocked(x: number, y: number): boolean {
    if (x < 2 || y < 2 || x > CAVE.w - 2 || y > CAVE.h - 2) return true;
    return this.solids.some(rect => circleHits(x, y, CAVE.playerR, rect));
  }

  private showBsod() {
    if (this.bsodEl) return;
    this.tapTarget = null;
    const el = document.createElement("div");
    el.className = "bsod";
    el.tabIndex = 0;
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "Error: Quest Not Implemented.");
    const pre = document.createElement("pre");
    pre.textContent = BSOD_TEXT;
    const cursor = document.createElement("span");
    cursor.className = "bsod-cursor";
    cursor.textContent = "_";
    el.append(pre, cursor);
    const tap = (event: PointerEvent) => {
      event.preventDefault();
      this.leave();
    };
    el.addEventListener("pointerdown", tap);
    document.body.appendChild(el);
    this.bsodEl = el;
    window.addEventListener("keydown", this.onBsodKey, true);
    el.focus();
  }

  private teardownBsod() {
    window.removeEventListener("keydown", this.onBsodKey, true);
    this.bsodEl?.remove();
    this.bsodEl = null;
  }

  private leave() {
    if (this.left) return;
    this.left = true;
    this.teardownBsod();
    this.hooks.onExit();
  }
}
