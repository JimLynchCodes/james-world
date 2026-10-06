import Phaser from "phaser";
import "./style.css";
import { GameSocket } from "./network";
import type { ServerMessage, PlayerSnapshot } from "./protocol";
import type { UUID } from "./types";
import { KidAvatar, createKidAnimations, preloadKid } from "./kid";
import { createSchoolyard } from "./schoolyard";
import { GameAudio } from "./audio";
import {
  SettingsPanel,
  controlsHint,
  loadSettings,
  type ControlMode,
} from "./settings";

const WS_URL =
  import.meta.env.VITE_WS_URL ??
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:8000/ws`;

const ROOM_ID = import.meta.env.VITE_ROOM_ID ?? "default";

const WORLD_WIDTH = 5000;
const WORLD_HEIGHT = 5000;

// Server collision radius; the kid sprite (~64px tall) is sized around it.
const PLAYER_RADIUS = 18;

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
  private player!: KidAvatar;
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

  private connected = false;

  private audio: GameAudio | null = null;
  private controlMode: ControlMode = "keyboard";
  /** Settings modal open: game input is paused. */
  private uiOpen = false;
  /** Tap mode destination (world px) and the last direction walked toward it. */
  private tapTarget: { x: number; y: number } | null = null;
  private tapDir: { x: number; y: number } | null = null;
  private tapDragging = false;
  private tapMarker!: Phaser.GameObjects.Container;
  private stepTimer = 0;

  private hudStatus!: HTMLElement;
  private hudEnergy!: HTMLElement;
  private hudPlayers!: HTMLElement;
  private hudEvents: HTMLElement | null = null;

  constructor() {
    super("GameScene");
  }

  preload() {
    preloadKid(this);
  }

  create() {
    this.createWorld();
    createKidAnimations(this);

    // The sprite's facing direction replaces the old white pointer dot.
    this.player = new KidAvatar(this, WORLD_WIDTH / 2, WORLD_HEIGHT / 2, PLAYER_RADIUS, "YOU");
    this.player.setRole("self");

    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    // Follow the ground ring (logical position), not the sprite, so the
    // tag lunge doesn't shake the camera.
    this.cameras.main.startFollow(this.player.shadow, true, 0.12, 0.12);

    this.cursors = this.input.keyboard!.createCursorKeys();
    this.keys = this.input.keyboard!.addKeys("W,A,S,D,SHIFT,E") as Record<
      string,
      Phaser.Input.Keyboard.Key
    >;

    this.createTapControls();
    this.setUiOpen(this.uiOpen);

    this.socket = new GameSocket(WS_URL, {
      onOpen: () => {
        this.connected = true;
        this.setStatus("Connected");
        this.socket.send({
          type: "Join",
          data: { room_id: ROOM_ID },
        });
      },
      onClose: () => {
        this.connected = false;
        this.setStatus("Disconnected");
      },
      onError: () => {
        this.connected = false;
        this.setStatus("Connection error");
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
    this.updateLocalMovement(delta);

    this.inputTimer -= delta;
    if (this.inputTimer <= 0) {
      this.sendMovement();
      this.inputTimer = 50;
    }

    this.tagCooldown = Math.max(0, this.tagCooldown - delta);

    if (Phaser.Input.Keyboard.JustDown(this.keys.E)) {
      this.tryTagNearest();
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
  }

  private updateLocalMovement(delta: number) {
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
        this.audio?.playSfx("step");
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
  }

  /**
   * Current movement input. Keyboard mode: dx/dy in {-1, 0, 1} from the keys.
   * Tap mode: unit vector toward the tap target (zero once arrived).
   * running = SHIFT while moving. Nothing moves while Settings is open.
   */
  private readInput() {
    let dx = 0;
    let dy = 0;
    if (this.uiOpen) return { dx, dy, running: false };
    if (this.controlMode === "tap") {
      if (this.tapDir) ({ x: dx, y: dy } = this.tapDir);
      return { dx, dy, running: this.keys.SHIFT.isDown && (dx !== 0 || dy !== 0) };
    }
    if (this.cursors.left.isDown || this.keys.A.isDown) dx -= 1;
    if (this.cursors.right.isDown || this.keys.D.isDown) dx += 1;
    if (this.cursors.up.isDown || this.keys.W.isDown) dy -= 1;
    if (this.cursors.down.isDown || this.keys.S.isDown) dy += 1;
    const running = this.keys.SHIFT.isDown && (dx !== 0 || dy !== 0);
    return { dx, dy, running };
  }

  private sendMovement() {
    if (!this.connected) return;

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
      case "Snapshot":
        this.applySnapshot(message.data.players);
        break;

      case "Welcome":
        // Sent only to us, before anything else: this is our own player id.
        this.localPlayerId = message.data.player_id;
        this.removeRemotePlayer(message.data.player_id);
        this.logEvent(`You joined as ${message.data.player_id.slice(0, 8)}`);
        break;

      case "PlayerJoined":
        if (message.data.player_id === this.localPlayerId) break;
        this.ensureRemotePlayer(message.data.player_id);
        this.audio?.playSfx("join");
        this.logEvent(`Player ${message.data.player_id.slice(0, 8)} joined`);
        this.updateHud();
        break;

      case "PlayerLeft":
        this.removeRemotePlayer(message.data.player_id);
        this.audio?.playSfx("leave");
        this.logEvent(`Player ${message.data.player_id.slice(0, 8)} left`);
        this.updateHud();
        break;

      case "PlayerTagged":
        this.flashTag(message.data.tagger_id, message.data.target_id);
        break;

      case "Pong":
        break;

      case "Error":
        this.setStatus(`Server error: ${message.data.message}`);
        break;
    }
  }

  private applySnapshot(players: PlayerSnapshot[]) {
    for (const player of players) {
      if (player.id === this.localPlayerId) {
        this.applyLocalSnapshot(player);
      } else {
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
    // Snap to the server position on the first snapshot, then ease toward it.
    if (this.localTargetX === null) {
      this.player.x = player.x;
      this.player.y = player.y;
    }
    this.localTargetX = player.x;
    this.localTargetY = player.y;

    this.player.setLabel(player.is_it ? "YOU • IT" : "YOU");
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

    remote.avatar.setLabel(
      `${player.is_it ? "IT • " : ""}${player.is_bot ? "BOT" : player.id.slice(0, 8)}`
    );
  }

  private ensureRemotePlayer(id: UUID): RemoteSprite {
    const existing = this.remotePlayers.get(id);
    if (existing) return existing;

    const x = WORLD_WIDTH / 2;
    const y = WORLD_HEIGHT / 2;
    const avatar = new KidAvatar(this, x, y, PLAYER_RADIUS, id.slice(0, 8), "12px");
    avatar.setRole("human");

    const remote: RemoteSprite = {
      avatar,
      targetX: x,
      targetY: y,
      lastMovedAt: -Infinity,
      snapshot: {
        id,
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
    if (!this.connected || this.tagCooldown > 0 || !this.localPlayerId) {
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
    if (!this.player.isTagging) this.audio?.playSfx("swing");
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
    const taggedLocal = targetId === this.localPlayerId;
    const taggingLocal = taggerId === this.localPlayerId;

    // Tagger swings their arm toward whoever they tagged. (If we already
    // started the swing optimistically on E, playTag() ignores the repeat.)
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
      const d = Phaser.Math.Distance.Between(this.player.x, this.player.y, target.x, target.y);
      this.audio?.playSfx("hit", 0.7 * (1 - d / 900));
    }
  }

  // --- Settings hooks -------------------------------------------------------

  setAudio(audio: GameAudio) {
    this.audio = audio;
  }

  setControlMode(mode: ControlMode) {
    this.controlMode = mode;
    if (mode !== "tap") this.clearTapTarget();
  }

  /** Pause game input while the Settings modal is open. */
  setUiOpen(open: boolean) {
    this.uiOpen = open;
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
      if (this.controlMode !== "tap" || this.uiOpen) return;
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      const kid = this.remoteAt(world.x, world.y);
      if (kid && this.distanceToPlayer(kid) < TAG_DISTANCE) {
        this.tryTag(kid); // tap a nearby kid: tag them
        return;
      }
      // Tap the ground (or a far-away kid): walk there; drag to steer.
      this.tapDragging = true;
      this.setTapTarget(kid ? kid.avatar.x : world.x, kid ? kid.avatar.y : world.y);
    });
    this.input.on(Phaser.Input.Events.POINTER_MOVE, (pointer: Phaser.Input.Pointer) => {
      if (!this.tapDragging || !pointer.isDown || this.controlMode !== "tap" || this.uiOpen) return;
      const world = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      this.setTapTarget(world.x, world.y);
    });
    const stopDrag = () => (this.tapDragging = false);
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
    const m = PLAYER_RADIUS + 2; // stay off the wall so we can actually arrive
    this.tapTarget = {
      x: Phaser.Math.Clamp(x, m, WORLD_WIDTH - m),
      y: Phaser.Math.Clamp(y, m, WORLD_HEIGHT - m),
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
    if (!this.tapTarget) return;
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
    createSchoolyard(this, WORLD_WIDTH, WORLD_HEIGHT);
  }

  private setStatus(status: string) {
    if (this.hudStatus) {
      this.hudStatus.textContent = status;
    }
  }

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
    events?: HTMLElement
  ) {
    this.hudEvents = events ?? null;
    this.hudStatus = status;
    this.hudEnergy = energy;
    this.hudPlayers = players;
    this.updateHud();
  }

  private updateHud() {
    if (!this.hudEnergy || !this.hudPlayers) return;

    const energy = Phaser.Math.Clamp(this.localEnergy, 0, 100);
    this.hudEnergy.style.transform = `scaleX(${energy / 100})`;
    this.hudPlayers.textContent =
      `${this.remotePlayers.size + 1} player${this.remotePlayers.size === 0 ? "" : "s"}`;
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

scene.setHudElements(status, energy, players, events);

// Settings (cog + modal) and procedural audio; all prefs live in localStorage.
const settings = loadSettings();
const audio = new GameAudio(settings);
audio.installGestureUnlock();
scene.setAudio(audio);
scene.setControlMode(settings.controlMode);

const controls = hud.querySelector(".controls") as HTMLElement;
controls.innerHTML = controlsHint(settings.controlMode);

new SettingsPanel(hud, settings, {
  onChange: s => {
    audio.apply(s);
    scene.setControlMode(s.controlMode);
    controls.innerHTML = controlsHint(s.controlMode);
  },
  onOpenChange: open => scene.setUiOpen(open),
  onSound: kind => audio.playSfx(kind === "preview" ? "join" : "click"),
});

window.addEventListener("resize", () => game.scale.resize(window.innerWidth, window.innerHeight));

game.events.on("step", () => {
  const socketConnected = status.textContent === "Connected";
  connection.className = `connection ${socketConnected ? "connected" : ""}`;
});