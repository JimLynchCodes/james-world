//! Server-controlled "bot" players.
//!
//! Bots only exist while at least one human is connected (see
//! `World::sync_bots`). Each tick, every bot runs `think`, which turns the
//! current world state into a movement input (and optionally a tag attempt),
//! exactly like a human's `MoveInput` would.
//!
//! * A bot that is **IT** hunts. It scores every taggable player by distance,
//!   prefers humans (more so at higher skill), prefers tired targets (they
//!   can't sprint away), sticks with its current target to avoid dithering,
//!   and aims ahead of a moving target (lead pursuit) instead of where it is.
//! * A bot that is **not IT** runs away from IT (mostly from where IT is now,
//!   with a little lead at higher skill), pushed off walls, sliding along
//!   them when cornered, and otherwise wanders.
//! * Bots manage their stamina (stop sprinting when drained, resume once
//!   recovered) and push apart from each other so they don't stack.
//!
//! Each bot is born with a [`BotSkill`]. The same decisions run for every
//! skill; the profile scales speed, reaction delay, aim, tagging, and stamina
//! so a room has a spread of opponents and none of them play perfectly.

use std::collections::HashMap;

use rand::Rng;
use uuid::Uuid;

use super::{
    energy,
    player::Player,
    world::{PlayerInput, MAX_X, MAX_Y, MIN_X, MIN_Y, WORLD_HEIGHT, WORLD_WIDTH},
};

pub const BOT_COUNT: usize = 3;

/// The current target looks this much closer, so bots don't flip-flop.
const CURRENT_TARGET_BONUS: f32 = 0.8;
/// Extra attractiveness of a target with no energy left (up to +30% farther).
const TIRED_TARGET_WEIGHT: f32 = 0.3;

const WALL_MARGIN: f32 = 350.0;
const SEPARATION_RADIUS: f32 = 90.0;
const WANDER_ARRIVE: f32 = 80.0;

/// How sharp a bot is. Assigned once, when that bot is spawned.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BotSkill {
    Easy,
    Medium,
    Hard,
}

impl BotSkill {
    pub fn profile(self) -> SkillProfile {
        match self {
            // Slow, late to react, short tag reach. A sprinting human
            // pulls away, and an IT human runs them down.
            Self::Easy => SkillProfile {
                speed_scale: 0.78,
                reaction_ticks: 12,
                aim_jitter: deg(18.0),
                lead: 0.25,
                flee_lead: 0.0,
                tag_range: 32.0,
                tag_dwell_ticks: 6,
                tag_retry_ticks: 18,
                retarget_ticks: 36,
                human_preference: 0.88,
                flee_radius: 420.0,
                sprint_flee_radius: 180.0,
                chase_sprint_beyond: 240.0,
                exhausted_below: 34.0,
                recovered_above: 70.0,
                flee_wall: 1.1,
                flee_tangent: 0.5,
            },
            // Close to a fair race: a little slower than the human in a
            // straight sprint, and slow enough to turn that a juke works.
            Self::Medium => SkillProfile {
                speed_scale: 0.88,
                reaction_ticks: 7,
                aim_jitter: deg(9.0),
                lead: 0.55,
                flee_lead: 0.2,
                tag_range: 38.0,
                tag_dwell_ticks: 4,
                tag_retry_ticks: 14,
                retarget_ticks: 18,
                human_preference: 0.72,
                flee_radius: 560.0,
                sprint_flee_radius: 270.0,
                chase_sprint_beyond: 150.0,
                exhausted_below: 22.0,
                recovered_above: 52.0,
                flee_wall: 1.8,
                flee_tangent: 1.05,
            },
            // Still a threat in a straight line, but short of the old
            // perfect intercept: small aim error, a short hesitation, and
            // a tag reach inside the server maximum of 50.
            Self::Hard => SkillProfile {
                speed_scale: 0.94,
                reaction_ticks: 3,
                aim_jitter: deg(4.0),
                lead: 0.85,
                flee_lead: 0.35,
                tag_range: 44.0,
                tag_dwell_ticks: 2,
                tag_retry_ticks: 10,
                retarget_ticks: 9,
                human_preference: 0.58,
                flee_radius: 700.0,
                sprint_flee_radius: 340.0,
                chase_sprint_beyond: 100.0,
                exhausted_below: 14.0,
                recovered_above: 40.0,
                flee_wall: 2.5,
                flee_tangent: 1.5,
            },
        }
    }
}

/// Knobs for one [`BotSkill`]. Every level is short of a perfect player:
/// `speed_scale` is below 1 (humans are 1), and `tag_range` is below the
/// server's tag distance of 50.
#[derive(Debug, Clone, Copy)]
pub struct SkillProfile {
    /// Multiplier on this bot's movement speed.
    pub speed_scale: f32,
    /// Ticks a heading is held before it is recomputed (reaction delay).
    pub reaction_ticks: u32,
    /// Max aim error in radians, applied to chase and flee headings.
    pub aim_jitter: f32,
    /// Fraction of a full one-second lead-pursuit intercept to aim at
    /// while chasing.
    pub lead: f32,
    /// Same idea while fleeing. Kept small: leading the chaser shortens the
    /// away-vector, and a tiny side offset then becomes a hard sideways dodge.
    pub flee_lead: f32,
    /// How close someone must be before this bot tries to tag them.
    pub tag_range: f32,
    /// Consecutive in-range ticks required before a tag is attempted.
    pub tag_dwell_ticks: u32,
    /// Ticks to wait after a tag attempt before trying again.
    pub tag_retry_ticks: u32,
    /// Ticks between target re-picks while the current target is still valid.
    pub retarget_ticks: u32,
    /// Humans look this much closer when scoring a chase target (lower
    /// prefers humans more).
    pub human_preference: f32,
    /// Start fleeing when IT is inside this radius.
    pub flee_radius: f32,
    /// Sprint while fleeing only when IT is inside this radius.
    pub sprint_flee_radius: f32,
    /// Sprint while chasing only when the target is beyond this distance.
    /// Inside it the bot walks, so a tag can be sidestepped.
    pub chase_sprint_beyond: f32,
    /// Stop sprinting at or below this energy.
    pub exhausted_below: f32,
    /// Resume sprinting once energy has recovered past this.
    pub recovered_above: f32,
    /// Weight of the wall-avoidance push while fleeing.
    pub flee_wall: f32,
    /// Weight of sliding along a wall while fleeing.
    pub flee_tangent: f32,
}

fn deg(degrees: f32) -> f32 {
    degrees.to_radians()
}

#[derive(Debug)]
pub struct BotBrain {
    pub target: Option<Uuid>,
    pub wander_to: Option<(f32, f32)>,
    pub tag_cooldown: u32,
    pub exhausted: bool,
    pub skill: BotSkill,
    /// Heading locked in until the reaction delay elapses.
    held_dx: f32,
    held_dy: f32,
    react_in: u32,
    retarget_in: u32,
    aim_bias: f32,
    tag_dwell: u32,
    tag_dwell_id: Option<Uuid>,
}

impl BotBrain {
    pub fn with_skill(skill: BotSkill) -> Self {
        Self {
            target: None,
            wander_to: None,
            tag_cooldown: 0,
            exhausted: false,
            skill,
            held_dx: 0.0,
            held_dy: 0.0,
            react_in: 0,
            retarget_in: 0,
            aim_bias: 0.0,
            tag_dwell: 0,
            tag_dwell_id: None,
        }
    }
}

impl Default for BotBrain {
    fn default() -> Self {
        Self::with_skill(BotSkill::Medium)
    }
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

fn rotate(v: Vec2, radians: f32) -> Vec2 {
    if radians.abs() < 1e-5 {
        return v;
    }
    let (s, c) = radians.sin_cos();
    (v.0 * c - v.1 * s, v.0 * s + v.1 * c)
}

fn dist(a: &Player, b: &Player) -> f32 {
    len((a.position.x - b.position.x, a.position.y - b.position.y))
}

/// Pick who an IT bot should chase. Lower score wins.
///
/// `human_preference` is how much closer a human looks (see [`SkillProfile`]).
pub fn choose_target(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    current: Option<Uuid>,
    human_preference: f32,
) -> Option<Uuid> {
    players
        .values()
        .filter(|p| p.id != me.id && p.tag_immunity_ticks == 0)
        .map(|p| {
            let mut score = dist(me, p);

            if !p.is_bot {
                score *= human_preference;
            }

            score *= 1.0 + TIRED_TARGET_WEIGHT * (p.energy / energy::MAX_ENERGY).clamp(0.0, 1.0);

            if Some(p.id) == current {
                score *= CURRENT_TARGET_BONUS;
            }

            (p.id, score)
        })
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(id, _)| id)
}

/// Where a player's velocity is taking them, in pixels per second.
fn velocity_of(p: &Player, inputs: &HashMap<Uuid, PlayerInput>) -> Vec2 {
    let Some(input) = inputs.get(&p.id) else {
        return (0.0, 0.0);
    };

    let dir = normalized((input.dx, input.dy));

    let speed = if input.running && p.energy >= energy::MIN_RUNNING_ENERGY {
        energy::RUN_SPEED * energy::running_speed_multiplier(p.energy)
    } else {
        energy::WALK_SPEED
    };

    (dir.0 * speed, dir.1 * speed)
}

/// Aim point that leads a moving target. `lead` is the fraction of a full
/// intercept (capped at 1 second) the bot actually aims at.
fn predicted_position(
    me: &Player,
    target: &Player,
    inputs: &HashMap<Uuid, PlayerInput>,
    lead: f32,
) -> Vec2 {
    let v = velocity_of(target, inputs);
    let d = dist(me, target);
    let t = (d / energy::RUN_SPEED).min(1.0) * lead.clamp(0.0, 1.0);

    (
        (target.position.x + v.0 * t).clamp(MIN_X, MAX_X),
        (target.position.y + v.1 * t).clamp(MIN_Y, MAX_Y),
    )
}

/// Pushes away from nearby walls (the fence, not the world edge); magnitude
/// grows quadratically as a wall nears.
fn wall_push(x: f32, y: f32) -> Vec2 {
    let f = |d: f32| {
        let k = ((WALL_MARGIN - d) / WALL_MARGIN).clamp(0.0, 1.0);
        k * k
    };

    (f(x - MIN_X) - f(MAX_X - x), f(y - MIN_Y) - f(MAX_Y - y))
}

fn separation(me: &Player, players: &HashMap<Uuid, Player>) -> Vec2 {
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

/// Slide along a wall toward the middle of the map when pinned in a corner.
fn wall_tangent(away: Vec2, me: &Player) -> Vec2 {
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
}

fn nudge_aim_bias(brain: &mut BotBrain, max_abs: f32) {
    if max_abs <= 0.0 {
        brain.aim_bias = 0.0;
        return;
    }
    // A new error each decision, opposite the previous one. A sticky bias
    // weaves into a spiral and the bot dodges sideways instead of running away.
    let mut rng = rand::rng();
    let sign = if brain.aim_bias >= 0.0 { -1.0 } else { 1.0 };
    let mag = rng.random_range(0.45..1.0) * max_abs;
    brain.aim_bias = sign * mag;
}

fn refresh_target(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    brain: &mut BotBrain,
    profile: SkillProfile,
) {
    let current_ok = brain
        .target
        .and_then(|id| players.get(&id))
        .is_some_and(|p| p.tag_immunity_ticks == 0);

    if brain.retarget_in == 0 || !current_ok {
        brain.target = choose_target(me, players, brain.target, profile.human_preference);
        brain.retarget_in = profile.retarget_ticks;
    } else {
        brain.retarget_in = brain.retarget_in.saturating_sub(1);
    }
}

/// Closest taggable player inside this bot's reach.
fn tag_candidate(me: &Player, players: &HashMap<Uuid, Player>, tag_range: f32) -> Option<Uuid> {
    players
        .values()
        .filter(|p| p.id != me.id && p.tag_immunity_ticks == 0 && dist(me, p) <= tag_range)
        .min_by(|a, b| dist(me, a).total_cmp(&dist(me, b)))
        .map(|p| p.id)
}

fn update_tag_dwell(brain: &mut BotBrain, candidate: Option<Uuid>) {
    match candidate {
        Some(id) if brain.tag_dwell_id == Some(id) => {
            brain.tag_dwell = brain.tag_dwell.saturating_add(1);
        }
        Some(id) => {
            brain.tag_dwell_id = Some(id);
            brain.tag_dwell = 1;
        }
        None => {
            brain.tag_dwell_id = None;
            brain.tag_dwell = 0;
        }
    }
}

fn should_sprint(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    brain: &BotBrain,
    profile: SkillProfile,
) -> bool {
    if me.is_it {
        return brain
            .target
            .and_then(|id| players.get(&id))
            .is_some_and(|target| dist(me, target) > profile.chase_sprint_beyond);
    }

    players
        .values()
        .find(|p| p.is_it && p.id != me.id)
        .is_some_and(|it| {
            let d = dist(me, it);
            d < profile.flee_radius && d < profile.sprint_flee_radius
        })
}

fn desired_steer(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    inputs: &HashMap<Uuid, PlayerInput>,
    brain: &mut BotBrain,
    profile: SkillProfile,
    homing: bool,
) -> Vec2 {
    let sep = separation(me, players);

    if me.is_it {
        match brain.target.and_then(|id| players.get(&id)) {
            Some(target) => {
                let aim = predicted_position(me, target, inputs, profile.lead);
                let mut to = normalized((aim.0 - me.position.x, aim.1 - me.position.y));
                if !homing {
                    let d = dist(me, target);
                    // Full error in the open; nearly straight once a tag is close,
                    // so a held heading still arrives on a stationary target.
                    let jitter = brain.aim_bias * (d / (d + 100.0));
                    to = rotate(to, jitter);
                }
                let wall = wall_push(me.position.x, me.position.y);
                (
                    to.0 + sep.0 * 0.6 + wall.0 * 0.3,
                    to.1 + sep.1 * 0.6 + wall.1 * 0.3,
                )
            }
            None => wander(me, brain, sep),
        }
    } else {
        let threat = players.values().find(|p| p.is_it && p.id != me.id);

        match threat {
            Some(it) if dist(me, it) < profile.flee_radius => {
                let it_pos = predicted_position(me, it, inputs, profile.flee_lead);
                let away = rotate(
                    normalized((me.position.x - it_pos.0, me.position.y - it_pos.1)),
                    brain.aim_bias,
                );
                let wall = wall_push(me.position.x, me.position.y);
                let wall_mag = len(wall);
                let tangent = wall_tangent(away, me);

                (
                    away.0
                        + wall.0 * profile.flee_wall
                        + tangent.0 * wall_mag * profile.flee_tangent
                        + sep.0 * 0.5,
                    away.1
                        + wall.1 * profile.flee_wall
                        + tangent.1 * wall_mag * profile.flee_tangent
                        + sep.1 * 0.5,
                )
            }
            _ => wander(me, brain, sep),
        }
    }
}

pub fn think(
    me: &Player,
    players: &HashMap<Uuid, Player>,
    inputs: &HashMap<Uuid, PlayerInput>,
    brain: &mut BotBrain,
) -> BotDecision {
    brain.tag_cooldown = brain.tag_cooldown.saturating_sub(1);

    let profile = brain.skill.profile();

    if me.energy < profile.exhausted_below {
        brain.exhausted = true;
    } else if me.energy > profile.recovered_above {
        brain.exhausted = false;
    }
    let can_sprint = !brain.exhausted;

    // In tag range the bot homes every tick. Out in the open it keeps its
    // last heading for `reaction_ticks`, which is what makes a juke work.
    let mut tag = None;
    let homing;

    if me.is_it {
        refresh_target(me, players, brain, profile);

        let candidate = tag_candidate(me, players, profile.tag_range);
        update_tag_dwell(brain, candidate);
        homing = brain.tag_dwell > 0;

        if brain.tag_cooldown == 0 && brain.tag_dwell >= profile.tag_dwell_ticks {
            tag = brain.tag_dwell_id;
            if tag.is_some() {
                brain.tag_cooldown = profile.tag_retry_ticks;
                // Misses have to be re-earned; a stationary target is still tagged.
                brain.tag_dwell = 0;
            }
        }
    } else {
        brain.target = None;
        brain.tag_dwell = 0;
        brain.tag_dwell_id = None;
        homing = false;
    }

    let held = brain.held_dx != 0.0 || brain.held_dy != 0.0;
    let steer = if !homing && brain.react_in > 0 && held {
        brain.react_in -= 1;
        (brain.held_dx, brain.held_dy)
    } else {
        if !homing {
            nudge_aim_bias(brain, profile.aim_jitter);
        }
        let desired = desired_steer(me, players, inputs, brain, profile, homing);
        let dir = normalized(desired);
        brain.held_dx = dir.0;
        brain.held_dy = dir.1;
        brain.react_in = if homing { 0 } else { profile.reaction_ticks };
        dir
    };

    let moving = steer.0 != 0.0 || steer.1 != 0.0;

    BotDecision {
        dx: steer.0,
        dy: steer.1,
        running: running_now(can_sprint, moving, me, players, brain, profile),
        tag,
    }
}

fn running_now(
    can_sprint: bool,
    moving: bool,
    me: &Player,
    players: &HashMap<Uuid, Player>,
    brain: &BotBrain,
    profile: SkillProfile,
) -> bool {
    can_sprint && moving && should_sprint(me, players, brain, profile)
}

/// Stroll toward a random point, then pick another.
fn wander(me: &Player, brain: &mut BotBrain, sep: Vec2) -> Vec2 {
    let mut rng = rand::rng();

    let arrived = brain
        .wander_to
        .map(|(x, y)| len((x - me.position.x, y - me.position.y)) < WANDER_ARRIVE)
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
