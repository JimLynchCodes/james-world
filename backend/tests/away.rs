//! Secret cave: the player stays in the world but is hidden and untaggable.
use taggame_backend::game::world::{PlayerInput, World};
use uuid::Uuid;

#[test]
fn away_player_is_hidden_held_still_and_untaggable() {
    let mut world = World::new();
    let human = Uuid::new_v4();
    world.add_player(human);

    let before = world.players[&human].position;
    let was_it = world.players[&human].is_it;
    let energy = world.players[&human].energy;

    world.set_away(human, true);
    assert!(world.players[&human].away);
    assert!(world.snapshot().iter().all(|p| p.id != human));

    // A move packet while away does not walk them, and does not clear IT / energy.
    world.set_input(
        human,
        PlayerInput {
            seq: 5,
            dx: 1.0,
            dy: 0.0,
            running: true,
        },
    );
    world.advance_tick(1.0);
    let player = &world.players[&human];
    assert!((player.position.x - before.x).abs() < 1e-3);
    assert!((player.position.y - before.y).abs() < 1e-3);
    assert_eq!(player.is_it, was_it);
    assert!(player.energy >= energy);

    // Overlapping an IT player still does not land a tag.
    let it = world
        .players
        .values()
        .find(|p| p.is_it && p.id != human)
        .map(|p| p.id);
    if let Some(it) = it {
        world.players.get_mut(&it).unwrap().position = before;
        assert!(!world.tag_player(it, human));
        assert!(!world.tag_player(human, it));
    } else {
        // The human themselves is IT. A bot beside them cannot take it.
        let bot = world.players.values().find(|p| p.is_bot).unwrap().id;
        world.players.get_mut(&bot).unwrap().position = before;
        assert!(!world.tag_player(bot, human));
    }

    world.set_away(human, false);
    assert!(!world.players[&human].away);
    assert!(world.snapshot().iter().any(|p| p.id == human));
    assert!((world.players[&human].position.x - before.x).abs() < 1e-3);
}
