//! Player skins (cosmetic only: how other clients draw the kid).
//!
//! The server doesn't know the list of skins. A skin is an opaque, validated
//! key ("james", "banana", "wizard", ...) that is stored per player and
//! relayed to other clients as-is; the client maps it to a sprite sheet and
//! falls back to the default kid for keys it doesn't know. So adding a new
//! skin is a client-only change - no backend redeploy.

use serde::{Deserialize, Deserializer, Serialize};

/// Longest accepted skin key.
pub const MAX_SKIN_LEN: usize = 32;

/// The outfit a player's kid wears: a lowercase key of 1-32 characters from
/// `[a-z0-9_-]`. Serialised as a plain string (wire-compatible with the old
/// enum names).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct Skin(String);

impl Default for Skin {
    /// The normal kid (bots always wear it).
    fn default() -> Self {
        Skin(Skin::DEFAULT.to_string())
    }
}

impl Skin {
    pub const DEFAULT: &'static str = "james";

    /// Parse a client-supplied skin key (trimmed, lowercased). Anything
    /// invalid falls back to the default, so an old or tampered client can't
    /// break the game.
    pub fn parse(value: &str) -> Self {
        let v = value.trim().to_ascii_lowercase();
        let ok = !v.is_empty()
            && v.len() <= MAX_SKIN_LEN
            && v.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-');
        if ok {
            Skin(v)
        } else {
            Skin::default()
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for Skin {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Ok(Skin::parse(&s))
    }
}
