//! Random spawn: inside the inset yard, clear of scenery and other players,
//! not beside IT, reproducible from a seed, and still used when someone rejoins.
use taggame_backend::game::{
    player::Player,
    world::{World, IT_SPAWN_GAP, SPAWN_GAP},
};
use uuid::Uuid;

fn pos(world: &World, id: Uuid) -> (f32, f32) {
    let p = &world.players[&id].position;
    (p.x, p.y)
}

fn in_box(p: (f32, f32)) {
    let (min_x, min_y, max_x, max_y) = World::spawn_box();
    assert!(
        p.0 >= min_x && p.0 <= max_x && p.1 >= min_y && p.1 <= max_y,
        "spawn {:?} outside {min_x}..{max_x} x {min_y}..{max_y}",
        p
    );
}

fn human_spots(seed: u64, n: usize) -> Vec<(u32, u32)> {
    let mut world = World::with_seed(seed);
    let mut spots = Vec::new();
    for _ in 0..n {
        let id = Uuid::new_v4();
        world.add_player(id);
        let (x, y) = pos(&world, id);
        spots.push((x.to_bits(), y.to_bits()));
    }
    spots
}

#[test]
fn seeded_spawns_vary_across_joins_and_repeat_for_the_same_seed() {
    let a = human_spots(42, 5);
    let b = human_spots(42, 5);
    let c = human_spots(99, 5);
    assert_eq!(a, b, "the same seed must place each join on the same spot");
    assert_ne!(a, c, "a different seed must not replay the same spots");
    let distinct = a.iter().collect::<std::collections::HashSet<_>>().len();
    assert!(distinct >= 4, "joins should not keep landing on one point: {a:?}");
    for bits in &a {
        let spot = (f32::from_bits(bits.0), f32::from_bits(bits.1));
        in_box(spot);
        assert!(
            !World::spawn_hits_scenery(spot.0, spot.1),
            "spawn landed in scenery: {spot:?}"
        );
    }
}

#[test]
fn spawns_keep_the_gap_and_stay_off_the_walls() {
    let mut world = World::with_seed(3);
    let mut ids = Vec::new();
    for _ in 0..8 {
        let id = Uuid::new_v4();
        world.add_player(id);
        ids.push(id);
    }
    for id in &ids {
        let spot = pos(&world, *id);
        in_box(spot);
        assert!(!World::spawn_hits_scenery(spot.0, spot.1));
    }
    for (i, a) in ids.iter().enumerate() {
        for b in ids.iter().skip(i + 1) {
            let (ax, ay) = pos(&world, *a);
            let (bx, by) = pos(&world, *b);
            let d = ((ax - bx).powi(2) + (ay - by).powi(2)).sqrt();
            assert!(d >= SPAWN_GAP - 0.01, "two humans spawned {d}px apart");
        }
    }
    // Bots share the sampler, so they land in the same box and clear of props.
    for bot in world.players.values().filter(|p| p.is_bot) {
        in_box((bot.position.x, bot.position.y));
        assert!(!World::spawn_hits_scenery(bot.position.x, bot.position.y));
    }
}

#[test]
fn new_humans_do_not_spawn_beside_whoever_is_it() {
    let mut world = World::with_seed(11);
    let it = Uuid::new_v4();
    world.add_player(it);
    for player in world.players.values_mut() {
        player.is_it = false;
        // Park the opening cast in one corner so the rest of the yard is free.
        player.position.x = World::spawn_box().2 - 20.0;
        player.position.y = World::spawn_box().1 + 20.0;
    }
    let it_player = world.players.get_mut(&it).unwrap();
    it_player.is_it = true;
    it_player.position.x = 2500.0;
    it_player.position.y = 2500.0;

    for _ in 0..6 {
        let id = Uuid::new_v4();
        world.add_player(id);
        let (x, y) = pos(&world, id);
        let d = ((x - 2500.0).powi(2) + (y - 2500.0).powi(2)).sqrt();
        assert!(
            d >= IT_SPAWN_GAP - 0.01,
            "joiner appeared {d}px from IT (want >= {IT_SPAWN_GAP})"
        );
        in_box((x, y));
    }
}

#[test]
fn rejoin_is_a_fresh_spot_inside_the_yard() {
    // Disconnect removes the player; the next Join is add_player again.
    // The secret cave is not this path: set_away leaves the position alone.
    let mut world = World::with_seed(21);
    let first_id = Uuid::new_v4();
    world.add_player(first_id);
    let first = pos(&world, first_id);
    let away_at = first;
    world.set_away(first_id, true);
    world.set_away(first_id, false);
    assert_eq!(pos(&world, first_id), away_at, "leaving the cave must not move you");

    world.remove_player(first_id);
    let second_id = Uuid::new_v4();
    world.add_player(second_id);
    let second = pos(&world, second_id);
    in_box(second);
    assert_ne!(first, second, "a rejoin should not replay the spot you just left");
    assert!(!World::spawn_hits_scenery(second.0, second.1));
}

#[test]
fn packed_yard_falls_back_to_the_centre_of_the_spawn_box() {
    let mut world = World::with_seed(1);
    let (min_x, min_y, max_x, max_y) = World::spawn_box();
    // A grid tighter than SPAWN_GAP so every sample fails the spread check.
    let cols = ((max_x - min_x) / 90.0).ceil() as i32;
    let rows = ((max_y - min_y) / 90.0).ceil() as i32;
    for i in 0..=cols {
        for j in 0..=rows {
            let id = Uuid::new_v4();
            let x = min_x + (max_x - min_x) * (i as f32) / (cols as f32);
            let y = min_y + (max_y - min_y) * (j as f32) / (rows as f32);
            world.players.insert(id, Player::new(id, x, y));
        }
    }
    let id = Uuid::new_v4();
    world.add_player(id);
    let spot = pos(&world, id);
    let centre = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5);
    assert!(
        (spot.0 - centre.0).abs() < 0.01 && (spot.1 - centre.1).abs() < 0.01,
        "fallback was {spot:?}, centre is {centre:?}"
    );
}
