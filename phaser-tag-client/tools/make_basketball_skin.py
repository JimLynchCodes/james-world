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
  3. both arms stay bare skin, the same tone as James;
  4. white headband across the forehead (wraps the hair on back views);
  5. sneakers -> orange with a white sole, side stripe and toe;
  6. an orange basketball with the original round seam pattern, dribbled
     on every frame. It stays a circle (no squash). Seams are pre-rendered
     at a few rotations so the spin stays crisp. The ball stays in front
     of him along the way he faces, close to the dribbling-side foot:
     lower on screen when he faces the camera, just ahead of the front
     foot in profile, and farther from the camera (drawn behind the body)
     when he faces away. One arm hangs from that shoulder and dribbles.
     The tagging arm stays bare skin and still tags.

Face, hair and neck (under the headband) are James's. Both arms are bare
skin. The dribbling arm is one tapered limb hanging at his side, with
the hand between the hip and the knee.

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
from make_pirate_skin import down, grid, over, premul, seg_dist, to_u8
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
_FACE = {
    "E": (1.0, 0.0), "SE": (1.0, 1.0), "S": (0.0, 1.0), "SW": (-1.0, 1.0),
    "W": (-1.0, 0.0), "NW": (-1.0, -1.0), "N": (0.0, -1.0), "NE": (1.0, -1.0),
}

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
    fist = fist | (hands & arm & ~rim)
    # the tagging arm stays the kid's own skin. No compression sleeve.

    # orange trim sits one pixel in from the silhouette
    inner = ~rim
    jtop, jbot = torso_rows(jersey & inner)
    if jtop is not None:
        neck = jersey & inner & (yy <= jtop + 1) & (yy > g.neck + 1)
        hem = jersey & inner & (yy >= jbot - 1)
        rgb = np.where(neck[..., None], ORANGE, rgb)
        rgb = np.where(hem[..., None], ORANGE, rgb)
    # orange armhole on the shirt only, where either arm leaves the jersey
    shoulder = jersey & inner & grow(arms, a, 1) & (yy > g.neck) & (yy <= g.neck + 8)
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


def _dribble_side(direction: str) -> float:
    return float(-TAG_SIDE[direction])


def _layout(g: Geometry, direction: str):
    """Rest pose and the ball's high/low centres.

    The arm hangs. Its hand sits on the crown of the ball at the top of
    the bounce, and the ball drops to the ground without the arm chasing.
    """
    side = _dribble_side(direction)
    cx, neck, hem = float(g.head_cx), float(g.neck), float(g.hem)
    floor_y = 98.0 - BALL_R
    if direction in PROFILE:
        face = float(PROFILE[direction])
        shoulder = (cx - face * 2.0, neck + 9.0)
        elbow = (cx + face * 0.5, hem - 16.0)
        hand = (cx + face * 6.5, hem - 11.0)
        ball = (cx + face * 11.0, hem - 4.0)
        low = min(hem + 6.0, floor_y)
    elif direction in BACK:
        # the limb stays behind the torso; the mitt is what peeks out
        shoulder = (cx + side * 2.5, neck + 9.0)
        elbow = (cx + side * 3.5, neck + 16.0)
        hand = (cx + side * 12.0, hem - 18.0)
        ball = (cx + side * 16.5 + _FACE[direction][0] * 2.0, hem - 12.0)
        low = hem - 6.0
    elif direction in ("SE", "SW"):
        shoulder = (cx + side * 8.5, neck + 7.0)
        elbow = (cx + side * 13.5, hem - 19.0)
        hand = (cx + side * 11.5, hem - 14.0)
        ball = (cx + side * 13.0, hem - 6.0)
        low = min(hem + 5.0, floor_y)
    else:
        shoulder = (cx + side * 8.0, neck + 7.0)
        elbow = (cx + side * 13.0, hem - 19.0)
        hand = (cx + side * 11.0, hem - 14.0)
        ball = (cx + side * 12.5, hem - 6.0)
        low = min(hem + 6.0, floor_y)
    high = ball[1]
    if low < high + 5.0:
        low = high + 5.0
    return shoulder, elbow, hand, (ball[0], high), (ball[0], low), side


def _flick_hand(elbow, hand, t: float):
    """Move the mitt a few pixels down without changing the forearm length."""
    flick = 3.0 * np.sin(np.pi * float(t))
    ex, ey = elbow
    hx, hy = hand
    length = float(np.hypot(hx - ex, hy - ey)) or 1.0
    vx, vy = hx - ex, (hy + flick) - ey
    norm = float(np.hypot(vx, vy)) or 1.0
    return ex + vx / norm * length, ey + vy / norm * length


def _tuck_back(body: np.ndarray, g: Geometry, direction: str,
               shoulder, elbow, hand, high, low):
    """Keep a back-view arm behind the shirt. Only the mitt clears the edge."""
    side = _dribble_side(direction)
    h = body.shape[0]
    hy = int(np.clip(round(hand[1]), 1, h - 2))
    edges = []
    for y in range(hy - 2, hy + 3):
        xs = np.nonzero(body[y, :, 3] > 180)[0]
        if side < 0:
            xs = xs[xs < g.head_cx + 4]
            if len(xs):
                edges.append(float(xs[0]))
        else:
            xs = xs[xs > g.head_cx - 4]
            if len(xs):
                edges.append(float(xs[-1]))
    if not edges:
        return shoulder, elbow, hand, high, low
    edge = float(np.median(edges))
    hx = edge + side * 3.6
    ex = edge - side * 2.2
    ey = min(float(elbow[1]), hand[1] - 2.0)
    bx = hx + side * 6.5
    return shoulder, (ex, ey), (hx, hand[1]), (bx, high[1]), (bx, low[1])


def _is_cloth(rgb: np.ndarray) -> np.ndarray:
    """Jersey, shorts and orange trim. These are the body, not the arm."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    navy = (b > r + 12) & (b > 45)
    orange = (r > 170) & (g < 170) & (b < 90) & (r > g + 40)
    return navy | orange


def dribble_arm_mask(src: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """The original swinging arm on the dribble side, outline included.

    Taken from the base James frame so the shorts and legs stay his shape.
    The other arm is the one that tags, and it stays.
    """
    h, w = src.shape[:2]
    yy = np.arange(h)[:, None]
    face = (yy <= g.neck + 1) & skin_mask(src)
    arms, _hands = arms_and_hands(src, g, face)
    side = float(-TAG_SIDE[direction])
    on = np.zeros_like(arms)
    for comp in components8(arms):
        _ys, xs = np.nonzero(comp)
        if len(xs) == 0:
            continue
        if float(((xs - g.head_cx) * side > 0).mean()) > 0.55:
            on |= comp
    # below the chin; the mask already starts under the neck
    on &= yy > g.neck + 2
    # the black outline of that arm, a couple of pixels out. The silhouette
    # outline is connected, so this stops after two steps and does not walk
    # around the whole body.
    L = lum(src)
    dark = (src[..., 3] > 40) & (L < 55)
    for _ in range(2):
        pad = np.pad(on, 1, constant_values=False)
        nb = (
            pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
            | pad[:-2, :-2] | pad[:-2, 2:] | pad[2:, :-2] | pad[2:, 2:]
        )
        on = on | (nb & dark & (yy > g.neck + 2))
    return on


def drop_limp_arm(body: np.ndarray, g: Geometry, direction: str,
                  arm_mask: np.ndarray | None = None) -> np.ndarray:
    """Clear the original dribble-side arm, skin and outline together.

    A skin-only erase left the black outline behind, and filling that
    gap painted it back as a navy shard on the hip.
    """
    if arm_mask is None:
        arm_mask = dribble_arm_mask(body, g, direction)
    out = body.copy()
    out[arm_mask] = 0
    return out


def restore_body(erased: np.ndarray, painted: np.ndarray, g: Geometry) -> np.ndarray:
    """Put the head, neck and any eaten jersey back from the painted kid.

    The arm we meant to remove was skin. Cloth and everything above the
    chin were never supposed to become transparent.
    """
    out = erased.copy()
    yy = np.arange(erased.shape[0])[:, None]
    deleted = (painted[..., 3] > 40) & (erased[..., 3] < 20)
    cloth = _is_cloth(painted[..., :3])
    head = yy <= g.neck + 5
    out[deleted & (cloth | head)] = painted[deleted & (cloth | head)]
    # the whole head and neck, even where the erase thought it found an arm
    keep = head & (painted[..., 3] > 20)
    out[keep] = painted[keep]
    return out


def _outside_clear(alpha: np.ndarray, thresh: int = 24) -> np.ndarray:
    """Transparent pixels a flood fill can reach from the frame border."""
    h, w = alpha.shape
    solid = alpha > thresh
    outside = np.zeros((h, w), dtype=bool)
    q: list[tuple[int, int]] = []
    for y in range(h):
        for x in (0, w - 1):
            if not solid[y, x]:
                outside[y, x] = True
                q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if not solid[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.pop()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and not solid[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                q.append((ny, nx))
    return outside


def fill_enclosed_holes(body: np.ndarray) -> np.ndarray:
    """Transparent pixels shut inside the silhouette get the nearest body colour."""
    h, w = body.shape[:2]
    outside = _outside_clear(body[..., 3])
    holes = (body[..., 3] <= 24) & ~outside
    if not holes.any():
        return body
    out = body.copy()
    src_y = np.full((h, w), -1, dtype=np.int16)
    src_x = np.full((h, w), -1, dtype=np.int16)
    q: list[tuple[int, int]] = []
    for y, x in zip(*np.nonzero(holes)):
        y = int(y)
        x = int(x)
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and out[ny, nx, 3] > 24:
                src_y[y, x] = ny
                src_x[y, x] = nx
                q.append((y, x))
                break
    seen = np.zeros((h, w), dtype=bool)
    head = 0
    while head < len(q):
        y, x = q[head]
        head += 1
        if seen[y, x]:
            continue
        sy, sx = int(src_y[y, x]), int(src_x[y, x])
        if sy < 0:
            continue
        seen[y, x] = True
        out[y, x, :3] = out[sy, sx, :3]
        out[y, x, 3] = 255
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and holes[ny, nx] and not seen[ny, nx] and src_y[ny, nx] < 0:
                src_y[ny, nx] = sy
                src_x[ny, nx] = sx
                q.append((ny, nx))
    return out


def snap_interior(body: np.ndarray) -> np.ndarray:
    """Partial alpha inside the body reads as the grass or the ball showing through."""
    a = body[..., 3]
    outside = _outside_clear(a, thresh=10)
    # a fringe pixel touches the outside; an interior one does not
    pad = np.pad(outside, 1, constant_values=True)
    touches = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    ghost = (a > 0) & (a < 250) & ~outside & ~touches
    if not ghost.any():
        return body
    out = body.copy()
    out[ghost, 3] = 255
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
    outside = _outside_clear(a, thresh=10)
    pad = np.pad(outside, 1, constant_values=False)
    touches = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    fringe = (
        (a > 0) & (a < 200)
        & touches
        & (yy >= 68) & (yy <= 88)
        & (rgb[..., 0] < 48)
        & (rgb[..., 2] + 6 >= rgb[..., 0])
    )
    if not fringe.any():
        return merged
    out = merged.copy()
    out[fringe] = 0
    return out


def _skin_colors(rgba: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
    light = np.clip(mid + np.array([10.0, 12.0, 6.0]), 0, 255)
    shade = np.clip(mid * np.array([0.82, 0.74, 0.70]), 0, 255)
    return light, mid, shade


def _limb_radius(s: np.ndarray) -> np.ndarray:
    """Outer radius along the arm. Upper arm a little wider than the forearm,
    then a small rounded mitt. The change is smooth, so no joint bulges."""
    s = np.asarray(s, dtype=np.float64)
    taper = np.clip(s / 0.72, 0.0, 1.0)
    taper = taper * taper * (3.0 - 2.0 * taper)
    # outer radius: upper arm a little wider than the forearm, matching
    # the other arm's ~5px of skin inside a 1px outline
    radius = 3.75 + (3.15 - 3.75) * taper
    fist = np.clip((s - 0.74) / 0.26, 0.0, 1.0)
    fist = fist * fist * (3.0 - 2.0 * fist)
    return radius + (3.55 - 3.15) * fist


def _arm_samples(shoulder, elbow, hand, n: int = 26):
    """Quadratic that passes through the elbow, plus arc-length fraction."""
    p0 = np.array(shoulder, dtype=np.float64)
    mid = np.array(elbow, dtype=np.float64)
    p2 = np.array(hand, dtype=np.float64)
    # control point so t=0.5 lands on the elbow; the bend stays rounded
    ctrl = 2.0 * mid - 0.5 * (p0 + p2)
    t = np.linspace(0.0, 1.0, n)
    u = 1.0 - t
    pts = (u * u)[:, None] * p0 + (2 * u * t)[:, None] * ctrl + (t * t)[:, None] * p2
    step = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    dist = np.concatenate([[0.0], np.cumsum(step)])
    total = float(dist[-1]) or 1.0
    return pts, dist / total, total


def draw_dribble_arm(rgba: np.ndarray, g: Geometry, direction: str,
                     shoulder, elbow, hand) -> None:
    """One continuous tapered arm: filled, antialiased, then outlined.

    Bare skin, same as the other arm. The mitt is the rounded end of the
    same shape, not a separate circle.
    """
    h, w = rgba.shape[:2]
    pts, frac, total = _arm_samples(shoulder, elbow, hand)
    # overlap the shirt so the sleeve grows out of the armhole
    sx, sy = shoulder
    Y, X = np.mgrid[0:h, 0:w]
    best_d = np.full((h, w), 1e9)
    best_s = np.zeros((h, w))
    best_qx = np.zeros((h, w))
    best_qy = np.zeros((h, w))
    for i in range(len(pts) - 1):
        d, tt = seg_dist(X, Y, pts[i, 0], pts[i, 1], pts[i + 1, 0], pts[i + 1, 1])
        closer = d < best_d
        best_d = np.where(closer, d, best_d)
        best_s = np.where(closer, frac[i] * (1.0 - tt) + frac[i + 1] * tt, best_s)
        best_qx = np.where(closer, pts[i, 0] * (1.0 - tt) + pts[i + 1, 0] * tt, best_qx)
        best_qy = np.where(closer, pts[i, 1] * (1.0 - tt) + pts[i + 1, 1] * tt, best_qy)

    radius = _limb_radius(best_s)
    nx = (X - best_qx) / (best_d + 1e-6)
    ny = (Y - best_qy) / (best_d + 1e-6)
    # lit from the upper left, in two flat tones like the other arm
    lit = nx * -0.60 + ny * -0.80
    light, mid, shade = _skin_colors(rgba, g, direction)
    fill = np.where((lit > 0.12)[..., None], light, np.where((lit > -0.28)[..., None], mid, shade))

    skin_zone = best_d <= (radius - 1.0)
    ink_zone = (best_d > (radius - 1.0)) & (best_d <= radius)
    aa = (best_d > radius) & (best_d <= radius + 0.8)
    # keep the arm below the chin
    below = Y > (g.neck + 1)
    layer = np.zeros((h, w, 4), dtype=np.float64)
    layer[skin_zone & below, :3] = fill[skin_zone & below] / 255.0
    layer[skin_zone & below, 3] = 1.0
    layer[ink_zone & below, :3] = INK / 255.0
    layer[ink_zone & below, 3] = 1.0
    cover = ((radius + 0.8 - best_d) / 0.8)[aa & below]
    layer[aa & below, :3] = (INK / 255.0) * cover[..., None]
    layer[aa & below, 3] = cover

    # tuck the round start of the sleeve back under the jersey
    base = premul(rgba)
    tucked = to_u8(over(base, layer))
    near = (np.hypot(X - sx, Y - sy) <= 5.2) & (Y <= sy + 1.5) & (rgba[..., 3] > 200)
    tucked[near] = rgba[near]
    rgba[...] = tucked


def _occlude_reach(merged: np.ndarray, body: np.ndarray,
                   hx: float, hy: float) -> None:
    """Opaque body over the ball and the arm. Only the mitt stays out."""
    yy, xx = np.mgrid[0:merged.shape[0], 0:merged.shape[1]]
    hand = ((xx - hx) / 4.2) ** 2 + ((yy - hy) / 4.4) ** 2 <= 1.0
    cover = (body[..., 3] > 40) & ~hand
    merged[cover] = body[cover]
    merged[cover, 3] = 255


def _is_ink_px(px) -> bool:
    return int(px[3]) > 200 and int(px[0]) < 32 and int(px[1]) < 40 and int(px[2]) < 58


def _inward_color(row: np.ndarray, x_edge: int, cx: float):
    """Body colour just inside the outline, walking toward the chest."""
    step = 1 if x_edge < cx else -1
    for k in range(0, 12):
        xx = int(x_edge) + step * k
        if xx < 0 or xx >= row.shape[0]:
            break
        if _is_ink_px(row[xx]):
            continue
        if int(row[xx, 3]) > 200:
            return row[xx].copy()
    return None


def close_arm_gap(merged: np.ndarray, painted: np.ndarray, g: Geometry,
                  arm_mask: np.ndarray | None = None) -> np.ndarray:
    """Grass between the new arm and the hip is the old arm, erased.

    That pocket is open at the top, so it is not an enclosed hole, but it
    still reads as a hole in the body. Fill it with the shirt or leg
    beside it and drop the outline that the fill just buried.
    """
    h, w = merged.shape[:2]
    yy = np.arange(h)[:, None]
    missing = (painted[..., 3] > 40) & (merged[..., 3] < 20)
    missing &= (yy > g.neck + 4) & (yy < g.hem + 14)
    # the swinging arm stays gone; filling it is the navy shard behind the hip
    if arm_mask is not None:
        missing &= ~arm_mask
    if not missing.any():
        return merged
    out = merged.copy()
    filled = np.zeros((h, w), dtype=bool)
    cx = float(g.head_cx)
    for y in range(h):
        if not missing[y].any():
            continue
        xs = np.nonzero(out[y, :, 3] > 40)[0]
        if len(xs) < 2:
            continue
        for i in range(len(xs) - 1):
            x0 = int(xs[i])
            x1 = int(xs[i + 1])
            gap = x1 - x0 - 1
            if gap <= 0 or gap > 14:
                continue
            sl = missing[y, x0 + 1:x1]
            if not sl.any() or int(sl.sum()) * 2 < gap:
                continue
            inner = x0 if abs(x0 - cx) <= abs(x1 - cx) else x1
            color = _inward_color(out[y], inner, cx)
            if color is None:
                # a row that is only outline (the hem, a shoe) still closes
                color = out[y, inner].copy()
                color[3] = 255
            for x in range(x0 + 1, x1):
                if missing[y, x]:
                    out[y, x] = color
                    out[y, x, 3] = 255
                    filled[y, x] = True
    if not filled.any():
        return out
    # only the outline pixels that touched the pocket, not every dark shoe
    a = out[..., 3] > 200
    rim = silhouette(a)
    rgb = out[..., :3]
    ink = (rgb[..., 0] < 32) & (rgb[..., 1] < 40) & (rgb[..., 2] < 58) & a & ~rim
    pad = np.pad(filled, 1, constant_values=False)
    beside = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    for y, x in zip(*np.nonzero(ink & beside)):
        color = _inward_color(out[y], int(x), cx)
        if color is not None:
            out[y, x, :3] = color[:3]
            out[y, x, 3] = 255
    return out


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    m = mask
    for _ in range(radius):
        p = np.pad(m, 1, constant_values=False)
        m = (
            p[1:-1, 1:-1]
            | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
            | p[:-2, :-2] | p[:-2, 2:] | p[2:, :-2] | p[2:, 2:]
        )
    return m


def _zone_arm(h: int, w: int, shoulder, elbow, hand, pad: float = 1.8) -> np.ndarray:
    """Pixels the new dribble arm covers, including its antialiased edge."""
    pts, frac, _total = _arm_samples(shoulder, elbow, hand)
    Y, X = np.mgrid[0:h, 0:w]
    best_d = np.full((h, w), 1e9)
    best_s = np.zeros((h, w))
    for i in range(len(pts) - 1):
        d, tt = seg_dist(X, Y, pts[i, 0], pts[i, 1], pts[i + 1, 0], pts[i + 1, 1])
        closer = d < best_d
        best_d = np.where(closer, d, best_d)
        best_s = np.where(closer, frac[i] * (1.0 - tt) + frac[i + 1] * tt, best_s)
    return best_d <= (_limb_radius(best_s) + pad)


def _zone_ball(h: int, w: int, bx: float, by: float) -> np.ndarray:
    Y, X = np.mgrid[0:h, 0:w]
    return (X - bx) ** 2 + (Y - by) ** 2 <= (BALL_R + 1.8) ** 2


def _zone_shadow(h: int, w: int, gx: float, gy: float) -> np.ndarray:
    Y, X = np.mgrid[0:h, 0:w]
    sx = (X - gx) / (BALL_R * 0.70)
    sy = (Y - gy) / 2.1
    return (sx * sx + sy * sy) < 1.3


def stray_fragments(merged: np.ndarray, src: np.ndarray, arm_mask: np.ndarray,
                    shoulder, elbow, hand, bx: float, by: float,
                    gx: float, gy: float) -> np.ndarray:
    """Opaque pixels that are not the base body, the ball, or the new arm.

    The base body is James with the dribble-side arm removed. A shard of
    the old arm, or a patch filled outside that silhouette, shows up here.
    """
    opaque = src[..., 3] > 40
    remain = opaque & ~arm_mask
    keep = np.zeros_like(remain)
    # the torso, the other arm and the legs are large. Outline crumbs of
    # the erased arm are a few pixels and are not part of his silhouette.
    for comp in components8(remain):
        if int(comp.sum()) >= 30:
            keep |= comp
    # inside that silhouette, including a one-pixel outline. A fin that
    # sticks out past it is not inside, so it still counts as a fragment.
    shell = np.where(_dilate(keep, 1), np.uint8(255), np.uint8(0))
    allowed = ~_outside_clear(shell, thresh=24)
    h, w = merged.shape[:2]
    allowed |= _zone_arm(h, w, shoulder, elbow, hand)
    allowed |= _zone_ball(h, w, bx, by)
    allowed |= _zone_shadow(h, w, gx, gy)
    raw = (merged[..., 3] > 80) & ~allowed
    if not raw.any():
        return raw
    # a repaired slit sits inside the shirt. A shard is a patch that touches
    # the outside, so only those components count.
    a = merged[..., 3] > 40
    pad = np.pad(~a, 1, constant_values=True)
    touches = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    exposed = np.zeros_like(raw)
    for comp in components8(raw):
        if (comp & touches).any():
            exposed |= comp
    return exposed


def clear_stray_fragments(merged: np.ndarray, stray: np.ndarray) -> np.ndarray:
    if not stray.any():
        return merged
    out = merged.copy()
    out[stray] = 0
    return out


def baller(frame: np.ndarray, direction: str, anim: str, index: int) -> np.ndarray:
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return src
    g0 = Geometry(src)
    painted, _chest, _hands = paint_uniform(src, g0, direction)
    g = Geometry(painted)
    arm_mask = dribble_arm_mask(src, g0, direction)
    body = drop_limp_arm(painted, g, direction, arm_mask)
    body = restore_body(body, painted, g)
    body = repair_torso(body, g, direction)
    body = scrub_loose_ink(body)
    body = restore_body(body, painted, g)
    # the shirt edge, then close whatever that edge just trapped
    a = body[..., 3] > 200
    rim = silhouette(a)
    yy, xx = np.mgrid[0:body.shape[0], 0:body.shape[1]]
    side = float(-TAG_SIDE[direction])
    edge = rim & (yy > g.neck + 5) & (yy < g.hem + 2) & ((xx - g.head_cx) * side > -2)
    body[edge, :3] = INK
    body[edge, 3] = 255
    # snap first: raising a soft pixel to opaque can close a gap and
    # trap the transparent pixels behind it, so the fill runs after
    body = snap_interior(body)
    body = fill_enclosed_holes(body)
    t = bounce_t(anim, index)
    # pose is measured on the original kid so the hem stays at the shorts
    shoulder, elbow, rest_hand, high, low, _side = _layout(g0, direction)
    if direction in BACK:
        shoulder, elbow, rest_hand, high, low = _tuck_back(
            body, g0, direction, shoulder, elbow, rest_hand, high, low)
    hand = _flick_hand(elbow, rest_hand, t)
    bx = high[0] * (1.0 - t) + low[0] * t
    by = high[1] * (1.0 - t) + low[1] * t
    margin = BALL_R + 0.6
    bx = float(np.clip(bx, margin, 100.0 - margin))
    by = float(np.clip(by, margin, 100.0 - margin))
    gx, gy, behind = bx, float(min(by + BALL_R, 99.0)), direction in BACK
    shadow = shadow_layer(body.shape[:2], gx, gy, strength=0.35 + 0.65 * t)
    ball = np.zeros_like(shadow)
    _paste(ball, ball_sprite(spin_deg(anim, index)), bx, by)
    if behind:
        # farther from the camera: opaque body covers the ball, the mitt peeks
        solid = body.copy()
        solid[solid[..., 3] > 40, 3] = 255
        under = to_u8(over(over(shadow, ball), premul(solid)))
        merged = under.copy()
        draw_dribble_arm(merged, g0, direction, shoulder, elbow, hand)
        merged = clear_waist_fringe(merged)
        _occlude_reach(merged, solid, hand[0], hand[1])
    else:
        merged = to_u8(over(premul(body), over(shadow, ball)))
        draw_dribble_arm(merged, g0, direction, shoulder, elbow, hand)
    merged = close_arm_gap(merged, painted, g, arm_mask)
    merged = snap_interior(merged)
    merged = fill_enclosed_holes(merged)
    stray = stray_fragments(
        merged, src, arm_mask, shoulder, elbow, hand, bx, by, gx, gy)
    merged = clear_stray_fragments(merged, stray)
    # clearing a shard can open a slit in the shirt; close that, not the fin
    merged = fill_enclosed_holes(merged)
    merged = snap_interior(merged)
    return merged


def anim_of(col: int, meta: dict) -> tuple[str, int]:
    for name, spec in meta["animations"].items():
        if spec["start"] <= col < spec["start"] + spec["count"]:
            return name, col - spec["start"]
    return "idle", 0


def count_strays(frame: np.ndarray, merged: np.ndarray, direction: str,
                 anim: str, index: int) -> int:
    """Re-check a finished frame. The pose matches baller, including the tuck."""
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return 0
    g0 = Geometry(src)
    arm_mask = dribble_arm_mask(src, g0, direction)
    painted, _chest, _hands = paint_uniform(src, g0, direction)
    g = Geometry(painted)
    body = drop_limp_arm(painted, g, direction, arm_mask)
    body = restore_body(body, painted, g)
    body = repair_torso(body, g, direction)
    body = scrub_loose_ink(body)
    body = restore_body(body, painted, g)
    a = body[..., 3] > 200
    rim = silhouette(a)
    yy, xx = np.mgrid[0:body.shape[0], 0:body.shape[1]]
    side = float(-TAG_SIDE[direction])
    edge = rim & (yy > g.neck + 5) & (yy < g.hem + 2) & ((xx - g.head_cx) * side > -2)
    body[edge, :3] = INK
    body[edge, 3] = 255
    body = snap_interior(body)
    body = fill_enclosed_holes(body)
    shoulder, elbow, rest_hand, high, low, _side = _layout(g0, direction)
    if direction in BACK:
        shoulder, elbow, rest_hand, high, low = _tuck_back(
            body, g0, direction, shoulder, elbow, rest_hand, high, low)
    t = bounce_t(anim, index)
    hand = _flick_hand(elbow, rest_hand, t)
    bx = high[0] * (1.0 - t) + low[0] * t
    by = high[1] * (1.0 - t) + low[1] * t
    margin = BALL_R + 0.6
    bx = float(np.clip(bx, margin, 100.0 - margin))
    by = float(np.clip(by, margin, 100.0 - margin))
    gx, gy = bx, float(min(by + BALL_R, 99.0))
    return int(stray_fragments(
        merged, src, arm_mask, shoulder, elbow, hand, bx, by, gx, gy).sum())


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
    stray_hits: list[str] = []
    for r, direction in enumerate(dirs):
        for c in range(cols):
            anim, index = anim_of(c, meta)
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            cell = baller(fr, direction, anim, index)
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = cell
            n = count_strays(fr, cell, direction, anim, index)
            if n:
                stray_hits.append(f"{direction} {anim} {index} (col {c}): {n} stray px")
    if stray_hits:
        print("stray fragments outside the James silhouette:")
        for line in stray_hits:
            print(" ", line)
        raise SystemExit(1)
    print(f"silhouette check ok ({len(dirs) * cols} frames)")
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
