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
