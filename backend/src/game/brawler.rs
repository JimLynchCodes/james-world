//! Side-scrolling co-op beat-'em-up room (Simpsons / TMNT arcade style).
//!
//! Created fresh when the first player joins. Later joiners spawn just behind
//! the furthest-right player. Players are a team (no friendly fire). When the
//! last player leaves, the arena resets so the next join starts clean.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::{cosmetic::Cosmetic, skin::Skin};

/// Horizontal length of the scroller.
pub const WORLD_W: f32 = 7000.0;
/// Vertical world extent (camera bounds height). Keep in sync with client BRAWLER.h.
pub const WORLD_H: f32 = 540.0;
/// Vertical playable band (lane): just under the HUD/horizon down to near the bottom edge.
pub const LANE_TOP: f32 = 72.0;
pub const LANE_BOTTOM: f32 = 520.0;
pub const GROUND_Y: f32 = 300.0;

pub const PLAYER_MAX_HP: f32 = 100.0;
pub const PLAYER_SPEED: f32 = 160.0;
pub const PLAYER_RADIUS: f32 = 14.0;

pub const ATTACK_RANGE: f32 = 52.0;
pub const ATTACK_DAMAGE: f32 = 22.0;
/// Active strike window — roughly the tag clip length.
pub const ATTACK_DURATION_S: f32 = 0.32;
/// Must be <= ATTACK_DURATION_S so rapid presses chain (no dead gap after the anim).
pub const ATTACK_COOLDOWN_S: f32 = 0.22;
/// Vertical hit slop — taller lane needs more Y tolerance.
pub const ATTACK_HIT_Y: f32 = 56.0;

pub const SPAWN_BEHIND: f32 = 70.0;
const START_X: f32 = 80.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EnemyKind {
    Grunt,
    Bruiser,
    Swift,
    /// Mid-run mini-boss (about halfway).
    Elite,
    Boss,
}

impl EnemyKind {
    fn max_hp(self) -> f32 {
        match self {
            Self::Grunt => 40.0,
            Self::Bruiser => 90.0,
            Self::Swift => 30.0,
            Self::Elite => 240.0,
            Self::Boss => 520.0,
        }
    }

    fn damage(self) -> f32 {
        match self {
            Self::Grunt => 8.0,
            Self::Bruiser => 16.0,
            Self::Swift => 10.0,
            Self::Elite => 18.0,
            Self::Boss => 22.0,
        }
    }

    fn speed(self) -> f32 {
        match self {
            Self::Grunt => 55.0,
            Self::Bruiser => 40.0,
            Self::Swift => 95.0,
            Self::Elite => 58.0,
            Self::Boss => 70.0,
        }
    }

    #[allow(dead_code)]
    fn radius(self) -> f32 {
        match self {
            Self::Grunt => 14.0,
            Self::Bruiser => 20.0,
            Self::Swift => 12.0,
            Self::Elite => 26.0,
            Self::Boss => 36.0,
        }
    }

    fn attack_cooldown(self) -> f32 {
        match self {
            Self::Grunt => 1.1,
            Self::Bruiser => 1.4,
            Self::Swift => 0.85,
            Self::Elite => 1.0,
            Self::Boss => 0.95,
        }
    }

    fn attack_range(self) -> f32 {
        match self {
            Self::Grunt => 28.0,
            Self::Bruiser => 34.0,
            Self::Swift => 24.0,
            Self::Elite => 40.0,
            Self::Boss => 48.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct BrawlerPlayer {
    pub id: Uuid,
    pub name: String,
    pub skin: Skin,
    pub cosmetic: Cosmetic,
    pub x: f32,
    pub y: f32,
    pub hp: f32,
    pub facing: f32,
    pub moving: bool,
    pub attacking: bool,
    pub attack_timer: f32,
    pub attack_cooldown: f32,
    /// Increments on every swing start so clients can restart the anim mid-clip.
    pub attack_seq: u32,
    /// Fresh press arrived while cooldown was active — fire when cooldown ends.
    pub attack_buffered: bool,
    pub invuln: f32,
    pub dead: bool,
    /// Input for this tick.
    pub input_dx: f32,
    pub input_dy: f32,
    pub input_attack: bool,
    /// Previous tick's attack input — rising edge only starts a swing.
    pub attack_held_prev: bool,
}

#[derive(Debug, Clone)]
pub struct Enemy {
    pub id: u32,
    pub kind: EnemyKind,
    pub x: f32,
    pub y: f32,
    pub hp: f32,
    pub facing: f32,
    pub attack_cooldown: f32,
    pub hit_flash: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrawlerPlayerSnap {
    pub id: Uuid,
    pub name: String,
    pub skin: Skin,
    pub cosmetic: Cosmetic,
    pub x: f32,
    pub y: f32,
    pub hp: f32,
    pub max_hp: f32,
    pub facing: f32,
    pub moving: bool,
    pub attacking: bool,
    pub attack_seq: u32,
    pub dead: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnemySnap {
    pub id: u32,
    pub kind: EnemyKind,
    pub x: f32,
    pub y: f32,
    pub hp: f32,
    pub max_hp: f32,
    pub facing: f32,
    pub hit_flash: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrawlerSnapshot {
    pub players: Vec<BrawlerPlayerSnap>,
    pub enemies: Vec<EnemySnap>,
    pub wave: u32,
    pub boss_hp: Option<f32>,
    pub boss_max_hp: Option<f32>,
    pub won: bool,
    /// Arcade "GO →" after a wave is cleared, until the next segment starts.
    pub show_go: bool,
    /// While fighting, players/camera are clamped to this band (inclusive).
    pub lock_left: Option<f32>,
    pub lock_right: Option<f32>,
    /// Leftmost camera/player fence — never scrolls or walks back past this.
    pub scroll_min: f32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BrawlerEvent {
    PlayerDied { player_id: Uuid },
    Won { player_ids: Vec<Uuid> },
}

/// One shared co-op arena. Empty = reset / ready for a fresh run.
#[derive(Debug, Default)]
pub struct BrawlerWorld {
    pub players: HashMap<Uuid, BrawlerPlayer>,
    pub enemies: Vec<Enemy>,
    pub wave: u32,
    next_enemy_id: u32,
    /// Waves already spawned (0 = none yet — nothing until first trigger).
    waves_spawned: u32,
    pub won: bool,
    /// True after a win until the room empties (so late leavers don't re-award).
    win_sent: bool,
    /// Fight camera/move lock while a wave is alive.
    pub lock_left: Option<f32>,
    pub lock_right: Option<f32>,
    /// Wave just cleared; show GO until the next trigger fires.
    pub show_go: bool,
    /// Progress fence: players and camera cannot go left of this.
    pub scroll_min: f32,
}

impl BrawlerWorld {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn is_empty(&self) -> bool {
        self.players.is_empty()
    }

    pub fn reset(&mut self) {
        *self = Self::new();
    }

    /// Join (or re-join). Spawns behind the furthest-right living player.
    pub fn join(
        &mut self,
        id: Uuid,
        name: String,
        skin: Skin,
        cosmetic: Cosmetic,
    ) -> (f32, f32) {
        if self.players.is_empty() {
            // Fresh run: no enemies until the lead player hits segment 1.
            self.reset();
        }

        let (x, y) = self.spawn_point();
        self.players.insert(
            id,
            BrawlerPlayer {
                id,
                name,
                skin,
                cosmetic,
                x,
                y,
                hp: PLAYER_MAX_HP,
                facing: 0.0,
                moving: false,
                attacking: false,
                attack_timer: 0.0,
                attack_cooldown: 0.0,
                attack_seq: 0,
                attack_buffered: false,
                invuln: 1.0,
                dead: false,
                input_dx: 0.0,
                input_dy: 0.0,
                input_attack: false,
                attack_held_prev: false,
            },
        );
        (x, y)
    }

    fn spawn_point(&self) -> (f32, f32) {
        let furthest = self
            .players
            .values()
            .filter(|p| !p.dead)
            .map(|p| p.x)
            .fold(None, |acc: Option<f32>, x| {
                Some(acc.map_or(x, |a| a.max(x)))
            });
        match furthest {
            Some(fx) => (
                (fx - SPAWN_BEHIND).max(self.scroll_min).max(20.0),
                GROUND_Y,
            ),
            None => (START_X, GROUND_Y),
        }
    }

    pub fn leave(&mut self, id: Uuid) {
        self.players.remove(&id);
        if self.players.is_empty() {
            self.reset();
        }
    }

    pub fn set_input(&mut self, id: Uuid, dx: f32, dy: f32, attack: bool) {
        if let Some(p) = self.players.get_mut(&id) {
            if p.dead {
                return;
            }
            p.input_dx = dx.clamp(-1.0, 1.0);
            p.input_dy = dy.clamp(-1.0, 1.0);
            p.input_attack = attack;
        }
    }

    pub fn advance(&mut self, dt: f32) -> Vec<BrawlerEvent> {
        let mut events = Vec::new();
        if self.players.is_empty() {
            return events;
        }

        // Move + attack players.
        let ids: Vec<Uuid> = self.players.keys().copied().collect();
        for id in ids {
            self.tick_player(id, dt);
        }

        // Resolve player attacks against enemies.
        self.resolve_player_attacks();

        // Enemy AI + attacks against players.
        self.tick_enemies(dt);

        // Wave progression.
        self.maybe_advance_wave();

        // Deaths.
        let dead: Vec<Uuid> = self
            .players
            .values()
            .filter(|p| p.dead || p.hp <= 0.0)
            .map(|p| p.id)
            .collect();
        for id in dead {
            if let Some(p) = self.players.get_mut(&id) {
                if !p.dead {
                    p.dead = true;
                    p.hp = 0.0;
                    events.push(BrawlerEvent::PlayerDied { player_id: id });
                }
            }
        }

        // Win: boss dead and every living player still here wins.
        if !self.win_sent && self.boss_defeated() {
            self.won = true;
            self.win_sent = true;
            let winners: Vec<Uuid> = self
                .players
                .values()
                .filter(|p| !p.dead && p.hp > 0.0)
                .map(|p| p.id)
                .collect();
            if !winners.is_empty() {
                events.push(BrawlerEvent::Won {
                    player_ids: winners,
                });
            }
        }

        events
    }

    fn tick_player(&mut self, id: Uuid, dt: f32) {
        let min_x = self
            .lock_left
            .unwrap_or(20.0)
            .max(self.scroll_min)
            .max(20.0);
        let max_x = self.lock_right.unwrap_or(WORLD_W - 20.0).min(WORLD_W - 20.0);

        let Some(p) = self.players.get_mut(&id) else {
            return;
        };
        if p.dead {
            return;
        }
        p.invuln = (p.invuln - dt).max(0.0);
        p.attack_cooldown = (p.attack_cooldown - dt).max(0.0);

        // One swing per fresh press (rising edge). Holding does nothing extra.
        let pressed = p.input_attack && !p.attack_held_prev;
        p.attack_held_prev = p.input_attack;

        if pressed {
            if p.attack_cooldown <= 0.0 {
                Self::start_player_attack(p);
            } else {
                // Don't drop the press — fire as soon as cooldown ends.
                p.attack_buffered = true;
            }
        }
        if p.attack_buffered && p.attack_cooldown <= 0.0 {
            p.attack_buffered = false;
            Self::start_player_attack(p);
        }

        if p.attack_timer > 0.0 {
            p.attack_timer = (p.attack_timer - dt).max(0.0);
        }
        p.attacking = p.attack_timer > 0.0;

        let mut dx = p.input_dx;
        let mut dy = p.input_dy;
        let len = (dx * dx + dy * dy).sqrt();
        if len > 1.0 {
            dx /= len;
            dy /= len;
        }
        // During the strike, slow walking a bit (arcade feel).
        let speed = if p.attacking {
            PLAYER_SPEED * 0.35
        } else {
            PLAYER_SPEED
        };
        p.x = (p.x + dx * speed * dt).clamp(min_x, max_x);
        p.y = (p.y + dy * speed * dt).clamp(LANE_TOP, LANE_BOTTOM);
        p.moving = len > 0.05;
        if p.moving {
            p.facing = dx.atan2(dy); // keep something; prefer horizontal
            if dx.abs() > 0.05 {
                p.facing = if dx >= 0.0 { 0.0 } else { std::f32::consts::PI };
            }
        }
    }

    /// Begin (or restart) a swing. Cooldown gates how often this can run;
    /// calling again while still attacking resets the timer so the anim can restart.
    fn start_player_attack(p: &mut BrawlerPlayer) {
        p.attack_timer = ATTACK_DURATION_S;
        p.attack_cooldown = ATTACK_COOLDOWN_S;
        p.attacking = true;
        p.attack_seq = p.attack_seq.wrapping_add(1);
        p.attack_buffered = false;
    }

    fn resolve_player_attacks(&mut self) {
        let strikes: Vec<(f32, f32, f32)> = self
            .players
            .values()
            .filter(|p| p.attacking && !p.dead)
            .map(|p| {
                let dir = if p.facing.abs() > 1.0 { -1.0 } else { 1.0 };
                (p.x + dir * 22.0, p.y, dir)
            })
            .collect();

        for (sx, sy, dir) in strikes {
            for enemy in &mut self.enemies {
                if enemy.hp <= 0.0 {
                    continue;
                }
                let dx = enemy.x - sx;
                let dy = enemy.y - sy;
                // Prefer hits in front of the player.
                if dx * dir < -8.0 {
                    continue;
                }
                let dist = (dx * dx + dy * dy).sqrt();
                if dist <= ATTACK_RANGE && dy.abs() <= ATTACK_HIT_Y {
                    enemy.hp = (enemy.hp - ATTACK_DAMAGE).max(0.0);
                    enemy.hit_flash = 0.12;
                    // Light knockback.
                    enemy.x = (enemy.x + dir * 10.0).clamp(20.0, WORLD_W - 20.0);
                }
            }
        }
        self.enemies.retain(|e| e.hp > 0.0);
    }

    fn tick_enemies(&mut self, dt: f32) {
        // Pick nearest living player as target for each enemy.
        let targets: Vec<(Uuid, f32, f32)> = self
            .players
            .values()
            .filter(|p| !p.dead && p.hp > 0.0)
            .map(|p| (p.id, p.x, p.y))
            .collect();
        if targets.is_empty() {
            return;
        }

        // Allow a margin so off-screen spawns can walk into the fight band.
        let min_x = (self.lock_left.unwrap_or(20.0) - ENTER_FROM).max(0.0);
        let max_x = (self.lock_right.unwrap_or(WORLD_W - 20.0) + ENTER_FROM).min(WORLD_W);
        let mut hits: Vec<(Uuid, f32)> = Vec::new();

        for enemy in &mut self.enemies {
            enemy.hit_flash = (enemy.hit_flash - dt).max(0.0);
            enemy.attack_cooldown = (enemy.attack_cooldown - dt).max(0.0);

            let (_, tx, ty) = targets
                .iter()
                .min_by(|a, b| {
                    let da = (a.1 - enemy.x).hypot(a.2 - enemy.y);
                    let db = (b.1 - enemy.x).hypot(b.2 - enemy.y);
                    da.partial_cmp(&db).unwrap_or(std::cmp::Ordering::Equal)
                })
                .copied()
                .unwrap();

            let dx = tx - enemy.x;
            let dy = ty - enemy.y;
            let dist = dx.hypot(dy);
            let speed = enemy.kind.speed();
            let range = enemy.kind.attack_range();

            if dist > range * 0.85 {
                let nx = dx / dist.max(0.001);
                let ny = dy / dist.max(0.001);
                enemy.x = (enemy.x + nx * speed * dt).clamp(min_x, max_x);
                enemy.y = (enemy.y + ny * speed * dt).clamp(LANE_TOP, LANE_BOTTOM);
            }
            if dx.abs() > 0.05 {
                enemy.facing = if dx >= 0.0 { 0.0 } else { std::f32::consts::PI };
            }

            if dist <= range && enemy.attack_cooldown <= 0.0 {
                enemy.attack_cooldown = enemy.kind.attack_cooldown();
                if let Some((tid, _, _)) = targets
                    .iter()
                    .find(|(_, x, y)| (*x - enemy.x).hypot(*y - enemy.y) <= range + 4.0)
                {
                    hits.push((*tid, enemy.kind.damage()));
                }
            }
        }

        for (tid, dmg) in hits {
            if let Some(p) = self.players.get_mut(&tid) {
                if p.dead || p.invuln > 0.0 {
                    continue;
                }
                // Only subtract HP here. Marking `dead` belongs in `advance` so
                // `BrawlerEvent::PlayerDied` is emitted (client needs that to
                // fade out and return to the playground).
                p.hp = (p.hp - dmg).max(0.0);
                p.invuln = 0.55;
            }
        }
    }

    fn maybe_advance_wave(&mut self) {
        if self.won {
            return;
        }

        // Wave just cleared → raise progress fence, unlock, show GO.
        if self.lock_right.is_some() && self.enemies.is_empty() && self.waves_spawned > 0 {
            if let Some(left) = self.lock_left {
                self.scroll_min = self.scroll_min.max(left);
            }
            self.lock_left = None;
            self.lock_right = None;
            if self.waves_spawned < TOTAL_WAVES && !self.boss_defeated() {
                self.show_go = true;
            }
            return;
        }

        if !self.enemies.is_empty() {
            return;
        }
        if self.waves_spawned >= TOTAL_WAVES {
            return;
        }

        let lead = self
            .players
            .values()
            .filter(|p| !p.dead)
            .map(|p| p.x)
            .fold(0.0_f32, f32::max);
        let next = self.waves_spawned + 1;
        let gate = segment_trigger(next);
        if next <= TOTAL_WAVES && lead >= gate {
            self.spawn_wave(next);
            self.waves_spawned = next;
            self.wave = next;
            self.show_go = false;
            // Lock the fight band around this segment.
            self.lock_left = Some((gate - 100.0).max(20.0));
            self.lock_right = Some((gate + FIGHT_WIDTH).min(WORLD_W - 20.0));
            // Pull anyone who overshot back into the band.
            let left = self.lock_left.unwrap();
            let right = self.lock_right.unwrap();
            for p in self.players.values_mut() {
                if !p.dead {
                    p.x = p.x.clamp(left, right);
                }
            }
        }
    }

    fn spawn_wave(&mut self, wave: u32) {
        let gate = segment_trigger(wave);
        let left = (gate - 100.0).max(20.0);
        let right = (gate + FIGHT_WIDTH).min(WORLD_W - 20.0);
        // Arcade entrance: pour in from just off the right (and a few from the left).
        let right_in = right + ENTER_FROM;
        let left_in = left - ENTER_FROM;
        let pack: Vec<(EnemyKind, f32, f32)> = match wave {
            1 => vec![
                (EnemyKind::Grunt, right_in, GROUND_Y - 10.0),
                (EnemyKind::Grunt, right_in + 30.0, GROUND_Y + 10.0),
                (EnemyKind::Grunt, right_in + 60.0, GROUND_Y),
            ],
            2 => vec![
                (EnemyKind::Grunt, right_in, GROUND_Y - 15.0),
                (EnemyKind::Grunt, right_in + 40.0, GROUND_Y + 15.0),
                (EnemyKind::Grunt, right_in + 70.0, GROUND_Y),
                (EnemyKind::Swift, left_in, GROUND_Y - 8.0),
            ],
            3 => vec![
                (EnemyKind::Swift, right_in, GROUND_Y - 20.0),
                (EnemyKind::Grunt, right_in + 35.0, GROUND_Y + 20.0),
                (EnemyKind::Bruiser, right_in + 65.0, GROUND_Y - 5.0),
                (EnemyKind::Swift, left_in, GROUND_Y + 10.0),
                (EnemyKind::Grunt, left_in - 30.0, GROUND_Y),
            ],
            4 => vec![
                (EnemyKind::Bruiser, right_in, GROUND_Y),
                (EnemyKind::Grunt, right_in + 40.0, GROUND_Y - 18.0),
                (EnemyKind::Swift, right_in + 80.0, GROUND_Y + 18.0),
                (EnemyKind::Swift, left_in, GROUND_Y),
                (EnemyKind::Bruiser, left_in - 30.0, GROUND_Y - 12.0),
                (EnemyKind::Grunt, right_in + 110.0, GROUND_Y + 12.0),
            ],
            // Midway elite / mini-boss + escorts.
            5 => vec![
                (EnemyKind::Elite, right_in + 20.0, GROUND_Y),
                (EnemyKind::Bruiser, right_in + 70.0, GROUND_Y - 16.0),
                (EnemyKind::Bruiser, left_in, GROUND_Y + 14.0),
                (EnemyKind::Swift, left_in - 40.0, GROUND_Y - 8.0),
            ],
            6 => vec![
                (EnemyKind::Bruiser, right_in, GROUND_Y),
                (EnemyKind::Bruiser, right_in + 45.0, GROUND_Y - 18.0),
                (EnemyKind::Swift, right_in + 85.0, GROUND_Y + 16.0),
                (EnemyKind::Swift, left_in, GROUND_Y),
                (EnemyKind::Grunt, left_in - 35.0, GROUND_Y - 12.0),
                (EnemyKind::Grunt, right_in + 120.0, GROUND_Y + 12.0),
                (EnemyKind::Bruiser, left_in - 70.0, GROUND_Y + 8.0),
            ],
            7 => vec![
                (EnemyKind::Bruiser, right_in, GROUND_Y - 10.0),
                (EnemyKind::Bruiser, right_in + 40.0, GROUND_Y + 14.0),
                (EnemyKind::Bruiser, left_in, GROUND_Y),
                (EnemyKind::Swift, right_in + 80.0, GROUND_Y - 18.0),
                (EnemyKind::Swift, right_in + 110.0, GROUND_Y + 18.0),
                (EnemyKind::Swift, left_in - 40.0, GROUND_Y + 10.0),
                (EnemyKind::Grunt, left_in - 70.0, GROUND_Y - 8.0),
                (EnemyKind::Grunt, right_in + 140.0, GROUND_Y),
            ],
            8 => vec![
                (EnemyKind::Bruiser, right_in, GROUND_Y),
                (EnemyKind::Bruiser, right_in + 35.0, GROUND_Y - 16.0),
                (EnemyKind::Bruiser, right_in + 70.0, GROUND_Y + 16.0),
                (EnemyKind::Bruiser, left_in, GROUND_Y - 8.0),
                (EnemyKind::Swift, right_in + 105.0, GROUND_Y),
                (EnemyKind::Swift, left_in - 35.0, GROUND_Y + 14.0),
                (EnemyKind::Swift, left_in - 70.0, GROUND_Y - 14.0),
                (EnemyKind::Grunt, right_in + 140.0, GROUND_Y + 8.0),
                (EnemyKind::Grunt, left_in - 100.0, GROUND_Y),
            ],
            _ => vec![(EnemyKind::Boss, right_in + 20.0, GROUND_Y)],
        };

        for (kind, x, y) in pack {
            self.next_enemy_id += 1;
            let id = self.next_enemy_id;
            // Do NOT clamp into the fight band — they walk in from off-screen.
            self.enemies.push(Enemy {
                id,
                kind,
                x,
                y: y.clamp(LANE_TOP, LANE_BOTTOM),
                hp: kind.max_hp(),
                facing: if x > right {
                    std::f32::consts::PI
                } else {
                    0.0
                },
                attack_cooldown: 0.6,
                hit_flash: 0.0,
            });
        }
    }

    fn boss_defeated(&self) -> bool {
        self.waves_spawned >= TOTAL_WAVES
            && !self.enemies.iter().any(|e| e.kind == EnemyKind::Boss)
            && self.wave >= TOTAL_WAVES
    }

    pub fn snapshot(&self) -> BrawlerSnapshot {
        let boss = self
            .enemies
            .iter()
            .find(|e| e.kind == EnemyKind::Boss)
            .or_else(|| self.enemies.iter().find(|e| e.kind == EnemyKind::Elite));
        BrawlerSnapshot {
            players: self
                .players
                .values()
                .map(|p| BrawlerPlayerSnap {
                    id: p.id,
                    name: p.name.clone(),
                    skin: p.skin.clone(),
                    cosmetic: p.cosmetic.clone(),
                    x: p.x,
                    y: p.y,
                    hp: p.hp,
                    max_hp: PLAYER_MAX_HP,
                    facing: p.facing,
                    moving: p.moving,
                    attacking: p.attacking,
                    attack_seq: p.attack_seq,
                    dead: p.dead,
                })
                .collect(),
            enemies: self
                .enemies
                .iter()
                .map(|e| EnemySnap {
                    id: e.id,
                    kind: e.kind,
                    x: e.x,
                    y: e.y,
                    hp: e.hp,
                    max_hp: e.kind.max_hp(),
                    facing: e.facing,
                    hit_flash: e.hit_flash > 0.0,
                })
                .collect(),
            wave: self.wave,
            boss_hp: boss.map(|b| b.hp),
            boss_max_hp: boss.map(|b| b.kind.max_hp()),
            won: self.won,
            show_go: self.show_go,
            lock_left: self.lock_left,
            lock_right: self.lock_right,
            scroll_min: self.scroll_min,
        }
    }

    /// Furthest-right living player x (for tests).
    pub fn furthest_right_x(&self) -> Option<f32> {
        self.players
            .values()
            .filter(|p| !p.dead)
            .map(|p| p.x)
            .fold(None, |acc: Option<f32>, x| {
                Some(acc.map_or(x, |a| a.max(x)))
            })
    }
}

/// Horizontal width of a locked fight arena (near full camera view on typical desktops).
pub const FIGHT_WIDTH: f32 = 1100.0;
/// How far off-screen enemies spawn before walking into the lock band.
pub const ENTER_FROM: f32 = 90.0;
/// Total waves including the final boss.
pub const TOTAL_WAVES: u32 = 9;
/// Wave index of the midway elite / mini-boss.
pub const ELITE_WAVE: u32 = 5;
/// Wave index of the final boss arena fight.
pub const BOSS_WAVE: u32 = 9;

/// X position the lead player must reach to trigger wave N (1..=TOTAL_WAVES).
pub fn segment_trigger(wave: u32) -> f32 {
    match wave {
        1 => 380.0,
        2 => 1000.0,
        3 => 1650.0,
        4 => 2350.0,
        5 => 3100.0, // elite / mini-boss
        6 => 3850.0,
        7 => 4600.0,
        8 => 5350.0,
        _ => 6100.0, // final boss arena
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn skin() -> Skin {
        Skin::default()
    }
    fn cos() -> Cosmetic {
        Cosmetic::default()
    }

    #[test]
    fn fresh_on_first_join_and_reset_when_empty() {
        let mut w = BrawlerWorld::new();
        assert!(w.is_empty());
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        assert_eq!(w.wave, 0);
        assert!(w.enemies.is_empty(), "no enemies before the first segment");
        w.leave(a);
        assert!(w.is_empty());
        assert_eq!(w.wave, 0);
        assert!(w.enemies.is_empty());
    }

    #[test]
    fn wave_spawns_only_after_lead_reaches_segment_trigger() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        assert!(w.enemies.is_empty());
        // Short of the trigger — still quiet.
        w.players.get_mut(&a).unwrap().x = segment_trigger(1) - 10.0;
        let _ = w.advance(0.05);
        assert!(w.enemies.is_empty());
        assert_eq!(w.waves_spawned, 0);
        // Cross the trigger — wave 1 locks in.
        w.players.get_mut(&a).unwrap().x = segment_trigger(1) + 1.0;
        let _ = w.advance(0.05);
        assert!(!w.enemies.is_empty());
        assert_eq!(w.wave, 1);
        assert_eq!(w.waves_spawned, 1);
        assert!(w.lock_right.is_some());
        assert!(!w.show_go);
        // Clear enemies → GO unlock.
        w.enemies.clear();
        let _ = w.advance(0.05);
        assert!(w.show_go);
        assert!(w.lock_right.is_none());
        // Walk to segment 2.
        w.players.get_mut(&a).unwrap().x = segment_trigger(2) + 1.0;
        let _ = w.advance(0.05);
        assert_eq!(w.wave, 2);
        assert!(!w.enemies.is_empty());
        assert!(!w.show_go);
    }

    #[test]
    fn attack_only_on_rising_edge_not_while_held() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        // Hold attack across many ticks: exactly one swing starts.
        w.set_input(a, 0.0, 0.0, true);
        let _ = w.advance(0.05);
        assert!(w.players[&a].attacking);
        // Finish the swing + cooldown while still held.
        for _ in 0..40 {
            w.set_input(a, 0.0, 0.0, true);
            let _ = w.advance(0.05);
        }
        assert!(!w.players[&a].attacking);
        assert!(w.players[&a].attack_held_prev);
        // Still held — must NOT start another.
        let _ = w.advance(0.05);
        assert!(!w.players[&a].attacking);
        // Release then press again → new swing.
        w.set_input(a, 0.0, 0.0, false);
        let _ = w.advance(0.05);
        w.set_input(a, 0.0, 0.0, true);
        let _ = w.advance(0.05);
        assert!(w.players[&a].attacking);
    }

    #[test]
    fn later_joiner_spawns_behind_furthest_right() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        let b = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.players.get_mut(&a).unwrap().x = 500.0;
        let (bx, _) = w.join(b, "James 2".into(), skin(), cos());
        assert!(bx < 500.0);
        assert!((bx - (500.0 - SPAWN_BEHIND)).abs() < 1.0);
    }

    #[test]
    fn no_friendly_fire_player_attack_only_hurts_enemies() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        let b = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.join(b, "James 2".into(), skin(), cos());
        {
            let p = w.players.get_mut(&a).unwrap();
            p.x = 100.0;
            p.y = GROUND_Y;
            p.facing = 0.0;
            p.attacking = true;
            p.attack_timer = ATTACK_DURATION_S;
        }
        {
            let p = w.players.get_mut(&b).unwrap();
            p.x = 120.0;
            p.y = GROUND_Y;
            p.hp = PLAYER_MAX_HP;
        }
        // Clear enemies so only friendlies could be hit.
        w.enemies.clear();
        w.resolve_player_attacks();
        assert!((w.players[&b].hp - PLAYER_MAX_HP).abs() < 0.01);
    }

    #[test]
    fn player_attack_damages_enemy() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        w.next_enemy_id += 1;
        w.enemies.push(Enemy {
            id: w.next_enemy_id,
            kind: EnemyKind::Grunt,
            x: 130.0,
            y: GROUND_Y,
            hp: 40.0,
            facing: std::f32::consts::PI,
            attack_cooldown: 9.0,
            hit_flash: 0.0,
        });
        {
            let p = w.players.get_mut(&a).unwrap();
            p.x = 100.0;
            p.y = GROUND_Y;
            p.facing = 0.0;
            p.attacking = true;
        }
        w.resolve_player_attacks();
        assert!(w.enemies[0].hp < 40.0);
    }

    #[test]
    fn lethal_damage_emits_player_died_once() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        // Fatal HP with dead still false — the old bug set `dead` in tick_enemies
        // and then skipped emitting PlayerDied.
        w.players.get_mut(&a).unwrap().hp = 0.0;
        assert!(!w.players[&a].dead);
        let events = w.advance(0.05);
        assert!(w.players[&a].dead);
        assert_eq!(
            events
                .iter()
                .filter(|e| matches!(e, BrawlerEvent::PlayerDied { player_id } if *player_id == a))
                .count(),
            1,
            "PlayerDied must fire so the client can leave the brawler"
        );
        let events2 = w.advance(0.05);
        assert!(!events2
            .iter()
            .any(|e| matches!(e, BrawlerEvent::PlayerDied { .. })));
    }

    #[test]
    fn snapshot_player_hp_drops_after_enemy_hit() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        {
            let p = w.players.get_mut(&a).unwrap();
            p.x = 200.0;
            p.y = GROUND_Y;
            p.hp = PLAYER_MAX_HP;
            p.invuln = 0.0;
        }
        w.next_enemy_id += 1;
        w.enemies.push(Enemy {
            id: w.next_enemy_id,
            kind: EnemyKind::Grunt,
            x: 205.0,
            y: GROUND_Y,
            hp: 40.0,
            facing: std::f32::consts::PI,
            attack_cooldown: 0.0,
            hit_flash: 0.0,
        });
        let before = w.snapshot();
        let before_p = before
            .players
            .iter()
            .find(|p| p.id == a)
            .expect("local player in snapshot");
        assert!((before_p.hp - PLAYER_MAX_HP).abs() < 0.01);
        assert!((before_p.max_hp - PLAYER_MAX_HP).abs() < 0.01);
        let _ = w.advance(0.05);
        let after = w.snapshot();
        let after_p = after
            .players
            .iter()
            .find(|p| p.id == a)
            .expect("local player in snapshot");
        assert!(
            after_p.hp < before_p.hp,
            "snapshot must carry the reduced HP so the client HUD can shrink"
        );
        assert!((after_p.max_hp - PLAYER_MAX_HP).abs() < 0.01);
    }

    #[test]
    fn enemy_kill_emits_player_died() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        {
            let p = w.players.get_mut(&a).unwrap();
            p.x = 200.0;
            p.y = GROUND_Y;
            p.hp = 1.0;
            p.invuln = 0.0;
        }
        w.next_enemy_id += 1;
        w.enemies.push(Enemy {
            id: w.next_enemy_id,
            kind: EnemyKind::Grunt,
            x: 205.0,
            y: GROUND_Y,
            hp: 40.0,
            facing: std::f32::consts::PI,
            attack_cooldown: 0.0,
            hit_flash: 0.0,
        });
        let events = w.advance(0.05);
        assert!(w.players[&a].dead, "player should be dead after lethal hit");
        assert!(
            events
                .iter()
                .any(|e| matches!(e, BrawlerEvent::PlayerDied { player_id } if *player_id == a)),
            "enemy kill must emit PlayerDied for the playground return path"
        );
    }

    
    #[test]
    fn clearing_wave_advances_scroll_min_and_unlocks() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.players.get_mut(&a).unwrap().x = segment_trigger(1) + 1.0;
        let _ = w.advance(0.05);
        assert_eq!(w.wave, 1);
        let left = w.lock_left.expect("fight lock left");
        w.enemies.clear();
        let _ = w.advance(0.05);
        assert!(w.show_go);
        assert!(w.lock_right.is_none());
        assert!(
            w.scroll_min >= left - 0.01,
            "scroll_min should advance to cleared lock_left ({left}), got {}",
            w.scroll_min
        );
        let snap = w.snapshot();
        assert!((snap.scroll_min - w.scroll_min).abs() < 0.01);
    }

    #[test]
    fn player_cannot_walk_left_of_scroll_min() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.scroll_min = 400.0;
        w.lock_left = None;
        w.lock_right = None;
        {
            let p = w.players.get_mut(&a).unwrap();
            p.x = 410.0;
            p.y = GROUND_Y;
        }
        w.set_input(a, -1.0, 0.0, false);
        for _ in 0..40 {
            let _ = w.advance(0.05);
        }
        assert!(
            w.players[&a].x + 0.5 >= w.scroll_min.max(20.0),
            "player x {} should stay >= scroll_min {}",
            w.players[&a].x,
            w.scroll_min
        );
    }

    #[test]
    fn wave_enemies_spawn_from_offscreen_edges() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.players.get_mut(&a).unwrap().x = segment_trigger(1) + 1.0;
        let _ = w.advance(0.05);
        let left = w.lock_left.expect("lock");
        let right = w.lock_right.expect("lock");
        assert!(!w.enemies.is_empty());
        for e in &w.enemies {
            let from_left = e.x < left;
            let from_right = e.x > right;
            assert!(
                from_left || from_right,
                "enemy at {} should start outside [{left}, {right}]",
                e.x
            );
        }
    }

    #[test]
    fn elite_wave_spawns_midway_mini_boss() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        for wave in 1..(ELITE_WAVE) {
            w.players.get_mut(&a).unwrap().x = segment_trigger(wave) + 1.0;
            let _ = w.advance(0.05);
            w.enemies.clear();
            let _ = w.advance(0.05);
        }
        w.players.get_mut(&a).unwrap().x = segment_trigger(ELITE_WAVE) + 1.0;
        let _ = w.advance(0.05);
        assert_eq!(w.wave, ELITE_WAVE);
        assert!(w.enemies.iter().any(|e| matches!(e.kind, EnemyKind::Elite)));
        assert!(w.lock_left.is_some());
        let snap = w.snapshot();
        assert!(snap.boss_hp.is_some(), "elite exposes HP on the boss bar");
    }

    #[test]
    fn boss_arena_locks_camera_band() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        // Fast-forward through crawl waves, then trigger the final boss.
        for wave in 1..BOSS_WAVE {
            w.players.get_mut(&a).unwrap().x = segment_trigger(wave) + 1.0;
            let _ = w.advance(0.05);
            w.enemies.clear();
            let _ = w.advance(0.05);
        }
        w.players.get_mut(&a).unwrap().x = segment_trigger(BOSS_WAVE) + 1.0;
        let _ = w.advance(0.05);
        assert_eq!(w.wave, BOSS_WAVE);
        assert!(w.lock_left.is_some());
        assert!(w.lock_right.is_some());
        assert!(!w.show_go);
        assert!(w.enemies.iter().any(|e| matches!(e.kind, EnemyKind::Boss)));
        assert!(
            segment_trigger(BOSS_WAVE) >= 6000.0,
            "boss arena should sit near the end of the doubled stage"
        );
    }

    #[test]
    fn stage_is_roughly_double_pre_boss_length() {
        // Pre-boss crawl used to end at 3000; keep boss gate ~2x that.
        assert!(segment_trigger(BOSS_WAVE) >= 5800.0);
        assert!(WORLD_W >= 6800.0);
        assert_eq!(TOTAL_WAVES, BOSS_WAVE);
        assert_eq!(ELITE_WAVE, 5);
    }

#[test]
    fn last_player_leave_after_death_resets_room() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.players.get_mut(&a).unwrap().hp = 0.0;
        let events = w.advance(0.05);
        assert!(events
            .iter()
            .any(|e| matches!(e, BrawlerEvent::PlayerDied { .. })));
        w.leave(a);
        assert!(w.is_empty());
        assert_eq!(w.wave, 0);
        assert!(w.enemies.is_empty());
        let b = Uuid::new_v4();
        w.join(b, "James 2".into(), skin(), cos());
        assert!(!w.players[&b].dead);
        assert!((w.players[&b].hp - PLAYER_MAX_HP).abs() < 0.01);
    }

    #[test]
    fn lane_spans_most_of_world_height() {
        let span = LANE_BOTTOM - LANE_TOP;
        assert!(span >= WORLD_H * 0.75, "lane {span} should cover most of WORLD_H {WORLD_H}");
        assert!(LANE_TOP <= 90.0, "lane top should sit just under the HUD/horizon");
        assert!(LANE_BOTTOM + 30.0 >= WORLD_H, "lane bottom should reach near the world bottom edge");
        assert!(GROUND_Y > LANE_TOP && GROUND_Y < LANE_BOTTOM);
    }

    #[test]
    fn fight_band_is_wide_for_near_edge_to_edge_walk() {
        assert!(
            FIGHT_WIDTH >= 900.0,
            "fight lock should let players walk nearly across a typical camera view"
        );
    }

    #[test]
    fn attack_cooldown_not_longer_than_duration() {
        assert!(
            ATTACK_COOLDOWN_S <= ATTACK_DURATION_S,
            "cooldown {} must be <= duration {} so presses aren't dropped after the anim",
            ATTACK_COOLDOWN_S,
            ATTACK_DURATION_S
        );
    }

    #[test]
    fn buffered_press_during_cooldown_fires_when_ready() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        // First swing.
        w.set_input(a, 0.0, 0.0, true);
        let _ = w.advance(0.05);
        assert!(w.players[&a].attacking);
        let seq1 = w.players[&a].attack_seq;
        // Release, then press again while still on cooldown — must buffer, not drop.
        w.set_input(a, 0.0, 0.0, false);
        let _ = w.advance(0.05);
        w.set_input(a, 0.0, 0.0, true);
        let _ = w.advance(0.05);
        assert!(w.players[&a].attack_buffered || w.players[&a].attack_seq > seq1);
        w.set_input(a, 0.0, 0.0, false);
        // Advance past remaining cooldown; buffered press should start a new swing.
        for _ in 0..20 {
            let _ = w.advance(0.05);
            if w.players[&a].attack_seq > seq1 {
                break;
            }
        }
        assert!(
            w.players[&a].attack_seq > seq1,
            "buffered press must fire a new attack_seq after cooldown"
        );
        assert!(!w.players[&a].attack_buffered);
    }

    #[test]
    fn rapid_press_restarts_attack_and_bumps_seq() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.enemies.clear();
        w.set_input(a, 0.0, 0.0, true);
        let _ = w.advance(0.05);
        let seq1 = w.players[&a].attack_seq;
        assert!(seq1 >= 1);
        // Wait just past cooldown (shorter than duration) while released.
        w.set_input(a, 0.0, 0.0, false);
        let steps = ((ATTACK_COOLDOWN_S / 0.05).ceil() as i32) + 1;
        for _ in 0..steps {
            let _ = w.advance(0.05);
        }
        // Still within first attack window possibly — press again must restart.
        w.set_input(a, 0.0, 0.0, true);
        let _ = w.advance(0.05);
        assert!(w.players[&a].attack_seq > seq1);
        assert!(w.players[&a].attacking);
        assert!((w.players[&a].attack_timer - ATTACK_DURATION_S).abs() < 0.06);
    }

    #[test]
    fn player_y_clamped_to_expanded_lane() {
        let mut w = BrawlerWorld::new();
        let a = Uuid::new_v4();
        w.join(a, "James 1".into(), skin(), cos());
        w.set_input(a, 0.0, -1.0, false);
        for _ in 0..200 {
            let _ = w.advance(0.05);
        }
        assert!((w.players[&a].y - LANE_TOP).abs() < 0.5);
        w.set_input(a, 0.0, 1.0, false);
        for _ in 0..400 {
            let _ = w.advance(0.05);
        }
        assert!((w.players[&a].y - LANE_BOTTOM).abs() < 0.5);
    }
}
