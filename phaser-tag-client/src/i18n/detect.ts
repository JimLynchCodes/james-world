/**
 * Pick a supported locale from browser signals. Pure: no localStorage,
 * geolocation, or network. Callers pass the signals in.
 *
 * Order:
 *   1. Saved choice, if it is a supported locale.
 *   2. Walk `languages` (most preferred first). The first tag whose language
 *      we support wins:
 *        - exact locale (en-US, es-MX, …) is used as-is
 *        - otherwise the region is inferred, and that result is returned
 *          even if a later, less-preferred tag is an exact match
 *   3. en-US when nothing matches.
 *
 * Region inference, when the language matches but the region does not
 * (es, es-419, es-US, en, zh-Hans, …):
 *   1. A later tag with the same language and a supported region (es + es-AR).
 *   2. Timezone mapped to a locale of that same language. A timezone that
 *      maps to a different language is ignored, so an English browser in
 *      Mexico stays English, while en + Australia/Sydney becomes en-AU.
 *   3. A region subtag on any other tag that forms a supported locale
 *      (es + en-MX → es-MX).
 *   4. The language default (en → en-US, es → es-MX, zh → zh-CN, ja → ja-JP).
 *      Spanish falls back to es-MX: it is the first Spanish locale we ship,
 *      and generic / Latin American / US Spanish are closer to it than to Spain.
 */

export const LOCALES = [
  "en-US",
  "en-GB",
  "en-AU",
  "es-MX",
  "es-CO",
  "es-DO",
  "es-ES",
  "es-AR",
  "zh-CN",
  "ja-JP",
] as const;

export type Locale = (typeof LOCALES)[number];

const LOCALE_SET: ReadonlySet<string> = new Set(LOCALES);

export function isLocale(value: string): value is Locale {
  return LOCALE_SET.has(value);
}

/** When the language is known but no region signal applies. */
const LANGUAGE_DEFAULT: Readonly<Record<string, Locale>> = {
  en: "en-US",
  es: "es-MX",
  zh: "zh-CN",
  ja: "ja-JP",
};

const MEXICO_ZONES: ReadonlySet<string> = new Set([
  "America/Bahia_Banderas",
  "America/Cancun",
  "America/Chihuahua",
  "America/Ciudad_Juarez",
  "America/Ensenada",
  "America/Hermosillo",
  "America/Matamoros",
  "America/Mazatlan",
  "America/Merida",
  "America/Mexico_City",
  "America/Monterrey",
  "America/Ojinaga",
  "America/Santa_Isabel",
  "America/Tijuana",
]);

/** Mainland China. Hong Kong / Taipei are not mapped; zh still defaults to zh-CN. */
const CHINA_ZONES: ReadonlySet<string> = new Set([
  "Asia/Shanghai",
  "Asia/Urumqi",
  "Asia/Chongqing",
  "Asia/Chungking",
  "Asia/Harbin",
  "Asia/Kashgar",
]);

/**
 * US timezones, including territories. Mapped to en-US only when the
 * browser language is English; a Spanish browser in New York stays Spanish.
 */
const US_ZONES: ReadonlySet<string> = new Set([
  "America/Adak",
  "America/Anchorage",
  "America/Boise",
  "America/Chicago",
  "America/Denver",
  "America/Detroit",
  "America/Indiana/Indianapolis",
  "America/Indiana/Knox",
  "America/Indiana/Marengo",
  "America/Indiana/Petersburg",
  "America/Indiana/Tell_City",
  "America/Indiana/Vevay",
  "America/Indiana/Vincennes",
  "America/Indiana/Winamac",
  "America/Juneau",
  "America/Kentucky/Louisville",
  "America/Kentucky/Monticello",
  "America/Los_Angeles",
  "America/Menominee",
  "America/Metlakatla",
  "America/New_York",
  "America/Nome",
  "America/North_Dakota/Beulah",
  "America/North_Dakota/Center",
  "America/North_Dakota/New_Salem",
  "America/Phoenix",
  "America/Puerto_Rico",
  "America/Sitka",
  "America/St_Thomas",
  "America/Yakutat",
  "Pacific/Guam",
  "Pacific/Honolulu",
  "Pacific/Pago_Pago",
]);

export interface LocaleSignals {
  /** `navigator.languages`, most preferred first. */
  languages: readonly string[];
  /** `Intl.DateTimeFormat().resolvedOptions().timeZone`. */
  timeZone: string;
  /** Previously saved choice. Ignored unless it is a supported locale. */
  saved?: string | null;
}

interface ParsedTag {
  language: string;
  region: string | null;
}

/** BCP 47 tag → language + region, ignoring script and Unicode extensions. */
export function parseLanguageTag(raw: string): ParsedTag | null {
  const trimmed = raw.trim().replace(/_/g, "-");
  if (!trimmed) return null;
  const parts = trimmed.split("-");
  const language = parts[0]?.toLowerCase() ?? "";
  if (!/^[a-z]{2,3}$/.test(language)) return null;
  let region: string | null = null;
  for (let i = 1; i < parts.length; i++) {
    const part = parts[i] ?? "";
    const lower = part.toLowerCase();
    if (lower === "u" || lower === "x" || lower === "t") break;
    if (/^[a-zA-Z]{4}$/.test(part)) continue; // script (Hans, Latn, …)
    if (/^[a-zA-Z]{2}$/.test(part) || /^\d{3}$/.test(part)) {
      region = part.toUpperCase();
      break;
    }
    break; // variant
  }
  return { language, region };
}

function exactLocale(tag: ParsedTag): Locale | null {
  if (!tag.region) return null;
  const candidate = `${tag.language}-${tag.region}`;
  return isLocale(candidate) ? candidate : null;
}

/** Timezone → locale, or null when the zone is not one we map. */
export function localeFromTimeZone(timeZone: string): Locale | null {
  if (timeZone.startsWith("America/Argentina/") || timeZone === "America/Buenos_Aires") return "es-AR";
  if (timeZone.startsWith("Australia/")) return "en-AU";
  if (MEXICO_ZONES.has(timeZone)) return "es-MX";
  if (timeZone === "America/Bogota") return "es-CO";
  if (timeZone === "America/Santo_Domingo") return "es-DO";
  if (timeZone === "Europe/Madrid" || timeZone === "Atlantic/Canary" || timeZone === "Africa/Ceuta") {
    return "es-ES";
  }
  if (timeZone === "Europe/London") return "en-GB";
  if (CHINA_ZONES.has(timeZone)) return "zh-CN";
  if (timeZone === "Asia/Tokyo") return "ja-JP";
  if (US_ZONES.has(timeZone)) return "en-US";
  return null;
}

function inferRegion(language: string, tags: readonly ParsedTag[], timeZone: string): Locale {
  for (const tag of tags) {
    if (tag.language !== language) continue;
    const exact = exactLocale(tag);
    if (exact) return exact;
  }
  const fromZone = localeFromTimeZone(timeZone);
  if (fromZone?.startsWith(`${language}-`)) return fromZone;
  for (const tag of tags) {
    if (tag.language === language || !tag.region) continue;
    const candidate = `${language}-${tag.region}`;
    if (isLocale(candidate)) return candidate;
  }
  return LANGUAGE_DEFAULT[language] ?? "en-US";
}

export function resolveLocale(signals: LocaleSignals): Locale {
  if (signals.saved) {
    const saved = parseLanguageTag(signals.saved);
    const exact = saved ? exactLocale(saved) : null;
    if (exact) return exact;
  }

  const tags: ParsedTag[] = [];
  for (const raw of signals.languages) {
    const parsed = parseLanguageTag(raw);
    if (parsed) tags.push(parsed);
  }

  for (const tag of tags) {
    const exact = exactLocale(tag);
    if (exact) return exact;
    if (LANGUAGE_DEFAULT[tag.language]) return inferRegion(tag.language, tags, signals.timeZone);
  }
  return "en-US";
}
