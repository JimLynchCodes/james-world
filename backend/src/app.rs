
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
    let rooms = RoomManager::new();

    // Clone the exact same RoomManager instance for the background tick task
    let rooms_clone = rooms.clone();
    tokio::spawn(async move {
        rooms_clone.run_tick_loop().await;
    });

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