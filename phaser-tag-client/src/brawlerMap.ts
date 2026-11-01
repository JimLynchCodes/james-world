/**
 * Procedural side-scroller stage: parallax sky/city, mid props, walkable lane,
 * themed sections and clear gate markers (Simpsons / TMNT arcade vibe).
 */
import Phaser from "phaser";

/** Keep in sync with server WORLD_W / LANE_* and client MAP. */
const MAP = { w: 3600, laneTop: 120, laneBottom: 230, groundY: 200 } as const;

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
  { name: "yard", from: 0, to: 320, ground: 0x6b9e4a, accent: 0x8bc34a },
  { name: "street", from: 320, to: 900, ground: 0x5a5a5a, accent: 0x777777 },
  { name: "alley", from: 900, to: 1500, ground: 0x4a3f35, accent: 0x6d5a4a },
  { name: "plaza", from: 1500, to: 2200, ground: 0x8a7a5a, accent: 0xb0a070 },
  { name: "docks", from: 2200, to: 3000, ground: 0x4a5560, accent: 0x6a7a8a },
  { name: "arena", from: 3000, to: 3600, ground: 0x5a3040, accent: 0x8a4055 },
] as const;

/** Default segment triggers — keep in sync with server `segment_trigger`. */
export const DEFAULT_GATES = [320, 900, 1500, 2200, 3000];

function tex(scene: Phaser.Scene, key: string, w: number, h: number, draw: (g: Phaser.GameObjects.Graphics) => void) {
  if (scene.textures.exists(key)) return;
  const g = scene.make.graphics({ x: 0, y: 0 });
  draw(g);
  g.generateTexture(key, w, h);
  g.destroy();
  scene.textures.get(key).setFilter(Phaser.Textures.FilterMode.NEAREST);
}

export function ensureStageTextures(scene: Phaser.Scene) {
  // Far sky gradient strip
  tex(scene, "brawler-far", 320, 180, g => {
    g.fillGradientStyle(0x5eb0ff, 0x5eb0ff, 0xffd9a0, 0xffc070, 1);
    g.fillRect(0, 0, 320, 180);
    g.fillStyle(0xffffff, 0.55);
    g.fillCircle(40, 40, 18);
    g.fillCircle(55, 42, 14);
    g.fillCircle(28, 48, 12);
    g.fillCircle(200, 30, 16);
    g.fillCircle(218, 34, 12);
    // Distant hills
    g.fillStyle(0x7ec87a, 1);
    g.fillTriangle(0, 180, 80, 110, 160, 180);
    g.fillTriangle(120, 180, 220, 100, 320, 180);
  });

  // Mid city / trees silhouette
  tex(scene, "brawler-mid", 400, 160, g => {
    g.fillStyle(0x000000, 0); // transparent base — draw only buildings
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
    // Trees between buildings
    g.fillStyle(0x2d5a2a, 1);
    for (const tx of [55, 175, 310]) {
      g.fillTriangle(tx, 100, tx + 18, 50, tx + 36, 100);
      g.fillStyle(0x5c4030, 1);
      g.fillRect(tx + 14, 100, 8, 40);
      g.fillStyle(0x2d5a2a, 1);
    }
  });

  // Ground / lane tile (walkable band look)
  tex(scene, "brawler-ground", 64, 128, g => {
    g.fillStyle(0x6b4a2e, 1);
    g.fillRect(0, 0, 64, 128);
    g.fillStyle(0x5a3c24, 1);
    for (let y = 0; y < 128; y += 8) {
      g.fillRect(0, y, 64, 3);
    }
    g.fillStyle(0x7a5a3a, 0.5);
    g.fillRect(0, 0, 64, 10);
  });

  // Foreground curb / fence strip
  tex(scene, "brawler-near", 96, 48, g => {
    g.fillStyle(0x3a2818, 1);
    g.fillRect(0, 24, 96, 24);
    g.fillStyle(0x2a1c10, 1);
    for (let x = 0; x < 96; x += 16) g.fillRect(x, 24, 8, 4);
    g.fillStyle(0x8a7060, 1);
    g.fillRect(0, 20, 96, 5);
  });

  // Gate post
  tex(scene, "brawler-gate", 28, 72, g => {
    g.fillStyle(0xc45c26, 1);
    g.fillRect(8, 0, 12, 72);
    g.fillStyle(0xffe680, 1);
    g.fillTriangle(2, 8, 14, 0, 26, 8);
    g.fillStyle(0xffffff, 1);
    g.fillRect(10, 20, 8, 18);
  });

  // Barrel / crate props
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
}

function sectionAt(x: number) {
  return SECTION.find(s => x >= s.from && x < s.to) ?? SECTION[SECTION.length - 1];
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

  // Colored ground band per section — drawn as world-space rects for variety.
  for (const sec of SECTION) {
    const midX = (sec.from + sec.to) / 2;
    const width = sec.to - sec.from;
    // Backdrop wash behind the lane
    scene.add
      .rectangle(midX, MAP.laneTop - 30, width, 80, sec.accent, 0.35)
      .setDepth(2);
    // Walkable floor
    scene.add
      .rectangle(midX, (MAP.laneTop + MAP.laneBottom) / 2 + 40, width, 140, sec.ground, 1)
      .setDepth(3);
    // Lane top edge (clear bound)
    scene.add
      .rectangle(midX, MAP.laneTop, width, 3, 0xffffff, 0.25)
      .setDepth(4);
    scene.add
      .rectangle(midX, MAP.laneBottom, width, 3, 0x000000, 0.35)
      .setDepth(4);
  }

  const ground = scene.add
    .tileSprite(0, MAP.laneBottom + 8, w, 80, "brawler-ground")
    .setOrigin(0, 0)
    .setScrollFactor(0)
    .setDepth(5);

  // Near foreground props container (scrolls with world via children positions)
  const near = scene.add.container(0, 0).setDepth(200);

  // Scatter props along the stage
  const propEvery = 140;
  for (let x = 40; x < MAP.w; x += propEvery) {
    const sec = sectionAt(x);
    const roll = (Math.sin(x * 12.9898) * 43758.5453) % 1;
    const r = Math.abs(roll);
    let key = "brawler-barrel";
    if (sec.name === "street" || sec.name === "plaza") key = r > 0.5 ? "brawler-hydrant" : "brawler-crate";
    else if (sec.name === "docks") key = r > 0.4 ? "brawler-crate" : "brawler-barrel";
    else if (sec.name === "alley") key = "brawler-barrel";
    else if (sec.name === "arena") key = r > 0.5 ? "brawler-crate" : "brawler-lamp";
    else key = r > 0.6 ? "brawler-lamp" : "brawler-barrel";
    // Keep props on the near edge so they don't block the lane center.
    const side = r > 0.5 ? MAP.laneBottom + 4 : MAP.laneTop - 8;
    const img = scene.add.image(x + (r - 0.5) * 40, side, key).setOrigin(0.5, 1);
    img.setDepth(side >= MAP.laneBottom ? 180 : 6);
    if (side >= MAP.laneBottom) near.add(img);
  }

  // Street lamps along the mid depth
  for (let x = 100; x < MAP.w; x += 280) {
    scene.add
      .image(x, MAP.laneTop - 4, "brawler-lamp")
      .setOrigin(0.5, 1)
      .setDepth(6)
      .setAlpha(0.9);
  }

  // Section gates — clear visual "doors" at each wave trigger
  for (const gx of gates) {
    scene.add.image(gx - 18, MAP.laneTop - 4, "brawler-gate").setOrigin(0.5, 1).setDepth(7);
    scene.add.image(gx + 18, MAP.laneTop - 4, "brawler-gate").setOrigin(0.5, 1).setDepth(7).setFlipX(true);
    // Floor stripe
    scene.add
      .rectangle(gx, (MAP.laneTop + MAP.laneBottom) / 2, 6, MAP.laneBottom - MAP.laneTop + 20, 0xffe680, 0.55)
      .setDepth(4);
  }

  // Boss arena floor flourish
  scene.add
    .rectangle(3300, (MAP.laneTop + MAP.laneBottom) / 2, 520, 100, 0x7a2030, 0.45)
    .setDepth(3);
  scene.add
    .rectangle(3300, (MAP.laneTop + MAP.laneBottom) / 2, 480, 4, 0xffe680, 0.7)
    .setDepth(4);

  return { layers: { far, mid, ground, near }, gates };
}

export function resizeParallax(layers: ParallaxLayers, width: number, height: number) {
  layers.far.setSize(width, height);
  layers.mid.setSize(width, 160);
  layers.mid.setY(height * 0.28);
  layers.ground.setSize(width, 80);
}
