/**
 * Shared brawler stage layout. Keep in sync with backend
 * WORLD_W / WORLD_H / LANE_* / GROUND_Y / FIGHT_WIDTH.
 */
export const BRAWLER_LAYOUT = {
  w: 7000,
  h: 540,
  laneTop: 72,
  laneBottom: 520,
  groundY: 300,
  /** Locked fight band width — nearly edge-to-edge on a typical camera view. */
  fightWidth: 1100,
} as const;
