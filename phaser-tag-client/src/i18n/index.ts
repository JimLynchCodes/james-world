/**
 * Locale state for the client. `resolveLocale` is pure (see detect.ts);
 * this module is the browser side: localStorage, `<html lang>`, and UI refresh.
 */
import { isLocale, resolveLocale, type Locale } from "./detect.ts";
import { MESSAGES } from "./catalog.ts";
import type { MessageKey } from "./messages/en-US.ts";

export { LOCALES, isLocale, resolveLocale, localeFromTimeZone, parseLanguageTag } from "./detect.ts";
export type { Locale, LocaleSignals } from "./detect.ts";
export { LOCALE_ORDER, localeCode, localeOptionLabel } from "./locales.ts";
export { flagSvg } from "./flags.ts";
export type { MessageKey } from "./messages/en-US.ts";

const STORAGE_KEY = "tag26.locale";

let current: Locale = "en-US";
const listeners = new Set<() => void>();

export function getLocale(): Locale {
  return current;
}

export function t(key: MessageKey, vars?: Record<string, string | number>): string {
  let text: string = MESSAGES[current][key];
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

/** One player vs many. Chinese and Japanese use the same pattern for both. */
export function tPlayers(count: number): string {
  return t(count === 1 ? "hud.players.one" : "hud.players.other", { count });
}

export function onLocaleChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function readSaved(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function applyDocument(locale: Locale) {
  document.documentElement.lang = locale;
  document.title = MESSAGES[locale]["meta.title"];
}

export function setLocale(locale: Locale): void {
  if (!isLocale(locale) || locale === current) return;
  current = locale;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Private mode: the choice still applies this session.
  }
  applyDocument(locale);
  for (const listener of listeners) listener();
}

/** Saved choice, else browser languages + timezone, else en-US. Does not prompt. */
export function initI18n(): Locale {
  const languages =
    typeof navigator !== "undefined" && navigator.languages?.length
      ? navigator.languages
      : [typeof navigator !== "undefined" ? navigator.language : "en-US"];
  let timeZone = "UTC";
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    timeZone = "UTC";
  }
  current = resolveLocale({ languages, timeZone, saved: readSaved() });
  applyDocument(current);
  return current;
}
