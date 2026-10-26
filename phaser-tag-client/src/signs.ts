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
    text: "If you want to go on adventurous quests and spelunk,\n\nthen say the special code in the tree with the wide trunk",
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
export const SIGN_READ_DISTANCE = 90;

/** Area kept clear of scattered trees around each sign. */
export const SIGN_FOOTPRINTS = SIGNS.map(s => ({ x: s.x - 70, y: s.y - 150, w: 140, h: 180 }));

const TEX = "yard-sign";
// Drawn at 2x and shown at half scale for smooth edges.
const W = 150;
const H = 170;

function signTexture(scene: Phaser.Scene) {
  if (scene.textures.exists(TEX)) return TEX;
  const tex = scene.textures.createCanvas(TEX, W * 2, H * 2)!;
  const ctx = tex.getContext();
  ctx.scale(2, 2);
  const round = (x: number, y: number, w: number, h: number, r: number) => {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  };
  // ground shadow
  ctx.fillStyle = "rgba(0,0,0,.22)";
  ctx.beginPath();
  ctx.ellipse(W / 2, H - 7, 26, 6, 0, 0, Math.PI * 2);
  ctx.fill();
  // post
  ctx.fillStyle = "#8a5a32";
  ctx.strokeStyle = "#3d2614";
  ctx.lineWidth = 2.5;
  round(W / 2 - 7, 70, 14, H - 78, 3);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#a8743f";
  ctx.fillRect(W / 2 - 4, 74, 3, H - 86);
  // board
  ctx.fillStyle = "#3a3a3a";
  round(8, 12, W - 16, 74, 14);
  ctx.fill();
  ctx.fillStyle = "#fbfaf3";
  round(6, 8, W - 12, 74, 14);
  ctx.fill();
  ctx.strokeStyle = "#2b2b2b";
  ctx.lineWidth = 3;
  ctx.stroke();
  // yellow panel
  ctx.fillStyle = "#f7d43c";
  round(16, 18, W - 32, 54, 8);
  ctx.fill();
  ctx.strokeStyle = "#c79b12";
  ctx.lineWidth = 1.5;
  ctx.stroke();
  // lettering (decorative lines)
  ctx.fillStyle = "#1b1b1b";
  ctx.font = "bold 16px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("READ ME", W / 2, 34);
  ctx.fillRect(30, 50, W - 60, 3);
  ctx.fillRect(40, 59, W - 80, 3);
  tex.refresh();
  return TEX;
}

export type PlacedSign = SignDef & { prompt: Phaser.GameObjects.Container };

/** Add the sign props plus a hidden bobbing prompt above each. */
export function createSigns(scene: Phaser.Scene): PlacedSign[] {
  const key = signTexture(scene);
  return SIGNS.map(def => {
    scene.add.image(def.x, def.y, key).setOrigin(0.5, (H - 7) / H).setScale(0.5).setDepth(propDepth(def.y));
    const top = def.y - (H - 7);
    const bubble = scene.add.graphics();
    const label = scene.add
      .text(0, 0, "", { fontFamily: "sans-serif", fontSize: "26px", fontStyle: "bold", color: "#1b1b1b" })
      .setOrigin(0.5)
      .setScale(0.5)
      .setResolution(2);
    const prompt = scene.add.container(def.x, top - 18, [bubble, label]).setDepth(100000).setVisible(false);
    prompt.setData("bubble", bubble).setData("label", label);
    scene.tweens.add({ targets: prompt, y: top - 26, duration: 520, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
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
    parent.appendChild(this.backdrop);
    this.body = this.backdrop.querySelector(".sign-text") as HTMLElement;
    this.actions = this.backdrop.querySelector(".sign-actions") as HTMLElement;
    const modal = this.backdrop.querySelector(".sign-modal") as HTMLElement;
    for (const type of ["keydown", "keyup", "pointerdown", "wheel"]) {
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
