use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ClientMessage {
    Join {
        room_id: String,
    },

    MoveInput {
        seq: u64,
        dx: f32,
        dy: f32,
        running: bool,
    },

    TagPlayer {
        target_id: Uuid,
    },

    Ping {
        timestamp: u64,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ServerMessage {
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlayerSnapshot {
    pub id: Uuid,
    pub x: f32,
    pub y: f32,
    pub energy: f32,
    pub is_running: bool,
    pub is_it: bool,
}

impl ServerMessage {
    pub fn to_json(
        &self,
    ) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}