
use axum::{
    extract::{
        ws::{WebSocket, WebSocketUpgrade},
        State,
    },
    response::Response,
};

use crate::{
    app::AppState,
    ws::{
        connection::handle_connection,
        protocol::ServerMessage,
    },
};

pub async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.max_message_size(16 * 1024)
        .max_frame_size(16 * 1024)
        .on_upgrade(move |socket| async move {
            connect_player(socket, state).await;
        })
}

async fn connect_player(
    socket: WebSocket,
    state: AppState,
) {
    let player_id = {
        let mut world = state.rooms.world.lock().await;

        world.add_player(
            format!("Duck-{}", rand_suffix()),
        )
    };

    
    let (outbound_tx, outbound_rx) =
        state.rooms.register(player_id).await;

    let _ = outbound_tx
        .send(ServerMessage::Welcome {
            player_id,
            tick_rate: crate::rooms::room::TICK_RATE,
        })
        .await;

    let snapshot = {
        state.rooms.world.lock().await.snapshot()
    };

    let _ = outbound_tx.send(snapshot).await;

    handle_connection(
        socket,
        player_id,
        outbound_rx,
        state.rooms,
    )
    .await;
}

fn rand_suffix() -> u16 {
    use std::time::{SystemTime, UNIX_EPOCH};

    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .subsec_micros() as u16
}