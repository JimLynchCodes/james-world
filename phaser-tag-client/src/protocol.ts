import type { UUID } from "./types";

export type ClientMessage =
  | { type: "Join"; data: { room_id: string } }
  | {
      type: "MoveInput";
      data: {
        seq: number;
        dx: number;
        dy: number;
        running: boolean;
      };
    }
  | { type: "TagPlayer"; data: { target_id: UUID } }
  | { type: "Ping"; data: { timestamp: number } };

export type PlayerSnapshot = {
  id: UUID;
  /** Display name from the server, e.g. "James 3". */
  name: string;
  x: number;
  y: number;
  energy: number;
  is_running: boolean;
  is_it: boolean;
  /** True for server-controlled bot players. */
  is_bot: boolean;
  /** Direction of last movement in radians (atan2(dy, dx)). */
  facing: number;
};

export type ServerMessage =
  | { type: "Welcome"; data: { player_id: UUID; name: string } }
  | { type: "Snapshot"; data: { players: PlayerSnapshot[] } }
  | { type: "PlayerJoined"; data: { player_id: UUID; name: string } }
  | { type: "PlayerLeft"; data: { player_id: UUID } }
  | {
      type: "PlayerTagged";
      data: { tagger_id: UUID; target_id: UUID };
    }
  | { type: "Pong"; data: { timestamp: number } }
  | { type: "Error"; data: { message: string } };
