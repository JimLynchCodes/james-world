/**
 * Boot preload must stay lean: only the default James skin (and no brawler /
 * cave sprites) go through GameScene.preload. Everything else is deferred.
 *
 *   npx tsx --test tools/check_boot_preload.ts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (name: string) => readFileSync(join(root, "src", name), "utf8");

test("BOOT_SKINS is only the default James skin", () => {
  const loader = src("assetLoader.ts");
  const match = loader.match(/export const BOOT_SKINS[^=]*=\s*\[([^\]]*)\]/);
  assert.ok(match, "expected BOOT_SKINS export");
  assert.equal(match[1].replace(/\s+/g, ""), "DEFAULT_SKIN");

  const skins = src("skins.ts");
  assert.match(skins, /export const DEFAULT_SKIN[^=]*=\s*"james"/);
  assert.match(skins, /export const SKIN_IDS = Object\.keys\(SKINS\)/);
  const typeMatch = skins.match(/export type Skin = ((?:\|?\s*"[a-z0-9_]+"\s*)+);/);
  assert.ok(typeMatch, "expected Skin union");
  const count = [...typeMatch[1].matchAll(/"/g)].length / 2;
  assert.ok(count > 1, `expected multiple skins, got ${count}`);
});

test("preloadKid only queues BOOT_SKINS", () => {
  const kid = src("kid.ts");
  const fn = kid.match(/export function preloadKid\([^)]*\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(fn, "expected preloadKid function");
  assert.match(fn[1], /for \(const id of BOOT_SKINS\)/);
  assert.doesNotMatch(fn[1], /SKIN_IDS/);
});

test("GameScene.preload does not pull cave or brawler textures", () => {
  const main = src("main.ts");
  const idx = main.indexOf("preload()");
  assert.ok(idx > 0, "expected a preload() method");
  const body = main.slice(idx, idx + 400);
  assert.match(body, /preloadKid\(this\)/);
  assert.doesNotMatch(body, /cave\//);
  assert.doesNotMatch(body, /brawler/i);
  assert.doesNotMatch(body, /old-man\.png|sword\.png|fire-0/);
});

test("secret dungeon and brawler world are dynamically imported", () => {
  const main = src("main.ts");
  const loader = src("assetLoader.ts");
  assert.match(loader, /import\(["']\.\/secretDungeon["']\)/);
  assert.match(loader, /import\(["']\.\/brawlerWorld["']\)/);
  assert.match(main, /loadSecretModule\(/);
  assert.match(main, /loadBrawlerModule\(/);
  assert.doesNotMatch(main, /^import \{[^}]*SecretDungeon/m);
  assert.doesNotMatch(main, /^import \{[^}]*BrawlerWorldScene/m);
  assert.match(main, /import type \{[^}]*DungeonHooks[^}]*\} from ["']\.\/secretDungeon["']/);
  assert.match(main, /import type \{[^}]*BrawlerWorldScene[^}]*\} from ["']\.\/brawlerWorld["']/);
});

test("default mood for new users is chillin", () => {
  assert.match(src("settings.ts"), /mood:\s*"chillin"/);
});

test("assetLoader exposes ensure + overlay helpers", () => {
  const loader = src("assetLoader.ts");
  for (const name of [
    "ensureSkinLoaded",
    "ensureCaveAssets",
    "loadSecretModule",
    "loadBrawlerModule",
    "startBackgroundLoads",
    "showLoadingOverlay",
    "isSkinReady",
  ]) {
    assert.match(loader, new RegExp(`export (async )?function ${name}`));
  }
});
