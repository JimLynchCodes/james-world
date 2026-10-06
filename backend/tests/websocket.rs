
use futures_util::StreamExt;
use tokio_tungstenite::connect_async;

#[tokio::test]
async fn websocket_sends_welcome() {
    let app = taggame_backend::app::create_app();

    let listener = tokio::net::TcpListener::bind(
        "127.0.0.1:0",
    )
    .await
    .unwrap();

    let address = listener.local_addr().unwrap();

    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let url = format!("ws://{}/ws", address);

    let (mut socket, _) =
        connect_async(url).await.unwrap();

    let message = socket.next().await.unwrap().unwrap();

    let text = message.into_text().unwrap();

    assert!(text.contains("Welcome"));

    // First player on a fresh server: "James 1".
    let welcome: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(welcome["data"]["name"], "James 1");
}
/// Read messages until a snapshot that contains `player_id`; returns its skin.
async fn next_snapshot_skin<S>(socket: &mut S, player_id: &str) -> String
where
    S: futures_util::Stream<Item = Result<tokio_tungstenite::tungstenite::Message, tokio_tungstenite::tungstenite::Error>>
        + Unpin,
{
    loop {
        let message = socket.next().await.unwrap().unwrap();
        let Ok(text) = message.into_text() else { continue };
        let value: serde_json::Value = serde_json::from_str(&text).unwrap();
        if value["type"] != "Snapshot" {
            continue;
        }
        let players = value["data"]["players"].as_array().unwrap();
        if let Some(me) = players.iter().find(|p| p["id"] == player_id) {
            return me["skin"].as_str().unwrap().to_string();
        }
    }
}

/// Skip snapshots that were already queued before the last change.
async fn wait_for_skin<S>(socket: &mut S, player_id: &str, want: &str) -> bool
where
    S: futures_util::Stream<Item = Result<tokio_tungstenite::tungstenite::Message, tokio_tungstenite::tungstenite::Error>>
        + Unpin,
{
    for _ in 0..30 {
        if next_snapshot_skin(socket, player_id).await == want {
            return true;
        }
    }
    false
}

#[tokio::test]
async fn skin_round_trips_and_unknown_values_fall_back_to_james() {
    use futures_util::SinkExt;
    use tokio_tungstenite::tungstenite::Message;

    let app = taggame_backend::app::create_app();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let url = format!("ws://{}/ws", address);

    // Player A joins wearing the banana costume.
    let (mut a, _) = connect_async(url.clone()).await.unwrap();
    let welcome: serde_json::Value =
        serde_json::from_str(&a.next().await.unwrap().unwrap().into_text().unwrap()).unwrap();
    let a_id = welcome["data"]["player_id"].as_str().unwrap().to_string();
    a.send(Message::Text(
        r#"{"type":"Join","data":{"room_id":"default","skin":"banana"}}"#.into(),
    ))
    .await
    .unwrap();
    assert!(wait_for_skin(&mut a, &a_id, "banana").await, "Join skin not applied");

    // Player B sees A as a banana: in the PlayerJoined for A and in snapshots.
    let (mut b, _) = connect_async(url.clone()).await.unwrap();
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

    // Live change back to james, seen by B.
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"james"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "james").await, "SetSkin james not seen");

    // Unknown skins are not an error: they fall back to james.
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"banana"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "banana").await);
    a.send(Message::Text(r#"{"type":"SetSkin","data":{"skin":"pineapple"}}"#.into()))
        .await
        .unwrap();
    assert!(wait_for_skin(&mut b, &a_id, "james").await, "unknown skin did not fall back");

    // Bots wear the default skin.
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
    use futures_util::SinkExt;
    use tokio_tungstenite::tungstenite::Message;

    let app = taggame_backend::app::create_app();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let (mut a, _) = connect_async(format!("ws://{}/ws", address)).await.unwrap();
    let welcome: serde_json::Value =
        serde_json::from_str(&a.next().await.unwrap().unwrap().into_text().unwrap()).unwrap();
    let a_id = welcome["data"]["player_id"].as_str().unwrap().to_string();
    // Old clients send Join without a skin: no Error, default skin.
    a.send(Message::Text(r#"{"type":"Join","data":{"room_id":"default"}}"#.into()))
        .await
        .unwrap();
    for _ in 0..10 {
        let text = a.next().await.unwrap().unwrap().into_text().unwrap();
        assert!(!text.contains("\"Error\""), "{text}");
    }
    assert_eq!(next_snapshot_skin(&mut a, &a_id).await, "james");
}
