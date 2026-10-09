
use taggame_backend::game::{
    movement::move_player,
    player::Position,
};

#[test]
fn diagonal_input_is_normalized() {
    let mut position = Position { x: 0.0, y: 0.0 };
    // speed 10 over 1s; a diagonal is normalized so the step is exactly that speed
    move_player(&mut position, 1.0, 1.0, 10.0, 1.0);
    let magnitude = (position.x * position.x + position.y * position.y).sqrt();
    assert!((magnitude - 10.0).abs() < 0.0001);
}

#[test]
fn player_cannot_move_outside_world() {
    let mut position = Position {
        x: 1999.0,
        y: 1999.0,
    };

    move_player(&mut position, 1.0, 1.0, 0.1, 1.0);

    assert!(position.x <= 2000.0);
    assert!(position.y <= 2000.0);
}