import Phaser from "phaser";
import "./style.css";
import { GameSocket } from "./network";
import type { ServerMessage, PlayerSnapshot } from "./protocol";
import type { UUID } from "./types";
import { KidAvatar, createKidAnimations, preloadKid } from "./kid";
import { applyPhysicalKey, movementAxes, noteTagKey, physicalCode } from "./tagging";
import { createSchoolyard, type Occluder } from "./schoolyard";
import { PLAYER_RADIUS, PLAY_AREA, WORLD_HEIGHT, WORLD_WIDTH } from "./world";
import { GameAudio, type Sfx } from "./audio";
import { SecretDungeonScene, type DungeonHooks } from "./secretDungeon";
import {
  nearSecretTree,
  predominantDirection,
  secretGate,
  SecretSequence,
  type SecretGate,
} from "./secretSequence";
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
import { SIGN_READ_DISTANCE, SignModal, createSigns, setPromptText, type PlacedSign, type SignDef } from "./signs";
import { initI18n, onLocaleChange, t, tPlayers } from "./i18n";
import { LanguagePicker } from "./languagePicker";
import {
  ZOOM_KEY_STEP,
  clampLevel,
  clampZoom,
  levelFromZoom,
  takeWheelLevels,
  zoomFromLevel,
  zoomLevelsFromWheel,
} from "./zoom";

initI18n();

/** Footstep sound for the local kid, per skin. */
const STEP_SFX: Record<Skin, Sfx> = {
  james: "step",
  banana: "bananaStep",
  trex: "trexStep",
  tuxedo: "tuxedoStep",
  pirate: "pirateStep",
  pharaoh: "pharaohStep",
  spaceman: "spacemanStep",
  wizard: "wizardStep",
  centaur: "centaurStep",
  tennis: "tennisStep",
};

/** Tag swing, when a skin has its own. */
const SWING_SFX: Partial<Record<Skin, Sfx>> = {
  pirate: "pirateSwing",
  pharaoh: "pharaohSwing",
  spaceman: "spacemanSwing",
  wizard: "wizardSwing",
  centaur: "centaurSwing",
  tennis: "tennisSwing",
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
/**
 * Where a human appeared before the server picked a random spot.
 * Welcome / PlayerJoined from an older server omit x/y; stand here until
 * the next snapshot says otherwise.
 */
const LEGACY_SPAWN_X = 400;
const LEGACY_SPAWN_Y = 300;

/** A placeable world position. Missing, null, NaN and Infinity are not. */
function finitePoint(x: unknown, y: unknown): { x: number; y: number } | null {
  if (typeof x === "number" && typeof y === "number" && Number.isFinite(x) && Number.isFinite(y)) {
    return { x, y };
  }
  return null;
}
/** Tap mode: stop once the server position is this close to the target (px). */
const TAP_ARRIVE_PX = 10;
/** Second tap within this window and distance counts as a double-tap (run). */
const DOUBLE_TAP_MS = 320;
const DOUBLE_TAP_PX = 48;
/** A press that drifts farther than this is a drag, not a tap. */
const TAP_SLOP_PX = 22;

const ZOOM_CODES = new Set(["ArrowUp", "ArrowDown", "KeyW", "KeyS"]);

function isAltEvent(event: KeyboardEvent): boolean {
  return event.key === "Alt" || event.code === "AltLeft" || event.code === "AltRight";
}
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
  /**
   * Physical keys held right now (`event.code`, not Phaser keyCode).
   * Arrows and WASD share this set; Space is latched separately.
   */
  private held = new Set<string>();
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
   * Space went down since the last step. Latched from the DOM `code`
   * ("Space"), not from Phaser's Space Key: that object only updates when
   * `keyCode === 32`. Arrow Up+Left still walk (their keyCodes arrive) while
   * a Space mash in the same step, or a Space event whose keyCode is 0, never
   * reached the latch — walk only, no swing. Keyup of an arrow must not clear
   * this; only a fresh step consumes it.
   */
  private tagQueued = false;

  private connected = false;

  private audio: GameAudio | null = null;
  private controlMode: ControlMode = "keyboard";
  /** Mobile mode with the joystick and Tag / Run buttons hidden. */
  private hideButtons = false;
  /**
   * Camera zoom slider level. 0 is the normal view. Pinch, zoom keys, the
   * mouse wheel, and the View tab all write this; the camera applies a
   * world-bounds clamp.
   */
  private zoomLevel = 0;
  private onZoomLevel: ((level: number) => void) | null = null;
  /** Alt is held, so W / S and Up / Down zoom instead of walking. */
  private altHeld = false;
  /** How long a zoom chord has been held, for the repeat after the first tap. */
  private zoomHoldMs = 0;
  /** Fractional slider levels from Alt + wheel that have not made a whole step yet. */
  private wheelRemainder = 0;
  /** Two-finger pinch: taps from those fingers must not walk or tag. */
  private pinchLock = false;
  private pinch: { dist: number; zoom: number } | null = null;
  private touches = new Map<number, { x: number; y: number }>();
  /** Double-tap run while the on-screen buttons are hidden. */
  private tapRunning = false;
  private lastTap: { t: number; x: number; y: number } | null = null;
  /** Where the current ground press started, so a drag isn't a double-tap. */
  private tapOrigin: { x: number; y: number } | null = null;
  private pendingTag: { id: number; kid: RemoteSprite; x: number; y: number } | null = null;
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
  /**
   * Hidden quest. While `inSecret` the kid is in the cave: we send no moves,
   * the server marks them away (still in the world, not taggable, omitted
   * from snapshots), and the schoolyard avatar is hidden. See enterSecret.
   */
  private readonly secret = new SecretSequence();
  private secretGateState: SecretGate = { awayAt: null };
  private secretTree: { x: number; y: number } | null = null;
  private inSecret = false;
  private secretReturn: { x: number; y: number } | null = null;

  private signs: PlacedSign[] = [];
  /** Sign the local kid is close enough to read, if any. */
  private nearSign: PlacedSign | null = null;
  /** Opens the sign popup (wired by the bootstrap). */
  onReadSign: ((sign: SignDef) => void) | null = null;

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
    this.syncZoom();
    this.scale.on(Phaser.Scale.Events.RESIZE, this.onResize);
    this.installPinch();
    this.installWheel();

    // One listener for arrows and WASD. Capture phase runs before Phaser's
    // bubble listener, which drops the event when keyCode is 0 or when
    // defaultPrevented is already set — the Up+Left+Space miss. preventDefault
    // here also stops the browser from treating the arrows as scroll.
    window.addEventListener("keydown", this.onDomKey, true);
    window.addEventListener("keyup", this.onDomKey, true);

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
          this.logEvent(t("toast.connectionLost"));
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
      if (document.hidden) {
        this.input.keyboard?.resetKeys();
        this.held.clear();
        this.altHeld = false;
        this.wheelRemainder = 0;
      }
    };
    const onBlur = () => {
      this.held.clear();
      this.altHeld = false;
      this.wheelRemainder = 0;
    };
    document.addEventListener("visibilitychange", releaseKeys);
    window.addEventListener("blur", onBlur);

    this.events.on("shutdown", () => {
      document.removeEventListener("visibilitychange", releaseKeys);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("keydown", this.onDomKey, true);
      window.removeEventListener("keyup", this.onDomKey, true);
      this.scale.off(Phaser.Scale.Events.RESIZE, this.onResize);
      this.removePinch();
      this.removeWheel();
      this.socket.close();
    });
  }

  private readonly onResize = () => {
    this.syncZoom();
  };

  /**
   * Arrows, WASD, Shift, Space, and T. Space and T share one latch: either
   * keyup does not forget a press that landed in this same step (see
   * noteTagKey), and an arrow keyup doesn't either.
   */
  private readonly onDomKey = (event: KeyboardEvent) => {
    const phase: "down" | "up" = event.type === "keydown" ? "down" : "up";
    if (isAltEvent(event)) {
      this.altHeld = phase === "down";
      if (!this.altHeld) this.wheelRemainder = 0;
    }
    if (this.uiOpen) {
      // Settings owns the keyboard. Drop movement keys as they release so
      // closing the modal can't leave a stuck walk.
      if (phase === "up") {
        this.held = applyPhysicalKey(this.held, event, "up");
        if (isAltEvent(event)) {
          this.altHeld = false;
          this.wheelRemainder = 0;
        }
      }
      return;
    }
    if (physicalCode(event) || isAltEvent(event)) event.preventDefault();
    this.held = applyPhysicalKey(this.held, event, phase);
    // A tap of the zoom chord steps once. Holding repeats from updateZoomHold.
    // W / S and the up / down arrows are in `held`, but movement ignores them
    // while Alt is down (see movementAxes altZoom).
    if (phase === "down" && !event.repeat && this.altHeld) {
      const code = physicalCode(event);
      const chord = (code !== null && ZOOM_CODES.has(code)) || isAltEvent(event);
      const dir = this.zoomKeyDir();
      if (chord && dir !== 0) {
        this.requestZoom(this.zoomLevel + dir * ZOOM_KEY_STEP);
        this.zoomHoldMs = 0;
      }
    }
    if (!this.playing) return;
    this.tagQueued = noteTagKey(this.tagQueued, event, phase);
  };

  /** +1 zoom in, -1 zoom out, 0 when both directions are held (or neither). */
  private zoomKeyDir(): number {
    let dir = 0;
    if (this.held.has("ArrowUp") || this.held.has("KeyW")) dir += 1;
    if (this.held.has("ArrowDown") || this.held.has("KeyS")) dir -= 1;
    return Math.sign(dir);
  }

  update(_time: number, delta: number) {
    this.updateSigns();
    this.updateZoomHold(delta);
    if (this.inSecret) {
      // The cave scene reads keys / the joystick itself. Drop tag presses
      // so leaving the cave doesn't swing, and don't send MoveInput.
      this.tagQueued = false;
    } else if (this.playing) {
      this.tagCooldown = Math.max(0, this.tagCooldown - delta);

      // Space or T (captured, so Space never scrolls the page). Consumed
      // before movement so the swing starts in the facing we already have,
      // and the walk clip this frame cannot replace it.
      if (this.tagQueued) {
        this.tagQueued = false;
        if (!this.readSignIfNear() && !this.observeSecretTag()) this.tryTagNearest();
      }

      this.updateLocalMovement(delta);

      if (!this.inSecret) {
        this.inputTimer -= delta;
        if (this.inputTimer <= 0) {
          this.sendMovement();
          this.inputTimer = 50;
        }
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
    this.observeSecretMove(dx, dy);
    if (this.inSecret) return;
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
        this.playEffect(STEP_SFX[this.localSkin]);
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
      const shift =
        this.held.has("ShiftLeft") || this.held.has("ShiftRight") || this.held.has("Shift");
      return { dx, dy, running: (shift || this.runHeld || this.tapRunning) && (dx !== 0 || dy !== 0) };
    }
    return movementAxes(this.held, { altZoom: this.altHeld });
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
        // Sent only to us, right after Join: this is our own player id and
        // the spot the server chose. A reconnect is a new body there.
        // Older servers omit x/y; spawnLocalPlayer falls back and the next
        // snapshot moves us.
        this.localPlayerId = message.data.player_id;
        this.removeRemotePlayer(message.data.player_id);
        this.spawnLocalPlayer(message.data.name, message.data.x, message.data.y);
        this.logEvent(
          t(this.rejoining ? "toast.reconnected" : "toast.joinedSelf", { name: message.data.name })
        );
        this.rejoining = false;
        break;

      case "PlayerJoined":
        if (message.data.player_id === this.localPlayerId) break;
        this.ensureRemotePlayer(message.data.player_id, message.data.name, message.data.x, message.data.y).avatar.setSkin(
          toSkin(message.data.skin)
        );
        this.logEvent(t("toast.joined", { name: message.data.name }));
        this.updateHud();
        this.playEffect("join");
        break;

      case "PlayerLeft": {
        const name = this.remotePlayers.get(message.data.player_id)?.snapshot.name;
        this.removeRemotePlayer(message.data.player_id);
        this.logEvent(name ? t("toast.left", { name }) : t("toast.leftUnknown"));
        this.updateHud();
        this.playEffect("leave");
        break;
      }

      case "PlayerTagged":
        this.flashTag(message.data.tagger_id, message.data.target_id);
        break;

      case "Pong":
        break;

      case "Error":
        // Keep the status line for the connection / name; errors go to the log.
        this.logEvent(t("toast.serverError", { message: message.data.message }));
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
    const spot = finitePoint(player.x, player.y);
    if (spot) {
      // First report of where we are (no Welcome coords yet): appear there
      // and put the camera on that spot in the same frame. Later snapshots
      // ease, so a normal correction doesn't yank the view.
      if (this.localTargetX === null) {
        this.player.x = spot.x;
        this.player.y = spot.y;
        this.snapCameraToLocalPlayer();
      }
      this.localTargetX = spot.x;
      this.localTargetY = spot.y;
    }

    this.player.setLabels({ name: player.name, you: true, it: player.is_it });
    this.player.setRole(player.is_it ? "it" : "self");

    // Energy comes straight from our entry in the server snapshot.
    this.localEnergy = player.energy;
  }

  private applyRemoteSnapshot(player: PlayerSnapshot) {
    const isNew = !this.remotePlayers.has(player.id);
    const remote = this.ensureRemotePlayer(player.id);
    const spot = finitePoint(player.x, player.y);

    if (spot) {
      if (isNew) {
        // First time we see this player: appear in place instead of sliding in.
        remote.avatar.x = spot.x;
        remote.avatar.y = spot.y;
      }
      // Moved between snapshots (ignoring sub-pixel nudges)?
      if (Math.hypot(spot.x - remote.targetX, spot.y - remote.targetY) > REMOTE_SNAPSHOT_MOVE_PX) {
        remote.lastMovedAt = this.time.now;
      }

      remote.targetX = spot.x;
      remote.targetY = spot.y;
    }
    remote.snapshot = spot ? player : { ...player, x: remote.targetX, y: remote.targetY };

    // Ring under the feet: bots purple, other humans amber, IT red.
    remote.avatar.setRole(player.is_it ? "it" : player.is_bot ? "bot" : "human");

    // Outfit: switches live when that player changes skin.
    remote.avatar.setSkin(toSkin(player.skin));

    // Bots have no "BOT" text any more; their purple ring says it.
    remote.avatar.setLabels({ name: player.name, you: false, it: player.is_it });
  }

  private ensureRemotePlayer(id: UUID, name = "", x?: number, y?: number): RemoteSprite {
    const existing = this.remotePlayers.get(id);
    if (existing) return existing;
    // Before join coordinates existed, other kids were drawn at the world
    // centre until a snapshot placed them.
    const spot = finitePoint(x, y) ?? { x: WORLD_WIDTH / 2, y: WORLD_HEIGHT / 2 };
    const avatar = new KidAvatar(this, spot.x, spot.y, PLAYER_RADIUS, name);
    avatar.setRole("human");

    const remote: RemoteSprite = {
      avatar,
      targetX: spot.x,
      targetY: spot.y,
      lastMovedAt: -Infinity,
      snapshot: {
        id,
        name,
        skin: DEFAULT_SKIN,
        x: spot.x,
        y: spot.y,
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

    // Optimistic: swing right away in the direction we're already facing.
    // A nearby player does not turn the clip, and walking does not cancel it.
    if (!this.player.isTagging) this.playEffect(SWING_SFX[this.localSkin] ?? "swing");
    this.player.playTag();

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
      // atan2 of a NaN position is NaN. playTag then falls back to the
      // facing the kid already has, instead of `kid-tag-undefined`.
      const toward =
        target && finitePoint(tagger.x, tagger.y) && finitePoint(target.x, target.y)
          ? Math.atan2(target.y - tagger.y, target.x - tagger.x)
          : undefined;
      tagger.playTag(toward !== undefined && Number.isFinite(toward) ? toward : undefined);
    }

    if (taggedLocal || taggingLocal) {
      this.cameras.main.flash(180, 255, 255, 255);
      this.playEffect("hit");
    } else if (target) {
      // Other kids' tags: quieter the further away they happen.
      const origin = this.player ?? [...this.remotePlayers.values()][0]?.avatar;
      if (!origin) return;
      const d = Phaser.Math.Distance.Between(origin.x, origin.y, target.x, target.y);
      const volume = 0.7 * (1 - d / 900);
      if (!Number.isFinite(volume)) return;
      this.playEffect("hit", Math.max(0, volume));
    }
  }

  // --- Settings hooks -------------------------------------------------------

  setAudio(audio: GameAudio) {
    this.audio = audio;
  }

  /**
   * Play a sound without letting a WebAudio failure skip the rest of the
   * caller (a server message's log line and HUD, for example).
   */
  private playEffect(name: Sfx, volume?: number) {
    try {
      this.audio?.playSfx(name, volume);
    } catch (error) {
      console.warn("[audio] sfx failed:", name, error);
    }
  }

  setPlayControls(mode: ControlMode, hideButtons: boolean) {
    this.controlMode = mode;
    this.hideButtons = hideButtons;
    if (!hideButtons) this.tapRunning = false;
    if (mode !== "mobile") {
      this.clearTapTarget();
      this.runHeld = false;
      this.joystick = { x: 0, y: 0 };
      this.pendingTag = null;
    }
  }

  /** Mobile joystick moved (or let go: 0, 0). Steering cancels tap-to-move. */
  setJoystick(dx: number, dy: number) {
    const was = this.joystick.x !== 0 || this.joystick.y !== 0;
    this.joystick = { x: dx, y: dy };
    const now = dx !== 0 || dy !== 0;
    if (now && this.tapTarget) this.clearTapTarget();
    if (now) this.tapRunning = false;
    if (was !== now) this.inputTimer = 0; // start / stop right away
  }

  /** Mobile Tag button: same as SPACE. */
  tagPressed() {
    if (!this.playing || this.uiOpen || this.inSecret) return;
    if (this.readSignIfNear()) return;
    if (!this.observeSecretTag()) this.tryTagNearest();
  }

  /**
   * Axes the cave should treat as keyboard / joystick movement. Tap-to-move
   * inside the cave is handled there; the schoolyard tap target is not.
   */
  dungeonAxes(): { dx: number; dy: number; mode: ControlMode } {
    if (this.controlMode === "keyboard") {
      const axes = movementAxes(this.held, { altZoom: this.altHeld });
      return { dx: axes.dx, dy: axes.dy, mode: "keyboard" };
    }
    if (this.joystick.x !== 0 || this.joystick.y !== 0) {
      return { dx: this.joystick.x, dy: this.joystick.y, mode: "mobile" };
    }
    return { dx: 0, dy: 0, mode: "mobile" };
  }

  /**
   * Feed one tag press into the hidden sequence when the kid is in the tree.
   * True when that press opened the cave (the caller should not also swing).
   */
  private observeSecretTag(): boolean {
    if (!this.feedSecret()) return false;
    if (this.secret.tag(this.time.now)) {
      this.enterSecret();
      return true;
    }
    return false;
  }

  /** One movement sample. Holding a direction counts as a single step. */
  private observeSecretMove(dx: number, dy: number) {
    if (!this.feedSecret()) return;
    if (this.secret.move(predominantDirection(dx, dy), this.time.now)) this.enterSecret();
  }

  /** True when a sample should reach the matcher. Applies the leave grace. */
  private feedSecret(): boolean {
    if (this.inSecret || this.uiOpen || !this.playing || !this.player || !this.secretTree) return false;
    const near = nearSecretTree(this.player.x, this.player.y, this.secretTree);
    const gated = secretGate(this.secretGateState, near, this.secret.inProgress, this.time.now);
    this.secretGateState = gated.gate;
    if (gated.reset) this.secret.reset();
    return gated.accept;
  }

  /**
   * Open the cave. Multiplayer: the kid stays in the server world at this
   * spot (IT, energy, and name are untouched) but we zero movement and send
   * SetAway. The server then ignores further MoveInput, refuses tags to or
   * from them, and leaves them out of snapshots, so other players see them
   * vanish and cannot tag the empty spot. Coming back clears the flag and
   * shows them here again, next to the secret tree.
   */
  private enterSecret() {
    if (this.inSecret || !this.player) return;
    this.inSecret = true;
    this.secret.reset();
    this.secretGateState = { awayAt: null };
    const x = this.localTargetX ?? this.player.x;
    const y = this.localTargetY ?? this.player.y;
    this.secretReturn = { x, y };
    this.clearTapTarget();
    this.player.setDrawn(false);
    this.socket.send({
      type: "MoveInput",
      data: { seq: ++this.sequence, dx: 0, dy: 0, running: false },
    });
    this.socket.send({ type: "SetAway", data: { away: true } });
    this.audio?.playSecret();
    document.body.classList.add("in-secret");
    const hooks: DungeonHooks = {
      skin: this.localSkin,
      audio: this.audio,
      readMove: () => this.dungeonAxes(),
      onExit: () => this.exitSecret(),
    };
    this.scene.launch("SecretDungeon", hooks);
  }

  /** Back to the schoolyard, on the spot we left (beside the secret tree). */
  private exitSecret() {
    if (!this.inSecret) return;
    this.scene.stop("SecretDungeon");
    this.inSecret = false;
    document.body.classList.remove("in-secret");
    this.socket.send({ type: "SetAway", data: { away: false } });
    this.tagQueued = false;
    this.held.clear();
    this.joystick = { x: 0, y: 0 };
    this.runHeld = false;
    this.clearTapTarget();
    this.secret.reset();
    this.secretGateState = { awayAt: null };
    const spot = this.secretReturn;
    if (this.player && spot) {
      this.player.x = spot.x;
      this.player.y = spot.y;
      this.localTargetX = spot.x;
      this.localTargetY = spot.y;
      this.player.setDrawn(true);
      this.cameras.main.centerOn(spot.x, spot.y);
    } else {
      this.player?.setDrawn(true);
    }
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

  /**
   * After Welcome: spawn our kid at the server's spot and put the camera
   * there immediately. A rejoin (the kid already exists) teleports instead
   * of easing across the yard from wherever we were standing. Coming back
   * from the secret cave does not use this path — that returns beside the
   * secret tree (see exitSecret).
   */
  private spawnLocalPlayer(name: string, x?: number, y?: number) {
    this.localName = name;
    const spot = finitePoint(x, y);
    // No usable server spot: the old fixed spawn, and leave the easing
    // target empty when we don't already have one so the next snapshot snaps.
    const px = spot?.x ?? this.localTargetX ?? LEGACY_SPAWN_X;
    const py = spot?.y ?? this.localTargetY ?? LEGACY_SPAWN_Y;
    if (spot) {
      this.localTargetX = spot.x;
      this.localTargetY = spot.y;
    }
    if (this.playing && this.player) {
      this.player.x = px;
      this.player.y = py;
      this.player.setLabels({ name, you: true, it: false });
      this.snapCameraToLocalPlayer();
      this.renderStatus();
      return;
    }
    this.player = new KidAvatar(this, px, py, PLAYER_RADIUS, name);
    this.player.setLabels({ name, you: true, it: false });
    this.player.setRole("self");
    this.player.setSkin(this.localSkin);
    this.snapCameraToLocalPlayer();
    this.playing = true;
    this.renderStatus();
    document.body.classList.remove("title-mode");
    this.title?.dismiss();
    this.title = null;
    this.playEffect("join");
  }

  /**
   * Centre the camera on our kid this frame. `startFollow` writes scroll
   * immediately (the lerp only applies on later frames), so the view does
   * not slide in from the title camera or from a previous spawn.
   */
  private snapCameraToLocalPlayer() {
    if (!this.player) return;
    this.player.update();
    this.cameras.main.startFollow(this.player.shadow, true, 0.12, 0.12);
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
    this.held.clear();
    this.altHeld = false;
    this.zoomHoldMs = 0;
    this.wheelRemainder = 0;
    this.tapDragging = false;
    this.pendingTag = null;
    const keyboard = this.input?.keyboard;
    if (!keyboard) return; // not created yet; create() applies it
    keyboard.enabled = !open;
    keyboard.resetKeys();
    // The DOM listener stops calling preventDefault while this is open, so
    // arrows, Space and Tab reach the modal. Release Phaser's capture too.
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
    // HUD, the cog, the hint's X, or the modal never reach these handlers.
    this.input.on(Phaser.Input.Events.POINTER_DOWN, (pointer: Phaser.Input.Pointer) => {
      if (!this.playing || this.controlMode !== "mobile" || this.uiOpen || this.inSecret) return;
      if (this.pinchLock || this.touches.size >= 2) {
        this.pendingTag = null;
        this.clearTapTarget();
        return;
      }
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      // Tapping a sign reads it from anywhere; it never walks or tags.
      const sign = this.signAt(world.x, world.y);
      if (sign && this.onReadSign) {
        this.pendingTag = null;
        this.clearTapTarget();
        this.onReadSign(sign);
        return;
      }
      const kid = this.remoteAt(world.x, world.y);
      // In range: wait for the finger to lift before tagging, so a second
      // finger (a pinch) can cancel it. Out of range: walk toward them.
      if (kid && this.distanceToPlayer(kid) < TAG_DISTANCE) {
        this.pendingTag = { id: pointer.id, kid, x: pointer.x, y: pointer.y };
        this.tapRunning = false;
        return;
      }
      const now = this.time.now;
      const double =
        this.hideButtons &&
        this.lastTap !== null &&
        now - this.lastTap.t <= DOUBLE_TAP_MS &&
        Phaser.Math.Distance.Between(pointer.x, pointer.y, this.lastTap.x, this.lastTap.y) <= DOUBLE_TAP_PX;
      this.tapRunning = double;
      this.tapDragging = true;
      this.tapPointerId = pointer.id;
      this.tapOrigin = { x: pointer.x, y: pointer.y };
      this.setTapTarget(kid ? kid.avatar.x : world.x, kid ? kid.avatar.y : world.y);
    });
    this.input.on(Phaser.Input.Events.POINTER_MOVE, (pointer: Phaser.Input.Pointer) => {
      if (this.pinchLock || this.controlMode !== "mobile" || this.uiOpen) return;
      if (this.pendingTag && pointer.id === this.pendingTag.id && pointer.isDown) {
        const moved = Phaser.Math.Distance.Between(pointer.x, pointer.y, this.pendingTag.x, this.pendingTag.y);
        if (moved <= TAP_SLOP_PX) return;
        const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
        this.pendingTag = null;
        this.tapRunning = false;
        this.tapDragging = true;
        this.tapPointerId = pointer.id;
        this.tapOrigin = { x: pointer.x, y: pointer.y };
        this.setTapTarget(world.x, world.y);
        return;
      }
      if (!this.tapDragging || pointer.id !== this.tapPointerId || !pointer.isDown) return;
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      this.setTapTarget(world.x, world.y);
    });
    const stopDrag = (pointer: Phaser.Input.Pointer) => {
      if (this.pinchLock) {
        if (this.pendingTag?.id === pointer.id) this.pendingTag = null;
        if (pointer.id === this.tapPointerId) this.tapDragging = false;
        return;
      }
      if (this.pendingTag && this.pendingTag.id === pointer.id) {
        const moved = Phaser.Math.Distance.Between(pointer.x, pointer.y, this.pendingTag.x, this.pendingTag.y);
        const kid = this.pendingTag.kid;
        this.pendingTag = null;
        if (moved <= TAP_SLOP_PX) {
          this.lastTap = { t: this.time.now, x: pointer.x, y: pointer.y };
          if (this.distanceToPlayer(kid) < TAG_DISTANCE && !this.observeSecretTag()) this.tryTag(kid);
        }
        return;
      }
      if (pointer.id !== this.tapPointerId) return;
      const dragged =
        this.tapOrigin !== null &&
        Phaser.Math.Distance.Between(pointer.x, pointer.y, this.tapOrigin.x, this.tapOrigin.y) > TAP_SLOP_PX;
      this.tapDragging = false;
      this.tapOrigin = null;
      // A drag isn't the first half of a double-tap.
      if (dragged) this.lastTap = null;
      else this.lastTap = { t: this.time.now, x: pointer.x, y: pointer.y };
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
    this.tapRunning = false;
    this.tapOrigin = null;
    this.tapMarker?.setVisible(false);
  }

  // --- Camera zoom ------------------------------------------------------------

  /** Settings, pinch, wheel, and zoom keys all meet here. Returns the level actually shown. */
  setZoomLevel(level: number): number {
    const cam = this.cameras?.main;
    if (!cam || !(cam.width > 0) || !(cam.height > 0)) {
      this.zoomLevel = clampLevel(level);
      return this.zoomLevel;
    }
    const zoom = clampZoom(zoomFromLevel(level), cam.width, cam.height);
    const effective = levelFromZoom(zoom);
    this.zoomLevel = effective;
    if (Math.abs(cam.zoom - zoom) > 0.0005) cam.setZoom(zoom);
    return effective;
  }

  setZoomListener(listener: (level: number) => void) {
    this.onZoomLevel = listener;
  }

  /** Apply the stored level and tell Settings if the world bounds clamped it. */
  syncZoom() {
    this.requestZoom(this.zoomLevel);
  }

  private requestZoom(level: number) {
    const applied = this.setZoomLevel(level);
    this.onZoomLevel?.(applied);
  }

  private updateZoomHold(delta: number) {
    if (this.uiOpen || this.inSecret || !this.altHeld || this.zoomKeyDir() === 0) {
      this.zoomHoldMs = 0;
      return;
    }
    this.zoomHoldMs += delta;
    if (this.zoomHoldMs < 180) return;
    const step = Math.max(1, Math.round(delta * 0.055));
    this.requestZoom(this.zoomLevel + this.zoomKeyDir() * step);
  }

  private installWheel() {
    // passive: false is required. On window, browsers otherwise treat wheel
    // as passive and ignore preventDefault, so Alt + wheel would still
    // scroll the page or trigger a browser zoom.
    window.addEventListener("wheel", this.onWheel, { capture: true, passive: false });
  }

  private removeWheel() {
    window.removeEventListener("wheel", this.onWheel, { capture: true });
  }

  /**
   * Alt + wheel up zooms in, Alt + wheel down zooms out, on the same
   * slider the keys and the View tab use. A wheel without Alt is left
   * alone (the page, and the browser, keep their own behavior).
   */
  private readonly onWheel = (event: WheelEvent) => {
    if (!event.altKey) return;
    event.preventDefault();
    if (this.uiOpen || this.inSecret) {
      this.wheelRemainder = 0;
      return;
    }
    const delta = zoomLevelsFromWheel(event.deltaY, event.deltaMode);
    const taken = takeWheelLevels(this.wheelRemainder, delta);
    this.wheelRemainder = taken.remainder;
    if (taken.levels === 0) return;
    const before = this.zoomLevel;
    this.requestZoom(before + taken.levels);
    // The slider end or the map filling the window ate part of the step.
    // Drop the leftover so the next nudge the other way is not stuck paying it back.
    if (this.zoomLevel !== before + taken.levels) this.wheelRemainder = 0;
  };

  private installPinch() {
    window.addEventListener("touchstart", this.onTouchStart, { capture: true, passive: false });
    window.addEventListener("touchmove", this.onTouchMove, { capture: true, passive: false });
    window.addEventListener("touchend", this.onTouchEnd, { capture: true, passive: false });
    window.addEventListener("touchcancel", this.onTouchEnd, { capture: true, passive: false });
  }

  private removePinch() {
    window.removeEventListener("touchstart", this.onTouchStart, { capture: true });
    window.removeEventListener("touchmove", this.onTouchMove, { capture: true });
    window.removeEventListener("touchend", this.onTouchEnd, { capture: true });
    window.removeEventListener("touchcancel", this.onTouchEnd, { capture: true });
  }

  /** Joystick / Tag / Run / the hint sit above the canvas and are not pinches. */
  private onGameSurface(touch: Touch): boolean {
    const canvas = this.game?.canvas;
    const target = touch.target;
    if (!canvas || !(target instanceof Node)) return false;
    return target === canvas || canvas.contains(target);
  }

  private readonly onTouchStart = (event: TouchEvent) => {
    if (this.uiOpen || this.inSecret) return;
    for (const touch of event.changedTouches) {
      if (!this.onGameSurface(touch)) continue;
      this.touches.set(touch.identifier, { x: touch.clientX, y: touch.clientY });
    }
    if (this.touches.size < 2) return;
    if (event.cancelable) event.preventDefault();
    this.pinchLock = true;
    this.pendingTag = null;
    this.lastTap = null;
    this.clearTapTarget();
    this.inputTimer = 0;
    this.armPinch();
  };

  private readonly onTouchMove = (event: TouchEvent) => {
    for (const touch of event.changedTouches) {
      if (!this.touches.has(touch.identifier)) continue;
      this.touches.set(touch.identifier, { x: touch.clientX, y: touch.clientY });
    }
    if (!this.pinchLock || this.touches.size < 2) return;
    if (event.cancelable) event.preventDefault();
    this.armPinch();
    if (!this.pinch) return;
    const dist = this.touchSpan();
    if (dist < 12) return;
    const cam = this.cameras.main;
    const zoom = clampZoom(this.pinch.zoom * (dist / this.pinch.dist), cam.width, cam.height);
    this.requestZoom(levelFromZoom(zoom));
  };

  private readonly onTouchEnd = (event: TouchEvent) => {
    for (const touch of event.changedTouches) this.touches.delete(touch.identifier);
    if (this.touches.size < 2) this.pinch = null;
    if (this.touches.size === 0 && this.pinchLock) {
      // pointerup can land in this same turn; keep the lock until it has
      // skipped the tag, then drop it.
      queueMicrotask(() => {
        if (this.touches.size === 0) this.pinchLock = false;
      });
    }
  };

  private touchSpan(): number {
    const pts = [...this.touches.values()];
    if (pts.length < 2) return 0;
    return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
  }

  /** Remember the finger span once it's wide enough to be a real pinch. */
  private armPinch() {
    if (this.pinch) return;
    const dist = this.touchSpan();
    if (dist < 24) return;
    const cam = this.cameras.main;
    this.pinch = { dist, zoom: cam.zoom > 0 ? cam.zoom : zoomFromLevel(this.zoomLevel) };
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
    this.secretTree = yard.secretTree;
    this.signs = createSigns(this);
  }

  /** Show the read prompt over the closest sign in range. */
  private updateSigns() {
    let best: PlacedSign | null = null;
    if (this.playing && this.player && !this.inSecret && !this.uiOpen) {
      let bestD = SIGN_READ_DISTANCE;
      for (const s of this.signs) {
        const d = Phaser.Math.Distance.Between(this.player.x, this.player.feetY, s.x, s.y);
        if (d < bestD) {
          bestD = d;
          best = s;
        }
      }
    }
    this.nearSign = best;
    for (const s of this.signs) {
      const show = s === best;
      if (show) {
        setPromptText(
          s,
          this.controlMode === "mobile" && !this.hideButtons
            ? t("sign.prompt.mobile")
            : t("sign.prompt.keyboard", { key: "Space / T" })
        );
      }
      if (s.prompt.visible !== show) s.prompt.setVisible(show);
    }
  }

  /** Sign under a world point, padded to at least a 48px screen target. */
  private signAt(x: number, y: number): PlacedSign | null {
    const pad = Math.max(6, 24 / this.cameras.main.zoom);
    let best: PlacedSign | null = null;
    let bestD = Infinity;
    for (const s of this.signs) {
      const cy = s.y - 22;
      if (Math.abs(x - s.x) > 22 + pad || Math.abs(y - cy) > 25 + pad) continue;
      const d = Math.hypot(x - s.x, y - cy);
      if (d < bestD) {
        bestD = d;
        best = s;
      }
    }
    return best;
  }

  /** Tag pressed: read a nearby sign instead of swinging. */
  private readSignIfNear(): boolean {
    if (!this.nearSign || !this.onReadSign) return false;
    this.onReadSign(this.nearSign);
    return true;
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
      state === "connected" ? (this.playing && this.localName) || t("hud.connected")
      : state === "error" ? t("hud.notConnected")
      : t("hud.connecting");
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
    this.hudPlayers.textContent = tPlayers(count);
  }

  /** Connection line, counts, and YOU / IT, in the current language. */
  applyLocale() {
    this.renderStatus();
    this.updateHud();
    this.player?.applyLocale();
    for (const remote of this.remotePlayers.values()) remote.avatar.applyLocale();
  }
}

const scene = new GameScene();
const secretDungeon = new SecretDungeonScene();

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
  scene: [scene, secretDungeon],
});

const hud = document.createElement("div");
hud.className = "hud";
hud.innerHTML = `
  <div class="status">
    <div>
      <span id="connection" class="connection"></span>
      <strong id="status"></strong>
    </div>
    <div><span id="players-label"></span> <span id="players"></span></div>
    <div id="energy-label"></div>
    <div class="energy-bar">
      <div id="energy" class="energy-fill"></div>
    </div>
    <div id="events" class="events"></div>
  </div>

  <div class="controls">
    <p class="controls-copy"></p>
    <button type="button" class="controls-dismiss">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>
      </svg>
    </button>
  </div>
`;

document.body.appendChild(hud);

const status = document.querySelector("#status") as HTMLElement;
const energy = document.querySelector("#energy") as HTMLElement;
const players = document.querySelector("#players") as HTMLElement;
const connection = document.querySelector("#connection") as HTMLElement;

const events = document.querySelector("#events") as HTMLElement;
const playersLabel = document.querySelector("#players-label") as HTMLElement;
const energyLabel = document.querySelector("#energy-label") as HTMLElement;

const paintHudLabels = () => {
  playersLabel.textContent = t("hud.playersLabel");
  energyLabel.textContent = t("hud.energy");
};
paintHudLabels();

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
const hintCopy = controls.querySelector(".controls-copy") as HTMLElement;
const hintDismiss = controls.querySelector(".controls-dismiss") as HTMLButtonElement;
/** Not saved. Comes back on a Keyboard / Mobile switch and on refresh. */
let hintDismissed = false;

const stopHintPress = (event: Event) => {
  event.preventDefault();
  event.stopPropagation();
};
hintDismiss.addEventListener("pointerdown", stopHintPress);
hintDismiss.addEventListener("pointerup", stopHintPress);
hintDismiss.addEventListener("click", event => {
  stopHintPress(event);
  hintDismissed = true;
  controls.hidden = true;
  hintDismiss.blur();
});

const mobileControls = new MobileControls(hud, {
  onJoystick: (dx, dy) => scene.setJoystick(dx, dy),
  onRunHeld: held => scene.setRunHeld(held),
  onTag: () => scene.tagPressed(),
});

const paintHint = (s: Readonly<Settings>) => {
  hintCopy.innerHTML = controlsHint(s);
  hintDismiss.setAttribute("aria-label", t("hint.dismiss"));
  hintDismiss.title = t("hint.dismiss");
  controls.hidden = hintDismissed;
};

const applyControls = (s: Readonly<Settings>, key?: keyof Settings) => {
  if (key === "controlMode") hintDismissed = false;
  scene.setPlayControls(s.controlMode, s.hideButtons);
  paintHint(s);
  mobileControls.setVisible(s.controlMode === "mobile" && !s.hideButtons);
  mobileControls.setLayout(s.leftyJoystick, s.flipTagRun);
  // Lets the CSS keep the controls hint clear of the joystick / buttons.
  hud.dataset.mode = s.controlMode;
  hud.dataset.lefty = String(s.leftyJoystick);
  hud.dataset.hideButtons = String(s.hideButtons);
};
applyControls(settings);

const chrome: { closeSettings: () => void; settingsOpen: boolean; closePicker: () => void; pickerOpen: boolean; signOpen: boolean } = {
  signOpen: false,
  closeSettings: () => {},
  settingsOpen: false,
  closePicker: () => {},
  pickerOpen: false,
};

const settingsPanel = new SettingsPanel(hud, settings, saved, {
  onChange: (s, key) => {
    if (key === "zoom") {
      const applied = scene.setZoomLevel(s.zoom);
      if (applied !== s.zoom) settingsPanel.adoptZoom(applied);
      return;
    }
    audio.apply(s);
    applyControls(s, key);
    if (key === "skin") scene.setSkin(s.skin);
  },
  onOpenChange: open => {
    chrome.settingsOpen = open;
    if (open) chrome.closePicker();
    scene.setUiOpen(open || chrome.pickerOpen || chrome.signOpen);
  },
  onSound: kind => audio.playSfx(kind === "preview" ? "join" : "click"),
});
chrome.closeSettings = () => {
  if (settingsPanel.isOpen) settingsPanel.close();
};

const languagePicker = new LanguagePicker(hud, {
  onSound: () => audio.playSfx("click"),
  onOpenChange: open => {
    chrome.pickerOpen = open;
    if (open) chrome.closeSettings();
    scene.setUiOpen(open || chrome.settingsOpen || chrome.signOpen);
  },
});
const signModal = new SignModal(hud, {
  label: key => t(key === "ok" ? "sign.ok" : "sign.close"),
  onSound: () => audio.playSfx("click"),
  onOpenChange: open => {
    chrome.signOpen = open;
    scene.setUiOpen(open || chrome.settingsOpen || chrome.pickerOpen);
  },
});
scene.onReadSign = sign => {
  chrome.closeSettings();
  chrome.closePicker();
  signModal.open(sign);
};

chrome.closePicker = () => {
  if (languagePicker.isOpen) languagePicker.close();
};

// Seed the saved level before the listener exists. syncZoom otherwise
// reports the scene's default (0) and the listener would save that over
// the stored choice.
scene.setZoomLevel(settings.zoom);
scene.setZoomListener(level => settingsPanel.adoptZoom(level));
scene.syncZoom();

onLocaleChange(() => {
  paintHudLabels();
  paintHint(settingsPanel.settings);
  mobileControls.applyLocale();
  scene.applyLocale();
});

scene.setHudOverlays([
  hud.querySelector(".status") as HTMLElement,
  controls,
  settingsPanel.cog,
  languagePicker.button,
  ...mobileControls.overlays,
]);

// Dev-only hooks for Playwright / live debugging (not shipped in prod builds).
if (import.meta.env.DEV) {
  (window as unknown as { __scene: GameScene; __audio: GameAudio }).__scene = scene;
  (window as unknown as { __scene: GameScene; __audio: GameAudio }).__audio = audio;
}

window.addEventListener("resize", () => game.scale.resize(window.innerWidth, window.innerHeight));
