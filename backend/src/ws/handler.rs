use std::sync::atomic::Ordering;

use axum::{
    extract::{
        ws::{WebSocket, WebSocketUpgrade},
        State,
    },
    http::{header::ORIGIN, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};

use crate::{
    app::AppState, config::origin_allowed, ws::connection::handle_connection,
};

/// Decrements the open-connection counter when the socket task ends.
struct ConnectionGuard(std::sync::Arc<std::sync::atomic::AtomicUsize>);

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

pub async fn ws_handler(
    ws: WebSocketUpgrade,
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
    let origin = headers.get(ORIGIN).and_then(|v| v.to_str().ok());
    if !origin_allowed(state.allowed_origins.as_deref(), origin) {
        tracing::warn!(?origin, "rejected WebSocket from a disallowed origin");
        return (StatusCode::FORBIDDEN, "origin not allowed").into_response();
    }
    if state.shutdown.as_ref().is_some_and(|rx| *rx.borrow()) {
        return (StatusCode::SERVICE_UNAVAILABLE, "restarting").into_response();
    }

    ws.on_upgrade(
        move |socket: WebSocket| async move {
            state.connections.fetch_add(1, Ordering::SeqCst);
            let _guard = ConnectionGuard(state.connections.clone());
            let player_id = uuid::Uuid::new_v4();

            let (outbound_tx, outbound_rx) = tokio::sync::mpsc::channel(100);

            let rooms = state.rooms.clone();

            // Connect as a spectator; Join (from the client) promotes to a player.
            rooms
                .register_spectator(
                    player_id,
                    outbound_tx,
                )
                .await;

            handle_connection(
                socket,
                player_id,
                outbound_rx,
                rooms,
                state.shutdown.clone(),
            )
            .await;
        },
    )
}