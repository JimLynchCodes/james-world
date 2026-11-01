/**
 * Co-op side-scrolling beat-'em-up entered after taking the cave sword.
 * Server is authoritative; this scene renders snapshots and sends input.
 */
import Phaser from "phaser";
import type { GameAudio } from "./audio";
import { shouldPlayAttackAnim } from "./brawlerAttack";
import {
  parallaxOffsets,
  stepBrawlerCamera,
} from "./brawlerCamera";
import {
  shouldBeginDeath,
  shouldBeginWin,
  shouldDrawBrawlerPeer,
  type BrawlerEnding,
} from "./brawlerLeave";
import {
  buildBrawlerStage,
  resizeParallax,
  type ParallaxLayers,
} from "./brawlerMap";
import { toCosmetic, type Cosmetic } from "./cosmetics";
import { onLocaleChange, t } from "./i18n";
import { KidAvatar } from "./kid";
import type {
  BrawlerPlayerSnap,
  BrawlerSnapshotData,
  EnemySnap,
  ServerMessage,
} from "./protocol";
import type { ControlMode } from "./settings";
import { toSkin, type Skin } from "./skins";
import type { UUID } from "./types";

export const BRAWLER = {
  w: 7000,
  laneTop: 120,
  laneBottom: 230,
  groundY: 200,
} as const;

export type BrawlerHooks = {
  skin: Skin;
  cosmetic: Cosmetic;
  name: string;
  audio: GameAudio | null;
  readMove: () => { dx: number; dy: number; mode: ControlMode };
  /** Rising-edge pulse: true for one consume after a fresh tag press. */
  readAttack: () => boolean;
  sendInput: (dx: number, dy: number, attack: boolean) => void;
  onLeaveBrawler: () => void;
  onDied: () => void;
  onWon: () => void;
};

type Peer = {
  avatar: KidAvatar;
  snap: BrawlerPlayerSnap;
  /** Last snapshot attacking flag — playTag only on rising edge. */
  wasAttacking: boolean;
};

const ENEMY_COLORS: Record<string, number> = {
  grunt: 0xc45c26,
  bruiser: 0x6b3a2a,
  swift: 0x3d8b6e,
  elite: 0x8a2be2,
  boss: 0x7a1f2b,
};

function ensureEnemyTextures(scene: Phaser.Scene) {
  const make = (key: string, w: number, h: number, fill: number, detail: (g: Phaser.GameObjects.Graphics) => void) => {
    if (scene.textures.exists(key)) return;
    const g = scene.make.graphics({ x: 0, y: 0 });
    g.fillStyle(fill, 1);
    g.fillRoundedRect(1, 1, w - 2, h - 2, 4);
    g.lineStyle(2, 0x1a0f0a, 1);
    g.strokeRoundedRect(1, 1, w - 2, h - 2, 4);
    detail(g);
    g.generateTexture(key, w, h);
    g.destroy();
    scene.textures.get(key).setFilter(Phaser.Textures.FilterMode.NEAREST);
  };
  make("brawler-grunt", 28, 36, ENEMY_COLORS.grunt, g => {
    g.fillStyle(0xffe0a0, 1);
    g.fillCircle(10, 12, 4);
    g.fillCircle(18, 12, 4);
    g.fillStyle(0x1a0f0a, 1);
    g.fillCircle(10, 12, 2);
    g.fillCircle(18, 12, 2);
  });
  make("brawler-bruiser", 40, 48, ENEMY_COLORS.bruiser, g => {
    g.fillStyle(0xffd090, 1);
    g.fillCircle(14, 14, 5);
    g.fillCircle(26, 14, 5);
    g.fillStyle(0x1a0f0a, 1);
    g.fillCircle(14, 14, 2.5);
    g.fillCircle(26, 14, 2.5);
    g.fillStyle(0x4a2818, 1);
    g.fillRect(8, 28, 24, 10);
  });
  make("brawler-swift", 24, 30, ENEMY_COLORS.swift, g => {
    g.fillStyle(0xe8fff0, 1);
    g.fillCircle(8, 10, 3);
    g.fillCircle(16, 10, 3);
    g.fillStyle(0x1a0f0a, 1);
    g.fillCircle(8, 10, 1.5);
    g.fillCircle(16, 10, 1.5);
  });
  make("brawler-elite", 52, 60, ENEMY_COLORS.elite, g => {
    g.fillStyle(0xffe0c0, 1);
    g.fillCircle(18, 18, 7);
    g.fillCircle(34, 18, 7);
    g.fillStyle(0x1a0f0a, 1);
    g.fillCircle(18, 18, 3);
    g.fillCircle(34, 18, 3);
    g.fillStyle(0xffd700, 1);
    g.fillTriangle(26, 2, 18, 14, 34, 14);
    g.fillStyle(0xaa44ff, 1);
    g.fillRect(10, 36, 32, 10);
  });
  make("brawler-boss", 72, 84, ENEMY_COLORS.boss, g => {
    g.fillStyle(0xffcc88, 1);
    g.fillCircle(24, 22, 8);
    g.fillCircle(48, 22, 8);
    g.fillStyle(0x1a0f0a, 1);
    g.fillCircle(24, 22, 4);
    g.fillCircle(48, 22, 4);
    g.fillStyle(0xffd700, 1);
    g.fillTriangle(36, 4, 28, 16, 44, 16);
    g.fillStyle(0xffffff, 0.9);
    g.fillRect(18, 50, 36, 8);
  });
}

function enemyKey(kind: string): string {
  if (kind === "bruiser") return "brawler-bruiser";
  if (kind === "swift") return "brawler-swift";
  if (kind === "elite") return "brawler-elite";
  if (kind === "boss") return "brawler-boss";
  return "brawler-grunt";
}

function ensureHudBar(scene: Phaser.Scene) {
  if (scene.textures.exists("brawler-bar-bg")) return;
  const g = scene.make.graphics({ x: 0, y: 0 });
  // Arcade life bar chrome: dark well + gold rim.
  g.fillStyle(0x0a0a0a, 0.92);
  g.fillRoundedRect(0, 0, 200, 18, 4);
  g.lineStyle(2, 0xffe680, 1);
  g.strokeRoundedRect(1, 1, 198, 16, 4);
  g.generateTexture("brawler-bar-bg", 200, 18);
  g.clear();
  g.fillStyle(0x33cc55, 1);
  g.fillRoundedRect(0, 0, 196, 14, 3);
  g.fillStyle(0x88ffaa, 0.45);
  g.fillRoundedRect(0, 0, 196, 5, 2);
  g.generateTexture("brawler-bar-fill", 196, 14);
  g.clear();
  g.fillStyle(0xcc3344, 1);
  g.fillRoundedRect(0, 0, 196, 14, 3);
  g.fillStyle(0xff8899, 0.4);
  g.fillRoundedRect(0, 0, 196, 5, 2);
  g.generateTexture("brawler-boss-fill", 196, 14);
  g.destroy();
}

export class BrawlerWorldScene extends Phaser.Scene {
  private hooks!: BrawlerHooks;
  private localId: UUID | null = null;
  private localHp = 100;
  private localMaxHp = 100;
  private peers = new Map<UUID, Peer>();
  private enemies = new Map<number, Phaser.GameObjects.Image>();
  private layers!: ParallaxLayers;
  private camX = 200;
  private camY = 180;
  private scrollMin = 0;
  private hudRoot!: Phaser.GameObjects.Container;
  private hpFill!: Phaser.GameObjects.Image;
  private hpLabel!: Phaser.GameObjects.Text;
  private waveLabel!: Phaser.GameObjects.Text;
  private bossWrap!: Phaser.GameObjects.Container;
  private bossFill!: Phaser.GameObjects.Image;
  private bossLabel!: Phaser.GameObjects.Text;
  private banner!: Phaser.GameObjects.Text;
  private goLabel!: Phaser.GameObjects.Text;
  private ending: BrawlerEnding = "none";
  private fade?: Phaser.GameObjects.Rectangle;
  private unsubLocale: (() => void) | null = null;
  private left = false;
  private lockLeft: number | null = null;
  private lockRight: number | null = null;

  constructor() {
    super({ key: "BrawlerWorld", active: false });
  }

  init(hooks: BrawlerHooks) {
    this.hooks = hooks;
    this.localId = null;
    this.peers.clear();
    this.enemies.clear();
    this.ending = "none";
    this.left = false;
    this.scrollMin = 0;
    this.lockLeft = null;
    this.lockRight = null;
    this.camX = 200;
    this.camY = 180;
  }

  create() {
    this.cameras.main.setBackgroundColor("#5eb0ff");
    this.cameras.main.setBounds(0, 0, BRAWLER.w, 360);
    this.cameras.main.setRoundPixels(true);
    // Disable built-in follow — we drive scroll with arcade group-cam logic.
    this.cameras.main.stopFollow();

    ensureEnemyTextures(this);
    ensureHudBar(this);

    const stage = buildBrawlerStage(this);
    this.layers = stage.layers;
    this.camX = 200;
    this.camY = 180;
    this.scrollMin = 0;
    this.cameras.main.centerOn(this.camX, this.camY);

    this.buildHud();
    // fillAlpha must be 1 — GameObject.alpha multiplies it; a 0 fill never shows.
    this.fade = this.add
      .rectangle(0, 0, this.scale.width, this.scale.height, 0x000000, 1)
      .setOrigin(0, 0)
      .setScrollFactor(0)
      .setDepth(1000)
      .setAlpha(0);

    this.scale.on(Phaser.Scale.Events.RESIZE, this.onResize, this);
    this.unsubLocale = onLocaleChange(() => this.refreshHudText());

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.onResize, this);
      this.unsubLocale?.();
      this.unsubLocale = null;
      for (const peer of this.peers.values()) peer.avatar.destroy();
      this.peers.clear();
      for (const img of this.enemies.values()) img.destroy();
      this.enemies.clear();
    });

    this.onResize();
  }

  private onResize = () => {
    const { width, height } = this.scale;
    if (this.layers) resizeParallax(this.layers, width, height);
    this.fade?.setSize(width, height);
    this.hudRoot?.setPosition(12, 10);
    this.bossWrap?.setPosition(width / 2, 10);
    this.banner?.setPosition(width / 2, height * 0.4);
    this.goLabel?.setPosition(width / 2, height * 0.28);
    this.cameras.main.setSize(width, height);
  };

  private buildHud() {
    this.hudRoot = this.add.container(12, 10).setScrollFactor(0).setDepth(900);
    const barBg = this.add.image(0, 22, "brawler-bar-bg").setOrigin(0, 0.5);
    this.hpFill = this.add.image(2, 22, "brawler-bar-fill").setOrigin(0, 0.5);
    this.hpLabel = this.add
      .text(0, 4, "", {
        fontFamily: "monospace",
        fontSize: "14px",
        color: "#ffffff",
        stroke: "#000000",
        strokeThickness: 3,
      })
      .setOrigin(0, 0);
    this.waveLabel = this.add
      .text(210, 22, "", {
        fontFamily: "monospace",
        fontSize: "14px",
        color: "#ffe680",
        stroke: "#000000",
        strokeThickness: 3,
      })
      .setOrigin(0, 0.5);
    this.hudRoot.add([barBg, this.hpFill, this.hpLabel, this.waveLabel]);

    this.bossWrap = this.add.container(this.scale.width / 2, 10).setScrollFactor(0).setDepth(900).setVisible(false);
    const bossBg = this.add.image(0, 22, "brawler-bar-bg").setOrigin(0.5, 0.5).setDisplaySize(280, 18);
    this.bossFill = this.add.image(-138, 22, "brawler-boss-fill").setOrigin(0, 0.5);
    this.bossLabel = this.add
      .text(0, 4, "", {
        fontFamily: "monospace",
        fontSize: "14px",
        color: "#ff8899",
        stroke: "#000000",
        strokeThickness: 3,
      })
      .setOrigin(0.5, 0);
    this.bossWrap.add([bossBg, this.bossFill, this.bossLabel]);

    this.banner = this.add
      .text(this.scale.width / 2, this.scale.height * 0.4, "", {
        fontFamily: "monospace",
        fontSize: "42px",
        color: "#ffe680",
        stroke: "#000000",
        strokeThickness: 8,
      })
      .setOrigin(0.5)
      .setScrollFactor(0)
      .setDepth(950)
      .setVisible(false);

    this.goLabel = this.add
      .text(this.scale.width / 2, this.scale.height * 0.28, "", {
        fontFamily: "monospace",
        fontSize: "36px",
        color: "#ffe680",
        stroke: "#000000",
        strokeThickness: 6,
      })
      .setOrigin(0.5)
      .setScrollFactor(0)
      .setDepth(940)
      .setVisible(false);

    this.refreshHudText();
  }

  private refreshHudText() {
    this.hpLabel?.setText(this.hooks?.name || t("brawler.fighter"));
    this.bossLabel?.setText(t("brawler.boss"));
    this.goLabel?.setText(t("brawler.go"));
  }

  /** Route a brawler-related server message into the scene. */
  handleServerMessage(message: ServerMessage) {
    if (this.left) return;
    switch (message.type) {
      case "BrawlerWelcome":
        this.localId = message.data.player_id;
        this.localHp = message.data.hp;
        this.localMaxHp = message.data.max_hp;
        this.ensurePeer({
          id: message.data.player_id,
          name: this.hooks.name,
          skin: this.hooks.skin,
          cosmetic: this.hooks.cosmetic,
          x: message.data.x,
          y: message.data.y,
          hp: message.data.hp,
          max_hp: message.data.max_hp,
          facing: 0,
          moving: false,
          attacking: false,
          dead: false,
        });
        break;
      case "BrawlerSnapshot":
        this.applySnapshot(message.data);
        break;
      case "BrawlerPlayerDied":
        if (
          shouldBeginDeath({
            isLocal: message.data.player_id === this.localId,
            dead: true,
            ending: this.ending,
          })
        ) {
          this.beginDeath();
        }
        break;
      case "BrawlerWon":
        if (
          shouldBeginWin({
            isLocalWinner: !!(this.localId && message.data.player_ids.includes(this.localId)),
            ending: this.ending,
          })
        ) {
          this.beginWin();
        }
        break;
      default:
        break;
    }
  }

  private applySnapshot(snap: BrawlerSnapshotData) {
    const seen = new Set<UUID>();
    for (const p of snap.players) {
      seen.add(p.id);
      const peer = this.ensurePeer(p);
      peer.snap = p;
      peer.avatar.x = p.x;
      peer.avatar.y = p.y;
      peer.avatar.facing = p.facing;
      peer.avatar.moving = p.moving && !p.attacking && !p.dead;
      peer.avatar.running = false;
      peer.avatar.setSkin(toSkin(p.skin));
      peer.avatar.setCosmetic(toCosmetic(p.cosmetic));
      peer.avatar.setLabels({ name: p.name, you: p.id === this.localId, it: false });
      // Only start the tag clip on a fresh server attacking rising-edge.
      // Snapshots that keep attacking:true after the clip ends must not re-fire it.
      if (shouldPlayAttackAnim(p.attacking, peer.wasAttacking)) {
        peer.avatar.playTag(p.facing);
        if (p.id === this.localId) this.hooks.audio?.playSfx("brawlerHit", 0.85);
      }
      peer.wasAttacking = p.attacking;
      if (p.dead) peer.avatar.sprite.setAngle(90);
      else peer.avatar.sprite.setAngle(0);
      peer.avatar.setDrawn(shouldDrawBrawlerPeer({ dead: p.dead, ending: this.ending }));
      peer.avatar.update();
      // Y-sort like classic beat-'em-ups (lower feet = in front).
      peer.avatar.sprite.setDepth(20 + p.y);
      if (p.id === this.localId) {
        this.localHp = p.hp;
        this.localMaxHp = p.max_hp;
        // Belt-and-suspenders: if Died was missed, snapshot still starts the exit.
        if (shouldBeginDeath({ isLocal: true, dead: p.dead, ending: this.ending })) {
          this.beginDeath();
        }
      }
    }
    for (const [id, peer] of this.peers) {
      if (!seen.has(id)) {
        peer.avatar.destroy();
        this.peers.delete(id);
      }
    }

    const enemySeen = new Set<number>();
    for (const e of snap.enemies) {
      enemySeen.add(e.id);
      this.ensureEnemy(e);
    }
    for (const [id, img] of this.enemies) {
      if (!enemySeen.has(id)) {
        img.destroy();
        this.enemies.delete(id);
      }
    }

    this.lockLeft = snap.lock_left ?? null;
    this.lockRight = snap.lock_right ?? null;
    this.scrollMin = snap.scroll_min ?? this.scrollMin;
    this.updateHud(snap);
  }

  private ensurePeer(p: BrawlerPlayerSnap): Peer {
    const existing = this.peers.get(p.id);
    if (existing) return existing;
    const avatar = new KidAvatar(this, p.x, p.y, 14, p.name);
    avatar.setSkin(toSkin(p.skin));
    avatar.setCosmetic(toCosmetic(p.cosmetic));
    avatar.setRole(p.id === this.localId ? "self" : "human");
    avatar.setLabels({ name: p.name, you: p.id === this.localId, it: false });
    const peer = { avatar, snap: p, wasAttacking: false };
    this.peers.set(p.id, peer);
    return peer;
  }

  private ensureEnemy(e: EnemySnap) {
    let img = this.enemies.get(e.id);
    if (!img) {
      img = this.add.image(e.x, e.y, enemyKey(e.kind)).setOrigin(0.5, 1).setDepth(10);
      this.enemies.set(e.id, img);
    } else if (img.texture.key !== enemyKey(e.kind)) {
      img.setTexture(enemyKey(e.kind));
    }
    img.setPosition(e.x, e.y);
    img.setFlipX(Math.cos(e.facing) > 0);
    img.setTint(e.hit_flash ? 0xffffff : 0xffffff);
    img.setAlpha(e.hit_flash ? 0.7 : 1);
    if (e.hit_flash) img.setTint(0xffaaaa);
    else img.clearTint();
    img.setDepth(20 + e.y);
  }

  private updateHud(snap: BrawlerSnapshotData) {
    const ratio = this.localMaxHp > 0 ? Math.max(0, this.localHp / this.localMaxHp) : 0;
    this.hpFill.setScale(Math.max(0.001, ratio), 1);
    this.hpFill.setTint(ratio > 0.3 ? 0x33cc55 : ratio > 0.15 ? 0xcccc33 : 0xcc3344);
    this.waveLabel.setText(t("brawler.wave", { n: snap.wave }));
    const bossHp = snap.boss_hp;
    const bossMax = snap.boss_max_hp;
    if (bossHp != null && bossMax != null && bossMax > 0) {
      this.bossWrap.setVisible(true);
      this.bossFill.setScale(Math.max(0, bossHp / bossMax), 1);
      // Elite mini-boss is weaker than the final boss — retitle the bar.
      this.bossLabel.setText(bossMax < 400 ? "ELITE" : t("brawler.boss"));
    } else {
      this.bossWrap.setVisible(false);
    }
    if (snap.show_go && this.ending === "none") {
      this.goLabel.setText(t("brawler.go"));
      this.goLabel.setVisible(true);
      this.goLabel.setAlpha(0.55 + 0.45 * Math.abs(Math.sin(this.time.now / 220)));
    } else {
      this.goLabel.setVisible(false);
    }
  }

  update(_time: number, delta: number) {
    this.stepCamera(delta / 1000);
    if (this.left || this.ending !== "none") return;
    const move = this.hooks.readMove();
    let dx = move.dx;
    let dy = move.dy;
    // Prefer horizontal progress in a side-scroller; still allow lane Y.
    if (Math.abs(dx) < 0.05 && Math.abs(dy) < 0.05) {
      dx = 0;
      dy = 0;
    }
    const attack = this.hooks.readAttack();
    this.hooks.sendInput(dx, dy, attack);
  }

  /** Smooth group-follow camera with lock / scroll_min / parallax. */
  private stepCamera(dtSec: number) {
    const players = [...this.peers.values()].map(p => ({
      x: p.snap.x,
      y: p.snap.y,
      dead: p.snap.dead,
    }));
    const local = this.localId ? this.peers.get(this.localId) : null;
    const fallbackX = local?.snap.x ?? this.camX;
    const fallbackY = local?.snap.y ?? BRAWLER.groundY;
    const next = stepBrawlerCamera({
      currentX: this.camX,
      currentY: this.camY,
      players,
      fallbackX,
      fallbackY,
      lock: {
        scrollMin: this.scrollMin,
        lockLeft: this.lockLeft,
        lockRight: this.lockRight,
        worldW: BRAWLER.w,
        viewW: this.cameras.main.width,
        viewCenterY: 180,
      },
      dtSec,
    });
    // Round to whole pixels after lerp to kill sub-pixel jitter on sprites.
    this.camX = next.x;
    this.camY = next.y;
    this.cameras.main.centerOn(Math.round(this.camX), Math.round(this.camY));
    if (this.layers) {
      const o = parallaxOffsets(this.camX, this.cameras.main.width);
      this.layers.far.tilePositionX = o.far;
      this.layers.mid.tilePositionX = o.mid;
      this.layers.ground.tilePositionX = o.near;
    }
  }

  private beginDeath() {
    if (this.ending !== "none") return;
    this.ending = "dying";
    this.hooks.audio?.playSfx("hit", 0.9);
    const me = this.localId ? this.peers.get(this.localId) : null;
    if (me) {
      this.tweens.add({
        targets: me.avatar.sprite,
        angle: 90,
        alpha: 0.2,
        duration: 700,
        ease: "Sine.easeIn",
      });
    }
    this.tweens.add({
      targets: this.fade,
      alpha: 1,
      duration: 900,
      delay: 400,
      onComplete: () => {
        this.ending = "done";
        this.left = true;
        // Defer so we do not stop this scene from inside its own tween callback.
        this.time.delayedCall(0, () => this.hooks.onDied());
      },
    });
  }

  private beginWin() {
    if (this.ending !== "none") return;
    this.ending = "winning";
    this.hooks.audio?.playSfx("itemGet", 1);
    this.banner.setText(t("brawler.win"));
    this.banner.setVisible(true);
    this.banner.setScale(0.4);
    this.tweens.add({
      targets: this.banner,
      scale: 1.1,
      duration: 500,
      yoyo: true,
      hold: 800,
    });
    this.tweens.add({
      targets: this.fade,
      alpha: 1,
      duration: 800,
      delay: 1600,
      onComplete: () => {
        this.ending = "done";
        this.left = true;
        this.time.delayedCall(0, () => this.hooks.onWon());
      },
    });
  }
}
