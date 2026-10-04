//! Server-controlled "bot" players.
//!
//! Bots only exist while at least one human is connected (see
//! `World::sync_bots`). Each tick, every bot runs `think`, which turns the
//! current world state into a movement input (and optionally a tag attempt),
//! exactly like a human's `MoveInput` would.
//!
//! * A bot that is **IT** hunts. It scores every taggable player by distance,
//!   strongly prefers humans, prefers tired targets (they can't sprint away),
//!   sticks with its current target to avoid dithering, and aims at where the
//!   target will be (lead pursuit) instead of where it is.
//! * A bot that is **not IT** runs away from IT (away from IT's predicted
//!   position, pushed off walls, sliding along them when cornered) and
//!   otherwise wanders.
//! * Bots manage their stamina (stop sprinting when drained, resume once
//!   recovered) and push apart from each other so they don't stack.

use std::collections::HashMap;

use rand::Rng;
use uuid::Uuid;

use super::{
    energy,
    player::Player,
    world::{PlayerInput, WORLD_HEIGHT, WORLD_WIDTH},
};

pub const BOT_COUNT: usize = 3;

/// Humans look this much closer than they really are when picking a target.
pub const HUMAN_PREFERENCE: f32 = 0.6;
/// The current target looks this much closer, so bots don't flip-flop.
const CURRENT_TARGET_BONUS: f32 = 0.8;
/// Extra attractiveness of a target with no energy left (up to +30% farther).
const TIRED_TARGET_WEIGHT: f32 = 0.3;

/// A bot tags anything this close (the server accepts up to 50).
const TAG_RANGE: f32 = 45.0;
const TAG_RETRY_TICKS: u32 = 15;

/// Non-IT bots only start fleeing when IT is this close.
const FLEE_RADIUS: f32 = 700.0;
const SPRINT_FLEE_RADIUS: f32 = 350.0;
const WALL_MARGIN: f32 = 350.0;
const SEPARATION_RADIUS: f32 = 90.0;
const WANDER_ARRIVE: f32 = 80.0;

const EXHAUSTED_BELOW: f32 = 12.0;
const RECOVERED_ABOVE: f32 = 45.0;

#[derive(Debug, Default)]
pub struct BotBrain {
    pub target: Option<Uuid>,
    pub wander_to: Option<(f32, f32)>,
    pub tag_cooldown: u32,
    pub exhausted: bool,
}

#[derive(Debug, Clone, Copy)]
pub struct BotDecision {
    pub dx: f32,
    pub dy: f32,
    pub running: bool,
    /// Player this bot wants to tag this tick, if any.
    pub tag: Option<Uuid>,
}

type Vec2 = (f32, f32);

fn len(v: Vec2) -> f32 {
    (v.0 * v.0 + v.1 * v.1).sqrt()
}

fn normalized(v: Vec2) -> Vec2 {
    let l = len(v);
    if l < 1e-4 {
        (0.0, 0.0)
    } else {
        (v.0 / l, v.1 / l)
    }
}

fn dist(a: &Player, b: &Player) -> f32 {
    len((
        a.position.x - b.position.x,
        a.position.y - b.position.y,
    ))
}

/// Pick who an IT bot should chase. Lower score wins.
pub fn choose_target(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    current: Option<Uuid>,
) -> Option<Uuid> {
    players
        .values()
        .filter(|p| p.id != me.id && p.tag_immunity_ticks == 0)
        .map(|p| {
            let mut score = dist(me, p);

            if !p.is_bot {
                score *= HUMAN_PREFERENCE;
            }

            score *= 1.0
                + TIRED_TARGET_WEIGHT
                    * (p.energy / energy::MAX_ENERGY)
                        .clamp(0.0, 1.0);

            if Some(p.id) == current {
                score *= CURRENT_TARGET_BONUS;
            }

            (p.id, score)
        })
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(id, _)| id)
}

/// Where a player's velocity is taking them, in pixels per second.
fn velocity_of(
    p: &Player,
    inputs: &HashMap<Uuid, PlayerInput>,
) -> Vec2 {
    let Some(input) = inputs.get(&p.id) else {
        return (0.0, 0.0);
    };

    let dir = normalized((input.dx, input.dy));

    let speed = if input.running
        && p.energy >= energy::MIN_RUNNING_ENERGY
    {
        energy::RUN_SPEED
            * energy::running_speed_multiplier(p.energy)
    } else {
        energy::WALK_SPEED
    };

    (dir.0 * speed, dir.1 * speed)
}

/// Aim point that leads a moving target (lead pursuit), capped at 1 second.
fn predicted_position(
    me: &Player,
    target: &Player,
    inputs: &HashMap<Uuid, PlayerInput>,
) -> Vec2 {
    let v = velocity_of(target, inputs);
    let d = dist(me, target);
    let my_speed = energy::RUN_SPEED;
    let t = (d / my_speed).min(1.0);

    (
        (target.position.x + v.0 * t).clamp(0.0, WORLD_WIDTH),
        (target.position.y + v.1 * t).clamp(0.0, WORLD_HEIGHT),
    )
}

/// Pushes away from nearby walls; magnitude grows quadratically as a wall nears.
fn wall_push(x: f32, y: f32) -> Vec2 {
    let f = |d: f32| {
        let k = ((WALL_MARGIN - d) / WALL_MARGIN).clamp(0.0, 1.0);
        k * k
    };

    (
        f(x) - f(WORLD_WIDTH - x),
        f(y) - f(WORLD_HEIGHT - y),
    )
}

fn separation(
    me: &Player,
    players: &HashMap<Uuid, Player>,
) -> Vec2 {
    let mut push = (0.0, 0.0);

    for other in players.values() {
        if other.id == me.id || !other.is_bot {
            continue;
        }

        let away = (
            me.position.x - other.position.x,
            me.position.y - other.position.y,
        );
        let d = len(away);

        if d > 0.0 && d < SEPARATION_RADIUS {
            let w = (SEPARATION_RADIUS - d) / SEPARATION_RADIUS;
            let n = normalized(away);
            push.0 += n.0 * w;
            push.1 += n.1 * w;
        }
    }

    push
}

pub fn think(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    inputs: &HashMap<Uuid, PlayerInput>,
    brain: &mut BotBrain,
) -> BotDecision {
    brain.tag_cooldown = brain.tag_cooldown.saturating_sub(1);

    if me.energy < EXHAUSTED_BELOW {
        brain.exhausted = true;
    } else if me.energy > RECOVERED_ABOVE {
        brain.exhausted = false;
    }
    let can_sprint = !brain.exhausted;

    let sep = separation(me, players);
    let mut tag = None;
    let steer: Vec2;
    let mut running = false;

    if me.is_it {
        brain.target = choose_target(me, players, brain.target);

        // Opportunistic tag: anything taggable in reach, not just the target.
        if brain.tag_cooldown == 0 {
            tag = players
                .values()
                .filter(|p| {
                    p.id != me.id
                        && p.tag_immunity_ticks == 0
                        && dist(me, p) <= TAG_RANGE
                })
                .min_by(|a, b| {
                    dist(me, a).total_cmp(&dist(me, b))
                })
                .map(|p| p.id);

            if tag.is_some() {
                brain.tag_cooldown = TAG_RETRY_TICKS;
            }
        }

        match brain.target.and_then(|id| players.get(&id)) {
            Some(target) => {
                let aim = predicted_position(me, target, inputs);
                let to = normalized((
                    aim.0 - me.position.x,
                    aim.1 - me.position.y,
                ));
                let wall = wall_push(me.position.x, me.position.y);

                steer = (
                    to.0 + sep.0 * 0.6 + wall.0 * 0.3,
                    to.1 + sep.1 * 0.6 + wall.1 * 0.3,
                );
                running = can_sprint && dist(me, target) > 100.0;
            }
            None => {
                steer = wander(me, brain, sep);
            }
        }
    } else {
        brain.target = None;

        let threat = players
            .values()
            .find(|p| p.is_it && p.id != me.id);

        match threat {
            Some(it) if dist(me, it) < FLEE_RADIUS => {
                let it_pos = predicted_position(me, it, inputs);
                let away = normalized((
                    me.position.x - it_pos.0,
                    me.position.y - it_pos.1,
                ));
                let wall = wall_push(me.position.x, me.position.y);
                let wall_mag = len(wall);

                // When pinned against a wall, slide along it toward the
                // middle of the map rather than running into the corner.
                let tangent = {
                    let t = (-away.1, away.0);
                    let to_center = (
                        WORLD_WIDTH / 2.0 - me.position.x,
                        WORLD_HEIGHT / 2.0 - me.position.y,
                    );
                    if t.0 * to_center.0 + t.1 * to_center.1 >= 0.0 {
                        t
                    } else {
                        (-t.0, -t.1)
                    }
                };

                steer = (
                    away.0
                        + wall.0 * 2.5
                        + tangent.0 * wall_mag * 1.5
                        + sep.0 * 0.5,
                    away.1
                        + wall.1 * 2.5
                        + tangent.1 * wall_mag * 1.5
                        + sep.1 * 0.5,
                );
                running = can_sprint
                    && dist(me, it) < SPRINT_FLEE_RADIUS;
            }
            _ => {
                steer = wander(me, brain, sep);
            }
        }
    }

    let dir = normalized(steer);

    BotDecision {
        dx: dir.0,
        dy: dir.1,
        running: running && (dir.0 != 0.0 || dir.1 != 0.0),
        tag,
    }
}

/// Stroll toward a random point, then pick another.
fn wander(me: &Player, brain: &mut BotBrain, sep: Vec2) -> Vec2 {
    let mut rng = rand::rng();

    let arrived = brain
        .wander_to
        .map(|(x, y)| {
            len((x - me.position.x, y - me.position.y)) < WANDER_ARRIVE
        })
        .unwrap_or(true);

    if arrived || rng.random_bool(0.005) {
        brain.wander_to = Some((
            rng.random_range(200.0..WORLD_WIDTH - 200.0),
            rng.random_range(200.0..WORLD_HEIGHT - 200.0),
        ));
    }

    let (x, y) = brain.wander_to.unwrap();
    let to = normalized((x - me.position.x, y - me.position.y));

    (to.0 + sep.0 * 0.6, to.1 + sep.1 * 0.6)
}
