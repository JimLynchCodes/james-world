
use std::collections::HashMap;

use uuid::Uuid;

use crate::{
    game::{
        collision::can_tag,
        movement::move_player,
        player::{Player, Position},
    },
    ws::protocol::{PlayerSnapshot, ServerMessage},
};

pub struct World {
    pub players: HashMap<Uuid, Player>,
    pub inputs: HashMap<Uuid, Position>,
    pub tick: u64,
}

impl World {
    pub fn new() -> Self {
        Self {
            players: HashMap::new(),
            inputs: HashMap::new(),
            tick: 0,
        }
    }

    pub fn add_player(&mut self, name: String) -> Uuid {
        let player = Player::new(name);
        let id = player.id;

        self.players.insert(id, player);
        self.inputs.insert(id, Position::default());

        id
    }

    pub fn remove_player(&mut self, player_id: Uuid) {
        self.players.remove(&player_id);
        self.inputs.remove(&player_id);
    }

    pub fn set_input(
        &mut self,
        player_id: Uuid,
        seq: u64,
        x: f32,
        y: f32,
    ) {
        if !x.is_finite() || !y.is_finite() {
            return;
        }

        let Some(player) = self.players.get_mut(&player_id)
        else {
            return;
        };

        if seq <= player.last_processed_seq {
            return;
        }

        player.last_processed_seq = seq;

        self.inputs.insert(
            player_id,
            Position {
                x: x.clamp(-1.0, 1.0),
                y: y.clamp(-1.0, 1.0),
            },
        );
    }

    pub fn advance_tick(&mut self, delta_seconds: f32) {
        self.tick += 1;

        let inputs = self.inputs.clone();

        for (player_id, input) in inputs {
            if let Some(player) = self.players.get_mut(&player_id) {
                move_player(
                    &mut player.position,
                    input.x,
                    input.y,
                    delta_seconds,
                );
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

        let Some(tagger) = self.players.get(&tagger_id) else {
            return false;
        };

        let Some(target) = self.players.get(&target_id) else {
            return false;
        };

        if !tagger.is_it {
            return false;
        }

        if !can_tag(&tagger.position, &target.position) {
            return false;
        }

        if let Some(tagger) = self.players.get_mut(&tagger_id) {
            tagger.is_it = false;
        }

        if let Some(target) = self.players.get_mut(&target_id) {
            target.is_it = true;
        }

        true
    }

    pub fn snapshot(&self) -> ServerMessage {
        let players = self
            .players
            .values()
            .map(|player| PlayerSnapshot {
                id: player.id,
                name: player.name.clone(),
                position: player.position,
                is_it: player.is_it,
                last_processed_seq: player.last_processed_seq,
            })
            .collect();

        ServerMessage::WorldSnapshot {
            tick: self.tick,
            players,
        }
    }
}