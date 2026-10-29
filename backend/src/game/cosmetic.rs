//! Opaque cosmetic keys (e.g. a golden crown), same validation rules as skins.
//!
//! The server does not know the list of cosmetics. A key is stored per player
//! and relayed to other clients; unknown keys are ignored by the client. So
//! adding a new cosmetic is a client-only change once the field exists.

use serde::{Deserialize, Deserializer, Serialize};

pub const MAX_COSMETIC_LEN: usize = 32;

/// A lowercase key of 1-32 characters from `[a-z0-9_-]`, or empty ("none").
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct Cosmetic(String);

impl Default for Cosmetic {
    fn default() -> Self {
        Cosmetic(Cosmetic::NONE.to_string())
    }
}

impl Cosmetic {
    pub const NONE: &'static str = "none";
    pub const CROWN: &'static str = "crown";

    /// Parse a client-supplied cosmetic key. Invalid values become "none".
    pub fn parse(value: &str) -> Self {
        let v = value.trim().to_ascii_lowercase();
        if v.is_empty() || v == Self::NONE {
            return Cosmetic::default();
        }
        let ok = v.len() <= MAX_COSMETIC_LEN
            && v
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-');
        if ok {
            Cosmetic(v)
        } else {
            Cosmetic::default()
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn is_none(&self) -> bool {
        self.0 == Self::NONE
    }
}

impl<'de> Deserialize<'de> for Cosmetic {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Ok(Cosmetic::parse(&s))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_accepts_crown_and_rejects_junk() {
        assert_eq!(Cosmetic::parse("crown").as_str(), "crown");
        assert_eq!(Cosmetic::parse("NONE").as_str(), "none");
        assert_eq!(Cosmetic::parse("").as_str(), "none");
        assert_eq!(Cosmetic::parse("Bad Key!").as_str(), "none");
    }
}
