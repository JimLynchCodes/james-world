/**
 * Mobile mode's on-screen controls: a virtual joystick in one bottom corner
 * and the Tag + Run buttons side by side in the other.
 *
 *   default:        [joystick] ............ [TAG][RUN]
 *   lefty joystick: [TAG][RUN] ............ [joystick]
 *   flip tag / run: RUN and TAG swap places within their pair
 *
 * Everything is multi-touch: each control tracks its own pointer ids, so one
 * thumb can steer with the joystick while the other holds RUN or taps TAG.
 * Their touches never reach Phaser (preventDefault on touch events, which
 * Phaser skips; the DOM sits above the canvas anyway), so pressing them never
 * sets a tap-to-move destination.
 */

import { RunButton } from "./runButton";

/** Fraction of the base radius that counts as "not pushed" (no movement). */
const DEAD_ZONE = 0.2;

const TAG_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
    <path class="tag-burst" d="M24 3l4.5 9.5L39 9l-3.5 10L46 24l-10.5 5L39 39l-10.5-3.5L24 45l-4.5-9.5L9 39l3.5-10.5L2 24l10.5-5L9 9l10.5 3.5z"/>
    <path class="tag-hand" d="M17 30V18.5a2.5 2.5 0 0 1 5 0V24v-8.5a2.5 2.5 0 0 1 5 0V24v-6a2.5 2.5 0 0 1 5 0v10c0 6-3.5 9-8.5 9-3.5 0-5.5-1.5-7.5-4.5l-3.5-5.5a2.3 2.3 0 0 1 3.9-2.4z"/>
  </svg>`;

/** Stop the browser scrolling / zooming / long-press menus on a control. */
function swallowTouches(el: HTMLElement) {
  const swallow = (event: Event) => {
    if (event.cancelable) event.preventDefault();
  };
  for (const type of ["touchstart", "touchmove", "touchend", "touchcancel"]) {
    el.addEventListener(type, swallow, { passive: false });
  }
  el.addEventListener("contextmenu", swallow);
}

/** Analog stick: drag the thumb, get a direction (dx, dy in -1..1). */
export class Joystick {
  readonly el: HTMLElement;
  private readonly thumb: HTMLElement;
  private pointerId: number | null = null;
  private centre = { x: 0, y: 0 };
  private radius = 1;
  private vector = { x: 0, y: 0 };

  constructor(parent: HTMLElement, private readonly onChange: (dx: number, dy: number) => void) {
    const el = document.createElement("div");
    el.className = "joystick";
    el.setAttribute("role", "application");
    el.setAttribute("aria-label", "Joystick: drag to move");
    el.innerHTML = `<div class="joystick-base"><div class="joystick-thumb"></div></div>`;
    el.hidden = true;
    this.el = el;
    this.thumb = el.querySelector(".joystick-thumb") as HTMLElement;

    el.addEventListener("pointerdown", event => {
      event.preventDefault();
      if (this.pointerId !== null) return; // one thumb steers at a time
      this.pointerId = event.pointerId;
      el.setPointerCapture?.(event.pointerId);
      const base = (el.querySelector(".joystick-base") as HTMLElement).getBoundingClientRect();
      this.centre = { x: base.left + base.width / 2, y: base.top + base.height / 2 };
      // The thumb can travel to the base's rim (minus a bit of its own size).
      this.radius = Math.max(1, base.width / 2 - this.thumb.offsetWidth * 0.2);
      el.classList.add("active");
      this.move(event);
    });
    el.addEventListener("pointermove", event => {
      if (event.pointerId === this.pointerId) this.move(event);
    });
    const release = (event: PointerEvent) => {
      if (event.pointerId === this.pointerId) this.reset();
    };
    el.addEventListener("pointerup", release);
    el.addEventListener("pointercancel", release);
    el.addEventListener("lostpointercapture", release);
    swallowTouches(el);
    window.addEventListener("blur", () => this.reset());
    parent.appendChild(el);
  }

  get value(): Readonly<{ x: number; y: number }> {
    return this.vector;
  }

  get active() {
    return this.pointerId !== null;
  }

  setVisible(visible: boolean) {
    this.el.hidden = !visible;
    if (!visible) this.reset();
  }

  private move(event: PointerEvent) {
    let ox = event.clientX - this.centre.x;
    let oy = event.clientY - this.centre.y;
    const d = Math.hypot(ox, oy);
    // Clamp the thumb to the base.
    if (d > this.radius) {
      ox = (ox / d) * this.radius;
      oy = (oy / d) * this.radius;
    }
    this.thumb.style.transform = `translate(calc(-50% + ${ox}px), calc(-50% + ${oy}px))`;
    // Dead zone, then rescale so movement ramps from 0 at its edge.
    const m = Math.min(1, d / this.radius);
    if (m < DEAD_ZONE) {
      this.set(0, 0);
      return;
    }
    const strength = (m - DEAD_ZONE) / (1 - DEAD_ZONE);
    this.set((ox / Math.hypot(ox, oy)) * strength, (oy / Math.hypot(ox, oy)) * strength);
  }

  private set(x: number, y: number) {
    if (x === this.vector.x && y === this.vector.y) return;
    this.vector = { x, y };
    this.onChange(x, y);
  }

  private reset() {
    if (this.pointerId !== null) {
      try { this.el.releasePointerCapture?.(this.pointerId); } catch { /* already released */ }
    }
    this.pointerId = null;
    this.el.classList.remove("active");
    this.thumb.style.transform = "";
    this.set(0, 0);
  }
}

/** Press to tag (same as SPACE on the keyboard). */
export class TagButton {
  readonly el: HTMLButtonElement;

  constructor(parent: HTMLElement, onPress: () => void) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "tag-button";
    el.setAttribute("aria-label", "Tag");
    el.innerHTML = `${TAG_ICON}<span class="tag-label">TAG</span>`;
    this.el = el;
    const pointers = new Set<number>();
    const update = () => el.classList.toggle("held", pointers.size > 0);
    el.addEventListener("pointerdown", event => {
      event.preventDefault();
      pointers.add(event.pointerId);
      update();
      onPress();
    });
    const release = (event: PointerEvent) => {
      if (pointers.delete(event.pointerId)) update();
    };
    el.addEventListener("pointerup", release);
    el.addEventListener("pointercancel", release);
    el.addEventListener("pointerleave", release);
    // Keyboard activation (Enter / Space on a focused button) still tags.
    el.addEventListener("click", event => {
      if (event.detail === 0) onPress();
    });
    swallowTouches(el);
    parent.appendChild(el);
  }
}

export interface MobileControlsOptions {
  onJoystick(dx: number, dy: number): void;
  onRunHeld(held: boolean): void;
  onTag(): void;
}

/** Joystick + Tag/Run pair, laid out from the Mobile settings. */
export class MobileControls {
  readonly joystick: Joystick;
  readonly run: RunButton;
  readonly tag: TagButton;
  /** Holds Tag and Run side by side in their corner. */
  readonly pad: HTMLElement;

  constructor(parent: HTMLElement, options: MobileControlsOptions) {
    this.joystick = new Joystick(parent, options.onJoystick);
    this.pad = document.createElement("div");
    this.pad.className = "action-pad";
    this.pad.hidden = true;
    parent.appendChild(this.pad);
    this.tag = new TagButton(this.pad, options.onTag);
    this.run = new RunButton(this.pad, options.onRunHeld);
    this.run.setVisible(true);
  }

  setVisible(visible: boolean) {
    this.joystick.setVisible(visible);
    this.pad.hidden = !visible;
    if (!visible) this.run.release();
  }

  /** lefty: joystick on the right, buttons on the left. flip: Run left of Tag. */
  setLayout(lefty: boolean, flip: boolean) {
    this.joystick.el.classList.toggle("right", lefty);
    this.pad.classList.toggle("left", lefty);
    this.pad.classList.toggle("flip", flip);
  }

  /** Elements that turn see-through when James walks under them. */
  get overlays(): HTMLElement[] {
    return [this.joystick.el, this.tag.el, this.run.el];
  }
}
