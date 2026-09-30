
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::game::player::Position;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data", rename_all = "snake_case")]
pub enum ClientMessage {
    Join {
        name: String,
    },
    MoveInput {
        seq: u64,
        x: f32,
        y: f32,
    },
    Ping {
        timestamp: u64,
    },
    TagPlayer {
        target_id: Uuid,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data", rename_all = "snake_case")]
pub enum ServerMessage {
    Welcome {
        player_id: Uuid,
        tick_rate: u32,
    },
    WorldSnapshot {
        tick: u64,
        players: Vec<PlayerSnapshot>,
    },
    PlayerJoined {
        player: PlayerSnapshot,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlayerSnapshot {
    pub id: Uuid,
    pub name: String,
    pub position: Position,
    pub is_it: bool,
    pub last_processed_seq: u64,
}

impl ServerMessage {
    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}