
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use axum::{
    http::StatusCode,
    routing::get,
    Json,
    Router,
};
use tokio::sync::watch;
use tower_http::trace::TraceLayer;

use crate::{
    rooms::room::RoomManager,
    ws::handler::ws_handler,
};

#[derive(Clone)]
pub struct AppState {
    pub rooms: RoomManager,
    /// Browser origins allowed to open the WebSocket (`None` = any).
    pub allowed_origins: Arc<Option<Vec<String>>>,
    /// Flips to `true` when the server is shutting down: every open
    /// WebSocket sends a Close frame (1012 "service restart") and ends.
    pub shutdown: Option<watch::Receiver<bool>>,
    /// Open WebSocket connections (so shutdown can wait for them to close).
    pub connections: Arc<AtomicUsize>,
}

/// Options for [`create_app_with`]. `Default` = allow every origin and no
/// shutdown signal (what tests and plain `create_app()` use).
#[derive(Default)]
pub struct AppConfig {
    pub allowed_origins: Option<Vec<String>>,
    pub shutdown: Option<watch::Receiver<bool>>,
}

/// Handle to the running app's open-connection counter.
#[derive(Clone)]
pub struct Connections(Arc<AtomicUsize>);

impl Connections {
    pub fn open(&self) -> usize {
        self.0.load(Ordering::SeqCst)
    }
}

pub fn create_app() -> Router {
    create_app_with(AppConfig::default()).0
}

pub fn create_app_with(config: AppConfig) -> (Router, Connections) {
    let rooms = RoomManager::new();

    // Clone the exact same RoomManager instance for the background tick task
    let rooms_clone = rooms.clone();
    tokio::spawn(async move {
        rooms_clone.run_tick_loop().await;
    });

    let connections = Arc::new(AtomicUsize::new(0));
    let state = AppState {
        rooms,
        allowed_origins: Arc::new(config.allowed_origins),
        shutdown: config.shutdown,
        connections: connections.clone(),
    };

    let router = Router::new()
        .route("/ws", get(ws_handler))
        .route("/health", get(health))
        .with_state(state)
        .layer(TraceLayer::new_for_http());
    (router, Connections(connections))
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
