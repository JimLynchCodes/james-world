
use crate::game::player::Position;

pub const TAG_RADIUS: f32 = 40.0;

pub fn is_near(
    first: &Position,
    second: &Position,
    radius: f32,
) -> bool {
    let dx = first.x - second.x;
    let dy = first.y - second.y;

    dx * dx + dy * dy <= radius * radius
}

pub fn can_tag(
    tagger: &Position,
    target: &Position,
) -> bool {
    is_near(tagger, target, TAG_RADIUS)
}