import type { Locale } from "./detect.ts";

/** Jim's order: English, Spanish, Chinese, Japanese, then Hindi and Urdu. */
export const LOCALE_ORDER: readonly Locale[] = [
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
  "hi-IN",
  "ur-PK",
];

/** Native names. Shown as `Language  -  Region` regardless of the UI locale. */
const NAMES: Record<Locale, { language: string; region: string }> = {
  "en-US": { language: "English", region: "United States" },
  "en-GB": { language: "English", region: "United Kingdom" },
  "en-AU": { language: "English", region: "Australia" },
  "es-MX": { language: "Español", region: "México" },
  "es-CO": { language: "Español", region: "Colombia" },
  "es-DO": { language: "Español", region: "República Dominicana" },
  "es-ES": { language: "Español", region: "España" },
  "es-AR": { language: "Español", region: "Argentina" },
  "zh-CN": { language: "简体中文", region: "中国大陆" },
  "ja-JP": { language: "日本語", region: "日本" },
  "hi-IN": { language: "हिन्दी", region: "भारत" },
  "ur-PK": { language: "اردو", region: "پاکستان" },
};

/** Uppercase language subtag: EN, ES, ZH, JA, HI, UR. */
export function localeCode(locale: Locale): string {
  return locale.slice(0, locale.indexOf("-")).toUpperCase();
}

/** `English  -  United States` (two spaces around the dash, as Jim specified). */
export function localeOptionLabel(locale: Locale): string {
  const name = NAMES[locale];
  return `${name.language}  -  ${name.region}`;
}
