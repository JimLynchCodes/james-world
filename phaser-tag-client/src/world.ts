/**
 * World geometry shared with the server. These mirror the constants in
 * backend/src/game/world.rs; backend/tests/bounds.rs fails if they drift.
 *
 * The fence (the wall players can't cross) is inset from the world edges so
 * that a kid standing against it keeps its sprite and the whole label stack
 * (IT / YOU / name above the head) on screen: the camera stops at the world
 * edge. Players' collision circles stay inside
 * [WALL_LEFT, WORLD_WIDTH - WALL_RIGHT] x [WALL_TOP, WORLD_HEIGHT - WALL_BOTTOM].
 */
export const WORLD_WIDTH = 5000;
export const WORLD_HEIGHT = 5000;
/** Server collision radius; the kid sprite is sized around it. */
export const PLAYER_RADIUS = 18;

export const WALL_LEFT = 40;
export const WALL_RIGHT = 40;
export const WALL_TOP = 110;
export const WALL_BOTTOM = 40;

/** Range of player centre positions the server allows. */
export const PLAY_AREA = {
  minX: WALL_LEFT + PLAYER_RADIUS,
  maxX: WORLD_WIDTH - WALL_RIGHT - PLAYER_RADIUS,
  minY: WALL_TOP + PLAYER_RADIUS,
  maxY: WORLD_HEIGHT - WALL_BOTTOM - PLAYER_RADIUS,
} as const;
