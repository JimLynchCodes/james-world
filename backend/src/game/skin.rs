//! Player skins (cosmetic only: how other clients draw the kid).

use serde::{Deserialize, Serialize};

/// The outfit a player's kid wears. Sent to clients as a lowercase string
/// ("james", "banana", "trex"); mirrored by `Skin` in phaser-tag-client/src/protocol.ts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Skin {
    /// The normal kid (default; bots always wear it).
    #[default]
    James,
    /// Banana James: the same kid in a banana costume.
    Banana,
    /// T-rex James: the same kid in a T-rex onesie.
    Trex,
}

impl Skin {
    /// Parse a client-supplied skin name. Anything unknown falls back to
    /// the default, so an old or tampered client can't break the game.
    pub fn parse(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "banana" => Skin::Banana,
            "trex" => Skin::Trex,
            _ => Skin::James,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Skin::James => "james",
            Skin::Banana => "banana",
            Skin::Trex => "trex",
        }
    }
}
