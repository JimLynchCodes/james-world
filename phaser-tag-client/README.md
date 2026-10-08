# Phaser Tag Client

A minimal fullscreen Phaser client for the Rust WebSocket protocol.

## Features

- Fullscreen Phaser game
- Title screen ("James World"): watch the yard, then hit Start to join
- WASD / arrow-key movement, or Mobile mode (tap where to walk, or a
  virtual joystick with Tag and Run buttons)
- Settings panel (cog, top right): controls mode, volumes, music mood, skin
- Skins: James (default), Banana James, or T-rex James, seen by every player
- Music and sound effects: procedural (Web Audio) plus one CC0 lo-fi loop
- SHIFT to request running
- SPACE to attempt tagging the nearest player
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
# terminal 1: the game server (port 8000)
cd backend && cargo run

# terminal 2: this client
cd phaser-tag-client
npm install
npm run dev
```

Then open the Vite URL, normally:

```text
http://localhost:5173
```

No configuration is needed: with `VITE_WS_URL` unset (the committed `.env`
leaves it commented out) the client connects to the host the page came from,
on port 8000: `ws://localhost:8000/ws` on your machine, or
`ws://192.168.x.y:8000/ws` when a phone on your Wi-Fi opens
`http://192.168.x.y:5173` (start Vite with `npm run dev -- --host` for that).

To point at some other server, put `VITE_WS_URL=ws://host:port/ws` in
`.env.local` (git-ignored; see `.env.example`) and restart Vite.

### Reconnecting

If the socket drops (server restart or deploy, Wi-Fi blip, laptop sleep), the
status panel turns red "Not Connected" and the client reconnects on its own,
retrying after 0.5s, 1s, 2s, 4s, then every 5s. A "service restart" close from
the server (code 1012, sent when it shuts down for a deploy) retries straight
away at 0.5s. If you had pressed Start, it joins again automatically with the
same skin (the server hands out a new `James N`); if you were watching from
the title screen, it just reconnects. Only one socket is ever open, so
retries can't pile up on the server.

## Which player is you

After `Join`, the server sends `Welcome { player_id, name }` to the joining
client only. The client stores `player_id` as `localPlayerId` to tell its own
`PlayerSnapshot` apart from everyone else's, and shows `name` (`James N`). A
reconnect is a new `Join`, so it gets a new `Welcome`.

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
  server sends `PlayerTagged`, and immediately when you press SPACE (or TAG)
- coloured ring under the feet: blue = you, red = IT, purple = bot,
  amber = other human; IT also gets a light red tint
- label stack above the head, top to bottom: **IT** (red, only on the IT
  player), **YOU** (blue, local player only), then the player's name
  (white with a dark stroke). Lines that don't apply collapse; IT keeps a
  4px gap above the line below it so the two don't touch. The labels sort
  with their kid's depth
- names come from the server: every join (humans and bots) bumps a
  server-wide counter and the player is named "James N". The name is in
  `Welcome`, `PlayerJoined` and every `PlayerSnapshot`
- near a world corner the camera stops scrolling, so James can walk under
  a HUD panel, the joystick or the Tag / Run buttons; whichever one covers
  him turns see-through
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

## Settings, Mobile mode and audio

The cog in the top-right corner opens the Settings modal (`src/settings.ts`,
styles in `src/style.css`). Close it with the X, a click on the backdrop,
or Escape. While it is open the game ignores the keyboard (Phaser's key
capture is released so the sliders, dropdown and Tab work) and the local
player stops.

- **Controls**: a Keyboard / Mobile switch. Keyboard is WASD / arrows,
  SHIFT to run, SPACE to tag (Space is captured so it never scrolls the
  page). Mobile mode offers two input styles that work together:
  - **Tap to move**: tapping the ground sets a destination (white marker)
    and the client sends `MoveInput` toward it from the server-reported
    position, stopping within 10px (drag to steer). Tapping a player within
    tag range tags them; tapping one further away walks toward them.
  - **Joystick + buttons** (`src/mobileControls.ts`): a virtual joystick in
    one bottom corner (drag the thumb in any direction; 20% dead zone,
    thumb clamped to the base; letting go stops; steering cancels any tap
    destination) and the **TAG** (blue) and **RUN** (orange, hold) buttons
    side by side in the other corner. Every control tracks its own pointer
    ids, so you can steer and hold RUN / press TAG at the same time. TAG
    does what SPACE does; RUN sets the same `running` flag as SHIFT.
  Touches on the joystick, buttons, HUD, cog or modal never set a tap
  destination. Everything respects phone safe-area insets, and the
  controls hint moves above the joystick.
  With Mobile selected the Controls tab shows two more switches:
  **Lefty Joystick** (Left / Right, default Left: joystick bottom-left,
  TAG + RUN bottom-right; Right swaps the corners) and **Flip Tag / Run**
  (default Off: TAG to the left of RUN; On: RUN to the left of TAG).
  A control mode saved as `tap` by an older build is migrated to `mobile`,
  and an old "Run button side: Left" becomes Lefty Joystick.
- **Default control mode**: auto-detected only while the user hasn't
  picked one: phones / tablets get Mobile, desktops / laptops get Keyboard
  (`isTouchFirstDevice()` in `src/settings.ts`: Client Hints `mobile`,
  mobile UA, iPadOS touch points, coarse primary pointer without hover).
- **Sound**: Master volume, Background music, Sound effects (0-100), and
  a Mood dropdown (Happy, Spooky, Relaxed, Chillin) that picks the music.
- **Skins**: three cards with a live preview of James in each skin: **James** (default),
  **Banana James** (banana costume, squeaky shoes on the SFX bus), and
  **T-rex James** (T-rex onesie, deep scary stomp on the SFX bus). See
  "Skins" below.

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

The top-left status panel (hidden on the title screen) shows a green light
and your "James N" name once you've joined, and a red light with
"Not Connected" if the socket closes or errors. Before Start it would read
"Connected" (green) while spectating, but the panel stays hidden there, as
before.

Pressing **Start** sends `Join`. The server replies with `Welcome` (your id
and "James N" name), the local kid appears, and the overlay dismisses.

Spectators count toward "someone is here" on the server, so bots keep
running even when you're alone on the title screen — the yard never looks
empty. Bots leave only when the last human *and* the last spectator are gone.

## Skins

`src/skins.ts` lists the skins. Each one is a spritesheet with the same
layout as `kid.png` (same columns, rows and animation ranges), so the same
animation code drives every skin. Costume skins may be taller/wider; each
skin carries its own frame size and feet line. Animation keys are
`<texture>-<anim>-<dir>`.

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
- `trex`: `public/assets/kid_trex.png` (120x122 frames, feet on y = 112;
  padded sides hold the long tail, padded top holds the crest and spikes).
  Generated from `kid.png` by `tools/make_trex_skin.py`. Olive onesie with
  a lime belly, dark dorsal spikes, white teeth around a mouth opening
  (face shows through on front/side views; back views are spiked hood +
  tail), claw mittens and booties, and a prominent spiked tail. Footsteps
  use a deep scary stomp on the SFX bus (`trexStep`). Re-run:
  `python3 tools/make_trex_skin.py [--preview /tmp/trex.png]`.

Multiplayer: the client sends its skin in `Join` (`skin`, optional) and
`SetSkin { skin }` when it changes in Settings. The server stores it on the
player and includes it in every `PlayerSnapshot` (and in `PlayerJoined`),
so other clients switch that kid's sheet live, keeping the current
animation. Unknown values become `james`; bots always wear `james`.

## Schoolyard background

`src/schoolyard.ts` draws the world procedurally at startup (no image
assets): grass with subtle patches, a blacktop with basketball courts,
four-square, hopscotch and other painted games, a running track around a
soccer field, a baseball diamond, a wood-chip playground (no paths through
the lawns: grass runs right up to each area), trees, bushes, benches, picnic tables, and a chain-link fence that sits exactly on
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
npm run build      # -> dist/
npm run preview
```

`VITE_WS_URL` is read when `vite build` runs and baked into the bundle, so a
build made for production has the production URL in it:

```bash
VITE_WS_URL=wss://api.jamesworld.example/ws npm run build
```

## Deployment (Netlify)

The client is a static site: `vite build` turns it into `dist/` (an
`index.html`, one hashed JS/CSS bundle, and the files from `public/`), which
Netlify serves from its CDN on your domain. The game server runs separately
on a DigitalOcean droplet; see
[`../backend/README.md`](../backend/README.md#production-deployment).

```text
https://jamesworld.example        -> Netlify (this client)
wss://api.jamesworld.example/ws   -> the droplet (Caddy -> Rust server)
```

(`jamesworld.example` is a placeholder; substitute your domain.) The browser
opens the WebSocket straight to the droplet: Netlify's rewrites/proxy rules
can't carry WebSockets. Because the page is `https://`, the socket must be
`wss://` (browsers block `ws://` from secure pages), which is what Caddy on the
droplet provides.

### One-time setup

1. **Create the site.** In Netlify: *Add new site* -> *Import an existing
   project* -> GitHub -> `tag-26`. Set:

   | Setting | Value |
   |---|---|
   | Base directory | `phaser-tag-client` |
   | Build command | `npm ci && npm run build` *(also set by `netlify.toml`)* |
   | Publish directory | `dist` *(relative to the base directory; also in `netlify.toml`)* |
   | Branch to deploy | `main` |

   [`netlify.toml`](netlify.toml) in this folder supplies the build command,
   publish directory, Node version (22) and cache headers, and wins over the
   UI fields. Only the base directory has to be set in the UI.

2. **Set the server URL.** *Site configuration* -> *Environment variables* ->
   add `VITE_WS_URL` = `wss://api.jamesworld.example/ws`. Variables that exist
   in the environment when `vite build` runs take priority over `.env` files,
   so this beats anything committed. It's baked in at build time: after
   changing it, trigger a new deploy (*Deploys* -> *Trigger deploy*).

3. **Add your domain.** *Domain management* -> *Add a domain* ->
   `jamesworld.example`. Then either move the domain's nameservers to Netlify
   DNS, or at your DNS provider add what Netlify shows (typically an `A`
   record for the apex pointing at Netlify's load balancer and a `CNAME` for
   `www` -> `<your-site>.netlify.app`). Keep the `api` `A`/`AAAA` records
   pointing at the droplet; if Netlify manages DNS, add them there. Netlify
   then provisions the HTTPS certificate on its own (*Domain management* ->
   *HTTPS*). Prefer a subdomain like `play.jamesworld.example` for the game?
   Use that instead; just keep the origin in the backend's `ALLOWED_ORIGINS`
   in sync.

4. **Check it.** Open `https://jamesworld.example`; the status panel shows
   your `James N` in green once it's connected. If it stays red "Not
   Connected", open dev tools -> Network -> WS: a `ws://` URL or the wrong
   host means `VITE_WS_URL` wasn't set for that build; a `403` means the page
   origin is missing from the server's `ALLOWED_ORIGINS`.

### Redeploys

Every push to `main` rebuilds and publishes the site. Netlify deploys are
atomic: the new version goes live in one switch, nobody is disconnected,
and players get it on their next page load. Old deploys stay available for
one-click rollback (*Deploys* -> pick one -> *Publish deploy*). Pull requests
get deploy previews (they use the same `VITE_WS_URL`, so they talk to the real
server; add the `deploy-preview-*--<site>.netlify.app` origin to
`ALLOWED_ORIGINS` if you restrict origins and want previews to connect).

Since the page and the server deploy separately, ship protocol additions to
the backend first, then the client (details in the backend README).

### About `node_modules`

`node_modules/` is committed to this repo, from a Mac, so it holds macOS
builds of the native packages Vite uses (rollup, esbuild) and lacks the Linux
ones Netlify needs. The build command starts with `npm ci`, which deletes it
and installs exactly what `package-lock.json` lists for Linux, so the
committed copy never reaches the build. Follow-up worth doing: remove
`node_modules/` from git (`git rm -r --cached phaser-tag-client/node_modules`
and add it to `.gitignore`); everyone runs `npm install` anyway.

### Headers and caching

`netlify.toml` caches `/assets/*.js` and `/assets/*.css` (Vite's
content-hashed bundles) forever; everything else, including the sprite sheets
in `public/assets/`, revalidates so a deploy shows up on the next reload.
There's no SPA redirect: the game is a single `index.html` with no
client-side routes.
