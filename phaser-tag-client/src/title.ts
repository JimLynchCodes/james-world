/**
 * Title screen: "James World" + Start, over the live schoolyard. Plain DOM
 * (same cartoony look as Settings). The game stays in spectator mode until
 * Start is pressed; see GameScene.startPlaying().
 *
 * "Starting…" only appears when Start was pressed and the field is not ready
 * yet (socket / skin). If everything is ready, onStart enters instantly and
 * the overlay is dismissed without the waiting label.
 */
import { onLocaleChange, t } from "./i18n";

export interface TitleScreenOptions {
  /**
   * Called when Start is pressed. Return true when the field was entered
   * immediately (caller will dismiss); return false to keep the title up and
   * show "Starting…" until dismiss() is called later.
   */
  onStart(): boolean;
  /** Optional: play a click when Start is pressed. */
  onSound?(): void;
}

export class TitleScreen {
  readonly el: HTMLElement;
  private readonly startBtn: HTMLButtonElement;
  private waiting = false;

  constructor(private readonly options: TitleScreenOptions) {
    this.el = document.createElement("div");
    this.el.className = "title-screen";
    this.el.innerHTML = `
      <div class="title-card" role="dialog" aria-labelledby="title-heading">
        <p class="title-kicker">Welcome to</p>
        <h1 id="title-heading" class="title-heading">James World</h1>
        <p class="title-blurb">Run around, play tag, and have fun!</p>
        <button type="button" class="title-start">Start</button>
      </div>`;
    document.body.appendChild(this.el);

    this.startBtn = this.el.querySelector(".title-start") as HTMLButtonElement;
    this.startBtn.addEventListener("click", () => {
      if (this.startBtn.disabled) return;
      this.options.onSound?.();
      const entered = this.options.onStart();
      if (entered) return;
      this.waiting = true;
      this.startBtn.disabled = true;
      this.startBtn.textContent = t("title.starting");
    });
    this.refresh();
    onLocaleChange(() => this.refresh());
  }

  private refresh() {
    const set = (selector: string, key: "title.kicker" | "title.heading" | "title.blurb") => {
      const el = this.el.querySelector(selector);
      if (el) el.textContent = t(key);
    };
    set(".title-kicker", "title.kicker");
    set(".title-heading", "title.heading");
    set(".title-blurb", "title.blurb");
    if (this.waiting || this.startBtn.disabled) this.startBtn.textContent = t("title.starting");
    else this.startBtn.textContent = t("title.start");
  }

  /**
   * Call once the player is on the field. `instant` skips the fade so a ready
   * Start feels immediate.
   */
  dismiss(instant = false) {
    if (!document.body.contains(this.el)) return;
    if (instant) {
      this.el.remove();
      return;
    }
    this.el.classList.add("title-out");
    const done = () => this.el.remove();
    this.el.addEventListener("animationend", done, { once: true });
    // Fallback if the browser skips the animation.
    setTimeout(done, 500);
  }

  get visible() {
    return document.body.contains(this.el) && !this.el.classList.contains("title-out");
  }
}
