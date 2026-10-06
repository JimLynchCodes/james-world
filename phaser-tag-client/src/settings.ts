/**
 * Settings: persisted preferences (localStorage) plus the cog button and
 * the Settings modal (vertical tabs: Controls, Sound, Skins). Plain DOM on
 * top of the Phaser canvas; styles live in style.css under "Settings".
 */
import { DEFAULT_SKIN, SKINS, SKIN_IDS, type Skin } from "./skins";

export type ControlMode = "keyboard" | "tap";
export type RunSide = "left" | "right";
/**
 * Background music moods. "relaxed" is the procedural lo-fi track that used
 * to be called "chillin"; "chillin" is now a CC0 lo-fi recording
 * (public/audio/CREDITS.md). A value saved by an older build is kept as-is.
 */
export type Mood = "happy" | "spooky" | "relaxed" | "chillin";

export const MOODS: ReadonlyArray<{ value: Mood; label: string }> = [
  { value: "happy", label: "Happy" },
  { value: "spooky", label: "Spooky" },
  { value: "relaxed", label: "Relaxed" },
  { value: "chillin", label: "Chillin" },
];

export interface Settings {
  controlMode: ControlMode;
  /** Tap mode: which bottom corner the Run button sits in. */
  runSide: RunSide;
  /** 0-100 */
  masterVolume: number;
  /** 0-100 */
  musicVolume: number;
  /** 0-100 */
  sfxVolume: number;
  mood: Mood;
  /** Which outfit your kid wears (everyone else sees it too). */
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

/** Phones / tablets start in Tap mode, desktops on the keyboard. */
function defaultSettings(): Settings {
  return {
    controlMode: isTouchFirstDevice() ? "tap" : "keyboard",
    runSide: "right",
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

  take("controlMode", oneOf(raw.controlMode, ["keyboard", "tap"] as const));
  take("runSide", oneOf(raw.runSide, ["left", "right"] as const));
  take("masterVolume", vol(raw.masterVolume));
  take("musicVolume", vol(raw.musicVolume));
  take("sfxVolume", vol(raw.sfxVolume));
  take("mood", oneOf(raw.mood, MOODS.map(m => m.value)));
  take("skin", oneOf(raw.skin, SKIN_IDS));
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
  return mode === "tap"
    ? "<strong>Tap</strong> the ground to walk · <strong>Tap a kid</strong> nearby to tag · " +
        "hold <strong>RUN</strong> to run"
    : "<strong>WASD / Arrow Keys</strong> move · <strong>SHIFT</strong> run · " +
        "<strong>E</strong> tag";
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

const SLIDERS: ReadonlyArray<{ key: "masterVolume" | "musicVolume" | "sfxVolume"; label: string }> = [
  { key: "masterVolume", label: "Master volume" },
  { key: "musicVolume", label: "Background music" },
  { key: "sfxVolume", label: "Sound effects" },
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
      ({ key, label }) => `
        <div class="setting-row slider-row">
          <label class="setting-label" for="setting-${key}">${label}</label>
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
          ${id === DEFAULT_SKIN ? '<span class="skin-note">Default</span>' : '<span class="skin-note">Squeaky shoes</span>'}
        </button>`;
    }).join("");

    return `
      <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <button type="button" class="settings-close" aria-label="Close settings">${ICONS.close}</button>
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

          <section class="settings-pane" role="tabpanel" id="pane-controls"
                   aria-labelledby="tab-controls" data-pane="controls">
            <h3>Controls</h3>
            <div class="setting-row">
              <span class="setting-label" id="mode-label">Move with</span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-mode="keyboard">Keyboard</button>
                <button type="button" class="switch" role="switch" aria-labelledby="mode-label"
                        data-toggle="mode" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-mode="tap">Tap</button>
              </div>
            </div>
            <div class="setting-row" data-tap-only>
              <span class="setting-label" id="side-label">Run button side</span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-side="left">Left</button>
                <button type="button" class="switch side-switch" role="switch" aria-labelledby="side-label"
                        data-toggle="side" aria-checked="true"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-side="right">Right</button>
              </div>
            </div>
            <p class="setting-help" data-help></p>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-sound"
                   aria-labelledby="tab-sound" data-pane="sound">
            <h3>Sound</h3>
            ${sliders}
            <div class="setting-row">
              <label class="setting-label" for="setting-mood">Mood</label>
              <div class="select-wrap">
                <select id="setting-mood" class="settings-select">${moods}</select>
              </div>
            </div>
            <p class="setting-help">The mood picks the background music.</p>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-skins"
                   aria-labelledby="tab-skins" data-pane="skins">
            <h3>Skins</h3>
            <div class="skin-cards" role="radiogroup" aria-label="Skin">${skinCards}</div>
            <p class="setting-help">Everyone in the game sees your kid in the skin you pick.</p>
          </section>
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
      this.set("controlMode", this.values.controlMode === "tap" ? "keyboard" : "tap");
    });
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option[data-mode]").forEach(option =>
      option.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set("controlMode", option.dataset.mode as ControlMode);
      })
    );
    this.q<HTMLButtonElement>('.switch[data-toggle="side"]').addEventListener("click", () => {
      this.options.onSound?.("click");
      this.set("runSide", this.values.runSide === "right" ? "left" : "right");
    });
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option[data-side]").forEach(option =>
      option.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set("runSide", option.dataset.side as RunSide);
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
    const tap = this.values.controlMode === "tap";
    const right = this.values.runSide === "right";
    const modeSwitch = this.q<HTMLButtonElement>('.switch[data-toggle="mode"]');
    modeSwitch.setAttribute("aria-checked", String(tap));
    modeSwitch.classList.toggle("on", tap);
    const sideSwitch = this.q<HTMLButtonElement>('.switch[data-toggle="side"]');
    sideSwitch.setAttribute("aria-checked", String(right));
    sideSwitch.classList.toggle("on", right);
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option").forEach(option => {
      const active = option.dataset.mode
        ? option.dataset.mode === this.values.controlMode
        : option.dataset.side === this.values.runSide;
      option.classList.toggle("active", active);
      option.setAttribute("aria-pressed", String(active));
    });
    this.q<HTMLElement>("[data-tap-only]").hidden = !tap;
    this.q<HTMLElement>("[data-help]").textContent = tap
      ? "Tap anywhere on the ground and your kid walks there (drag to steer). " +
        "Hold the RUN button to run, and tap a kid close by to tag them. " +
        "Great for phones and tablets!"
      : "Move with WASD or the arrow keys, hold SHIFT to run, press E to tag.";

    for (const { key } of SLIDERS) {
      const value = this.values[key];
      const slider = this.q<HTMLInputElement>(`.settings-slider[data-key="${key}"]`);
      if (Number(slider.value) !== value) slider.value = String(value);
      slider.style.setProperty("--fill", `${value}%`);
      this.q<HTMLOutputElement>(`[data-value="${key}"]`).textContent = String(value);
    }
    const mood = this.q<HTMLSelectElement>(".settings-select");
    if (mood.value !== this.values.mood) mood.value = this.values.mood;

    this.backdrop.querySelectorAll<HTMLButtonElement>(".skin-card").forEach(card => {
      const picked = card.dataset.skin === this.values.skin;
      card.setAttribute("aria-checked", String(picked));
      card.classList.toggle("picked", picked);
      card.tabIndex = picked ? 0 : -1;
    });
  }
}
