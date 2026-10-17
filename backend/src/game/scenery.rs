//! Solid-looking schoolyard props, mirrored from the client's procedural yard
//! (`phaser-tag-client/src/schoolyard.ts`, mulberry32 seed 2026).
//!
//! The client does not collide with these — they are drawn only — but a kid
//! should not *appear* inside a trunk, bush, bench, or picnic table. Spawn
//! sampling rejects any centre that would overlap one. The fence itself is the
//! wall inset in `world`, plus `SPAWN_MARGIN`; it is not a prop here.
//!
//! Footprints match the sprites' origins (`0.5, 0.85`) and the canopy sizes
//! passed to `tallProp`, expanded by `PLAYER_RADIUS` so the player's centre
//! stays clear of the art.

use std::sync::OnceLock;

use super::world::{PLAYER_RADIUS, WALL_BOTTOM, WALL_LEFT, WALL_RIGHT, WALL_TOP, WORLD_HEIGHT, WORLD_WIDTH};

/// Canopy half-width from `placeTree` plus the player radius.
const TREE_CLEAR: f64 = 58.0 + PLAYER_RADIUS as f64;
/// Canopy half-width from `placeBush` plus the player radius.
const BUSH_CLEAR: f64 = 38.0 + PLAYER_RADIUS as f64;

#[derive(Clone, Copy)]
enum Obstacle {
    /// Player centre must stay at least `r` away from `(x, y)`.
    Circle { x: f64, y: f64, r: f64 },
    /// Inclusive AABB already expanded by the player radius.
    Rect { min_x: f64, min_y: f64, max_x: f64, max_y: f64 },
}

impl Obstacle {
    fn hits(self, x: f64, y: f64) -> bool {
        match self {
            Obstacle::Circle { x: cx, y: cy, r } => {
                let dx = x - cx;
                let dy = y - cy;
                dx * dx + dy * dy < r * r
            }
            Obstacle::Rect {
                min_x,
                min_y,
                max_x,
                max_y,
            } => x >= min_x && x <= max_x && y >= min_y && y <= max_y,
        }
    }
}

/// True when a player centred at `(x, y)` would overlap a tree, bush, bench,
/// or picnic table.
pub fn blocks_spawn(x: f32, y: f32) -> bool {
    let x = f64::from(x);
    let y = f64::from(y);
    obstacles().iter().any(|obstacle| obstacle.hits(x, y))
}

fn obstacles() -> &'static [Obstacle] {
    static OBSTACLES: OnceLock<Vec<Obstacle>> = OnceLock::new();
    OBSTACLES.get_or_init(build_obstacles)
}

/// Same generator as `createSchoolyard`: seed 2026, then the fixed benches
/// and picnic tables (those are not gated by the yard's `free` check).
fn build_obstacles() -> Vec<Obstacle> {
    let mut rnd = mulberry32(2026);
    let mut out = Vec::new();

    let yard_left = f64::from(WALL_LEFT);
    let yard_top = f64::from(WALL_TOP) + 2.0 * f64::from(PLAYER_RADIUS);
    let yard_right = f64::from(WORLD_WIDTH - WALL_RIGHT);
    let yard_bottom = f64::from(WORLD_HEIGHT - WALL_BOTTOM);

    let areas = [
        Rect {
            x: 256.0,
            y: 512.0,
            w: 1920.0,
            h: 1140.0,
        },
        Rect {
            x: 2816.0,
            y: 512.0,
            w: 1900.0,
            h: 900.0,
        },
        Rect {
            x: 512.0,
            y: 2816.0,
            w: 1100.0,
            h: 1000.0,
        },
        Rect {
            x: 3072.0,
            y: 3072.0,
            w: 1300.0,
            h: 1000.0,
        },
    ];

    let mut edge: Vec<(f64, f64)> = Vec::new();
    let mut t = yard_left + 120.0;
    while t < yard_right - 120.0 {
        let inset = 80.0 + rnd() * 50.0;
        edge.push((t, yard_top + inset));
        edge.push((t + 60.0, yard_bottom - inset));
        t += 210.0 + rnd() * 120.0;
    }
    t = yard_top + 120.0;
    while t < yard_bottom - 120.0 {
        let inset = 80.0 + rnd() * 50.0;
        edge.push((yard_left + inset, t));
        edge.push((yard_right - inset, t + 60.0));
        t += 210.0 + rnd() * 120.0;
    }
    for (x, y) in edge {
        if !prop_free(&areas, x, y, 70.0) {
            continue;
        }
        if rnd() < 0.62 {
            out.push(Obstacle::Circle {
                x,
                y,
                r: TREE_CLEAR,
            });
        } else {
            out.push(Obstacle::Circle {
                x,
                y,
                r: BUSH_CLEAR,
            });
        }
    }

    let mut placed = 0;
    let mut i = 0;
    while i < 400 && placed < 70 {
        i += 1;
        let x = 300.0 + rnd() * (f64::from(WORLD_WIDTH) - 600.0);
        let y = 300.0 + rnd() * (f64::from(WORLD_HEIGHT) - 600.0);
        if !prop_free(&areas, x, y, 110.0) {
            continue;
        }
        placed += 1;
        if rnd() < 0.55 {
            out.push(Obstacle::Circle {
                x,
                y,
                r: TREE_CLEAR,
            });
        } else {
            for k in 0..3 {
                let by = y + (rnd() - 0.5) * 20.0;
                out.push(Obstacle::Circle {
                    x: x + (k as f64 - 1.0) * 46.0,
                    y: by,
                    r: BUSH_CLEAR,
                });
            }
        }
    }

    // Benches: texture 120×60, origin (0.5, 0.85).
    const BENCHES: [(f64, f64); 12] = [
        (500.0, 1720.0),
        (800.0, 1720.0),
        (1500.0, 1720.0),
        (1800.0, 1720.0),
        (3300.0, 1480.0),
        (3700.0, 1480.0),
        (4100.0, 1480.0),
        (3200.0, 4140.0),
        (3600.0, 4140.0),
        (4000.0, 4140.0),
        (1300.0, 3900.0),
        (800.0, 3900.0),
    ];
    for (x, y) in BENCHES {
        out.push(sprite_rect(x, y, 120.0, 60.0));
    }

    // Picnic tables: texture 150×120, origin (0.5, 0.85).
    for i in 0..6 {
        let x = 2700.0 + (i % 3) as f64 * 230.0;
        let y = 4440.0 + (i / 3) as f64 * 190.0;
        out.push(sprite_rect(x, y, 150.0, 120.0));
    }

    out
}

#[derive(Clone, Copy)]
struct Rect {
    x: f64,
    y: f64,
    w: f64,
    h: f64,
}

impl Rect {
    fn overlaps(self, x: f64, y: f64, pad: f64) -> bool {
        x > self.x - pad && x < self.x + self.w + pad && y > self.y - pad && y < self.y + self.h + pad
    }
}

/// Client `free()`: not on a court/track/diamond/playground, and outside the
/// open clearing the yard still keeps around the old fixed spawn (400, 300).
fn prop_free(areas: &[Rect], x: f64, y: f64, pad: f64) -> bool {
    !areas.iter().any(|r| r.overlaps(x, y, pad)) && hypot(x - 400.0, y - 300.0) > 160.0
}

fn hypot(x: f64, y: f64) -> f64 {
    (x * x + y * y).sqrt()
}

/// Axis-aligned sprite box expanded by the player radius. `origin_y` is 0.85.
fn sprite_rect(x: f64, y: f64, w: f64, h: f64) -> Obstacle {
    let pad = f64::from(PLAYER_RADIUS);
    Obstacle::Rect {
        min_x: x - w * 0.5 - pad,
        max_x: x + w * 0.5 + pad,
        min_y: y - h * 0.85 - pad,
        max_y: y + h * 0.15 + pad,
    }
}

/// mulberry32, matching the client's `schoolyard.ts` (JS `Math.imul` / `>>>`).
fn mulberry32(seed: u32) -> impl FnMut() -> f64 {
    let mut seed = seed as i32;
    move || {
        seed = seed.wrapping_add(0x6d2b79f5_u32 as i32);
        let mut t = seed ^ ((seed as u32) >> 15) as i32;
        t = t.wrapping_mul(seed | 1);
        let mixed = t ^ ((t as u32) >> 7) as i32;
        t = t.wrapping_add(mixed.wrapping_mul(t | 61)) ^ t;
        let bits = (t as u32) ^ ((t as u32) >> 14);
        f64::from(bits) / 4294967296.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prop_layout_matches_the_client_yard() {
        let obstacles = build_obstacles();
        // 201 foliage props from the client's loops, plus 12 benches and 6 picnics.
        assert_eq!(obstacles.len(), 201 + 12 + 6);
        let circle = |obstacle: &Obstacle| match *obstacle {
            Obstacle::Circle { x, y, r } => (x, y, r),
            Obstacle::Rect { .. } => panic!("expected a tree or bush"),
        };
        let (x, y, r) = circle(&obstacles[0]);
        assert!((x - 160.0).abs() < 1e-9 && (y - 248.77038496686146).abs() < 1e-9);
        assert!((r - TREE_CLEAR).abs() < 1e-9);
        let (x, y, _) = circle(&obstacles[2]);
        assert!((x - 467.01953751966357).abs() < 1e-9);
        assert!((y - 4846.9421275379136).abs() < 1e-9);
        let (x, y, r) = circle(&obstacles[200]);
        assert!((x - 1587.7804673314095).abs() < 1e-6, "{x}");
        assert!((y - 2502.7065032348037).abs() < 1e-6, "{y}");
        assert!((r - BUSH_CLEAR).abs() < 1e-9);
        // A player standing on that bush is rejected; the old clearing is not.
        assert!(blocks_spawn(x as f32, y as f32));
        assert!(!blocks_spawn(400.0, 300.0));
    }

    #[test]
    fn mulberry_matches_the_client_prng() {
        // First outputs of mulberry32(2026), from the same formula in JS.
        let mut rnd = mulberry32(2026);
        let got: Vec<f64> = (0..4).map(|_| rnd()).collect();
        let want = [
            0.455407699337229133,
            0.308496145997196436,
            0.661157449241727591,
            0.618475218303501606,
        ];
        for (g, w) in got.iter().zip(want) {
            assert!((g - w).abs() < 1e-12, "{g} != {w}");
        }
    }
}
