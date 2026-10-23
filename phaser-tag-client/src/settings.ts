/**
 * Settings: persisted preferences (localStorage) plus the cog button and
 * the Settings modal (tabs: Controls, Sound, View, Skins, Credits). The header and tabs stay
 * put; the option panes scroll inside the rounded frame. Plain DOM on
 * top of the Phaser canvas; styles live in style.css under "Settings".
 */
import { onLocaleChange, t, type MessageKey } from "./i18n";
import { DEFAULT_SKIN, SKINS, SKIN_IDS, type Skin } from "./skins";
import { clampLevel, zoomTrackPercent } from "./zoom";

export type ControlMode = "keyboard" | "mobile";
/**
 * Background music moods. "relaxed" is the procedural lo-fi track that used
 * to be called "chillin"; "chillin" is now a CC0 lo-fi recording
 * (public/audio/CREDITS.md). A value saved by an older build is kept as-is.
 */
export type Mood = "happy" | "spooky" | "relaxed" | "chillin";

export const MOODS: ReadonlyArray<{ value: Mood }> = [
  { value: "happy" },
  { value: "spooky" },
  { value: "relaxed" },
  { value: "chillin" },
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
  /**
   * Camera zoom. 0 is the middle of the slider and the normal view.
   * Negative zooms out, positive zooms in. Range -100..100 (about 0.5x..2x).
   */
  zoom: number;
  /**
   * Mobile mode: hide the joystick and the Tag / Run buttons.
   * Play is tap-to-walk, double-tap-to-run, and tap-a-player-to-tag.
   */
  hideButtons: boolean;
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
    zoom: 0,
    hideButtons: false,
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
  take("zoom", typeof raw.zoom === "number" && Number.isFinite(raw.zoom) ? clampLevel(raw.zoom) : undefined);
  take("hideButtons", bool(raw.hideButtons));
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

/** Bottom-left controls hint for the current mode (HTML). */
export function controlsHint(settings: Pick<Settings, "controlMode" | "hideButtons">): string {
  if (settings.controlMode === "keyboard") return t("hint.keyboard");
  if (settings.hideButtons) return t("hint.mobileTouch");
  return t("hint.mobile");
}

export interface SettingsPanelOptions {
  /** A setting changed (already saved). */
  onChange(settings: Readonly<Settings>, key: keyof Settings): void;
  /** The modal opened or closed. */
  onOpenChange?(open: boolean): void;
  /** UI feedback sounds: a button/tab press, or a volume slider was let go. */
  onSound?(kind: "click" | "preview"): void;
}

type Tab = "controls" | "sound" | "view" | "skins" | "credits";

/** Portrait on the Credits tab. Square source, framed in CSS (not stretched). */
const JAMES_PORTRAIT = `${import.meta.env.BASE_URL}assets/james.webp`;

/** URLs stay in every language. The sentences around them are translated. */
const CREDIT_COPY = {
  linkedinUrl: "https://linkedin.com/in/jimlynchcodes",
  linkedinLabel: "linkedin.com/in/jimlynchcodes",
  githubUrl: "https://github.com/JimLynchCodes/james-world",
  githubLabel: "github.com/JimLynchCodes/james-world",
} as const;

/**
 * Visible link label. Breaks only after a slash, and the last segment stays
 * on the same line as the external-link icon.
 */
function creditUrlRow(label: string, icon: string): string {
  const parts = label.split("/");
  const tail = parts.pop() ?? label;
  const head = parts.map(part => `${part}/<wbr>`).join("");
  return `<span class="credit-url-row" dir="ltr"><span class="credit-url">${head}</span><span class="credit-url-tail"><span class="credit-url">${tail}</span><span class="credit-ext">${icon}</span></span></span>`;
}

/** Filled marks, drawn in the same chunky badges as the rest of the panel. */
const CREDIT_ICONS = {
  linkedin: `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12zM7.12 20.45H3.56V9h3.56v11.45z"/></svg>`,
  github: `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12.02c0 4.42 2.87 8.18 6.84 9.5.5.09.68-.22.68-.48 0-.24-.01-.87-.01-1.7-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.95 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.03A9.56 9.56 0 0 1 12 6.84c.85 0 1.71.11 2.51.34 1.91-1.3 2.75-1.03 2.75-1.03.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.85-2.34 4.7-4.57 4.94.36.31.68.92.68 1.86 0 1.34-.01 2.42-.01 2.75 0 .26.18.58.69.48A10.02 10.02 0 0 0 22 12.02C22 6.48 17.52 2 12 2z"/></svg>`,
  external: `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M14 5h5v5"/><path d="M13 11l6-6"/><path d="M18 13.5V18a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4.5"/></svg>`,
};

/** On/off settings shown as switches in the Controls tab (Mobile only). */
const FLAGS = ["leftyJoystick", "flipTagRun", "hideButtons"] as const;
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
  view: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.2"/><path d="M15.2 15.2 20.5 20.5"/></svg>`,
  skins: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 3.5 5 5.5 2.5 9.5l3 2 1.5-1.5V20.5h10V10l1.5 1.5 3-2L19 5.5l-3.5-2a3.5 3.5 0 0 1-7 0z"/></svg>`,
  credits: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.2"/><path d="M5.2 19.6c.7-3.4 3.1-5.1 6.8-5.1s6.1 1.7 6.8 5.1"/></svg>`,
  close: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>`,
};

/** Little line icons in front of the Sound rows (same style as the tabs). */
const ROW_ICONS = {
  master: ICONS.sound,
  music: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M9 17.5V5.5l10-2v12"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="16.5" cy="15.5" r="2.5"/></svg>`,
  sfx: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/></svg>`,
  mood: `<svg ${SVG_NS} viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 14.5a4.5 4.5 0 0 0 8 0"/><path d="M9 9.5h.01M15 9.5h.01"/></svg>`,
};

const SLIDERS: ReadonlyArray<{
  key: "masterVolume" | "musicVolume" | "sfxVolume";
  labelKey: MessageKey;
  icon: keyof typeof ROW_ICONS;
}> = [
  { key: "masterVolume", labelKey: "settings.sound.master", icon: "master" },
  { key: "musicVolume", labelKey: "settings.sound.music", icon: "music" },
  { key: "sfxVolume", labelKey: "settings.sound.sfx", icon: "sfx" },
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
    this.cog.setAttribute("aria-haspopup", "dialog");
    this.cog.setAttribute("aria-expanded", "false");
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
    this.localize();
    onLocaleChange(() => this.localize());
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
      ({ key, labelKey, icon }) => `
        <div class="setting-row slider-row">
          <label class="setting-label" for="setting-${key}">${ROW_ICONS[icon]}<span data-i18n="${labelKey}"></span></label>
          <div class="slider-wrap">
            <input id="setting-${key}" class="settings-slider" type="range"
                   min="0" max="100" step="1" data-key="${key}">
            <output class="slider-value" for="setting-${key}" data-value="${key}"></output>
          </div>
        </div>`
    ).join("");
    const moods = MOODS.map(m => `<option value="${m.value}" data-i18n="mood.${m.value}"></option>`).join("");
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
          <span class="skin-name" data-i18n="skin.${id}"></span>
          <span class="skin-note" data-i18n="skin.${id}.note"></span>
        </button>`;
    }).join("");

    return `
      <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <button type="button" class="settings-close" data-i18n-aria="settings.close">${ICONS.close}</button>
        <div class="settings-frame">
        <h2 id="settings-title" class="settings-title" data-i18n="settings.title"></h2>
        <div class="settings-body">
          <div class="settings-tabs" role="tablist" aria-orientation="vertical">
            <button type="button" class="settings-tab" role="tab" id="tab-controls"
                    data-tab="controls" aria-controls="pane-controls">${ICONS.controls}<span data-i18n="settings.tab.controls"></span></button>
            <button type="button" class="settings-tab" role="tab" id="tab-sound"
                    data-tab="sound" aria-controls="pane-sound">${ICONS.sound}<span data-i18n="settings.tab.sound"></span></button>
            <button type="button" class="settings-tab" role="tab" id="tab-view"
                    data-tab="view" aria-controls="pane-view">${ICONS.view}<span data-i18n="settings.tab.view"></span></button>
            <button type="button" class="settings-tab" role="tab" id="tab-skins"
                    data-tab="skins" aria-controls="pane-skins">${ICONS.skins}<span data-i18n="settings.tab.skins"></span></button>
            <button type="button" class="settings-tab" role="tab" id="tab-credits"
                    data-tab="credits" aria-controls="pane-credits">${ICONS.credits}<span data-i18n="settings.tab.credits"></span></button>
          </div>
          <div class="settings-main">
          <div class="settings-scroll">

          <section class="settings-pane" role="tabpanel" id="pane-controls"
                   aria-labelledby="tab-controls" data-pane="controls">
            <h3 data-i18n="settings.controls.heading"></h3>
            <div class="controls-layout">
            <div class="controls-options">
            <div class="setting-row">
              <span class="setting-label" id="mode-label" data-i18n="settings.controls.moveWith"></span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-mode="keyboard" data-i18n="settings.controls.keyboard"></button>
                <button type="button" class="switch" role="switch" aria-labelledby="mode-label"
                        data-toggle="mode" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-mode="mobile" data-i18n="settings.controls.mobile"></button>
              </div>
            </div>
            <div class="setting-row" data-mobile-only>
              <span class="setting-label" id="hide-buttons-label" data-i18n="settings.controls.hideButtons"></span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-flag="hideButtons" data-value="false" data-i18n="settings.controls.off"></button>
                <button type="button" class="switch" role="switch" aria-labelledby="hide-buttons-label"
                        data-toggle="hideButtons" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-flag="hideButtons" data-value="true" data-i18n="settings.controls.on"></button>
              </div>
            </div>
            <div class="setting-row" data-mobile-only>
              <span class="setting-label" id="lefty-label" data-i18n="settings.controls.flipJoystick"></span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-flag="leftyJoystick" data-value="false" data-i18n="settings.controls.off"></button>
                <button type="button" class="switch side-switch" role="switch" aria-labelledby="lefty-label"
                        data-toggle="leftyJoystick" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-flag="leftyJoystick" data-value="true" data-i18n="settings.controls.on"></button>
              </div>
            </div>
            <div class="setting-row" data-mobile-only>
              <span class="setting-label" id="flip-label" data-i18n="settings.controls.flipTagRun"></span>
              <div class="mode-switch">
                <button type="button" class="mode-option" data-flag="flipTagRun" data-value="false" data-i18n="settings.controls.off"></button>
                <button type="button" class="switch" role="switch" aria-labelledby="flip-label"
                        data-toggle="flipTagRun" aria-checked="false"><span class="switch-knob"></span></button>
                <button type="button" class="mode-option" data-flag="flipTagRun" data-value="true" data-i18n="settings.controls.on"></button>
              </div>
            </div>
            <p class="setting-help controls-note" data-keyboard-only data-i18n-html="settings.controls.phoneHint"></p>
            </div>
            <aside class="howto" data-i18n-aria="howto.aria">
              <h4 class="howto-title" data-i18n="howto.title"></h4>
              <ul class="howto-list" data-howto="keyboard">
                <li class="howto-row">
                  <span class="howto-keys move-keys">
                    <span class="key-cluster"><kbd class="key k-up">W</kbd><kbd class="key k-left">A</kbd><kbd class="key k-down">S</kbd><kbd class="key k-right">D</kbd></span>
                    <span class="howto-or" data-i18n="howto.or"></span>
                    <span class="key-cluster"><kbd class="key k-up" data-i18n-aria="howto.up">&#9650;</kbd><kbd class="key k-left" data-i18n-aria="howto.left">&#9664;</kbd><kbd class="key k-down" data-i18n-aria="howto.down">&#9660;</kbd><kbd class="key k-right" data-i18n-aria="howto.right">&#9654;</kbd></span>
                  </span>
                  <span class="howto-what" data-i18n="howto.move"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-wide" data-i18n="howto.shift"></kbd></span>
                  <span class="howto-what" data-i18n="howto.runHold"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-space" data-i18n="howto.space"></kbd><span class="howto-or" data-i18n="howto.or"></span><kbd class="key">T</kbd></span>
                  <span class="howto-what" data-i18n="howto.tag"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-wide">Alt</kbd><span class="howto-plus">+</span><kbd class="key">W</kbd><span class="howto-or" data-i18n="howto.or"></span><kbd class="key" aria-hidden="true">&#9650;</kbd></span>
                  <span class="howto-what" data-i18n="howto.zoomIn"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-wide">Alt</kbd><span class="howto-plus">+</span><kbd class="key">S</kbd><span class="howto-or" data-i18n="howto.or"></span><kbd class="key" aria-hidden="true">&#9660;</kbd></span>
                  <span class="howto-what" data-i18n="howto.zoomOut"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><kbd class="key key-wide">Alt</kbd><span class="howto-plus">+</span><kbd class="key key-wheel" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="7.5" y="2.5" width="9" height="19" rx="4.5"/><path d="M12 2.8v5.2"/><path d="M10.3 6.4 12 8.3l1.7-1.9"/></svg></kbd></span>
                  <span class="howto-what" data-i18n="howto.wheel"></span>
                </li>
              </ul>
              <ul class="howto-list" data-howto="mobile">
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip-stick" aria-hidden="true"><span></span></span></span>
                  <span class="howto-what" data-i18n="howto.joyWalk"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-tag" data-i18n="mobile.tag"></span></span>
                  <span class="howto-what" data-i18n="howto.tagTap"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-run" data-i18n="mobile.run"></span></span>
                  <span class="howto-what" data-i18n="howto.holdRun"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-gesture chip-pinch" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M9 7 6.5 12 9 17M15 7l2.5 5L15 17"/></svg></span></span>
                  <span class="howto-what" data-i18n="howto.pinch"></span>
                </li>
              </ul>
              <ul class="howto-list" data-howto="touch">
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-gesture" aria-hidden="true"><span class="g-dot"></span></span></span>
                  <span class="howto-what" data-i18n="howto.tapWalk"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-gesture" aria-hidden="true"><span class="g-dot"></span><span class="g-dot"></span></span></span>
                  <span class="howto-what" data-i18n="howto.doubleRun"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-gesture" aria-hidden="true"><span class="g-person"></span></span></span>
                  <span class="howto-what" data-i18n="howto.tapPlayer"></span>
                </li>
                <li class="howto-row">
                  <span class="howto-keys"><span class="chip chip-gesture chip-pinch" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M9 7 6.5 12 9 17M15 7l2.5 5L15 17"/></svg></span></span>
                  <span class="howto-what" data-i18n="howto.pinch"></span>
                </li>
              </ul>
              <p class="setting-help" data-help></p>
            </aside>
            </div>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-sound"
                   aria-labelledby="tab-sound" data-pane="sound">
            <h3 data-i18n="settings.sound.heading"></h3>
            ${sliders}
            <div class="setting-row mood-row">
              <label class="setting-label" for="setting-mood">${ROW_ICONS.mood}<span data-i18n="settings.sound.mood"></span></label>
              <div class="mood-pick">
                <div class="select-wrap">
                  <select id="setting-mood" class="settings-select">${moods}</select>
                </div>
                <span class="mood-blurb" data-mood-blurb></span>
              </div>
            </div>
            <p class="setting-help" data-i18n="settings.sound.moodHelp"></p>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-view"
                   aria-labelledby="tab-view" data-pane="view">
            <h3 data-i18n="settings.view.heading"></h3>
            <div class="setting-row slider-row">
              <label class="setting-label" for="setting-zoom">${ICONS.view}<span data-i18n="settings.view.zoom"></span></label>
              <div class="slider-wrap zoom-wrap">
                <span class="zoom-cap" data-i18n="settings.view.out"></span>
                <input id="setting-zoom" class="settings-slider zoom-slider" type="range"
                       min="-100" max="100" step="1" value="0" data-key="zoom">
                <span class="zoom-cap" data-i18n="settings.view.in"></span>
                <output class="slider-value" for="setting-zoom" data-value="zoom"></output>
              </div>
            </div>
            <p class="setting-help" data-i18n="settings.view.help"></p>
            <p class="setting-help" data-i18n="settings.view.input"></p>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-skins"
                   aria-labelledby="tab-skins" data-pane="skins">
            <h3 data-i18n="settings.skins.heading"></h3>
            <p class="setting-help" data-i18n="settings.skins.help"></p>
            <div class="skin-cards" role="radiogroup" data-i18n-aria="settings.skins.aria">${skinCards}</div>
          </section>

          <section class="settings-pane" role="tabpanel" id="pane-credits"
                   aria-labelledby="tab-credits" data-pane="credits">
            <h3 data-i18n="settings.credits.heading"></h3>
            <div class="credit-cards">
              <article class="credit-card credit-bio">
                <span class="credit-photo-ring">
                  <img class="credit-photo" src="${JAMES_PORTRAIT}" alt="" width="256" height="256" draggable="false">
                </span>
                <p class="credit-copy" data-i18n="credits.bio"></p>
              </article>
              <a class="credit-card credit-link" data-credit="linkedin" draggable="false"
                 href="${CREDIT_COPY.linkedinUrl}" target="_blank" rel="noopener noreferrer">
                <span class="credit-badge credit-badge-li" aria-hidden="true">${CREDIT_ICONS.linkedin}</span>
                <span class="credit-link-text">
                  <span class="credit-lead" data-i18n="credits.linkedinLead"></span>
                  ${creditUrlRow(CREDIT_COPY.linkedinLabel, CREDIT_ICONS.external)}
                </span>
                <span class="credit-sr" data-i18n="credits.newTab"></span>
              </a>
              <a class="credit-card credit-link" data-credit="github" draggable="false"
                 href="${CREDIT_COPY.githubUrl}" target="_blank" rel="noopener noreferrer">
                <span class="credit-badge credit-badge-gh" aria-hidden="true">${CREDIT_ICONS.github}</span>
                <span class="credit-link-text">
                  <span class="credit-lead" data-i18n="credits.githubLead"></span>
                  ${creditUrlRow(CREDIT_COPY.githubLabel, CREDIT_ICONS.external)}
                </span>
                <span class="credit-sr" data-i18n="credits.newTab"></span>
              </a>
            </div>
          </section>
          </div>
          <div class="settings-fade" hidden></div>
          </div>
        </div>
        </div>
      </div>`;
  }

  /** Fill every labelled string from the current locale. Keeps the open tab. */
  private localize() {
    const text = (key: string | undefined) => (key ? t(key as MessageKey) : "");
    this.cog.setAttribute("aria-label", t("settings.aria"));
    this.cog.title = t("settings.aria");
    this.backdrop.querySelectorAll<HTMLElement>("[data-i18n]").forEach(el => {
      el.textContent = text(el.dataset.i18n);
    });
    this.backdrop.querySelectorAll<HTMLElement>("[data-i18n-html]").forEach(el => {
      el.innerHTML = text(el.dataset.i18nHtml);
    });
    this.backdrop.querySelectorAll<HTMLElement>("[data-i18n-aria]").forEach(el => {
      el.setAttribute("aria-label", text(el.dataset.i18nAria));
    });
    this.backdrop.querySelector(".credit-photo")?.setAttribute("alt", t("credits.photoAlt"));
    this.render();
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
        const step =
          event.key === "ArrowDown" || event.key === "ArrowRight" ? 1
          : event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1
          : 0;
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

    this.q<HTMLInputElement>(".zoom-slider").addEventListener("input", event => {
      const slider = event.currentTarget as HTMLInputElement;
      this.set("zoom", clampLevel(Number(slider.value)));
    });

    this.backdrop.querySelectorAll<HTMLInputElement>(".settings-slider").forEach(slider => {
      if (slider.classList.contains("zoom-slider")) return;
      const key = slider.dataset.key as (typeof SLIDERS)[number]["key"];
      slider.addEventListener("input", () => this.set(key, Number(slider.value)));
      // Let go of the master / effects slider: play a blip at the new level.
      if (key !== "musicVolume") {
        slider.addEventListener("change", () => this.options.onSound?.("preview"));
      }
    });

    const mood = this.q<HTMLSelectElement>(".settings-select");
    mood.addEventListener("change", () => this.set("mood", mood.value as Mood));

    // Real <a target="_blank"> links. Stop the gesture before it reaches window,
    // where Phaser's mouse/touch listeners would treat it as tap-to-move.
    // Don't preventDefault: the browser has to follow the link, including on
    // touch, where window.open is what popup blockers throw away.
    this.backdrop.querySelectorAll<HTMLAnchorElement>("a.credit-link").forEach(link => {
      const stop = (event: Event) => event.stopPropagation();
      for (const type of ["pointerdown", "pointerup", "mousedown", "mouseup", "touchstart", "touchend", "click"] as const) {
        link.addEventListener(type, stop);
      }
      link.addEventListener("click", () => this.options.onSound?.("click"));
    });

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
      ...this.modal.querySelectorAll<HTMLElement>("button, input, select, a[href]"),
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

  /**
   * The camera (pinch, wheel, zoom keys, or a resize clamp) landed on `level`.
   * Saves it and moves the slider without treating it as a new user edit
   * that would call back into the camera.
   */
  adoptZoom(level: number) {
    const next = clampLevel(level);
    if (this.values.zoom === next) {
      this.renderZoom();
      return;
    }
    this.values.zoom = next;
    this.chosen.add("zoom");
    saveSettings(this.values, this.chosen);
    this.renderZoom();
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
    const howto = !mobile ? "keyboard" : this.values.hideButtons ? "touch" : "mobile";
    this.backdrop.querySelectorAll<HTMLElement>("[data-howto]").forEach(list => {
      list.hidden = list.dataset.howto !== howto;
    });
    this.q<HTMLElement>("[data-help]").textContent =
      howto === "touch" ? t("howto.helpTouch")
      : howto === "mobile" ? t("howto.helpMobile")
      : t("howto.helpKeyboard");

    this.renderZoom();

    for (const { key } of SLIDERS) {
      const value = this.values[key];
      const slider = this.q<HTMLInputElement>(`.settings-slider[data-key="${key}"]`);
      if (Number(slider.value) !== value) slider.value = String(value);
      slider.style.setProperty("--fill", `${value}%`);
      this.q<HTMLOutputElement>(`[data-value="${key}"]`).textContent = String(value);
    }
    const mood = this.q<HTMLSelectElement>(".settings-select");
    if (mood.value !== this.values.mood) mood.value = this.values.mood;
    const blurbKey = `mood.${this.values.mood}.blurb` as MessageKey;
    this.q<HTMLElement>("[data-mood-blurb]").textContent = t(blurbKey);

    this.backdrop.querySelectorAll<HTMLButtonElement>(".skin-card").forEach(card => {
      const picked = card.dataset.skin === this.values.skin;
      card.setAttribute("aria-checked", String(picked));
      card.classList.toggle("picked", picked);
      card.tabIndex = picked ? 0 : -1;
    });
    this.updateScrollFade();
  }

  /** Zoom thumb, center-out fill, and the numeric level (0 in the middle). */
  private renderZoom() {
    const value = this.values.zoom;
    const slider = this.q<HTMLInputElement>(".zoom-slider");
    if (Number(slider.value) !== value) slider.value = String(value);
    slider.style.setProperty("--p", `${zoomTrackPercent(value)}%`);
    this.q<HTMLOutputElement>("[data-value='zoom']").textContent = String(value);
  }
}
