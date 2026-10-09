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

#[test]
fn every_join_is_named_james_with_a_server_wide_counter() {
    let mut world = World::new();
    let h1 = Uuid::new_v4();
    let spawned = world.add_player(h1);
    assert_eq!(world.players[&h1].name, "James 1");
    // Bots spawned by that join are numbered right after the human.
    let mut bot_names = spawned.iter().map(|id| world.players[id].name.clone()).collect::<Vec<_>>();
    bot_names.sort();
    assert_eq!(bot_names, ["James 2", "James 3", "James 4"]);

    let h2 = Uuid::new_v4();
    world.add_player(h2);
    assert_eq!(world.players[&h2].name, "James 5");

    // Leaving doesn't free up numbers: the counter only goes up.
    world.remove_player(h2);
    let h3 = Uuid::new_v4();
    world.add_player(h3);
    assert_eq!(world.players[&h3].name, "James 6");

    // Names are in the snapshot.
    let snap = world.snapshot();
    assert_eq!(snap.iter().find(|p| p.id == h3).unwrap().name, "James 6");
}

#[test]
fn skins_default_to_james_and_unknown_values_fall_back() {
    use taggame_backend::game::skin::Skin;

    let mut world = World::new();
    let human = Uuid::new_v4();
    world.add_player(human);
    // Everyone (bots included) starts as plain James.
    assert!(world.players.values().all(|p| p.skin == Skin::James));

    assert!(world.set_skin(human, Skin::parse("banana")));
    assert_eq!(world.skin_of(&human), Skin::Banana);
    let snap = world.snapshot();
    let me = snap.iter().find(|p| p.id == human).unwrap();
    assert_eq!(me.skin, Skin::Banana);
    assert_eq!(serde_json::to_value(me).unwrap()["skin"], "banana");
    // Bots keep the default.
    assert!(snap.iter().filter(|p| p.is_bot).all(|p| p.skin == Skin::James));

    for bad in ["", "pineapple", "BANANA2", "James 1"] {
        assert_eq!(Skin::parse(bad), Skin::James, "{bad:?}");
    }
    assert_eq!(Skin::parse(" Banana "), Skin::Banana);
    assert!(world.set_skin(human, Skin::parse("trex")));
    assert_eq!(world.skin_of(&human), Skin::Trex);
    assert_eq!(Skin::parse("TREX"), Skin::Trex);
    assert_eq!(Skin::parse(" Trex "), Skin::Trex);
    assert!(world.set_skin(human, Skin::parse("tuxedo")));
    assert_eq!(world.skin_of(&human), Skin::Tuxedo);
    assert_eq!(Skin::parse(" TUXEDO "), Skin::Tuxedo);
    assert_eq!(Skin::Tuxedo.as_str(), "tuxedo");
    assert_eq!(serde_json::to_value(Skin::Tuxedo).unwrap(), "tuxedo");
    assert_eq!(serde_json::from_value::<Skin>(serde_json::json!("tuxedo")).unwrap(), Skin::Tuxedo);
    assert_eq!(Skin::parse("tux"), Skin::James, "unknown skins fall back to james");
    assert!(!world.set_skin(Uuid::new_v4(), Skin::Banana));
}

#[test]
fn spectators_keep_bots_and_joining_keeps_them() {
    let mut world = World::new();
    let spawned = world.add_spectator();
    assert_eq!(spawned.len(), BOT_COUNT);
    assert_eq!(bots(&world).len(), BOT_COUNT);

    // Spectator hits Start: seat released, then human added — bots stay.
    world.release_spectator_seat();
    let human = Uuid::new_v4();
    assert!(world.add_player(human).is_empty()); // bots already there
    assert_eq!(bots(&world).len(), BOT_COUNT);
    assert_eq!(world.spectator_count(), 0);
    assert_eq!(world.human_count(), 1);

    // Human leaves with no spectators: bots go.
    let removed = world.remove_player(human);
    assert_eq!(removed.len(), BOT_COUNT);
}
