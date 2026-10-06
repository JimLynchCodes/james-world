use taggame_backend::game::world::{
    PlayerInput, World, MAX_X, MAX_Y, MIN_X, MIN_Y, PLAYER_RADIUS, WALL_BOTTOM, WALL_LEFT,
    WALL_RIGHT, WALL_TOP, WORLD_HEIGHT, WORLD_WIDTH,
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

    // Top-left corner: stopped by the fence, which is inset from the edge.
    run(&mut world, id, -1.0, -1.0, 20);
    let p = &world.players[&id];
    assert_eq!(p.position.x, WALL_LEFT + PLAYER_RADIUS);
    assert_eq!(p.position.y, WALL_TOP + PLAYER_RADIUS);
    assert_eq!((p.position.x, p.position.y), (MIN_X, MIN_Y));

    // Bottom-right corner.
    run(&mut world, id, 1.0, 1.0, 60);
    let p = &world.players[&id];
    assert_eq!(p.position.x, WORLD_WIDTH - WALL_RIGHT - PLAYER_RADIUS);
    assert_eq!(p.position.y, WORLD_HEIGHT - WALL_BOTTOM - PLAYER_RADIUS);
    assert_eq!((p.position.x, p.position.y), (MAX_X, MAX_Y));
}

#[test]
fn top_wall_leaves_room_for_the_label_stack() {
    let mut world = World::new();
    let id = Uuid::new_v4();
    world.add_player(id);

    // Walk straight up for a long time: stops at the top fence, well below
    // the world edge (the camera can't scroll above y = 0, and the IT / YOU
    // / name labels sit ~130px above the player's centre).
    run(&mut world, id, 0.0, -1.0, 20);
    let p = &world.players[&id];
    assert_eq!(p.position.y, MIN_Y);
    assert!(MIN_Y >= 120.0, "top wall too close to the world edge: {MIN_Y}");
    assert!(p.position.x > MIN_X && p.position.x < MAX_X);
}

#[test]
fn bots_stay_inside_the_fence() {
    let mut world = World::new();
    world.add_player(Uuid::new_v4());
    for _ in 0..(30 * 30) {
        world.advance_tick(1.0 / 30.0);
    }
    for p in world.players.values() {
        assert!((MIN_X..=MAX_X).contains(&p.position.x), "{} x={}", p.name, p.position.x);
        assert!((MIN_Y..=MAX_Y).contains(&p.position.y), "{} y={}", p.name, p.position.y);
    }
}

/// The client draws the fence and clamps tap targets from its own copy of
/// these numbers (phaser-tag-client/src/world.ts); keep the two in sync.
#[test]
fn wall_constants_match_the_client() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../phaser-tag-client/src/world.ts");
    let ts = std::fs::read_to_string(path).expect("read client world.ts");
    let value = |name: &str| -> f32 {
        let needle = format!("export const {name} = ");
        let start = ts.find(&needle).unwrap_or_else(|| panic!("{name} missing in world.ts")) + needle.len();
        let end = start + ts[start..].find(';').unwrap();
        ts[start..end].trim().replace('_', "").parse().unwrap()
    };
    assert_eq!(value("WORLD_WIDTH"), WORLD_WIDTH);
    assert_eq!(value("WORLD_HEIGHT"), WORLD_HEIGHT);
    assert_eq!(value("PLAYER_RADIUS"), PLAYER_RADIUS);
    assert_eq!(value("WALL_LEFT"), WALL_LEFT);
    assert_eq!(value("WALL_RIGHT"), WALL_RIGHT);
    assert_eq!(value("WALL_TOP"), WALL_TOP);
    assert_eq!(value("WALL_BOTTOM"), WALL_BOTTOM);
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
