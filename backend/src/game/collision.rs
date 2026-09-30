use crate::game::player::Position;

pub fn distance_squared(
    a: Position,
    b: Position,
) -> f32 {
    let dx = a.x - b.x;
    let dy = a.y - b.y;

    dx * dx + dy * dy
}

pub fn is_within_distance(
    a: Position,
    b: Position,
    distance: f32,
) -> bool {
    distance_squared(a, b)
        <= distance * distance
}