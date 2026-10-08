# Tag Game

A server-authoritative multiplayer game of tag built with **Rust, Axum, Tokio, and WebSockets.**

---

# Table of Contents

* [Game Overview](#game-overview)
* [Core Game Rules](#core-game-rules)
* [Server-Authoritative Architecture](#server-authoritative-architecture)
* [Movement](#movement)
* [Energy System](#energy-system)
* [The "It" System](#the-it-system)
* [Tagging](#tagging)
* [Five-Second Tag Protection](#five-second-tag-protection)
* [Disconnects](#disconnects)
* [Networking](#networking)
* [Project Structure](#project-structure)
* [Technology Stack](#technology-stack)
* [System Requirements](#system-requirements)
* [Local Development](#local-development)
* [Building](#building)
* [Production Deployment](#production-deployment)
* [Security and Anti-Cheat](#security-and-anti-cheat)
* [Future Improvements](#future-improvements)

---

# Game Overview

TagGame is a real-time multiplayer game where players move around a shared world and attempt to avoid being tagged.

At any point after at least two players have joined, exactly one player is normally designated as **IT**.

The objective is simple:

* If you are **IT**, catch another player.
* If you are tagged, **you become IT**.
* The previous IT gets a temporary speed boost and cannot immediately be tagged back.
* Players manage an energy meter that controls their ability to run.
* IT has slightly better movement and energy economics, giving them the tools needed to chase other players.

The game should feel like a continuous chase rather than a series of discrete turns.

---

# Core Game Rules

## Joining

When the first player joins:

```text
Player 1
   ↓
No IT yet
```

When the second player joins:

```text
Player 1
Player 2
   ↓
Server randomly selects one player
   ↓
Selected player becomes IT
```

The server performs this selection.

The client does not choose who is IT.

---

# Server-Authoritative Architecture

The most important architectural rule in TagGame is:

> **Clients send intentions. Servers determine results.**

The client should never be trusted to tell the server:

```text
"My position is X=5000, Y=3000."
```

Instead, it sends:

```text
"I want to move northeast."
```

For example:

```json
{
  "type": "MoveInput",
  "data": {
    "seq": 123,
    "dx": 1,
    "dy": -1,
    "running": true
  }
}
```

The server then calculates:

```text
direction
    ↓
energy
    ↓
running state
    ↓
base speed
    ↓
IT modifiers
    ↓
escape boost
    ↓
new position
```

The resulting position is sent back to all clients.

This means the browser is primarily:

```text
Input
  +
Rendering
```

while the server is:

```text
Game Rules
  +
Physics
  +
State
  +
Networking
```

---

# Server vs Client Responsibilities

## Client

The client is responsible for:

* keyboard/controller input
* rendering players
* rendering the map
* rendering energy
* rendering who is IT
* displaying animations
* displaying UI
* sending movement input
* requesting a tag attempt
* interpolating server snapshots for smooth visuals

The client does **not** determine:

* player position
* player speed
* energy
* who is IT
* whether a tag occurred
* tag distance
* tag cooldown
* collision results

---

## Server

The Rust server owns:

* player IDs
* player positions
* player movement
* player energy
* running state
* IT state
* tagging
* tag cooldowns
* escape boosts
* player joining
* player leaving
* game ticks
* snapshots

The server is the authoritative source of truth.

---

# Movement

Players do not send coordinates.

They send a direction:

```text
dx
dy
```

Examples:

```text
Right:

dx = 1
dy = 0
```

```text
Left:

dx = -1
dy = 0
```

```text
Up:

dx = 0
dy = -1
```

```text
Down:

dx = 0
dy = 1
```

Diagonal movement can be represented as:

```text
dx = 1
dy = -1
```

The server normalizes the vector so diagonal movement does not accidentally make the player faster.

For example:

```text
(1, 0)
```

and:

```text
(1, 1)
```

both represent a unit-speed direction after normalization.

The server then applies:

```text
position += direction × speed × delta_time
```

---

# Why Not Send Coordinates?

Sending coordinates would allow a malicious client to send:

```text
x = 100000
y = 100000
```

and potentially teleport.

It would also allow clients to manipulate their speed by sending positions farther apart every update.

Instead:

```text
Client:
"I want to move this direction."

Server:
"Based on your energy, state, and game rules,
this is where you actually moved."
```

This makes cheating substantially more difficult.

---

# Server Tick

The server runs the game at approximately:

```text
30 ticks / second
```

Each tick:

1. Read the latest input for each player.
2. Update energy.
3. Determine running state.
4. Determine movement speed.
5. Apply IT modifiers.
6. Apply escape modifiers.
7. Move the player.
8. Decrease cooldown timers.
9. Produce a world snapshot.
10. Broadcast the snapshot.

Conceptually:

```text
             ┌──────────────┐
             │ Client Input │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Server Tick  │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Energy Logic │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Speed Logic  │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │    Move      │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │   Snapshot   │
             └──────┬───────┘
                    ↓
              All Clients
```

---

# Energy System

Every player starts with:

```text
100 energy
```

Energy ranges from:

```text
0 → 100
```

## Normal Player

### Standing

```text
+25 energy / second
```

### Walking

```text
+5 energy / second
```

### Running

```text
-20 energy / second
```

---

# Running

Running is different from walking.

Base speeds:

```text
Walking: 200
Running: 350
```

However, running speed depends on energy.

At:

```text
50+ energy
```

the player runs at full running speed.

Below 50 energy, running gradually becomes slower.

The running multiplier is:

```text
0.5 + 0.5 × (energy / 50)
```

Therefore:

```text
Energy     Running Speed
--------------------------------
100        350
75         350
50         350
25         262.5
10         210
```

Below 10 energy, running is disabled.

The player can still walk.

This prevents a player from becoming completely immobilized when exhausted.

---

# IT Bonuses

Being IT provides a small advantage because IT must successfully chase another player.

IT receives:

```text
+10% movement speed
```

Energy improvements:

```text
Standing regeneration: 30/sec
Walking regeneration: 7.5/sec
Running drain: 15/sec
```

Compared with a normal player:

```text
                    Normal       IT
---------------------------------------
Standing regen       25          30
Walking regen         5         7.5
Running drain        20          15
Speed multiplier      1.0        1.10
```

The purpose is not to make IT dramatically stronger.

The purpose is to prevent the game from becoming a situation where IT can never catch anyone.

---

# The "IT" System

There is normally exactly one IT player.

The server tracks this using:

```rust
is_it: bool
```

When the second player joins, the server randomly selects one connected player.

For example:

```text
Alice
Bob
```

might become:

```text
Alice = IT
Bob   = normal
```

Or:

```text
Alice = normal
Bob   = IT
```

The decision happens on the server.

---

# Tagging

A client can request a tag:

```json
{
  "type": "TagPlayer",
  "data": {
    "target_id": "..."
  }
}
```

The client is only requesting that the server check whether a tag occurred.

The server verifies:

1. The tagger exists.
2. The target exists.
3. The tagger is IT.
4. The target is not temporarily immune.
5. The players are physically close enough.

Only then does the tag succeed.

The client cannot simply announce:

```text
"I tagged Bob."
```

and have the server accept it.

---

# Tag Distance

The current tag distance is:

```text
50 world units
```

The server compares the squared distance between players:

```text
dx² + dy² <= tag_distance²
```

This avoids an unnecessary square-root operation.

Conceptually:

```text
        Player B
           ●
        ↗
      /  50 units
    /
  ●
Player A
```

If the distance is within the tag radius, the tag succeeds.

---

# What Happens When Someone Is Tagged?

Suppose:

```text
Alice = IT
Bob   = normal
```

Alice tags Bob.

Immediately:

```text
Alice = normal
Bob   = IT
```

The server also gives Alice:

### Five-second tag immunity

Alice cannot immediately be tagged again.

### Five-second escape boost

Alice gets a temporary:

```text
+25% speed
```

boost.

This creates a natural transition:

```text
Alice catches Bob
        ↓
Bob becomes IT
        ↓
Alice gets a burst of speed
        ↓
Alice escapes
        ↓
Bob begins the next chase
```

This prevents the game from becoming:

```text
tag
↓
instant tag-back
↓
tag
↓
instant tag-back
```

---

# Tag Immunity

The player who was previously IT receives:

```text
5 seconds
```

of tag immunity.

The server tracks this in ticks.

At 30 ticks per second:

```text
5 × 30 = 150 ticks
```

So the player receives approximately:

```text
150 ticks of immunity
```

During that period, another player cannot tag them.

---

# Escape Boost

The same player receives a temporary:

```text
+25% movement speed
```

boost for five seconds.

This is intentionally stronger than the permanent IT bonus.

The idea is:

```text
IT catches player
       ↓
player escapes rapidly
       ↓
new IT has to chase them
```

This gives the newly tagged IT time to establish control of the chase.

---

# What If IT Disconnects?

If the current IT player leaves:

```text
IT disconnects
       ↓
Server removes player
       ↓
Server detects there is no IT
```

Server will then randomly select a new player to be IT.

---

## Getting started

Run the project with cargo:
```
cargo run
```

This will install any dependencies (if needed) and start the local webserver at: 0.0.0.0:8000

Check it by sending a GET request to: http://0.0.0.0:8000/health

With nothing configured it listens on every interface, so a phone on the same
Wi-Fi can play against your laptop (the client connects to "same host, port
8000" by default). See [Configuration](#configuration) to change that.

originally built with rustc 1.92.0-nightly (dd7fda570 2025-09-20); builds on
stable Rust (1.85+).

---

# Production Deployment

The game server runs on a DigitalOcean droplet behind
[Caddy](https://caddyserver.com) (automatic HTTPS), as a systemd service. The
browser client is a static site on Netlify (see
[`../phaser-tag-client/README.md`](../phaser-tag-client/README.md#deployment-netlify))
and connects straight to the droplet over a secure WebSocket:

```text
https://jamesworld.example            -> Netlify (the game page)
wss://api.jamesworld.example/ws       -> droplet: Caddy :443 -> 127.0.0.1:8000
```

`jamesworld.example` is a placeholder used throughout: substitute your domain.
One domain with two hostnames is all you need (the API could live on a
different domain, but there's no reason to). The page goes directly to the
droplet because Netlify's rewrites/proxy can't carry WebSockets, and it must be
`wss://` because a page served over `https://` may not open a plain `ws://`
socket.

Files used below live in [`deploy/`](deploy):

| File | Goes to | What it is |
|---|---|---|
| [`deploy/tag26.service`](deploy/tag26.service) | `/etc/systemd/system/tag26.service` | systemd unit: non-root user, env vars, restart on crash |
| [`deploy/Caddyfile`](deploy/Caddyfile) | `/etc/caddy/Caddyfile` | TLS for `api.` + reverse proxy (WebSockets included) |
| [`deploy/deploy.sh`](deploy/deploy.sh) | run from your machine | build, copy, restart, health-check (and `rollback`) |

## Configuration

All settings are environment variables (none are secret):

| Variable | Default | Production value | Meaning |
|---|---|---|---|
| `BIND_ADDR` | `0.0.0.0:8000` | `127.0.0.1:8000` | Address to listen on. `host:port`, or just an IP (then `PORT` is used). |
| `PORT` | `8000` | | Port when `BIND_ADDR` has none. |
| `ALLOWED_ORIGINS` | *(any)* | `https://jamesworld.example,https://www.jamesworld.example` | Comma-separated page origins allowed to open `/ws`; others get `403`. Requests without an `Origin` header (bots, scripts, tests) are always allowed. |
| `RUST_LOG` | `info` | `info` | Log filter ([`tracing` env-filter syntax](https://docs.rs/tracing-subscriber/latest/tracing_subscriber/filter/struct.EnvFilter.html)). |

Behind Caddy, bind to `127.0.0.1` so port 8000 is unreachable from the
internet; everything public goes through Caddy on 443.

On `SIGTERM` or Ctrl-C the server shuts down gracefully: it stops accepting
connections, closes every WebSocket with close code `1012` ("service
restart") so clients reconnect straight away, waits up to 3 seconds for them
to go, and exits 0.

## 1. DNS

At your DNS provider (or DigitalOcean's, if the domain's nameservers point
there), add for the API hostname:

| Type | Name | Value |
|---|---|---|
| `A` | `api` | the droplet's IPv4 address |
| `AAAA` | `api` | the droplet's IPv6 address (only if IPv6 is enabled on the droplet) |

The apex / `www` records point at Netlify; the client README covers those.
Wait until `dig +short api.jamesworld.example` shows the droplet's IP before
starting Caddy, otherwise it can't get a certificate yet (it keeps retrying).

## 2. Prepare the droplet (once)

Ubuntu 24.04 LTS. The smallest droplet runs the game easily; compiling on it
wants 2 GB of RAM, or add swap as below.

```bash
ssh root@api.jamesworld.example

apt update && apt upgrade -y

# Firewall: SSH + HTTP + HTTPS only. Port 8000 stays private (BIND_ADDR=127.0.0.1).
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Unprivileged user the server runs as, and its directory.
useradd --system --no-create-home --shell /usr/sbin/nologin tag26
mkdir -p /opt/tag26

# Caddy, from its official apt repo (https://caddyserver.com/docs/install#debian-ubuntu-raspbian)
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

Only if you'll build on the droplet (the simplest option, below):

```bash
apt install -y build-essential rsync
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y   # installs to ~/.cargo
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

If you use a DigitalOcean Cloud Firewall instead of (or as well as) `ufw`,
give it the same inbound rules: 22, 80, 443.

## 3. Build and install the binary

Pick one:

**A. Build on the droplet** (no cross-compiling; the binary matches the
droplet's libraries):

```bash
# from your machine, in backend/
rsync -az --delete --exclude target/ ./ root@api.jamesworld.example:tag26-src/
ssh root@api.jamesworld.example 'cd tag26-src && ~/.cargo/bin/cargo build --release --locked \
  && install -m 0755 target/release/taggame-backend /opt/tag26/taggame-backend'
```

**B. Build on your machine and copy it.** On Linux x86_64, `cargo build
--release` (build on the same or an older Ubuntu than the droplet, or glibc
may not match). On a Mac (or to avoid glibc questions entirely), build a
static Linux binary with [cargo-zigbuild](https://github.com/rust-cross/cargo-zigbuild):

```bash
brew install zig && cargo install cargo-zigbuild
rustup target add x86_64-unknown-linux-musl
cargo zigbuild --release --target x86_64-unknown-linux-musl
scp target/x86_64-unknown-linux-musl/release/taggame-backend root@api.jamesworld.example:/tmp/
ssh root@api.jamesworld.example 'install -m 0755 /tmp/taggame-backend /opt/tag26/taggame-backend'
```

After the first time, [`deploy/deploy.sh`](deploy/deploy.sh) does either
flavour in one command (see [Redeploying](#redeploying-and-upgrading)).

## 4. systemd service

Edit `ALLOWED_ORIGINS` in [`deploy/tag26.service`](deploy/tag26.service) to
your site's origin(s) (exact `https://host`, no path), then:

```bash
scp deploy/tag26.service root@api.jamesworld.example:/etc/systemd/system/tag26.service
ssh root@api.jamesworld.example 'systemctl daemon-reload && systemctl enable --now tag26 && systemctl status tag26 --no-pager'
```

The unit runs the server as `tag26` with `BIND_ADDR=127.0.0.1:8000` and
`RUST_LOG=info`, restarts it if it ever exits (`Restart=always`), starts it at
boot, and gives it 10s to stop on `SIGTERM` (it needs well under one).

To change a setting later: `systemctl edit tag26` (adds an override, e.g.
`[Service]` / `Environment=RUST_LOG=debug`) or edit the unit, then
`systemctl daemon-reload && systemctl restart tag26`.

## 5. Caddy (HTTPS and wss://)

Replace `api.jamesworld.example` in [`deploy/Caddyfile`](deploy/Caddyfile),
then:

```bash
scp deploy/Caddyfile root@api.jamesworld.example:/etc/caddy/Caddyfile
ssh root@api.jamesworld.example 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy'
```

Caddy obtains and renews the Let's Encrypt certificate on its own (it needs
the DNS record from step 1 and ports 80/443 open), redirects HTTP to HTTPS,
and its `reverse_proxy` passes WebSocket upgrades through without extra
settings. While the game server restarts, it holds new connections for up to
5 seconds (`lb_try_duration`) instead of failing them.

## 6. Check it

```bash
curl https://api.jamesworld.example/health
# {"service":"taggame-backend","status":"ok"}

ssh root@api.jamesworld.example
journalctl -u tag26 -f            # game server logs (live)
journalctl -u caddy -n 50         # certificate / proxy problems
systemctl status tag26
```

For more detail, set `RUST_LOG=debug` (or e.g.
`RUST_LOG=info,taggame_backend=debug`) with `systemctl edit tag26` and
restart. Rejected origins are logged as warnings
(`rejected WebSocket from a disallowed origin`).

Then open the Netlify site: the status panel shows your James name in green
once the socket is up.

**If the game says "Not Connected":** in the browser dev tools (Network ->
WS) check the URL it tries. `ws://` instead of `wss://`, or the wrong host,
means `VITE_WS_URL` wasn't set when Netlify built the site (set it, then
redeploy). A `403` means the page's origin isn't in `ALLOWED_ORIGINS`. A TLS
error means Caddy has no certificate yet (`journalctl -u caddy`).

## Redeploying and upgrading

**The frontend** redeploys on every push to `main` (Netlify builds it). Netlify
deploys are atomic: the new version goes live all at once and nobody is
disconnected. Players pick it up on their next page load.

**The backend** is the interesting one, and the honest answer is: the game
world lives only in this process's memory (positions, who's IT, the
`James N` counter, the bots). Starting a new binary starts a new world, and
everyone connected to the old one is disconnected. Rust has no practical way
to swap code inside a running process, so "upgrading" means "replace the
process"; the choice is how much of that players notice.

### Option 1 (what's set up now): fast restart + auto-reconnect

```bash
DEPLOY_HOST=root@api.jamesworld.example ./deploy/deploy.sh            # build on droplet
BUILD_ON=local DEPLOY_HOST=root@api.jamesworld.example ./deploy/deploy.sh   # build here, scp
DEPLOY_HOST=root@api.jamesworld.example ./deploy/deploy.sh rollback   # back to the previous binary
```

The script builds the new binary (all the slow part happens while the old one
keeps serving), swaps it in (keeping the old one as `taggame-backend.prev`),
runs `systemctl restart tag26`, and waits for `/health`. A non-root
`DEPLOY_HOST` user needs passwordless `sudo`.

What players see: the server closes their sockets with "service restart", the
status turns red "Not Connected" for about a second, and the client
reconnects by itself (retrying after 0.5s, 1s, 2s, 4s, then every 5s for longer
outages). Anyone who had pressed Start joins the new world automatically, in
the same skin, under a fresh `James N`; spectators simply see the new world.
Positions and IT start over. For a casual game of tag, this is usually fine.

### Option 2: blue/green (no gap, but briefly two worlds)

Run the new version next to the old one and move traffic over:

1. Start the new binary on another port, e.g. a second unit with
   `Environment=BIND_ADDR=127.0.0.1:8001` (`tag26-green.service`).
2. Wait for `curl http://127.0.0.1:8001/health`.
3. Point Caddy at it (`reverse_proxy 127.0.0.1:8001`) and `systemctl reload caddy`.
4. Stop the old one; its players reconnect, landing on the new server.

New players go straight to the new server while the old one is still up. Two
caveats: by default Caddy closes proxied WebSockets when its config reloads,
so add `stream_close_delay 10m` inside `reverse_proxy` if you want old
games to keep running until you stop the old server; and until then the two
servers are two separate worlds (players on one can't see the other). Not
worth the complexity for now.

### Option 3 (later): hand the world over

Make restarts nearly invisible by carrying the state across:

- On `SIGTERM`, write the world (players, positions, IT, energy, counter) to
  disk or Redis; on boot, load it if it's fresh (a few seconds old).
- Give each player a resume token in `Welcome`; on reconnect the client sends
  it with `Join`, and the server gives them back their `James N`, position and
  IT status instead of a new player.

Combined with the reconnect that already exists, a deploy would look like a
one-second lag spike.

### Keep old and new talking

Because the frontend and backend deploy separately, there are moments when an
old page talks to a new server (or the reverse). Keep the protocol
backward-compatible:

- Add fields, don't rename or remove them, and give new fields serde defaults
  (`#[serde(default)]`) so messages from older clients still parse.
- Deploy the backend first, then the frontend, when adding a field (the old
  client ignores fields it doesn't know about).
- Never change the meaning of an existing message type; add a new one.

