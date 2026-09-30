use std::collections::HashMap;

use rand::seq::IteratorRandom;
use uuid::Uuid;

use super::{
    energy,
    movement,
    player::Player,
};

pub const TICK_RATE: u32 = 30;

pub const TAG_COOLDOWN_SECONDS: f32 = 5.0;

#[derive(Debug, Clone, Copy)]
pub struct PlayerInput {
    pub seq: u64,
    pub x: f32,
    pub y: f32,
    pub running: bool,
}

impl Default for PlayerInput {
    fn default() -> Self {
        Self {
            seq: 0,
            x: 0.0,
            y: 0.0,
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
        let player =
            Player::new(
                id,
                400.0,
                300.0,
            );

        self.players.insert(
            id,
            player,
        );

        self.inputs.insert(
            id,
            PlayerInput::default(),
        );

        // If this is the second player,
        // randomly choose someone to be it.
        self.assign_it_if_needed();
    }

    pub fn remove_player(
        &mut self,
        id: Uuid,
    ) {
        let was_it =
            self.players
                .get(&id)
                .map(|player| player.is_it)
                .unwrap_or(false);

        self.players.remove(&id);
        self.inputs.remove(&id);

        // If it left, choose another player.
        if was_it {
            self.assign_random_it();
        }
    }

    fn assign_it_if_needed(
        &mut self,
    ) {
        // Don't assign another it if one already exists.
        if self.players.values().any(
            |player| player.is_it
        ) {
            return;
        }

        // We only start the game once there
        // are at least two players.
        if self.players.len() < 2 {
            return;
        }

        self.assign_random_it();
    }

    fn assign_random_it(
        &mut self,
    ) {
        let mut rng =
            rand::rng();

        let Some(id) =
            self.players
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
        input: PlayerInput,
    ) {
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
        // Tick down tag immunity and escape boosts.
        for player in self.players.values_mut() {
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

            let Some(player) =
                self.players.get_mut(&id)
            else {
                continue;
            };

            let moving =
                input.x != 0.0
                    || input.y != 0.0;

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
                            player.energy
                        )
                } else {
                    energy::WALK_SPEED
                };

            // It gets a permanent 10% speed boost.
            if player.is_it {
                speed *=
                    energy::IT_SPEED_MULTIPLIER;
            }

            // The person who just lost "it" gets
            // a temporary super-speed escape boost.
            if player.escape_boost_ticks > 0 {
                speed *=
                    energy::ESCAPE_BOOST_MULTIPLIER;
            }

            movement::move_player(
                &mut player.position,
                input.x,
                input.y,
                speed,
                dt,
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

        // Only "it" can tag someone.
        let tagger_is_it =
            self.players
                .get(&tagger_id)
                .map(|player| player.is_it)
                .unwrap_or(false);

        if !tagger_is_it {
            return false;
        }

        // Target must exist.
        let target_exists =
            self.players
                .contains_key(&target_id);

        if !target_exists {
            return false;
        }

        // The target may be temporarily immune
        // immediately after being it.
        let target_immune =
            self.players
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

        // Old it.
        if let Some(old_it) =
            self.players.get_mut(&tagger_id)
        {
            old_it.is_it = false;

            // 5-second escape protection.
            old_it.tag_immunity_ticks =
                (TAG_COOLDOWN_SECONDS
                    * TICK_RATE as f32)
                    as u32;

            // 5-second super-speed boost.
            old_it.escape_boost_ticks =
                (TAG_COOLDOWN_SECONDS
                    * TICK_RATE as f32)
                    as u32;
        }

        // New it.
        if let Some(new_it) =
            self.players.get_mut(&target_id)
        {
            new_it.is_it = true;

            // The new it can immediately tag
            // other players.
            new_it.tag_immunity_ticks = 0;
        }

        true
    }

    pub fn snapshot(
        &self,
    ) -> Vec<
        crate::ws::protocol::PlayerSnapshot
    > {
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
                }
            })
            .collect()
    }
}