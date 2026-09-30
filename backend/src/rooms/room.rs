
use std::{
    collections::HashMap,
    sync::Arc,
    time::Duration,
};

use tokio::{
    sync::{mpsc, Mutex},
    time,
};
use uuid::Uuid;

use crate::{
    game::world::World,
    ws::protocol::ServerMessage,
};

pub const TICK_RATE: u32 = 30;
pub const OUTBOUND_CAPACITY: usize = 64;

pub type OutboundSender = mpsc::Sender<ServerMessage>;

#[derive(Clone)]
pub struct RoomManager {
    pub world: Arc<Mutex<World>>,
    pub connections: Arc<Mutex<HashMap<Uuid, OutboundSender>>>,
}

impl RoomManager {
    pub fn new(world: World) -> Self {
        let manager = Self {
            world: Arc::new(Mutex::new(world)),
            connections: Arc::new(Mutex::new(HashMap::new())),
        };

        manager.start_game_loop();

        manager
    }

    pub async fn register(
        &self,
        player_id: Uuid,
    ) -> (
        OutboundSender,
        mpsc::Receiver<ServerMessage>,
    ) {
        let (tx, rx) =
            mpsc::channel(OUTBOUND_CAPACITY);

        self.connections
            .lock()
            .await
            .insert(player_id, tx.clone());

        (tx, rx)
    }

    pub async fn unregister(&self, player_id: Uuid) {
        self.connections.lock().await.remove(&player_id);

        self.world.lock().await.remove_player(player_id);

        self.broadcast(ServerMessage::PlayerLeft {
            player_id,
        })
        .await;
    }

    pub async fn broadcast(&self, message: ServerMessage) {
        let mut connections = self.connections.lock().await;

        connections.retain(|_, sender| {
            match sender.try_send(message.clone()) {
                Ok(()) => true,
                Err(mpsc::error::TrySendError::Closed(_)) => false,
                Err(mpsc::error::TrySendError::Full(_)) => true,
            }
        });
    }

    pub async fn start_tick(&self) {
        let snapshot = {
            let mut world = self.world.lock().await;

            world.advance_tick(1.0 / TICK_RATE as f32);

            world.snapshot()
        };

        self.broadcast(snapshot).await;
    }

    fn start_game_loop(&self) {
        let manager = self.clone();

        tokio::spawn(async move {
            let mut interval = time::interval(
                Duration::from_secs_f64(
                    1.0 / TICK_RATE as f64,
                ),
            );

            loop {
                interval.tick().await;
                manager.start_tick().await;
            }
        });
    }
}