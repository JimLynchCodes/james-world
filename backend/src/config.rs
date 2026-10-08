//! Runtime configuration from environment variables (all optional, so
//! `cargo run` just works locally).
//!
//! | Variable          | Default        | Meaning                                         |
//! |-------------------|----------------|-------------------------------------------------|
//! | `BIND_ADDR`       | `0.0.0.0:8000` | Listen address. `host:port`, or just a host/IP  |
//! |                   |                | (then `PORT` is used). Behind Caddy in          |
//! |                   |                | production use `127.0.0.1:8000`.                |
//! | `PORT`            | `8000`         | Port, when `BIND_ADDR` is unset or has no port. |
//! | `ALLOWED_ORIGINS` | (allow all)    | Comma-separated browser origins allowed to open |
//! |                   |                | the WebSocket, e.g.                             |
//! |                   |                | `https://jamesworld.example,https://www.jamesworld.example`. |
//! | `RUST_LOG`        | `info`         | Log filter (tracing-subscriber `EnvFilter`).    |

use std::net::{IpAddr, Ipv4Addr, SocketAddr};

pub const DEFAULT_PORT: u16 = 8000;

/// Resolve the listen address from `BIND_ADDR` / `PORT` values.
/// Invalid values fall back to the defaults (with the reason returned so
/// main can log it) rather than refusing to start.
pub fn bind_addr(bind: Option<&str>, port: Option<&str>) -> (SocketAddr, Option<String>) {
    let mut warning = None;
    let port = match port.map(str::trim).filter(|p| !p.is_empty()) {
        None => DEFAULT_PORT,
        Some(p) => p.parse::<u16>().unwrap_or_else(|_| {
            warning = Some(format!("invalid PORT {p:?}, using {DEFAULT_PORT}"));
            DEFAULT_PORT
        }),
    };
    let default = SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), port);
    let Some(bind) = bind.map(str::trim).filter(|b| !b.is_empty()) else {
        return (default, warning);
    };
    if let Ok(addr) = bind.parse::<SocketAddr>() {
        return (addr, warning);
    }
    // "[::1]" or "127.0.0.1" without a port.
    if let Ok(ip) = bind.trim_start_matches('[').trim_end_matches(']').parse::<IpAddr>() {
        return (SocketAddr::new(ip, port), warning);
    }
    (default, Some(format!("invalid BIND_ADDR {bind:?}, using {default}")))
}

/// Parse `ALLOWED_ORIGINS`. `None` (unset / empty) means allow every origin.
pub fn allowed_origins(value: Option<&str>) -> Option<Vec<String>> {
    let list: Vec<String> = value?
        .split(',')
        .map(|o| o.trim().trim_end_matches('/').to_ascii_lowercase())
        .filter(|o| !o.is_empty())
        .collect();
    (!list.is_empty()).then_some(list)
}

/// Is a WebSocket upgrade with this `Origin` header allowed?
/// No allowlist: everything. With one: listed origins, plus requests with
/// no `Origin` at all (non-browser clients such as tests and bots, which
/// could fake the header anyway; the check exists to stop other websites
/// embedding the game server in a visitor's browser).
pub fn origin_allowed(allowed: Option<&[String]>, origin: Option<&str>) -> bool {
    match (allowed, origin) {
        (None, _) | (Some(_), None) => true,
        (Some(list), Some(origin)) => {
            let origin = origin.trim().trim_end_matches('/').to_ascii_lowercase();
            list.iter().any(|o| *o == origin)
        }
    }
}
