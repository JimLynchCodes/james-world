/**
 * Boot-critical vs background asset loading.
 *
 * Phaser's GameScene.preload only pulls the default James sheet so the title
 * screen and playground can start immediately. Everything else (other skins,
 * the cave sprites, and the secret/brawler scene modules) is queued after
 * create() and fetched in the background. Callers that need a skin or a
 * scene before the idle queue reaches it use ensure* and wait.
 */
import Phaser from "phaser";
import { DEFAULT_SKIN, SKINS, SKIN_IDS, type Skin } from "./skins";

/** Wired once from kid.ts so we can register animations without a circular import. */
let afterSkinTextures: ((scene: Phaser.Scene, skin: Skin) => void) | null = null;
export function setAfterSkinTextures(fn: (scene: Phaser.Scene, skin: Skin) => void) {
  afterSkinTextures = fn;
}

/** Skins pulled during GameScene.preload. Everything else waits. */
export const BOOT_SKINS: readonly Skin[] = [DEFAULT_SKIN];

const CAVE_IMAGES: readonly { key: string; file: string }[] = [
  { key: "dungeon-man", file: "old-man.png" },
  { key: "dungeon-fire-0", file: "fire-0.png" },
  { key: "dungeon-fire-1", file: "fire-1.png" },
  { key: "dungeon-sword", file: "sword.png" },
];

const BASE = import.meta.env.BASE_URL;

type ReadyState = "pending" | "loading" | "ready" | "error";

const skinState = new Map<Skin, ReadyState>();
const skinWaiters = new Map<Skin, Array<(ok: boolean) => void>>();
let caveState: ReadyState = "pending";
const caveWaiters: Array<(ok: boolean) => void> = [];

let secretModule: typeof import("./secretDungeon") | null = null;
let secretModulePromise: Promise<typeof import("./secretDungeon")> | null = null;
let brawlerModule: typeof import("./brawlerWorld") | null = null;
let brawlerModulePromise: Promise<typeof import("./brawlerWorld")> | null = null;

/** True when the skin's Phaser textures (and animations) are ready to draw. */
export function isSkinReady(skin: Skin): boolean {
  if (skin === DEFAULT_SKIN) return true;
  return skinState.get(skin) === "ready";
}

const skinReadyListeners = new Set<(skin: Skin) => void>();

/** Subscribe to skins becoming drawable (textures + animations registered). */
export function onSkinReady(listener: (skin: Skin) => void): () => void {
  skinReadyListeners.add(listener);
  return () => {
    skinReadyListeners.delete(listener);
  };
}

function finishSkin(skin: Skin, ok: boolean) {
  skinState.set(skin, ok ? "ready" : "error");
  const waiters = skinWaiters.get(skin) ?? [];
  skinWaiters.delete(skin);
  for (const w of waiters) w(ok);
  if (ok) for (const listener of skinReadyListeners) listener(skin);
}

function finishCave(ok: boolean) {
  caveState = ok ? "ready" : "error";
  while (caveWaiters.length) caveWaiters.shift()?.(ok);
}

function queueSkinFiles(scene: Phaser.Scene, skin: Skin) {
  const sheet = SKINS[skin];
  const frame = { frameWidth: sheet.frameWidth, frameHeight: sheet.frameHeight };
  if (!scene.textures.exists(sheet.texture)) {
    scene.load.spritesheet(sheet.texture, sheet.url, frame);
  }
  if (sheet.extra && !scene.textures.exists(sheet.extra.texture)) {
    scene.load.spritesheet(sheet.extra.texture, sheet.extra.url, frame);
  }
}

function queueCaveFiles(scene: Phaser.Scene) {
  for (const { key, file } of CAVE_IMAGES) {
    if (!scene.textures.exists(key)) {
      scene.load.image(key, `${BASE}assets/cave/${file}`);
    }
  }
}

/**
 * Run one Phaser load batch. Phaser ignores start() while already loading, so
 * callers that add files mid-batch piggy-back; we only start when idle.
 */
function runLoad(scene: Phaser.Scene): Promise<void> {
  return new Promise(resolve => {
    if (!scene.load.isLoading() && scene.load.totalToLoad === 0) {
      resolve();
      return;
    }
    const done = () => {
      scene.load.off(Phaser.Loader.Events.COMPLETE, done);
      scene.load.off(Phaser.Loader.Events.FILE_LOAD_ERROR, done);
      resolve();
    };
    scene.load.once(Phaser.Loader.Events.COMPLETE, done);
    scene.load.once(Phaser.Loader.Events.FILE_LOAD_ERROR, done);
    if (!scene.load.isLoading()) scene.load.start();
  });
}

/** Load one skin's sheet(s) into the scene and register its animations. */
export async function ensureSkinLoaded(scene: Phaser.Scene, skin: Skin): Promise<boolean> {
  if (isSkinReady(skin)) {
    afterSkinTextures?.(scene, skin);
    return true;
  }
  const existing = skinState.get(skin);
  if (existing === "loading") {
    return new Promise(resolve => {
      const list = skinWaiters.get(skin) ?? [];
      list.push(resolve);
      skinWaiters.set(skin, list);
    });
  }
  if (existing === "error") {
    // Allow a retry.
    skinState.set(skin, "pending");
  }

  skinState.set(skin, "loading");
  queueSkinFiles(scene, skin);
  await runLoad(scene);
  const sheet = SKINS[skin];
  const ok =
    scene.textures.exists(sheet.texture) &&
    (!sheet.extra || scene.textures.exists(sheet.extra.texture));
  if (ok) afterSkinTextures?.(scene, skin);
  finishSkin(skin, ok);
  return ok;
}

/** Cave sprites used by the secret room. Tiny; still kept off the boot path. */
export async function ensureCaveAssets(scene: Phaser.Scene): Promise<boolean> {
  if (caveState === "ready") return true;
  if (caveState === "loading") {
    return new Promise(resolve => caveWaiters.push(resolve));
  }
  caveState = "loading";
  queueCaveFiles(scene);
  await runLoad(scene);
  const ok = CAVE_IMAGES.every(({ key }) => scene.textures.exists(key));
  finishCave(ok);
  return ok;
}

export function loadSecretModule(): Promise<typeof import("./secretDungeon")> {
  if (secretModule) return Promise.resolve(secretModule);
  if (!secretModulePromise) {
    secretModulePromise = import("./secretDungeon").then(mod => {
      secretModule = mod;
      return mod;
    });
  }
  return secretModulePromise;
}

export function loadBrawlerModule(): Promise<typeof import("./brawlerWorld")> {
  if (brawlerModule) return Promise.resolve(brawlerModule);
  if (!brawlerModulePromise) {
    brawlerModulePromise = import("./brawlerWorld").then(mod => {
      brawlerModule = mod;
      return mod;
    });
  }
  return brawlerModulePromise;
}

/**
 * After the playground is up, fetch the rest in the background. Prefer the
 * player's saved skin so a returning visitor swaps off James quickly; then
 * every other skin, the cave, and the scene modules.
 */
export function startBackgroundLoads(scene: Phaser.Scene, prefer?: Skin) {
  const order: Skin[] = [];
  if (prefer && prefer !== DEFAULT_SKIN) order.push(prefer);
  for (const id of SKIN_IDS) {
    if (id === DEFAULT_SKIN) continue;
    if (!order.includes(id)) order.push(id);
  }

  const kick = () => {
    void (async () => {
      for (const skin of order) {
        if (isSkinReady(skin)) continue;
        await ensureSkinLoaded(scene, skin);
        // Yield so input / frames stay responsive between sheets.
        await new Promise<void>(r => setTimeout(r, 0));
      }
      await ensureCaveAssets(scene);
      // Prefetch scene chunks so the secret tree / sword feel instant.
      void loadSecretModule();
      void loadBrawlerModule();
    })();
  };

  const ric = (window as Window & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  }).requestIdleCallback;
  if (typeof ric === "function") ric(kick, { timeout: 1200 });
  else setTimeout(kick, 0);
}

/** Mark the boot skin ready (loaded in preload). */
export function markBootSkinsReady(scene: Phaser.Scene) {
  for (const skin of BOOT_SKINS) {
    skinState.set(skin, "ready");
    afterSkinTextures?.(scene, skin);
    for (const listener of skinReadyListeners) listener(skin);
  }
}

/** Brief full-screen "Loading…" while a deferred scene catches up. */
export function showLoadingOverlay(label = "Loading…"): () => void {
  const existing = document.querySelector(".lazy-loading");
  if (existing) existing.remove();
  const el = document.createElement("div");
  el.className = "lazy-loading";
  el.setAttribute("role", "status");
  el.innerHTML = `<div class="lazy-loading-card"><span class="lazy-spinner" aria-hidden="true"></span><span class="lazy-loading-text">${label}</span></div>`;
  document.body.appendChild(el);
  return () => el.remove();
}
