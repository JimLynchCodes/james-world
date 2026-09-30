
use axum::{
    http::StatusCode,
    routing::get,
    Json,
    Router,
};
use tower_http::trace::TraceLayer;

use crate::{
    game::world::World,
    rooms::room::RoomManager,
    ws::handler::ws_handler,
};

#[derive(Clone)]
pub struct AppState {
    pub rooms: RoomManager,
}

pub fn create_app() -> Router {
    let world = World::new();
    let rooms = RoomManager::new(world);

    let state = AppState { rooms };

    Router::new()
        .route("/ws", get(ws_handler))
        .route("/health", get(health))
        .with_state(state)
        .layer(TraceLayer::new_for_http())
}

async fn health() -> (
    StatusCode,
    Json<serde_json::Value>,
) {
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "ok",
            "service": "taggame-backend"
        })),
    )
}