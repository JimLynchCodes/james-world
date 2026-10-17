/**
 * Locale picking and dictionary coverage.
 *
 *   node --experimental-strip-types --test tools/check_locale.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { supportsCaveGlyphs } from "../src/caveFont.ts";
import { MESSAGES } from "../src/i18n/catalog.ts";
import { LOCALES, resolveLocale, type LocaleSignals } from "../src/i18n/detect.ts";

function pick(partial: Partial<LocaleSignals> & Pick<LocaleSignals, "languages">): string {
  return resolveLocale({ timeZone: "UTC", saved: null, ...partial });
}

test("saved choice wins over languages and timezone", () => {
  assert.equal(
    pick({ saved: "es-CO", languages: ["en-US"], timeZone: "Asia/Tokyo" }),
    "es-CO"
  );
  assert.equal(pick({ saved: "en_GB", languages: ["es-MX"], timeZone: "America/Mexico_City" }), "en-GB");
  assert.equal(pick({ saved: "  zh-cn ", languages: ["en"], timeZone: "Europe/London" }), "zh-CN");
});

test("an unrecognised saved value is ignored", () => {
  assert.equal(pick({ saved: "fr-FR", languages: ["en-GB"], timeZone: "Asia/Tokyo" }), "en-GB");
  assert.equal(pick({ saved: "en", languages: ["es-MX"], timeZone: "Europe/Madrid" }), "es-MX");
  assert.equal(pick({ saved: "", languages: [], timeZone: "UTC" }), "en-US");
});

test("exact navigator.languages match beats timezone and later tags", () => {
  assert.equal(pick({ languages: ["en-US"], timeZone: "Australia/Sydney" }), "en-US");
  assert.equal(pick({ languages: ["en-GB", "en-US"], timeZone: "America/New_York" }), "en-GB");
  assert.equal(pick({ languages: ["es-CO", "en"], timeZone: "Europe/Madrid" }), "es-CO");
  assert.equal(pick({ languages: ["EN-au"], timeZone: "America/Chicago" }), "en-AU");
  assert.equal(pick({ languages: ["zh-Hans-CN"], timeZone: "Asia/Tokyo" }), "zh-CN");
  assert.equal(pick({ languages: ["ja-JP"], timeZone: "America/Los_Angeles" }), "ja-JP");
});

test("a preferred language is inferred before a later exact match", () => {
  assert.equal(
    pick({ languages: ["es", "en-US"], timeZone: "America/Mexico_City" }),
    "es-MX"
  );
  assert.equal(
    pick({ languages: ["es-419", "en-US"], timeZone: "America/Santo_Domingo" }),
    "es-DO"
  );
});

test("English in Mexico stays English; English in Australia becomes en-AU", () => {
  assert.equal(pick({ languages: ["en"], timeZone: "America/Mexico_City" }), "en-US");
  assert.equal(pick({ languages: ["en"], timeZone: "America/Cancun" }), "en-US");
  assert.equal(pick({ languages: ["en"], timeZone: "Asia/Tokyo" }), "en-US");
  assert.equal(pick({ languages: ["en"], timeZone: "Asia/Shanghai" }), "en-US");
  assert.equal(pick({ languages: ["en"], timeZone: "Australia/Sydney" }), "en-AU");
  assert.equal(pick({ languages: ["en"], timeZone: "Australia/Perth" }), "en-AU");
  assert.equal(pick({ languages: ["en"], timeZone: "Australia/Lord_Howe" }), "en-AU");
  assert.equal(pick({ languages: ["en"], timeZone: "Europe/London" }), "en-GB");
});

test("US timezones map an English browser to en-US", () => {
  for (const timeZone of [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Indiana/Indianapolis",
  ]) {
    assert.equal(pick({ languages: ["en"], timeZone }), "en-US", timeZone);
  }
});

test("Spanish region comes from the timezone when the tag has none", () => {
  assert.equal(pick({ languages: ["es"], timeZone: "America/Mexico_City" }), "es-MX");
  assert.equal(pick({ languages: ["es"], timeZone: "America/Tijuana" }), "es-MX");
  assert.equal(pick({ languages: ["es"], timeZone: "America/Bogota" }), "es-CO");
  assert.equal(pick({ languages: ["es"], timeZone: "America/Santo_Domingo" }), "es-DO");
  assert.equal(pick({ languages: ["es"], timeZone: "Europe/Madrid" }), "es-ES");
  assert.equal(pick({ languages: ["es"], timeZone: "Atlantic/Canary" }), "es-ES");
  assert.equal(pick({ languages: ["es"], timeZone: "Africa/Ceuta" }), "es-ES");
  assert.equal(pick({ languages: ["es"], timeZone: "America/Argentina/Buenos_Aires" }), "es-AR");
  assert.equal(pick({ languages: ["es"], timeZone: "America/Argentina/Cordoba" }), "es-AR");
  assert.equal(pick({ languages: ["es"], timeZone: "America/Buenos_Aires" }), "es-AR");
});

test("es-419 and es-US infer a Spanish region and never switch to English", () => {
  assert.equal(pick({ languages: ["es-419"], timeZone: "America/Bogota" }), "es-CO");
  assert.equal(pick({ languages: ["es-419"], timeZone: "Europe/Madrid" }), "es-ES");
  assert.equal(pick({ languages: ["es-US"], timeZone: "America/Mexico_City" }), "es-MX");
  // New York maps to en-US, which is the wrong language, so Spanish stays Spanish.
  assert.equal(pick({ languages: ["es-US"], timeZone: "America/New_York" }), "es-MX");
  assert.equal(pick({ languages: ["es"], timeZone: "UTC" }), "es-MX");
});

test("an explicit same-language region beats the timezone", () => {
  assert.equal(
    pick({ languages: ["en", "en-AU"], timeZone: "America/New_York" }),
    "en-AU"
  );
  assert.equal(
    pick({ languages: ["es", "es-AR"], timeZone: "America/Mexico_City" }),
    "es-AR"
  );
});

test("a region subtag on another language is used when the timezone disagrees in language", () => {
  assert.equal(
    pick({ languages: ["es", "en-MX"], timeZone: "America/New_York" }),
    "es-MX"
  );
  // Madrid is Spanish, so the timezone wins over a borrowed MX region.
  assert.equal(pick({ languages: ["es", "en-MX"], timeZone: "Europe/Madrid" }), "es-ES");
});

test("Chinese and Japanese follow the same language-wins rule", () => {
  assert.equal(pick({ languages: ["zh"], timeZone: "Asia/Shanghai" }), "zh-CN");
  assert.equal(pick({ languages: ["zh"], timeZone: "Asia/Urumqi" }), "zh-CN");
  assert.equal(pick({ languages: ["zh-Hans"], timeZone: "Asia/Tokyo" }), "zh-CN");
  assert.equal(pick({ languages: ["ja"], timeZone: "Asia/Tokyo" }), "ja-JP");
  assert.equal(pick({ languages: ["ja"], timeZone: "America/Chicago" }), "ja-JP");
});

test("Hindi and Urdu follow language, then their timezones", () => {
  assert.equal(pick({ languages: ["hi"], timeZone: "Asia/Kolkata" }), "hi-IN");
  assert.equal(pick({ languages: ["hi"], timeZone: "Asia/Calcutta" }), "hi-IN");
  assert.equal(pick({ languages: ["hi-IN"], timeZone: "Asia/Karachi" }), "hi-IN");
  assert.equal(pick({ languages: ["hi"], timeZone: "America/New_York" }), "hi-IN");
  assert.equal(pick({ languages: ["ur"], timeZone: "Asia/Karachi" }), "ur-PK");
  assert.equal(pick({ languages: ["ur"], timeZone: "Asia/Kolkata" }), "ur-PK");
  assert.equal(pick({ languages: ["ur-PK"], timeZone: "Europe/London" }), "ur-PK");
  assert.equal(pick({ languages: ["en"], timeZone: "Asia/Kolkata" }), "en-US");
  assert.equal(pick({ languages: ["en"], timeZone: "Asia/Calcutta" }), "en-US");
  assert.equal(pick({ languages: ["en"], timeZone: "Asia/Karachi" }), "en-US");
  assert.equal(pick({ languages: ["hi", "en-IN"], timeZone: "America/Chicago" }), "hi-IN");
  assert.equal(pick({ saved: "ur-PK", languages: ["en"], timeZone: "Asia/Kolkata" }), "ur-PK");
});

test("unsupported languages fall through, and nothing at all is en-US", () => {
  assert.equal(pick({ languages: ["fr-FR", "de", "en-GB"], timeZone: "Europe/Madrid" }), "en-GB");
  assert.equal(pick({ languages: ["fr", "de"], timeZone: "Australia/Sydney" }), "en-US");
  assert.equal(pick({ languages: [], timeZone: "Europe/London" }), "en-US");
});

test("every locale has every message key", () => {
  const keys = Object.keys(MESSAGES["en-US"]).sort();
  for (const locale of LOCALES) {
    assert.deepEqual(Object.keys(MESSAGES[locale]).sort(), keys, locale);
    for (const key of keys) {
      const value = MESSAGES[locale][key as keyof (typeof MESSAGES)["en-US"]];
      assert.equal(typeof value, "string", `${locale} ${key}`);
      assert.ok(value.length > 0, `${locale} ${key} empty`);
    }
  }
});

test("names and link targets stay put inside translated copy", () => {
  for (const locale of LOCALES) {
    const bio = MESSAGES[locale]["credits.bio"];
    assert.match(bio, /James/);
    assert.match(bio, /Jimbo/);
    assert.match(bio, /Jimothy/);
    assert.match(bio, /Sir Jims-a-lot/);
    assert.match(MESSAGES[locale]["toast.joinedSelf"], /\{name\}/);
    assert.match(MESSAGES[locale]["toast.serverError"], /\{message\}/);
    assert.match(MESSAGES[locale]["bsod.text"], /0x0000007B/);
  }
});

test("regional voice shows up in the strings that should differ", () => {
  assert.match(MESSAGES["en-GB"]["settings.skins.help"], /colour/);
  assert.match(MESSAGES["en-AU"]["settings.skins.help"], /colour/);
  assert.match(MESSAGES["en-AU"]["credits.githubLead"], /squiz/);
  assert.match(MESSAGES["es-ES"]["title.blurb"], /jugad/);
  assert.match(MESSAGES["es-ES"]["credits.githubLead"], /haced/);
  assert.match(MESSAGES["es-ES"]["bsod.text"], /ordenador/);
  assert.match(MESSAGES["es-AR"]["title.blurb"], /jugá/);
  assert.match(MESSAGES["es-AR"]["label.you"], /VOS/);
  assert.match(MESSAGES["es-AR"]["cave.line1"], /DOMINÁ/);
  assert.match(MESSAGES["es-CO"]["bsod.text"], /computador/);
  assert.equal(MESSAGES["zh-CN"]["label.it"], "鬼");
  assert.equal(MESSAGES["ja-JP"]["label.it"], "鬼");
  assert.equal(MESSAGES["ja-JP"]["label.you"], "自分");
  assert.match(MESSAGES["hi-IN"]["title.blurb"], /[\u0900-\u097F]/);
  assert.equal(MESSAGES["hi-IN"]["label.it"], "डेन");
  assert.match(MESSAGES["ur-PK"]["title.blurb"], /[\u0600-\u06FF]/);
  assert.equal(MESSAGES["ur-PK"]["label.it"], "ڈین");
  assert.equal(MESSAGES["ur-PK"]["lang.choose"], "زبان چنو");
});

test("the cave pixel font covers Latin quotes and not CJK", () => {
  for (const locale of ["en-US", "en-GB", "en-AU", "es-MX", "es-CO", "es-DO", "es-ES", "es-AR"] as const) {
    assert.equal(supportsCaveGlyphs(MESSAGES[locale]["cave.line1"]), true, locale);
    assert.equal(supportsCaveGlyphs(MESSAGES[locale]["cave.line2"]), true, locale);
  }
  assert.equal(supportsCaveGlyphs(MESSAGES["zh-CN"]["cave.line1"]), false);
  assert.equal(supportsCaveGlyphs(MESSAGES["ja-JP"]["cave.line1"]), false);
  assert.equal(supportsCaveGlyphs(MESSAGES["ja-JP"]["cave.line2"]), false);
  assert.equal(supportsCaveGlyphs(MESSAGES["hi-IN"]["cave.line1"]), false);
  assert.equal(supportsCaveGlyphs(MESSAGES["ur-PK"]["cave.line1"]), false);
  assert.equal(supportsCaveGlyphs(MESSAGES["ur-PK"]["cave.line2"]), false);
});
