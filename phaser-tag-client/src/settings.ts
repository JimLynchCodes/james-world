/**
 * Settings: persisted preferences (localStorage) plus the cog button and
 * the Settings modal (vertical tabs: Controls, Sound). Plain DOM on top of
 * the Phaser canvas; styles live in style.css under "Settings".
 */

export type ControlMode = "keyboard" | "tap";
export type Mood = "happy" | "spooky" | "chillin";

export const MOODS: ReadonlyArray<{ value: Mood; label: string }> = [
  { value: "happy", label: "Happy" },
  { value: "spooky", label: "Spooky" },
  { value: "chillin", label: "Chillin" },
];

export interface Settings {
  controlMode: ControlMode;
  /** 0-100 */
  masterVolume: number;
  /** 0-100 */
  musicVolume: number;
  /** 0-100 */
  sfxVolume: number;
  mood: Mood;
}

export const STORAGE_KEY = "tag26.settings";

/** Touch-first devices start in Tap mode; everything else on the keyboard. */
function defaultSettings(): Settings {
  const coarse =
    typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  return {
    controlMode: coarse ? "tap" : "keyboard",
    masterVolume: 80,
    musicVolume: 60,
    sfxVolume: 80,
    mood: "happy",
  };
}

function volume(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.round(Math.min(100, Math.max(0, value)))
    : fallback;
}

/** Saved settings merged over the defaults; bad or missing fields fall back. */
export function loadSettings(): Settings {
  const defaults = defaultSettings();
  let saved: Partial<Record<keyof Settings, unknown>> = {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) saved = JSON.parse(raw) ?? {};
  } catch {
    // Storage disabled or corrupt JSON: just use the defaults.
  }
  return {
    controlMode:
      saved.controlMode === "tap" || saved.controlMode === "keyboard"
        ? saved.controlMode
        : defaults.controlMode,
    masterVolume: volume(saved.masterVolume, defaults.masterVolume),
    musicVolume: volume(saved.musicVolume, defaults.musicVolume),
    sfxVolume: volume(saved.sfxVolume, defaults.sfxVolume),
    mood: MOODS.some(m => m.value === saved.mood) ? (saved.mood as Mood) : defaults.mood,
  };
}

export function saveSettings(settings: Settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Private mode / quota: settings still apply for this session.
  }
}

/** Bottom-left controls hint for each mode (HTML). */
export function controlsHint(mode: ControlMode): string {
  return mode === "tap"
    ? "<strong>Tap / click</strong> the ground to walk there · " +
        "<strong>Tap a kid</strong> nearby to tag · <strong>SHIFT</strong> run"
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

type Tab = "controls" | "sound";

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
  private opened = false;
  private returnFocus: HTMLElement | null = null;

  constructor(
    hud: HTMLElement,
    initial: Settings,
    private readonly options: SettingsPanelOptions
  ) {
    this.values = { ...initial };

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
          </div>

          <section class="settings-pane" role="tabpanel" id="pane-controls"
                   aria-labelledby="tab-controls" data-pane="controls">
            <h3>Controls</h3>
            <div class="setting-row">
              <span class="setting-label" id="mode-label">Move with</span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-mode="keyboard">Keyboard</button>
                <button type="button" class="switch" role="switch" aria-labelledby="mode-label"
                        aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-mode="tap">Tap</button>
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

    this.q<HTMLButtonElement>(".switch").addEventListener("click", () => {
      this.options.onSound?.("click");
      this.set("controlMode", this.values.controlMode === "tap" ? "keyboard" : "tap");
    });
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option").forEach(option =>
      option.addEventListener("click", () => {
        this.options.onSound?.("click");
        this.set("controlMode", option.dataset.mode as ControlMode);
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
    if (this.values[key] === value) return;
    this.values[key] = value;
    saveSettings(this.values);
    this.render();
    this.options.onChange(this.values, key);
  }

  /** Reflect the current values in the controls. */
  private render() {
    const tap = this.values.controlMode === "tap";
    const sw = this.q<HTMLButtonElement>(".switch");
    sw.setAttribute("aria-checked", String(tap));
    sw.classList.toggle("on", tap);
    this.backdrop.querySelectorAll<HTMLButtonElement>(".mode-option").forEach(option => {
      const active = option.dataset.mode === this.values.controlMode;
      option.classList.toggle("active", active);
      option.setAttribute("aria-pressed", String(active));
    });
    this.q<HTMLElement>("[data-help]").textContent = tap
      ? "Tap or click anywhere on the ground and your kid walks there. " +
        "Tap a kid close by to tag them. Great for phones and tablets!"
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
  }
}
