use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::game::skin::Skin;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ClientMessage {
    Join {
        room_id: String,
        /// Skin key to wear (e.g. "james", "wizard"; 1-32 chars of [a-z0-9_-]). Optional for older clients;
        /// invalid values fall back to "james" (see `Skin::parse`).
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

    /// Secret cave. The player stays in the world; snapshots omit them
    /// and they cannot tag or be tagged until this is cleared.
    SetAway {
        away: bool,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ServerMessage {
    /// Sent on connect: the socket is a spectator. Snapshots and join/leave
    /// events follow; the client is not a player until it sends `Join`.
    Hello {},

    /// Sent only to the client that just joined as a player: its id, name,
    /// and the spot it should appear at. The client snaps there immediately
    /// (a reconnect is a new body, not a walk from the old one).
    Welcome {
        player_id: Uuid,
        name: String,
        x: f32,
        y: f32,
    },

    Snapshot {
        players: Vec<PlayerSnapshot>,
    },

    PlayerJoined {
        player_id: Uuid,
        name: String,
        /// Skin at join time; live changes arrive in snapshots.
        skin: Skin,
        /// Where they are standing, so other clients don't draw them at the
        /// world centre for a frame and then jump.
        x: f32,
        y: f32,
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