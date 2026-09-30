use std::collections::HashMap;

use uuid::Uuid;

use super::{
    energy,
    movement,
    player::Player,
};

pub const WALK_SPEED: f32 = 200.0;
pub const RUN_SPEED: f32 = 350.0;

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
    }

    pub fn remove_player(
        &mut self,
        id: Uuid,
    ) {
        self.players.remove(&id);
        self.inputs.remove(&id);
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

            let speed =
                if player.is_running {
                    RUN_SPEED
                        * energy::running_speed_multiplier(
                            player.energy
                        )
                } else {
                    WALK_SPEED
                };

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
        &self,
        tagger_id: Uuid,
        target_id: Uuid,
    ) -> bool {
        if tagger_id == target_id {
            return false;
        }

        let Some(tagger) =
            self.players.get(&tagger_id)
        else {
            return false;
        };

        let Some(target) =
            self.players.get(&target_id)
        else {
            return false;
        };

        let dx =
            tagger.position.x
                - target.position.x;

        let dy =
            tagger.position.y
                - target.position.y;

        const TAG_DISTANCE: f32 = 50.0;

        dx * dx + dy * dy
            <= TAG_DISTANCE * TAG_DISTANCE
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
                }
            })
            .collect()
    }
}