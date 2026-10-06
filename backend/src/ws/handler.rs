use axum::{
    extract::{
        ws::{WebSocket, WebSocketUpgrade},
        State,
    },
    response::Response,
};

use crate::{
    app::AppState, ws::connection::handle_connection,
};

pub async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(
        move |socket: WebSocket| async move {
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
            )
            .await;
        },
    )
}