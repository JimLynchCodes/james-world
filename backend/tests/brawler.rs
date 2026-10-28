//! Co-op sword brawler room lifecycle.
use futures_util::{SinkExt, StreamExt};
use taggame_backend::game::brawler::{BrawlerWorld, PLAYER_MAX_HP, SPAWN_BEHIND};
use taggame_backend::game::cosmetic::Cosmetic;
use taggame_backend::game::skin::Skin;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use uuid::Uuid;

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
        let Ok(text) = message.into_text() else {
            continue;
        };
        let value: serde_json::Value = serde_json::from_str(&text).unwrap();
        if value["type"] == want {
            return value;
        }
    }
}

async fn join_playground(url: &str) -> (tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>, String) {
    let (mut socket, _) = connect_async(url).await.unwrap();
    let _ = next_typed(&mut socket, "Hello").await;
    socket
        .send(Message::Text(
            r#"{"type":"Join","data":{"room_id":"default","skin":"james"}}"#.into(),
        ))
        .await
        .unwrap();
    let welcome = next_typed(&mut socket, "Welcome").await;
    let id = welcome["data"]["player_id"].as_str().unwrap().to_string();
    (socket, id)
}

#[test]
fn unit_fresh_creation_spawn_behind_no_ff_reset() {
    // Mirror of the lib unit tests, kept here so `cargo test` integration
    // suite also covers the lifecycle contract called out in the PR.
    let mut w = BrawlerWorld::new();
    let a = Uuid::new_v4();
    let b = Uuid::new_v4();
    w.join(a, "James 1".into(), Skin::default(), Cosmetic::default());
    assert_eq!(w.wave, 1);
    assert!(!w.enemies.is_empty());

    w.players.get_mut(&a).unwrap().x = 400.0;
    let (bx, _) = w.join(b, "James 2".into(), Skin::default(), Cosmetic::default());
    assert!((bx - (400.0 - SPAWN_BEHIND)).abs() < 1.0);

    // Friendly fire: attacking teammate does nothing.
    {
        let p = w.players.get_mut(&a).unwrap();
        p.x = 100.0;
        p.y = 200.0;
        p.facing = 0.0;
        p.attacking = true;
    }
    {
        let p = w.players.get_mut(&b).unwrap();
        p.x = 120.0;
        p.y = 200.0;
        p.hp = PLAYER_MAX_HP;
    }
    w.enemies.clear();
    // resolve via a tick with no enemies: HP stays full
    let hp_before = w.players[&b].hp;
    w.set_input(a, 0.0, 0.0, true);
    let _ = w.advance(0.05);
    assert!((w.players[&b].hp - hp_before).abs() < 0.01);

    w.leave(a);
    w.leave(b);
    assert!(w.is_empty());
    assert!(w.enemies.is_empty());
    assert_eq!(w.wave, 0);
}

#[tokio::test]
async fn ws_join_brawler_welcome_and_empty_resets() {
    let url = boot().await;
    let (mut a, a_id) = join_playground(&url).await;

    // Mark away (as the cave does) then enter the brawler.
    a.send(Message::Text(r#"{"type":"SetAway","data":{"away":true}}"#.into()))
        .await
        .unwrap();
    a.send(Message::Text(r#"{"type":"JoinBrawler","data":{}}"#.into()))
        .await
        .unwrap();

    let welcome = next_typed(&mut a, "BrawlerWelcome").await;
    assert_eq!(welcome["data"]["player_id"], a_id);
    assert!(welcome["data"]["hp"].as_f64().unwrap() > 0.0);

    let snap = next_typed(&mut a, "BrawlerSnapshot").await;
    assert!(
        snap["data"]["enemies"].as_array().unwrap().len() >= 1,
        "fresh room should have wave-1 enemies"
    );
    assert_eq!(snap["data"]["wave"], 1);

    // Second player joins and should spawn behind A once A has walked right.
    // Move A via input for a bit.
    for _ in 0..20 {
        a.send(Message::Text(
            r#"{"type":"BrawlerInput","data":{"seq":1,"dx":1,"dy":0,"attack":false}}"#.into(),
        ))
        .await
        .unwrap();
        let _ = next_typed(&mut a, "BrawlerSnapshot").await;
    }

    let (mut b, b_id) = join_playground(&url).await;
    b.send(Message::Text(r#"{"type":"SetAway","data":{"away":true}}"#.into()))
        .await
        .unwrap();
    b.send(Message::Text(r#"{"type":"JoinBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    let b_welcome = next_typed(&mut b, "BrawlerWelcome").await;
    assert_eq!(b_welcome["data"]["player_id"], b_id);
    let bx = b_welcome["data"]["x"].as_f64().unwrap();

    // A's x from a snapshot should be ahead of B.
    let snap = next_typed(&mut b, "BrawlerSnapshot").await;
    let players = snap["data"]["players"].as_array().unwrap();
    let a_snap = players.iter().find(|p| p["id"] == a_id).unwrap();
    let ax = a_snap["x"].as_f64().unwrap();
    assert!(
        bx < ax,
        "joiner ({bx}) should spawn behind furthest-right ({ax})"
    );

    // Both leave → room resets for the next joiner.
    a.send(Message::Text(r#"{"type":"LeaveBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    b.send(Message::Text(r#"{"type":"LeaveBrawler","data":{}}"#.into()))
        .await
        .unwrap();

    // Rejoin: should be a fresh wave 1 at the start.
    a.send(Message::Text(r#"{"type":"JoinBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    let _ = next_typed(&mut a, "BrawlerWelcome").await;
    let snap = next_typed(&mut a, "BrawlerSnapshot").await;
    assert_eq!(snap["data"]["wave"], 1);
    let me = snap["data"]["players"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["id"] == a_id)
        .unwrap();
    assert!(
        me["x"].as_f64().unwrap() < 150.0,
        "fresh run should start near the left"
    );
}

#[tokio::test]
async fn cosmetic_crown_round_trips_in_snapshot() {
    let url = boot().await;
    let (mut a, a_id) = join_playground(&url).await;
    a.send(Message::Text(
        r#"{"type":"SetCosmetic","data":{"cosmetic":"crown"}}"#.into(),
    ))
    .await
    .unwrap();

    // Wait for a snapshot that shows our crown.
    for _ in 0..40 {
        let snap = next_typed(&mut a, "Snapshot").await;
        if let Some(me) = snap["data"]["players"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["id"] == a_id)
        {
            if me["cosmetic"] == "crown" {
                return;
            }
        }
    }
    panic!("crown never appeared in playground snapshot");
}
