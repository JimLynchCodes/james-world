use axum::extract::ws::{
    Message,
    WebSocket,
};

use futures_util::{
    SinkExt,
    StreamExt,
};

use tokio::sync::mpsc;

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
) {
    let (mut sender, mut receiver) =
        socket.split();

    loop {
        tokio::select! {
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

        // The player is already in the world (added when the socket
        // connected); Join just carries their chosen skin.
        ClientMessage::Join {
            room_id: _,
            skin,
        } => {
            if let Some(skin) = skin {
                rooms
                    .world
                    .lock()
                    .await
                    .set_skin(player_id, Skin::parse(&skin));
            }
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