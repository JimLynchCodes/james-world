use taggame_backend::game::{
    bot::{choose_target, BOT_COUNT},
    world::{PlayerInput, World},
};
use uuid::Uuid;

fn bots(world: &World) -> Vec<Uuid> {
    world.players.values().filter(|p| p.is_bot).map(|p| p.id).collect()
}

fn dist(world: &World, a: Uuid, b: Uuid) -> f32 {
    let (a, b) = (&world.players[&a].position, &world.players[&b].position);
    ((a.x - b.x).powi(2) + (a.y - b.y).powi(2)).sqrt()
}

#[test]
fn no_bots_without_a_human() {
    let world = World::new();
    assert!(world.players.is_empty());
}

#[test]
fn bots_spawn_with_first_human_and_leave_with_the_last() {
    let mut world = World::new();
    let h1 = Uuid::new_v4();
    let h2 = Uuid::new_v4();

    let spawned = world.add_player(h1);
    assert_eq!(spawned.len(), BOT_COUNT);
    assert_eq!(bots(&world).len(), BOT_COUNT);

    // A second human does not spawn more bots.
    assert!(world.add_player(h2).is_empty());
    assert_eq!(bots(&world).len(), BOT_COUNT);

    // Bots stay while any human remains...
    assert!(world.remove_player(h1).is_empty());
    assert_eq!(bots(&world).len(), BOT_COUNT);

    // ...and all go when the last human leaves.
    let removed = world.remove_player(h2);
    assert_eq!(removed.len(), BOT_COUNT);
    assert!(world.players.is_empty());
    assert!(world.bots.is_empty());
}

#[test]
fn someone_is_it_once_bots_spawn() {
    let mut world = World::new();
    world.add_player(Uuid::new_v4());
    assert_eq!(world.players.values().filter(|p| p.is_it).count(), 1);
}

#[test]
fn it_bot_prefers_humans_over_slightly_closer_bots() {
    let mut world = World::new();
    let human = Uuid::new_v4();
    world.add_player(human);

    let ids = bots(&world);
    let (hunter, other) = (ids[0], ids[1]);
    for p in world.players.values_mut() {
        p.is_it = false;
    }
    world.players.get_mut(&hunter).unwrap().is_it = true;

    world.players.get_mut(&hunter).unwrap().position.x = 1000.0;
    world.players.get_mut(&hunter).unwrap().position.y = 1000.0;
    world.players.get_mut(&other).unwrap().position.x = 1400.0; // 400 away
    world.players.get_mut(&other).unwrap().position.y = 1000.0;
    world.players.get_mut(&human).unwrap().position.x = 1000.0;
    world.players.get_mut(&human).unwrap().position.y = 1500.0; // 500 away

    let me = world.players[&hunter].clone();
    assert_eq!(choose_target(&me, &world.players, None), Some(human));

    // But a much closer bot still wins.
    world.players.get_mut(&other).unwrap().position.x = 1100.0;
    assert_eq!(choose_target(&me, &world.players, None), Some(other));
}

#[test]
fn it_bot_chases_down_and_tags_a_stationary_human() {
    let mut world = World::new();
    let human = Uuid::new_v4();
    world.add_player(human);

    // Park the human; make one bot IT and put it a bit away, others far.
    let ids = bots(&world);
    for p in world.players.values_mut() {
        p.is_it = false;
    }
    world.players.get_mut(&ids[0]).unwrap().is_it = true;
    world.players.get_mut(&ids[0]).unwrap().position.x = 400.0 + 900.0;
    world.players.get_mut(&ids[0]).unwrap().position.y = 300.0;

    let mut tagged = false;
    for _ in 0..(30 * 20) {
        world.advance_tick(1.0 / 30.0);
        if world
            .take_tag_events()
            .iter()
            .any(|(tagger, target)| *tagger == ids[0] && *target == human)
        {
            tagged = true;
            break;
        }
    }

    assert!(tagged, "IT bot should reach and tag the human within 20s");
    assert!(world.players[&human].is_it);
}

#[test]
fn non_it_bot_runs_away_from_it() {
    let mut world = World::new();
    let human = Uuid::new_v4();
    world.add_player(human);

    let ids = bots(&world);
    for p in world.players.values_mut() {
        p.is_it = false;
    }
    world.players.get_mut(&human).unwrap().is_it = true;

    // Fleeing bot in open space, IT human 200 away; park the other bots far away.
    let fleer = ids[0];
    world.players.get_mut(&human).unwrap().position.x = 2400.0;
    world.players.get_mut(&human).unwrap().position.y = 2500.0;
    world.players.get_mut(&fleer).unwrap().position.x = 2600.0;
    world.players.get_mut(&fleer).unwrap().position.y = 2500.0;
    for other in &ids[1..] {
        world.players.get_mut(other).unwrap().position.x = 200.0;
        world.players.get_mut(other).unwrap().position.y = 4800.0;
    }

    let before = dist(&world, fleer, human);
    // Human stands still (default input).
    world.set_input(human, PlayerInput { seq: 1, dx: 0.0, dy: 0.0, running: false });
    for _ in 0..30 {
        world.advance_tick(1.0 / 30.0);
    }
    assert!(dist(&world, fleer, human) > before + 100.0);
}
