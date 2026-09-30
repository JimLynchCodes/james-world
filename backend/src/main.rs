
use std::net::SocketAddr;

use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::EnvFilter;

use taggame_backend::app::create_app;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let app = create_app();

    let address = SocketAddr::from(([0, 0, 0, 0], 8000));

    let listener = TcpListener::bind(address)
        .await
        .expect("failed to bind TCP listener");

    info!("TagGame server listening on {}", address);

    axum::serve(listener, app)
        .await
        .expect("TagGame server failed");
}