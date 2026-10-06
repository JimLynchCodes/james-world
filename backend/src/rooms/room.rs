use std::{
    collections::HashMap,
    sync::Arc,
};

use tokio::sync::{
    mpsc,
    Mutex,
};

use uuid::Uuid;

use crate::{
    game::world::World,
    ws::protocol::ServerMessage,
};

const TICK_RATE: u64 = 30;

#[derive(Clone)]
pub struct RoomManager {
    pub world: Arc<Mutex<World>>,

    pub connections:
        Arc<
            Mutex<
                HashMap<
                    Uuid,
                    mpsc::Sender<ServerMessage>,
                >,
            >,
        >,
}

impl RoomManager {
    pub fn new() -> Self {
        Self {
            world: Arc::new(
                Mutex::new(
                    World::new()
                )
            ),

            connections: Arc::new(
                Mutex::new(
                    HashMap::new()
                )
            ),
        }
    }

    pub async fn register(
        &self,
        player_id: Uuid,
        sender: mpsc::Sender<ServerMessage>,
    ) {
        // Add to the world first: that's where the player's name comes from.
        let (name, existing_players, spawned_bots) = {
            let mut world =
                self.world
                    .lock()
                    .await;

            let existing = world
                .players
                .values()
                .map(|p| (p.id, p.name.clone()))
                .collect::<Vec<_>>();

            // Joining may also spawn the bot players.
            let spawned_bots = world
                .add_player(player_id)
                .into_iter()
                .map(|id| (id, world.name_of(&id)))
                .collect::<Vec<_>>();

            (world.name_of(&player_id), existing, spawned_bots)
        };

        // The connection's channel is ordered and snapshots only reach
        // registered connections, so queueing the Welcome before registering
        // means the client always learns its own id before any snapshot or join.
        let _ = sender
            .send(ServerMessage::Welcome {
                player_id,
                name: name.clone(),
            })
            .await;

        {
            let mut connections =
                self.connections
                    .lock()
                    .await;

            connections.insert(
                player_id,
                sender.clone(),
            );
        }

        // Tell the new player about everyone already here...
        for (existing_id, existing_name) in existing_players {
            let _ = sender
                .send(
                    ServerMessage::PlayerJoined {
                        player_id: existing_id,
                        name: existing_name,
                    },
                )
                .await;
        }

        // ...and tell everyone else about the new player.
        self.broadcast_except(
            player_id,
            ServerMessage::PlayerJoined {
                player_id,
                name,
            },
        )
        .await;

        for (bot_id, bot_name) in spawned_bots {
            self.broadcast(
                ServerMessage::PlayerJoined {
                    player_id: bot_id,
                    name: bot_name,
                },
            )
            .await;
        }
    }

    pub async fn unregister(
        &self,
        player_id: Uuid,
    ) {
        {
            let mut connections =
                self.connections
                    .lock()
                    .await;

            connections.remove(
                &player_id
            );
        }

        let removed_bots = self
            .world
            .lock()
            .await
            .remove_player(
                player_id
            );

        self.broadcast(
            ServerMessage::PlayerLeft {
                player_id,
            },
        )
        .await;

        for bot_id in removed_bots {
            self.broadcast(
                ServerMessage::PlayerLeft {
                    player_id: bot_id,
                },
            )
            .await;
        }
    }

    pub async fn send_to(
        &self,
        player_id: Uuid,
        message: ServerMessage,
    ) {
        let sender = {
            let connections =
                self.connections
                    .lock()
                    .await;

            connections
                .get(&player_id)
                .cloned()
        };

        if let Some(sender) = sender {
            let _ =
                sender
                    .send(message)
                    .await;
        }
    }

    pub async fn broadcast_except(
        &self,
        excluded: Uuid,
        message: ServerMessage,
    ) {
        let connections = {
            let connections =
                self.connections
                    .lock()
                    .await;

            connections
                .iter()
                .filter(|(id, _)| **id != excluded)
                .map(|(_, sender)| sender.clone())
                .collect::<Vec<_>>()
        };

        for sender in connections {
            let _ =
                sender
                    .send(message.clone())
                    .await;
        }
    }

    pub async fn broadcast(
        &self,
        message: ServerMessage,
    ) {
        let connections = {
            let connections =
                self.connections
                    .lock()
                    .await;

            connections
                .values()
                .cloned()
                .collect::<Vec<_>>()
        };

        for sender in connections {
            let _ =
                sender
                    .send(message.clone())
                    .await;
        }
    }

    pub async fn run_tick_loop(
        &self,
    ) {
        let mut interval =
            tokio::time::interval(
                tokio::time::Duration::from_millis(
                    1000 / TICK_RATE
                ),
            );

        loop {
            interval.tick().await;

            let (snapshot, bot_tags) = {
                let mut world =
                    self.world
                        .lock()
                        .await;

                world.advance_tick(
                    1.0 / TICK_RATE as f32
                );

                (world.snapshot(), world.take_tag_events())
            };

            for (tagger_id, target_id) in bot_tags {
                self.broadcast(
                    ServerMessage::PlayerTagged {
                        tagger_id,
                        target_id,
                    },
                )
                .await;
            }

            self.broadcast(
                ServerMessage::Snapshot {
                    players: snapshot,
                },
            )
            .await;
        }
    }
}