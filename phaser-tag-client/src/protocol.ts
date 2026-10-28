import type { UUID } from "./types";
import type { Skin } from "./skins";
import type { Cosmetic } from "./cosmetics";
export type { Skin } from "./skins";
export type { Cosmetic } from "./cosmetics";

export type ClientMessage =
  /** `skin` / `cosmetic` are optional on the server (older clients); opaque keys relayed as-is. */
  | { type: "Join"; data: { room_id: string; skin?: Skin; cosmetic?: Cosmetic } }
  /** Change skin mid-game (Settings > Skins). */
  | { type: "SetSkin"; data: { skin: Skin } }
  /** Change opaque cosmetic mid-game (e.g. after awarding a crown). */
  | { type: "SetCosmetic"; data: { cosmetic: Cosmetic } }
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
  | { type: "Ping"; data: { timestamp: number } }
  /**
   * Secret cave. The player stays in the world (position, IT, energy) but
   * the server hides them from snapshots and will not tag them.
   */
  | { type: "SetAway"; data: { away: boolean } }
  /** Enter the co-op sword brawler room (player should already be away). */
  | { type: "JoinBrawler"; data?: Record<string, never> }
  /** Leave the brawler room (death, win, or quit). */
  | { type: "LeaveBrawler"; data?: Record<string, never> }
  /** Movement + attack for the brawler room. `attack` is the tag button. */
  | {
      type: "BrawlerInput";
      data: {
        seq: number;
        dx: number;
        dy: number;
        attack: boolean;
      };
    };

export type PlayerSnapshot = {
  id: UUID;
  /** Display name from the server, e.g. "James 3". */
  name: string;
  /** Outfit to draw this player in. */
  skin: Skin;
  /** Opaque cosmetic (e.g. "crown"). Older servers omit it. */
  cosmetic?: Cosmetic;
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

export type EnemyKind = "grunt" | "bruiser" | "swift" | "boss";

export type BrawlerPlayerSnap = {
  id: UUID;
  name: string;
  skin: Skin;
  cosmetic?: Cosmetic;
  x: number;
  y: number;
  hp: number;
  max_hp: number;
  facing: number;
  moving: boolean;
  attacking: boolean;
  dead: boolean;
};

export type EnemySnap = {
  id: number;
  kind: EnemyKind;
  x: number;
  y: number;
  hp: number;
  max_hp: number;
  facing: number;
  hit_flash: boolean;
};

export type BrawlerSnapshotData = {
  players: BrawlerPlayerSnap[];
  enemies: EnemySnap[];
  wave: number;
  boss_hp?: number | null;
  boss_max_hp?: number | null;
  won: boolean;
  show_go?: boolean;
  lock_left?: number | null;
  lock_right?: number | null;
};

export type ServerMessage =
  /** Spectator connected; Join to become a player. */
  | { type: "Hello"; data?: Record<string, never> }
  /** `x`/`y` are optional: servers from before random spawns omit them. */
  | { type: "Welcome"; data: { player_id: UUID; name: string; x?: number; y?: number } }
  | { type: "Snapshot"; data: { players: PlayerSnapshot[] } }
  /** `skin` is the player's skin at join time; live changes come in snapshots. `x`/`y` is where they are standing (omitted by older servers). */
  | {
      type: "PlayerJoined";
      data: {
        player_id: UUID;
        name: string;
        skin: Skin;
        cosmetic?: Cosmetic;
        x?: number;
        y?: number;
      };
    }
  | { type: "PlayerLeft"; data: { player_id: UUID } }
  | {
      type: "PlayerTagged";
      data: { tagger_id: UUID; target_id: UUID };
    }
  | { type: "Pong"; data: { timestamp: number } }
  | { type: "Error"; data: { message: string } }
  | {
      type: "BrawlerWelcome";
      data: { player_id: UUID; x: number; y: number; hp: number; max_hp: number };
    }
  | { type: "BrawlerSnapshot"; data: BrawlerSnapshotData }
  | { type: "BrawlerPlayerDied"; data: { player_id: UUID } }
  | { type: "BrawlerWon"; data: { player_ids: UUID[] } };
