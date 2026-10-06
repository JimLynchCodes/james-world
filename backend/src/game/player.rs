use uuid::Uuid;

#[derive(Debug, Clone, Copy)]
pub struct Position {
    pub x: f32,
    pub y: f32,
}

#[derive(Debug, Clone)]
pub struct Player {
    pub id: Uuid,

    /// Display name, e.g. "James 7" (assigned by the World on join).
    pub name: String,

    pub position: Position,

    pub energy: f32,

    pub is_running: bool,

    pub is_it: bool,

    /// True for server-controlled bots (no websocket connection).
    pub is_bot: bool,

    /// Direction the player last moved in, in radians (0 = +x, atan2(dy, dx)).
    pub facing: f32,

    pub tag_immunity_ticks: u32,

    pub escape_boost_ticks: u32,
}

impl Player {
    pub fn new(
        id: Uuid,
        x: f32,
        y: f32,
    ) -> Self {
        Self {
            id,

            name: String::new(),

            position: Position {
                x,
                y,
            },

            energy: 100.0,

            is_running: false,

            is_it: false,

            is_bot: false,

            facing: 0.0,

            tag_immunity_ticks: 0,

            escape_boost_ticks: 0,
        }
    }
}