use super::player::Player;

pub const MAX_ENERGY: f32 = 100.0;
pub const STANDING_REGEN: f32 = 25.0;
pub const WALKING_REGEN: f32 = 5.0;
pub const RUNNING_DRAIN: f32 = 20.0;

pub const MIN_RUNNING_ENERGY: f32 = 10.0;
pub const FULL_SPEED_THRESHOLD: f32 = 50.0;

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

        player.energy -= RUNNING_DRAIN * dt;

        if player.energy < 0.0 {
            player.energy = 0.0;
        }
    } else {
        player.is_running = false;

        let regen = if moving {
            WALKING_REGEN
        } else {
            STANDING_REGEN
        };

        player.energy =
            (player.energy + regen * dt).min(MAX_ENERGY);
    }
}

pub fn running_speed_multiplier(energy: f32) -> f32 {
    if energy >= FULL_SPEED_THRESHOLD {
        1.0
    } else {
        0.5 + 0.5 * (energy / FULL_SPEED_THRESHOLD)
    }
}