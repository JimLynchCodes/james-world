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
        brawler::{BrawlerEvent, BrawlerWorld, PLAYER_MAX_HP},
        cosmetic::Cosmetic,
        skin::Skin,
        world::World,
    },
    ws::protocol::ServerMessage,
};

const TICK_RATE: u64 = 30;

#[derive(Clone)]
pub struct RoomManager {
    pub world: Arc<Mutex<World>>,

    /// Co-op sword brawler arena (separate from the playground tag world).
    pub brawler: Arc<Mutex<BrawlerWorld>>,

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

            brawler: Arc::new(Mutex::new(BrawlerWorld::new())),

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
                .map(|p| (p.id, p.name.clone(), p.skin.clone(), p.cosmetic.clone(), p.position.x, p.position.y))
                .collect::<Vec<_>>();
            let spawned_bots = world
                .add_spectator()
                .into_iter()
                .map(|id| {
                    let player = &world.players[&id];
                    (
                        id,
                        player.name.clone(),
                        player.skin.clone(),
                        player.cosmetic.clone(),
                        player.position.x,
                        player.position.y,
                    )
                })
                .collect::<Vec<_>>();
            (existing, spawned_bots)
        };

        // Hello before the connection is listed so it arrives first.
        let _ = sender.send(ServerMessage::Hello {}).await;

        {
            let mut connections = self.connections.lock().await;
            connections.insert(connection_id, sender.clone());
        }

        for (id, name, skin, cosmetic, x, y) in existing_players {
            let _ = sender
                .send(ServerMessage::PlayerJoined {
                    player_id: id,
                    name,
                    skin,
                    cosmetic,
                    x,
                    y,
                })
                .await;
        }

        for (bot_id, bot_name, bot_skin, bot_cosmetic, x, y) in spawned_bots {
            self.broadcast(ServerMessage::PlayerJoined {
                player_id: bot_id,
                name: bot_name,
                skin: bot_skin,
                cosmetic: bot_cosmetic,
                x,
                y,
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
        cosmetic: Option<String>,
    ) {
        let already = {
            let world = self.world.lock().await;
            world.players.contains_key(&player_id)
        };
        if already {
            let mut world = self.world.lock().await;
            if let Some(skin) = skin {
                world.set_skin(player_id, Skin::parse(&skin));
            }
            if let Some(cosmetic) = cosmetic {
                world.set_cosmetic(player_id, Cosmetic::parse(&cosmetic));
            }
            return;
        }

        // Leaving spectator status before becoming a human so bot presence
        // stays continuous (spectators→humans never dips to zero).
        let (name, player_skin, player_cosmetic, spawn_x, spawn_y, spawned_bots) = {
            let mut world = self.world.lock().await;
            // Spectator → human: drop the spectator seat first so presence
            // never dips to zero (bots stay).
            world.release_spectator_seat();
            let spawned = world
                .add_player(player_id)
                .into_iter()
                .map(|id| {
                    let player = &world.players[&id];
                    (
                        id,
                        player.name.clone(),
                        player.skin.clone(),
                        player.cosmetic.clone(),
                        player.position.x,
                        player.position.y,
                    )
                })
                .collect::<Vec<_>>();
            if let Some(skin) = skin {
                world.set_skin(player_id, Skin::parse(&skin));
            }
            if let Some(cosmetic) = cosmetic {
                world.set_cosmetic(player_id, Cosmetic::parse(&cosmetic));
            }
            let player = &world.players[&player_id];
            (
                player.name.clone(),
                player.skin.clone(),
                player.cosmetic.clone(),
                player.position.x,
                player.position.y,
                spawned,
            )
        };

        self.send_to(
            player_id,
            ServerMessage::Welcome {
                player_id,
                name: name.clone(),
                x: spawn_x,
                y: spawn_y,
            },
        )
        .await;

        self.broadcast_except(
            player_id,
            ServerMessage::PlayerJoined {
                player_id,
                name,
                skin: player_skin,
                cosmetic: player_cosmetic,
                x: spawn_x,
                y: spawn_y,
            },
        )
        .await;

        for (bot_id, bot_name, bot_skin, bot_cosmetic, x, y) in spawned_bots {
            self.broadcast(ServerMessage::PlayerJoined {
                player_id: bot_id,
                name: bot_name,
                skin: bot_skin,
                cosmetic: bot_cosmetic,
                x,
                y,
            })
            .await;
        }
    }

    pub async fn unregister(
        &self,
        connection_id: Uuid,
    ) {
        // Drop out of the brawler first so an empty arena resets.
        {
            let mut brawler = self.brawler.lock().await;
            brawler.leave(connection_id);
        }

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


    /// Join the co-op brawler. Player should already be away from the playground.
    pub async fn join_brawler(&self, player_id: Uuid) {
        let (name, skin, cosmetic) = {
            let world = self.world.lock().await;
            match world.players.get(&player_id) {
                // Playground bots stay in the playground — never enter the brawler.
                Some(p) if p.is_bot => return,
                Some(p) => (p.name.clone(), p.skin.clone(), p.cosmetic.clone()),
                None => return,
            }
        };
        // Ensure they stay hidden in the playground.
        {
            let mut world = self.world.lock().await;
            world.set_away(player_id, true);
        }
        let (x, y) = {
            let mut brawler = self.brawler.lock().await;
            brawler.join(player_id, name, skin, cosmetic)
        };
        self.send_to(
            player_id,
            ServerMessage::BrawlerWelcome {
                player_id,
                x,
                y,
                hp: PLAYER_MAX_HP,
                max_hp: PLAYER_MAX_HP,
            },
        )
        .await;
        // Immediate snapshot so the joiner sees peers/enemies without waiting a tick.
        let snap = {
            let brawler = self.brawler.lock().await;
            brawler.snapshot()
        };
        self.send_to(
            player_id,
            ServerMessage::BrawlerSnapshot { snapshot: snap },
        )
        .await;
    }

    pub async fn leave_brawler(&self, player_id: Uuid) {
        let mut brawler = self.brawler.lock().await;
        brawler.leave(player_id);
    }

    pub async fn brawler_input(
        &self,
        player_id: Uuid,
        dx: f32,
        dy: f32,
        attack: bool,
    ) {
        let mut brawler = self.brawler.lock().await;
        brawler.set_input(player_id, dx, dy, attack);
    }

    /// Award the crown cosmetic on the playground player record.
    pub async fn award_crown(&self, player_id: Uuid) {
        let mut world = self.world.lock().await;
        world.set_cosmetic(player_id, Cosmetic::parse(Cosmetic::CROWN));
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
            let dt = 1.0 / TICK_RATE as f32;

            let (snapshot, bot_tags) = {
                let mut world =
                    self.world
                        .lock()
                        .await;

                world.advance_tick(dt);

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

            // Brawler: advance and fan out only to members of the arena.
            let (brawler_snap, events, member_ids) = {
                let mut brawler = self.brawler.lock().await;
                let events = brawler.advance(dt);
                let members: Vec<Uuid> = brawler.players.keys().copied().collect();
                (brawler.snapshot(), events, members)
            };

            for event in events {
                match event {
                    BrawlerEvent::PlayerDied { player_id } => {
                        self.send_to(
                            player_id,
                            ServerMessage::BrawlerPlayerDied { player_id },
                        )
                        .await;
                    }
                    BrawlerEvent::Won { player_ids } => {
                        for pid in &player_ids {
                            self.award_crown(*pid).await;
                        }
                        let msg = ServerMessage::BrawlerWon {
                            player_ids: player_ids.clone(),
                        };
                        for pid in &member_ids {
                            self.send_to(*pid, msg.clone()).await;
                        }
                    }
                }
            }

            if !member_ids.is_empty() {
                let msg = ServerMessage::BrawlerSnapshot {
                    snapshot: brawler_snap,
                };
                for pid in &member_ids {
                    self.send_to(*pid, msg.clone()).await;
                }
            }
        }
    }
}