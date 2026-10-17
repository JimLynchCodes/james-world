/**
 * Secret cave. Original pixel room (not ripped tiles): black floor, rocky
 * brown walls, an old man between two flickering fires, a sword on the
 * floor, and a door gap in the bottom wall. The three sprites are derived
 * from the reference picture by tools/make_cave_sprites.py.
 *
 * The player is locked until the two-line message finishes revealing.
 * Walls, both fires, and the old man are solid. The sword is not: touching
 * it opens a full-screen blue error page. Walking out the bottom door, or
 * dismissing that page, returns to the schoolyard.
 */
import Phaser from "phaser";
import type { GameAudio } from "./audio";
import { CAVE_FONT, CAVE_GLYPH_H, CAVE_GLYPH_W, supportsCaveGlyphs } from "./caveFont";
import { onLocaleChange, t } from "./i18n";
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
/** Kid height as a fraction of the room. The old man and the fires match it. */
const PLAYER_ROOM_FRACTION = 0.11;
/** Sword length relative to the player, head to feet. */
const SWORD_HEIGHT_FRACTION = 0.6;
const PLAYER_CAVE_H = CAVE.h * PLAYER_ROOM_FRACTION;

const BASE = import.meta.env.BASE_URL;

const DOOR_X = (CAVE.w - CAVE.doorW) / 2;

export type CaveRect = { x: number; y: number; w: number; h: number };

/** Feet in the bottom doorway, well below the sword. */
const SPAWN = { x: CAVE.w / 2, y: CAVE.h - 24 };
/** Feet line for the old man and both fires, under the typed lines. */
const FIGURE_FEET_Y = 86;
/** Gap between the man's robe and each fire, in cave pixels. */
const FIGURE_GAP = 4;

/** x/y are feet for the man and fires, and the center for the sword. w/h are the drawn size. */
type PlacedSprite = { x: number; y: number; w: number; h: number };

type CaveSprites = {
  man: PlacedSprite;
  fireL: PlacedSprite;
  fireR: PlacedSprite;
  sword: PlacedSprite;
};

function wallSolids(): CaveRect[] {
  const { w, h, wall, doorW } = CAVE;
  const doorX = (w - doorW) / 2;
  return [
    { x: 0, y: 0, w, h: wall },
    { x: 0, y: 0, w: wall, h },
    { x: w - wall, y: 0, w: wall, h },
    { x: 0, y: h - wall, w: doorX, h: wall },
    { x: doorX + doorW, y: h - wall, w: w - (doorX + doorW), h: wall },
  ];
}

function figureSolids(sprites: CaveSprites): CaveRect[] {
  const box = (s: PlacedSprite): CaveRect => ({
    x: s.x - s.w / 2,
    y: s.y - s.h,
    w: s.w,
    h: s.h,
  });
  return [box(sprites.man), box(sprites.fireL), box(sprites.fireR)];
}

function swordRect(sword: PlacedSprite): CaveRect {
  const pad = 1;
  return {
    x: sword.x - sword.w / 2 - pad,
    y: sword.y - sword.h / 2 - pad,
    w: sword.w + pad * 2,
    h: sword.h + pad * 2,
  };
}

export type DungeonHooks = {
  skin: Skin;
  readMove: () => { dx: number; dy: number; mode: ControlMode };
  audio: GameAudio | null;
  onExit: () => void;
};

const GLYPH_W = CAVE_GLYPH_W;
const GLYPH_H = CAVE_GLYPH_H;
const GLYPH_GAP = 1;
const LETTER_MS = 78;
const SPACE_MS = 42;
const LINE_PAUSE_MS = 320;

/** Current quote. Latin stays on the pixel font; CJK uses a fallback face. */
function caveLines(): readonly [string, string] {
  return [t("cave.line1"), t("cave.line2")];
}

type RGB = [number, number, number];

function hash(x: number, y: number): number {
  let n = (x * 374761393 + y * 668265263) | 0;
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return (n ^ (n >>> 16)) >>> 0;
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
  private solids: CaveRect[] = wallSolids();
  private sprites!: CaveSprites;
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
  private unsubLocale: (() => void) | null = null;
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

  preload() {
    const load = (key: string, file: string) => {
      if (!this.textures.exists(key)) this.load.image(key, `${BASE}assets/cave/${file}`);
    };
    load("dungeon-man", "old-man.png");
    load("dungeon-fire-0", "fire-0.png");
    load("dungeon-fire-1", "fire-1.png");
    load("dungeon-sword", "sword.png");
  }

  create() {
    this.cameras.main.setBackgroundColor("#000000");
    this.cameras.main.setRoundPixels(true);

    for (const key of ["dungeon-man", "dungeon-fire-0", "dungeon-fire-1", "dungeon-sword"]) {
      this.textures.get(key).setFilter(Phaser.Textures.FilterMode.NEAREST);
    }
    this.sprites = this.measureSprites();
    this.solids = [...wallSolids(), ...figureSolids(this.sprites)];

    makeCanvas(this, "dungeon-room", CAVE.w, CAVE.h, drawRocks);
    this.textTex = makeCanvas(this, "dungeon-text", CAVE.w, CAVE.h, () => {});

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

    this.unsubLocale = onLocaleChange(() => {
      // Retype the quote in the new language. The BSOD, if it's up, swaps too.
      this.revealed = 0;
      this.locked = true;
      this.nextRevealAt = this.time.now;
      this.drawText(this.time.now);
      if (this.bsodEl) this.fillBsod(this.bsodEl);
    });

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.layout, this);
      this.unsubLocale?.();
      this.unsubLocale = null;
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
      total: caveLines()[0].length + caveLines()[1].length,
      locked: this.locked,
      x: this.lx,
      y: this.ly,
      bsod: this.bsodEl != null,
      solids: this.solids,
      sword: swordRect(this.sprites.sword),
      playerR: CAVE.playerR,
      playerH: PLAYER_CAVE_H,
      sprites: this.sprites,
      screen: {
        man: this.screenBox(this.man),
        fireL: this.screenBox(this.fires[0]),
        fireR: this.screenBox(this.fires[1]),
        sword: this.screenBox(this.sword),
        playerH: CAVE.h * this.fit.scale * PLAYER_ROOM_FRACTION,
      },
    };
  }

  private sourceSize(key: string): { w: number; h: number } {
    const image = this.textures.get(key).getSourceImage() as { width: number; height: number };
    return { w: image.width, h: image.height };
  }

  /** Drawn width and height in cave pixels for a target height. */
  private drawn(key: string, targetH: number): { w: number; h: number } {
    const src = this.sourceSize(key);
    return { w: (src.w * targetH) / src.h, h: targetH };
  }

  private measureSprites(): CaveSprites {
    const man = this.drawn("dungeon-man", PLAYER_CAVE_H);
    const fire = this.drawn("dungeon-fire-0", PLAYER_CAVE_H);
    const sword = this.drawn("dungeon-sword", PLAYER_CAVE_H * SWORD_HEIGHT_FRACTION);
    const x = CAVE.w / 2;
    const y = FIGURE_FEET_Y;
    return {
      man: { x, y, w: man.w, h: man.h },
      fireL: { x: x - man.w / 2 - FIGURE_GAP - fire.w / 2, y, w: fire.w, h: fire.h },
      fireR: { x: x + man.w / 2 + FIGURE_GAP + fire.w / 2, y, w: fire.w, h: fire.h },
      sword: { x, y: y + 8 + sword.h / 2, w: sword.w, h: sword.h },
    };
  }

  /** Nearest-neighbor scale that makes `targetH` cave pixels tall on screen. */
  private pixelScale(key: string, targetH: number): number {
    return this.fit.scale * (targetH / this.sourceSize(key).h);
  }

  private screenBox(img: Phaser.GameObjects.Image) {
    return {
      x: img.x - img.displayWidth * img.originX,
      y: img.y - img.displayHeight * img.originY,
      w: img.displayWidth,
      h: img.displayHeight,
    };
  }

  private readonly layout = () => {
    const viewW = this.scale.width;
    const viewH = this.scale.height;
    const contain = Math.min(viewW / CAVE.w, viewH / CAVE.h);
    // Portrait phones otherwise letterbox a tiny landscape room. Fill the
    // width (the room can crop vertically if the screen is shorter).
    const portrait = viewH > viewW;
    const scale = portrait ? contain : contain * CAVE_ZOOM;
    const ox = (viewW - CAVE.w * scale) / 2;
    const oy = (viewH - CAVE.h * scale) / 2;
    this.fit = { scale, ox, oy };
    this.cameras.main.setSize(viewW, viewH);
    this.roomImage.setPosition(ox, oy).setScale(scale);
    this.textImage.setPosition(ox, oy).setScale(scale);
    const sprites = this.sprites;
    const placeFeet = (img: Phaser.GameObjects.Image, sprite: PlacedSprite, key: string) => {
      img.setPosition(ox + sprite.x * scale, oy + sprite.y * scale).setScale(this.pixelScale(key, sprite.h));
    };
    placeFeet(this.man, sprites.man, "dungeon-man");
    placeFeet(this.fires[0], sprites.fireL, "dungeon-fire-0");
    placeFeet(this.fires[1], sprites.fireR, "dungeon-fire-1");
    this.sword
      .setPosition(ox + sprites.sword.x * scale, oy + sprites.sword.y * scale)
      .setScale(this.pixelScale("dungeon-sword", sprites.sword.h));
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
    if (circleHits(this.lx, this.ly, CAVE.playerR, swordRect(this.sprites.sword))) this.showBsod();
  }

  private reveal(time: number) {
    const lines = caveLines();
    const total = lines[0].length + lines[1].length;
    if (this.revealed >= total) return;
    if (time < this.nextRevealAt) {
      this.drawText(time);
      return;
    }
    const flat = lines[0] + lines[1];
    const ch = flat[this.revealed] ?? " ";
    this.revealed += 1;
    if (ch !== " ") this.hooks.audio?.playSfx("blip", 0.7);
    const pause = this.revealed === lines[0].length ? LINE_PAUSE_MS : ch === " " ? SPACE_MS : LETTER_MS;
    this.nextRevealAt = time + pause;
    if (this.revealed >= total) this.locked = false;
    this.drawText(time);
  }

  private drawText(time: number) {
    const lines = caveLines();
    const ctx = this.textTex.getContext();
    ctx.clearRect(0, 0, CAVE.w, CAVE.h);
    const shown: [string, string] = [
      lines[0].slice(0, this.revealed),
      lines[1].slice(0, Math.max(0, this.revealed - lines[0].length)),
    ];
    if (supportsCaveGlyphs(lines[0]) && supportsCaveGlyphs(lines[1])) {
      this.drawPixelLines(ctx, lines, shown, time);
    } else {
      this.drawFallbackLines(ctx, lines, shown, time);
    }
    this.textTex.refresh();
  }

  /** Chunky 5×7 glyphs. Used when every character has a pixel. */
  private drawPixelLines(
    ctx: CanvasRenderingContext2D,
    lines: readonly [string, string],
    shown: readonly [string, string],
    time: number
  ) {
    const top = CAVE.wall + 6;
    shown.forEach((line, i) => {
      const x = Math.round((CAVE.w - glyphWidth(lines[i])) / 2);
      const y = top + i * (GLYPH_H + 5);
      for (let c = 0; c < line.length; c++) {
        const glyph = CAVE_FONT[line[c]] ?? CAVE_FONT[" "];
        if (!glyph) continue;
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
      const lineIndex = this.revealed <= lines[0].length ? 0 : 1;
      const count = lineIndex === 0 ? this.revealed : this.revealed - lines[0].length;
      const x = Math.round((CAVE.w - glyphWidth(lines[lineIndex])) / 2) + count * (GLYPH_W + GLYPH_GAP);
      const y = top + lineIndex * (GLYPH_H + 5);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(x, y, 4, GLYPH_H);
    }
  }

  /**
   * System face for quotes the pixel font cannot draw (CJK, and anything
   * else we did not carve a glyph for). Nearest-neighbor scaling of this
   * canvas keeps the letters blocky, close to the English quote.
   */
  private drawFallbackLines(
    ctx: CanvasRenderingContext2D,
    lines: readonly [string, string],
    shown: readonly [string, string],
    time: number
  ) {
    const family =
      '"Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans SC", "Noto Sans JP", "PingFang SC", "Hiragino Sans", "Microsoft YaHei", "Yu Gothic", "WenQuanYi Micro Hei", "Droid Sans Fallback", "Noto Sans", sans-serif';
    const maxW = CAVE.w - 12;
    let size = 12;
    const widthAt = (px: number) => {
      ctx.font = `bold ${px}px ${family}`;
      return Math.max(ctx.measureText(lines[0]).width, ctx.measureText(lines[1]).width);
    };
    while (size > 7 && widthAt(size) > maxW) size -= 1;
    ctx.font = `bold ${size}px ${family}`;
    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const top = CAVE.wall + 4;
    shown.forEach((line, i) => {
      const fullW = ctx.measureText(lines[i]).width;
      const x = Math.round((CAVE.w - fullW) / 2);
      const y = top + i * (size + 4);
      ctx.fillText(line, x, y);
    });
    if (this.locked && this.revealed > 0 && Math.floor(time / 240) % 2 === 0) {
      const lineIndex = this.revealed <= lines[0].length ? 0 : 1;
      const count = lineIndex === 0 ? this.revealed : this.revealed - lines[0].length;
      const partial = lines[lineIndex].slice(0, count);
      const fullW = ctx.measureText(lines[lineIndex]).width;
      const x = Math.round((CAVE.w - fullW) / 2) + ctx.measureText(partial).width;
      const y = top + lineIndex * (size + 4);
      ctx.fillRect(x, y, Math.max(4, Math.round(size * 0.45)), size);
    }
  }

  private flicker(time: number) {
    this.fires.forEach((fire, i) => {
      const frame = Math.floor(time / 110 + i) % 2;
      const key = frame === 0 ? "dungeon-fire-0" : "dungeon-fire-1";
      if (fire.texture.key !== key) fire.setTexture(key);
      const feet = i === 0 ? this.sprites.fireL.y : this.sprites.fireR.y;
      fire.setDepth(this.groundDepth(feet));
    });
    this.man.setDepth(this.groundDepth(this.sprites.man.y));
    // Sort with the sword's lowest point, so a kid standing under it
    // draws in front and a kid behind it does not cover the blade.
    this.sword.setDepth(this.groundDepth(this.sprites.sword.y + this.sprites.sword.h / 2));
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
    this.fillBsod(el);
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

  private fillBsod(el: HTMLElement) {
    el.setAttribute("aria-label", t("bsod.aria"));
    el.replaceChildren();
    const pre = document.createElement("pre");
    pre.textContent = t("bsod.text");
    const cursor = document.createElement("span");
    cursor.className = "bsod-cursor";
    cursor.textContent = "_";
    el.append(pre, cursor);
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
