
use taggame_backend::game::{
    movement::{move_player, normalize_input},
    player::Position,
};

#[test]
fn diagonal_input_is_normalized() {
    let input = normalize_input(1.0, 1.0);

    let magnitude =
        (input.x * input.x + input.y * input.y).sqrt();

    assert!((magnitude - 1.0).abs() < 0.0001);
}

#[test]
fn player_cannot_move_outside_world() {
    let mut position = Position {
        x: 1999.0,
        y: 1999.0,
    };

    move_player(&mut position, 1.0, 1.0, 0.1);

    assert!(position.x <= 2000.0);
    assert!(position.y <= 2000.0);
}