/**
 * Title screen: "James Game" + Start, over the live schoolyard. Plain DOM
 * (same cartoony look as Settings). The game stays in spectator mode until
 * Start is pressed; see GameScene.startPlaying().
 */

export interface TitleScreenOptions {
  onStart(): void;
  /** Optional: play a click when Start is pressed. */
  onSound?(): void;
}

export class TitleScreen {
  readonly el: HTMLElement;
  private readonly startBtn: HTMLButtonElement;

  constructor(private readonly options: TitleScreenOptions) {
    this.el = document.createElement("div");
    this.el.className = "title-screen";
    this.el.innerHTML = `
      <div class="title-card" role="dialog" aria-labelledby="title-heading">
        <p class="title-kicker">Welcome to</p>
        <h1 id="title-heading" class="title-heading">James Game</h1>
        <p class="title-blurb">Run around, play tag, and have fun!</p>
        <button type="button" class="title-start">Start</button>
        <p class="title-hint">Pick a skin in Settings before you jump in</p>
      </div>`;
    document.body.appendChild(this.el);

    this.startBtn = this.el.querySelector(".title-start") as HTMLButtonElement;
    this.startBtn.addEventListener("click", () => {
      if (this.startBtn.disabled) return;
      this.options.onSound?.();
      this.startBtn.disabled = true;
      this.startBtn.textContent = "Starting…";
      this.options.onStart();
    });
  }

  /** Call once the player has joined and the local kid exists. */
  dismiss() {
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
