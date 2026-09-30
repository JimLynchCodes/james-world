use crate::game::player::Position;

pub fn move_player(
    position: &mut Position,
    dx: f32,
    dy: f32,
    speed: f32,
    dt: f32,
) {
    let length =
        (dx * dx + dy * dy).sqrt();

    if length == 0.0 {
        return;
    }

    let normalized_x = dx / length;
    let normalized_y = dy / length;

    position.x +=
        normalized_x * speed * dt;

    position.y +=
        normalized_y * speed * dt;
}