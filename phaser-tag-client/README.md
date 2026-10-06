# Phaser Tag Client

A minimal fullscreen Phaser client for the Rust WebSocket protocol.

## Features

- Fullscreen Phaser game
- WASD / arrow-key movement
- SHIFT to request running
- E to attempt tagging the nearest player
- Periodic `Ping` messages
- Normalized `dx` / `dy` movement vectors
- Sends `MoveInput` at 20 Hz
- Server-authoritative snapshot reconciliation
- Other players rendered in world coordinates
- Camera follows the local player, keeping them centered
- `is_it` visual state
- Energy bar
- Join / leave handling
- Configurable WebSocket URL and room

## Protocol mapping

The client sends exactly the protocol's JSON shape:

```json
{
  "type": "Join",
  "data": {
    "room_id": "default"
  }
}
```

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

The game uses a 5000 x 5000 world.

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

- walk loop while moving (faster while running), breathing loop when still
- tag (arm reach + small forward lunge) plays once on the tagger when the
  server sends `PlayerTagged`, and immediately when you press E
- coloured ring under the feet: blue = you, red = IT, purple = bot,
  amber = other human; IT also gets a light red tint
- sprites are depth-sorted by y so lower players draw in front

`public/assets/kid.png` (80x100 frames, 22 per row, rows E, SE, S, SW, W,
NW, N, NE; columns idle 0-3, walk 4-11, breathing 12-15, tag 16-21) is
generated from the original presentation sheet `tools/kid_sheet_source.png`:

```bash
python3 tools/slice_kid_sheet.py --preview /tmp/kid_preview.png
```

(needs Python 3 with Pillow and numpy). See the comments at the top of the
script for how the source rows map to directions. The source sheet has no
front-three-quarter frames (its SE/SW rows are side profiles), so SE and SW
are built from the S (front) frames with a small "head turn" warp, mirrored
for SW, so diagonal-down movement shows a kid facing the camera rather than
a profile.

## Schoolyard background

`src/schoolyard.ts` draws the world procedurally at startup (no image
assets): grass with subtle patches, a blacktop with basketball courts,
four-square, hopscotch and other painted games, a running track around a
soccer field, a baseball diamond, a wood-chip playground, sidewalks, trees,
bushes, benches, picnic tables, and a chain-link fence along the world edge
(which is the server's boundary wall). It is decoration only (no
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
