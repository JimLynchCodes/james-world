/**
 * Procedural side-scroller stage: parallax sky/city, mid props, walkable lane,
 * themed sections and clear gate markers (Simpsons / TMNT arcade vibe).
 */
import Phaser from "phaser";

/** Keep in sync with server WORLD_W / LANE_* and client BRAWLER. */
const MAP = { w: 7000, laneTop: 120, laneBottom: 230, groundY: 200 } as const;

export type ParallaxLayers = {
  far: Phaser.GameObjects.TileSprite;
  mid: Phaser.GameObjects.TileSprite;
  ground: Phaser.GameObjects.TileSprite;
  near: Phaser.GameObjects.Container;
};

export type StageBuild = {
  layers: ParallaxLayers;
  /** World x of each segment trigger (gates). */
  gates: number[];
};

const SECTION = [
  { name: "yard", from: 0, to: 400, ground: 0x6b9e4a, accent: 0x8bc34a },
  { name: "street", from: 400, to: 1100, ground: 0x5a5a5a, accent: 0x777777 },
  { name: "park", from: 1100, to: 1800, ground: 0x4f8a45, accent: 0x7ec87a },
  { name: "alley", from: 1800, to: 2500, ground: 0x4a3f35, accent: 0x6d5a4a },
  { name: "warehouse", from: 2500, to: 3400, ground: 0x5a5a48, accent: 0x8a8060 },
  { name: "rooftop", from: 3400, to: 4200, ground: 0x4a4a55, accent: 0x6a7088 },
  { name: "plaza", from: 4200, to: 5000, ground: 0x8a7a5a, accent: 0xb0a070 },
  { name: "docks", from: 5000, to: 5800, ground: 0x4a5560, accent: 0x6a7a8a },
  { name: "arena", from: 5800, to: 7000, ground: 0x5a3040, accent: 0x8a4055 },
] as const;

/** Default segment triggers — keep in sync with server `segment_trigger`. */
export const DEFAULT_GATES = [380, 1000, 1650, 2350, 3100, 3850, 4600, 5350, 6100];

function tex(scene: Phaser.Scene, key: string, w: number, h: number, draw: (g: Phaser.GameObjects.Graphics) => void) {
  if (scene.textures.exists(key)) return;
  const g = scene.make.graphics({ x: 0, y: 0 });
  draw(g);
  g.generateTexture(key, w, h);
  g.destroy();
  scene.textures.get(key).setFilter(Phaser.Textures.FilterMode.NEAREST);
}

export function ensureStageTextures(scene: Phaser.Scene) {
  tex(scene, "brawler-far", 320, 180, g => {
    g.fillGradientStyle(0x5eb0ff, 0x5eb0ff, 0xffd9a0, 0xffc070, 1);
    g.fillRect(0, 0, 320, 180);
    g.fillStyle(0xffffff, 0.55);
    g.fillCircle(40, 40, 18);
    g.fillCircle(55, 42, 14);
    g.fillCircle(28, 48, 12);
    g.fillCircle(200, 30, 16);
    g.fillCircle(218, 34, 12);
    g.fillStyle(0x7ec87a, 1);
    g.fillTriangle(0, 180, 80, 110, 160, 180);
    g.fillTriangle(120, 180, 220, 100, 320, 180);
  });

  tex(scene, "brawler-mid", 400, 160, g => {
    g.fillStyle(0x000000, 0);
    g.fillRect(0, 0, 400, 160);
    const buildings: Array<[number, number, number, number]> = [
      [10, 60, 50, 100],
      [70, 40, 40, 120],
      [120, 70, 55, 90],
      [190, 30, 45, 130],
      [250, 55, 60, 105],
      [320, 45, 50, 115],
    ];
    for (const [x, y, w, h] of buildings) {
      g.fillStyle(0x3a4a6a, 1);
      g.fillRect(x, y, w, h);
      g.fillStyle(0xffe080, 0.7);
      for (let wy = y + 8; wy < y + h - 8; wy += 14) {
        for (let wx = x + 6; wx < x + w - 6; wx += 12) {
          g.fillRect(wx, wy, 5, 6);
        }
      }
    }
    g.fillStyle(0x2d5a2a, 1);
    for (const tx of [55, 175, 310]) {
      g.fillTriangle(tx, 100, tx + 18, 50, tx + 36, 100);
      g.fillStyle(0x5c4030, 1);
      g.fillRect(tx + 14, 100, 8, 40);
      g.fillStyle(0x2d5a2a, 1);
    }
  });

  tex(scene, "brawler-ground", 64, 128, g => {
    g.fillStyle(0x6b4a2e, 1);
    g.fillRect(0, 0, 64, 128);
    g.fillStyle(0x5a3c24, 1);
    for (let y = 0; y < 128; y += 8) g.fillRect(0, y, 64, 3);
    g.fillStyle(0x7a5a3a, 0.5);
    g.fillRect(0, 0, 64, 10);
  });

  tex(scene, "brawler-near", 96, 48, g => {
    g.fillStyle(0x3a2818, 1);
    g.fillRect(0, 24, 96, 24);
    g.fillStyle(0x2a1c10, 1);
    for (let x = 0; x < 96; x += 16) g.fillRect(x, 24, 8, 4);
    g.fillStyle(0x8a7060, 1);
    g.fillRect(0, 20, 96, 5);
  });

  tex(scene, "brawler-gate", 28, 72, g => {
    g.fillStyle(0xc45c26, 1);
    g.fillRect(8, 0, 12, 72);
    g.fillStyle(0xffe680, 1);
    g.fillTriangle(2, 8, 14, 0, 26, 8);
    g.fillStyle(0xffffff, 1);
    g.fillRect(10, 20, 8, 18);
  });

  tex(scene, "brawler-barrel", 22, 28, g => {
    g.fillStyle(0x8b4513, 1);
    g.fillRoundedRect(1, 1, 20, 26, 3);
    g.lineStyle(2, 0x5c2e0a, 1);
    g.strokeRoundedRect(1, 1, 20, 26, 3);
    g.lineStyle(2, 0xd4a017, 1);
    g.strokeRect(1, 8, 20, 3);
    g.strokeRect(1, 18, 20, 3);
  });
  tex(scene, "brawler-crate", 26, 22, g => {
    g.fillStyle(0xb8860b, 1);
    g.fillRect(1, 1, 24, 20);
    g.lineStyle(2, 0x5c4010, 1);
    g.strokeRect(1, 1, 24, 20);
    g.lineBetween(1, 11, 25, 11);
    g.lineBetween(13, 1, 13, 21);
  });
  tex(scene, "brawler-hydrant", 16, 24, g => {
    g.fillStyle(0xcc2233, 1);
    g.fillRect(4, 6, 8, 18);
    g.fillCircle(8, 6, 6);
    g.fillRect(0, 10, 16, 5);
  });
  tex(scene, "brawler-lamp", 12, 48, g => {
    g.fillStyle(0x333333, 1);
    g.fillRect(4, 12, 4, 36);
    g.fillStyle(0xffe080, 1);
    g.fillCircle(6, 10, 7);
  });
  // Park bench
  tex(scene, "brawler-bench", 36, 18, g => {
    g.fillStyle(0x6b4423, 1);
    g.fillRect(2, 8, 32, 4);
    g.fillRect(4, 12, 4, 6);
    g.fillRect(28, 12, 4, 6);
    g.fillStyle(0x8b5a2b, 1);
    g.fillRect(2, 4, 32, 4);
  });
  // Tree (park)
  tex(scene, "brawler-tree", 28, 40, g => {
    g.fillStyle(0x5c4030, 1);
    g.fillRect(11, 22, 6, 18);
    g.fillStyle(0x2d7a2a, 1);
    g.fillCircle(14, 16, 12);
    g.fillCircle(8, 20, 8);
    g.fillCircle(20, 20, 8);
  });
  // Dumpster (alley / warehouse)
  tex(scene, "brawler-dumpster", 34, 26, g => {
    g.fillStyle(0x3a6a3a, 1);
    g.fillRoundedRect(1, 6, 32, 20, 2);
    g.fillStyle(0x2a4a2a, 1);
    g.fillRect(1, 6, 32, 5);
    g.fillStyle(0x888888, 1);
    g.fillRect(6, 2, 8, 5);
    g.fillRect(20, 2, 8, 5);
  });
  // AC unit (rooftop)
  tex(scene, "brawler-ac", 28, 20, g => {
    g.fillStyle(0x888898, 1);
    g.fillRect(1, 4, 26, 16);
    g.lineStyle(1, 0x555566, 1);
    g.strokeRect(1, 4, 26, 16);
    g.fillStyle(0x333344, 1);
    for (let i = 0; i < 4; i++) g.fillRect(5 + i * 5, 7, 3, 10);
  });
  // Vent / chimney (rooftop)
  tex(scene, "brawler-vent", 18, 28, g => {
    g.fillStyle(0x666670, 1);
    g.fillRect(4, 8, 10, 20);
    g.fillStyle(0x888890, 1);
    g.fillRect(2, 4, 14, 6);
    g.fillStyle(0xccccd0, 0.5);
    g.fillCircle(9, 2, 4);
  });
  // Cone (street / plaza)
  tex(scene, "brawler-cone", 14, 20, g => {
    g.fillStyle(0xff6600, 1);
    g.fillTriangle(7, 0, 0, 20, 14, 20);
    g.fillStyle(0xffffff, 1);
    g.fillRect(3, 10, 8, 3);
  });
  // Bollard (docks / plaza)
  tex(scene, "brawler-bollard", 12, 22, g => {
    g.fillStyle(0xccaa22, 1);
    g.fillRect(2, 6, 8, 16);
    g.fillCircle(6, 6, 5);
    g.fillStyle(0x222222, 1);
    g.fillRect(2, 12, 8, 3);
  });
}

function sectionAt(x: number) {
  return SECTION.find(s => x >= s.from && x < s.to) ?? SECTION[SECTION.length - 1];
}

function propKeyFor(secName: string, r: number): string {
  switch (secName) {
    case "street":
      return r > 0.55 ? "brawler-hydrant" : r > 0.25 ? "brawler-cone" : "brawler-crate";
    case "park":
      return r > 0.5 ? "brawler-tree" : "brawler-bench";
    case "alley":
      return r > 0.45 ? "brawler-dumpster" : "brawler-barrel";
    case "warehouse":
      return r > 0.5 ? "brawler-crate" : r > 0.25 ? "brawler-dumpster" : "brawler-barrel";
    case "rooftop":
      return r > 0.5 ? "brawler-ac" : "brawler-vent";
    case "plaza":
      return r > 0.55 ? "brawler-bollard" : r > 0.25 ? "brawler-cone" : "brawler-lamp";
    case "docks":
      return r > 0.45 ? "brawler-bollard" : r > 0.2 ? "brawler-crate" : "brawler-barrel";
    case "arena":
      return r > 0.5 ? "brawler-crate" : "brawler-lamp";
    default:
      return r > 0.6 ? "brawler-tree" : "brawler-barrel";
  }
}

/**
 * Build the scrolling stage into the scene. Call once from create().
 * Returns parallax handles + gate xs for camera/GO logic.
 */
export function buildBrawlerStage(scene: Phaser.Scene, gates: number[] = DEFAULT_GATES): StageBuild {
  ensureStageTextures(scene);
  const w = scene.scale.width;
  const h = scene.scale.height;

  const far = scene.add
    .tileSprite(0, 0, w, h, "brawler-far")
    .setOrigin(0, 0)
    .setScrollFactor(0)
    .setDepth(0);

  const mid = scene.add
    .tileSprite(0, h * 0.28, w, 160, "brawler-mid")
    .setOrigin(0, 0)
    .setScrollFactor(0)
    .setDepth(1)
    .setAlpha(0.92);

  for (const sec of SECTION) {
    const midX = (sec.from + sec.to) / 2;
    const width = sec.to - sec.from;
    scene.add
      .rectangle(midX, MAP.laneTop - 30, width, 80, sec.accent, 0.35)
      .setDepth(2);
    scene.add
      .rectangle(midX, (MAP.laneTop + MAP.laneBottom) / 2 + 40, width, 140, sec.ground, 1)
      .setDepth(3);
    scene.add
      .rectangle(midX, MAP.laneTop, width, 3, 0xffffff, 0.25)
      .setDepth(4);
    scene.add
      .rectangle(midX, MAP.laneBottom, width, 3, 0x000000, 0.35)
      .setDepth(4);

    // Section name plate (subtle landmark)
    scene.add
      .text(sec.from + 24, MAP.laneTop - 48, sec.name.toUpperCase(), {
        fontFamily: "monospace",
        fontSize: "11px",
        color: "#ffe680",
        stroke: "#000000",
        strokeThickness: 3,
      })
      .setDepth(8)
      .setAlpha(0.7);
  }

  const ground = scene.add
    .tileSprite(0, MAP.laneBottom + 8, w, 80, "brawler-ground")
    .setOrigin(0, 0)
    .setScrollFactor(0)
    .setDepth(5);

  const near = scene.add.container(0, 0).setDepth(200);

  const propEvery = 130;
  for (let x = 40; x < MAP.w; x += propEvery) {
    const sec = sectionAt(x);
    const roll = (Math.sin(x * 12.9898) * 43758.5453) % 1;
    const r = Math.abs(roll);
    const key = propKeyFor(sec.name, r);
    const side = r > 0.5 ? MAP.laneBottom + 4 : MAP.laneTop - 8;
    const img = scene.add.image(x + (r - 0.5) * 40, side, key).setOrigin(0.5, 1);
    img.setDepth(side >= MAP.laneBottom ? 180 : 6);
    if (side >= MAP.laneBottom) near.add(img);
  }

  // Extra park trees / rooftop vents for density
  for (let x = 1150; x < 1780; x += 160) {
    scene.add.image(x, MAP.laneTop - 6, "brawler-tree").setOrigin(0.5, 1).setDepth(6);
  }
  for (let x = 3450; x < 4150; x += 180) {
    scene.add.image(x, MAP.laneTop - 4, "brawler-vent").setOrigin(0.5, 1).setDepth(6).setAlpha(0.95);
  }

  for (let x = 100; x < MAP.w; x += 280) {
    const sec = sectionAt(x);
    if (sec.name === "park" || sec.name === "rooftop") continue;
    scene.add
      .image(x, MAP.laneTop - 4, "brawler-lamp")
      .setOrigin(0.5, 1)
      .setDepth(6)
      .setAlpha(0.9);
  }

  for (const gx of gates) {
    scene.add.image(gx - 18, MAP.laneTop - 4, "brawler-gate").setOrigin(0.5, 1).setDepth(7);
    scene.add.image(gx + 18, MAP.laneTop - 4, "brawler-gate").setOrigin(0.5, 1).setDepth(7).setFlipX(true);
    scene.add
      .rectangle(gx, (MAP.laneTop + MAP.laneBottom) / 2, 6, MAP.laneBottom - MAP.laneTop + 20, 0xffe680, 0.55)
      .setDepth(4);
  }

  // Boss arena floor flourish (centered near boss gate)
  const arenaX = 6400;
  scene.add
    .rectangle(arenaX, (MAP.laneTop + MAP.laneBottom) / 2, 700, 100, 0x7a2030, 0.45)
    .setDepth(3);
  scene.add
    .rectangle(arenaX, (MAP.laneTop + MAP.laneBottom) / 2, 640, 4, 0xffe680, 0.7)
    .setDepth(4);

  // Warehouse floor stripes
  for (let x = 2550; x < 3350; x += 80) {
    scene.add
      .rectangle(x, (MAP.laneTop + MAP.laneBottom) / 2 + 20, 40, 6, 0xffcc33, 0.35)
      .setDepth(4);
  }

  return { layers: { far, mid, ground, near }, gates };
}

export function resizeParallax(layers: ParallaxLayers, width: number, height: number) {
  layers.far.setSize(width, height);
  layers.mid.setSize(width, 160);
  layers.mid.setY(height * 0.28);
  layers.ground.setSize(width, 80);
}
