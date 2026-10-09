/**
 * Settings: persisted preferences (localStorage) plus the cog button and
 * the Settings modal (tabs: Controls, Sound, Skins). The header and tabs stay
 * put; the option panes scroll inside the rounded frame. Plain DOM on
 * top of the Phaser canvas; styles live in style.css under "Settings".
 */
import { DEFAULT_SKIN, SKINS, SKIN_IDS, type Skin } from "./skins";

export type ControlMode = "keyboard" | "mobile";
/**
 * Background music moods. "relaxed" is the procedural lo-fi track that used
 * to be called "chillin"; "chillin" is now a CC0 lo-fi recording
 * (public/audio/CREDITS.md). A value saved by an older build is kept as-is.
 */
export type Mood = "happy" | "spooky" | "relaxed" | "chillin";

export const MOODS: ReadonlyArray<{ value: Mood; label: string; blurb: string }> = [
  { value: "happy", label: "Happy", blurb: "Bouncy chiptune" },
  { value: "spooky", label: "Spooky", blurb: "Creepy bells and a heartbeat" },
  { value: "relaxed", label: "Relaxed", blurb: "Mellow lo-fi keys" },
  { value: "chillin", label: "Chillin", blurb: "Lo-fi hip hop loop" },
];

export interface Settings {
  controlMode: ControlMode;
  /**
   * Mobile mode: false = joystick bottom-left, Tag / Run bottom-right;
   * true = joystick bottom-right, Tag / Run bottom-left.
   */
  leftyJoystick: boolean;
  /** Mobile mode: false = Tag to the left of Run; true = Run left of Tag. */
  flipTagRun: boolean;
  /** 0-100 */
  masterVolume: number;
  /** 0-100 */
  musicVolume: number;
  /** 0-100 */
  sfxVolume: number;
  mood: Mood;
  /** Which outfit James wears (everyone else sees it too). */
  skin: Skin;
}

export const STORAGE_KEY = "tag26.settings";

/**
 * Is this a phone / tablet (touch-first) rather than a desktop or laptop?
 * Any one strong signal is enough: Client Hints `mobile`, a mobile UA,
 * iPadOS (desktop Safari UA + touch points), or a primary pointer that is
 * coarse with no hover. Touchscreen laptops (fine primary pointer that can
 * hover) stay on the keyboard.
 */
export function isTouchFirstDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { userAgentData?: { mobile?: boolean } };
  if (nav.userAgentData?.mobile === true) return true;
  const ua = nav.userAgent ?? "";
  const touchPoints = nav.maxTouchPoints ?? 0;
  if (/Android|iPhone|iPad|iPod|Mobile|Silk|Kindle|Opera Mini|IEMobile/i.test(ua)) return true;
  if (/Macintosh/.test(ua) && touchPoints > 1) return true; // iPadOS
  const media = (query: string) =>
    typeof matchMedia === "function" && matchMedia(query).matches;
  if (media("(pointer: coarse)") && media("(hover: none)")) return true;
  return touchPoints > 0 && media("(pointer: coarse)") && !media("(any-pointer: fine)");
}

/** Phones / tablets start in Mobile mode, desktops on the keyboard. */
function defaultSettings(): Settings {
  return {
    controlMode: isTouchFirstDevice() ? "mobile" : "keyboard",
    leftyJoystick: false,
    flipTagRun: false,
    masterVolume: 80,
    musicVolume: 60,
    sfxVolume: 80,
    mood: "happy",
    skin: DEFAULT_SKIN,
  };
}

function volume(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.round(Math.min(100, Math.max(0, value)))
    : fallback;
}

export interface LoadedSettings {
  settings: Settings;
  /** Keys the user has actually chosen (present and valid in storage). */
  saved: Set<keyof Settings>;
}

/**
 * Saved settings merged over the defaults. Missing, invalid or unknown
 * (e.g. from an older build) values fall back to the default and don't
 * count as saved, so e.g. the control mode keeps being auto-detected until
 * the user picks one.
 */
export function loadSettings(): LoadedSettings {
  const defaults = defaultSettings();
  let raw: Record<string, unknown> = {};
  try {
    const json = localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = json ? JSON.parse(json) : null;
    if (parsed && typeof parsed === "object") raw = parsed as Record<string, unknown>;
  } catch {
    // Storage disabled or corrupt JSON: just use the defaults.
  }

  const settings: Settings = { ...defaults };
  const saved = new Set<keyof Settings>();
  const take = <K extends keyof Settings>(key: K, value: Settings[K] | undefined) => {
    if (value === undefined) return;
    settings[key] = value;
    saved.add(key);
  };
  const oneOf = <T extends string>(value: unknown, options: readonly T[]) =>
    options.includes(value as T) ? (value as T) : undefined;
  const vol = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value) ? volume(value, 0) : undefined;

  // "tap" is what Mobile mode was called before the joystick existed.
  take("controlMode", oneOf(raw.controlMode === "tap" ? "mobile" : raw.controlMode, ["keyboard", "mobile"] as const));
  const bool = (value: unknown) => (typeof value === "boolean" ? value : undefined);
  // Old "Run button side: Left" put the buttons on the left: that's lefty now.
  take("leftyJoystick", bool(raw.leftyJoystick) ?? (raw.runSide === "left" ? true : undefined));
  take("flipTagRun", bool(raw.flipTagRun));
  take("masterVolume", vol(raw.masterVolume));
  take("musicVolume", vol(raw.musicVolume));
  take("sfxVolume", vol(raw.sfxVolume));
  take("mood", oneOf(raw.mood, MOODS.map(m => m.value)));
  take("skin", oneOf(raw.skin, SKIN_IDS));
  // Rewrite saves from older builds ("tap", runSide) in the new shape.
  if (raw.controlMode === "tap" || "runSide" in raw) saveSettings(settings, saved);
  return { settings, saved };
}

/** Persist only the settings the user has chosen (`keys`). */
export function saveSettings(settings: Settings, keys: Iterable<keyof Settings>) {
  const out: Partial<Settings> = {};
  for (const key of keys) (out as Record<string, unknown>)[key] = settings[key];
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(out));
  } catch {
    // Private mode / quota: settings still apply for this session.
  }
}

/** Bottom-left controls hint for each mode (HTML). */
export function controlsHint(mode: ControlMode): string {
  return mode === "mobile"
    ? "<strong>Tap</strong> the ground to walk or use the <strong>joystick</strong> · " +
        "<strong>TAG</strong> or tap a nearby player to tag · hold <strong>RUN</strong> to run"
    : "<strong>WASD / Arrow Keys</strong> move · <strong>SHIFT</strong> run · " +
        "<strong>SPACE</strong> tag";
}

export interface SettingsPanelOptions {
  /** A setting changed (already saved). */
  onChange(settings: Readonly<Settings>, key: keyof Settings): void;
  /** The modal opened or closed. */
  onOpenChange?(open: boolean): void;
  /** UI feedback sounds: a button/tab press, or a volume slider was let go. */
  onSound?(kind: "click" | "preview"): void;
}

type Tab = "controls" | "sound" | "skins";

/** On/off settings shown as switches in the Controls tab (Mobile only). */
const FLAGS = ["leftyJoystick", "flipTagRun"] as const;
type Flag = (typeof FLAGS)[number];

const SVG_NS = 'xmlns="http://www.w3.org/2000/svg"';

/** Chunky 8-tooth cog: tooth polygon + hole + a little highlight. */
function cogSvg(): string {
  const teeth = 8;
  const rTip = 27;
  const rRoot = 20;
  const pts: string[] = [];
  const polar = (r: number, a: number) =>
    `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
  for (let i = 0; i < teeth; i++) {
    const a = (i / teeth) * Math.PI * 2;
    const w = Math.PI / teeth;
    pts.push(polar(rRoot, a - w * 0.72), polar(rTip, a - w * 0.46));
    pts.push(polar(rTip, a + w * 0.46), polar(rRoot, a + w * 0.72));
  }
  return `
    <svg ${SVG_NS} viewBox="-32 -32 64 64" aria-hidden="true" focusable="false">
      <path class="cog-body" d="M${pts.join(" L")} Z"/>
      <path class="cog-shine" d="M -13 -8 A 15 15 0 0 1 4 -15"/>
      <circle class="cog-hole" r="8"/>
    </svg>`;
}

const ICONS = {
  controls: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" y="7" width="19" height="11" rx="5.5"/><path d="M7.5 10.5v4M5.5 12.5h4"/><circle cx="15.5" cy="11.5" r="1.1"/><circle cx="18" cy="14" r="1.1"/></svg>`,
  sound: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/></svg>`,
  skins: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 3.5 5 5.5 2.5 9.5l3 2 1.5-1.5V20.5h10V10l1.5 1.5 3-2L19 5.5l-3.5-2a3.5 3.5 0 0 1-7 0z"/></svg>`,
  close: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>`,
};

/** Little line icons in front of the Sound rows (same style as the tabs). */
const ROW_ICONS = {
  master: ICONS.sound,
  music: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M9 17.5V5.5l10-2v12"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="16.5" cy="15.5" r="2.5"/></svg>`,
  sfx: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/></svg>`,
  mood: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 14.5a4.5 4.5 0 0 0 8 0"/><path d="M9 9.5h.01M15 9.5h.01"/></svg>`,
};

const SLIDERS: ReadonlyArray<{ key: "masterVolume" | "musicVolume" | "sfxVolume"; label: string; icon: keyof typeof ROW_ICONS }> = [
  { key: "masterVolume", label: "Master volume", icon: "master" },
  { key: "musicVolume", label: "Background music", icon: "music" },
  { key: "sfxVolume", label: "Sound effects", icon: "sfx" },
];

export class SettingsPanel {
  readonly cog: HTMLButtonElement;
  private readonly backdrop: HTMLElement;
  private readonly modal: HTMLElement;
  private readonly values: Settings;
  private readonly chosen: Set<keyof Settings>;
  private opened = false;
  private returnFocus: HTMLElement | null = null;

  constructor(
    hud: HTMLElement,
    initial: Settings,
    saved: Iterable<keyof Settings>,
    private readonly options: SettingsPanelOptions
  ) {
    this.values = { ...initial };
    this.chosen = new Set(saved);

    this.cog = document.createElement("button");
    this.cog.type = "button";
    this.cog.className = "settings-cog";
    this.cog.setAttribute("aria-label", "Settings");
    this.cog.setAttribute("aria-haspopup", "dialog");
    this.cog.setAttribute("aria-expanded", "false");
    this.cog.title = "Settings";
    this.cog.innerHTML = cogSvg();
    this.cog.addEventListener("click", () => {
      this.options.onSound?.("click");
      this.toggle();
    });
    hud.appendChild(this.cog);

    this.backdrop = document.createElement("div");
    this.backdrop.className = "settings-backdrop";
    this.backdrop.hidden = true;
    this.backdrop.innerHTML = this.template();
    document.body.appendChild(this.backdrop);
    this.modal = this.backdrop.querySelector(".settings-modal") as HTMLElement;

    this.wire();
    this.selectTab("controls");
    this.render();
  }

  get settings(): Readonly<Settings> {
    return this.values;
  }

  get isOpen() {
    return this.opened;
  }

  open() {
    if (this.opened) return;
    this.opened = true;
    this.returnFocus = document.activeElement as HTMLElement | null;
    this.backdrop.hidden = false;
    this.cog.setAttribute("aria-expanded", "true");
    this.cog.classList.add("open");
    document.addEventListener("keydown", this.onDocumentKey, true);
    this.options.onOpenChange?.(true);
    this.q<HTMLElement>(".settings-tab[aria-selected='true']").focus();
    // Layout is ready on the next frame; that's when the fade can measure.
    requestAnimationFrame(() => this.updateScrollFade());
  }

  close() {
    if (!this.opened) return;
    this.opened = false;
    this.backdrop.hidden = true;
    this.cog.setAttribute("aria-expanded", "false");
    this.cog.classList.remove("open");
    document.removeEventListener("keydown", this.onDocumentKey, true);
    this.options.onOpenChange?.(false);
    // Hand focus back (normally the cog) so Space/Enter don't stay on a
    // hidden control, then blur so game keys aren't captured by the button.
    (this.returnFocus ?? this.cog).focus?.();
    (document.activeElement as HTMLElement | null)?.blur?.();
  }

  toggle() {
    if (this.opened) this.close();
    else this.open();
  }

  private template() {
    const sliders = SLIDERS.map(
      ({ key, label, icon }) => `
        <div class="setting-row slider-row">
          <label class="setting-label" for="setting-${key}">${ROW_ICONS[icon]}<span>${label}</span></label>
          <div class="slider-wrap">
            <input id="setting-${key}" class="settings-slider" type="range"
                   min="0" max="100" step="1" data-key="${key}">
            <output class="slider-value" for="setting-${key}" data-value="${key}"></output>
          </div>
        </div>`
    ).join("");
    const moods = MOODS.map(m => `<option value="${m.value}">${m.label}</option>`).join("");
    // A card per skin with a live preview: the kid facing the camera,
    // straight from the skin's spritesheet (breathing idle; walking when picked).
    const skinCards = SKIN_IDS.map(id => {
      const s = SKINS[id];
      const vars = [
        `--sheet:url('${s.url}')`,
        `--fw:${s.frameWidth}`,
        `--fh:${s.frameHeight}`,
        `--base:${s.baselineY}`,
      ].join(";");
      return `
        <button type="button" class="skin-card" role="radio" aria-checked="false" data-skin="${id}">
          <span class="skin-stage"><span class="skin-preview" style="${vars}"></span></span>
          <span class="skin-name">${s.label}</span>
          <span class="skin-note">${s.note}</span>
        </button>`;
    }).join("");

    return `
      <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <button type="button" class="settings-close" aria-label="Close settings">${ICONS.close}</button>
        <div class="settings-frame">
        <h2 id="settings-title" class="settings-title">Settings</h2>
        <div class="settings-body">
          <div class="settings-tabs" role="tablist" aria-orientation="vertical">
            <button type="button" class="settings-tab" role="tab" id="tab-controls"
                    data-tab="controls" aria-controls="pane-controls">${ICONS.controls}<span>Controls</span></button>
            <button type="button" class="settings-tab" role="tab" id="tab-sound"
                    data-tab="sound" aria-controls="pane-sound">${ICONS.sound}<span>Sound</span></button>
            <button type="button" class="settings-tab" role="tab" id="tab-skins"
                    data-tab="skins" aria-controls="pane-skins">${ICONS.skins}<span>Skins</span></button>
          </div>
          <div class="settings-main">
          <div class="settings-scroll">

          <section class="settings-pane" role="tabpanel" id="pane-controls"
                   aria-labelledby="tab-controls" data-pane="controls">
            <h3>Controls</h3>
            <div class="controls-layout">
            <div class="controls-options">
            <div class="setting-row">
              <span class="setting-label" id="mode-label">Move with</span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-mode="keyboard">Keyboard</button>
                <button type="button" class="switch" role="switch" aria-labelledby="mode-label"
                        data-toggle="mode" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-mode="mobile">Mobile</button>
              </div>
            </div>
            <div class="setting-row" data-mobile-only>
              <span class="setting-label" id="lefty-label">Lefty Joystick</span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-flag="leftyJoystick" data-value="false">Left</button>
                <button type="button" class="switch side-switch" role="switch" aria-labelledby="lefty-label"
                        data-toggle="leftyJoystick" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-flag="leftyJoystick" data-value="true">Right</button>
              </div>
            </div>
            <div class="setting-row" data-mobile-only>
              <span class="setting-label" id="flip-label">Flip Tag / Run</span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-flag="flipTagRun" data-value="false">Off</button>
                <button type="button" class="switch" role="switch" aria-labelledby="flip-label"
                        data-toggle="flipTagRun" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-flag="flipTagRun" data-value="true">On</button>
              </div>
            </div>
            <p class="setting-help controls-note" data-keyboard-only>Playing on a phone or tablet?
              Pick <strong>Mobile</strong> for a joystick and big TAG and RUN buttons.</p>
            </div>
            <aside class="howto" aria-label="How to play">
              <h4 class="howto-title">How to play</h4>
              <ul class="howto-list" data-howto="keyboard">
                <li class="howto-row">
                  <span class="howto-keys move-keys">
                    <span class="key-cluster"><kbd class="key k-up">W</kbd><kbd class="key k-left">A</kbd><kbd class="key k-down">S</kbd><kbd class="key k-right">D</kbd></span>
                    <span class="howto-or">or</span>
                    <span class="key-cluster"><kbd class="key k-up" aria-label="Up arrow">&#9650;</kbd><kbd class="key k-left" aria-label="Left arrow">&#9664;</kbd><kbd class="key k-down" aria-label="Down arrow">&#9660;</kbd><kbd class="key k-right" aria-label="Right arrow">&#9654;</kbd></span>
                  </span>
                  <span class="howto-what">Move</span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-wide">Shift</kbd></span>
                  <span class="howto-what">Run (hold)</span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-space">Space</kbd></span>
                  <span class="howto-what">Tag!</span>
                </li>
              </ul>
              <ul class="howto-list" data-howto="mobile">
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip-stick" aria-hidden="true"><span></span></span></span>
                  <span class="howto-what">Joystick, or tap the ground, to walk</span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-tag">TAG</span></span>
                  <span class="howto-what">Tag, or tap a nearby player</span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-run">RUN</span></span>
                  <span class="howto-what">Hold to run</span>
                </li>
              </ul>
              <p class="setting-help" data-help></p>
            </aside>
            </div>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-sound"
                   aria-labelledby="tab-sound" data-pane="sound">
            <h3>Sound</h3>
            ${sliders}
            <div class="setting-row mood-row">
              <label class="setting-label" for="setting-mood">${ROW_ICONS.mood}<span>Mood</span></label>
              <div class="mood-pick">
                <div class="select-wrap">
                  <select id="setting-mood" class="settings-select">${moods}</select>
                </div>
                <span class="mood-blurb" data-mood-blurb></span>
              </div>
            </div>
            <p class="setting-help">The mood picks the background music.</p>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-skins"
                   aria-labelledby="tab-skins" data-pane="skins">
            <h3>Skins</h3>
            <div class="skin-cards" role="radiogroup" aria-label="Skin">${skinCards}</div>
            <p class="setting-help">Everyone in the game sees James in the skin you pick.</p>
          </section>
          </div>
          <div class="settings-fade" hidden></div>
          </div>
        </div>
        </div>
      </div>`;
  }

  private q<T extends Element>(selector: string): T {
    return this.backdrop.querySelector(selector) as T;
  }

  private wire() {
    // Backdrop click (outside the panel) closes.
    this.backdrop.addEventListener("pointerdown", event => {
      if (event.target === this.backdrop) this.close();
    });
    // A drag on the dimmed page (or the frame chrome) must not scroll the
    // document or rubber-band into the game. The options scroller is exempt.
    const scroller = this.q<HTMLElement>(".settings-scroll");
    this.backdrop.addEventListener("touchmove", event => {
      const target = event.target;
      if (target instanceof Node && scroller.contains(target)) return;
      if (event.cancelable) event.preventDefault();
    }, { passive: false });
    scroller.addEventListener("scroll", () => this.updateScrollFade(), { passive: true });
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => this.updateScrollFade()).observe(scroller);
    }
    this.q<HTMLButtonElement>(".settings-close").addEventListener("click", () => {
      this.options.onSound?.("click");
      this.close();
    });

    // Keys typed inside the modal never reach the game (Phaser listens on window).
    for (const type of ["keydown", "keyup"] as const) {
      this.modal.addEventListener(type, event => event.stopPropagation());
    }

    const tabs = [...this.backdrop.querySelectorAll<HTMLButtonElement>(".settings-tab")];
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.selectTab(tab.dataset.tab as Tab);
      });
      tab.addEventListener("keydown", event => {
        const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        const next = tabs[(i + step + tabs.length) % tabs.length];
        this.selectTab(next.dataset.tab as Tab);
        next.focus();
      });
    });

    this.q<HTMLButtonElement>('.switch[data-toggle="mode"]').addEventListener("click", () => {
      this.options.onSound?.("click");
      this.set("controlMode", this.values.controlMode === "mobile" ? "keyboard" : "mobile");
    });
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option[data-mode]").forEach(option =>
      option.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set("controlMode", option.dataset.mode as ControlMode);
      })
    );
    for (const flag of FLAGS) {
      this.q<HTMLButtonElement>(`.switch[data-toggle="${flag}"]`).addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set(flag, !this.values[flag]);
      });
    }
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option[data-flag]").forEach(option =>
      option.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set(option.dataset.flag as Flag, option.dataset.value === "true");
      })
    );

    this.backdrop.querySelectorAll<HTMLInputElement>(".settings-slider").forEach(slider => {
      const key = slider.dataset.key as (typeof SLIDERS)[number]["key"];
      slider.addEventListener("input", () => this.set(key, Number(slider.value)));
      // Let go of the master / effects slider: play a blip at the new level.
      if (key !== "musicVolume") {
        slider.addEventListener("change", () => this.options.onSound?.("preview"));
      }
    });

    const mood = this.q<HTMLSelectElement>(".settings-select");
    mood.addEventListener("change", () => this.set("mood", mood.value as Mood));

    const cards = [...this.backdrop.querySelectorAll<HTMLButtonElement>(".skin-card")];
    cards.forEach((card, i) => {
      card.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set("skin", card.dataset.skin as Skin);
      });
      // Radio group keys: arrows move (and pick) between the cards.
      card.addEventListener("keydown", event => {
        const step =
          event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
          : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        const next = cards[(i + step + cards.length) % cards.length];
        this.set("skin", next.dataset.skin as Skin);
        next.focus();
      });
    });
  }

  private onDocumentKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.close();
    } else if (event.key === "Tab") {
      this.trapFocus(event);
    }
  };

  /** Keep Tab / Shift+Tab cycling inside the dialog while it's open. */
  private trapFocus(event: KeyboardEvent) {
    const focusable = [
      ...this.modal.querySelectorAll<HTMLElement>("button, input, select"),
    ].filter(el => el.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !this.modal.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !this.modal.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  private selectTab(tab: Tab) {
    this.backdrop.querySelectorAll<HTMLButtonElement>(".settings-tab").forEach(button => {
      const selected = button.dataset.tab === tab;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    this.backdrop.querySelectorAll<HTMLElement>(".settings-pane").forEach(pane => {
      pane.hidden = pane.dataset.pane !== tab;
    });
    const scroller = this.q<HTMLElement>(".settings-scroll");
    scroller.scrollTop = 0;
    this.updateScrollFade();
  }

  /** Show a fade along the bottom edge while more options sit below. */
  private updateScrollFade() {
    const scroller = this.q<HTMLElement>(".settings-scroll");
    const fade = this.q<HTMLElement>(".settings-fade");
    const more = scroller.scrollTop + scroller.clientHeight < scroller.scrollHeight - 4;
    fade.hidden = !more;
  }

  private set<K extends keyof Settings>(key: K, value: Settings[K]) {
    // Picking a value is an explicit choice even if it equals the default
    // (e.g. confirming the auto-detected control mode), so always save.
    const changed = this.values[key] !== value;
    this.values[key] = value;
    this.chosen.add(key);
    saveSettings(this.values, this.chosen);
    if (!changed) return;
    this.render();
    this.options.onChange(this.values, key);
  }

  /** Reflect the current values in the controls. */
  private render() {
    const mobile = this.values.controlMode === "mobile";
    const modeSwitch = this.q<HTMLButtonElement>('.switch[data-toggle="mode"]');
    modeSwitch.setAttribute("aria-checked", String(mobile));
    modeSwitch.classList.toggle("on", mobile);
    for (const flag of FLAGS) {
      const sw = this.q<HTMLButtonElement>(`.switch[data-toggle="${flag}"]`);
      sw.setAttribute("aria-checked", String(this.values[flag]));
      sw.classList.toggle("on", this.values[flag]);
    }
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option").forEach(option => {
      const active = option.dataset.mode
        ? option.dataset.mode === this.values.controlMode
        : String(this.values[option.dataset.flag as Flag]) === option.dataset.value;
      option.classList.toggle("active", active);
      option.setAttribute("aria-pressed", String(active));
    });
    this.backdrop.querySelectorAll<HTMLElement>("[data-mobile-only]").forEach(row => {
      row.hidden = !mobile;
    });
    this.backdrop.querySelectorAll<HTMLElement>("[data-keyboard-only]").forEach(row => {
      row.hidden = mobile;
    });
    this.backdrop.querySelectorAll<HTMLElement>("[data-howto]").forEach(list => {
      list.hidden = list.dataset.howto !== this.values.controlMode;
    });
    this.q<HTMLElement>("[data-help]").textContent = mobile
      ? "Drag on the ground to steer. Mix and match! Great for phones and tablets."
      : "Tag someone nearby to make them it.";

    for (const { key } of SLIDERS) {
      const value = this.values[key];
      const slider = this.q<HTMLInputElement>(`.settings-slider[data-key="${key}"]`);
      if (Number(slider.value) !== value) slider.value = String(value);
      slider.style.setProperty("--fill", `${value}%`);
      this.q<HTMLOutputElement>(`[data-value="${key}"]`).textContent = String(value);
    }
    const mood = this.q<HTMLSelectElement>(".settings-select");
    if (mood.value !== this.values.mood) mood.value = this.values.mood;
    this.q<HTMLElement>("[data-mood-blurb]").textContent =
      MOODS.find(m => m.value === this.values.mood)?.blurb ?? "";

    this.backdrop.querySelectorAll<HTMLButtonElement>(".skin-card").forEach(card => {
      const picked = card.dataset.skin === this.values.skin;
      card.setAttribute("aria-checked", String(picked));
      card.classList.toggle("picked", picked);
      card.tabIndex = picked ? 0 : -1;
    });
    this.updateScrollFade();
  }
}
