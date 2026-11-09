/**
 * Title-screen preload races `new Phaser.Game` boot: ensureSkinLoaded must
 * not touch scene.textures / scene.load until the scene is usable.
 *
 *   npx tsx --test tools/check_scene_load_ready.ts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const loader = readFileSync(join(root, "src", "assetLoader.ts"), "utf8");
const main = readFileSync(join(root, "src", "main.ts"), "utf8");

/** Mirror of Phaser.Scenes status ints used by isSceneReadyForLoad. */
const STATUS = {
  PENDING: 0,
  INIT: 1,
  RUNNING: 5,
  SHUTDOWN: 8,
  DESTROYED: 9,
} as const;

/** Pure copy of the readiness gate (keeps the check Phaser-free in Node). */
function isSceneReadyForLoad(scene: {
  sys?: { settings?: { status: number }; game?: unknown } | null;
  textures?: unknown;
  load?: unknown;
}): boolean {
  const sys = scene.sys;
  if (!sys?.settings || !sys.game) return false;
  const status = sys.settings.status;
  if (status < STATUS.INIT || status >= STATUS.SHUTDOWN) return false;
  if (!(scene.textures ?? (sys.game as { textures?: unknown }).textures)) return false;
  if (!scene.load) return false;
  return true;
}

test("assetLoader guards PENDING scenes and uses texturesOf", () => {
  assert.match(loader, /export function texturesOf/);
  assert.match(loader, /export function isSceneReadyForLoad/);
  assert.match(loader, /export function whenSceneCanLoad/);
  assert.match(loader, /scene\.textures \?\? scene\.sys\?\.game\?\.textures/);
  assert.match(loader, /status < Phaser\.Scenes\.INIT/);
  assert.match(loader, /status >= Phaser\.Scenes\.SHUTDOWN/);
  assert.match(loader, /await whenSceneCanLoad\(scene\)/);
  // queue helpers must not call bare scene.textures.exists
  const queueSkin = loader.match(/function queueSkinFiles\([\s\S]*?\n\}/);
  assert.ok(queueSkin);
  assert.match(queueSkin[0], /texturesOf\(scene\)/);
  assert.doesNotMatch(queueSkin[0], /scene\.textures\.exists/);
  const queueCave = loader.match(/function queueCaveFiles\([\s\S]*?\n\}/);
  assert.ok(queueCave);
  assert.match(queueCave[0], /texturesOf\(scene\)/);
  assert.doesNotMatch(queueCave[0], /scene\.textures\.exists/);
});

test("ensureSkinLoaded / ensureCaveAssets / background loads wait for boot", () => {
  assert.match(loader, /export async function ensureSkinLoaded[\s\S]*?whenSceneCanLoad/);
  assert.match(loader, /export async function ensureCaveAssets[\s\S]*?whenSceneCanLoad/);
  assert.match(loader, /export function startBackgroundLoads[\s\S]*?whenSceneCanLoad/);
  assert.match(loader, /console\.error\("\[lazy\] ensureSkinLoaded failed"/);
  assert.match(loader, /console\.error\("\[lazy\] background loads failed"/);
});

test("main title preload catches rejections", () => {
  assert.match(main, /preloadPlaySkin[\s\S]*?ensureSkinLoaded[\s\S]*?\.catch\(/);
  assert.match(main, /beginBackgroundLoads[\s\S]*?startBackgroundLoads/);
});

test("readiness gate rejects PENDING and DESTROYED scenes", () => {
  assert.equal(
    isSceneReadyForLoad({
      sys: { settings: { status: STATUS.PENDING }, game: { textures: {} } },
      load: {},
    }),
    false,
  );
  assert.equal(
    isSceneReadyForLoad({
      sys: { settings: { status: STATUS.DESTROYED }, game: { textures: {} } },
      textures: {},
      load: {},
    }),
    false,
  );
  assert.equal(
    isSceneReadyForLoad({
      sys: { settings: { status: STATUS.RUNNING }, game: { textures: {} } },
      load: {},
    }),
    true,
  );
  // scene.textures missing but game.textures present — still ready once load exists.
  assert.equal(
    isSceneReadyForLoad({
      sys: { settings: { status: STATUS.INIT }, game: { textures: { exists() {} } } },
      load: {},
    }),
    true,
  );
  // No load plugin yet.
  assert.equal(
    isSceneReadyForLoad({
      sys: { settings: { status: STATUS.RUNNING }, game: { textures: {} } },
      textures: {},
    }),
    false,
  );
});
