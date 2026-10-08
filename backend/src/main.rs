use std::time::Duration;

use tokio::{net::TcpListener, sync::watch};
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

use taggame_backend::{
    app::{create_app_with, AppConfig},
    config,
};

/// After a shutdown signal, how long open WebSockets get to close cleanly.
const DRAIN_TIMEOUT: Duration = Duration::from_secs(3);

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let (address, warning) = config::bind_addr(
        std::env::var("BIND_ADDR").ok().as_deref(),
        std::env::var("PORT").ok().as_deref(),
    );
    if let Some(warning) = warning {
        warn!("{warning}");
    }
    let allowed_origins = config::allowed_origins(std::env::var("ALLOWED_ORIGINS").ok().as_deref());
    match &allowed_origins {
        Some(list) => info!("WebSocket origins allowed: {}", list.join(", ")),
        None => info!("WebSocket origins allowed: any (set ALLOWED_ORIGINS to restrict)"),
    }

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (app, connections) = create_app_with(AppConfig {
        allowed_origins,
        shutdown: Some(shutdown_rx),
    });

    let listener = TcpListener::bind(address)
        .await
        .unwrap_or_else(|e| panic!("failed to bind TCP listener on {address}: {e}"));

    info!("TagGame server listening on {}", address);

    // SIGTERM (systemd stop / restart) or Ctrl-C: stop accepting, tell every
    // WebSocket to close (clients auto-reconnect), wait briefly, exit 0.
    let signal = async move {
        shutdown_signal().await;
        info!("shutdown signal received: closing connections");
        let _ = shutdown_tx.send(true);
    };
    axum::serve(listener, app)
        .with_graceful_shutdown(signal)
        .await
        .expect("TagGame server failed");

    // Upgraded WebSockets run on their own tasks: give them a moment to
    // send their Close frames before the process exits.
    let deadline = tokio::time::Instant::now() + DRAIN_TIMEOUT;
    while connections.open() > 0 && tokio::time::Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    info!("TagGame server stopped ({} connection(s) still open)", connections.open());
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut s) => {
                s.recv().await;
            }
            Err(_) => std::future::pending::<()>().await,
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
