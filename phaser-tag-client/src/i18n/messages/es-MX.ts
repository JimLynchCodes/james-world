import type { Messages } from "./en-US.ts";

/**
 * Mexican Spanish. Base for the other Spanish locales.
 * Tag is "la lleva"; the short label is LLEVA. Tú, not vos.
 */
export const esMX: Messages = {
  "meta.title": "Juego de la lleva",

  "title.kicker": "Bienvenido a",
  "title.heading": "Mundo de James",
  "title.blurb": "¡Corre, juega a la lleva y diviértete!",
  "title.start": "Empezar",
  "title.starting": "Empezando…",

  "hud.connecting": "Conectando…",
  "hud.connected": "Conectado",
  "hud.notConnected": "Sin conexión",
  "hud.playersLabel": "Jugadores:",
  "hud.players.one": "{count} jugador",
  "hud.players.other": "{count} jugadores",
  "hud.energy": "Energía",

  "toast.connectionLost": "Se perdió la conexión, reconectando…",
  "toast.reconnected": "Reconectado como {name}",
  "toast.joinedSelf": "Entraste como {name}",
  "toast.joined": "{name} se unió",
  "toast.left": "{name} se fue",
  "toast.leftUnknown": "Un jugador se fue",
  "toast.serverError": "Error del servidor: {message}",

  "label.you": "TÚ",
  "label.it": "LLEVA",

  "hint.keyboard":
    "<strong>WASD / flechas</strong> para moverte · <strong>MAYÚS</strong> para correr · <strong>ESPACIO</strong> o <strong>T</strong> para tocar",
  "hint.mobile":
    "<strong>Toca</strong> el suelo para caminar o usa la <strong>palanca</strong> · <strong>TOCA</strong> o toca a un jugador cerca · mantén <strong>CORRE</strong> para correr",
  "hint.mobileTouch":
    "<strong>Toca</strong> el suelo para caminar · <strong>doble toque</strong> para correr · <strong>toca a un jugador</strong> cerca para que la lleve",
  "hint.dismiss": "Cerrar el aviso",

  "settings.aria": "Ajustes",
  "settings.title": "Ajustes",
  "settings.close": "Cerrar ajustes",
  "sign.prompt.keyboard": "Pulsa {key} para leer",
  "sign.prompt.mobile": "Toca el letrero para leer",
  "sign.ok": "OK",
  "sign.close": "Cerrar",
  "settings.tab.controls": "Controles",
  "settings.tab.sound": "Sonido",
  "settings.tab.view": "Vista",
  "settings.tab.skins": "Trajes",
  "settings.tab.credits": "Créditos",

  "settings.controls.heading": "Controles",
  "settings.controls.moveWith": "Moverse con",
  "settings.controls.keyboard": "Teclado",
  "settings.controls.mobile": "Celular",
  "settings.controls.flipJoystick": "Invertir palanca",
  "settings.controls.flipTagRun": "Invertir Toca / Corre",
  "settings.controls.off": "No",
  "settings.controls.on": "Sí",
  "settings.controls.hideButtons": "Ocultar botones",
  "settings.controls.phoneHint":
    "¿Juegas en un celular o una tableta? Elige <strong>Celular</strong> para una palanca y botones grandes de TOCA y CORRE.",

  "howto.aria": "Cómo jugar",
  "howto.title": "Cómo jugar",
  "howto.move": "Mover",
  "howto.or": "o",
  "howto.runHold": "Correr (mantén)",
  "howto.tag": "¡Toca!",
  "howto.shift": "Mayús",
  "howto.space": "Espacio",
  "howto.up": "Flecha arriba",
  "howto.down": "Flecha abajo",
  "howto.left": "Flecha izquierda",
  "howto.right": "Flecha derecha",
  "howto.joyWalk": "Palanca, o toca el suelo, para caminar",
  "howto.tagTap": "Toca, o toca a un jugador cerca",
  "howto.holdRun": "Mantén para correr",
  "howto.zoomIn": "Acercar",
  "howto.zoomOut": "Alejar",
  "howto.wheel": "Rueda del mouse para hacer zoom",
  "howto.pinch": "Pellizca para hacer zoom",
  "howto.tapWalk": "Toca el suelo para caminar",
  "howto.doubleRun": "Doble toque para correr",
  "howto.tapPlayer": "Toca a un jugador para que la lleve",
  "howto.helpMobile": "Arrastra en el suelo para dirigir. ¡Combina como quieras! Ideal para celulares y tabletas.",
  "howto.helpTouch": "Si está lejos, caminas hacia él.",
  "howto.helpKeyboard": "Toca a alguien cerca para que la lleve.",

  "settings.sound.heading": "Sonido",
  "settings.sound.master": "Volumen general",
  "settings.sound.music": "Música de fondo",
  "settings.sound.sfx": "Efectos de sonido",
  "settings.sound.mood": "Ambiente",
  "settings.sound.moodHelp": "El ambiente elige la música de fondo.",

  "settings.view.heading": "Vista",
  "settings.view.zoom": "Zoom",
  "settings.view.out": "Alejar",
  "settings.view.in": "Acercar",
  "settings.view.help": "El centro (0) es el zoom normal. Alejar muestra más del mapa; acercar te pone más cerca.",
  "settings.view.input": "Alt + ↑ o W acerca. Alt + ↓ o S aleja. Alt + la rueda del mouse acerca y aleja. Pellizca con dos dedos.",

  "mood.happy": "Feliz",
  "mood.happy.blurb": "Chiptune con brinco",
  "mood.spooky": "Espeluznante",
  "mood.spooky.blurb": "Campanas de miedo y un latido",
  "mood.relaxed": "Relajado",
  "mood.relaxed.blurb": "Teclas lo-fi suaves",
  "mood.chillin": "Tranqui",
  "mood.chillin.blurb": "Loop de lo-fi hip hop",

  "settings.skins.heading": "Trajes",
  "settings.skins.help": "El mismo héroe, otro flow.",
  "settings.skins.aria": "Traje",

  "skin.james": "James",
  "skin.james.note": "El James de siempre",
  "skin.banana": "James plátano",
  "skin.banana.note": "¡A lamer y a correr!",
  "skin.trex": "James dino",
  "skin.trex.note": "¡T-Rex la lleva!",
  "skin.tuxedo": "James de esmoquin",
  "skin.tuxedo.note": "¡De gala para impresionar!",
  "skin.pirate": "James pirata",
  "skin.pirate.note": "¡Arrr, la llevas!",
  "skin.pharaoh": "James faraón",
  "skin.pharaoh.note": "¡Camina como egipcio!",
  "skin.spaceman": "James astronauta",
  "skin.spaceman.note": "Un pequeño paso...",
  "skin.wizard": "James Mago",
  "skin.wizard.note": "¡Abracadabra, la traes!",
  "skin.centaur": "James Centauro",
  "skin.centaur.note": "¡Cuatro patas y cero calma!",
  "skin.tennis": "James Tenista",
  "skin.tennis.note": "¡Derechazo, la traes!",
  "skin.cobra": "James Cobra",
  "skin.cobra.note": "¡Sss-úper rápido! ¡Te toca!",
  "skin.billy": "Billy",
  "skin.billy.note": "Amigo de James",
  "skin.boxer": "James Boxeador",
  "skin.boxer.note": "Flota como mariposa, etiqueta como abeja.",

  "settings.credits.heading": "Créditos",
  "credits.bio":
    "Este juego lo hizo James, un ingeniero de software que vive en la Ciudad de Nueva York (también conocido como Jim, Jimbo, Jimothy y Sir Jims-a-lot).",
  "credits.linkedinLead": "Si quieres, conéctate conmigo en LinkedIn:",
  "credits.githubLead": "Échale un ojo al código de este juego, hazle un fork y ponle una estrella. 😉",
  "credits.newTab": "Se abre en una pestaña nueva.",
  "credits.photoAlt": "James",

  "mobile.tag": "TOCA",
  "mobile.tagAria": "Tocar",
  "mobile.run": "CORRE",
  "mobile.runAria": "Correr (mantén)",
  "mobile.joystickAria": "Palanca: arrastra para moverte",

  "lang.choose": "Elige un idioma",

  "cave.line1": "DOMINA LA LLEVA Y",
  "cave.line2": "ESTO SERÁ TUYO.",

  "bsod.aria": "Error: misión no implementada.",
  "bsod.text": `Se detectó un problema y James World se cerró para evitar daños
en tu computadora.

Error: misión no implementada.

Si es la primera vez que ves esta pantalla de error,
reinicia tu computadora. Si vuelve a aparecer, sigue
estos pasos:

Revisa que el hardware o software nuevo esté bien instalado.
Si es una instalación nueva, pídele al fabricante
las actualizaciones de James World que hagan falta.

Si el problema sigue, desactiva o quita el hardware
o software recién instalado. Desactiva opciones de memoria del BIOS como la caché o el shadowing.
Si necesitas el modo seguro para quitar o desactivar componentes, reinicia
tu computadora, pulsa F8 para elegir las opciones de inicio avanzadas y luego
elige Modo seguro.

Información técnica:

*** STOP: 0x0000007B (0xC0000034, 0x00000000, 0x00000000, 0x00000000)


Pulsa cualquier tecla o toca para continuar `,
};
