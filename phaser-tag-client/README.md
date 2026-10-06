# Phaser Tag Client

A minimal fullscreen Phaser client for the Rust WebSocket protocol.

## Features

- Fullscreen Phaser game
- Title screen ("James World"): watch the yard, then hit Start to join
- WASD / arrow-key movement, or Tap mode (tap/click where to walk)
- Settings panel (cog, top right): controls mode, volumes, music mood, skin
- Skins: James (default) or Banana James, seen by every player
- Music and sound effects: procedural (Web Audio) plus one CC0 lo-fi loop
- SHIFT to request running
- E to attempt tagging the nearest player
- Periodic `Ping` messages
- Normalized `dx` / `dy` movement vectors
- Sends `MoveInput` at 20 Hz
- Server-authoritative snapshot reconciliation
- Other players rendered in world coordinates
- Camera follows the local player, keeping them centered
- `is_it` visual state
- Server-assigned player names ("James 1", "James 2", ...) and a label
  stack above every head: IT / YOU / name
- Energy bar
- Join / leave handling (the event feed uses player names)
- Configurable WebSocket URL and room

## Protocol mapping

The client sends exactly the protocol's JSON shape:

```json
{
  "type": "Join",
  "data": {
    "room_id": "default",
    "skin": "banana"
  }
}
```

Changing skin mid-game: `{"type": "SetSkin", "data": {"skin": "james"}}`.

Movement:

```json
{
  "type": "MoveInput",
  "data": {
    "seq": 42,
    "dx": 0.7071,
    "dy": -0.7071,
    "running": true
  }
}
```

The important part is that the client sends a direction vector rather
than an x/y position. The Rust server remains responsible for deciding
where the player actually is.

## Local development

```bash
npm install
cp .env.example .env
npm run dev
```

Then open the Vite URL, normally:

```text
http://localhost:5173
```

Set the Rust WebSocket endpoint in `.env`:

```text
VITE_WS_URL=ws://localhost:3000/ws
```

## Important protocol limitation

The supplied protocol does not contain a message that tells the client
which UUID belongs to the local player.

For a multiplayer game, the recommended protocol addition is:

```rust
Joined {
    player_id: Uuid,
}
```

sent only to the newly connected client.

Then the browser can set:

```ts
this.localPlayerId = message.data.player_id;
```

Without that, the browser cannot reliably distinguish its own
`PlayerSnapshot` from another player's snapshot.

As a temporary development workaround, set:

```text
VITE_PLAYER_ID=<uuid>
```

in `.env`.

## Suggested next server-side addition

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ServerMessage {
    Joined {
        player_id: Uuid,
    },

    Snapshot {
        players: Vec<PlayerSnapshot>,
    },

    PlayerJoined {
        player_id: Uuid,
    },

    PlayerLeft {
        player_id: Uuid,
    },

    PlayerTagged {
        tagger_id: Uuid,
        target_id: Uuid,
    },

    Pong {
        timestamp: u64,
    },

    Error {
        message: String,
    },
}
```

This is a small change but makes the protocol unambiguous.

## Coordinate model

The game uses a 5000 x 5000 world. The play area is fenced in by wall
insets (`WALL_LEFT/RIGHT/BOTTOM = 40`, `WALL_TOP = 110`): the server clamps
player centres to `[wall + PLAYER_RADIUS, size - wall - PLAYER_RADIUS]`.
The top inset is larger so the label stack above a kid at the top wall
stays on screen (the camera cannot scroll above y = 0). The constants live
in `src/world.ts` and mirror `backend/src/game/world.rs`;
`backend/tests/bounds.rs` parses `src/world.ts` and fails if they drift.

The local player is drawn as a kid sprite (see "Character sprites")
at their authoritative world coordinate. Phaser's camera follows that object, so the player
stays approximately in the center of the viewport while the world
moves underneath them.

Remote players use their server snapshot coordinates and are
interpolated toward the latest snapshot to reduce visible network
jitter.

## Character sprites

Every player (you, other humans and bots) is an 8-direction kid sprite
(`src/kid.ts`). The direction comes from the facing angle (`atan2(dy, dx)`,
0 = east, +PI/2 = south): your own input for the local player, `facing`
from the snapshot for everyone else.

- walk loop while moving, a separate run loop while running (SHIFT locally,
  `is_running` for others: bigger strides, much bigger arm swing, lean and
  hop), a calm breathing idle as soon as you stop
- local "moving" comes from the keys held right now; remote players count
  as moving while their snapshot position changes (with a short grace time)
- tag (arm reach + small forward lunge) plays once on the tagger when the
  server sends `PlayerTagged`, and immediately when you press E
- coloured ring under the feet: blue = you, red = IT, purple = bot,
  amber = other human; IT also gets a light red tint
- label stack above the head, top to bottom: **IT** (red, only on the IT
  player), **YOU** (blue, local player only), then the player's name
  (white with a dark stroke). Lines that don't apply collapse with no gap,
  and the labels draw above all sprites
- names come from the server: every join (humans and bots) bumps a
  server-wide counter and the player is named "James N". The name is in
  `Welcome`, `PlayerJoined` and every `PlayerSnapshot`
- near a world corner the camera stops scrolling, so the local kid can walk
  under a HUD panel; whichever panel covers the kid turns see-through
- sprites are depth-sorted by y so lower players draw in front
- trees, bushes and the fence share that depth sort: a kid whose feet are
  north of a trunk/post sorts behind it, and the foliage goes translucent
  (~50% alpha) so you can still see them and their labels

`public/assets/kid.png` (80x100 frames, 30 per row, rows E, SE, S, SW, W,
NW, N, NE; columns idle 0-3, walk 4-11, breathing 12-15, tag 16-21,
run 22-29) is generated from the original presentation sheet
`tools/kid_sheet_source.png`:

```bash
python3 tools/slice_kid_sheet.py --preview /tmp/kid_preview.png
```

(needs Python 3 with Pillow and numpy). See the comments at the top of the
script for how the source rows map to directions. The source sheet has no
front-three-quarter frames (its SE/SW rows are side profiles), so SE and SW
are built from the S (front) frames with a small "head turn" warp, mirrored
for SW, so diagonal-down movement shows a kid facing the camera rather than
a profile.

Some animation is generated rather than sliced, because the sheet doesn't
have it (see the "Procedural animation" comments in the script):

- idle/breathing: one standing frame per direction with a 1px chest rise
  (the sheet's "breathing" frames shift stance from frame to frame, so the
  idle looked like walking on the spot);
- front walk (S, and SE/SW derived from it): the standing frame is cut into
  legs and arms that are re-posed per frame (alternating lifted/forward
  foot, arms swinging opposite, 1px bob) because the sheet's S walk frames
  barely differ;
- run, all directions: the same front/back generator with bigger amplitudes
  for S/SE/SW/N, and an exaggerated version of the sheet's side/back-3/4
  stride frames (wider stride, ~2.4x arm swing, lean, hop) for E/W/NE/NW.

Kids are drawn at 0.84 scale (~75px tall on screen); the ground ring,
feet offset and tag lunge grow with them. Display only: the server
collision radius (`PLAYER_RADIUS` = 18) is unchanged.

## Settings, Tap mode and audio

The cog in the top-right corner opens the Settings modal (`src/settings.ts`,
styles in `src/style.css`). Close it with the X, a click on the backdrop,
or Escape. While it is open the game ignores the keyboard (Phaser's key
capture is released so the sliders, dropdown and Tab work) and the local
player stops.

- **Controls**: a Keyboard / Tap switch. Keyboard is WASD / arrows + SHIFT
  + E. In Tap mode, tapping or clicking the ground sets a destination
  (white marker) and the client sends `MoveInput` toward it from the
  server-reported position, stopping within 10px (drag to steer). Tapping
  a kid within tag range tags them, tapping one further away walks toward
  them. Clicks on the HUD, cog, Run button or modal are ignored.
- **Run button** (Tap mode only): a big hold-to-run button in the bottom
  corner (respects phone safe-area insets). It's held while any pointer is
  down on it, so one thumb can hold RUN while the other taps / drags to
  steer (multi-touch; Phaser tracks 3 pointers). It sets the same
  `running` flag in `MoveInput` as SHIFT and never sets a destination.
  With Tap selected the Controls tab shows a **Run button side** switch
  (Left / Right, default Right). The controls hint moves so it doesn't
  sit under the button.
- **Default control mode**: auto-detected only while the user hasn't
  picked one: phones / tablets get Tap, desktops / laptops get Keyboard
  (`isTouchFirstDevice()` in `src/settings.ts`: Client Hints `mobile`,
  mobile UA, iPadOS touch points, coarse primary pointer without hover).
- **Sound**: Master volume, Background music, Sound effects (0-100), and
  a Mood dropdown (Happy, Spooky, Relaxed, Chillin) that picks the music.
- **Skins**: two cards with a live preview of each kid: **James** (default)
  and **Banana James** (the same kid in a banana costume, with squeaky
  costume shoes: a squishy "boing" footstep on the SFX bus instead of the
  normal step). See "Skins" below.

Only settings the user has actually chosen are saved in `localStorage`
(`tag26.settings`), and they are applied on load. Invalid or unknown saved
values fall back to the defaults. A `chillin` mood saved before Relaxed
existed simply stays Chillin.

`src/audio.ts` plays four looping tracks.

- Three are synthesised with the Web Audio API by a small look-ahead step
  sequencer:
  - Happy: bouncy C-major chiptune, 132 bpm.
  - Spooky: slow minor / diminished pads, drone, heartbeat, music-box bells
    and a theremin wail, 70 bpm.
  - Relaxed: swung lo-fi 7th chords, soft drums and vinyl crackle, 76 bpm.
- Chillin is a CC0 recording, "Lofi Hip Hop Loop" by omfgdude
  (`public/audio/`, see `public/audio/CREDITS.md`). It's fetched the first
  time it's selected (Ogg Vorbis, or MP3 where Ogg isn't supported),
  decoded into an AudioBuffer and looped. It goes through the same
  per-track gain and music bus, so the sliders and the crossfade work the
  same way.

Changing the mood crossfades over 1.5s. Effects (tag whoosh / hit, player
joined / left blips, footsteps, UI clicks) go to their own bus:
`track -> music bus -> master`, `sfx -> sfx bus -> master`, then a gentle
limiter. The AudioContext is only created/resumed on the first click, tap
or key press (autoplay policy) and is suspended while the tab is hidden.

## Title screen

On load the client connects as a **spectator**: it receives `Hello`, then
snapshots of whoever is already playing, but does not send `Join` and does
not spawn a local kid. The title overlay ("James World" / Start) sits on top;
the settings cog stays available so you can pick a skin first.

Pressing **Start** sends `Join`. The server replies with `Welcome` (your id
and "James N" name), the local kid appears, and the overlay dismisses.

Spectators count toward "someone is here" on the server, so bots keep
running even when you're alone on the title screen — the yard never looks
empty. Bots leave only when the last human *and* the last spectator are gone.

## Skins

`src/skins.ts` lists the skins. Each one is a spritesheet with the same
layout as `kid.png` (same columns, rows and animation ranges), so the same
animation code drives both. Animation keys are `<texture>-<anim>-<dir>`.

- `james`: `public/assets/kid.png` (80x100 frames).
- `banana`: `public/assets/kid_banana.png` (80x120 frames, feet on y = 116;
  the extra 20px on top hold the banana tip and stem). It is generated
  from `kid.png` by `tools/make_banana_skin.py`, so every animation and
  direction keeps the kid's own motion. The tool turns the outfit black
  (long sleeves, leggings; hands, face and shoes stay), draws a shaded
  yellow banana tube from a pointed tip with a brown stem above the head
  down to the knees (brown end), cuts an oval opening for the face in the
  front and side views (back views are all banana), and puts the arms
  back on top. Re-run it after regenerating `kid.png`:
  `python3 tools/make_banana_skin.py [--preview /tmp/banana.png]`.

Multiplayer: the client sends its skin in `Join` (`skin`, optional) and
`SetSkin { skin }` when it changes in Settings. The server stores it on the
player and includes it in every `PlayerSnapshot` (and in `PlayerJoined`),
so other clients switch that kid's sheet live, keeping the current
animation. Unknown values become `james`; bots always wear `james`.

## Schoolyard background

`src/schoolyard.ts` draws the world procedurally at startup (no image
assets): grass with subtle patches, a blacktop with basketball courts,
four-square, hopscotch and other painted games, a running track around a
soccer field, a baseball diamond, a wood-chip playground, sidewalks, trees,
bushes, benches, picnic tables, and a chain-link fence that sits exactly on
the server's walls (see "Coordinate model"), with a street and sidewalk
outside the top fence. It is decoration only (no
collision). For performance everything is baked once into canvas textures:
the grass layers are camera-sized TileSprites that follow the view, each
area is a single image, and props reuse a few small textures. The layout is
seeded, so every client sees the same yard.

## Security / authority

The browser never sends:

```text
x
y
```

It only sends:

```text
dx
dy
running
seq
```

The server should validate:

- `dx` and `dy` are finite
- the vector is zero or approximately normalized
- movement speed
- energy consumption
- whether running is allowed
- sequence ordering
- world boundaries
- tag distance / cooldown
- `target_id`

The client-side movement is prediction only. Snapshots from the server
reconcile the displayed position.

## Build

```bash
npm run build
npm run preview
```
