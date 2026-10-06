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

    /// Socket connected: register as a spectator (receive snapshots, no player
    /// yet). Bots may spawn so a lone title-screen visitor sees activity.
    pub async fn register_spectator(
        &self,
        connection_id: Uuid,
        sender: mpsc::Sender<ServerMessage>,
    ) {
        let (existing_players, spawned_bots) = {
            let mut world = self.world.lock().await;
            let existing = world
                .players
                .values()
                .map(|p| (p.id, p.name.clone(), p.skin))
                .collect::<Vec<_>>();
            let spawned_bots = world
                .add_spectator()
                .into_iter()
                .map(|id| (id, world.name_of(&id), world.skin_of(&id)))
                .collect::<Vec<_>>();
            (existing, spawned_bots)
        };

        // Hello before the connection is listed so it arrives first.
        let _ = sender.send(ServerMessage::Hello {}).await;

        {
            let mut connections = self.connections.lock().await;
            connections.insert(connection_id, sender.clone());
        }

        for (id, name, skin) in existing_players {
            let _ = sender
                .send(ServerMessage::PlayerJoined {
                    player_id: id,
                    name,
                    skin,
                })
                .await;
        }

        for (bot_id, bot_name, bot_skin) in spawned_bots {
            self.broadcast(ServerMessage::PlayerJoined {
                player_id: bot_id,
                name: bot_name,
                skin: bot_skin,
            })
            .await;
        }
    }

    /// Promote a spectator to a player. Sends Welcome to them and announces
    /// the join to everyone else. Idempotent if they already joined.
    pub async fn join(
        &self,
        player_id: Uuid,
        skin: Option<String>,
    ) {
        use crate::game::skin::Skin;

        let already = {
            let world = self.world.lock().await;
            world.players.contains_key(&player_id)
        };
        if already {
            if let Some(skin) = skin {
                self.world
                    .lock()
                    .await
                    .set_skin(player_id, Skin::parse(&skin));
            }
            return;
        }

        // Leaving spectator status before becoming a human so bot presence
        // stays continuous (spectators→humans never dips to zero).
        let (name, player_skin, spawned_bots) = {
            let mut world = self.world.lock().await;
            // Spectator → human: drop the spectator seat first so presence
            // never dips to zero (bots stay).
            world.release_spectator_seat();
            let spawned = world
                .add_player(player_id)
                .into_iter()
                .map(|id| (id, world.name_of(&id), world.skin_of(&id)))
                .collect::<Vec<_>>();
            if let Some(skin) = skin {
                world.set_skin(player_id, Skin::parse(&skin));
            }
            (world.name_of(&player_id), world.skin_of(&player_id), spawned)
        };

        self.send_to(
            player_id,
            ServerMessage::Welcome {
                player_id,
                name: name.clone(),
            },
        )
        .await;

        self.broadcast_except(
            player_id,
            ServerMessage::PlayerJoined {
                player_id,
                name,
                skin: player_skin,
            },
        )
        .await;

        for (bot_id, bot_name, bot_skin) in spawned_bots {
            self.broadcast(ServerMessage::PlayerJoined {
                player_id: bot_id,
                name: bot_name,
                skin: bot_skin,
            })
            .await;
        }
    }

    pub async fn unregister(
        &self,
        connection_id: Uuid,
    ) {
        {
            let mut connections = self.connections.lock().await;
            connections.remove(&connection_id);
        }

        let (was_player, removed_bots) = {
            let mut world = self.world.lock().await;
            if world.players.contains_key(&connection_id) {
                (true, world.remove_player(connection_id))
            } else {
                (false, world.remove_spectator())
            }
        };

        if was_player {
            self.broadcast(ServerMessage::PlayerLeft {
                player_id: connection_id,
            })
            .await;
        }

        for bot_id in removed_bots {
            self.broadcast(ServerMessage::PlayerLeft {
                player_id: bot_id,
            })
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