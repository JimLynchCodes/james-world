/**
 * Readable yard signs. A white board with a yellow panel and lettering on a
 * wooden post. Walk up to one and press tag to read it (see SignModal).
 */
import Phaser from "phaser";
import { propDepth } from "./schoolyard";

export type SignButton = { label: "ok"; action: "close" };
export type SignDef = {
  id: string;
  x: number;
  /** Post base (ground) Y. */
  y: number;
  /** Shown verbatim in every locale. */
  text: string;
  buttons: SignButton[];
};

export const SIGNS: SignDef[] = [
  {
    id: "playground",
    x: 3010,
    y: 3420,
    text: "If you seek to go on adventurous quests and spelunk,\n\n Then do the special code in the tree with wide trunk...",
    buttons: [{ label: "ok", action: "close" }],
  },
  {
    id: "track",
    x: 3766,
    y: 470,
    text: "The special code is:\n\n⚫️ ⚫️ ⚫️ ⬅️ ➡️ ⚫️",
    buttons: [{ label: "ok", action: "close" }],
  },
];

/** Feet within this many px of the post can read it. */
export const SIGN_READ_DISTANCE = 70;

/** Area kept clear of scattered trees around each sign. */
export const SIGN_FOOTPRINTS = SIGNS.map(s => ({ x: s.x - 40, y: s.y - 60, w: 80, h: 80 }));

const TEX = "yard-sign";
// World size ~46px tall (about 60% of James). Drawn at 4x, shown at 1/4.
const R = 4;
const W = 44;
const H = 50;
const FOOT = 3;

function signTexture(scene: Phaser.Scene) {
  if (scene.textures.exists(TEX)) return TEX;
  const tex = scene.textures.createCanvas(TEX, W * R, H * R)!;
  const ctx = tex.getContext();
  ctx.scale(R, R);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  const round = (x: number, y: number, w: number, h: number, r: number) => {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  };
  // ground shadow
  ctx.fillStyle = "rgba(0,0,0,.22)";
  ctx.beginPath();
  ctx.ellipse(W / 2, H - FOOT, 9, 2.5, 0, 0, Math.PI * 2);
  ctx.fill();
  // post
  const post = ctx.createLinearGradient(W / 2 - 3, 0, W / 2 + 3, 0);
  post.addColorStop(0, "#5e3a1e");
  post.addColorStop(0.45, "#8f5f35");
  post.addColorStop(1, "#5a361b");
  ctx.fillStyle = post;
  ctx.strokeStyle = "#2e1b0c";
  ctx.lineWidth = 1;
  round(W / 2 - 3, 18, 6, H - FOOT - 18, 1.2);
  ctx.fill();
  ctx.stroke();
  // plank board (two planks)
  const bx = 3, by = 4, bw = W - 6, bh = 22;
  const wood = ctx.createLinearGradient(0, by, 0, by + bh);
  wood.addColorStop(0, "#b57a43");
  wood.addColorStop(0.5, "#a36a37");
  wood.addColorStop(1, "#8e5a2d");
  ctx.fillStyle = wood;
  round(bx, by, bw, bh, 2.5);
  ctx.fill();
  // grain
  ctx.save();
  round(bx, by, bw, bh, 2.5);
  ctx.clip();
  ctx.strokeStyle = "rgba(70,40,16,.35)";
  ctx.lineWidth = 0.5;
  for (const gy of [7, 9.5, 13, 18, 21, 23.5]) {
    ctx.beginPath();
    ctx.moveTo(bx, by + gy);
    ctx.bezierCurveTo(bx + bw * 0.3, by + gy - 0.8, bx + bw * 0.6, by + gy + 0.9, bx + bw, by + gy - 0.3);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(70,40,16,.4)";
  ctx.beginPath();
  ctx.ellipse(bx + bw * 0.78, by + 16, 1.6, 0.8, 0, 0, Math.PI * 2);
  ctx.fill();
  // seam between planks
  ctx.strokeStyle = "#4a2c14";
  ctx.lineWidth = 0.8;
  ctx.beginPath();
  ctx.moveTo(bx, by + bh / 2);
  ctx.lineTo(bx + bw, by + bh / 2);
  ctx.stroke();
  ctx.restore();
  // dark edge
  ctx.strokeStyle = "#3a2210";
  ctx.lineWidth = 1.2;
  round(bx, by, bw, bh, 2.5);
  ctx.stroke();
  // nails
  ctx.fillStyle = "#2a2a2a";
  for (const [nx, ny] of [[bx + 2.6, by + 2.6], [bx + bw - 2.6, by + 2.6], [bx + 2.6, by + bh - 2.6], [bx + bw - 2.6, by + bh - 2.6]]) {
    ctx.beginPath();
    ctx.arc(nx, ny, 0.75, 0, Math.PI * 2);
    ctx.fill();
  }
  // scribbled "writing"
  ctx.strokeStyle = "#24140a";
  ctx.lineWidth = 0.8;
  const rows: [number, number, number][] = [[8, 9, 35], [8, 15, 30], [11, 21, 33]];
  for (const [x0, y0, x1] of rows) {
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    let x = x0;
    let i = 0;
    while (x < x1) {
      const step = 1.1 + ((i * 7) % 5) * 0.18;
      const up = i % 2 === 0 ? -1.5 - ((i * 3) % 4) * 0.25 : 0.9;
      ctx.quadraticCurveTo(x + step / 2, y0 + up, x + step, y0 + (i % 3 === 0 ? 0.3 : 0));
      x += step;
      if (i % 6 === 5 && x < x1 - 3) {
        x += 1.6; // word gap
        ctx.moveTo(x, y0);
      }
      i++;
    }
    ctx.stroke();
  }
  tex.refresh();
  return TEX;
}

export type PlacedSign = SignDef & { prompt: Phaser.GameObjects.Container };

/** Add the sign props plus a hidden bobbing prompt above each. */
export function createSigns(scene: Phaser.Scene): PlacedSign[] {
  const key = signTexture(scene);
  return SIGNS.map(def => {
    scene.add.image(def.x, def.y, key).setOrigin(0.5, (H - FOOT) / H).setScale(1 / R).setDepth(propDepth(def.y));
    const top = def.y - (H - FOOT);
    const bubble = scene.add.graphics();
    const label = scene.add
      .text(0, 0, "", { fontFamily: "sans-serif", fontSize: "26px", fontStyle: "bold", color: "#1b1b1b" })
      .setOrigin(0.5)
      .setScale(0.5)
      .setResolution(2);
    const prompt = scene.add.container(def.x, top - 14, [bubble, label]).setDepth(100000).setVisible(false);
    prompt.setData("bubble", bubble).setData("label", label);
    scene.tweens.add({ targets: prompt, y: top - 22, duration: 520, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
    return { ...def, prompt };
  });
}

/** Set the prompt text and redraw its pill. */
export function setPromptText(sign: PlacedSign, text: string) {
  const label = sign.prompt.getData("label") as Phaser.GameObjects.Text;
  if (label.text === text) return;
  label.setText(text);
  const g = sign.prompt.getData("bubble") as Phaser.GameObjects.Graphics;
  const w = label.displayWidth + 18;
  const h = label.displayHeight + 8;
  g.clear();
  g.fillStyle(0xffffff, 1);
  g.lineStyle(2, 0x1b1b1b, 1);
  g.fillRoundedRect(-w / 2, -h / 2, w, h, 8);
  g.strokeRoundedRect(-w / 2, -h / 2, w, h, 8);
  g.fillTriangle(-5, h / 2 - 1, 5, h / 2 - 1, 0, h / 2 + 6);
  g.lineBetween(-5, h / 2, 0, h / 2 + 6);
  g.lineBetween(5, h / 2, 0, h / 2 + 6);
}

/** DOM popup in the Settings modal style. */
export class SignModal {
  private readonly backdrop: HTMLElement;
  private readonly body: HTMLElement;
  private readonly actions: HTMLElement;
  private opened = false;

  constructor(
    parent: HTMLElement,
    private readonly hooks: { onOpenChange: (open: boolean) => void; label: (key: "ok" | "close") => string; onSound?: () => void }
  ) {
    this.backdrop = document.createElement("div");
    this.backdrop.className = "settings-backdrop sign-backdrop";
    this.backdrop.hidden = true;
    this.backdrop.innerHTML = `
      <div class="settings-modal sign-modal" role="dialog" aria-modal="true">
        <button type="button" class="settings-close sign-close"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg></button>
        <div class="settings-frame sign-frame">
          <p class="sign-text" dir="auto"></p>
          <div class="sign-actions"></div>
        </div>
      </div>`;
    // On <body>, not inside .hud (pointer-events: none), so the X and OK get clicks and taps.
    void parent;
    document.body.appendChild(this.backdrop);
    this.body = this.backdrop.querySelector(".sign-text") as HTMLElement;
    this.actions = this.backdrop.querySelector(".sign-actions") as HTMLElement;
    const modal = this.backdrop.querySelector(".sign-modal") as HTMLElement;
    for (const type of ["keydown", "keyup", "pointerdown", "pointerup", "touchstart", "touchend", "mousedown", "wheel"]) {
      modal.addEventListener(type, e => e.stopPropagation());
    }
    this.backdrop.addEventListener("click", e => {
      if (e.target === this.backdrop) this.close();
    });
    this.backdrop.querySelector(".sign-close")!.addEventListener("click", () => this.close());
    window.addEventListener("keydown", e => {
      if (this.opened && e.key === "Escape") {
        e.preventDefault();
        this.close();
      }
    });
  }

  get isOpen() {
    return this.opened;
  }

  open(sign: SignDef) {
    this.body.textContent = sign.text;
    this.actions.replaceChildren(
      ...sign.buttons.map(b => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "sign-button";
        btn.textContent = this.hooks.label(b.label);
        btn.addEventListener("click", () => {
          if (b.action === "close") this.close();
        });
        return btn;
      })
    );
    (this.backdrop.querySelector(".sign-close") as HTMLElement).setAttribute("aria-label", this.hooks.label("close"));
    this.backdrop.hidden = false;
    this.opened = true;
    this.hooks.onSound?.();
    this.hooks.onOpenChange(true);
    (this.actions.querySelector("button") as HTMLElement | null)?.focus();
  }

  close() {
    if (!this.opened) return;
    this.opened = false;
    this.backdrop.hidden = true;
    this.hooks.onOpenChange(false);
  }
}
