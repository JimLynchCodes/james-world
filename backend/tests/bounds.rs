use taggame_backend::game::world::{
    PlayerInput, World, PLAYER_RADIUS, WORLD_HEIGHT, WORLD_WIDTH,
};
use uuid::Uuid;

fn run(world: &mut World, id: Uuid, dx: f32, dy: f32, seconds: u32) {
    world.set_input(id, PlayerInput { seq: 1, dx, dy, running: false });
    for _ in 0..(seconds * 30) {
        world.advance_tick(1.0 / 30.0);
    }
}

#[test]
fn player_cannot_leave_the_world() {
    let mut world = World::new();
    let id = Uuid::new_v4();
    world.add_player(id);

    run(&mut world, id, -1.0, -1.0, 20);
    let p = &world.players[&id];
    assert_eq!(p.position.x, PLAYER_RADIUS);
    assert_eq!(p.position.y, PLAYER_RADIUS);

    run(&mut world, id, 1.0, 1.0, 60);
    let p = &world.players[&id];
    assert_eq!(p.position.x, WORLD_WIDTH - PLAYER_RADIUS);
    assert_eq!(p.position.y, WORLD_HEIGHT - PLAYER_RADIUS);
}

#[test]
fn facing_follows_last_movement_direction() {
    let mut world = World::new();
    let id = Uuid::new_v4();
    world.add_player(id);

    run(&mut world, id, 0.0, 1.0, 1);
    assert!((world.players[&id].facing - std::f32::consts::FRAC_PI_2).abs() < 1e-4);

    // Standing still keeps the last facing.
    run(&mut world, id, 0.0, 0.0, 1);
    assert!((world.players[&id].facing - std::f32::consts::FRAC_PI_2).abs() < 1e-4);
    assert!((world.snapshot().iter().find(|p| p.id == id).unwrap().facing - std::f32::consts::FRAC_PI_2).abs() < 1e-4);
}
