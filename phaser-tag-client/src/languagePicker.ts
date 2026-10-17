/**
 * Language button immediately left of the settings cog, plus the list that
 * opens under it. Collapsed: region flag + language code (EN, ES, ZH, JA).
 * Open: every locale as flag + "Language  -  Region" in its own language.
 */
import {
  flagSvg,
  getLocale,
  localeCode,
  localeOptionLabel,
  LOCALE_ORDER,
  onLocaleChange,
  setLocale,
  t,
} from "./i18n";

export interface LanguagePickerOptions {
  onOpenChange?(open: boolean): void;
  onSound?(): void;
}

export class LanguagePicker {
  readonly button: HTMLButtonElement;
  private readonly panel: HTMLElement;
  private opened = false;

  constructor(
    hud: HTMLElement,
    private readonly options: LanguagePickerOptions = {}
  ) {
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "lang-button";
    this.button.setAttribute("aria-haspopup", "listbox");
    this.button.setAttribute("aria-expanded", "false");
    this.button.addEventListener("click", event => {
      event.stopPropagation();
      this.options.onSound?.();
      this.toggle();
    });
    hud.appendChild(this.button);

    this.panel = document.createElement("div");
    this.panel.className = "lang-popover";
    this.panel.hidden = true;
    this.panel.setAttribute("role", "listbox");
    this.panel.tabIndex = -1;
    document.body.appendChild(this.panel);

    this.panel.addEventListener("pointerdown", event => event.stopPropagation());
    this.panel.addEventListener("click", event => event.stopPropagation());
    for (const type of ["keydown", "keyup"] as const) {
      this.panel.addEventListener(type, event => event.stopPropagation());
    }
    // A drag on the list scrolls the list, not the page or the game.
    this.panel.addEventListener(
      "touchmove",
      event => event.stopPropagation(),
      { passive: true }
    );

    let previous: string | null = null;
    for (const locale of LOCALE_ORDER) {
      const language = locale.slice(0, locale.indexOf("-"));
      const option = document.createElement("button");
      option.type = "button";
      option.className = "lang-option";
      if (previous !== null && previous !== language) option.classList.add("group-start");
      previous = language;
      option.dataset.locale = locale;
      option.lang = locale;
      option.dir = locale === "ur-PK" ? "rtl" : "ltr";
      option.setAttribute("role", "option");
      option.innerHTML = `<span class="lang-flag" aria-hidden="true">${flagSvg(locale)}</span><span class="lang-name"></span>`;
      const name = option.querySelector(".lang-name");
      if (name) name.textContent = localeOptionLabel(locale);
      option.addEventListener("click", () => {
        this.options.onSound?.();
        setLocale(locale);
        this.close();
      });
      this.panel.appendChild(option);
    }

    onLocaleChange(() => this.render());
    this.render();
  }

  get isOpen() {
    return this.opened;
  }

  toggle() {
    if (this.opened) this.close();
    else this.open();
  }

  open() {
    if (this.opened) return;
    this.opened = true;
    this.panel.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    this.button.classList.add("open");
    this.place();
    document.addEventListener("pointerdown", this.onPointerDown, true);
    document.addEventListener("keydown", this.onKey, true);
    window.addEventListener("resize", this.place);
    this.options.onOpenChange?.(true);
    const selected = this.panel.querySelector<HTMLElement>('[aria-selected="true"]');
    selected?.scrollIntoView({ block: "nearest" });
    this.panel.focus();
  }

  close() {
    if (!this.opened) return;
    this.opened = false;
    this.panel.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
    this.button.classList.remove("open");
    document.removeEventListener("pointerdown", this.onPointerDown, true);
    document.removeEventListener("keydown", this.onKey, true);
    window.removeEventListener("resize", this.place);
    this.options.onOpenChange?.(false);
    this.button.blur();
  }

  private readonly place = () => {
    const rect = this.button.getBoundingClientRect();
    const width = Math.min(340, window.innerWidth - 16);
    let left = rect.right - width;
    if (left < 8) left = 8;
    if (left + width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - 8 - width);
    const top = rect.bottom + 8;
    this.panel.style.width = `${width}px`;
    this.panel.style.left = `${left}px`;
    this.panel.style.top = `${top}px`;
    const room = Math.max(160, window.innerHeight - top - 12);
    this.panel.style.maxHeight = `${Math.min(360, room)}px`;
  };

  private readonly onPointerDown = (event: PointerEvent) => {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (this.panel.contains(target) || this.button.contains(target)) return;
    // The tap that dismisses the list must not also walk or tag.
    event.preventDefault();
    event.stopPropagation();
    this.close();
  };

  private readonly onKey = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    this.close();
  };

  private render() {
    const locale = getLocale();
    this.button.setAttribute("aria-label", `${t("lang.choose")}: ${localeOptionLabel(locale)}`);
    this.panel.setAttribute("aria-label", t("lang.choose"));
    this.button.innerHTML = `<span class="lang-flag" aria-hidden="true">${flagSvg(locale)}</span><span class="lang-code">${localeCode(locale)}</span>`;
    this.panel.querySelectorAll<HTMLButtonElement>(".lang-option").forEach(option => {
      const selected = option.dataset.locale === locale;
      option.setAttribute("aria-selected", String(selected));
      option.classList.toggle("selected", selected);
    });
  }
}
