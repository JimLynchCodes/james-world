use std::collections::HashMap;

use rand::seq::IteratorRandom;
use uuid::Uuid;

use super::{
    energy,
    movement,
    player::Player,
};

pub const TICK_RATE: u32 = 30;
pub const WORLD_WIDTH: f32 = 5000.0;
pub const WORLD_HEIGHT: f32 = 5000.0;
pub const PLAYER_RADIUS: f32 = 18.0;
pub const TAG_COOLDOWN_SECONDS: f32 = 5.0;

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
}

impl World {
    pub fn new() -> Self {
        Self {
            players: HashMap::new(),
            inputs: HashMap::new(),
        }
    }

    pub fn add_player(
        &mut self,
        id: Uuid,
    ) {
        let player = Player::new(
            id,
            400.0,
            300.0,
        );

        self.players.insert(id, player);

        self.inputs.insert(
            id,
            PlayerInput::default(),
        );

        self.assign_it_if_needed();
    }

    pub fn remove_player(
        &mut self,
        id: Uuid,
    ) {
        let was_it = self
            .players
            .get(&id)
            .map(|player| player.is_it)
            .unwrap_or(false);

        self.players.remove(&id);
        self.inputs.remove(&id);

        if was_it {
            self.assign_random_it();
        }
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

            movement::clamp_to_bounds(
                &mut player.position,
                PLAYER_RADIUS,
                WORLD_WIDTH,
                WORLD_HEIGHT,
            );
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
                    x: player.position.x,
                    y: player.position.y,
                    energy: player.energy,
                    is_running: player.is_running,
                    is_it: player.is_it,
                    facing: player.facing,
                }
            })
            .collect()
    }
}