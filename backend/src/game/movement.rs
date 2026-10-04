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

    let normalized_x =
        dx / length;

    let normalized_y =
        dy / length;

    position.x +=
        normalized_x * speed * dt;

    position.y +=
        normalized_y * speed * dt;
}

/// Keep a circle of `radius` fully inside the `[0, width] x [0, height]` world.
pub fn clamp_to_bounds(
    position: &mut Position,
    radius: f32,
    width: f32,
    height: f32,
) {
    position.x =
        position.x.clamp(radius, width - radius);

    position.y =
        position.y.clamp(radius, height - radius);
}
