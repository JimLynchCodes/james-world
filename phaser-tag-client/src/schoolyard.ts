import Phaser from "phaser";
import { PLAYER_RADIUS, WALL_BOTTOM, WALL_LEFT, WALL_RIGHT, WALL_TOP } from "./world";

/**
 * Procedural schoolyard background for the 5000x5000 world.
 *
 * Everything is purely decorative (no collision). To stay cheap on a big
 * world it is built from:
 *  - a few small seamless tiles (grass, patchy variation, fence) drawn once
 *    into canvas textures and shown with TileSprites (the ground layers only
 *    cover the camera view and follow it, see alignGround);
 *  - one canvas texture per "area" (blacktop with courts, running track,
 *    baseball diamond, playground) shown as a single Image each;
 *  - small prop textures (trees, bushes, benches, picnic tables) reused by
 *    many Images;
 *  - a single Graphics object for the edge strip and the street outside the fence (a few dozen
 *    commands).
 * Colours are kept muted so the kid sprites and their foot rings stay
 * clearly readable on top.
 */

const DEPTH = {
  grass: -100,
  patches: -99,
  ground: -95, // edge strip + street outside the fence
  areas: -90,
  // Tall props (trees, bushes, fence) share the kid depth band:
  //   10 + baseY / 10
  // so a kid whose feet are north of a trunk sorts behind it. Short props
  // (benches, picnic tables) stay under the kids.
  props: -60, // + y / 100000 for y-sorting among short props
  fenceBehind: -50, // unused; fence segments use the kid depth band
};

/** Depth shared with KidAvatar sprites (see kid.ts). */
export function propDepth(baseY: number) {
  return 10 + baseY / 10;
}

/** A tall schoolyard prop that can occlude kids (trees, bushes, fence). */
export type Occluder = {
  /** Drawn image / tile sprite. */
  view: Phaser.GameObjects.Image | Phaser.GameObjects.TileSprite;
  /** Ground / trunk base Y — compared to a kid's feetY for sorting. */
  baseY: number;
  /** Axis-aligned canopy (or mesh) footprint in world space. */
  left: number;
  right: number;
  top: number;
  bottom: number;
};

const OCCLUDE_ALPHA = 0.58;

// Muted palette.
const C = {
  grass: "#4a7342",
  grassBlades: ["#3f6838", "#557f4b", "#456f3d", "#5a8550", "#41693a"],
  asphalt: "#3b3f45",
  asphaltSpeck: ["#33373c", "#454a51", "#2e3237", "#4d5259"],
  paint: "rgba(236, 236, 226, 0.78)",
  paintYellow: "rgba(226, 196, 92, 0.8)",
  track: "#8b4c3d",
  dirt: "#9b7a55",
  chips: "#7a5b3d",
  sand: "#c4ae7e",
  wood: "#86643f",
  woodDark: "#5d4228",
};

type Rect = { x: number; y: number; w: number; h: number };
type Ctx = CanvasRenderingContext2D;

/** Small deterministic PRNG so the yard looks the same for everyone. */
function mulberry32(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function canvasTexture(
  scene: Phaser.Scene,
  key: string,
  w: number,
  h: number,
  draw: (ctx: Ctx, w: number, h: number) => void
): string {
  if (scene.textures.exists(key)) return key;
  const tex = scene.textures.createCanvas(key, w, h);
  if (!tex) throw new Error(`could not create texture ${key}`);
  draw(tex.getContext(), w, h);
  tex.refresh();
  return key;
}

/** Draw something at (x, y) and at its wrapped copies so tiles are seamless. */
function wrapped(w: number, h: number, x: number, y: number, fn: (x: number, y: number) => void) {
  for (const ox of [-w, 0, w]) for (const oy of [-h, 0, h]) fn(x + ox, y + oy);
}

function speckle(ctx: Ctx, rnd: () => number, w: number, h: number, n: number, colors: string[], size = 2) {
  for (let i = 0; i < n; i++) {
    ctx.fillStyle = colors[(rnd() * colors.length) | 0];
    const s = size * (0.5 + rnd());
    ctx.fillRect(rnd() * w, rnd() * h, s, s);
  }
}

function roundRect(ctx: Ctx, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function stadium(ctx: Ctx, cx: number, cy: number, straight: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(cx - straight / 2, cy - r);
  ctx.lineTo(cx + straight / 2, cy - r);
  ctx.arc(cx + straight / 2, cy, r, -Math.PI / 2, Math.PI / 2);
  ctx.lineTo(cx - straight / 2, cy + r);
  ctx.arc(cx - straight / 2, cy, r, Math.PI / 2, (3 * Math.PI) / 2);
  ctx.closePath();
}

// ---------------------------------------------------------------------------
// Tiles

const GRASS_TILE = 256;

function grassTile(scene: Phaser.Scene) {
  return canvasTexture(scene, "sy-grass", GRASS_TILE, GRASS_TILE, (ctx, w, h) => {
    const rnd = mulberry32(11);
    ctx.fillStyle = C.grass;
    ctx.fillRect(0, 0, w, h);
    // soft mottling
    for (let i = 0; i < 26; i++) {
      const x = rnd() * w;
      const y = rnd() * h;
      const r = 14 + rnd() * 34;
      const light = rnd() < 0.5;
      wrapped(w, h, x, y, (px, py) => {
        const g = ctx.createRadialGradient(px, py, 0, px, py, r);
        g.addColorStop(0, light ? "rgba(120,160,80,0.10)" : "rgba(20,45,15,0.10)");
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(px - r, py - r, r * 2, r * 2);
      });
    }
    // grass blades
    ctx.lineWidth = 1;
    for (let i = 0; i < 1500; i++) {
      const x = rnd() * w;
      const y = rnd() * h;
      const len = 2 + rnd() * 4;
      const a = -Math.PI / 2 + (rnd() - 0.5) * 0.9;
      ctx.strokeStyle = C.grassBlades[(rnd() * C.grassBlades.length) | 0];
      wrapped(w, h, x, y, (px, py) => {
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px + Math.cos(a) * len, py + Math.sin(a) * len);
        ctx.stroke();
      });
    }
  });
}

/** Large, low-contrast light/dark patches so the field isn't a flat repeat. */
function patchTile(scene: Phaser.Scene) {
  return canvasTexture(scene, "sy-patches", 1024, 1024, (ctx, w, h) => {
    const rnd = mulberry32(23);
    for (let i = 0; i < 34; i++) {
      const x = rnd() * w;
      const y = rnd() * h;
      const r = 70 + rnd() * 190;
      const light = rnd() < 0.45;
      wrapped(w, h, x, y, (px, py) => {
        const g = ctx.createRadialGradient(px, py, 0, px, py, r);
        g.addColorStop(0, light ? "rgba(150,180,90,0.06)" : "rgba(15,35,10,0.075)");
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(px - r, py - r, r * 2, r * 2);
      });
    }
  });
}

const FENCE_T = 32; // fence band thickness in world px

function fenceTile(scene: Phaser.Scene, vertical: boolean) {
  const key = vertical ? "sy-fence-v" : "sy-fence-h";
  const w = vertical ? FENCE_T : 64;
  const h = vertical ? 64 : FENCE_T;
  return canvasTexture(scene, key, w, h, ctx => {
    // Draw the horizontal version, rotating the context for the vertical one.
    if (vertical) {
      ctx.translate(FENCE_T, 0);
      ctx.rotate(Math.PI / 2);
    }
    const L = 64;
    // shadow cast on the ground
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.fillRect(0, 24, L, 8);
    // chain-link mesh
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 7, L, 16);
    ctx.clip();
    ctx.strokeStyle = "rgba(205,212,218,0.45)";
    ctx.lineWidth = 1;
    for (let x = -24; x < L + 24; x += 8) {
      ctx.beginPath();
      ctx.moveTo(x, 7);
      ctx.lineTo(x + 16, 23);
      ctx.moveTo(x + 16, 7);
      ctx.lineTo(x, 23);
      ctx.stroke();
    }
    ctx.restore();
    // rails
    ctx.fillStyle = "#c5cacf";
    ctx.fillRect(0, 5, L, 3);
    ctx.fillStyle = "#8b9095";
    ctx.fillRect(0, 22, L, 2);
    // post
    ctx.fillStyle = "#5f656b";
    ctx.fillRect(2, 1, 7, 26);
    ctx.fillStyle = "#9aa1a7";
    ctx.fillRect(3, 1, 2, 26);
    ctx.fillStyle = "#4b5056";
    ctx.fillRect(1, 0, 9, 3);
  });
}

// ---------------------------------------------------------------------------
// Areas

/** Blacktop with a basketball court, a half court, four-square, hopscotch, etc. */
function blacktop(scene: Phaser.Scene) {
  return canvasTexture(scene, "sy-blacktop", 1920, 1140, (ctx, w, h) => {
    const rnd = mulberry32(5);
    roundRect(ctx, 2, 2, w - 4, h - 4, 36);
    ctx.fillStyle = C.asphalt;
    ctx.fill();
    ctx.save();
    ctx.clip();
    speckle(ctx, rnd, w, h, 26000, C.asphaltSpeck, 2);
    // a few cracks and oil-ish stains
    ctx.strokeStyle = "rgba(20,22,25,0.55)";
    ctx.lineWidth = 1.5;
    for (let i = 0; i < 14; i++) {
      let x = rnd() * w;
      let y = rnd() * h;
      ctx.beginPath();
      ctx.moveTo(x, y);
      for (let k = 0; k < 6; k++) {
        x += (rnd() - 0.5) * 60;
        y += (rnd() - 0.5) * 60;
        ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    for (let i = 0; i < 10; i++) {
      const x = rnd() * w;
      const y = rnd() * h;
      const r = 20 + rnd() * 50;
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, "rgba(25,27,30,0.35)");
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.fillRect(x - r, y - r, r * 2, r * 2);
    }
    ctx.restore();
    // curb
    roundRect(ctx, 2, 2, w - 4, h - 4, 36);
    ctx.strokeStyle = "#6d6f70";
    ctx.lineWidth = 4;
    ctx.stroke();

    ctx.lineCap = "butt";
    // --- full basketball court (94x50 ft -> 940x500)
    const bx = 920;
    const by = 50;
    const bw = 940;
    const bh = 500;
    ctx.fillStyle = "rgba(120,62,52,0.30)"; // keys
    ctx.fillRect(bx, by + bh / 2 - 95, 190, 190);
    ctx.fillRect(bx + bw - 190, by + bh / 2 - 95, 190, 190);
    ctx.fillStyle = "rgba(60,90,130,0.22)"; // centre circle fill
    ctx.beginPath();
    ctx.arc(bx + bw / 2, by + bh / 2, 60, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = C.paint;
    ctx.lineWidth = 4;
    ctx.strokeRect(bx, by, bw, bh);
    ctx.beginPath();
    ctx.moveTo(bx + bw / 2, by);
    ctx.lineTo(bx + bw / 2, by + bh);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(bx + bw / 2, by + bh / 2, 60, 0, Math.PI * 2);
    ctx.stroke();
    for (const side of [0, 1]) {
      const dir = side === 0 ? 1 : -1;
      const base = side === 0 ? bx : bx + bw;
      const cy = by + bh / 2;
      // lane
      ctx.strokeRect(side === 0 ? bx : bx + bw - 190, cy - 95, 190, 190);
      // free throw circle
      ctx.beginPath();
      ctx.arc(base + dir * 190, cy, 60, 0, Math.PI * 2);
      ctx.stroke();
      // three point line
      const rimX = base + dir * 52;
      ctx.beginPath();
      ctx.moveTo(base, cy - 220);
      ctx.lineTo(base + dir * 140, cy - 220);
      const a = Math.asin(220 / 237);
      if (dir === 1) ctx.arc(rimX, cy, 237, -a, a);
      else ctx.arc(rimX, cy, 237, Math.PI + a, Math.PI - a, true);
      ctx.lineTo(base, cy + 220);
      ctx.stroke();
      // backboard + rim
      ctx.fillStyle = "#d9d9d2";
      ctx.fillRect(base + dir * 38 - 2, cy - 30, 4, 60);
      ctx.strokeStyle = "#c8673a";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(rimX, cy, 9, 0, Math.PI * 2);
      ctx.stroke();
      // pole pad outside the baseline
      ctx.fillStyle = "#2d4f7a";
      ctx.fillRect(base - dir * 34 - 8, cy - 8, 16, 16);
      ctx.strokeStyle = C.paint;
      ctx.lineWidth = 4;
    }
    ctx.fillStyle = "rgba(236,236,226,0.55)";
    ctx.font = "bold 34px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("TAG 26", bx + bw / 2, by + bh / 2);

    // --- half court
    const hx = 1100;
    const hy = 640;
    const hw = 600;
    const hh = 450;
    ctx.fillStyle = "rgba(60,90,130,0.22)";
    ctx.fillRect(hx + hw / 2 - 95, hy + hh - 190, 190, 190);
    ctx.strokeStyle = C.paint;
    ctx.strokeRect(hx, hy, hw, hh);
    ctx.strokeRect(hx + hw / 2 - 95, hy + hh - 190, 190, 190);
    ctx.beginPath();
    ctx.arc(hx + hw / 2, hy + hh - 190, 60, Math.PI, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(hx + hw / 2 - 220, hy + hh);
    ctx.lineTo(hx + hw / 2 - 220, hy + hh - 140);
    const a2 = Math.asin(220 / 237);
    ctx.arc(hx + hw / 2, hy + hh - 52, 237, Math.PI + (Math.PI / 2 - a2), -(Math.PI / 2 - a2));
    ctx.lineTo(hx + hw / 2 + 220, hy + hh);
    ctx.stroke();
    ctx.fillStyle = "#d9d9d2";
    ctx.fillRect(hx + hw / 2 - 30, hy + hh - 40, 60, 4);
    ctx.strokeStyle = "#c8673a";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(hx + hw / 2, hy + hh - 52, 9, 0, Math.PI * 2);
    ctx.stroke();

    // --- four-square courts
    const quad = ["rgba(170,70,60,0.28)", "rgba(60,110,170,0.28)", "rgba(200,170,60,0.28)", "rgba(70,140,80,0.28)"];
    for (const [fx, fy] of [
      [70, 70],
      [370, 70],
    ]) {
      const s = 240;
      for (let q = 0; q < 4; q++) {
        ctx.fillStyle = quad[q];
        ctx.fillRect(fx + (q % 2) * (s / 2), fy + Math.floor(q / 2) * (s / 2), s / 2, s / 2);
      }
      ctx.strokeStyle = C.paint;
      ctx.lineWidth = 4;
      ctx.strokeRect(fx, fy, s, s);
      ctx.beginPath();
      ctx.moveTo(fx + s / 2, fy);
      ctx.lineTo(fx + s / 2, fy + s);
      ctx.moveTo(fx, fy + s / 2);
      ctx.lineTo(fx + s, fy + s / 2);
      ctx.stroke();
      ctx.fillStyle = "rgba(236,236,226,0.6)";
      ctx.font = "bold 40px system-ui, sans-serif";
      ["1", "2", "4", "3"].forEach((n, q) =>
        ctx.fillText(n, fx + s / 4 + (q % 2) * (s / 2), fy + s / 4 + Math.floor(q / 2) * (s / 2))
      );
    }

    // --- hopscotch (two of them)
    for (const [ox, oy] of [
      [720, 90],
      [150, 420],
    ]) {
      const b = 62;
      const rows: number[][] = [[1], [2], [3, 4], [5], [6, 7], [8], [9, 10]];
      ctx.strokeStyle = C.paintYellow;
      ctx.lineWidth = 4;
      ctx.font = "bold 28px system-ui, sans-serif";
      rows.forEach((nums, r) => {
        const y = oy + (rows.length - 1 - r) * b + b;
        nums.forEach((n, i) => {
          const x = nums.length === 1 ? ox + b / 2 : ox + i * b;
          ctx.strokeRect(x, y, b, b);
          ctx.fillStyle = "rgba(226,196,92,0.75)";
          ctx.fillText(String(n), x + b / 2, y + b / 2 + 1);
        });
      });
      ctx.beginPath();
      ctx.arc(ox + b, oy + b, b, Math.PI, 0);
      ctx.stroke();
    }

    // --- tetherball + painted target circles
    ctx.strokeStyle = C.paint;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(560, 520, 90, 0, Math.PI * 2);
    ctx.moveTo(470, 520);
    ctx.lineTo(650, 520);
    ctx.stroke();
    ctx.fillStyle = "#9aa0a6";
    ctx.beginPath();
    ctx.arc(560, 520, 7, 0, Math.PI * 2);
    ctx.fill();
    const rings = ["rgba(170,70,60,0.30)", "rgba(236,236,226,0.22)", "rgba(60,110,170,0.30)", "rgba(200,170,60,0.32)"];
    rings.forEach((col, i) => {
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(420, 860, 170 - i * 40, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.strokeStyle = C.paint;
    for (let i = 0; i < 4; i++) {
      ctx.beginPath();
      ctx.arc(420, 860, 170 - i * 40, 0, Math.PI * 2);
      ctx.stroke();
    }
    // painted number grid (snail/four-by-four)
    const gx = 690;
    const gy = 720;
    ctx.font = "bold 22px system-ui, sans-serif";
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 4; c++) {
        ctx.strokeStyle = C.paintYellow;
        ctx.strokeRect(gx + c * 70, gy + r * 70, 70, 70);
        ctx.fillStyle = "rgba(226,196,92,0.6)";
        ctx.fillText(String(r * 4 + c + 1), gx + c * 70 + 35, gy + r * 70 + 36);
      }
    }
  });
}

/** Running track (6 lanes) around a mowed soccer field. */
function track(scene: Phaser.Scene) {
  const grass = scene.textures.get("sy-grass").getSourceImage() as HTMLCanvasElement;
  return canvasTexture(scene, "sy-track", 1900, 900, (ctx, w, h) => {
    const cx = w / 2;
    const cy = h / 2;
    const straight = 1000;
    const rIn = 320;
    const lane = 17;
    const lanes = 6;
    const rOut = rIn + lane * lanes;
    // outer kerb + track surface
    stadium(ctx, cx, cy, straight, rOut + 6);
    ctx.fillStyle = "#7d7f7c";
    ctx.fill();
    stadium(ctx, cx, cy, straight, rOut);
    ctx.fillStyle = C.track;
    ctx.fill();
    const rnd = mulberry32(9);
    ctx.save();
    ctx.clip();
    speckle(ctx, rnd, w, h, 14000, ["#7e4436", "#97574a", "#83493b"], 2);
    ctx.restore();
    // infield grass (same tile as the world so it blends) with mowing stripes
    stadium(ctx, cx, cy, straight, rIn);
    ctx.save();
    ctx.clip();
    const pat = ctx.createPattern(grass, "repeat");
    if (pat) ctx.fillStyle = pat;
    ctx.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 80) {
      ctx.fillStyle = (x / 80) % 2 === 0 ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.05)";
      ctx.fillRect(x, 0, 80, h);
    }
    ctx.restore();
    stadium(ctx, cx, cy, straight, rIn);
    ctx.strokeStyle = "#cfcfc6";
    ctx.lineWidth = 4;
    ctx.stroke();
    // lane lines
    ctx.strokeStyle = "rgba(236,236,226,0.6)";
    ctx.lineWidth = 2;
    for (let i = 1; i <= lanes; i++) {
      stadium(ctx, cx, cy, straight, rIn + i * lane);
      ctx.stroke();
    }
    // start / finish line and lane numbers
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(cx + straight / 2 - 120, cy + rIn);
    ctx.lineTo(cx + straight / 2 - 120, cy + rOut);
    ctx.stroke();
    ctx.fillStyle = "rgba(236,236,226,0.65)";
    ctx.font = "bold 13px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let i = 0; i < lanes; i++) ctx.fillText(String(i + 1), cx + straight / 2 - 140, cy + rIn + lane * (i + 0.5));

    // soccer field
    const fw = 900;
    const fh = 540;
    const fx = cx - fw / 2;
    const fy = cy - fh / 2;
    ctx.strokeStyle = "rgba(236,236,226,0.7)";
    ctx.lineWidth = 3;
    ctx.strokeRect(fx, fy, fw, fh);
    ctx.beginPath();
    ctx.moveTo(cx, fy);
    ctx.lineTo(cx, fy + fh);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, 72, 0, Math.PI * 2);
    ctx.stroke();
    for (const side of [0, 1]) {
      const x = side === 0 ? fx : fx + fw;
      const d = side === 0 ? 1 : -1;
      ctx.strokeRect(Math.min(x, x + d * 140), cy - 160, 140, 320);
      ctx.strokeRect(Math.min(x, x + d * 50), cy - 75, 50, 150);
      ctx.beginPath();
      ctx.arc(x + d * 100, cy, 70, d === 1 ? -0.93 : Math.PI - 0.93, d === 1 ? 0.93 : Math.PI + 0.93);
      ctx.stroke();
      // goal net
      ctx.fillStyle = "rgba(230,230,225,0.25)";
      ctx.fillRect(Math.min(x, x - d * 22), cy - 40, 22, 80);
      ctx.strokeStyle = "rgba(240,240,235,0.85)";
      ctx.strokeRect(Math.min(x, x - d * 22), cy - 40, 22, 80);
      ctx.strokeStyle = "rgba(236,236,226,0.7)";
    }
  });
}

/** Dirt baseball infield with bases, mound, foul lines and a backstop. */
function diamond(scene: Phaser.Scene) {
  const grass = scene.textures.get("sy-grass").getSourceImage() as HTMLCanvasElement;
  return canvasTexture(scene, "sy-diamond", 1100, 1000, (ctx, w) => {
    const hx = w / 2;
    const hy = 900;
    const base = 260;
    const d = base / Math.SQRT2;
    const first = [hx + d, hy - d];
    const second = [hx, hy - 2 * d];
    const third = [hx - d, hy - d];
    const mound = [hx, hy - 0.672 * 2 * d];
    const rnd = mulberry32(17);
    // infield dirt: wedge between the foul lines, cut by an arc around the mound
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(hx, hy);
    ctx.lineTo(hx - 700, hy - 700);
    ctx.lineTo(hx + 700, hy - 700);
    ctx.closePath();
    ctx.clip();
    ctx.beginPath();
    ctx.arc(mound[0], mound[1], 300, 0, Math.PI * 2);
    ctx.fillStyle = C.dirt;
    ctx.fill();
    ctx.restore();
    ctx.beginPath();
    ctx.arc(hx, hy, 62, 0, Math.PI * 2);
    ctx.fillStyle = C.dirt;
    ctx.fill();
    // dirt speckle (only on the dirt drawn so far)
    ctx.save();
    ctx.globalCompositeOperation = "source-atop";
    speckle(ctx, rnd, w, 1000, 9000, ["rgba(120,92,62,0.6)", "rgba(178,146,108,0.5)"], 2);
    ctx.restore();
    // infield grass
    const inset = 34;
    ctx.beginPath();
    ctx.moveTo(hx, hy - inset * 1.6);
    ctx.lineTo(first[0] - inset, first[1]);
    ctx.lineTo(second[0], second[1] + inset);
    ctx.lineTo(third[0] + inset, third[1]);
    ctx.closePath();
    const pat = ctx.createPattern(grass, "repeat");
    if (pat) ctx.fillStyle = pat;
    ctx.fill();
    // mound
    ctx.beginPath();
    ctx.arc(mound[0], mound[1], 30, 0, Math.PI * 2);
    ctx.fillStyle = "#a8865f";
    ctx.fill();
    ctx.fillStyle = "#e8e6dc";
    ctx.fillRect(mound[0] - 10, mound[1] - 2, 20, 4);
    // foul lines + base paths
    ctx.strokeStyle = "rgba(240,240,232,0.85)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(hx, hy);
    ctx.lineTo(hx - 700, hy - 700);
    ctx.moveTo(hx, hy);
    ctx.lineTo(hx + 700, hy - 700);
    ctx.stroke();
    // batter's boxes
    ctx.lineWidth = 2;
    ctx.strokeRect(hx - 30, hy - 22, 18, 40);
    ctx.strokeRect(hx + 12, hy - 22, 18, 40);
    // bases
    ctx.fillStyle = "#f2f0e8";
    for (const [bx, by] of [first, second, third]) {
      ctx.save();
      ctx.translate(bx, by);
      ctx.rotate(Math.PI / 4);
      ctx.fillRect(-8, -8, 16, 16);
      ctx.restore();
    }
    ctx.beginPath();
    ctx.moveTo(hx - 8, hy - 6);
    ctx.lineTo(hx + 8, hy - 6);
    ctx.lineTo(hx + 8, hy + 2);
    ctx.lineTo(hx, hy + 9);
    ctx.lineTo(hx - 8, hy + 2);
    ctx.closePath();
    ctx.fill();
    // backstop (chain-link arc)
    ctx.strokeStyle = "#8d9399";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.arc(hx, hy, 85, Math.PI * 0.15, Math.PI * 0.85);
    ctx.stroke();
    ctx.strokeStyle = "rgba(0,0,0,0.25)";
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.arc(hx, hy + 6, 85, Math.PI * 0.2, Math.PI * 0.8);
    ctx.stroke();
  });
}

/** Wood-chip playground with a play structure, swings, a dome and a sandbox. */
function playground(scene: Phaser.Scene) {
  return canvasTexture(scene, "sy-playground", 1300, 1000, (ctx, w, h) => {
    const rnd = mulberry32(31);
    roundRect(ctx, 10, 10, w - 20, h - 20, 60);
    ctx.fillStyle = C.chips;
    ctx.fill();
    ctx.save();
    ctx.clip();
    speckle(ctx, rnd, w, h, 22000, ["#6a4d32", "#8d6c4a", "#5e432b", "#9a7a55"], 3);
    ctx.restore();
    roundRect(ctx, 10, 10, w - 20, h - 20, 60);
    ctx.strokeStyle = C.woodDark;
    ctx.lineWidth = 12;
    ctx.stroke();

    const shadow = (fn: () => void) => {
      ctx.save();
      ctx.translate(8, 10);
      ctx.fillStyle = "rgba(0,0,0,0.28)";
      ctx.strokeStyle = "rgba(0,0,0,0.28)";
      fn();
      ctx.restore();
    };

    // --- play structure: two decks, roof, slide, ladder, bridge
    const deck = (x: number, y: number, s: number) => {
      ctx.fillStyle = C.wood;
      ctx.fillRect(x, y, s, s);
      ctx.strokeStyle = C.woodDark;
      ctx.lineWidth = 2;
      for (let i = 1; i < 6; i++) {
        ctx.beginPath();
        ctx.moveTo(x, y + (s / 6) * i);
        ctx.lineTo(x + s, y + (s / 6) * i);
        ctx.stroke();
      }
      ctx.strokeRect(x, y, s, s);
      ctx.fillStyle = "#4f6e8c";
      for (const [px, py] of [
        [x, y],
        [x + s, y],
        [x, y + s],
        [x + s, y + s],
      ])
        ctx.fillRect(px - 6, py - 6, 12, 12);
    };
    shadow(() => ctx.fillRect(300, 230, 420, 150));
    deck(300, 230, 150);
    deck(570, 230, 150);
    // bridge
    ctx.fillStyle = "#7a5a39";
    ctx.fillRect(450, 280, 120, 50);
    ctx.strokeStyle = C.woodDark;
    for (let x = 455; x < 570; x += 12) {
      ctx.beginPath();
      ctx.moveTo(x, 280);
      ctx.lineTo(x, 330);
      ctx.stroke();
    }
    ctx.strokeStyle = "#4f6e8c";
    ctx.lineWidth = 4;
    ctx.strokeRect(450, 280, 120, 50);
    // roof on first deck
    ctx.fillStyle = "#9a4a3c";
    ctx.beginPath();
    ctx.moveTo(290, 220);
    ctx.lineTo(460, 220);
    ctx.lineTo(375, 305);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#b45a49";
    ctx.beginPath();
    ctx.moveTo(290, 220);
    ctx.lineTo(375, 305);
    ctx.lineTo(290, 390);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#87402f";
    ctx.beginPath();
    ctx.moveTo(460, 220);
    ctx.lineTo(460, 390);
    ctx.lineTo(375, 305);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#a35242";
    ctx.beginPath();
    ctx.moveTo(290, 390);
    ctx.lineTo(460, 390);
    ctx.lineTo(375, 305);
    ctx.closePath();
    ctx.fill();
    // slide off the second deck
    shadow(() => roundRect(ctx, 720, 270, 240, 70, 30));
    ctx.fill();
    ctx.fillStyle = "#c9a43f";
    roundRect(ctx, 720, 270, 240, 70, 30);
    ctx.fill();
    ctx.fillStyle = "#e0c06a";
    roundRect(ctx, 730, 285, 215, 40, 20);
    ctx.fill();
    // ladder below deck 1
    ctx.strokeStyle = "#5f6b75";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(340, 380);
    ctx.lineTo(340, 470);
    ctx.moveTo(410, 380);
    ctx.lineTo(410, 470);
    ctx.stroke();
    ctx.lineWidth = 3;
    for (let y = 395; y < 470; y += 18) {
      ctx.beginPath();
      ctx.moveTo(340, y);
      ctx.lineTo(410, y);
      ctx.stroke();
    }
    // climbing wall below deck 2
    ctx.fillStyle = "#4d6f62";
    ctx.fillRect(590, 380, 110, 80);
    for (let i = 0; i < 14; i++) {
      ctx.fillStyle = ["#c9a43f", "#b45a49", "#5b86b0"][i % 3];
      ctx.beginPath();
      ctx.arc(598 + rnd() * 94, 388 + rnd() * 64, 5, 0, Math.PI * 2);
      ctx.fill();
    }

    // --- swing set
    const sx = 780;
    const sy = 610;
    const sw = 420;
    for (let i = 0; i < 4; i++) {
      const x = sx + 50 + i * 105;
      ctx.fillStyle = "rgba(70,50,32,0.6)";
      ctx.beginPath();
      ctx.ellipse(x, sy + 95, 34, 18, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    shadow(() => ctx.fillRect(sx, sy - 4, sw, 10));
    ctx.strokeStyle = "#566573";
    ctx.lineWidth = 7;
    for (const x of [sx, sx + sw]) {
      ctx.beginPath();
      ctx.moveTo(x - 30, sy + 50);
      ctx.lineTo(x, sy);
      ctx.lineTo(x + 30, sy + 50);
      ctx.stroke();
    }
    ctx.fillStyle = "#6e8496";
    ctx.fillRect(sx - 4, sy - 5, sw + 8, 10);
    for (let i = 0; i < 4; i++) {
      const x = sx + 50 + i * 105;
      ctx.strokeStyle = "#a7adb2";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x - 14, sy + 4);
      ctx.lineTo(x - 14, sy + 82);
      ctx.moveTo(x + 14, sy + 4);
      ctx.lineTo(x + 14, sy + 82);
      ctx.stroke();
      ctx.fillStyle = "#2b2f33";
      roundRect(ctx, x - 18, sy + 80, 36, 12, 5);
      ctx.fill();
    }

    // --- climbing dome
    const dx = 230;
    const dy = 700;
    ctx.fillStyle = "rgba(0,0,0,0.25)";
    ctx.beginPath();
    ctx.ellipse(dx + 12, dy + 14, 118, 112, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#c27a3e";
    ctx.lineWidth = 4;
    for (let r = 30; r <= 110; r += 26) {
      ctx.beginPath();
      ctx.arc(dx, dy, r, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(dx + Math.cos(a) * 30, dy + Math.sin(a) * 30);
      ctx.lineTo(dx + Math.cos(a) * 110, dy + Math.sin(a) * 110);
      ctx.stroke();
    }

    // --- merry-go-round
    const mx = 560;
    const my = 720;
    ctx.fillStyle = "rgba(0,0,0,0.25)";
    ctx.beginPath();
    ctx.arc(mx + 8, my + 10, 80, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#5b86b0";
    ctx.beginPath();
    ctx.arc(mx, my, 80, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#c9a43f";
    for (let i = 0; i < 6; i += 2) {
      ctx.beginPath();
      ctx.moveTo(mx, my);
      ctx.arc(mx, my, 80, (i / 6) * Math.PI * 2, ((i + 1) / 6) * Math.PI * 2);
      ctx.closePath();
      ctx.fill();
    }
    ctx.strokeStyle = "#d8dde2";
    ctx.lineWidth = 4;
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(mx + Math.cos(a) * 20, my + Math.sin(a) * 20);
      ctx.lineTo(mx + Math.cos(a) * 72, my + Math.sin(a) * 72);
      ctx.stroke();
    }
    ctx.fillStyle = "#d8dde2";
    ctx.beginPath();
    ctx.arc(mx, my, 14, 0, Math.PI * 2);
    ctx.fill();

    // --- sandbox
    const bx = 80;
    const by = 90;
    ctx.fillStyle = C.woodDark;
    ctx.fillRect(bx, by, 170, 130);
    ctx.fillStyle = C.sand;
    ctx.fillRect(bx + 10, by + 10, 150, 110);
    ctx.save();
    ctx.beginPath();
    ctx.rect(bx + 10, by + 10, 150, 110);
    ctx.clip();
    for (let i = 0; i < 600; i++) {
      ctx.fillStyle = rnd() < 0.5 ? "rgba(150,130,90,0.5)" : "rgba(225,210,170,0.5)";
      ctx.fillRect(bx + 10 + rnd() * 150, by + 10 + rnd() * 110, 2, 2);
    }
    ctx.fillStyle = "rgba(230,215,175,0.6)";
    ctx.beginPath();
    ctx.ellipse(bx + 60, by + 60, 26, 16, 0.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.fillStyle = "#b45a49";
    ctx.beginPath();
    ctx.arc(bx + 120, by + 85, 9, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#5b86b0";
    ctx.fillRect(bx + 95, by + 40, 24, 6);

    // --- spring riders
    for (const [rx, ry, col] of [
      [880, 840, "#b45a49"],
      [990, 860, "#5b86b0"],
      [1100, 830, "#c9a43f"],
    ] as [number, number, string][]) {
      ctx.fillStyle = "rgba(0,0,0,0.25)";
      ctx.beginPath();
      ctx.ellipse(rx + 6, ry + 8, 24, 14, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.ellipse(rx, ry, 22, 12, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(rx + 18, ry - 6, 8, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}

// ---------------------------------------------------------------------------
// Props

function treeTexture(scene: Phaser.Scene, variant: number) {
  const key = `sy-tree-${variant}`;
  return canvasTexture(scene, key, 170, 180, (ctx, w) => {
    const rnd = mulberry32(100 + variant);
    const palettes = [
      ["#2c5228", "#386633", "#467a3d", "#5a8f4c"],
      ["#2f4f2a", "#3d6235", "#4d7541", "#628a52"],
      ["#34512b", "#456a35", "#557c42", "#6b9354"],
    ][variant % 3];
    const cx = w / 2;
    const cy = 78;
    // ground shadow
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.beginPath();
    ctx.ellipse(cx + 16, 150, 62, 24, 0, 0, Math.PI * 2);
    ctx.fill();
    // trunk
    ctx.fillStyle = "#5a3f27";
    ctx.fillRect(cx - 7, 110, 14, 42);
    ctx.fillStyle = "#6e4f33";
    ctx.fillRect(cx - 7, 110, 5, 42);
    // canopy: dark base, then lighter clusters toward the top-left
    const blob = (x: number, y: number, r: number, col: string) => {
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    };
    blob(cx, cy, 62, palettes[0]);
    for (let i = 0; i < 9; i++) {
      const a = rnd() * Math.PI * 2;
      blob(cx + Math.cos(a) * 34, cy + Math.sin(a) * 30, 28 + rnd() * 8, palettes[0]);
    }
    for (let i = 0; i < 10; i++) {
      const a = rnd() * Math.PI * 2;
      const d = rnd() * 30;
      blob(cx - 6 + Math.cos(a) * d, cy - 6 + Math.sin(a) * d, 20 + rnd() * 10, palettes[1]);
    }
    for (let i = 0; i < 8; i++) {
      blob(cx - 18 + rnd() * 26, cy - 24 + rnd() * 24, 10 + rnd() * 8, palettes[2]);
    }
    for (let i = 0; i < 6; i++) {
      blob(cx - 22 + rnd() * 20, cy - 30 + rnd() * 16, 5 + rnd() * 5, palettes[3]);
    }
    // outline-ish rim
    ctx.strokeStyle = "rgba(15,30,12,0.5)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, 63, 0, Math.PI * 2);
    ctx.stroke();
  });
}

function bushTexture(scene: Phaser.Scene, variant: number) {
  return canvasTexture(scene, `sy-bush-${variant}`, 90, 70, (ctx, w) => {
    const rnd = mulberry32(200 + variant);
    ctx.fillStyle = "rgba(0,0,0,0.25)";
    ctx.beginPath();
    ctx.ellipse(w / 2 + 8, 52, 36, 13, 0, 0, Math.PI * 2);
    ctx.fill();
    const cols = ["#2f5a2b", "#3c6b35", "#4b7d40"];
    for (let layer = 0; layer < 3; layer++) {
      for (let i = 0; i < 6; i++) {
        ctx.fillStyle = cols[layer];
        ctx.beginPath();
        ctx.arc(20 + rnd() * 50 - layer * 3, 26 + rnd() * 18 - layer * 5, 15 - layer * 3 + rnd() * 5, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    if (variant === 1) {
      for (let i = 0; i < 9; i++) {
        ctx.fillStyle = i % 2 ? "#d8c46a" : "#c97a8a";
        ctx.beginPath();
        ctx.arc(20 + rnd() * 50, 20 + rnd() * 24, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  });
}

function benchTexture(scene: Phaser.Scene) {
  return canvasTexture(scene, "sy-bench", 120, 60, ctx => {
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.fillRect(14, 30, 100, 24);
    // legs
    ctx.fillStyle = "#3d4247";
    ctx.fillRect(14, 20, 6, 30);
    ctx.fillRect(100, 20, 6, 30);
    // backrest
    ctx.fillStyle = C.woodDark;
    ctx.fillRect(8, 8, 104, 9);
    // seat planks
    ctx.fillStyle = C.wood;
    ctx.fillRect(8, 22, 104, 8);
    ctx.fillRect(8, 32, 104, 8);
    ctx.fillStyle = "rgba(255,255,255,0.12)";
    ctx.fillRect(8, 22, 104, 2);
    ctx.fillRect(8, 32, 104, 2);
  });
}

function picnicTexture(scene: Phaser.Scene) {
  return canvasTexture(scene, "sy-picnic", 150, 120, ctx => {
    ctx.fillStyle = "rgba(0,0,0,0.26)";
    ctx.fillRect(22, 22, 120, 92);
    ctx.fillStyle = C.wood;
    ctx.fillRect(15, 10, 120, 18); // bench
    ctx.fillRect(15, 88, 120, 18); // bench
    ctx.fillStyle = "#93704a";
    ctx.fillRect(10, 36, 130, 44); // table top
    ctx.strokeStyle = C.woodDark;
    ctx.lineWidth = 2;
    for (let y = 47; y < 80; y += 11) {
      ctx.beginPath();
      ctx.moveTo(10, y);
      ctx.lineTo(140, y);
      ctx.stroke();
    }
    ctx.strokeRect(10, 36, 130, 44);
  });
}

// ---------------------------------------------------------------------------

function overlaps(r: Rect, x: number, y: number, pad: number) {
  return x > r.x - pad && x < r.x + r.w + pad && y > r.y - pad && y < r.y + r.h + pad;
}

export function createSchoolyard(scene: Phaser.Scene, worldW: number, worldH: number) {
  const rnd = mulberry32(2026);

  // --- grass base + large-scale variation.
  // Phaser's TileSprite allocates a canvas as big as the sprite, so a
  // 5000x5000 one would cost ~100MB. Instead each layer is a TileSprite just
  // larger than the camera view that is re-aligned to the tile grid every
  // frame, which looks identical to an infinite tiled ground.
  const groundLayers = [
    { key: grassTile(scene), depth: DEPTH.grass },
    { key: patchTile(scene), depth: DEPTH.patches },
  ].map(({ key, depth }) =>
    scene.add.tileSprite(0, 0, GRASS_TILE, GRASS_TILE, key).setOrigin(0).setDepth(depth)
  );
  const alignGround = () => {
    const view = scene.cameras.main.worldView;
    const x = Math.floor(view.x / GRASS_TILE) * GRASS_TILE - GRASS_TILE;
    const y = Math.floor(view.y / GRASS_TILE) * GRASS_TILE - GRASS_TILE;
    const w = (Math.ceil(view.width / GRASS_TILE) + 3) * GRASS_TILE;
    const h = (Math.ceil(view.height / GRASS_TILE) + 3) * GRASS_TILE;
    for (const layer of groundLayers) {
      if (layer.width !== w || layer.height !== h) layer.setSize(w, h);
      layer.setPosition(x, y);
      layer.setTilePosition(x, y);
    }
  };
  alignGround();
  scene.events.on(Phaser.Scenes.Events.POST_UPDATE, alignGround);

  // --- the fenced yard (see world.ts). Kids stop with their collision
  // circle against these lines. A kid's feet are at the bottom of its
  // circle, so the top fence is drawn with its base on the foot line of a
  // kid pressed against the top wall: the fence is exactly where they stop.
  const yard = {
    left: WALL_LEFT,
    top: WALL_TOP + 2 * PLAYER_RADIUS,
    right: worldW - WALL_RIGHT,
    bottom: worldH - WALL_BOTTOM,
  };
  scene.events.once(Phaser.Scenes.Events.SHUTDOWN, () =>
    scene.events.off(Phaser.Scenes.Events.POST_UPDATE, alignGround)
  );

  // --- areas (positions on multiples of the grass tile so the grass
  // pattern inside the track/diamond lines up with the world grass)
  const areas: Record<string, Rect> = {
    blacktop: { x: 256, y: 512, w: 1920, h: 1140 },
    track: { x: 2816, y: 512, w: 1900, h: 900 },
    diamond: { x: 512, y: 2816, w: 1100, h: 1000 },
    playground: { x: 3072, y: 3072, w: 1300, h: 1000 },
  };
  scene.add.image(areas.blacktop.x, areas.blacktop.y, blacktop(scene)).setOrigin(0).setDepth(DEPTH.areas);
  scene.add.image(areas.track.x, areas.track.y, track(scene)).setOrigin(0).setDepth(DEPTH.areas);
  scene.add.image(areas.diamond.x, areas.diamond.y, diamond(scene)).setOrigin(0).setDepth(DEPTH.areas);
  scene.add.image(areas.playground.x, areas.playground.y, playground(scene)).setOrigin(0).setDepth(DEPTH.areas);

  // --- ground: mulch strip along the fence (no paths through the lawns:
  // the grass runs right up to the blacktop, track, diamond and playground)
  const g = scene.add.graphics().setDepth(DEPTH.ground);
  const strip = 64;
  const yw = yard.right - yard.left;
  const yh = yard.bottom - yard.top;
  g.fillStyle(0x5a4733, 0.55);
  g.fillRect(yard.left, yard.top, yw, strip);
  g.fillRect(yard.left, yard.bottom - strip, yw, strip);
  g.fillRect(yard.left, yard.top + strip, strip, yh - 2 * strip);
  g.fillRect(yard.right - strip, yard.top + strip, strip, yh - 2 * strip);
  g.fillStyle(0x3e3124, 0.35);
  g.fillRect(yard.left + strip, yard.top + strip, yw - 2 * strip, 4);
  g.fillRect(yard.left + strip, yard.bottom - strip - 4, yw - 2 * strip, 4);
  g.fillRect(yard.left + strip, yard.top + strip, 4, yh - 2 * strip);
  g.fillRect(yard.right - strip - 4, yard.top + strip, 4, yh - 2 * strip);

  // Outside the fence: a street and sidewalk along the top (the deep
  // margin that keeps labels on screen), plain pavement on the other sides.
  const outTop = yard.top - FENCE_T;
  g.fillStyle(0xa3a29a, 1); // pavement everywhere outside
  g.fillRect(0, 0, worldW, outTop);
  g.fillRect(0, yard.bottom + FENCE_T, worldW, worldH - yard.bottom - FENCE_T);
  g.fillRect(0, 0, yard.left - FENCE_T, worldH);
  g.fillRect(yard.right + FENCE_T, 0, worldW - yard.right - FENCE_T, worldH);
  const road = Math.round(outTop * 0.42);
  g.fillStyle(0x4d5055, 1);
  g.fillRect(0, 0, worldW, road);
  g.fillStyle(0xd9c25a, 0.8); // dashed centre line
  for (let x = 20; x < worldW; x += 90) g.fillRect(x, Math.round(road / 2) - 2, 46, 4);
  g.fillStyle(0xc4c1b7, 1); // curb
  g.fillRect(0, road, worldW, 5);
  g.fillStyle(0x58744a, 1); // grass verge along the fence
  g.fillRect(0, outTop - 10, worldW, 10);
  g.lineStyle(2, 0x8a8981, 0.9); // sidewalk joints
  for (let x = 0; x < worldW; x += 56) g.lineBetween(x, road + 5, x, outTop - 10);

  // --- props
  const blocked: Rect[] = [...Object.values(areas)];
  const free = (x: number, y: number, pad: number) =>
    !blocked.some(r => overlaps(r, x, y, pad)) && Math.hypot(x - 400, y - 300) > 160; // keep the spawn point clear

  const occluders: Occluder[] = [];

  /** Short props (benches, picnic): stay under kids, no occlusion. */
  const shortProp = (key: string, x: number, y: number) =>
    scene.add
      .image(x, y, key)
      .setOrigin(0.5, 0.85)
      .setDepth(DEPTH.props + y / 100000);

  /**
   * Tall foliage: Y-sorted with kids. `canopy` is the leafy footprint relative
   * to the ground point (x, y) — kids whose feet are north of `y` and overlap
   * it see the prop go translucent so they can't fully hide.
   */
  const tallProp = (
    key: string,
    x: number,
    y: number,
    canopy: { halfW: number; up: number; down: number }
  ) => {
    const img = scene.add.image(x, y, key).setOrigin(0.5, 0.85).setDepth(propDepth(y));
    occluders.push({
      view: img,
      baseY: y,
      left: x - canopy.halfW,
      right: x + canopy.halfW,
      top: y - canopy.up,
      bottom: y - canopy.down,
    });
    return img;
  };

  const trees = [0, 1, 2].map(v => treeTexture(scene, v));
  const bushes = [0, 1].map(v => bushTexture(scene, v));
  const bench = benchTexture(scene);
  const picnic = picnicTexture(scene);

  const placeTree = (x: number, y: number) =>
    tallProp(trees[(rnd() * 3) | 0], x, y, { halfW: 58, up: 145, down: 18 });
  const placeBush = (x: number, y: number) =>
    tallProp(bushes[(rnd() * 2) | 0], x, y, { halfW: 38, up: 55, down: 8 });

  // a row of trees and bushes just inside the fence
  const edgeSpots: [number, number][] = [];
  for (let t = yard.left + 120; t < yard.right - 120; t += 210 + rnd() * 120) {
    const inset = 80 + rnd() * 50;
    edgeSpots.push([t, yard.top + inset], [t + 60, yard.bottom - inset]);
  }
  for (let t = yard.top + 120; t < yard.bottom - 120; t += 210 + rnd() * 120) {
    const inset = 80 + rnd() * 50;
    edgeSpots.push([yard.left + inset, t], [yard.right - inset, t + 60]);
  }
  for (const [x, y] of edgeSpots) {
    if (!free(x, y, 70)) continue;
    if (rnd() < 0.62) placeTree(x, y);
    else placeBush(x, y);
  }
  // scattered trees and bush clumps in the open lawns
  let placed = 0;
  for (let i = 0; i < 400 && placed < 70; i++) {
    const x = 300 + rnd() * (worldW - 600);
    const y = 300 + rnd() * (worldH - 600);
    if (!free(x, y, 110)) continue;
    placed++;
    if (rnd() < 0.55) placeTree(x, y);
    else for (let k = 0; k < 3; k++) placeBush(x + (k - 1) * 46, y + (rnd() - 0.5) * 20);
  }

  // benches by the blacktop, the track and the playground
  const benchSpots: [number, number][] = [
    [500, 1720],
    [800, 1720],
    [1500, 1720],
    [1800, 1720],
    [3300, 1480],
    [3700, 1480],
    [4100, 1480],
    [3200, 4140],
    [3600, 4140],
    [4000, 4140],
    [1300, 3900],
    [800, 3900],
  ];
  for (const [x, y] of benchSpots) shortProp(bench, x, y);
  // picnic lawn
  for (let i = 0; i < 6; i++) shortProp(picnic, 2700 + (i % 3) * 230, 4440 + Math.floor(i / 3) * 190);

  // --- cover everything outside the world (only visible if the camera is
  // zoomed out past the world bounds, since the ground layers follow the view)
  const outside = scene.add.graphics().setDepth(DEPTH.fenceBehind - 1);
  const far = 20000;
  outside.fillStyle(0x171b24, 1);
  outside.fillRect(-far, -far, worldW + 2 * far, far);
  outside.fillRect(-far, worldH, worldW + 2 * far, far);
  outside.fillRect(-far, 0, far, worldH);
  outside.fillRect(worldW, 0, far, worldH);

  // --- fence: Y-sorted with kids. Horizontal bands are one baseY; vertical
  // runs are split into short segments so a kid north of a section sorts
  // behind it. Visual only — walls / bounds are unchanged.
  const fenceH = fenceTile(scene, false);
  const fenceV = fenceTile(scene, true);
  const SEG = 1024;
  const FENCE_SEG_Y = 64; // vertical fence chunk height for depth sorting
  const x0 = yard.left - FENCE_T;
  const x1 = yard.right + FENCE_T;
  const y0 = yard.top - FENCE_T;
  const y1 = yard.bottom + FENCE_T;

  const addFenceH = (x: number, y: number, w: number) => {
    // Horizontal band: base is the bottom edge of the mesh.
    const baseY = y + FENCE_T;
    const tile = scene.add
      .tileSprite(x, y, w, FENCE_T, fenceH)
      .setOrigin(0)
      .setDepth(propDepth(baseY))
      .setTilePosition(x, 0);
    occluders.push({
      view: tile,
      baseY,
      left: x,
      right: x + w,
      top: y,
      bottom: baseY,
    });
  };
  const addFenceV = (x: number, y: number, h: number) => {
    const tile = scene.add
      .tileSprite(x, y, FENCE_T, h, fenceV)
      .setOrigin(0)
      .setDepth(propDepth(y + h))
      .setTilePosition(0, y);
    occluders.push({
      view: tile,
      baseY: y + h,
      left: x,
      right: x + FENCE_T,
      top: y,
      bottom: y + h,
    });
  };

  for (let t = x0; t < x1; t += SEG) {
    const len = Math.min(SEG, x1 - t);
    addFenceH(t, y0, len);
    addFenceH(t, yard.bottom, len);
  }
  for (let t = y0; t < y1; t += FENCE_SEG_Y) {
    const len = Math.min(FENCE_SEG_Y, y1 - t);
    addFenceV(x0, t, len);
    addFenceV(yard.right, t, len);
  }

  /**
   * Each frame: if any kid's feet are north of an occluder's base and their
   * body overlaps its canopy/mesh, fade that prop so the kid (and labels)
   * stay visible. Feet south of the base → prop stays opaque and sorts
   * behind the kid via depth.
   */
  const updateOcclusion = (feet: ReadonlyArray<{ x: number; y: number; top: number }>) => {
    for (const o of occluders) {
      let hide = false;
      for (const k of feet) {
        // Feet at/below the base → in front (no fade).
        if (k.y >= o.baseY - 4) continue;
        // Rough body/label box vs canopy footprint.
        const half = 22;
        if (k.x + half < o.left || k.x - half > o.right) continue;
        if (k.top > o.bottom || k.y + 8 < o.top) continue;
        hide = true;
        break;
      }
      const a = hide ? OCCLUDE_ALPHA : 1;
      if (o.view.alpha !== a) o.view.setAlpha(a);
    }
  };

  return { occluders, updateOcclusion };
}
