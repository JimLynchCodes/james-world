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

/// Keep a circle of `radius` fully inside the `[left, right] x [top, bottom]`
/// rectangle (the fenced playing area).
pub fn clamp_to_area(
    position: &mut Position,
    radius: f32,
    left: f32,
    top: f32,
    right: f32,
    bottom: f32,
) {
    position.x =
        position.x.clamp(left + radius, right - radius);

    position.y =
        position.y.clamp(top + radius, bottom - radius);
}
