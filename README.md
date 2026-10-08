# James World

A multiplayer game of tag in the browser: every player is a "James", the
server decides who's IT, and you run around a schoolyard trying not to get
tagged.

- [`backend/`](backend): the game server. Rust (Axum + Tokio), server-authoritative,
  WebSockets. It owns the whole world: movement, energy, tagging, bots.
- [`phaser-tag-client/`](phaser-tag-client): the browser client. Phaser 3 +
  TypeScript, built with Vite. It sends inputs and draws the server's snapshots.

## Run it locally

```bash
cd backend && cargo run                              # game server on :8000
cd phaser-tag-client && npm install && npm run dev   # client on :5173
```

Open http://localhost:5173. No config needed: the client connects to the
same host on port 8000. Phones on your Wi-Fi can play too (`npm run dev -- --host`,
then open `http://<your-laptop-ip>:5173`).

## How it's deployed

**Full guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)** covers DNS,
Netlify, the DigitalOcean/Vultr server, redeploys and troubleshooting, with
an architecture diagram.

```text
https://jamesworld.lol, https://www.jamesworld.lol  ->  Netlify (the game page)
wss://api.jamesworld.lol/ws                         ->  VPS: Caddy :443 -> Rust server on 127.0.0.1:8000
```

- **Frontend:** Netlify builds `phaser-tag-client` on every push to `main`.
  `VITE_WS_URL=wss://api.jamesworld.lol/ws` tells the page where the server
  is.
- **Backend:** one Rust binary on an Ubuntu VPS, run by systemd, with Caddy
  in front for HTTPS. The browser connects to it directly, because Netlify
  can't proxy WebSockets.
- **DNS:** `jamesworld.lol` and `www` point at Netlify; `api` (`A`/`AAAA`)
  points at the VPS.
- **Redeploys:** Netlify deploys are atomic, so nobody notices them. A
  backend deploy restarts the server: the in-memory world starts fresh, and
  players see "Not Connected" for about 1–2 seconds while their clients
  reconnect and rejoin automatically.
