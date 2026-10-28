use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::game::{
    brawler::BrawlerSnapshot,
    cosmetic::Cosmetic,
    skin::Skin,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum ClientMessage {
    Join {
        room_id: String,
        /// Skin key to wear (e.g. "james", "wizard"; 1-32 chars of [a-z0-9_-]). Optional for older clients;
        /// invalid values fall back to "james" (see `Skin::parse`).
        #[serde(default)]
        skin: Option<String>,
        /// Opaque cosmetic key (e.g. "crown"). Optional; defaults to "none".
        #[serde(default)]
        cosmetic: Option<String>,
    },

    /// Change skin mid-game (from the settings panel).
    SetSkin {
        skin: String,
    },

    /// Change opaque cosmetic mid-game (e.g. after loading a saved crown).
    SetCosmetic {
        cosmetic: String,
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

    /// Enter the co-op sword brawler room (player should already be away).
    JoinBrawler {},

    /// Leave the brawler room (death, win, or quit). Does not clear away by itself.
    LeaveBrawler {},

    /// Movement + attack for the brawler room. `attack` is the tag button.
    BrawlerInput {
        seq: u64,
        dx: f32,
        dy: f32,
        attack: bool,
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
        /// Opaque cosmetic at join time; live changes arrive in snapshots.
        #[serde(default)]
        cosmetic: Cosmetic,
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

    /// Welcome into the brawler arena.
    BrawlerWelcome {
        player_id: Uuid,
        x: f32,
        y: f32,
        hp: f32,
        max_hp: f32,
    },

    /// Authoritative brawler state (only sent to players in the arena).
    BrawlerSnapshot {
        #[serde(flatten)]
        snapshot: BrawlerSnapshot,
    },

    /// This player died in the brawler (client plays death anim and leaves).
    BrawlerPlayerDied {
        player_id: Uuid,
    },

    /// The final boss is down; listed players win a crown.
    BrawlerWon {
        player_ids: Vec<Uuid>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlayerSnapshot {
    pub id: Uuid,
    /// Display name, e.g. "James 3".
    pub name: String,
    pub skin: Skin,
    /// Opaque cosmetic key (e.g. "crown"). Defaults to "none" for old peers.
    #[serde(default)]
    pub cosmetic: Cosmetic,
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

