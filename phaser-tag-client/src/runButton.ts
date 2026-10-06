/**
 * Tap mode's hold-to-run button, fixed to a bottom corner of the screen.
 *
 * Held while at least one pointer is down on it, so it works with
 * multi-touch: one thumb holds RUN while the other taps / drags on the
 * game to steer. Its touches are kept away from Phaser (preventDefault on
 * the touch / pointer events, which Phaser skips), so pressing it never
 * sets a tap destination.
 */

import type { RunSide } from "./settings";

const ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
    <path class="run-lines" d="M4 17h9M2 25h10M5 33h8"/>
    <path class="run-bolt" d="M28 4 14 27h10l-4 17 16-25H26z"/>
  </svg>`;

export class RunButton {
  readonly el: HTMLButtonElement;
  private readonly pointers = new Set<number>();

  constructor(parent: HTMLElement, private readonly onChange: (held: boolean) => void) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "run-button";
    el.setAttribute("aria-label", "Run (hold)");
    el.setAttribute("aria-pressed", "false");
    el.innerHTML = `${ICON}<span class="run-label">RUN</span>`;
    el.hidden = true;
    this.el = el;

    el.addEventListener("pointerdown", event => {
      // Also stops the compatibility mousedown that Phaser would see.
      event.preventDefault();
      this.pointers.add(event.pointerId);
      this.update();
    });
    const release = (event: PointerEvent) => {
      if (this.pointers.delete(event.pointerId)) this.update();
    };
    el.addEventListener("pointerup", release);
    el.addEventListener("pointercancel", release);
    el.addEventListener("pointerleave", release);

    // No scrolling / zooming / long-press menus, and Phaser ignores touches
    // whose default was prevented (so they can't become tap targets).
    const swallow = (event: Event) => {
      if (event.cancelable) event.preventDefault();
    };
    for (const type of ["touchstart", "touchmove", "touchend", "touchcancel"]) {
      el.addEventListener(type, swallow, { passive: false });
    }
    el.addEventListener("contextmenu", swallow);

    window.addEventListener("blur", () => this.releaseAll());
    parent.appendChild(el);
  }

  get held() {
    return this.pointers.size > 0;
  }

  setVisible(visible: boolean) {
    this.el.hidden = !visible;
    if (!visible) this.releaseAll();
  }

  setSide(side: RunSide) {
    this.el.classList.toggle("left", side === "left");
    this.el.classList.toggle("right", side === "right");
  }

  private releaseAll() {
    if (this.pointers.size === 0) return;
    this.pointers.clear();
    this.update();
  }

  private update() {
    const held = this.held;
    this.el.classList.toggle("held", held);
    this.el.setAttribute("aria-pressed", String(held));
    this.onChange(held);
  }
}
