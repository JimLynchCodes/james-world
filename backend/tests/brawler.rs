//! Co-op sword brawler room lifecycle.
use futures_util::{SinkExt, StreamExt};
use taggame_backend::game::brawler::{
    segment_trigger, BrawlerWorld, PLAYER_MAX_HP, SPAWN_BEHIND,
};
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

async fn join_playground(
    url: &str,
) -> (
    tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
    String,
) {
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
    let mut w = BrawlerWorld::new();
    let a = Uuid::new_v4();
    let b = Uuid::new_v4();
    w.join(a, "James 1".into(), Skin::default(), Cosmetic::default());
    assert_eq!(w.wave, 0);
    assert!(
        w.enemies.is_empty(),
        "no enemies until the lead player reaches a segment trigger"
    );

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

#[test]
fn unit_wave_triggers_by_x_position() {
    let mut w = BrawlerWorld::new();
    let a = Uuid::new_v4();
    w.join(a, "James 1".into(), Skin::default(), Cosmetic::default());
    assert!(w.enemies.is_empty());
    w.players.get_mut(&a).unwrap().x = segment_trigger(1) - 5.0;
    let _ = w.advance(0.05);
    assert!(w.enemies.is_empty());
    w.players.get_mut(&a).unwrap().x = segment_trigger(1) + 2.0;
    let _ = w.advance(0.05);
    assert!(!w.enemies.is_empty());
    assert_eq!(w.wave, 1);
    let snap = w.snapshot();
    assert!(snap.lock_right.is_some());
    assert!(!snap.show_go);
    w.enemies.clear();
    let _ = w.advance(0.05);
    let snap = w.snapshot();
    assert!(snap.show_go);
    assert!(snap.lock_right.is_none());
}

#[tokio::test]
async fn ws_join_brawler_welcome_and_empty_resets() {
    let url = boot().await;
    let (mut a, a_id) = join_playground(&url).await;

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
        snap["data"]["enemies"].as_array().unwrap().is_empty(),
        "fresh room must have no enemies before the first segment"
    );
    assert_eq!(snap["data"]["wave"], 0);

    // Walk right until wave 1 triggers.
    let mut saw_wave = false;
    for _ in 0..200 {
        a.send(Message::Text(
            r#"{"type":"BrawlerInput","data":{"seq":1,"dx":1,"dy":0,"attack":false}}"#.into(),
        ))
        .await
        .unwrap();
        let snap = next_typed(&mut a, "BrawlerSnapshot").await;
        if snap["data"]["wave"].as_u64().unwrap_or(0) >= 1
            && !snap["data"]["enemies"].as_array().unwrap().is_empty()
        {
            saw_wave = true;
            break;
        }
    }
    assert!(saw_wave, "walking right should trigger wave 1");

    // Second player joins and should spawn behind A.
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

    let snap = next_typed(&mut b, "BrawlerSnapshot").await;
    let players = snap["data"]["players"].as_array().unwrap();
    let a_snap = players.iter().find(|p| p["id"] == a_id).unwrap();
    let ax = a_snap["x"].as_f64().unwrap();
    assert!(
        bx < ax,
        "joiner ({bx}) should spawn behind furthest-right ({ax})"
    );

    a.send(Message::Text(r#"{"type":"LeaveBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    b.send(Message::Text(r#"{"type":"LeaveBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    // Let the server drain leave before we rejoin (no leave-ack on the wire).
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;

    a.send(Message::Text(r#"{"type":"JoinBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    let _ = next_typed(&mut a, "BrawlerWelcome").await;
    let snap = next_typed(&mut a, "BrawlerSnapshot").await;
    assert_eq!(snap["data"]["wave"], 0);
    assert!(snap["data"]["enemies"].as_array().unwrap().is_empty());
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
async fn ws_brawler_snapshot_has_no_bots() {
    let url = boot().await;
    let (mut a, a_id) = join_playground(&url).await;

    // Wait until playground bots exist.
    let mut saw_bot = false;
    for _ in 0..80 {
        let snap = next_typed(&mut a, "Snapshot").await;
        let players = snap["data"]["players"].as_array().unwrap();
        if players.iter().any(|p| p["is_bot"] == true) {
            saw_bot = true;
            break;
        }
    }
    assert!(saw_bot, "playground should spawn computer Jameses");

    a.send(Message::Text(r#"{"type":"SetAway","data":{"away":true}}"#.into()))
        .await
        .unwrap();
    a.send(Message::Text(r#"{"type":"JoinBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    let _ = next_typed(&mut a, "BrawlerWelcome").await;
    let snap = next_typed(&mut a, "BrawlerSnapshot").await;
    let players = snap["data"]["players"].as_array().unwrap();
    assert_eq!(players.len(), 1, "only the human should be in the brawler");
    assert_eq!(players[0]["id"], a_id);
    // Brawler player snaps have no is_bot field; presence of only the human is the contract.
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

#[test]
fn playtest_two_waves_side_scroller_by_x() {
    let mut w = BrawlerWorld::new();
    let a = Uuid::new_v4();
    w.join(a, "James 1".into(), Skin::default(), Cosmetic::default());
    assert!(w.enemies.is_empty());

    // Approach segment 1 — still quiet.
    w.players.get_mut(&a).unwrap().x = segment_trigger(1) - 20.0;
    let _ = w.advance(0.05);
    assert!(w.enemies.is_empty());

    // Cross trigger → wave 1 locks in.
    w.players.get_mut(&a).unwrap().x = segment_trigger(1) + 5.0;
    let _ = w.advance(0.05);
    assert_eq!(w.wave, 1);
    assert!(!w.enemies.is_empty());
    assert!(w.lock_right.is_some());
    assert!(!w.show_go);
    let enemy_count = w.enemies.len();

    // Fight: walk into the pack and swing with rising-edge presses.
    for tick in 0..500 {
        let x = w.players[&a].x;
        let nearest = w
            .enemies
            .iter()
            .map(|e| e.x)
            .fold(f32::MAX, f32::min);
        let dx = if nearest > x + 20.0 {
            1.0
        } else if nearest < x - 20.0 {
            -1.0
        } else {
            0.0
        };
        // Rising edge every ~12 ticks (~0.4s at 30Hz-ish dt of 0.05 → every 12*0.05=0.6s).
        let press = tick % 12 == 0;
        w.set_input(a, dx, 0.0, press);
        let _ = w.advance(0.05);
        if press {
            w.set_input(a, dx, 0.0, false);
        }
        if w.enemies.is_empty() {
            break;
        }
        if w.players[&a].dead {
            panic!("player died clearing wave 1 (started with {enemy_count} enemies)");
        }
    }
    assert!(w.enemies.is_empty(), "wave 1 should be clearable in-range");
    let _ = w.advance(0.05);
    assert!(w.show_go, "cleared wave should show GO");
    assert!(w.lock_right.is_none());

    // Advance to segment 2.
    w.players.get_mut(&a).unwrap().x = segment_trigger(2) + 5.0;
    let _ = w.advance(0.05);
    assert_eq!(w.wave, 2);
    assert!(!w.enemies.is_empty());
    assert!(!w.show_go);
    assert!(w.lock_right.is_some());
}

#[tokio::test]
async fn ws_wave_one_triggers_on_walk_right() {
    let url = boot().await;
    let (mut a, _a_id) = join_playground(&url).await;
    a.send(Message::Text(r#"{"type":"SetAway","data":{"away":true}}"#.into()))
        .await
        .unwrap();
    a.send(Message::Text(r#"{"type":"JoinBrawler","data":{}}"#.into()))
        .await
        .unwrap();
    let _ = next_typed(&mut a, "BrawlerWelcome").await;
    let snap = next_typed(&mut a, "BrawlerSnapshot").await;
    assert!(snap["data"]["enemies"].as_array().unwrap().is_empty());
    assert_eq!(snap["data"]["wave"], 0);

    let mut wave1 = false;
    for i in 0..250 {
        a.send(Message::Text(
            format!(
                r#"{{"type":"BrawlerInput","data":{{"seq":{},"dx":1,"dy":0,"attack":false}}}}"#,
                i
            )
            .into(),
        ))
        .await
        .unwrap();
        let snap = next_typed(&mut a, "BrawlerSnapshot").await;
        if snap["data"]["wave"].as_u64().unwrap_or(0) >= 1 {
            wave1 = true;
            assert!(!snap["data"]["enemies"].as_array().unwrap().is_empty());
            assert!(snap["data"]["lock_right"].as_f64().is_some());
            break;
        }
    }
    assert!(wave1, "walking right should trigger wave 1 over the wire");
}
