import type { Locale } from "./detect.ts";

/** Jim's order: English, Spanish, Chinese, Japanese, then Hindi and Urdu, then the rest. */
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
  "pt-BR",
  "pt-PT",
  "fr-FR",
  "fr-CA",
  "fr-BE",
  "de-DE",
  "de-AT",
  "de-CH",
  "ru-RU",
  "ko-KR",
  "id-ID",
  "ar-SA",
  "ar-EG",
  "tr-TR",
  "vi-VN",
  "it-IT",
  "pl-PL",
  "fil-PH",
  "th-TH",
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
  "pt-BR": { language: "Português", region: "Brasil" },
  "pt-PT": { language: "Português", region: "Portugal" },
  "fr-FR": { language: "Français", region: "France" },
  "fr-CA": { language: "Français", region: "Canada" },
  "fr-BE": { language: "Français", region: "Belgique" },
  "de-DE": { language: "Deutsch", region: "Deutschland" },
  "de-AT": { language: "Deutsch", region: "Österreich" },
  "de-CH": { language: "Deutsch", region: "Schweiz" },
  "ru-RU": { language: "Русский", region: "Россия" },
  "ko-KR": { language: "한국어", region: "대한민국" },
  "id-ID": { language: "Bahasa Indonesia", region: "Indonesia" },
  "ar-SA": { language: "العربية الفصحى", region: "السعودية" },
  "ar-EG": { language: "العربية", region: "مصر" },
  "tr-TR": { language: "Türkçe", region: "Türkiye" },
  "vi-VN": { language: "Tiếng Việt", region: "Việt Nam" },
  "it-IT": { language: "Italiano", region: "Italia" },
  "pl-PL": { language: "Polski", region: "Polska" },
  "fil-PH": { language: "Filipino", region: "Pilipinas" },
  "th-TH": { language: "ไทย", region: "ประเทศไทย" },
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
