/**
 * Boot-critical vs background asset loading.
 *
 * Phaser's GameScene.preload only pulls the default James sheet so the title
 * screen and playground can start immediately. Everything else (other skins,
 * the cave sprites, and the secret/brawler scene modules) is queued after
 * create() and fetched in the background. Callers that need a skin or a
 * scene before the idle queue reaches it use ensure* and wait.
 *
 * Important: `new Phaser.Game` boots scenes asynchronously. Callers may invoke
 * ensure* / startBackgroundLoads before `scene.textures` / `scene.load` exist.
 * We always resolve the game TextureManager and wait until the scene can load
 * (or give up if it was destroyed).
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
const getCaveState = (): ReadyState => caveState;

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

/**
 * Game-level texture manager. Prefer this over `scene.textures`, which is
 * undefined until the scene Systems finish INIT.
 */
export function texturesOf(scene: Phaser.Scene): Phaser.Textures.TextureManager | null {
  return scene.textures ?? scene.sys?.game?.textures ?? null;
}

/**
 * True when the scene can safely queue Phaser loads and read textures.
 * PENDING scenes (right after `new Phaser.Game`) are not ready; SHUTDOWN /
 * DESTROYED scenes are never used again.
 */
export function isSceneReadyForLoad(scene: Phaser.Scene): boolean {
  const sys = scene.sys;
  if (!sys?.settings || !sys.game) return false;
  const status = sys.settings.status;
  if (status < Phaser.Scenes.INIT || status >= Phaser.Scenes.SHUTDOWN) return false;
  if (!texturesOf(scene)) return false;
  if (!scene.load) return false;
  return true;
}

/**
 * Resolve when the scene can load files, or false if it shuts down first.
 * Safe to call before boot — listens for START/READY and also polls.
 */
export function whenSceneCanLoad(scene: Phaser.Scene): Promise<boolean> {
  if (isSceneReadyForLoad(scene)) return Promise.resolve(true);

  return new Promise(resolve => {
    const sys = scene.sys;
    const events = scene.events;
    if (!sys || !events) {
      resolve(false);
      return;
    }
    if (sys.settings?.status >= Phaser.Scenes.SHUTDOWN) {
      resolve(false);
      return;
    }

    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(ok);
    };
    const tryReady = () => {
      if (isSceneReadyForLoad(scene)) finish(true);
    };
    const onDead = () => finish(false);
    const cleanup = () => {
      events.off(Phaser.Scenes.Events.START, tryReady);
      events.off(Phaser.Scenes.Events.READY, tryReady);
      events.off(Phaser.Scenes.Events.CREATE, tryReady);
      events.off(Phaser.Scenes.Events.SHUTDOWN, onDead);
      events.off(Phaser.Scenes.Events.DESTROY, onDead);
      clearInterval(timer);
    };

    events.on(Phaser.Scenes.Events.START, tryReady);
    events.on(Phaser.Scenes.Events.READY, tryReady);
    events.on(Phaser.Scenes.Events.CREATE, tryReady);
    events.once(Phaser.Scenes.Events.SHUTDOWN, onDead);
    events.once(Phaser.Scenes.Events.DESTROY, onDead);

    // Boot is usually on the next frames; poll briefly so we don't hang if an
    // event was already missed between PENDING and RUNNING.
    let attempts = 0;
    const timer = setInterval(() => {
      tryReady();
      if (++attempts > 120) finish(isSceneReadyForLoad(scene)); // ~2s at 60hz
    }, 16);

    queueMicrotask(tryReady);
  });
}

function queueSkinFiles(scene: Phaser.Scene, skin: Skin) {
  const textures = texturesOf(scene);
  if (!textures || !scene.load) return;
  const sheet = SKINS[skin];
  const frame = { frameWidth: sheet.frameWidth, frameHeight: sheet.frameHeight };
  if (!textures.exists(sheet.texture)) {
    scene.load.spritesheet(sheet.texture, sheet.url, frame);
  }
  if (sheet.extra && !textures.exists(sheet.extra.texture)) {
    scene.load.spritesheet(sheet.extra.texture, sheet.extra.url, frame);
  }
}

function queueCaveFiles(scene: Phaser.Scene) {
  const textures = texturesOf(scene);
  if (!textures || !scene.load) return;
  for (const { key, file } of CAVE_IMAGES) {
    if (!textures.exists(key)) {
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
    if (!scene.load) {
      resolve();
      return;
    }
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
  try {
    if (isSkinReady(skin)) {
      if (isSceneReadyForLoad(scene)) afterSkinTextures?.(scene, skin);
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

    // Wait for boot before claiming the "loading" slot so a PENDING scene
    // does not leave skins stuck if the wait fails.
    const canLoad = await whenSceneCanLoad(scene);
    if (!canLoad) {
      console.warn("[lazy] ensureSkinLoaded: scene not ready", skin);
      return false;
    }
    if (isSkinReady(skin)) {
      afterSkinTextures?.(scene, skin);
      return true;
    }
    if (skinState.get(skin) === "loading") {
      return new Promise(resolve => {
        const list = skinWaiters.get(skin) ?? [];
        list.push(resolve);
        skinWaiters.set(skin, list);
      });
    }

    skinState.set(skin, "loading");
    queueSkinFiles(scene, skin);
    await runLoad(scene);
    if (!isSceneReadyForLoad(scene)) {
      finishSkin(skin, false);
      return false;
    }
    const textures = texturesOf(scene);
    const sheet = SKINS[skin];
    const ok = !!(
      textures &&
      textures.exists(sheet.texture) &&
      (!sheet.extra || textures.exists(sheet.extra.texture))
    );
    if (ok) afterSkinTextures?.(scene, skin);
    finishSkin(skin, ok);
    return ok;
  } catch (err) {
    console.error("[lazy] ensureSkinLoaded failed", skin, err);
    if (skinState.get(skin) === "loading") finishSkin(skin, false);
    return false;
  }
}

/** Cave sprites used by the secret room. Tiny; still kept off the boot path. */
export async function ensureCaveAssets(scene: Phaser.Scene): Promise<boolean> {
  try {
    if (caveState === "ready") return true;
    if (caveState === "loading") {
      return new Promise(resolve => caveWaiters.push(resolve));
    }

    const canLoad = await whenSceneCanLoad(scene);
    if (!canLoad) {
      console.warn("[lazy] ensureCaveAssets: scene not ready");
      return false;
    }
    // Re-read after await: another caller may have finished or started.
    const afterWait = getCaveState();
    if (afterWait === "ready") return true;
    if (afterWait === "loading") {
      return new Promise(resolve => caveWaiters.push(resolve));
    }

    caveState = "loading";
    queueCaveFiles(scene);
    await runLoad(scene);
    if (!isSceneReadyForLoad(scene)) {
      finishCave(false);
      return false;
    }
    const textures = texturesOf(scene);
    const ok = !!textures && CAVE_IMAGES.every(({ key }) => textures.exists(key));
    finishCave(ok);
    return ok;
  } catch (err) {
    console.error("[lazy] ensureCaveAssets failed", err);
    if (caveState === "loading") finishCave(false);
    return false;
  }
}

export function loadSecretModule(): Promise<typeof import("./secretDungeon")> {
  if (secretModule) return Promise.resolve(secretModule);
  if (!secretModulePromise) {
    secretModulePromise = import("./secretDungeon")
      .then(mod => {
        secretModule = mod;
        return mod;
      })
      .catch(err => {
        secretModulePromise = null;
        console.error("[lazy] secretDungeon import failed", err);
        throw err;
      });
  }
  return secretModulePromise;
}

export function loadBrawlerModule(): Promise<typeof import("./brawlerWorld")> {
  if (brawlerModule) return Promise.resolve(brawlerModule);
  if (!brawlerModulePromise) {
    brawlerModulePromise = import("./brawlerWorld")
      .then(mod => {
        brawlerModule = mod;
        return mod;
      })
      .catch(err => {
        brawlerModulePromise = null;
        console.error("[lazy] brawlerWorld import failed", err);
        throw err;
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
      try {
        const canLoad = await whenSceneCanLoad(scene);
        if (!canLoad) return;
        for (const skin of order) {
          if (isSkinReady(skin)) continue;
          await ensureSkinLoaded(scene, skin);
          // Yield so input / frames stay responsive between sheets.
          await new Promise<void>(r => setTimeout(r, 0));
        }
        await ensureCaveAssets(scene);
        // Prefetch scene chunks so the secret tree / sword feel instant.
        void loadSecretModule().catch(() => {});
        void loadBrawlerModule().catch(() => {});
      } catch (err) {
        console.error("[lazy] background loads failed", err);
      }
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
