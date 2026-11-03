/**
 * Synthetic click→field timing model for the title Start path.
 *
 * Before (Join-on-Start, wait Welcome, fade title ~400ms):
 *   click → Join → RTT → Welcome → spawn → title fade
 * After (warm Join + preload skin, optimistic enter, instant dismiss):
 *   click → enter when connected+skinReady (Welcome optional)
 *
 *   npx tsx tools/measure_start_flow.ts
 */
import {
  canEnterField,
  shouldShowStarting,
  type StartGateState,
} from "../src/startGate.ts";

/** Assumed network RTT to the game server (ms) for the model. */
const RTT_MS = 80;
/** Previous title fade-out before the field felt interactive (ms). */
const TITLE_FADE_MS = 400;
/** Client work to spawn the local avatar (ms). */
const SPAWN_MS = 8;

function beforeMs(rtt = RTT_MS): number {
  // Always waited on Welcome + fade, even when the socket was already up.
  return rtt + SPAWN_MS + TITLE_FADE_MS;
}

function afterMs(state: StartGateState, rtt = RTT_MS): number {
  if (canEnterField(state)) {
    // Instant dismiss; Welcome may already be cached from warm Join.
    return SPAWN_MS;
  }
  if (!state.connected) {
    // Wait for connect ≈ half RTT for TCP+WS, then same as ready (optimistic).
    return rtt / 2 + SPAWN_MS;
  }
  // Connected but skin still loading — network sheet fetch dominates; model one RTT.
  return rtt + SPAWN_MS;
}

const ready: StartGateState = {
  connected: true,
  skinReady: true,
  startRequested: true,
  playing: false,
};
const waitingSkin: StartGateState = { ...ready, skinReady: false };
const waitingNet: StartGateState = { ...ready, connected: false };

console.log("Start flow timing model (ms)");
console.log("----------------------------");
console.log(`before (Join→Welcome→fade): ${beforeMs().toFixed(0)}`);
console.log(
  `after  (ready on click):       ${afterMs(ready).toFixed(0)}  starting?= ${shouldShowStarting(ready)}`,
);
console.log(
  `after  (skin still loading):   ${afterMs(waitingSkin).toFixed(0)}  starting?= ${shouldShowStarting(waitingSkin)}`,
);
console.log(
  `after  (socket not open yet):  ${afterMs(waitingNet).toFixed(0)}  starting?= ${shouldShowStarting(waitingNet)}`,
);
console.log(
  `speedup when ready: ~${(beforeMs() / afterMs(ready)).toFixed(1)}x (model RTT=${RTT_MS}ms)`,
);
console.log("Runtime: open with ?timing=1 (or vite DEV) and read [start-timing] click-to-field.");
