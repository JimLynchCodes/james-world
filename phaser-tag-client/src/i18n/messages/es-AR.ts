import type { Messages } from "./en-US.ts";

/** Rioplatense Spanish. Voseo (vos, corré, tocá) and "la mancha". */
export const esAR: Partial<Messages> = {
  "meta.title": "La mancha",

  "title.kicker": "Bienvenido a",
  "title.blurb": "¡Corré, jugá a la mancha y divertite!",
  "title.start": "Empezar",
  "title.starting": "Empezando…",

  "toast.connectionLost": "Se cortó la conexión, reconectando…",
  "toast.joinedSelf": "Entraste como {name}",
  "toast.joined": "{name} se unió",
  "toast.left": "{name} se fue",

  "label.you": "VOS",
  "label.it": "MANCHA",

  "hint.keyboard":
    "<strong>WASD / flechas</strong> para moverte · <strong>MAYÚS</strong> para correr · <strong>ESPACIO</strong> o <strong>T</strong> para manchar",
  "hint.mobile":
    "<strong>Tocá</strong> el piso para caminar o usá la <strong>palanca</strong> · <strong>TOCA</strong> o tocá a un jugador cerca · mantené <strong>CORRÉ</strong> para correr",
  "hint.mobileTouch":
    "<strong>Tocá</strong> el piso para caminar · <strong>doble toque</strong> para correr · <strong>tocá a un jugador</strong> cerca para manchar",

  "settings.controls.mobile": "Celular",
  "settings.controls.flipJoystick": "Invertir palanca",
  "settings.controls.flipTagRun": "Invertir Toca / Corré",
  "settings.controls.phoneHint":
    "¿Jugás en el celular o en una tablet? Elegí <strong>Celular</strong> para una palanca y botones grandes de TOCA y CORRÉ.",

  "howto.runHold": "Correr (mantené)",
  "howto.tag": "¡Toca!",
  "howto.joyWalk": "Palanca, o tocá el piso, para caminar",
  "howto.tagTap": "Tocá, o tocá a un jugador cerca",
  "howto.holdRun": "Mantené para correr",
  "howto.pinch": "Pellizcá para hacer zoom",
  "howto.tapWalk": "Tocá el piso para caminar",
  "howto.tapPlayer": "Tocá a un jugador para manchar",
  "howto.helpMobile": "Arrastrá en el piso para manejar. ¡Mezclá todo! Ideal para el celular y la tablet.",
  "howto.helpTouch": "Si está lejos, caminás hacia él.",
  "settings.view.input": "Alt + ↑ o W acerca. Alt + ↓ o S aleja. Alt + la rueda del mouse acerca y aleja. Pellizcá con dos dedos.",
  "howto.helpKeyboard": "Tocá a alguien cerca para que quede la mancha.",

  "settings.skins.help": "El mismo héroe, otro estilo.",
  "skin.banana.note": "¡A lamer y salir rajando!",
  "skin.trex.note": "¡T-Rex, la mancha!",
  "skin.tuxedo.note": "¡Empilchadísimo!",
  "skin.pirate.note": "¡Arrr, la manchás!",
  "skin.pharaoh.note": "¡Caminá como egipcio!",
  "skin.spaceman.note": "Un pasito...",

  "credits.bio":
    "Este juego lo hizo James, un ingeniero de software que vive en Nueva York (también conocido como Jim, Jimbo, Jimothy y Sir Jims-a-lot).",
  "credits.linkedinLead": "Si querés, conectate conmigo en LinkedIn:",
  "credits.githubLead": "Dale una mirada al código, hacé un fork y dejale una estrella. 😉",

  "mobile.tag": "TOCA",
  "mobile.tagAria": "Manchar",
  "mobile.run": "CORRÉ",
  "mobile.runAria": "Correr (mantené)",
  "mobile.joystickAria": "Palanca: arrastrá para moverte",

  "lang.choose": "Elegí un idioma",

  "cave.line1": "DOMINÁ LA MANCHA Y",
  "cave.line2": "ESTO SERÁ TUYO.",

  "bsod.aria": "Error: misión no implementada.",
  "bsod.text": `Se detectó un problema y James World se cerró para evitar daños
en tu computadora.

Error: misión no implementada.

Si es la primera vez que ves esta pantalla de error,
reiniciá tu computadora. Si aparece de nuevo, seguí
estos pasos:

Fijate de que el hardware o el software nuevo esté bien instalado.
Si es una instalación nueva, pedile al fabricante
las actualizaciones de James World que hagan falta.

Si el problema sigue, desactivá o sacá el hardware
o el software recién instalado. Desactivá opciones de memoria del BIOS como la caché o el shadowing.
Si necesitás el modo seguro para sacar o desactivar componentes, reiniciá
tu computadora, apretá F8 para elegir las opciones de inicio avanzadas y después
elegí Modo seguro.

Información técnica:

*** STOP: 0x0000007B (0xC0000034, 0x00000000, 0x00000000, 0x00000000)


Apretá cualquier tecla o tocá para continuar `,
  "sign.quest": "Si buscás aventuras y cuevas para explorar,\n\nhacé el código especial en el árbol de tronco ancho, dale, sin dudar...",
};
