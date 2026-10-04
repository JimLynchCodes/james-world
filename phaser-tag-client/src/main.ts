import Phaser from "phaser";
import "./style.css";
import { GameSocket } from "./network";
import type { ServerMessage, PlayerSnapshot } from "./protocol";
import type { UUID } from "./types";

const WS_URL =
  import.meta.env.VITE_WS_URL ??
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:3000/ws`;

const ROOM_ID = import.meta.env.VITE_ROOM_ID ?? "default";

const WORLD_WIDTH = 5000;
const WORLD_HEIGHT = 5000;

const WALK_SPEED = 180;
const RUN_SPEED = 320;
const PLAYER_RADIUS = 18;

type RemoteSprite = {
  body: Phaser.GameObjects.Arc;
  label: Phaser.GameObjects.Text;
  targetX: number;
  targetY: number;
  snapshot: PlayerSnapshot;
};

class GameScene extends Phaser.Scene {
  private socket!: GameSocket;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private keys!: Record<string, Phaser.Input.Keyboard.Key>;
  private playerBody!: Phaser.GameObjects.Arc;
  private playerPointer!: Phaser.GameObjects.Arc;
  private playerLabel!: Phaser.GameObjects.Text;
  private playerFacingAngle = 0; // In radians

  private remotePlayers = new Map<UUID, RemoteSprite>();
  private localPlayerId: UUID | null = null;

  private sequence = 0;
  private inputTimer = 0;
  private tagCooldown = 0;

  private connected = false;
  private worldGraphics!: Phaser.GameObjects.Graphics;

  private hudStatus!: HTMLElement;
  private hudEnergy!: HTMLElement;
  private hudPlayers!: HTMLElement;

  constructor() {
    super("GameScene");
  }

  create() {
    this.createWorld();

    this.playerBody = this.add.circle(
      WORLD_WIDTH / 2,
      WORLD_HEIGHT / 2,
      PLAYER_RADIUS,
      0x38bdf8
    );
    this.playerBody.setDepth(20);

    // Facing direction dot attached to local player
    this.playerPointer = this.add.circle(
      WORLD_WIDTH / 2 + PLAYER_RADIUS - 2,
      WORLD_HEIGHT / 2,
      4,
      0xffffff
    );
    this.playerPointer.setDepth(21);

    this.playerLabel = this.add
      .text(WORLD_WIDTH / 2, WORLD_HEIGHT / 2 - 34, "YOU", {
        fontFamily: "system-ui, sans-serif",
        fontSize: "12px",
        color: "#ffffff",
        stroke: "#10131a",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(21);

    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    this.cameras.main.startFollow(this.playerBody, true, 0.12, 0.12);

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

    this.events.on("shutdown", () => this.socket.close());
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
      remote.body.x = Phaser.Math.Linear(remote.body.x, remote.targetX, 0.25);
      remote.body.y = Phaser.Math.Linear(remote.body.y, remote.targetY, 0.25);
      remote.label.setPosition(remote.body.x, remote.body.y - 34);
    }
  }

  private updateLocalMovement(dt: number) {
    let dx = 0;
    let dy = 0;

    if (this.cursors.left.isDown || this.keys.A.isDown) dx -= 1;
    if (this.cursors.right.isDown || this.keys.D.isDown) dx += 1;
    if (this.cursors.up.isDown || this.keys.W.isDown) dy -= 1;
    if (this.cursors.down.isDown || this.keys.S.isDown) dy += 1;

    const moving = dx !== 0 || dy !== 0;
    const running = this.keys.SHIFT.isDown;

    if (moving) {
      const length = Math.hypot(dx, dy);
      dx /= length;
      dy /= length;

      this.playerFacingAngle = Math.atan2(dy, dx);

      const speed = running ? RUN_SPEED : WALK_SPEED;

      this.playerBody.x = Phaser.Math.Clamp(
        this.playerBody.x + dx * speed * dt,
        PLAYER_RADIUS,
        WORLD_WIDTH - PLAYER_RADIUS
      );

      this.playerBody.y = Phaser.Math.Clamp(
        this.playerBody.y + dy * speed * dt,
        PLAYER_RADIUS,
        WORLD_HEIGHT - PLAYER_RADIUS
      );

      this.playerLabel.setPosition(
        this.playerBody.x,
        this.playerBody.y - 34
      );
    }

    // Update direction indicator relative to player angle
    const pointerOffset = PLAYER_RADIUS - 3;
    this.playerPointer.setPosition(
      this.playerBody.x + Math.cos(this.playerFacingAngle) * pointerOffset,
      this.playerBody.y + Math.sin(this.playerFacingAngle) * pointerOffset
    );

    // Update HUD every frame (drains/recharges energy smoothly while stationary)
    this.updateHud();
  }

  private sendMovement() {
    if (!this.connected) return;

    let dx = 0;
    let dy = 0;

    if (this.cursors.left.isDown || this.keys.A.isDown) dx -= 1;
    if (this.cursors.right.isDown || this.keys.D.isDown) dx += 1;
    if (this.cursors.up.isDown || this.keys.W.isDown) dy -= 1;
    if (this.cursors.down.isDown || this.keys.S.isDown) dy += 1;

    const running =
      this.keys.SHIFT.isDown && (dx !== 0 || dy !== 0);

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

      case "PlayerJoined":
        // If local ID is not set yet, the first PlayerJoined belongs to us
        if (!this.localPlayerId) {
          this.localPlayerId = message.data.player_id;
        }
        this.ensureRemotePlayer(message.data.player_id);
        break;

      case "PlayerLeft":
        this.removeRemotePlayer(message.data.player_id);
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
    if (!this.localPlayerId) {
      const configured = import.meta.env.VITE_PLAYER_ID as string | undefined;
      if (configured) {
        this.localPlayerId = configured;
      } else if (players.length === 1) {
        this.localPlayerId = players[0].id;
      }
    }

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
    // Reconcile prediction to server authority.
    this.playerBody.x = Phaser.Math.Linear(
      this.playerBody.x,
      player.x,
      0.35
    );
    this.playerBody.y = Phaser.Math.Linear(
      this.playerBody.y,
      player.y,
      0.35
    );

    this.playerLabel.setText(player.is_it ? "YOU • IT" : "YOU");

    if (player.is_it) {
      this.playerBody.setFillStyle(0xef4444);
    } else {
      this.playerBody.setFillStyle(0x38bdf8);
    }

    this.localEnergy = player.energy;
  }

  private applyRemoteSnapshot(player: PlayerSnapshot) {
    const remote = this.ensureRemotePlayer(player.id);

    remote.targetX = player.x;
    remote.targetY = player.y;
    remote.snapshot = player;

    remote.body.setFillStyle(
      player.is_it ? 0xef4444 : 0xf59e0b
    );

    remote.label.setText(
      `${player.is_it ? "IT • " : ""}${player.id.slice(0, 8)}`
    );
  }

  private ensureRemotePlayer(id: UUID): RemoteSprite {
    const existing = this.remotePlayers.get(id);
    if (existing) return existing;

    const body = this.add.circle(
      WORLD_WIDTH / 2,
      WORLD_HEIGHT / 2,
      PLAYER_RADIUS,
      0xf59e0b
    );

    body.setDepth(19);

    const label = this.add
      .text(body.x, body.y - 34, id.slice(0, 8), {
        fontFamily: "system-ui, sans-serif",
        fontSize: "11px",
        color: "#ffffff",
        stroke: "#10131a",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(20);

    const remote: RemoteSprite = {
      body,
      label,
      targetX: body.x,
      targetY: body.y,
      snapshot: {
        id,
        x: body.x,
        y: body.y,
        energy: 100,
        is_running: false,
        is_it: false,
      },
    };

    this.remotePlayers.set(id, remote);
    return remote;
  }

  private removeRemotePlayer(id: UUID) {
    const remote = this.remotePlayers.get(id);
    if (!remote) return;

    remote.body.destroy();
    remote.label.destroy();
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
        this.playerBody.x,
        this.playerBody.y,
        remote.body.x,
        remote.body.y
      );

      if (distance < closestDistance) {
        closest = remote;
        closestDistance = distance;
      }
    }

    if (!closest) return;

    this.socket.send({
      type: "TagPlayer",
      data: {
        target_id: closest.snapshot.id,
      },
    });

    this.tagCooldown = 500;
  }

  private flashTag(taggerId: UUID, targetId: UUID) {
    const taggedLocal = targetId === this.localPlayerId;
    const taggingLocal = taggerId === this.localPlayerId;

    if (taggedLocal || taggingLocal) {
      this.cameras.main.flash(180, 255, 255, 255);
    }
  }

  private createWorld() {
    this.worldGraphics = this.add.graphics();

    this.worldGraphics.fillStyle(0x171b24, 1);
    this.worldGraphics.fillRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT);

    this.worldGraphics.lineStyle(1, 0x242a36, 1);

    const grid = 100;
    for (let x = 0; x <= WORLD_WIDTH; x += grid) {
      this.worldGraphics.lineBetween(x, 0, x, WORLD_HEIGHT);
    }

    for (let y = 0; y <= WORLD_HEIGHT; y += grid) {
      this.worldGraphics.lineBetween(0, y, WORLD_WIDTH, y);
    }

    this.worldGraphics.lineStyle(4, 0x475569, 1);
    this.worldGraphics.strokeRect(
      0,
      0,
      WORLD_WIDTH,
      WORLD_HEIGHT
    );

    this.worldGraphics.setDepth(-10);
  }

  private setStatus(status: string) {
    if (this.hudStatus) {
      this.hudStatus.textContent = status;
    }
  }

  setHudElements(
    status: HTMLElement,
    energy: HTMLElement,
    players: HTMLElement
  ) {
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

scene.setHudElements(status, energy, players);

window.addEventListener("resize", () => game.scale.resize(window.innerWidth, window.innerHeight));

game.events.on("step", () => {
  const socketConnected = status.textContent === "Connected";
  connection.className = `connection ${socketConnected ? "connected" : ""}`;
});