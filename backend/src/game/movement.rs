
use crate::game::player::Position;

pub const PLAYER_SPEED: f32 = 200.0;
pub const WORLD_WIDTH: f32 = 2000.0;
pub const WORLD_HEIGHT: f32 = 2000.0;

pub fn normalize_input(x: f32, y: f32) -> Position {
    if !x.is_finite() || !y.is_finite() {
        return Position::default();
    }

    // Prevent the client from sending unbounded input.
    let x = x.clamp(-1.0, 1.0);
    let y = y.clamp(-1.0, 1.0);

    let magnitude = (x * x + y * y).sqrt();

    if magnitude > 1.0 {
        Position {
            x: x / magnitude,
            y: y / magnitude,
        }
    } else {
        Position { x, y }
    }
}

pub fn move_player(
    position: &mut Position,
    input_x: f32,
    input_y: f32,
    delta_seconds: f32,
) {
    let input = normalize_input(input_x, input_y);
    let dt = delta_seconds.clamp(0.0, 0.1);

    position.x += input.x * PLAYER_SPEED * dt;
    position.y += input.y * PLAYER_SPEED * dt;

    position.x = position.x.clamp(0.0, WORLD_WIDTH);
    position.y = position.y.clamp(0.0, WORLD_HEIGHT);
}