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
import { ptBR } from "./messages/pt-BR.ts";
import { ptPT } from "./messages/pt-PT.ts";
import { frFR } from "./messages/fr-FR.ts";
import { frCA } from "./messages/fr-CA.ts";
import { frBE } from "./messages/fr-BE.ts";
import { deDE } from "./messages/de-DE.ts";
import { deAT } from "./messages/de-AT.ts";
import { deCH } from "./messages/de-CH.ts";
import { ruRU } from "./messages/ru-RU.ts";
import { koKR } from "./messages/ko-KR.ts";
import { idID } from "./messages/id-ID.ts";
import { arSA } from "./messages/ar-SA.ts";
import { arEG } from "./messages/ar-EG.ts";
import { trTR } from "./messages/tr-TR.ts";
import { viVN } from "./messages/vi-VN.ts";
import { itIT } from "./messages/it-IT.ts";
import { plPL } from "./messages/pl-PL.ts";
import { filPH } from "./messages/fil-PH.ts";
import { thTH } from "./messages/th-TH.ts";

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
  "pt-BR": ptBR,
  "pt-PT": withBase(ptBR, ptPT),
  "fr-FR": frFR,
  "fr-CA": withBase(frFR, frCA),
  "fr-BE": withBase(frFR, frBE),
  "de-DE": deDE,
  "de-AT": withBase(deDE, deAT),
  "de-CH": withBase(deDE, deCH),
  "ru-RU": ruRU,
  "ko-KR": koKR,
  "id-ID": idID,
  "ar-SA": arSA,
  "ar-EG": withBase(arSA, arEG),
  "tr-TR": trTR,
  "vi-VN": viVN,
  "it-IT": itIT,
  "pl-PL": plPL,
  "fil-PH": filPH,
  "th-TH": thTH,
};
