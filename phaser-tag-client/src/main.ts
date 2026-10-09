import Phaser from "phaser";
import "./style.css";
import { GameSocket } from "./network";
import type { ServerMessage, PlayerSnapshot } from "./protocol";
import type { UUID } from "./types";
import { KidAvatar, createKidAnimations, preloadKid } from "./kid";
import { latchTagPress } from "./tagging";
import { createSchoolyard, type Occluder } from "./schoolyard";
import { PLAYER_RADIUS, PLAY_AREA, WORLD_HEIGHT, WORLD_WIDTH } from "./world";
import { GameAudio, type Sfx } from "./audio";
import { DEFAULT_SKIN, toSkin, type Skin } from "./skins";
import { MobileControls } from "./mobileControls";
import {
  SettingsPanel,
  controlsHint,
  loadSettings,
  type ControlMode,
  type Settings,
} from "./settings";
import { TitleScreen } from "./title";

/** Footstep sound for the local kid, per skin. */
const STEP_SFX: Record<Skin, Sfx> = {
  james: "step",
  banana: "bananaStep",
  trex: "trexStep",
  tuxedo: "tuxedoStep",
  pirate: "pirateStep",
  pharaoh: "pharaohStep",
};

/** Tag swing, when a skin has its own. */
const SWING_SFX: Partial<Record<Skin, Sfx>> = {
  pirate: "pirateSwing",
  pharaoh: "pharaohSwing",
};

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:8000/ws`;

const ROOM_ID = import.meta.env.VITE_ROOM_ID ?? "default";


/** Remote players count as "moving" while this far from their target (px). */
const REMOTE_MOVE_EPSILON = 1.5;
/** ...or for this long after their snapshot position last changed (ms). */
const REMOTE_MOVE_GRACE_MS = 120;
/** A snapshot-to-snapshot change smaller than this (px) doesn't count as moving. */
const REMOTE_SNAPSHOT_MOVE_PX = 0.5;
/** Keep a diagonal facing if the keys are let go within this window (ms). */
const DIAGONAL_RELEASE_MS = 120;
/** Max distance (px, between centres) for a client tag attempt. */
const TAG_DISTANCE = 70;
/** Tap mode: stop once the server position is this close to the target (px). */
const TAP_ARRIVE_PX = 10;
/** Footstep sound interval while walking / running (ms). */
const STEP_MS = { walk: 300, run: 190 };

type RemoteSprite = {
  avatar: KidAvatar;
  targetX: number;
  targetY: number;
  /** scene time (ms) when the snapshot position last changed */
  lastMovedAt: number;
  snapshot: PlayerSnapshot;
};

class GameScene extends Phaser.Scene {
  private socket!: GameSocket;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private keys!: Record<string, Phaser.Input.Keyboard.Key>;
  /** Local kid: null on the title screen until Start. */
  private player: KidAvatar | null = null;
  /** True after Start / Welcome: we are a player, not a spectator. */
  private playing = false;
  private playerFacingAngle = Math.PI / 2; // In radians; start facing the camera
  private wasMoving = false;
  private lastDiagonal: { angle: number; at: number } | null = null;

  private remotePlayers = new Map<UUID, RemoteSprite>();
  private localPlayerId: UUID | null = null;
  private localTargetX: number | null = null;
  private localTargetY: number | null = null;

  private sequence = 0;
  private inputTimer = 0;
  private tagCooldown = 0;
  /**
   * Space went down since the last step. Latched from the key itself, not
   * JustDown: a keyup in the same step clears JustDown, so Up+Left+Space
   * (a northwest walk-and-tag) was dropping the swing entirely.
   */
  private tagQueued = false;

  private connected = false;

  private audio: GameAudio | null = null;
  private controlMode: ControlMode = "keyboard";
  /** Settings modal open: game input is paused. */
  private uiOpen = false;
  /** Mobile mode tap-to-move destination (world px) and the last direction walked toward it. */
  private tapTarget: { x: number; y: number } | null = null;
  private tapDir: { x: number; y: number } | null = null;
  private tapDragging = false;
  /** Phaser pointer id doing the tap / drag-to-steer (multi-touch safe). */
  private tapPointerId: number | null = null;
  /** Mobile mode's on-screen Run button is held. */
  private runHeld = false;
  /** Mobile mode joystick direction (each axis -1..1; zero when released). */
  private joystick = { x: 0, y: 0 };
  private tapMarker!: Phaser.GameObjects.Container;
  private stepTimer = 0;
  /** Our chosen skin (Settings > Skins); sent on Join and with SetSkin. */
  private localSkin: Skin = DEFAULT_SKIN;

  private hudStatus!: HTMLElement;
  private hudEnergy!: HTMLElement;
  private hudPlayers!: HTMLElement;
  private hudEvents: HTMLElement | null = null;
  /** HUD bits that turn see-through while the local kid is behind them. */
  private hudOverlays: HTMLElement[] = [];

  constructor() {
    super("GameScene");
  }

  preload() {
    preloadKid(this);
  }

  create() {
    this.createWorld();
    createKidAnimations(this);

    // Title screen: watch the yard. Local kid is created on Start / Welcome.
    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    this.cameras.main.centerOn(900, 700);

    this.cursors = this.input.keyboard!.createCursorKeys();
    this.keys = this.input.keyboard!.addKeys("W,A,S,D,SHIFT,SPACE") as Record<
      string,
      Phaser.Input.Keyboard.Key
    >;
    // Latch Space on the key event. JustDown is false when the keyup is
    // processed in the same step (Key.onUp clears it first), which is how a
    // short tap arrives while two movement keys are already held.
    this.keys.SPACE.on("down", () => {
      if (!this.playing || this.uiOpen) return;
      this.tagQueued = latchTagPress(this.tagQueued, "down");
    });
    this.keys.SPACE.on("up", () => {
      this.tagQueued = latchTagPress(this.tagQueued, "up");
    });

    this.createTapControls();
    this.setUiOpen(this.uiOpen);

    this.socket = new GameSocket(WS_URL, {
      onOpen: () => {
        this.connected = true;
        // Spectator until Start: Hello arrives next; Join is sent from startPlaying().
        // After a reconnect (server restart / deploy, network blip) a player
        // who had pressed Start joins again automatically, in the same skin;
        // the server hands out a fresh "James N" in its Welcome.
        this.renderStatus();
        if (this.startRequested) {
          this.socket.send({
            type: "Join",
            data: { room_id: ROOM_ID, skin: this.localSkin },
          });
        }
      },
      onClose: ({ retryInMs }) => {
        const wasConnected = this.connected;
        this.connected = false;
        this.socketFailed = true;
        this.renderStatus();
        if (wasConnected) {
          // The next server is a fresh world: snap to wherever it spawns us
          // instead of sliding there, and drop any tap destination.
          this.localTargetX = null;
          this.localTargetY = null;
          this.clearTapTarget();
          this.rejoining = this.playing;
          this.logEvent("Connection lost, reconnecting…");
        }
        console.info(`[net] socket closed, retrying in ${retryInMs}ms`);
      },
      onError: () => {
        this.connected = false;
        this.socketFailed = true;
        this.renderStatus();
      },
      onMessage: message => this.handleServerMessage(message),
    });

    this.socket.connect();

    // Keep connection alive
    this.time.addEvent({
      delay: 5000,
      loop: true,
      callback: () => {
        this.socket.send({
          type: "Ping",
          data: { timestamp: Date.now() },
        });
      },
    });

    // Phaser already releases held keys when the window blurs; also do it
    // when the tab is hidden so a key-up we never saw can't leave the kid
    // walking.
    const releaseKeys = () => {
      if (document.hidden) this.input.keyboard?.resetKeys();
    };
    document.addEventListener("visibilitychange", releaseKeys);

    this.events.on("shutdown", () => {
      document.removeEventListener("visibilitychange", releaseKeys);
      this.socket.close();
    });
  }

  update(_time: number, delta: number) {
    if (this.playing) {
      this.updateLocalMovement(delta);

      this.inputTimer -= delta;
      if (this.inputTimer <= 0) {
        this.sendMovement();
        this.inputTimer = 50;
      }

      this.tagCooldown = Math.max(0, this.tagCooldown - delta);

      // SPACE tags (captured, so it never scrolls the page). Consumed from
      // the latch so a same-step press+release still swings.
      if (this.tagQueued) {
        this.tagQueued = false;
        this.tryTagNearest();
      }
    } else {
      this.updateSpectatorCamera();
      this.updateHud();
    }

    for (const remote of this.remotePlayers.values()) {
      const avatar = remote.avatar;
      avatar.x = Phaser.Math.Linear(avatar.x, remote.targetX, 0.25);
      avatar.y = Phaser.Math.Linear(avatar.y, remote.targetY, 0.25);
      avatar.facing = remote.snapshot.facing;
      avatar.running = remote.snapshot.is_running;
      avatar.moving =
        Phaser.Math.Distance.Between(avatar.x, avatar.y, remote.targetX, remote.targetY) >
          REMOTE_MOVE_EPSILON || this.time.now - remote.lastMovedAt < REMOTE_MOVE_GRACE_MS;
      avatar.update();
    }

    this.updateOcclusion?.(this.occlusionFeet());
  }

  private updateLocalMovement(delta: number) {
    if (!this.player) return;
    // The server is authoritative: we only send inputs (see sendMovement)
    // and ease toward the position it reports in each Snapshot.
    // Animation state comes from the input held *now* (keys, or an active
    // tap target), never from the eased position (which keeps drifting
    // toward the server for a few frames).
    this.updateTapTarget();
    const { dx, dy, running } = this.readInput();
    const moving = dx !== 0 || dy !== 0;
    if (moving) {
      this.playerFacingAngle = Math.atan2(dy, dx);
      if (dx !== 0 && dy !== 0) {
        this.lastDiagonal = { angle: this.playerFacingAngle, at: this.time.now };
      }
    } else if (
      this.wasMoving &&
      this.lastDiagonal &&
      this.time.now - this.lastDiagonal.at < DIAGONAL_RELEASE_MS
    ) {
      // Two keys are rarely released on the same frame: don't let the last
      // one turn a SE/SW/NE/NW kid to face S/E/N/W as they stop.
      this.playerFacingAngle = this.lastDiagonal.angle;
    }
    this.wasMoving = moving;

    if (moving) {
      this.stepTimer -= delta;
      if (this.stepTimer <= 0) {
        // Costumes have their own footsteps (squeaky / stomp / dress shoe / sand).
        this.audio?.playSfx(STEP_SFX[this.localSkin]);
        this.stepTimer = running ? STEP_MS.run : STEP_MS.walk;
      }
    } else {
      this.stepTimer = 0;
    }

    if (this.localTargetX !== null && this.localTargetY !== null) {
      this.player.x = Phaser.Math.Linear(this.player.x, this.localTargetX, 0.35);
      this.player.y = Phaser.Math.Linear(this.player.y, this.localTargetY, 0.35);
    }

    this.player.facing = this.playerFacingAngle;
    this.player.moving = moving;
    this.player.running = running;
    this.player.update();

    this.updateHud();
    this.fadeHudOverPlayer();
  }

  /**
   * Current movement input. Keyboard mode: dx/dy in {-1, 0, 1} from the keys.
   * Mobile mode: the joystick while it's pushed, otherwise the unit vector
   * toward the tap target (zero once arrived).
   * running = SHIFT (or the Run button) while moving. Nothing moves while
   * Settings is open.
   */
  private readInput() {
    let dx = 0;
    let dy = 0;
    if (this.uiOpen || !this.playing) return { dx, dy, running: false };
    if (this.controlMode === "mobile") {
      if (this.joystick.x !== 0 || this.joystick.y !== 0) ({ x: dx, y: dy } = this.joystick);
      else if (this.tapDir) ({ x: dx, y: dy } = this.tapDir);
      const runKey = this.keys.SHIFT.isDown || this.runHeld;
      return { dx, dy, running: runKey && (dx !== 0 || dy !== 0) };
    }
    if (this.cursors.left.isDown || this.keys.A.isDown) dx -= 1;
    if (this.cursors.right.isDown || this.keys.D.isDown) dx += 1;
    if (this.cursors.up.isDown || this.keys.W.isDown) dy -= 1;
    if (this.cursors.down.isDown || this.keys.S.isDown) dy += 1;
    const running = this.keys.SHIFT.isDown && (dx !== 0 || dy !== 0);
    return { dx, dy, running };
  }

  private sendMovement() {
    if (!this.connected || !this.playing) return;

    const input = this.readInput();
    let { dx, dy } = input;
    const { running } = input;

    if (dx !== 0 || dy !== 0) {
      const length = Math.hypot(dx, dy);
      dx /= length;
      dy /= length;
    }

    this.socket.send({
      type: "MoveInput",
      data: {
        seq: ++this.sequence,
        dx,
        dy,
        running,
      },
    });
  }

  private handleServerMessage(message: ServerMessage) {
    switch (message.type) {
      case "Hello":
        // Spectator: we receive snapshots of everyone else until Start.
        this.renderStatus();
        break;

      case "Snapshot":
        this.applySnapshot(message.data.players);
        break;

      case "Welcome":
        // Sent only to us, right after Join: this is our own player id.
        this.localPlayerId = message.data.player_id;
        this.removeRemotePlayer(message.data.player_id);
        this.spawnLocalPlayer(message.data.name);
        this.logEvent(`${this.rejoining ? "Reconnected" : "You joined"} as ${message.data.name}`);
        this.rejoining = false;
        break;

      case "PlayerJoined":
        if (message.data.player_id === this.localPlayerId) break;
        this.ensureRemotePlayer(message.data.player_id, message.data.name).avatar.setSkin(
          toSkin(message.data.skin)
        );
        this.audio?.playSfx("join");
        this.logEvent(`${message.data.name} joined`);
        this.updateHud();
        break;

      case "PlayerLeft": {
        const name = this.remotePlayers.get(message.data.player_id)?.snapshot.name;
        this.removeRemotePlayer(message.data.player_id);
        this.audio?.playSfx("leave");
        this.logEvent(`${name || "A player"} left`);
        this.updateHud();
        break;
      }

      case "PlayerTagged":
        this.flashTag(message.data.tagger_id, message.data.target_id);
        break;

      case "Pong":
        break;

      case "Error":
        // Keep the status line for the connection / name; errors go to the log.
        this.logEvent(`Server error: ${message.data.message}`);
        break;
    }
  }

  private applySnapshot(players: PlayerSnapshot[]) {
    for (const player of players) {
      if (this.playing && player.id === this.localPlayerId) {
        this.applyLocalSnapshot(player);
      } else if (player.id !== this.localPlayerId) {
        this.applyRemoteSnapshot(player);
      }
    }

    const currentIds = new Set(players.map(p => p.id));

    for (const [id] of this.remotePlayers) {
      if (!currentIds.has(id)) this.removeRemotePlayer(id);
    }

    this.updateHud();
  }

  private localEnergy = 100;

  private applyLocalSnapshot(player: PlayerSnapshot) {
    if (!this.player) return;
    // Snap to the server position on the first snapshot, then ease toward it.
    if (this.localTargetX === null) {
      this.player.x = player.x;
      this.player.y = player.y;
    }
    this.localTargetX = player.x;
    this.localTargetY = player.y;

    this.player.setLabels({ name: player.name, you: true, it: player.is_it });
    this.player.setRole(player.is_it ? "it" : "self");

    // Energy comes straight from our entry in the server snapshot.
    this.localEnergy = player.energy;
  }

  private applyRemoteSnapshot(player: PlayerSnapshot) {
    const isNew = !this.remotePlayers.has(player.id);
    const remote = this.ensureRemotePlayer(player.id);

    if (isNew) {
      // First time we see this player: appear in place instead of sliding in.
      remote.avatar.x = player.x;
      remote.avatar.y = player.y;
    }
    // Moved between snapshots (ignoring sub-pixel nudges)?
    if (Math.hypot(player.x - remote.targetX, player.y - remote.targetY) > REMOTE_SNAPSHOT_MOVE_PX) {
      remote.lastMovedAt = this.time.now;
    }

    remote.targetX = player.x;
    remote.targetY = player.y;
    remote.snapshot = player;

    // Ring under the feet: bots purple, other humans amber, IT red.
    remote.avatar.setRole(player.is_it ? "it" : player.is_bot ? "bot" : "human");

    // Outfit: switches live when that player changes skin.
    remote.avatar.setSkin(toSkin(player.skin));

    // Bots have no "BOT" text any more; their purple ring says it.
    remote.avatar.setLabels({ name: player.name, you: false, it: player.is_it });
  }

  private ensureRemotePlayer(id: UUID, name = ""): RemoteSprite {
    const existing = this.remotePlayers.get(id);
    if (existing) return existing;

    const x = WORLD_WIDTH / 2;
    const y = WORLD_HEIGHT / 2;
    const avatar = new KidAvatar(this, x, y, PLAYER_RADIUS, name);
    avatar.setRole("human");

    const remote: RemoteSprite = {
      avatar,
      targetX: x,
      targetY: y,
      lastMovedAt: -Infinity,
      snapshot: {
        id,
        name,
        skin: DEFAULT_SKIN,
        x,
        y,
        energy: 100,
        is_running: false,
        is_it: false,
        is_bot: false,
        facing: 0,
      },
    };

    this.remotePlayers.set(id, remote);
    return remote;
  }

  private removeRemotePlayer(id: UUID) {
    const remote = this.remotePlayers.get(id);
    if (!remote) return;

    remote.avatar.destroy();
    this.remotePlayers.delete(id);
  }

  private distanceToPlayer(remote: RemoteSprite) {
    if (!this.player) return Infinity;
    return Phaser.Math.Distance.Between(
      this.player.x,
      this.player.y,
      remote.avatar.x,
      remote.avatar.y
    );
  }

  private tryTagNearest() {
    let closest: RemoteSprite | null = null;
    let closestDistance = TAG_DISTANCE;

    for (const remote of this.remotePlayers.values()) {
      const distance = this.distanceToPlayer(remote);
      if (distance < closestDistance) {
        closest = remote;
        closestDistance = distance;
      }
    }
    this.tryTag(closest);
  }

  /** Swing at `closest` (a remote within TAG_DISTANCE), or at the air if null. */
  private tryTag(closest: RemoteSprite | null) {
    if (!this.connected || !this.playing || !this.player || this.tagCooldown > 0 || !this.localPlayerId) {
      return;
    }

    // Optimistic: swing the arm right away (toward the target if there is
    // one, otherwise straight ahead) without waiting for the server.
    if (closest) {
      this.playerFacingAngle = Math.atan2(
        closest.avatar.y - this.player.y,
        closest.avatar.x - this.player.x
      );
    }
    this.player.facing = this.playerFacingAngle;
    if (!this.player.isTagging) this.audio?.playSfx(SWING_SFX[this.localSkin] ?? "swing");
    this.player.playTag(this.playerFacingAngle);

    if (!closest) return;

    this.socket.send({
      type: "TagPlayer",
      data: {
        target_id: closest.snapshot.id,
      },
    });

    this.tagCooldown = 500;
  }

  private avatarFor(id: UUID): KidAvatar | null {
    if (id === this.localPlayerId) return this.player;
    return this.remotePlayers.get(id)?.avatar ?? null;
  }

  private flashTag(taggerId: UUID, targetId: UUID) {
    const taggedLocal = this.playing && targetId === this.localPlayerId;
    const taggingLocal = this.playing && taggerId === this.localPlayerId;

    // Tagger swings their arm toward whoever they tagged. (If we already
    // started the swing optimistically on SPACE / TAG, playTag() ignores the repeat.)
    const tagger = this.avatarFor(taggerId);
    const target = this.avatarFor(targetId);
    if (tagger) {
      tagger.playTag(
        target ? Math.atan2(target.y - tagger.y, target.x - tagger.x) : undefined
      );
    }

    if (taggedLocal || taggingLocal) {
      this.cameras.main.flash(180, 255, 255, 255);
      this.audio?.playSfx("hit");
    } else if (target) {
      // Other kids' tags: quieter the further away they happen.
      const origin = this.player ?? [...this.remotePlayers.values()][0]?.avatar;
      if (!origin) return;
      const d = Phaser.Math.Distance.Between(origin.x, origin.y, target.x, target.y);
      this.audio?.playSfx("hit", 0.7 * (1 - d / 900));
    }
  }

  // --- Settings hooks -------------------------------------------------------

  setAudio(audio: GameAudio) {
    this.audio = audio;
  }

  setControlMode(mode: ControlMode) {
    this.controlMode = mode;
    if (mode !== "mobile") {
      this.clearTapTarget();
      this.runHeld = false;
      this.joystick = { x: 0, y: 0 };
    }
  }

  /** Mobile joystick moved (or let go: 0, 0). Steering cancels tap-to-move. */
  setJoystick(dx: number, dy: number) {
    const was = this.joystick.x !== 0 || this.joystick.y !== 0;
    this.joystick = { x: dx, y: dy };
    const now = dx !== 0 || dy !== 0;
    if (now && this.tapTarget) this.clearTapTarget();
    if (was !== now) this.inputTimer = 0; // start / stop right away
  }

  /** Mobile Tag button: same as SPACE. */
  tagPressed() {
    if (!this.playing || this.uiOpen) return;
    this.tryTagNearest();
  }

  /**
   * Our skin: shown on our kid right away and sent to the server, which
   * puts it in the snapshots so everyone else sees it.
   */
  setSkin(skin: Skin) {
    const changed = skin !== this.localSkin;
    this.localSkin = skin;
    this.player?.setSkin(skin);
    // Only players (post-Start) can change skin on the server.
    if (changed && this.connected && this.playing) {
      this.socket.send({ type: "SetSkin", data: { skin } });
    }
  }

  /**
   * Title-screen Start: Join the room. Welcome creates the local kid and
   * dismisses the overlay (see spawnLocalPlayer).
   */
  /** True once the user has pressed Start (Join may still be in flight). */
  private startRequested = false;

  startPlaying() {
    if (this.playing || this.startRequested) return;
    this.startRequested = true;
    if (!this.connected) return; // Join as soon as onOpen fires
    this.socket.send({
      type: "Join",
      data: { room_id: ROOM_ID, skin: this.localSkin },
    });
  }

  /** After Welcome: spawn our kid, follow the camera, leave the title screen. */
  private spawnLocalPlayer(name: string) {
    this.localName = name;
    if (this.playing && this.player) {
      this.player.setLabels({ name, you: true, it: false });
      this.renderStatus();
      return;
    }
    const x = this.localTargetX ?? 400;
    const y = this.localTargetY ?? 300;
    this.player = new KidAvatar(this, x, y, PLAYER_RADIUS, name);
    this.player.setLabels({ name, you: true, it: false });
    this.player.setRole("self");
    this.player.setSkin(this.localSkin);
    this.cameras.main.startFollow(this.player.shadow, true, 0.12, 0.12);
    this.playing = true;
    this.renderStatus();
    document.body.classList.remove("title-mode");
    this.title?.dismiss();
    this.title = null;
    this.audio?.playSfx("join");
  }

  private title: TitleScreen | null = null;
  /** Fade tall props that are covering a kid (trees / bushes / fence). */
  private updateOcclusion: ((feet: ReadonlyArray<{ x: number; y: number; top: number }>) => void) | null = null;
  /** Tall props (trees / bushes / fence); used by occlusion + screenshot tests. */
  occluders: Occluder[] = [];

  setTitle(title: TitleScreen) {
    this.title = title;
  }

  /** Ease the camera toward nearby kids while watching from the title screen. */
  private updateSpectatorCamera() {
    const cam = this.cameras.main;
    // Anchor near the human spawn so the blacktop / yard stays in frame;
    // prefer the closest kids to that spot so far-away bots don't yank the view.
    const anchorX = 900;
    const anchorY = 700;
    const remotes = [...this.remotePlayers.values()].map(r => ({
      x: r.avatar.x,
      y: r.avatar.y,
      d: Math.hypot(r.avatar.x - anchorX, r.avatar.y - anchorY),
    }));
    remotes.sort((a, b) => a.d - b.d);
    const near = remotes.filter(r => r.d < 1600).slice(0, 4);
    let tx = anchorX;
    let ty = anchorY;
    if (near.length) {
      tx = near.reduce((s, r) => s + r.x, 0) / near.length;
      ty = near.reduce((s, r) => s + r.y, 0) / near.length;
    } else if (remotes.length) {
      tx = remotes[0].x;
      ty = remotes[0].y;
    }
    const cx = cam.scrollX + cam.width / 2;
    const cy = cam.scrollY + cam.height / 2;
    const far = Math.hypot(tx - cx, ty - cy) > 600;
    const k = far ? 0.25 : 0.06;
    cam.centerOn(Phaser.Math.Linear(cx, tx, k), Phaser.Math.Linear(cy, ty, k));
  }

  /** Mobile Run button: same `running` flag as SHIFT. */
  setRunHeld(held: boolean) {
    this.runHeld = held;
  }

  /** Pause game input while the Settings modal is open. */
  setUiOpen(open: boolean) {
    this.uiOpen = open;
    this.tagQueued = false;
    this.tapDragging = false;
    const keyboard = this.input?.keyboard;
    if (!keyboard) return; // not created yet; create() applies it
    keyboard.enabled = !open;
    keyboard.resetKeys();
    // Phaser preventDefault()s captured keys (arrows, WASD, Space...) on the
    // window; release them so sliders, the dropdown and Tab work in the modal.
    if (open) keyboard.disableGlobalCapture();
    else keyboard.enableGlobalCapture();
  }

  // --- Tap-to-move ------------------------------------------------------------

  private createTapControls() {
    const ring = this.add.ellipse(0, 0, 30, 13).setStrokeStyle(3, 0xffffff, 0.95);
    const dot = this.add.ellipse(0, 0, 8, 4, 0xffffff, 0.95);
    this.tapMarker = this.add.container(0, 0, [ring, dot]).setDepth(2).setVisible(false);
    this.tweens.add({
      targets: ring,
      scale: 1.35,
      alpha: 0.35,
      duration: 520,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });

    // Phaser only reports presses on the canvas itself, so clicks on the
    // HUD, the cog or the modal never reach these handlers.
    this.input.on(Phaser.Input.Events.POINTER_DOWN, (pointer: Phaser.Input.Pointer) => {
      if (!this.playing || this.controlMode !== "mobile" || this.uiOpen) return;
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      const kid = this.remoteAt(world.x, world.y);
      if (kid && this.distanceToPlayer(kid) < TAG_DISTANCE) {
        this.tryTag(kid); // tap a nearby kid: tag them
        return;
      }
      // Tap the ground (or a far-away kid): walk there; drag to steer.
      this.tapDragging = true;
      this.tapPointerId = pointer.id;
      this.setTapTarget(kid ? kid.avatar.x : world.x, kid ? kid.avatar.y : world.y);
    });
    this.input.on(Phaser.Input.Events.POINTER_MOVE, (pointer: Phaser.Input.Pointer) => {
      if (!this.tapDragging || pointer.id !== this.tapPointerId || !pointer.isDown) return;
      if (this.controlMode !== "mobile" || this.uiOpen) return;
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      this.setTapTarget(world.x, world.y);
    });
    const stopDrag = (pointer: Phaser.Input.Pointer) => {
      if (pointer.id === this.tapPointerId) this.tapDragging = false;
    };
    this.input.on(Phaser.Input.Events.POINTER_UP, stopDrag);
    this.input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, stopDrag);
  }

  /** Topmost remote kid whose sprite covers world point (x, y). */
  private remoteAt(x: number, y: number): RemoteSprite | null {
    let best: RemoteSprite | null = null;
    for (const remote of this.remotePlayers.values()) {
      if (remote.avatar.hitTest(x, y) && (!best || remote.avatar.y > best.avatar.y)) best = remote;
    }
    return best;
  }

  private setTapTarget(x: number, y: number) {
    // Stay just inside the fence so we can actually arrive.
    const m = 2;
    this.tapTarget = {
      x: Phaser.Math.Clamp(x, PLAY_AREA.minX + m, PLAY_AREA.maxX - m),
      y: Phaser.Math.Clamp(y, PLAY_AREA.minY + m, PLAY_AREA.maxY - m),
    };
    this.tapDir = null;
    this.tapMarker.setPosition(this.tapTarget.x, this.tapTarget.y).setVisible(true);
    this.updateTapTarget();
  }

  private clearTapTarget() {
    this.tapTarget = null;
    this.tapDir = null;
    this.tapDragging = false;
    this.tapMarker?.setVisible(false);
  }

  /** Steer toward the tap target from the server position; stop on arrival. */
  private updateTapTarget() {
    if (!this.tapTarget || !this.player) return;
    const x = this.localTargetX ?? this.player.x;
    const y = this.localTargetY ?? this.player.y;
    const dx = this.tapTarget.x - x;
    const dy = this.tapTarget.y - y;
    const d = Math.hypot(dx, dy);
    const dir = d > 0 ? { x: dx / d, y: dy / d } : null;
    // Arrived, or stepped past it (direction flipped): stop, don't jitter.
    if (
      !dir ||
      d <= TAP_ARRIVE_PX ||
      (this.tapDir && dir.x * this.tapDir.x + dir.y * this.tapDir.y < 0)
    ) {
      if (!this.tapDragging) this.clearTapTarget();
      else this.tapDir = null;
      this.inputTimer = 0; // send the stop now, not up to 50ms later
      return;
    }
    this.tapDir = dir;
  }

  private createWorld() {
    // Decorative schoolyard (grass, blacktop courts, track, diamond,
    // playground, trees, fence on the world edge). Visual only.
    const yard = createSchoolyard(this, WORLD_WIDTH, WORLD_HEIGHT);
    this.updateOcclusion = yard.updateOcclusion;
    this.occluders = yard.occluders;
  }

  /** Feet + head-top of every on-screen kid, for schoolyard occlusion. */
  private occlusionFeet() {
    const out: { x: number; y: number; top: number }[] = [];
    const add = (avatar: KidAvatar) => {
      out.push({ x: avatar.x, y: avatar.feetY, top: avatar.labelTop });
    };
    if (this.player) add(this.player);
    for (const remote of this.remotePlayers.values()) add(remote.avatar);
    return out;
  }

  /** Our "James N" name from Welcome (shown in the status panel). */
  private localName: string | null = null;
  private hudConnection: HTMLElement | null = null;

  /**
   * Status panel line: green light + our "James N" name once joined; green
   * + "Connected" while spectating before Start (the panel is hidden on the
   * title screen anyway); red + "Not Connected" when the socket is closed or
   * errored; amber + "Connecting…" before the first open.
   */
  private renderStatus() {
    const state = this.connected ? "connected" : this.everConnected || this.socketFailed ? "error" : "connecting";
    if (this.connected) this.everConnected = true;
    const text =
      state === "connected" ? (this.playing && this.localName) || "Connected"
      : state === "error" ? "Not Connected"
      : "Connecting…";
    if (this.hudStatus && this.hudStatus.textContent !== text) this.hudStatus.textContent = text;
    if (this.hudConnection) {
      this.hudConnection.classList.toggle("connected", state === "connected");
      this.hudConnection.classList.toggle("error", state === "error");
      this.hudConnection.title = text;
    }
  }
  private everConnected = false;
  /** Lost the connection while playing; the next Welcome is a rejoin. */
  private rejoining = false;
  private socketFailed = false;

  private logEvent(text: string) {
    console.log(`[game] ${text}`);
    if (!this.hudEvents) return;

    const entry = document.createElement("div");
    entry.textContent = text;
    this.hudEvents.appendChild(entry);
    while (this.hudEvents.childElementCount > 5) {
      this.hudEvents.firstElementChild?.remove();
    }
    setTimeout(() => entry.remove(), 6000);
  }

  setHudElements(
    status: HTMLElement,
    energy: HTMLElement,
    players: HTMLElement,
    events?: HTMLElement,
    connection?: HTMLElement
  ) {
    this.hudEvents = events ?? null;
    this.hudConnection = connection ?? null;
    this.hudStatus = status;
    this.hudEnergy = energy;
    this.hudPlayers = players;
    this.renderStatus();
    this.updateHud();
  }

  /** HUD elements to fade when the local kid walks under them (corners). */
  setHudOverlays(elements: HTMLElement[]) {
    this.hudOverlays = elements;
  }

  /**
   * Near the world edges the camera stops scrolling, so the local kid can
   * end up under the status panel, the cog, the hint, the joystick or the
   * Tag / Run buttons.
   * Make whichever one covers the kid (body + labels) see-through.
   */
  private fadeHudOverPlayer() {
    if (!this.playing || this.hudOverlays.length === 0 || !this.player) return;
    const cam = this.cameras.main;
    const view = cam.worldView;
    const b = this.player.bounds;
    const canvas = this.game.canvas.getBoundingClientRect();
    const kid = {
      left: canvas.left + (b.left - view.x) * cam.zoom,
      right: canvas.left + (b.right - view.x) * cam.zoom,
      top: canvas.top + (b.top - view.y) * cam.zoom,
      bottom: canvas.top + (b.bottom - view.y) * cam.zoom,
    };
    // Read every rect first, then write classes (no layout thrash).
    const hits = this.hudOverlays.map(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.left < kid.right && kid.left < r.right && r.top < kid.bottom && kid.top < r.bottom;
    });
    this.hudOverlays.forEach((el, i) => {
      if (el.classList.contains("see-through") !== hits[i]) el.classList.toggle("see-through", hits[i]);
    });
  }

  private updateHud() {
    if (!this.hudEnergy || !this.hudPlayers) return;

    const energy = Phaser.Math.Clamp(this.localEnergy, 0, 100);
    this.hudEnergy.style.transform = `scaleX(${energy / 100})`;
    // Spectator: remotes only. Playing: remotes + you.
    const count = this.remotePlayers.size + (this.playing ? 1 : 0);
    this.hudPlayers.textContent = `${count} player${count === 1 ? "" : "s"}`;
  }
}

const scene = new GameScene();

const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: window.innerWidth,
  height: window.innerHeight,
  backgroundColor: "#171b24",
  render: {
    antialias: true,
    roundPixels: true,
  },
  scale: {
    mode: Phaser.Scale.RESIZE,
    autoCenter: Phaser.Scale.CENTER_BOTH,
    width: "100%",
    height: "100%",
  },
  input: {
    // Tap mode: one finger steers while another holds the Run button.
    activePointers: 3,
  },
  physics: {
    default: "arcade",
    arcade: {
      debug: false,
    },
  },
  scene,
});

const hud = document.createElement("div");
hud.className = "hud";
hud.innerHTML = `
  <div class="status">
    <div>
      <span id="connection" class="connection"></span>
      <strong id="status">Connecting…</strong>
    </div>
    <div>Players: <span id="players">1</span></div>
    <div>Energy</div>
    <div class="energy-bar">
      <div id="energy" class="energy-fill"></div>
    </div>
    <div id="events" class="events"></div>
  </div>

  <div class="controls"></div>
`;

document.body.appendChild(hud);

const status = document.querySelector("#status") as HTMLElement;
const energy = document.querySelector("#energy") as HTMLElement;
const players = document.querySelector("#players") as HTMLElement;
const connection = document.querySelector("#connection") as HTMLElement;

const events = document.querySelector("#events") as HTMLElement;

scene.setHudElements(status, energy, players, events, connection);

// Settings (cog + modal), audio and the Run button; prefs live in localStorage.
const { settings, saved } = loadSettings();
const audio = new GameAudio(settings);
audio.installGestureUnlock();
scene.setAudio(audio);
scene.setSkin(settings.skin);

document.body.classList.add("title-mode");
const title = new TitleScreen({
  onStart: () => scene.startPlaying(),
  onSound: () => audio.playSfx("click"),
});
scene.setTitle(title);

const controls = hud.querySelector(".controls") as HTMLElement;
const mobileControls = new MobileControls(hud, {
  onJoystick: (dx, dy) => scene.setJoystick(dx, dy),
  onRunHeld: held => scene.setRunHeld(held),
  onTag: () => scene.tagPressed(),
});

const applyControls = (s: Readonly<Settings>) => {
  scene.setControlMode(s.controlMode);
  controls.innerHTML = controlsHint(s.controlMode);
  mobileControls.setVisible(s.controlMode === "mobile");
  mobileControls.setLayout(s.leftyJoystick, s.flipTagRun);
  // Lets the CSS keep the controls hint clear of the joystick / buttons.
  hud.dataset.mode = s.controlMode;
  hud.dataset.lefty = String(s.leftyJoystick);
};
applyControls(settings);

const settingsPanel = new SettingsPanel(hud, settings, saved, {
  onChange: (s, key) => {
    audio.apply(s);
    applyControls(s);
    if (key === "skin") scene.setSkin(s.skin);
  },
  onOpenChange: open => scene.setUiOpen(open),
  onSound: kind => audio.playSfx(kind === "preview" ? "join" : "click"),
});
scene.setHudOverlays([
  hud.querySelector(".status") as HTMLElement,
  controls,
  settingsPanel.cog,
  ...mobileControls.overlays,
]);

// Dev-only hooks for Playwright / live debugging (not shipped in prod builds).
if (import.meta.env.DEV) {
  (window as unknown as { __scene: GameScene; __audio: GameAudio }).__scene = scene;
  (window as unknown as { __scene: GameScene; __audio: GameAudio }).__audio = audio;
}

window.addEventListener("resize", () => game.scale.resize(window.innerWidth, window.innerHeight));
