//! Deployment knobs: BIND_ADDR / PORT parsing, the ALLOWED_ORIGINS check on
//! the WebSocket upgrade, and graceful shutdown closing sockets with 1012.

use std::time::Duration;

use futures_util::StreamExt;
use taggame_backend::{
    app::{create_app_with, AppConfig},
    config::{allowed_origins, bind_addr, origin_allowed},
};
use tokio::sync::watch;
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, http::HeaderValue, protocol::frame::coding::CloseCode, Message},
};

#[test]
fn bind_addr_defaults_and_overrides() {
    assert_eq!(bind_addr(None, None).0.to_string(), "0.0.0.0:8000");
    assert_eq!(bind_addr(None, Some("9001")).0.to_string(), "0.0.0.0:9001");
    assert_eq!(bind_addr(Some("127.0.0.1:8000"), None).0.to_string(), "127.0.0.1:8000");
    // host only: PORT (or 8000) supplies the port
    assert_eq!(bind_addr(Some("127.0.0.1"), Some("8100")).0.to_string(), "127.0.0.1:8100");
    assert_eq!(bind_addr(Some("[::1]"), None).0.to_string(), "[::1]:8000");
    // BIND_ADDR with a port wins over PORT
    assert_eq!(bind_addr(Some("127.0.0.1:7000"), Some("8100")).0.to_string(), "127.0.0.1:7000");
    // junk falls back with a warning
    let (addr, warning) = bind_addr(Some("not an addr"), Some("nope"));
    assert_eq!(addr.to_string(), "0.0.0.0:8000");
    assert!(warning.is_some());
    assert!(bind_addr(Some(""), Some(" ")).1.is_none());
}

#[test]
fn origin_allowlist() {
    assert_eq!(allowed_origins(None), None);
    assert_eq!(allowed_origins(Some(" , ")), None);
    let list = allowed_origins(Some("https://JamesWorld.lol/, https://www.jamesworld.lol")).unwrap();
    assert_eq!(list, vec!["https://jamesworld.lol", "https://www.jamesworld.lol"]);
    assert!(origin_allowed(None, Some("https://evil.example")));
    assert!(origin_allowed(Some(&list), Some("https://jamesworld.lol")));
    assert!(origin_allowed(Some(&list), Some("https://WWW.jamesworld.lol/")));
    assert!(!origin_allowed(Some(&list), Some("https://evil.example")));
    assert!(!origin_allowed(Some(&list), Some("http://jamesworld.lol")));
    assert!(origin_allowed(Some(&list), None), "non-browser clients send no Origin");
}

async fn boot(config: AppConfig) -> String {
    let (app, _) = create_app_with(config);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    format!("ws://{}/ws", address)
}

fn request(url: &str, origin: &str) -> tokio_tungstenite::tungstenite::handshake::client::Request {
    let mut req = url.into_client_request().unwrap();
    req.headers_mut().insert("Origin", HeaderValue::from_str(origin).unwrap());
    req
}

#[tokio::test]
async fn websocket_upgrade_checks_allowed_origins() {
    let url = boot(AppConfig {
        allowed_origins: allowed_origins(Some("https://jamesworld.lol")),
        shutdown: None,
    })
    .await;
    assert!(connect_async(request(&url, "https://jamesworld.lol")).await.is_ok());
    let err = connect_async(request(&url, "https://evil.example")).await.unwrap_err();
    assert!(err.to_string().contains("403"), "{err}");
}

#[tokio::test]
async fn shutdown_closes_sockets_with_service_restart() {
    let (tx, rx) = watch::channel(false);
    let url = boot(AppConfig { allowed_origins: None, shutdown: Some(rx) }).await;
    let (mut socket, _) = connect_async(&url).await.unwrap();
    tokio::time::sleep(Duration::from_millis(100)).await;
    tx.send(true).unwrap();
    let close = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            match socket.next().await {
                Some(Ok(Message::Close(frame))) => return frame,
                Some(Ok(_)) => continue,
                other => panic!("expected a Close frame, got {other:?}"),
            }
        }
    })
    .await
    .expect("no Close frame within 2s")
    .expect("Close frame without a code");
    assert_eq!(close.code, CloseCode::Restart);
    // New connections are refused while shutting down.
    assert!(connect_async(&url).await.is_err());
}
