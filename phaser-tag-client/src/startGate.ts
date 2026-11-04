/**
 * When the title Start button may drop the player onto the field immediately
 * vs. show "Starting…" and wait. Pure helpers so the gate can be unit-tested
 * without Phaser or a socket.
 */

export interface StartGateState {
  /** WebSocket is open (Hello may or may not have arrived). */
  connected: boolean;
  /** Default / chosen skin textures are drawable. */
  skinReady: boolean;
  /** User has pressed Start. */
  startRequested: boolean;
  /** Already dismissed the title and enabled play. */
  playing: boolean;
}

/** True when Start can switch to the field without waiting. */
export function canEnterField(state: StartGateState): boolean {
  return state.connected && state.skinReady && !state.playing;
}

/** Show the "Starting…" label only while Start is pending and we're not ready. */
export function shouldShowStarting(state: StartGateState): boolean {
  return state.startRequested && !state.playing && !canEnterField({
    ...state,
    startRequested: true,
  });
}

/**
 * Pick an optimistic spawn inside the play area when Welcome has not arrived.
 * Prefer a previously known server spot; otherwise the yard centre.
 */
export function optimisticSpawn(opts: {
  welcomeX?: number | null;
  welcomeY?: number | null;
  fallbackX: number;
  fallbackY: number;
}): { x: number; y: number } {
  const { welcomeX, welcomeY, fallbackX, fallbackY } = opts;
  if (
    typeof welcomeX === "number" &&
    Number.isFinite(welcomeX) &&
    typeof welcomeY === "number" &&
    Number.isFinite(welcomeY)
  ) {
    return { x: welcomeX, y: welcomeY };
  }
  return { x: fallbackX, y: fallbackY };
}
