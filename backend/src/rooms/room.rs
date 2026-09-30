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
    game::{
        world::World,
    },
    ws::protocol::ServerMessage,
};

const TICK_RATE: u64 = 30;

#[derive(Clone)]
pub struct RoomManager {
    pub world: Arc<Mutex<World>>,

    connections:
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
                Mutex::new(World::new())
            ),

            connections: Arc::new(
                Mutex::new(HashMap::new())
            ),
        }
    }

    pub async fn register(
        &self,
        player_id: Uuid,
        sender: mpsc::Sender<ServerMessage>,
    ) {
        {
            let mut connections =
                self.connections.lock().await;

            connections.insert(
                player_id,
                sender,
            );
        }

        self.world
            .lock()
            .await
            .add_player(player_id);

        self.broadcast(
            ServerMessage::PlayerJoined {
                player_id,
            },
        )
        .await;
    }

    pub async fn unregister(
        &self,
        player_id: Uuid,
    ) {
        {
            let mut connections =
                self.connections.lock().await;

            connections.remove(&player_id);
        }

        self.world
            .lock()
            .await
            .remove_player(player_id);

        self.broadcast(
            ServerMessage::PlayerLeft {
                player_id,
            },
        )
        .await;
    }

    pub async fn send_to(
        &self,
        player_id: Uuid,
        message: ServerMessage,
    ) {
        let sender = {
            let connections =
                self.connections.lock().await;

            connections
                .get(&player_id)
                .cloned()
        };

        if let Some(sender) = sender {
            let _ = sender.send(message).await;
        }
    }

    pub async fn broadcast(
        &self,
        message: ServerMessage,
    ) {
        let connections = {
            let connections =
                self.connections.lock().await;

            connections
                .values()
                .cloned()
                .collect::<Vec<_>>()
        };

        for sender in connections {
            let _ = sender
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

            let snapshot = {
                let mut world =
                    self.world.lock().await;

                world.advance_tick(
                    1.0 / TICK_RATE as f32
                );

                world.snapshot()
            };

            self.broadcast(
                ServerMessage::Snapshot {
                    players: snapshot,
                },
            )
            .await;
        }
    }
}