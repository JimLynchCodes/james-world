#!/usr/bin/env python3
"""Build the "Basketball James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_basketball.png + kid_basketball.json

Same columns, rows and animation ranges as kid.png. Frames are padded
(PAD_SIDE each side so the ball never clips the cell). Feet stay on the
same row as James (see src/skins.ts).

Per frame:
  1. T-shirt -> navy jersey with orange neck, armhole and hem trim;
     front views get an orange NEW YORK wordmark and number 11, back
     views a larger 11, profiles a 1 on the facing flank;
  2. shorts -> navy with an orange leg hem;
  3. the arm James tags with -> white compression sleeve (hand stays bare);
  4. white headband across the forehead (wraps the hair on back views);
  5. sneakers -> orange with a white sole, side stripe and toe;
  6. an orange basketball with the original round seam pattern, dribbled
     on every frame. It stays a circle (no squash). Seams are pre-rendered
     at a few rotations so the spin stays crisp. The ball is in front of
     him along the way he faces: toward the camera when he faces south,
     out ahead when he faces sideways, and farther from the camera (drawn
     behind the body) when he faces north. The dribbling arm reaches to
     the ball. The sleeve arm still tags.

Face and hair (under the headband) are untouched. The tagging hand stays
the original skin. The other arm is removed and one dribbling arm, the
same thickness as that arm, is drawn from the shoulder to the ball.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_basketball_skin.py [--preview /tmp/basketball_preview.png]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from make_banana_skin import (  # shared frame analysis helpers
    Geometry,
    alpha_mask,
    arms_and_hands,
    components8,
    grow,
    loose_skin,
    skin_mask,
)
from make_pirate_skin import down, grid, over, premul, to_u8
from make_tuxedo_skin import close_streaks, lum, row_span, torso_rows

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

# 10px each side -> 100px frames. 1.2 / 1 / 0.9 / 0.82 / 0.8 / 0.72 of 100
# are whole pixels, so the skins card stays crisp (same trick as pharaoh).
PAD_SIDE = 10
PAD_TOP = 0

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW", "N", "NE"}
# Screen side of the hand that reaches in the tag clip (read off kid.png).
# The ball stays in the other hand so the tag arm still reads.
TAG_SIDE = {"E": 1, "SE": 1, "S": 1, "SW": -1, "W": -1, "NW": -1, "N": 1, "NE": 1}

# Feet line of the unpadded kid. The ball rests on this row.
GROUND = 96.0
# About 75% of the front-view head width (~36px), so it reads as a ball
# a kid would actually dribble.
BALL_R = 13.2

C = lambda *v: np.array(v, dtype=np.float64)  # noqa: E731
NAVY = C(16, 48, 148)
NAVY_DARK = C(8, 22, 78)
ORANGE = C(242, 96, 18)
ORANGE_HOT = C(255, 138, 42)
WHITE = C(246, 246, 250)
WHITE_SHADE = C(206, 210, 222)
BAND_EDGE = C(36, 40, 58)
SHOE_ORANGE = C(232, 108, 28)
SOLE = C(244, 244, 246)
BALL = C(232, 108, 26)
BALL_DARK = C(186, 72, 16)
BALL_LIGHT = C(255, 176, 92)
SEAM = C(52, 28, 16)
BALL_EDGE = C(92, 40, 12)
INK = C(12, 16, 36)


def shade(col: np.ndarray, l: np.ndarray, lo: float = 0.62, hi: float = 1.16) -> np.ndarray:
    k = lo + (hi - lo) * np.clip((l - 28.0) / 150.0, 0.0, 1.0)
    return col[None, None, :] * k[..., None]


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def stamp_pattern(rgb: np.ndarray, ok: np.ndarray, pattern: tuple[str, ...], x0: int, y0: int,
                  fill, edge=None) -> None:
    """Paint a '#' pattern. Optional 1px edge is drawn first so a gap of 3
    stays a 1px split instead of the two glyphs melting together."""
    h, w = ok.shape
    pts = []
    for dy, row in enumerate(pattern):
        for dx, ch in enumerate(row):
            if ch == "#" and 0 <= y0 + dy < h and 0 <= x0 + dx < w:
                pts.append((x0 + dx, y0 + dy))
    if edge is not None:
        seen = set(pts)
        for x, y in pts:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if (xx, yy) in seen:
                        continue
                    if 0 <= xx < w and 0 <= yy < h and ok[yy, xx]:
                        rgb[yy, xx] = edge
    for x, y in pts:
        if ok[y, x]:
            rgb[y, x] = fill


def centered_pattern(pattern: tuple[str, ...], cx: float, y: int) -> tuple[int, int]:
    width = max(len(row) for row in pattern)
    return int(round(cx - (width - 1) / 2)), y


# Bounce amount: 0 = up in the hand, 1 = resting on its ground spot.
# Every loop (including idle, which the skins card plays) shows the full
# dribble: hand on the ball, push down, contact, rebound.
def bounce_t(anim: str, index: int) -> float:
    if anim == "tag":
        return (0.0, 0.48, 0.86, 1.0, 0.42, 0.12)[index]
    return (0.0, 0.58, 1.0, 0.30)[index % 4]


# The classic seam picture is unchanged by a half turn, so a 4-frame bounce
# can step 45° and a 6-frame tag 30° and the loop meets itself. Same
# direction every facing. Angles are pre-rendered, not warped per pixel.
def spin_deg(anim: str, index: int) -> float:
    if anim == "tag":
        return index * 30.0
    return (index % 4) * 45.0


def dribble_hand(f: np.ndarray, g: Geometry, direction: str) -> tuple[float, float]:
    """Hand on the non-tagging side, or a hip fallback."""
    h, w = f.shape[:2]
    yy = np.arange(h)[:, None]
    face = (yy <= g.neck + 1) & skin_mask(f)
    _arms, hands = arms_and_hands(f, g, face)
    side = -TAG_SIDE[direction]
    best: tuple[float, float] | None = None
    best_out = -1e9
    for comp in components8(hands):
        if comp.sum() < 6:
            continue
        ys, xs = np.nonzero(comp)
        cy, cx = float(ys.mean()), float(xs.mean())
        if cy > g.hem - 2:
            continue  # knee / shin false positives
        outward = (cx - g.head_cx) * side
        if outward < 3:
            continue
        if outward > best_out:
            best_out = outward
            best = (cx, cy)
    if best is None:
        return g.head_cx + side * 15.0, float(g.hem - 8)
    return best


def silhouette(alpha: np.ndarray) -> np.ndarray:
    """Opaque pixels that touch transparency. These stay a dark outline
    so a recolor can't leave a white or orange fringe."""
    a = alpha
    pad = np.pad(a, 1, constant_values=False)
    neighbor_clear = (
        ~pad[:-2, 1:-1] | ~pad[2:, 1:-1] | ~pad[1:-1, :-2] | ~pad[1:-1, 2:]
    )
    return a & neighbor_clear


def tagging_arm(arms: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """The arm James tags with, or the tag-side half when both arms touch."""
    h, w = arms.shape
    xx = np.arange(w)[None, :]
    tag = TAG_SIDE[direction]
    comps = [c for c in components8(arms) if c.sum() >= 12]
    if not comps:
        return np.zeros(arms.shape, dtype=bool)

    def score(c: np.ndarray) -> float:
        _ys, xs = np.nonzero(c)
        return (float(xs.mean()) - g.head_cx) * tag

    best = max(comps, key=score)
    if score(best) < 1:
        return np.zeros(arms.shape, dtype=bool)
    _ys, xs = np.nonzero(best)
    if xs.min() < g.head_cx - 3 and xs.max() > g.head_cx + 3:
        best = best & ((xx - g.head_cx) * tag > 1)
    within = arms & ((xx - g.head_cx) * tag > -1)
    return grow(best, within, 1)


def fist_mask(arm: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """The outer end of the tagging arm. Wide enough that the hand still
    reads at the end of the sleeve on the reach frame."""
    if not arm.any():
        return np.zeros(arm.shape, dtype=bool)
    h, w = arm.shape
    xx = np.arange(w)[None, :]
    tag = TAG_SIDE[direction]
    ys, xs = np.nonzero(arm)
    outward = (xs.astype(np.float64) - g.head_cx) * tag
    cut = float(outward.max()) - 7.0
    return arm & ((xx - g.head_cx) * tag >= cut) & (np.arange(h)[:, None] > g.neck)


# Facing on screen. +x is right, +y is down (toward the camera).
# The ball leads him along this vector.
_FACE = {
    "E": (1.0, 0.0), "SE": (1.0, 1.0), "S": (0.0, 1.0), "SW": (-1.0, 1.0),
    "W": (-1.0, 0.0), "NW": (-1.0, -1.0), "N": (0.0, -1.0), "NE": (1.0, -1.0),
}
# Ground-contact offset from (head, feet), in pixels, along the facing.
# Sideways is far enough that the ball clears the chest. North/back is
# up-screen (farther from the camera). South is just below the feet.
_REACH = {
    "E": (28.0, 0.0), "W": (-28.0, 0.0),
    "S": (0.0, 3.0), "N": (0.0, -20.0),
    "SE": (18.0, 3.0), "SW": (-18.0, 3.0),
    "NE": (18.0, -16.0), "NW": (-18.0, -16.0),
}
# Extra shift toward the dribbling hand so a back-view ball peeks out.
_NUDGE = {"E": 0.0, "W": 0.0, "S": 5.0, "N": 13.0, "SE": 2.0, "SW": 2.0, "NE": 3.0, "NW": 3.0}
# How far the ball rises off its ground spot, in screen pixels. No squash.
_LIFT = 10.0

_BALL_SPRITE: dict[int, np.ndarray] = {}


def _render_ball_sprite(spin: float) -> np.ndarray:
    """Crisp pre-rendered circle. Seams use the original pattern, rotated.
    Highlight and outline do not spin. Supersampled so a turned seam stays
    a clean line instead of a stair-step."""
    radius = BALL_R
    box = int(np.ceil(radius * 2 + 5))
    if box % 2 == 0:
        box += 1
    ss = 8
    n = box * ss
    ys = (np.arange(n) + 0.5) / ss
    xs = (np.arange(n) + 0.5) / ss
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    mid = box / 2.0
    nx = (X - mid) / radius
    ny = (Y - mid) / radius
    r = np.hypot(nx, ny)
    aa = np.clip((1.04 - r) * radius, 0.0, 1.0)
    inside = aa > 0.02
    light = 0.78 + 0.28 * np.clip(0.55 - 0.65 * nx - 0.35 * ny, -0.35, 0.7)
    base = BALL * light[..., None]
    base = np.where((ny > 0.15)[..., None], base * 0.92 + BALL_DARK * 0.08, base)
    spec = np.exp(-((nx + 0.38) ** 2 + (ny + 0.42) ** 2) / 0.08)
    base = base * (1 - 0.65 * spec[..., None]) + BALL_LIGHT * spec[..., None]
    col = np.where(inside[..., None], base, 0.0)
    alpha = np.where(inside, aa, 0.0)

    ang = np.deg2rad(spin)
    ca, sa = np.cos(ang), np.sin(ang)
    # clockwise on screen
    px = nx * ca + ny * sa
    py = -nx * sa + ny * ca
    seam = (np.abs(py) < 0.055) | (np.abs(px - 0.12 * np.sin(py * np.pi)) < 0.05)
    seam |= (np.abs(np.abs(px) - 0.55) < 0.045) & (np.abs(py) < 0.62)
    seam &= r < 0.94
    col = np.where(seam[..., None], SEAM, col)
    edge = inside & (r > 0.84)
    col = np.where(edge[..., None], BALL_EDGE, col)

    col = col.reshape(box, ss, box, ss, 3).mean(axis=(1, 3))
    alpha = alpha.reshape(box, ss, box, ss).mean(axis=(1, 3))
    rgb = np.clip(col, 0, 255).astype(np.uint8)
    a = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out = np.zeros((box, box, 4), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = a
    # kill the corner haze so a rotated seam can't leave a square fringe
    out[a < 8] = 0
    return out


def ball_sprite(spin: float) -> np.ndarray:
    key = int(round(spin)) % 180
    sprite = _BALL_SPRITE.get(key)
    if sprite is None:
        sprite = _render_ball_sprite(float(key))
        _BALL_SPRITE[key] = sprite
    return sprite


def _paste(layer: np.ndarray, sprite: np.ndarray, cx: float, cy: float) -> None:
    """Paste a straight-alpha uint8 sprite into a premultiplied float layer."""
    h, w = layer.shape[:2]
    sh, sw = sprite.shape[:2]
    x0 = int(round(cx)) - sw // 2
    y0 = int(round(cy)) - sh // 2
    x1, y1 = x0 + sw, y0 + sh
    sx0 = sy0 = 0
    sx1, sy1 = sw, sh
    if x0 < 0:
        sx0 = -x0
        x0 = 0
    if y0 < 0:
        sy0 = -y0
        y0 = 0
    if x1 > w:
        sx1 -= x1 - w
        x1 = w
    if y1 > h:
        sy1 -= y1 - h
        y1 = h
    if x0 >= x1 or y0 >= y1:
        return
    sp = sprite[sy0:sy1, sx0:sx1].astype(np.float64) / 255.0
    sp[..., :3] *= sp[..., 3:4]
    dst = layer[y0:y1, x0:x1]
    layer[y0:y1, x0:x1] = sp + dst * (1.0 - sp[..., 3:4])


def shadow_layer(size, gx: float, gy: float, strength: float) -> np.ndarray:
    """Flat contact shadow on the ball's own ground spot."""
    Y, X = grid(size)
    col = np.zeros((*Y.shape, 3), dtype=np.float64)
    alpha = np.zeros(Y.shape, dtype=np.float64)
    sx = (X - gx) / (BALL_R * 0.70)
    sy = (Y - gy) / 2.1
    sd = sx * sx + sy * sy
    sa = np.clip(1.15 - sd, 0.0, 1.0) * (0.20 + 0.45 * strength)
    alpha = sa * 0.85
    col = np.where(sa[..., None] > 0.04, INK, col)
    return down(col, alpha, size)


def paint_uniform(f: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Recolour clothes. Returns (rgba, jersey mask, hand mask)."""
    f = close_streaks(f, g.neck + 2)
    g = Geometry(f)
    a = alpha_mask(f)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    L = lum(f)
    out = f.copy()
    rgb = out[..., :3].astype(np.float64)

    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & (yy > g.neck), 1)
    sk = loose_skin(f)
    outline = a & (L < 42)

    waist = g.hem - 9
    clothes = a & (yy > g.neck) & ~sk & ~outline & ~hands
    jersey = clothes & (yy <= waist + 1)
    shorts = clothes & (yy > waist) & (yy < g.hem + 2)
    shins = a & sk & (yy >= g.hem) & ~arms & ~hands
    shoes = a & (yy >= g.hem + 2) & ~sk & ~shins & ~arms

    rim = silhouette(a)
    # interior cloth only. The 1px rim is painted last, one dark colour,
    # so anti-aliased shirt pixels can't turn into a speckled halo.
    rgb = np.where((jersey & ~rim)[..., None], shade(NAVY, L, 0.78, 1.12), rgb)
    rgb = np.where((shorts & ~rim)[..., None], shade(NAVY_DARK, L, 0.85, 1.15), rgb)

    arm = tagging_arm(arms | (outline & grow(arms, a, 1)), g, direction)
    fist = fist_mask(arm & ~rim, g, direction)
    # the original hand detector, so a hanging arm still ends in skin
    fist = fist | (hands & arm & ~rim)
    sleeve = arm & ~fist & ~rim & (yy > g.neck)
    if sleeve.any():
        rgb = np.where(sleeve[..., None], shade(WHITE, L, 0.92, 1.02), rgb)
        cuff = grow(fist, sleeve, 1) & sleeve
        rgb = np.where(cuff[..., None], WHITE_SHADE, rgb)
    # put the fist back in the kid's own skin, on top of the sleeve
    rgb = np.where(fist[..., None], f[..., :3].astype(np.float64), rgb)

    # orange trim sits one pixel in from the silhouette
    inner = ~rim
    jtop, jbot = torso_rows(jersey & inner)
    if jtop is not None:
        neck = jersey & inner & (yy <= jtop + 1) & (yy > g.neck + 1)
        hem = jersey & inner & (yy >= jbot - 1)
        rgb = np.where(neck[..., None], ORANGE, rgb)
        rgb = np.where(hem[..., None], ORANGE, rgb)
    # armhole: only the shoulder, not a trail of orange down the sleeve
    shoulder = jersey & inner & grow(sleeve, a, 1) & (yy <= g.neck + 8)
    rgb = np.where(shoulder[..., None], ORANGE, rgb)
    if shorts.any():
        ys = np.nonzero((shorts & inner).any(axis=1))[0]
        if len(ys):
            cuff_rows = np.zeros_like(shorts)
            cuff_rows[ys[-1]] = shorts[ys[-1]] & inner[ys[-1]]
            if len(ys) > 3:
                cuff_rows[ys[-2]] = shorts[ys[-2]] & inner[ys[-2]]
            rgb = np.where(cuff_rows[..., None], ORANGE, rgb)

    # sneakers: the tan ankle and the dark shoe both become jersey orange.
    # Shading from the original near-black pixels was reading as brown.
    footwear = a & (yy >= g.hem) & ~jersey & ~shorts & ~arms & ~hands & ~fist
    if footwear.any():
        rgb = np.where((footwear & ~rim)[..., None], ORANGE, rgb)
        for comp in components8(footwear):
            if comp.sum() < 4:
                continue
            ys, xs = np.nonzero(comp)
            y1 = int(ys.max())
            sole = comp & ~rim & (yy >= y1 - 2)
            rgb = np.where(sole[..., None], SOLE, rgb)
            stripe_y = int(ys.min() + max(1, (y1 - int(ys.min())) * 0.42))
            stripe = comp & ~rim & (yy == stripe_y)
            rgb = np.where(stripe[..., None], WHITE, rgb)
            face_side = PROFILE.get(direction, FRONT.get(direction, 0))
            if face_side == 0:
                left, right = int(xs.min()), int(xs.max())
                toe = comp & ~rim & ((xx <= left + 1) | (xx >= right - 1)) & (yy <= y1 - 3)
            else:
                end = int(xs.max() if face_side > 0 else xs.min())
                toe = comp & ~rim & (np.abs(xx - end) <= 1) & (yy <= y1 - 3)
            rgb = np.where(toe[..., None], WHITE, rgb)

    # headband: a taller wrap on the hairline, above the eyes. Filled
    # across each row so hair spikes don't poke holes through it.
    band0 = g.top + 11
    band1 = g.top + 17
    for y in range(band0, band1):
        if not (0 <= y < h):
            continue
        xs = np.nonzero(a[y] & (np.abs(np.arange(w) - g.head_cx) <= g.head_hw + 2))[0]
        if len(xs) < 5:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        if y == band0:
            col = BAND_EDGE
        elif y == band1 - 1:
            col = WHITE_SHADE
        else:
            col = WHITE
        for x in range(x0, x1 + 1):
            # the hair's own outline stays dark; painting it white is the halo
            if rim[y, x]:
                continue
            # stay inside the head: don't bridge a real gap beside an ear
            if x0 < x < x1 and not a[y, x]:
                # only fill 1-2px holes
                if not (a[y, x - 1] and a[y, min(w - 1, x + 1)]):
                    continue
            rgb[y, x] = col
            out[y, x, 3] = 255

    # chest lettering. At this scale "NEW YORK" is a readable NY wordmark
    # over a blocky 11; the back is just 11; profiles show a 1 on the
    # flank that faces the camera. Gaps are wide enough that the outline
    # doesn't glue the digits together.
    painted = np.abs(rgb - ORANGE).sum(-1) > 40
    chest = jersey & painted & (yy > (jtop + 1 if jtop is not None else g.neck))
    cx = g.head_cx + FRONT.get(direction, 0) * 2.0
    # N and Y, one column apart. Reads as the NEW YORK wordmark.
    ny = ("#.#.#.#", "###.#.#", "#.#..#.")
    num = ("##...##", "##...##", "##...##", "##...##", "##...##")
    big = ("##....##", "##....##", "##....##", "##....##", "##....##", "##....##", "##....##")
    one = ("##", "##", "##", "##", "##", "##")
    # No outline: a 1px gap is the whole letter at this scale, and the
    # outline was gluing NY and the two 1s into one orange blob.
    if direction in FRONT:
        name_y = (jtop + 3) if jtop is not None else g.neck + 4
        stamp_pattern(rgb, chest, ny, *centered_pattern(ny, cx, name_y), ORANGE_HOT)
        stamp_pattern(rgb, chest, num, *centered_pattern(num, cx, name_y + 4), ORANGE_HOT)
    elif direction in BACK:
        num_y = (jtop + 3) if jtop is not None else g.neck + 4
        shift = {"NW": -1.5, "N": 0.0, "NE": 1.5}[direction]
        stamp_pattern(rgb, chest, big, *centered_pattern(big, cx + shift, num_y), ORANGE_HOT)
    else:
        side = PROFILE[direction]
        num_y = (jtop + 4) if jtop is not None else g.neck + 5
        flank = int(round(g.head_cx + side * 5 - (1 if side > 0 else 0)))
        stamp_pattern(rgb, chest, one, flank, num_y, ORANGE_HOT)

    # one dark rim around the body, after every recolor, so jersey, shorts,
    # sleeve and shoe edges match the other skins' crisp outline
    body_rim = rim & (yy > g.neck + 1)
    rgb = np.where(body_rim[..., None], INK, rgb)
    soft = (out[..., 3] > 0) & (out[..., 3] < 240) & (yy > g.neck + 1)
    rgb = np.where(soft[..., None], INK, rgb)
    out[..., 3] = np.where(soft, np.uint8(255), out[..., 3])

    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out, chest, hands | fist


def place_ball(g: Geometry, direction: str, anim: str, index: int):
    """Ball in front of the direction he faces.

    Returns (bx, by, gx, gy, behind). (gx, gy) is the ground contact.
    `behind` is true when that spot is farther from the camera than his
    body, so the body is drawn over the ball.
    """
    side = float(-TAG_SIDE[direction])
    dx, dy = _REACH[direction]
    t = bounce_t(anim, index)
    gx = g.head_cx + dx + side * _NUDGE[direction]
    gy = GROUND + dy
    # full circle, lifted straight up off that ground spot
    bx = gx
    by = gy - BALL_R - _LIFT * (1.0 - t)
    margin = BALL_R + 0.6
    bx = float(np.clip(bx, margin, 100.0 - margin))
    by = float(np.clip(by, margin, 100.0 - margin))
    behind = direction in BACK
    return bx, by, float(gx), float(gy), behind


def drop_limp_arm(body: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """Clear the original arm on the dribble side, outline included.

    The sleeve stays: that is the tagging arm, on the other side. What
    remains on the dribble side is skin that used to be the hanging arm,
    plus the dark pixels wrapped around it.
    """
    h, w = body.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :].astype(np.float64)
    side = float(-TAG_SIDE[direction])
    if direction in PROFILE:
        # profile draws that arm along the back edge, just past centre
        face = float(PROFILE[direction])
        on_side = (xx - g.head_cx) * (-face) > -3.5
    else:
        on_side = (xx - g.head_cx) * side > 0.4
    below = yy > g.neck + 1
    above_leg = yy < g.hem
    sk = loose_skin(body) & on_side & below & above_leg
    # a raised arm during the run still counts, even up at the shoulder
    raised = loose_skin(body) & on_side & (yy > g.neck - 2) & (yy <= g.neck + 2)
    raised = raised & ((xx - g.head_cx) * side > 8)
    sk = sk | raised
    dark = alpha_mask(body) & (lum(body) < 90) & on_side & (yy > g.neck - 1) & above_leg
    limp = sk | grow(sk, dark, 2)
    out = body.copy()
    out[limp] = 0
    return out


def repair_torso(body: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """Close the bite the removed arm left in the shirt and re-ink that edge.

    Only short gaps on the dribble side are filled, so the chest lettering
    stays split and the other arm is left alone.
    """
    h, w = body.shape[:2]
    side = float(-TAG_SIDE[direction])
    out = body.copy()
    for y in range(int(g.neck) + 2, int(g.hem) + 1):
        xs = np.nonzero(out[y, :, 3] > 40)[0]
        if len(xs) < 2:
            continue
        for i in range(len(xs) - 1):
            gap = int(xs[i + 1] - xs[i] - 1)
            if gap <= 0 or gap > 4:
                continue
            mid = (int(xs[i]) + int(xs[i + 1])) / 2.0
            if (mid - g.head_cx) * side < 2:
                continue
            # the neighbour closer to the chest is the shirt colour to extend
            inner = int(xs[i] if (xs[i] - g.head_cx) * side < (xs[i + 1] - g.head_cx) * side else xs[i + 1])
            for x in range(int(xs[i]) + 1, int(xs[i + 1])):
                out[y, x] = out[y, inner]
    # crisp edge where the shirt now meets empty space
    a = out[..., 3] > 200
    rim = silhouette(a)
    yy, xx = np.mgrid[0:h, 0:w]
    band = (yy > g.neck + 1) & (yy < g.hem + 2) & ((xx - g.head_cx) * side > 0)
    out[rim & band, :3] = INK
    out[rim & band, 3] = 255
    return out


def shoulder_point(g: Geometry, direction: str) -> tuple[float, float]:
    """Where the dribbling arm leaves the shirt."""
    side = float(-TAG_SIDE[direction])
    if direction in PROFILE:
        # in profile the arm reaches forward, out of the front of the chest
        face = float(PROFILE[direction])
        return g.head_cx + face * 4.5, float(g.neck + 10)
    if direction in BACK:
        return g.head_cx + side * 9.0, float(g.neck + 8)
    return g.head_cx + side * 10.0, float(g.neck + 8)


def paint_armhole(body: np.ndarray, g: Geometry, sx: float, sy: float) -> None:
    """Orange ring on the jersey around the socket. The arm covers the middle."""
    h, w = body.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - sx, yy - sy)
    ring = (d >= 2.6) & (d <= 4.6) & (yy > g.neck) & (yy < g.neck + 15)
    rgb = body[..., :3].astype(np.int16)
    navy = (body[..., 3] > 200) & (rgb[..., 2] > rgb[..., 0] + 15) & (rgb[..., 2] > 60)
    rim = silhouette(body[..., 3] > 200)
    body[ring & navy & ~rim, :3] = ORANGE


def scrub_loose_ink(body: np.ndarray) -> np.ndarray:
    """The erased arm leaves a dashed outline, sometimes with a skin pixel
    still stuck to it. The kid is one component; those crumbs are not."""
    opaque = body[..., 3] > 0
    comps = components8(opaque)
    if len(comps) < 2:
        return body
    comps.sort(key=lambda c: -int(c.sum()))
    out = body.copy()
    for comp in comps[1:]:
        if int(comp.sum()) > 40:
            continue
        out[comp] = 0
    return out


def clear_waist_fringe(merged: np.ndarray) -> np.ndarray:
    """North-facing contact shadow sits on the shorts. The body covers the
    middle and leaves a faint ink halo; on the grass that halo reads as
    teal crumbs. The ball's edge is orange, so this leaves it alone."""
    a = merged[..., 3]
    rgb = merged[..., :3].astype(np.int16)
    yy = np.arange(merged.shape[0])[:, None]
    fringe = (
        (a > 0) & (a < 200)
        & (yy >= 68) & (yy <= 88)
        & (rgb[..., 0] < 48)
        & (rgb[..., 2] + 6 >= rgb[..., 0])
    )
    if not fringe.any():
        return merged
    out = merged.copy()
    out[fringe] = 0
    return out


def _stamp(rgba: np.ndarray, pts: np.ndarray, rx: float, ry: float, color: np.ndarray) -> None:
    """Hard-edged discs. rx == ry is a circle; a wider rx reads as a mitt."""
    h, w = rgba.shape[:2]
    ys = np.arange(h)[:, None]
    xs = np.arange(w)[None, :]
    mask = np.zeros((h, w), dtype=bool)
    for x, y in pts:
        mask |= ((xs - x) / rx) ** 2 + ((ys - y) / ry) ** 2 <= 1.0
    rgba[mask, :3] = np.clip(color, 0, 255)
    rgba[mask, 3] = 255


def _along(p0: tuple[float, float], p1: tuple[float, float], step: float = 0.4) -> np.ndarray:
    dist = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
    n = max(2, int(dist / step) + 1)
    ts = np.linspace(0.0, 1.0, n)
    return np.stack([p0[0] * (1 - ts) + p1[0] * ts, p0[1] * (1 - ts) + p1[1] * ts], axis=1)


def _skin_colors(rgba: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray]:
    """Highlight and shade taken from the other hand, so this arm matches it."""
    h, w = rgba.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    tag = float(TAG_SIDE[direction])
    r = rgba[..., 0].astype(np.int16)
    gg = rgba[..., 1].astype(np.int16)
    b = rgba[..., 2].astype(np.int16)
    skin = (
        (rgba[..., 3] > 200) & (r > 170) & (gg > 110) & (r - b > 40)
        & (yy > g.neck + 4) & (yy < g.hem) & ((xx - g.head_cx) * tag > 2)
    )
    samples = rgba[skin][:, :3].astype(np.float64)
    if len(samples) < 6:
        face = (
            (rgba[..., 3] > 200) & (r > 170) & (gg > 100)
            & (yy > g.top + 16) & (yy < g.neck - 2)
        )
        samples = rgba[face][:, :3].astype(np.float64)
    if len(samples) < 4:
        mid = np.array([240.0, 174.0, 122.0])
    else:
        mid = np.median(samples, axis=0)
    light = np.clip(mid + np.array([8.0, 10.0, 8.0]), 0, 255)
    shade = np.clip(mid * np.array([0.84, 0.78, 0.76]), 0, 255)
    return light, shade


def _paint_limb(rgba: np.ndarray, pts: np.ndarray, radius: float,
                light: np.ndarray, shade: np.ndarray) -> None:
    """One pixel of dark outline, skin filling the rest, lit from the upper left."""
    _stamp(rgba, pts, radius, radius, INK)
    skin_r = max(1.15, radius - 1.0)
    _stamp(rgba, pts, skin_r, skin_r, shade)
    lit = pts + np.array([-0.75, -0.7])
    _stamp(rgba, lit, max(0.8, skin_r - 0.85), max(0.8, skin_r - 0.85), light)


def draw_dribble_arm(rgba: np.ndarray, g: Geometry, direction: str,
                     bx: float, by: float, ry: float, t: float) -> tuple[float, float]:
    """One arm, shoulder to elbow to a round hand on the ball.

    The elbow bends out while the ball is up and straightens as the hand
    pushes down. Width matches the other arm: a 1px outline around skin.
    Returns the hand centre.
    """
    side = float(-TAG_SIDE[direction])
    sx, sy = shoulder_point(g, direction)
    # overlap the shirt by a pixel so the arm comes out of the armhole
    if direction in PROFILE:
        face = float(PROFILE[direction])
        sx0, sy0 = sx - face * 2.0, sy
    else:
        sx0, sy0 = sx - side * 1.6, sy

    # hand sits on top of the ball so the fist reads, not buried in it.
    # Back views put it on the side that peeks past the body.
    if direction in BACK:
        hx = bx + side * ry * 0.42
        hy = by - ry * 0.40
    else:
        hx = bx
        hy = by - ry * 0.92

    # Elbow out to the dribble side. A perpendicular bow was dropping the
    # joint down the shirt, which read as a second arm lying on the torso.
    u = t * t * (3.0 - 2.0 * t)
    bend = 13.0 * (1.0 - u) + 7.0 * u
    if direction in PROFILE:
        ex = sx0 + (hx - sx0) * 0.50
        ey = sy0 + (hy - sy0) * 0.55 + bend * 0.45
    else:
        # straight out to the side, then back in to the ball
        ex = sx0 + side * bend
        ey = sy0 + (hy - sy0) * 0.58
    if ey < g.neck + 6:
        ey = float(g.neck + 6)

    hand_r = 4.05
    fx, fy = hx - ex, hy - ey
    fl = float(np.hypot(fx, fy)) or 1.0
    wx = hx - fx / fl * (hand_r * 0.72)
    wy = hy - fy / fl * (hand_r * 0.72)

    light, shade = _skin_colors(rgba, g, direction)
    # same thickness as the other arm: ~7px across, 1px of that outline
    arm_r = 3.45
    upper = _along((sx0, sy0), (ex, ey))
    fore = _along((ex, ey), (wx, wy))
    _paint_limb(rgba, upper, arm_r, light, shade)
    _paint_limb(rgba, fore, arm_r, light, shade)
    _paint_limb(rgba, np.array([[ex, ey]]), arm_r + 0.15, light, shade)
    _paint_limb(rgba, np.array([[hx, hy]]), hand_r, light, shade)
    return float(hx), float(hy)


def _occlude_reach(merged: np.ndarray, under: np.ndarray, body: np.ndarray,
                   hx: float, hy: float) -> None:
    """Put the torso back over the reaching arm, but leave the hand."""
    h, w = merged.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    hand = ((xx - hx) / 5.2) ** 2 + ((yy - hy) / 4.8) ** 2 <= 1.0
    restore = (body[..., 3] > 180) & ~hand
    merged[restore] = under[restore]


def baller(frame: np.ndarray, direction: str, anim: str, index: int) -> np.ndarray:
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return src
    g = Geometry(src)
    body, _chest, _hands = paint_uniform(src, g, direction)
    g = Geometry(body)
    body = drop_limp_arm(body, g, direction)
    body = repair_torso(body, g, direction)
    body = scrub_loose_ink(body)
    paint_armhole(body, g, *shoulder_point(g, direction))
    t = bounce_t(anim, index)
    bx, by, gx, gy, behind = place_ball(g, direction, anim, index)
    shadow = shadow_layer(body.shape[:2], gx, gy, strength=0.35 + 0.65 * t)
    ball = np.zeros_like(shadow)
    _paste(ball, ball_sprite(spin_deg(anim, index)), bx, by)
    if behind:
        # farther from the camera: body covers the ball, arm reaches past it
        under = to_u8(over(over(shadow, ball), premul(body)))
        merged = under.copy()
        hx, hy = draw_dribble_arm(merged, g, direction, bx, by, BALL_R, t)
        _occlude_reach(merged, under, body, hx, hy)
        merged = clear_waist_fringe(merged)
    else:
        merged = to_u8(over(premul(body), over(shadow, ball)))
        draw_dribble_arm(merged, g, direction, bx, by, BALL_R, t)
    return merged


def anim_of(col: int, meta: dict) -> tuple[str, int]:
    for name, spec in meta["animations"].items():
        if spec["start"] <= col < spec["start"] + spec["count"]:
            return name, col - spec["start"]
    return "idle", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    ofh = fh + PAD_TOP
    ofw = fw + 2 * PAD_SIDE
    out = np.zeros((len(dirs) * ofh, cols * ofw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            anim, index = anim_of(c, meta)
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = baller(fr, direction, anim, index)
    Image.fromarray(out).save(ASSETS / "kid_basketball.png", optimize=True)
    bb = dict(meta)
    bb["image"] = "kid_basketball.png"
    bb["frameWidth"] = ofw
    bb["frameHeight"] = ofh
    bb["baselineY"] = meta["baselineY"] + PAD_TOP
    bb["anchorX"] = meta["anchorX"] + PAD_SIDE
    (ASSETS / "kid_basketball.json").write_text(json.dumps(bb, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_basketball.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")

    if args.preview:
        from PIL import ImageDraw
        scale, pad = 3, 46
        # one cell per animation frame that the game actually plays, plus idle
        groups = [("idle", 0, 4), ("breathe", 12, 4), ("walk", 4, 8), ("run", 22, 8), ("tag", 16, 6)]
        picks: list[tuple[str, int]] = []
        for name, start, count in groups:
            for i in range(count):
                picks.append((name, start + i))
        pv = Image.new("RGB", (pad + len(picks) * ofw * scale, pad + len(dirs) * ofh * scale), (46, 120, 72))
        d = ImageDraw.Draw(pv)
        sheet = Image.fromarray(out)
        for r in range(len(dirs)):
            for i, (_name, c) in enumerate(picks):
                cell = sheet.crop((c * ofw, r * ofh, (c + 1) * ofw, (r + 1) * ofh))
                bg = Image.new("RGBA", (ofw, ofh), (120, 186, 96, 255))
                bg.alpha_composite(cell)
                pv.paste(bg.resize((ofw * scale, ofh * scale), Image.NEAREST).convert("RGB"),
                         (pad + i * ofw * scale, pad + r * ofh * scale))
            d.text((4, pad + r * ofh * scale + 8), dirs[r], fill="white")
        label_x = pad
        for name, _start, count in groups:
            d.text((label_x + 4, 8), name, fill="white")
            label_x += count * ofw * scale
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        pv.save(args.preview)
        print(f"wrote {args.preview} ({pv.size[0]}x{pv.size[1]})")


if __name__ == "__main__":
    main()
