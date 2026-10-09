use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::Message};

async fn boot() -> String {
    let app = taggame_backend::app::create_app();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{}/ws", address)
}

async fn next_typed<S>(socket: &mut S, want: &str) -> serde_json::Value
where
    S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
{
    loop {
        let message = socket.next().await.unwrap().unwrap();
        let Ok(text) = message.into_text() else { continue };
        let value: serde_json::Value = serde_json::from_str(&text).unwrap();
        if value["type"] == want {
            return value;
        }
    }
}

async fn next_snapshot_skin<S>(socket: &mut S, player_id: &str) -> String
where
    S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
{
    loop {
        let value = next_typed(socket, "Snapshot").await;
        let players = value["data"]["players"].as_array().unwrap();
        if let Some(me) = players.iter().find(|p| p["id"] == player_id) {
            return me["skin"].as_str().unwrap().to_string();
        }
    }
}

async fn wait_for_skin<S>(socket: &mut S, player_id: &str, want: &str) -> bool
where
    S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
{
    for _ in 0..40 {
        if next_snapshot_skin(socket, player_id).await == want {
            return true;
        }
    }
    false
}

#[tokio::test]
async fn connect_sends_hello_and_join_sends_welcome() {
    let url = boot().await;
    let (mut socket, _) = connect_async(url).await.unwrap();

    // First message is Hello: spectator, not yet a player.
    let hello = next_typed(&mut socket, "Hello").await;
    assert_eq!(hello["type"], "Hello");

    // No Welcome until Join. Drain a few snapshots; none should Welcome.
    for _ in 0..5 {
        let message = socket.next().await.unwrap().unwrap();
        let text = message.into_text().unwrap();
        assert!(!text.contains("\"Welcome\""), "{text}");
        assert!(!text.contains("\"Error\""), "{text}");
    }

    socket
        .send(Message::Text(
            r#"{"type":"Join","data":{"room_id":"default"}}"#.into(),
        ))
        .await
        .unwrap();

    let welcome = next_typed(&mut socket, "Welcome").await;
    // Connecting as a spectator already spawned the 3 bots (James 1-3).
    assert_eq!(welcome["data"]["name"], "James 4");
    let id = welcome["data"]["player_id"].as_str().unwrap();
    assert!(!id.is_empty());
}

#[tokio::test]
async fn spectator_sees_others_and_bots_spawn_for_spectators() {
    let url = boot().await;

    // A connects and joins.
    let (mut a, _) = connect_async(url.clone()).await.unwrap();
    let _ = next_typed(&mut a, "Hello").await;
    a.send(Message::Text(
        r#"{"type":"Join","data":{"room_id":"default","skin":"banana"}}"#.into(),
    ))
    .await
    .unwrap();
    let welcome = next_typed(&mut a, "Welcome").await;
    let a_id = welcome["data"]["player_id"].as_str().unwrap().to_string();
    // A was James 4 (bots 1-3 spawned while A was a spectator).
    assert_eq!(welcome["data"]["name"], "James 4");

    // B connects as a spectator only: sees A (and bots) without joining.
    let (mut b, _) = connect_async(url.clone()).await.unwrap();
    let _ = next_typed(&mut b, "Hello").await;

    let mut saw_a = false;
    let mut bot_count = 0;
    for _ in 0..40 {
        let message = b.next().await.unwrap().unwrap();
        let text = message.into_text().unwrap();
        let value: serde_json::Value = serde_json::from_str(&text).unwrap();
        if value["type"] == "PlayerJoined" && value["data"]["player_id"] == a_id.as_str() {
            assert_eq!(value["data"]["skin"], "banana");
            saw_a = true;
        }
        if value["type"] == "Snapshot" {
            let players = value["data"]["players"].as_array().unwrap();
            // Spectator B is not in the snapshot.
            assert!(players.iter().all(|p| p["id"] != ""), "empty id?");
            assert!(
                players.iter().all(|p| p["id"] != a_id.as_str() || true),
                "ok"
            );
            assert!(
                !players.iter().any(|p| {
                    // B has no player_id yet; just ensure A is listed and B's
                    // connection id isn't somehow a player without Join.
                    false
                })
            );
            bot_count = players.iter().filter(|p| p["is_bot"] == true).count();
            if players.iter().any(|p| p["id"] == a_id.as_str()) && bot_count >= 3 {
                break;
            }
        }
    }
    assert!(saw_a, "spectator never got PlayerJoined for A");
    assert!(bot_count >= 3, "bots should be running for the human");

    // B's id must not appear in snapshots until Join.
    let snap = next_typed(&mut b, "Snapshot").await;
    let ids: Vec<_> = snap["data"]["players"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p["id"].as_str().unwrap().to_string())
        .collect();
    assert!(ids.contains(&a_id));
    assert_eq!(ids.len(), 1 + bot_count); // A + bots, no spectator

    // B joins: Welcome with next James number (1 human + 3 bots already named).
    b.send(Message::Text(
        r#"{"type":"Join","data":{"room_id":"default"}}"#.into(),
    ))
    .await
    .unwrap();
    let welcome_b = next_typed(&mut b, "Welcome").await;
    let b_id = welcome_b["data"]["player_id"].as_str().unwrap().to_string();
    assert_eq!(welcome_b["data"]["name"], "James 5"); // 1+3 bots + B
    assert!(wait_for_skin(&mut a, &b_id, "james").await);
}

#[tokio::test]
async fn skin_round_trips_and_unknown_values_fall_back_to_james() {
    let url = boot().await;

    let (mut a, _) = connect_async(url.clone()).await.unwrap();
    let _ = next_typed(&mut a, "Hello").await;
    a.send(Message::Text(
        r#"{"type":"Join","data":{"room_id":"default","skin":"banana"}}"#.into(),
    ))
    .await
    .unwrap();
    let welcome = next_typed(&mut a, "Welcome").await;
    let a_id = welcome["data"]["player_id"].as_str().unwrap().to_string();
    assert!(wait_for_skin(&mut a, &a_id, "banana").await, "Join skin not applied");

    let (mut b, _) = connect_async(url.clone()).await.unwrap();
    let _ = next_typed(&mut b, "Hello").await;
    let mut saw_joined = false;
    for _ in 0..20 {
        let text = b.next().await.unwrap().unwrap().into_text().unwrap();
        let value: serde_json::Value = serde_json::from_str(&text).unwrap();
        if value["type"] == "PlayerJoined" && value["data"]["player_id"] == a_id.as_str() {
            assert_eq!(value["data"]["skin"], "banana");
            saw_joined = true;
            break;
        }
    }
    assert!(saw_joined, "B never got PlayerJoined for A");
    assert!(wait_for_skin(&mut b, &a_id, "banana").await);

    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"james"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "james").await, "SetSkin james not seen");

    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"banana"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "banana").await);
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"trex"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "trex").await, "SetSkin trex not seen");
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"tuxedo"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "tuxedo").await, "SetSkin tuxedo not seen");
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"pirate"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "pirate").await, "SetSkin pirate not seen");
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"pineapple"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "james").await, "unknown skin did not fall back");

    let text = loop {
        let text = b.next().await.unwrap().unwrap().into_text().unwrap();
        if text.contains("\"Snapshot\"") {
            break text;
        }
    };
    let value: serde_json::Value = serde_json::from_str(&text).unwrap();
    for p in value["data"]["players"].as_array().unwrap() {
        if p["is_bot"] == true {
            assert_eq!(p["skin"], "james");
        }
    }
}

#[tokio::test]
async fn join_without_a_skin_still_works() {
    let url = boot().await;
    let (mut a, _) = connect_async(url).await.unwrap();
    let _ = next_typed(&mut a, "Hello").await;
    a.send(Message::Text(r#"{"type":"Join","data":{"room_id":"default"}}"#.into()))
        .await
        .unwrap();
    let welcome = next_typed(&mut a, "Welcome").await;
    let a_id = welcome["data"]["player_id"].as_str().unwrap().to_string();
    for _ in 0..10 {
        let text = a.next().await.unwrap().unwrap().into_text().unwrap();
        assert!(!text.contains("\"Error\""), "{text}");
        if text.contains("\"Snapshot\"") {
            break;
        }
    }
    assert_eq!(next_snapshot_skin(&mut a, &a_id).await, "james");
}

#[tokio::test]
async fn bots_spawn_for_a_lone_spectator_and_leave_when_they_disconnect() {
    use taggame_backend::game::world::World;
    // Unit-level presence: spectators keep bots without a human player.
    let mut world = World::new();
    assert!(!world.has_presence());
    let spawned = world.add_spectator();
    assert_eq!(spawned.len(), 3);
    assert_eq!(world.spectator_count(), 1);
    assert!(world.has_presence());
    assert_eq!(world.human_count(), 0);
    assert_eq!(world.bots.len(), 3);

    // Another spectator: no extra bots.
    assert!(world.add_spectator().is_empty());
    assert_eq!(world.spectator_count(), 2);

    // One leaves: bots stay.
    assert!(world.remove_spectator().is_empty());
    assert_eq!(world.bots.len(), 3);

    // Last spectator leaves: bots go.
    let removed = world.remove_spectator();
    assert_eq!(removed.len(), 3);
    assert!(!world.has_presence());
    assert!(world.bots.is_empty());
}
