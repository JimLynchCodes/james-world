use super::player::Player;

pub const MAX_ENERGY: f32 = 100.0;

// Normal player
pub const STANDING_REGEN: f32 = 25.0;
pub const WALKING_REGEN: f32 = 5.0;
pub const RUNNING_DRAIN: f32 = 20.0;

// It
pub const IT_STANDING_REGEN: f32 = 30.0;
pub const IT_WALKING_REGEN: f32 = 7.5;
pub const IT_RUNNING_DRAIN: f32 = 15.0;

pub const MIN_RUNNING_ENERGY: f32 = 10.0;
pub const FULL_SPEED_THRESHOLD: f32 = 50.0;

// Movement
pub const WALK_SPEED: f32 = 200.0;
pub const RUN_SPEED: f32 = 350.0;

// It gets a modest permanent speed advantage.
pub const IT_SPEED_MULTIPLIER: f32 = 1.10;

// The old "it" gets this temporary escape boost.
pub const ESCAPE_BOOST_MULTIPLIER: f32 = 1.25;

pub fn update_energy(
    player: &mut Player,
    moving: bool,
    wants_to_run: bool,
    dt: f32,
) {
    if wants_to_run
        && moving
        && player.energy >= MIN_RUNNING_ENERGY
    {
        player.is_running = true;

        let drain = if player.is_it {
            IT_RUNNING_DRAIN
        } else {
            RUNNING_DRAIN
        };

        player.energy -= drain * dt;

        if player.energy < 0.0 {
            player.energy = 0.0;
        }
    } else {
        player.is_running = false;

        let regen = if moving {
            if player.is_it {
                IT_WALKING_REGEN
            } else {
                WALKING_REGEN
            }
        } else if player.is_it {
            IT_STANDING_REGEN
        } else {
            STANDING_REGEN
        };

        player.energy =
            (player.energy + regen * dt)
                .min(MAX_ENERGY);
    }
}

pub fn running_speed_multiplier(
    energy: f32,
) -> f32 {
    if energy >= FULL_SPEED_THRESHOLD {
        1.0
    } else {
        0.5 + 0.5 * (energy / FULL_SPEED_THRESHOLD)
    }
}