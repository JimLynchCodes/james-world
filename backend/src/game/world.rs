use std::collections::HashMap;

use rand::{seq::IteratorRandom, Rng};
use uuid::Uuid;

use super::{
    bot::{self, BotBrain, BOT_COUNT},
    energy,
    movement,
    player::Player,
    skin::Skin,
};

pub const TICK_RATE: u32 = 30;
pub const WORLD_WIDTH: f32 = 5000.0;
pub const WORLD_HEIGHT: f32 = 5000.0;
pub const PLAYER_RADIUS: f32 = 18.0;

// The fence (the wall players can't cross) is inset from the world edges so
// a kid standing against it still has its sprite and the whole label stack
// (IT / YOU / name, drawn above the head) on screen: the camera can't
// scroll past the world edge, and labels extend ~130px above a player's
// centre. The top inset is the big one; the sides leave room for a name
// label wider than the player. Players' collision circles stay inside
// [WALL_LEFT, WORLD_WIDTH - WALL_RIGHT] x [WALL_TOP, WORLD_HEIGHT - WALL_BOTTOM].
//
// Mirrored in phaser-tag-client/src/world.ts (checked by tests/bounds.rs).
pub const WALL_LEFT: f32 = 40.0;
pub const WALL_RIGHT: f32 = 40.0;
pub const WALL_TOP: f32 = 110.0;
pub const WALL_BOTTOM: f32 = 40.0;

/// Range of player centre positions allowed by the fence.
pub const MIN_X: f32 = WALL_LEFT + PLAYER_RADIUS;
pub const MAX_X: f32 = WORLD_WIDTH - WALL_RIGHT - PLAYER_RADIUS;
pub const MIN_Y: f32 = WALL_TOP + PLAYER_RADIUS;
pub const MAX_Y: f32 = WORLD_HEIGHT - WALL_BOTTOM - PLAYER_RADIUS;

/// Everybody in James world is called James; the number is a server-wide
/// join counter (humans and bots), so names are "James 1", "James 2", ...
pub const PLAYER_FIRST_NAME: &str = "James";
pub const TAG_COOLDOWN_SECONDS: f32 = 5.0;

/// Where humans join (kept clear of props by the client's schoolyard).
pub const SPAWN: (f32, f32) = (400.0, 300.0);
/// Joining humans are placed at least this far from every other player, so
/// sprites and label stacks never start on top of each other.
pub const SPAWN_GAP: f32 = 110.0;

#[derive(Debug, Clone, Copy)]
pub struct PlayerInput {
    pub seq: u64,
    pub dx: f32,
    pub dy: f32,
    pub running: bool,
}

impl Default for PlayerInput {
    fn default() -> Self {
        Self {
            seq: 0,
            dx: 0.0,
            dy: 0.0,
            running: false,
        }
    }
}

pub struct World {
    pub players: HashMap<Uuid, Player>,
    pub inputs: HashMap<Uuid, PlayerInput>,
    pub bots: HashMap<Uuid, BotBrain>,
    tag_events: Vec<(Uuid, Uuid)>,
    /// Players (humans and bots) that have joined so far; names use it.
    joins: u64,
    /// Connected sockets that have not (yet) sent Join. They keep bots
    /// alive so the title screen isn't empty when you're alone.
    spectators: u32,
}

impl World {
    pub fn new() -> Self {
        Self {
            players: HashMap::new(),
            inputs: HashMap::new(),
            bots: HashMap::new(),
            tag_events: Vec::new(),
            joins: 0,
            spectators: 0,
        }
    }

    /// Next player name: "James <n>", n counting every join from 1.
    fn next_name(&mut self) -> String {
        self.joins += 1;
        format!("{PLAYER_FIRST_NAME} {}", self.joins)
    }

    /// Display name of a player ("" if unknown).
    pub fn name_of(&self, id: &Uuid) -> String {
        self.players
            .get(id)
            .map(|p| p.name.clone())
            .unwrap_or_default()
    }

    /// Skin of a player (the default if unknown).
    pub fn skin_of(&self, id: &Uuid) -> Skin {
        self.players
            .get(id)
            .map(|p| p.skin)
            .unwrap_or_default()
    }

    /// Change a player's skin. Returns false if there is no such player.
    pub fn set_skin(&mut self, id: Uuid, skin: Skin) -> bool {
        match self.players.get_mut(&id) {
            Some(player) => {
                player.skin = skin;
                true
            }
            None => false,
        }
    }

    pub fn human_count(&self) -> usize {
        self.players
            .values()
            .filter(|p| !p.is_bot)
            .count()
    }

    /// True while anyone is watching or playing (bots stay for both).
    pub fn has_presence(&self) -> bool {
        self.human_count() > 0 || self.spectators > 0
    }

    pub fn spectator_count(&self) -> u32 {
        self.spectators
    }

    /// A title-screen connection opened. May spawn bots so the yard isn't empty.
    pub fn add_spectator(&mut self) -> Vec<Uuid> {
        self.spectators += 1;
        let spawned = self.spawn_missing_bots();
        self.assign_it_if_needed();
        spawned
    }

    /// A spectator disconnected without joining. Bots leave if nobody is left.
    pub fn remove_spectator(&mut self) -> Vec<Uuid> {
        self.spectators = self.spectators.saturating_sub(1);
        self.despawn_bots_if_empty()
    }

    /// Spectator is about to Join: free the seat (presence continues via the human).
    pub fn release_spectator_seat(&mut self) {
        self.spectators = self.spectators.saturating_sub(1);
    }

    /// Adds a human player. Returns the ids of any bots that were spawned
    /// because of this join. No-op (empty vec) if this id is already a player.
    pub fn add_player(
        &mut self,
        id: Uuid,
    ) -> Vec<Uuid> {
        if self.players.contains_key(&id) {
            return Vec::new();
        }
        let (x, y) = self.human_spawn_spot();
        let mut player = Player::new(id, x, y);
        player.name = self.next_name();

        self.players.insert(id, player);

        self.inputs.insert(
            id,
            PlayerInput::default(),
        );

        let spawned = self.spawn_missing_bots();

        self.assign_it_if_needed();

        spawned
    }

    /// Where a joining human appears: the spawn point (the clearing the
    /// client keeps free of props), or the nearest free spot beside it.
    /// Two kids on the exact same spot draw their sprites and label stacks
    /// (IT / YOU / name) on top of each other, and nobody moves you apart
    /// (players don't collide), so never stack a new player on anyone.
    pub fn human_spawn_spot(&self) -> (f32, f32) {
        let free = |x: f32, y: f32| {
            self.players.values().all(|p| {
                let dx = p.position.x - x;
                let dy = p.position.y - y;
                dx * dx + dy * dy >= SPAWN_GAP * SPAWN_GAP
            })
        };
        // Rows of spots fanning out sideways from the spawn point, then
        // further down the yard; clamped inside the fence.
        for row in 0..12 {
            for k in 0..12 {
                let side = if k % 2 == 0 { 1.0 } else { -1.0 };
                let dx = side * ((k + 1) / 2) as f32 * SPAWN_GAP;
                let x = (SPAWN.0 + dx).clamp(MIN_X, MAX_X);
                let y = (SPAWN.1 + row as f32 * SPAWN_GAP).clamp(MIN_Y, MAX_Y);
                if free(x, y) {
                    return (x, y);
                }
            }
        }
        SPAWN
    }

    fn spawn_missing_bots(&mut self) -> Vec<Uuid> {
        let mut spawned = Vec::new();

        if !self.has_presence() {
            return spawned;
        }

        let mut rng = rand::rng();

        while self.bots.len() < BOT_COUNT {
            let humans = self
                .players
                .values()
                .filter(|p| !p.is_bot)
                .map(|p| p.position)
                .collect::<Vec<_>>();

            // Spawn well away from humans so a join isn't an instant tag.
            let mut spot = (0.0, 0.0);
            for _ in 0..16 {
                spot = (
                    rng.random_range(200.0..WORLD_WIDTH - 200.0),
                    rng.random_range(200.0..WORLD_HEIGHT - 200.0),
                );

                let far_enough = humans.iter().all(|h| {
                    let dx = h.x - spot.0;
                    let dy = h.y - spot.1;
                    dx * dx + dy * dy > 800.0 * 800.0
                });

                if far_enough {
                    break;
                }
            }

            let id = Uuid::new_v4();
            let mut bot_player = Player::new(id, spot.0, spot.1);
            bot_player.is_bot = true;
            bot_player.name = self.next_name();

            self.players.insert(id, bot_player);
            self.inputs.insert(id, PlayerInput::default());
            self.bots.insert(id, BotBrain::default());
            spawned.push(id);
        }

        spawned
    }

    /// Removes a player. When nobody is left (no humans and no spectators),
    /// every bot is removed too; their ids are returned so callers can announce it.
    pub fn remove_player(
        &mut self,
        id: Uuid,
    ) -> Vec<Uuid> {
        let was_it = self
            .players
            .get(&id)
            .map(|player| player.is_it)
            .unwrap_or(false);

        self.players.remove(&id);
        self.inputs.remove(&id);
        self.bots.remove(&id);

        let removed_bots = self.despawn_bots_if_empty();

        if was_it {
            self.assign_random_it();
        }

        removed_bots
    }

    /// Drop every bot when the room has no humans and no spectators.
    fn despawn_bots_if_empty(&mut self) -> Vec<Uuid> {
        if self.has_presence() {
            return Vec::new();
        }
        let removed: Vec<_> = self.bots.keys().copied().collect();
        for bot_id in &removed {
            self.players.remove(bot_id);
            self.inputs.remove(bot_id);
        }
        self.bots.clear();
        removed
    }

    /// Tags performed by bots since the last call, for broadcasting.
    pub fn take_tag_events(&mut self) -> Vec<(Uuid, Uuid)> {
        std::mem::take(&mut self.tag_events)
    }

    /// Runs each bot's AI and stores its movement input.
    fn think_bots(&mut self) -> Vec<(Uuid, Uuid)> {
        let bot_ids = self.bots.keys().copied().collect::<Vec<_>>();
        let mut tag_attempts = Vec::new();

        for id in bot_ids {
            let Some(mut brain) = self.bots.remove(&id) else {
                continue;
            };

            if let Some(me) = self.players.get(&id) {
                let decision = bot::think(
                    me,
                    &self.players,
                    &self.inputs,
                    &mut brain,
                );

                self.inputs.insert(
                    id,
                    PlayerInput {
                        seq: 0,
                        dx: decision.dx,
                        dy: decision.dy,
                        running: decision.running,
                    },
                );

                if let Some(target) = decision.tag {
                    tag_attempts.push((id, target));
                }
            }

            self.bots.insert(id, brain);
        }

        tag_attempts
    }

    fn assign_it_if_needed(
        &mut self,
    ) {
        if self
            .players
            .values()
            .any(|player| player.is_it)
        {
            return;
        }

        if self.players.len() < 2 {
            return;
        }

        self.assign_random_it();
    }

    fn assign_random_it(
        &mut self,
    ) {
        let mut rng = rand::rng();

        let Some(id) = self
            .players
            .keys()
            .copied()
            .choose(&mut rng)
        else {
            return;
        };

        if let Some(player) =
            self.players.get_mut(&id)
        {
            player.is_it = true;
        }
    }

    pub fn set_input(
        &mut self,
        id: Uuid,
        mut input: PlayerInput,
    ) {
        // Normalize/validate the direction on the server.
        let length =
            (input.dx * input.dx
                + input.dy * input.dy)
                .sqrt();

        if length > 1.0 {
            input.dx /= length;
            input.dy /= length;
        }

        if let Some(existing) =
            self.inputs.get_mut(&id)
        {
            if input.seq >= existing.seq {
                *existing = input;
            }
        }
    }

    pub fn advance_tick(
        &mut self,
        dt: f32,
    ) {
        for player in
            self.players.values_mut()
        {
            if player.tag_immunity_ticks > 0 {
                player.tag_immunity_ticks -= 1;
            }

            if player.escape_boost_ticks > 0 {
                player.escape_boost_ticks -= 1;
            }
        }

        let tag_attempts = self.think_bots();

        let player_ids =
            self.players
                .keys()
                .copied()
                .collect::<Vec<_>>();

        for id in player_ids {
            let input =
                self.inputs
                    .get(&id)
                    .copied()
                    .unwrap_or_default();

            let moving =
                input.dx != 0.0
                    || input.dy != 0.0;

            let Some(player) =
                self.players.get_mut(&id)
            else {
                continue;
            };

            energy::update_energy(
                player,
                moving,
                input.running,
                dt,
            );

            let mut speed =
                if player.is_running {
                    energy::RUN_SPEED
                        * energy::running_speed_multiplier(
                            player.energy,
                        )
                } else {
                    energy::WALK_SPEED
                };

            if player.is_it {
                speed *=
                    energy::IT_SPEED_MULTIPLIER;
            }

            if player.escape_boost_ticks > 0 {
                speed *=
                    energy::ESCAPE_BOOST_MULTIPLIER;
            }

            movement::move_player(
                &mut player.position,
                input.dx,
                input.dy,
                speed,
                dt,
            );

            if moving {
                player.facing =
                    input.dy.atan2(input.dx);
            }

            movement::clamp_to_area(
                &mut player.position,
                PLAYER_RADIUS,
                WALL_LEFT,
                WALL_TOP,
                WORLD_WIDTH - WALL_RIGHT,
                WORLD_HEIGHT - WALL_BOTTOM,
            );
        }

        for (tagger, target) in tag_attempts {
            if self.tag_player(tagger, target) {
                self.tag_events.push((tagger, target));
            }
        }
    }

    pub fn tag_player(
        &mut self,
        tagger_id: Uuid,
        target_id: Uuid,
    ) -> bool {
        if tagger_id == target_id {
            return false;
        }

        let tagger_is_it = self
            .players
            .get(&tagger_id)
            .map(|player| player.is_it)
            .unwrap_or(false);

        if !tagger_is_it {
            return false;
        }

        let target_immune = self
            .players
            .get(&target_id)
            .map(|player|
                player.tag_immunity_ticks > 0
            )
            .unwrap_or(true);

        if target_immune {
            return false;
        }

        let tagger_position =
            match self.players.get(&tagger_id) {
                Some(player) =>
                    player.position,
                None =>
                    return false,
            };

        let target_position =
            match self.players.get(&target_id) {
                Some(player) =>
                    player.position,
                None =>
                    return false,
            };

        const TAG_DISTANCE: f32 = 50.0;

        let dx =
            tagger_position.x
                - target_position.x;

        let dy =
            tagger_position.y
                - target_position.y;

        let touching =
            dx * dx + dy * dy
                <= TAG_DISTANCE * TAG_DISTANCE;

        if !touching {
            return false;
        }

        if let Some(old_it) =
            self.players.get_mut(&tagger_id)
        {
            old_it.is_it = false;

            old_it.tag_immunity_ticks =
                (TAG_COOLDOWN_SECONDS
                    * TICK_RATE as f32)
                    as u32;

            old_it.escape_boost_ticks =
                (TAG_COOLDOWN_SECONDS
                    * TICK_RATE as f32)
                    as u32;
        }

        if let Some(new_it) =
            self.players.get_mut(&target_id)
        {
            new_it.is_it = true;
            new_it.tag_immunity_ticks = 0;
        }

        true
    }

    pub fn snapshot(
        &self,
    ) -> Vec<crate::ws::protocol::PlayerSnapshot> {
        self.players
            .values()
            .map(|player| {
                crate::ws::protocol::PlayerSnapshot {
                    id: player.id,
                    name: player.name.clone(),
                    skin: player.skin,
                    x: player.position.x,
                    y: player.position.y,
                    energy: player.energy,
                    is_running: player.is_running,
                    is_it: player.is_it,
                    is_bot: player.is_bot,
                    facing: player.facing,
                }
            })
            .collect()
    }
}