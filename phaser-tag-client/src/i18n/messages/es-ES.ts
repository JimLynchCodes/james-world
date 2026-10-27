import type { Messages } from "./en-US.ts";

/**
 * Spanish from Spain. Vocabulary (ordenador, móvil, pilla) and vosotros
 * where the line addresses more than one person (title, credits).
 * One player still gets tú.
 */
export const esES: Partial<Messages> = {
  "meta.title": "La pilla",

  "title.kicker": "Bienvenidos a",
  "title.heading": "Mundo de James",
  "title.blurb": "¡Corred, jugad a la pilla y pasadlo bien!",
  "title.start": "Empezar",
  "title.starting": "Empezando…",

  "toast.connectionLost": "Se ha perdido la conexión. Reconectando…",
  "toast.reconnected": "Reconectado como {name}",
  "toast.joinedSelf": "Te has unido como {name}",
  "toast.joined": "{name} se ha unido",
  "toast.left": "{name} se ha ido",
  "toast.leftUnknown": "Un jugador se ha ido",

  "label.you": "TÚ",
  "label.it": "PILLA",

  "hint.keyboard":
    "<strong>WASD / flechas</strong> para moverte · <strong>MAYÚS</strong> para correr · <strong>ESPACIO</strong> o <strong>T</strong> para pillar",
  "hint.mobile":
    "<strong>Toca</strong> el suelo para andar o usa el <strong>joystick</strong> · <strong>PILLA</strong> o toca a un jugador cercano · mantén <strong>CORRE</strong> para correr",
  "hint.mobileTouch":
    "<strong>Toca</strong> el suelo para andar · <strong>doble toque</strong> para correr · <strong>toca a un jugador</strong> cercano para pillar",

  "settings.aria": "Ajustes",
  "settings.title": "Ajustes",
  "settings.controls.mobile": "Móvil",
  "settings.controls.flipJoystick": "Invertir joystick",
  "settings.controls.flipTagRun": "Invertir Pilla / Corre",
  "settings.controls.phoneHint":
    "¿Jugáis en el móvil o en una tableta? Elegid <strong>Móvil</strong> para un joystick y botones grandes de PILLA y CORRE.",

  "howto.tag": "¡Pilla!",
  "howto.runHold": "Correr (mantén)",
  "howto.joyWalk": "Joystick, o toca el suelo, para andar",
  "howto.tagTap": "Pilla, o toca a un jugador cercano",
  "howto.holdRun": "Mantén pulsado para correr",
  "howto.tapWalk": "Toca el suelo para andar",
  "howto.tapPlayer": "Toca a un jugador para pillar",
  "howto.helpMobile": "Arrastra por el suelo para dirigir. ¡Combinadlo como queráis! Genial en el móvil y la tableta.",
  "howto.helpTouch": "Si está lejos, andas hacia él.",
  "howto.helpKeyboard": "Pilla a alguien cerca para que la lleve.",
  "howto.wheel": "Rueda del ratón para hacer zoom",
  "settings.view.input": "Alt + ↑ o W acerca. Alt + ↓ o S aleja. Alt + la rueda del ratón acerca y aleja. Pellizca con dos dedos.",

  "settings.skins.help": "El mismo héroe, otro rollo.",
  "skin.james.note": "James de toda la vida",
  "skin.banana.note": "¡En un pis pas, a lamer!",
  "skin.trex.note": "¡T-Rex, la pilla!",
  "skin.tuxedo.note": "¡Vestido para impresionar!",
  "skin.pirate.note": "¡Arrr, la pillas!",
  "skin.pharaoh.note": "¡Anda como un egipcio!",
  "skin.spaceman.note": "Un pequeño paso...",
  "skin.wizard.note": "¡Abracadabra, la llevas tú!",
  "skin.centaur.note": "¡Cuatro patas y cero calma, tío!",
  "skin.tennis.note": "¡Derechazo, la llevas, tío!",
  "skin.cobra.note": "¡Sss-úper rápido! ¡Tú la llevas!",

  "credits.bio":
    "Este juego lo ha hecho James, un ingeniero de software que vive en Nueva York (también conocido como Jim, Jimbo, Jimothy y Sir Jims-a-lot).",
  "credits.linkedinLead": "Si os apetece, conectad conmigo en LinkedIn:",
  "credits.githubLead": "Echadle un vistazo al código, haced un fork y dejad una estrella. 😉",

  "mobile.tag": "PILLA",
  "mobile.tagAria": "Pillar",
  "mobile.run": "CORRE",
  "mobile.runAria": "Correr (mantén pulsado)",
  "mobile.joystickAria": "Joystick: arrastra para moverte",

  "lang.choose": "Elegid un idioma",

  "cave.line1": "DOMINA LA PILLA Y",
  "cave.line2": "ESTO SERÁ TUYO.",

  "bsod.aria": "Error: misión no implementada.",
  "bsod.text": `Se ha detectado un problema y James World se ha cerrado para evitar daños
en el ordenador.

Error: misión no implementada.

Si es la primera vez que ves esta pantalla de error,
reinicia el ordenador. Si vuelve a aparecer, sigue
estos pasos:

Comprueba que el hardware o el software nuevo está bien instalado.
Si es una instalación nueva, pide al fabricante
las actualizaciones de James World que hagan falta.

Si el problema continúa, desactiva o quita el hardware
o el software recién instalado. Desactiva opciones de memoria de la BIOS como la caché o el shadowing.
Si necesitas el modo seguro para quitar o desactivar componentes, reinicia
el ordenador, pulsa F8 para elegir las opciones de inicio avanzadas y luego
elige Modo seguro.

Información técnica:

*** STOP: 0x0000007B (0xC0000034, 0x00000000, 0x00000000, 0x00000000)


Pulsa cualquier tecla o toca para continuar `,
};
