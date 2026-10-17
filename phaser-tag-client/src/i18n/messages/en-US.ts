/** American English. Every other locale has these keys, or inherits them. */
export const enUS = {
  "meta.title": "Tag Game",

  "title.kicker": "Welcome to",
  "title.heading": "James World",
  "title.blurb": "Run around, play tag, and have fun!",
  "title.start": "Start",
  "title.starting": "Starting…",

  "hud.connecting": "Connecting…",
  "hud.connected": "Connected",
  "hud.notConnected": "Not Connected",
  "hud.playersLabel": "Players:",
  "hud.players.one": "{count} player",
  "hud.players.other": "{count} players",
  "hud.energy": "Energy",

  "toast.connectionLost": "Connection lost, reconnecting…",
  "toast.reconnected": "Reconnected as {name}",
  "toast.joinedSelf": "You joined as {name}",
  "toast.joined": "{name} joined",
  "toast.left": "{name} left",
  "toast.leftUnknown": "A player left",
  "toast.serverError": "Server error: {message}",

  "label.you": "YOU",
  "label.it": "IT",

  "hint.keyboard":
    "<strong>WASD / Arrow Keys</strong> move · <strong>SHIFT</strong> run · <strong>SPACE</strong> or <strong>T</strong> tag",
  "hint.mobile":
    "<strong>Tap</strong> the ground to walk or use the <strong>joystick</strong> · <strong>TAG</strong> or tap a nearby player to tag · hold <strong>RUN</strong> to run",

  "settings.aria": "Settings",
  "settings.title": "Settings",
  "settings.close": "Close settings",
  "settings.tab.controls": "Controls",
  "settings.tab.sound": "Sound",
  "settings.tab.skins": "Skins",
  "settings.tab.credits": "Credits",

  "settings.controls.heading": "Controls",
  "settings.controls.moveWith": "Move with",
  "settings.controls.keyboard": "Keyboard",
  "settings.controls.mobile": "Mobile",
  "settings.controls.flipJoystick": "Flip Joystick",
  "settings.controls.flipTagRun": "Flip Tag / Run",
  "settings.controls.off": "Off",
  "settings.controls.on": "On",
  "settings.controls.phoneHint":
    "Playing on a phone or tablet? Pick <strong>Mobile</strong> for a joystick and big TAG and RUN buttons.",

  "howto.aria": "How to play",
  "howto.title": "How to play",
  "howto.move": "Move",
  "howto.or": "or",
  "howto.runHold": "Run (hold)",
  "howto.tag": "Tag!",
  "howto.shift": "Shift",
  "howto.space": "Space",
  "howto.up": "Up arrow",
  "howto.down": "Down arrow",
  "howto.left": "Left arrow",
  "howto.right": "Right arrow",
  "howto.joyWalk": "Joystick, or tap the ground, to walk",
  "howto.tagTap": "Tag, or tap a nearby player",
  "howto.holdRun": "Hold to run",
  "howto.helpMobile": "Drag on the ground to steer. Mix and match! Great for phones and tablets.",
  "howto.helpKeyboard": "Tag someone nearby to make them it.",

  "settings.sound.heading": "Sound",
  "settings.sound.master": "Master volume",
  "settings.sound.music": "Background music",
  "settings.sound.sfx": "Sound effects",
  "settings.sound.mood": "Mood",
  "settings.sound.moodHelp": "The mood picks the background music.",

  "mood.happy": "Happy",
  "mood.happy.blurb": "Bouncy chiptune",
  "mood.spooky": "Spooky",
  "mood.spooky.blurb": "Creepy bells and a heartbeat",
  "mood.relaxed": "Relaxed",
  "mood.relaxed.blurb": "Mellow lo-fi keys",
  "mood.chillin": "Chillin",
  "mood.chillin.blurb": "Lo-fi hip hop loop",

  "settings.skins.heading": "Skins",
  "settings.skins.help": "Same hero, different drip.",
  "settings.skins.aria": "Skin",

  "skin.james": "James",
  "skin.james.note": "Regular James",
  "skin.banana": "Banana James",
  "skin.banana.note": "Lickity Split!",
  "skin.trex": "Dino James",
  "skin.trex.note": "T-Rex Tag!",
  "skin.tuxedo": "Tuxedo James",
  "skin.tuxedo.note": "Dressed To Impress!",
  "skin.pirate": "Pirate James",
  "skin.pirate.note": "Arrr, You're It!",
  "skin.pharaoh": "Pharaoh James",
  "skin.pharaoh.note": "Walk Like An Egyptian!",
  "skin.basketball": "Basketball James",
  "skin.basketball.note": "Nothing But Net!",

  "settings.credits.heading": "Credits",
  "credits.bio":
    "This game was made by James, a software engineer living in New York City (also known by many other names such as Jim, Jimbo, Jimothy, and Sir Jims-a-lot).",
  "credits.linkedinLead": "Feel free to connect with me on LinkedIn:",
  "credits.githubLead": "Take a peek at the source code for this game, fork it, and give it a star! 😉",
  "credits.newTab": "Opens in a new tab.",
  "credits.photoAlt": "James",

  "mobile.tag": "TAG",
  "mobile.tagAria": "Tag",
  "mobile.run": "RUN",
  "mobile.runAria": "Run (hold)",
  "mobile.joystickAria": "Joystick: drag to move",

  "lang.choose": "Choose a language",

  "cave.line1": "MASTER USING IT AND",
  "cave.line2": "YOU CAN HAVE THIS.",

  "bsod.aria": "Error: Quest Not Implemented.",
  "bsod.text": `A problem has been detected and James World has been shut down to prevent damage
to your computer.

Error: Quest Not Implemented.

If this is the first time you've seen this Stop error screen,
restart your computer. If this screen appears again, follow
these steps:

Check to make sure any new hardware or software is properly installed.
If this is a new installation, ask your hardware or software manufacturer
for any James World updates you might need.

If problems continue, disable or remove any newly installed hardware
or software. Disable BIOS memory options such as caching or shadowing.
If you need to use Safe Mode to remove or disable components, restart
your computer, press F8 to select Advanced Startup Options, and then
select Safe Mode.

Technical information:

*** STOP: 0x0000007B (0xC0000034, 0x00000000, 0x00000000, 0x00000000)


Press any key or tap to continue `,
} as const;

export type MessageKey = keyof typeof enUS;
export type Messages = { [K in MessageKey]: string };
