use axum::extract::ws::{
    close_code,
    CloseFrame,
    Message,
    WebSocket,
};

use futures_util::{
    SinkExt,
    StreamExt,
};

use tokio::sync::{mpsc, watch};

use uuid::Uuid;

use crate::{
    game::skin::Skin,
    rooms::room::RoomManager,
    ws::protocol::{
        ClientMessage,
        ServerMessage,
    },
};

pub async fn handle_connection(
    socket: WebSocket,
    player_id: Uuid,
    mut outbound_rx: mpsc::Receiver<ServerMessage>,
    rooms: RoomManager,
    mut shutdown: Option<watch::Receiver<bool>>,
) {
    let (mut sender, mut receiver) =
        socket.split();

    loop {
        tokio::select! {
            // Server restarting: say so (1012 = service restart) so the
            // client reconnects right away, then leave the world.
            _ = wait_for_shutdown(&mut shutdown) => {
                let _ = sender
                    .send(Message::Close(Some(CloseFrame {
                        code: close_code::RESTART,
                        reason: "server restarting".into(),
                    })))
                    .await;
                break;
            }

            outgoing = outbound_rx.recv() => {
                match outgoing {
                    Some(message) => {
                        let Ok(json) =
                            message.to_json()
                        else {
                            continue;
                        };

                        if sender
                            .send(
                                Message::Text(
                                    json.into()
                                )
                            )
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }

                    None => {
                        break;
                    }
                }
            }

            incoming = receiver.next() => {
                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        let message =
                            match serde_json::from_str::<ClientMessage>(&text) {
                                Ok(message) => message,

                                Err(_) => {
                                    let error =
                                        ServerMessage::Error {
                                            message:
                                                "Invalid message".into(),
                                        };

                                    if let Ok(json) =
                                        error.to_json()
                                    {
                                        let _ = sender
                                            .send(
                                                Message::Text(
                                                    json.into()
                                                )
                                            )
                                            .await;
                                    }

                                    continue;
                                }
                            };

                        handle_client_message(
                            message,
                            player_id,
                            &rooms,
                        )
                        .await;
                    }

                    Some(Ok(Message::Ping(bytes))) => {
                        if sender
                            .send(
                                Message::Pong(bytes)
                            )
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }

                    Some(Ok(Message::Close(_)))
                    | None => {
                        break;
                    }

                    Some(Ok(_)) => {}

                    Some(Err(_)) => {
                        break;
                    }
                }
            }
        }
    }

    rooms
        .unregister(player_id)
        .await;
}

/// Resolves once the shutdown flag is set; never, without a signal.
async fn wait_for_shutdown(shutdown: &mut Option<watch::Receiver<bool>>) {
    let Some(rx) = shutdown else {
        return std::future::pending().await;
    };
    loop {
        if *rx.borrow_and_update() {
            return;
        }
        if rx.changed().await.is_err() {
            // Sender gone without a signal: nothing will ever fire.
            return std::future::pending().await;
        }
    }
}

async fn handle_client_message(
    message: ClientMessage,
    player_id: Uuid,
    rooms: &RoomManager,
) {
    match message {
        ClientMessage::MoveInput {
            seq,
            dx,
            dy,
            running,
        } => {
            rooms
                .world
                .lock()
                .await
                .set_input(
                    player_id,
                    crate::game::world::PlayerInput {
                        seq,
                        dx,
                        dy,
                        running,
                    },
                );
        }

        ClientMessage::TagPlayer {
            target_id,
        } => {
            let tagged = rooms
                .world
                .lock()
                .await
                .tag_player(
                    player_id,
                    target_id,
                );

            if tagged {
                rooms
                    .broadcast(
                        ServerMessage::PlayerTagged {
                            tagger_id: player_id,
                            target_id,
                        },
                    )
                    .await;
            }
        }

        ClientMessage::Ping {
            timestamp,
        } => {
            rooms
                .send_to(
                    player_id,
                    ServerMessage::Pong {
                        timestamp,
                    },
                )
                .await;
        }

        // Spectator → player. Carries the chosen skin.
        ClientMessage::Join {
            room_id: _,
            skin,
        } => {
            rooms.join(player_id, skin).await;
        }

        ClientMessage::SetSkin {
            skin,
        } => {
            rooms
                .world
                .lock()
                .await
                .set_skin(player_id, Skin::parse(&skin));
        }
    }
}