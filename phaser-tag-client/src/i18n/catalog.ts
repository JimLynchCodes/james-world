import type { Locale } from "./detect.ts";
import { enAU } from "./messages/en-AU.ts";
import { enGB } from "./messages/en-GB.ts";
import { enUS, type Messages } from "./messages/en-US.ts";
import { esAR } from "./messages/es-AR.ts";
import { esCO } from "./messages/es-CO.ts";
import { esDO } from "./messages/es-DO.ts";
import { esES } from "./messages/es-ES.ts";
import { esMX } from "./messages/es-MX.ts";
import { hiIN } from "./messages/hi-IN.ts";
import { jaJP } from "./messages/ja-JP.ts";
import { urPK } from "./messages/ur-PK.ts";
import { zhCN } from "./messages/zh-CN.ts";

/** Regional packs override a complete base, so every locale has every key. */
function withBase(base: Messages, over: Partial<Messages>): Messages {
  return { ...base, ...over };
}

export const MESSAGES: Record<Locale, Messages> = {
  "en-US": enUS,
  "en-GB": withBase(enUS, enGB),
  "en-AU": withBase(enUS, enAU),
  "es-MX": esMX,
  "es-CO": withBase(esMX, esCO),
  "es-DO": withBase(esMX, esDO),
  "es-ES": withBase(esMX, esES),
  "es-AR": withBase(esMX, esAR),
  "zh-CN": zhCN,
  "ja-JP": jaJP,
  "hi-IN": hiIN,
  "ur-PK": urPK,
};
