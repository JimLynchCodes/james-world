use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::game::skin::Skin;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ClientMessage {
    Join {
        room_id: String,
        /// Skin to wear ("james" | "banana" | "trex" | "tuxedo" | "pirate" | "gorilla"). Optional for older clients;
        /// unknown values fall back to "james" (see `Skin::parse`).
        #[serde(default)]
        skin: Option<String>,
    },

    /// Change skin mid-game (from the settings panel).
    SetSkin {
        skin: String,
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
    /// Sent on connect: the socket is a spectator. Snapshots and join/leave
    /// events follow; the client is not a player until it sends `Join`.
    Hello {},

    /// Sent only to the client that just joined as a player: its id and name.
    Welcome {
        player_id: Uuid,
        name: String,
    },

    Snapshot {
        players: Vec<PlayerSnapshot>,
    },

    PlayerJoined {
        player_id: Uuid,
        name: String,
        /// Skin at join time; live changes arrive in snapshots.
        skin: Skin,
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
    /// Display name, e.g. "James 3".
    pub name: String,
    pub skin: Skin,
    pub x: f32,
    pub y: f32,
    pub energy: f32,
    pub is_running: bool,
    pub is_it: bool,
    pub is_bot: bool,
    pub facing: f32,
}

impl ServerMessage {
    pub fn to_json(
        &self,
    ) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}