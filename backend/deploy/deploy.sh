#!/usr/bin/env bash
# Build the game server, copy it to the droplet, restart it, check /health.
#
#   DEPLOY_HOST=deploy@api.jamesworld.example ./deploy/deploy.sh            # deploy
#   DEPLOY_HOST=deploy@api.jamesworld.example ./deploy/deploy.sh rollback   # previous binary
#
# Run from backend/. Settings (environment variables, no secrets here):
#   DEPLOY_HOST  ssh destination; that user needs sudo (required)
#   BUILD_ON     droplet (default): rsync the source and `cargo build --release`
#                  on the droplet (needs rustup there; no cross-compiling)
#                local: build here and scp the binary. On Linux x86_64 that's a
#                  plain release build; elsewhere (e.g. a Mac) it uses
#                  `cargo zigbuild` (cargo install cargo-zigbuild; brew install zig)
#   TARGET       local cross-build target (default x86_64-unknown-linux-musl,
#                  a static binary that runs on any x86_64 Linux)
#   HEALTH_URL   checked on the droplet after the restart
#                  (default http://127.0.0.1:8000/health)
#
# The restart is the only downtime: players see "Not Connected" for a second
# or two and their clients reconnect and rejoin on their own. The in-memory
# world (positions, who's IT, the James N counter) starts fresh.
set -euo pipefail

: "${DEPLOY_HOST:?set DEPLOY_HOST, e.g. DEPLOY_HOST=deploy@api.jamesworld.example}"
BUILD_ON="${BUILD_ON:-droplet}"
TARGET="${TARGET:-x86_64-unknown-linux-musl}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
APP_DIR=/opt/tag26
BIN=taggame-backend

cd "$(dirname "$0")/.."   # backend/

# Runs on the droplet: swap in $1 (a freshly built binary), keep the old one
# as .prev, restart, and wait for /health.
REMOTE_INSTALL='
set -euo pipefail
new="$1"; app='"$APP_DIR"'; bin='"$BIN"'; health='"$HEALTH_URL"'
sudo install -m 0755 -o root -g root "$new" "$app/$bin.new"
if [ -f "$app/$bin" ]; then sudo cp -p "$app/$bin" "$app/$bin.prev"; fi
sudo mv -f "$app/$bin.new" "$app/$bin"
echo "restarting tag26..."
sudo systemctl restart tag26
for _ in $(seq 1 40); do
  if curl -fsS "$health" >/dev/null 2>&1; then
    echo "healthy: $(curl -fsS "$health")"; exit 0
  fi
  sleep 0.25
done
echo "tag26 did not become healthy; recent logs:" >&2
sudo journalctl -u tag26 -n 30 --no-pager >&2
exit 1
'

if [ "${1:-}" = rollback ]; then
  # shellcheck disable=SC2029
  ssh "$DEPLOY_HOST" "set -e; test -f $APP_DIR/$BIN.prev; cp $APP_DIR/$BIN.prev /tmp/$BIN.rollback; bash -s /tmp/$BIN.rollback" <<<"$REMOTE_INSTALL"
  exit
fi

case "$BUILD_ON" in
  droplet)
    echo "syncing source to $DEPLOY_HOST:tag26-src ..."
    rsync -az --delete --exclude target/ --exclude .git/ ./ "$DEPLOY_HOST:tag26-src/"
    ssh "$DEPLOY_HOST" 'set -e; cd tag26-src; ~/.cargo/bin/cargo build --release --locked 2>&1 | tail -3'
    ssh "$DEPLOY_HOST" "bash -s tag26-src/target/release/$BIN" <<<"$REMOTE_INSTALL"
    ;;
  local)
    if [ "$(uname -s)-$(uname -m)" = Linux-x86_64 ]; then
      cargo build --release --locked
      artifact="target/release/$BIN"
    else
      cargo zigbuild --release --locked --target "$TARGET"
      artifact="target/$TARGET/release/$BIN"
    fi
    echo "copying $artifact to $DEPLOY_HOST ..."
    scp -q "$artifact" "$DEPLOY_HOST:/tmp/$BIN.upload"
    ssh "$DEPLOY_HOST" "bash -s /tmp/$BIN.upload" <<<"$REMOTE_INSTALL"
    ;;
  *)
    echo "BUILD_ON must be droplet or local" >&2; exit 2 ;;
esac
