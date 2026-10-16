use taggame_backend::game::{
    bot::{choose_target, BotSkill, BOT_COUNT},
    world::{PlayerInput, World, SPAWN, SPAWN_GAP},
};
use uuid::Uuid;

fn bots(world: &World) -> Vec<Uuid> {
    world
        .players
        .values()
        .filter(|p| p.is_bot)
        .map(|p| p.id)
        .collect()
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
    let medium = BotSkill::Medium.profile().human_preference;
    assert_eq!(
        choose_target(&me, &world.players, None, medium),
        Some(human)
    );

    // But a much closer bot still wins.
    world.players.get_mut(&other).unwrap().position.x = 1100.0;
    assert_eq!(
        choose_target(&me, &world.players, None, medium),
        Some(other)
    );

    // Easy bots barely prefer humans, so the bot 400 away beats the human at 500.
    world.players.get_mut(&other).unwrap().position.x = 1400.0;
    let easy = BotSkill::Easy.profile().human_preference;
    assert_eq!(choose_target(&me, &world.players, None, easy), Some(other));
    // Hard bots still go for that human.
    let hard = BotSkill::Hard.profile().human_preference;
    assert_eq!(choose_target(&me, &world.players, None, hard), Some(human));
}

#[test]
fn it_bot_chases_down_and_tags_a_stationary_human() {
    for skill in [BotSkill::Easy, BotSkill::Medium, BotSkill::Hard] {
        let mut world = World::new();
        let human = Uuid::new_v4();
        world.add_player(human);

        // Park the human; make one bot IT and put it a bit away, others far.
        let ids = bots(&world);
        for p in world.players.values_mut() {
            p.is_it = false;
        }
        let hunter = ids[0];
        world.bots.get_mut(&hunter).unwrap().skill = skill;
        world.players.get_mut(&hunter).unwrap().is_it = true;
        world.players.get_mut(&hunter).unwrap().position.x = 400.0 + 900.0;
        world.players.get_mut(&hunter).unwrap().position.y = 300.0;
        // Keep the other bots out of the hunt so a close spawn can't steal the target.
        for other in ids.iter().filter(|id| **id != hunter) {
            world.players.get_mut(other).unwrap().position.x = 4600.0;
            world.players.get_mut(other).unwrap().position.y = 4600.0;
        }

        let mut tagged = false;
        for _ in 0..(30 * 20) {
            world.advance_tick(1.0 / 30.0);
            if world
                .take_tag_events()
                .iter()
                .any(|(tagger, target)| *tagger == hunter && *target == human)
            {
                tagged = true;
                break;
            }
        }

        assert!(
            tagged,
            "{skill:?} IT bot should reach and tag the human within 20s"
        );
        assert!(world.players[&human].is_it);
    }
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
    world.set_input(
        human,
        PlayerInput {
            seq: 1,
            dx: 0.0,
            dy: 0.0,
            running: false,
        },
    );
    for _ in 0..30 {
        world.advance_tick(1.0 / 30.0);
    }
    assert!(dist(&world, fleer, human) > before + 100.0);
}

#[test]
fn spawned_bots_have_one_of_each_skill() {
    let mut world = World::new();
    world.add_player(Uuid::new_v4());
    let mut skills: Vec<_> = world.bots.values().map(|b| b.skill).collect();
    skills.sort_by_key(|s| match s {
        BotSkill::Easy => 0,
        BotSkill::Medium => 1,
        BotSkill::Hard => 2,
    });
    assert_eq!(skills, [BotSkill::Easy, BotSkill::Medium, BotSkill::Hard]);
    assert!(world
        .players
        .values()
        .filter(|p| p.is_bot)
        .all(|p| p.name.starts_with("James ")));
}

#[test]
fn skill_profiles_are_ordered_and_all_short_of_perfect() {
    let easy = BotSkill::Easy.profile();
    let medium = BotSkill::Medium.profile();
    let hard = BotSkill::Hard.profile();

    assert!(easy.speed_scale < medium.speed_scale && medium.speed_scale < hard.speed_scale);
    assert!(
        hard.speed_scale < 1.0,
        "even a hard bot is slower than a human"
    );
    assert!(easy.tag_range < medium.tag_range && medium.tag_range < hard.tag_range);
    assert!(
        hard.tag_range < 50.0,
        "tag reach stays inside the server maximum"
    );
    assert!(
        easy.reaction_ticks > medium.reaction_ticks && medium.reaction_ticks > hard.reaction_ticks
    );
    assert!(easy.aim_jitter > medium.aim_jitter && medium.aim_jitter > hard.aim_jitter);
    assert!(easy.lead < medium.lead && medium.lead < hard.lead && hard.lead < 1.0);
    assert!(easy.flee_lead < medium.flee_lead && medium.flee_lead < hard.flee_lead);
    assert!(hard.flee_lead < hard.lead);
    assert!(easy.flee_radius < medium.flee_radius && medium.flee_radius < hard.flee_radius);
    assert!(
        easy.tag_dwell_ticks > medium.tag_dwell_ticks
            && medium.tag_dwell_ticks > hard.tag_dwell_ticks
    );
    // Weaker human preference is a larger multiplier (1 would ignore the difference).
    assert!(
        easy.human_preference > medium.human_preference
            && medium.human_preference > hard.human_preference
    );
    assert!(hard.human_preference > 0.0);
}

/// Distance a bot of `skill` opens on a stationary IT human in 1.5 seconds,
/// starting 230px to the east in open ground. Easy is already outside its
/// sprint radius and only walks; medium and hard sprint until they cross
/// theirs, so the gap is smaller than a full-speed race and still ordered.
fn flee_gain(skill: BotSkill) -> f32 {
    let mut world = World::new();
    let human = Uuid::new_v4();
    world.add_player(human);
    let ids = bots(&world);
    for p in world.players.values_mut() {
        p.is_it = false;
        p.energy = 100.0;
    }
    world.players.get_mut(&human).unwrap().is_it = true;
    world.players.get_mut(&human).unwrap().position.x = 2200.0;
    world.players.get_mut(&human).unwrap().position.y = 2500.0;

    let fleer = ids[0];
    world.bots.get_mut(&fleer).unwrap().skill = skill;
    // 230px east: easy only walks (sprint radius 180), medium and hard sprint.
    world.players.get_mut(&fleer).unwrap().position.x = 2430.0;
    world.players.get_mut(&fleer).unwrap().position.y = 2500.0;
    for other in ids.iter().filter(|id| **id != fleer) {
        world.players.get_mut(other).unwrap().position.x = 4200.0;
        world.players.get_mut(other).unwrap().position.y = 800.0;
    }

    let before = dist(&world, fleer, human);
    world.set_input(
        human,
        PlayerInput {
            seq: 1,
            dx: 0.0,
            dy: 0.0,
            running: false,
        },
    );
    for _ in 0..45 {
        world.advance_tick(1.0 / 30.0);
    }
    dist(&world, fleer, human) - before
}

#[test]
fn easier_bots_flee_slower_than_harder_ones() {
    for _ in 0..8 {
        let easy = flee_gain(BotSkill::Easy);
        let medium = flee_gain(BotSkill::Medium);
        let hard = flee_gain(BotSkill::Hard);
        assert!(
            medium > easy + 30.0 && hard > medium + 20.0,
            "flee gains easy={easy:.1} medium={medium:.1} hard={hard:.1}"
        );
    }
}

#[test]
fn human_it_closes_on_a_fleeing_bot_of_every_skill() {
    for skill in [BotSkill::Easy, BotSkill::Medium, BotSkill::Hard] {
        let mut world = World::new();
        let human = Uuid::new_v4();
        world.add_player(human);
        let ids = bots(&world);
        for p in world.players.values_mut() {
            p.is_it = false;
            p.energy = 100.0;
        }
        world.players.get_mut(&human).unwrap().is_it = true;
        world.players.get_mut(&human).unwrap().position.x = 2000.0;
        world.players.get_mut(&human).unwrap().position.y = 2500.0;

        let fleer = ids[0];
        world.bots.get_mut(&fleer).unwrap().skill = skill;
        // 320px east: inside every flee radius, so they run, but a sprinting IT human is faster.
        world.players.get_mut(&fleer).unwrap().position.x = 2320.0;
        world.players.get_mut(&fleer).unwrap().position.y = 2500.0;
        for other in ids.iter().filter(|id| **id != fleer) {
            world.players.get_mut(other).unwrap().position.x = 4300.0;
            world.players.get_mut(other).unwrap().position.y = 700.0;
        }

        let before = dist(&world, fleer, human);
        for _ in 0..45 {
            world.set_input(
                human,
                PlayerInput {
                    seq: 1,
                    dx: 1.0,
                    dy: 0.0,
                    running: true,
                },
            );
            world.advance_tick(1.0 / 30.0);
        }
        let after = dist(&world, fleer, human);
        assert!(
            after < before - 70.0,
            "{skill:?} should be catchable: {before:.1} -> {after:.1}"
        );
    }
}

#[test]
fn sprinting_human_escapes_easy_and_medium_but_not_a_hard_straight_line() {
    // Two seconds, both starting full. Human runs due east; the IT bot starts
    // 400px to the west and has to chase.
    fn gap_after_chase(skill: BotSkill) -> (f32, f32) {
        let mut world = World::new();
        let human = Uuid::new_v4();
        world.add_player(human);
        let ids = bots(&world);
        for p in world.players.values_mut() {
            p.is_it = false;
            p.energy = 100.0;
        }
        let hunter = ids[0];
        world.bots.get_mut(&hunter).unwrap().skill = skill;
        world.players.get_mut(&hunter).unwrap().is_it = true;
        world.players.get_mut(&hunter).unwrap().position.x = 2100.0;
        world.players.get_mut(&hunter).unwrap().position.y = 2500.0;
        world.players.get_mut(&human).unwrap().position.x = 2500.0;
        world.players.get_mut(&human).unwrap().position.y = 2500.0;
        for other in ids.iter().filter(|id| **id != hunter) {
            world.players.get_mut(other).unwrap().position.x = 4300.0;
            world.players.get_mut(other).unwrap().position.y = 700.0;
        }

        let before = dist(&world, hunter, human);
        for _ in 0..60 {
            world.set_input(
                human,
                PlayerInput {
                    seq: 1,
                    dx: 1.0,
                    dy: 0.0,
                    running: true,
                },
            );
            world.advance_tick(1.0 / 30.0);
        }
        (before, dist(&world, hunter, human))
    }

    let (easy_before, easy_after) = gap_after_chase(BotSkill::Easy);
    assert!(
        easy_after > easy_before + 60.0,
        "easy IT bot should lose a sprinting human: {easy_before:.1} -> {easy_after:.1}"
    );

    let (medium_before, medium_after) = gap_after_chase(BotSkill::Medium);
    assert!(
        medium_after > medium_before + 8.0,
        "medium IT bot should lose a straight sprint: {medium_before:.1} -> {medium_after:.1}"
    );

    let (hard_before, hard_after) = gap_after_chase(BotSkill::Hard);
    assert!(
        hard_after < hard_before - 8.0,
        "hard IT bot still closes a straight sprint: {hard_before:.1} -> {hard_after:.1}"
    );
}

#[test]
fn every_join_is_named_james_with_a_server_wide_counter() {
    let mut world = World::new();
    let h1 = Uuid::new_v4();
    let spawned = world.add_player(h1);
    assert_eq!(world.players[&h1].name, "James 1");
    // Bots spawned by that join are numbered right after the human.
    let mut bot_names = spawned
        .iter()
        .map(|id| world.players[id].name.clone())
        .collect::<Vec<_>>();
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
    assert!(snap
        .iter()
        .filter(|p| p.is_bot)
        .all(|p| p.skin == Skin::James));

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
    assert_eq!(
        serde_json::from_value::<Skin>(serde_json::json!("tuxedo")).unwrap(),
        Skin::Tuxedo
    );
    assert!(world.set_skin(human, Skin::parse("pirate")));
    assert_eq!(world.skin_of(&human), Skin::Pirate);
    assert_eq!(Skin::parse(" Pirate "), Skin::Pirate);
    assert_eq!(Skin::Pirate.as_str(), "pirate");
    assert_eq!(serde_json::to_value(Skin::Pirate).unwrap(), "pirate");
    assert_eq!(
        serde_json::from_value::<Skin>(serde_json::json!("pirate")).unwrap(),
        Skin::Pirate
    );
    assert_eq!(Skin::parse("pirates"), Skin::James);
    assert!(world.set_skin(human, Skin::parse("pharaoh")));
    assert_eq!(world.skin_of(&human), Skin::Pharaoh);
    assert_eq!(Skin::parse(" Pharaoh "), Skin::Pharaoh);
    assert_eq!(Skin::Pharaoh.as_str(), "pharaoh");
    assert_eq!(serde_json::to_value(Skin::Pharaoh).unwrap(), "pharaoh");
    assert_eq!(
        serde_json::from_value::<Skin>(serde_json::json!("pharaoh")).unwrap(),
        Skin::Pharaoh
    );
    assert_eq!(Skin::parse("pharaohs"), Skin::James);
    assert_eq!(
        Skin::parse("tux"),
        Skin::James,
        "unknown skins fall back to james"
    );
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

#[test]
fn joining_humans_never_spawn_on_top_of_someone() {
    // Everyone used to appear at exactly (400, 300): two idle kids there drew
    // their sprites and IT / YOU / name labels on top of each other.
    let mut world = World::new();
    let first = Uuid::new_v4();
    world.add_player(first);
    let p = &world.players[&first].position;
    assert_eq!((p.x, p.y), SPAWN);

    let mut humans = vec![first];
    for _ in 0..15 {
        let id = Uuid::new_v4();
        world.add_player(id);
        humans.push(id);
    }
    for (i, a) in humans.iter().enumerate() {
        for b in &world.players {
            if b.0 != a {
                assert!(
                    dist(&world, *a, *b.0) >= SPAWN_GAP - 0.01,
                    "human {i} spawned on another player"
                );
            }
        }
        let pos = &world.players[a].position;
        assert!(
            pos.x >= taggame_backend::game::world::MIN_X
                && pos.x <= taggame_backend::game::world::MAX_X
        );
        assert!(
            pos.y >= taggame_backend::game::world::MIN_Y
                && pos.y <= taggame_backend::game::world::MAX_Y
        );
    }

    // A spot frees up again once its player walks off.
    world.players.get_mut(&first).unwrap().position.x = 2500.0;
    let id = Uuid::new_v4();
    world.add_player(id);
    let p = &world.players[&id].position;
    assert_eq!((p.x, p.y), SPAWN);
}
