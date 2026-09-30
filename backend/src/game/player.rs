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
        }
    }
}