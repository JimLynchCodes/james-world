import Phaser from "phaser";
import "./style.css";
import { GameSocket } from "./network";
import type { ServerMessage, PlayerSnapshot } from "./protocol";
import type { UUID } from "./types";
import { KidAvatar, createKidAnimations, preloadKid } from "./kid";
import { createSchoolyard } from "./schoolyard";

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
    const dt = delta / 1000;

    this.updateLocalMovement(dt);

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

  private updateLocalMovement(_dt: number) {
    // The server is authoritative: we only send inputs (see sendMovement)
    // and ease toward the position it reports in each Snapshot.
    // Animation state comes from the keys held *now*, never from the eased
    // position (which keeps drifting toward the server for a few frames).
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

  /** Current movement keys: dx/dy in {-1, 0, 1}; running = SHIFT while moving. */
  private readInput() {
    let dx = 0;
    let dy = 0;
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
        this.logEvent(`Player ${message.data.player_id.slice(0, 8)} joined`);
        this.updateHud();
        break;

      case "PlayerLeft":
        this.removeRemotePlayer(message.data.player_id);
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
    const avatar = new KidAvatar(this, x, y, PLAYER_RADIUS, id.slice(0, 8), "11px");
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

  private tryTagNearest() {
    if (!this.connected || this.tagCooldown > 0 || !this.localPlayerId) {
      return;
    }

    const TAG_DISTANCE = 70;
    let closest: RemoteSprite | null = null;
    let closestDistance = TAG_DISTANCE;

    for (const remote of this.remotePlayers.values()) {
      const distance = Phaser.Math.Distance.Between(
        this.player.x,
        this.player.y,
        remote.avatar.x,
        remote.avatar.y
      );

      if (distance < closestDistance) {
        closest = remote;
        closestDistance = distance;
      }
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
    }
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

  <div class="controls">
    <strong>WASD / Arrow Keys</strong> move ·
    <strong>SHIFT</strong> run ·
    <strong>E</strong> tag
  </div>
`;

document.body.appendChild(hud);

const status = document.querySelector("#status") as HTMLElement;
const energy = document.querySelector("#energy") as HTMLElement;
const players = document.querySelector("#players") as HTMLElement;
const connection = document.querySelector("#connection") as HTMLElement;

const events = document.querySelector("#events") as HTMLElement;

scene.setHudElements(status, energy, players, events);

window.addEventListener("resize", () => game.scale.resize(window.innerWidth, window.innerHeight));

game.events.on("step", () => {
  const socketConnected = status.textContent === "Connected";
  connection.className = `connection ${socketConnected ? "connected" : ""}`;
});