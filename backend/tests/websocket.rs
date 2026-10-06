
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