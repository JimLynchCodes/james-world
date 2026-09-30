use uuid::Uuid;

#[derive(Debug, Clone, Copy)]
pub struct Position {
    pub x: f32,
    pub y: f32,
}

#[derive(Debug, Clone)]
pub struct Player {
    pub id: Uuid,

    pub position: Position,

    pub energy: f32,

    pub is_running: bool,

    pub is_it: bool,

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

            position: Position {
                x,
                y,
            },

            energy: 100.0,

            is_running: false,

            is_it: false,

            tag_immunity_ticks: 0,

            escape_boost_ticks: 0,
        }
    }
}