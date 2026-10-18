#!/usr/bin/env python3
"""Build the "Basketball James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_basketball.png + kid_basketball.json

Same columns, rows and animation ranges as kid.png. Frames are padded
(PAD_SIDE each side so the ball never clips the cell). Feet stay on the
same row as James (see src/skins.ts).

Per frame James is recolored with a small flat palette (three navy shades
on the jersey and the shorts, three of his own skin tones, orange trim
and shoes). The ball-side arm is his dribbling arm: the part that stuck
out is cleared and one arm of his width is drawn from the shoulder to
the hand on the ball. Where that arm crossed the torso, the body stays
filled. The other arm is unchanged. At most two arms are visible.

  1. T-shirt -> sleeveless navy tank with a 1px orange collar, armhole
     and hem; both arms stay bare skin. Front views get an orange NY
     wordmark and number 11, back views a larger 11, profiles a 1 on the
     facing flank;
  2. shorts -> three navy shades with an orange side stripe;
  3. sneakers -> orange with a white sole;
  4. white headband across the forehead (wraps the hair on back views);
  5. an orange basketball, still a circle, dribbled on every frame.
     Seams are pre-rendered at a few rotations so the spin stays crisp.
     The ball stays in front of him along the way he faces: lower on
     screen when he faces the camera, ahead of the front foot in
     profile (further ahead on a run), and higher on screen, partly
     behind the body, when he faces away.

Face, hair and neck (under the headband) are James's.

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
SHOE_SHADOW = C(176, 72, 14)
SOLE = C(244, 244, 246)
# Three flat shades each. A pixel's luminance picks one; nothing is blended.
JERSEY_LIGHT = C(46, 84, 190)
JERSEY_MID = NAVY
JERSEY_SHADOW = C(8, 28, 96)
SHORTS_LIGHT = C(22, 46, 124)
SHORTS_MID = C(10, 28, 86)
SHORTS_SHADOW = C(6, 16, 52)
# Taken from James's face and arms, not invented.
SKIN_LIGHT = C(252, 186, 130)
SKIN_MID = C(240, 160, 104)
SKIN_SHADOW = C(198, 122, 72)
BALL = C(232, 108, 26)
BALL_DARK = C(186, 72, 16)
BALL_LIGHT = C(255, 176, 92)
SEAM = C(52, 28, 16)
BALL_EDGE = C(92, 40, 12)
INK = C(12, 16, 36)


def shade(col: np.ndarray, l: np.ndarray, lo: float = 0.62, hi: float = 1.16) -> np.ndarray:
    k = lo + (hi - lo) * np.clip((l - 28.0) / 150.0, 0.0, 1.0)
    return col[None, None, :] * k[..., None]


def _neigh_count(mask: np.ndarray) -> np.ndarray:
    p = np.pad(mask.astype(np.int16), 1, constant_values=0)
    h, w = mask.shape
    total = np.zeros((h, w), dtype=np.int16)
    for dy in range(3):
        for dx in range(3):
            if dy == 1 and dx == 1:
                continue
            total += p[dy:dy + h, dx:dx + w]
    return total


def _solidify_skin(skin: np.ndarray, body: np.ndarray) -> np.ndarray:
    """Close one-pixel holes in an arm and drop one-pixel skin specks.

    James's side view mixes arm pixels with shirt pixels along the same
    limb. Painted one-by-one that is navy/skin stripes. Two passes make
    the arm a solid skin shape and the shirt a solid navy shape.
    """
    s = skin & body
    for _ in range(2):
        skin_nb = _neigh_count(s)
        body_nb = _neigh_count(body)
        gain = body & ~s & (skin_nb >= 5)
        lose = s & (skin_nb <= 1) & ((body_nb - skin_nb) >= 4)
        s = (s | gain) & ~lose & body
    return s


def _apply_shades(rgb: np.ndarray, mask: np.ndarray, L: np.ndarray,
                  light, mid, shadow, cut_lo: float, cut_hi: float) -> np.ndarray:
    """Map luminance to three flat colours. The cuts are fixed, so a walk
    frame can't flicker into a different shade than its neighbour."""
    if not mask.any():
        return rgb
    rgb = np.where((mask & (L <= cut_lo))[..., None], shadow, rgb)
    rgb = np.where((mask & (L > cut_lo) & (L <= cut_hi))[..., None], mid, rgb)
    rgb = np.where((mask & (L > cut_hi))[..., None], light, rgb)
    return rgb


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


def _sample_skin(f: np.ndarray, g: Geometry) -> np.ndarray:
    """Mid skin tone from the arms and face, for the bare shoulders."""
    yy = np.arange(f.shape[0])[:, None]
    r = f[..., 0].astype(np.int16)
    gg = f[..., 1].astype(np.int16)
    b = f[..., 2].astype(np.int16)
    sk = (
        (f[..., 3] > 200) & (r > 170) & (gg > 110) & (b > 60)
        & (r - b > 30) & (yy > g.top + 8) & (yy < g.hem)
    )
    samples = f[sk][:, :3].astype(np.float64)
    if len(samples) < 8:
        return np.array([232.0, 168.0, 120.0])
    return np.median(samples, axis=0)


def _torso_column(jersey: np.ndarray, g: Geometry) -> tuple[int, int] | None:
    """X span of the shirt below the shoulders. That column is the body."""
    h = jersey.shape[0]
    lefts, rights = [], []
    y0 = int(g.neck) + 12
    y1 = int(g.hem) - 8
    for y in range(max(0, y0), min(h, y1)):
        xs = np.nonzero(jersey[y])[0]
        if len(xs) < 6:
            continue
        best = None
        start = 0
        splits = list(np.where(np.diff(xs) > 2)[0]) + [len(xs) - 1]
        for b in splits:
            run = xs[start:int(b) + 1]
            start = int(b) + 1
            if best is None or len(run) > len(best):
                best = run
        if best is None or len(best) < 6:
            continue
        lefts.append(int(best[0]))
        rights.append(int(best[-1]))
    if not lefts:
        return None
    return int(np.median(lefts)), int(np.median(rights))


def _sleeve_caps(jersey: np.ndarray, g: Geometry) -> np.ndarray:
    """Bare skin only where a sleeve sticks out past the torso.

    A side or diagonal shirt is the torso itself. Shaving its edges
    leaves a navy sliver and the midsection looks cut out.
    """
    h, w = jersey.shape
    cap = np.zeros((h, w), dtype=bool)
    column = _torso_column(jersey, g)
    if column is None:
        return cap
    torso_lo, torso_hi = column
    y0 = int(g.neck) + 2
    y1 = int(g.neck) + 13
    for y in range(max(0, y0), min(h, y1)):
        xs = np.nonzero(jersey[y])[0]
        if len(xs) < 8:
            continue
        outside = (xs < torso_lo) | (xs > torso_hi)
        if not outside.any():
            continue
        # keep a solid chest; a row that would lose it is the body, not a sleeve
        if int((~outside).sum()) < 8:
            continue
        cap[y, xs[outside]] = True
    return cap


def _armhole_edge(jersey: np.ndarray, g: Geometry) -> np.ndarray:
    """One pixel of orange where the tank meets the arm, not a band across the chest."""
    h, _w = jersey.shape
    edge = np.zeros_like(jersey)
    y0 = int(g.neck) + 2
    y1 = int(g.neck) + 14
    for y in range(max(0, y0), min(h, y1)):
        xs = np.nonzero(jersey[y])[0]
        if len(xs) < 4:
            continue
        edge[y, int(xs[0])] = True
        edge[y, int(xs[-1])] = True
    return edge


def _shorts_side_stripe(shorts: np.ndarray, cx: float) -> np.ndarray:
    """Outer side of each shorts run, one pixel in from the silhouette."""
    h, w = shorts.shape
    stripe = np.zeros((h, w), dtype=bool)
    for y in range(h):
        xs = np.nonzero(shorts[y])[0]
        if len(xs) < 4:
            continue
        start = 0
        splits = list(np.where(np.diff(xs) > 2)[0]) + [len(xs) - 1]
        for b in splits:
            run = xs[start:int(b) + 1]
            start = int(b) + 1
            if len(run) < 3:
                continue
            # the end away from the chest is the outer seam
            if float(run.mean()) <= cx:
                stripe[y, int(run[0])] = True
                if len(run) > 7:
                    stripe[y, int(run[1])] = True
            else:
                stripe[y, int(run[-1])] = True
                if len(run) > 7:
                    stripe[y, int(run[-2])] = True
            # a single run across the body gets a stripe on both hips
            if int(run[0]) < cx - 2 and int(run[-1]) > cx + 2:
                stripe[y, int(run[0])] = True
                stripe[y, int(run[-1])] = True
                if len(run) > 10:
                    stripe[y, int(run[1])] = True
                    stripe[y, int(run[-2])] = True
    return stripe


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
    # dark shirt and shorts pixels are still cloth. The outline test used
    # to drop them, and on a side view the whole short then stayed James's
    # muddy grey instead of navy. The rim is inked afterwards.
    clothes = a & (yy > g.neck) & ~sk & ~hands
    jersey = clothes & (yy <= waist + 1)
    # sleeveless: the outer shoulder of the tee is skin, not a sleeve cap.
    # The ball side is the drawn arm, so a cap there is a second limb.
    caps = _sleeve_caps(jersey, g)
    side = _ball_side(direction)
    if side > 0:
        caps &= xx < g.head_cx
    else:
        caps &= xx > g.head_cx
    jersey = jersey & ~caps
    shorts = clothes & (yy > waist) & (yy < g.hem + 2)
    shins = a & sk & (yy >= g.hem) & ~arms & ~hands
    shoes = a & (yy >= g.hem + 2) & ~sk & ~shins & ~arms

    rim = silhouette(a)
    # skin, including the bare shoulders, matches James's own three tones
    if caps.any():
        out[caps, 3] = 255
    skin_region = (sk | caps) & (out[..., 3] > 40)
    # arms only. Legs stay as James painted them; growing skin into the
    # shorts would erase the navy.
    band = (yy > g.neck) & (yy < g.hem)
    body_band = (out[..., 3] > 40) & band
    solidified = _solidify_skin(skin_region & band, body_band)
    # holes the arm gave back become jersey or shorts so they are not
    # left as James's grey
    lost = (skin_region & band) & ~solidified & body_band
    skin_region = solidified | (skin_region & ~band)
    jersey = (jersey & ~skin_region) | (lost & (yy <= waist + 1))
    shorts = (shorts & ~skin_region) | (lost & (yy > waist) & (yy < g.hem + 2))
    caps = caps & skin_region
    # Flat fills. Continuous shading was the mottled orange/blue/skin noise.
    rgb = _apply_shades(rgb, jersey & ~rim, L, JERSEY_LIGHT, JERSEY_MID, JERSEY_SHADOW, 52, 76)
    rgb = _apply_shades(rgb, shorts & ~rim, L, SHORTS_LIGHT, SHORTS_MID, SHORTS_SHADOW, 48, 72)
    rgb = _apply_shades(rgb, skin_region & ~caps, L, SKIN_LIGHT, SKIN_MID, SKIN_SHADOW, 165, 198)
    rgb = np.where(caps[..., None], SKIN_MID, rgb)

    arm = tagging_arm(arms | (outline & grow(arms, a, 1)), g, direction)
    fist = fist_mask(arm & ~rim, g, direction)
    fist = fist | (hands & arm & ~rim)
    # the tagging arm stays the kid's own skin. No compression sleeve.

    # orange trim sits one pixel in from the silhouette
    inner = ~rim
    jtop, jbot = torso_rows(jersey & inner)
    if jtop is not None:
        # one continuous row at the collar and one at the hem
        neck = jersey & inner & (yy == jtop) & (yy > g.neck + 1)
        hem = jersey & inner & (yy == jbot)
        rgb = np.where((neck | hem)[..., None], ORANGE, rgb)
    # armholes: the outer pixel of the shoulder, not a scatter where skin touches cloth
    armhole = _armhole_edge(jersey & inner, g)
    rgb = np.where(armhole[..., None], ORANGE, rgb)
    # one orange stripe down each outer side of the shorts, inside the outline
    stripe = _shorts_side_stripe(shorts & inner, g.head_cx)
    rgb = np.where(stripe[..., None], ORANGE, rgb)

    # sneakers keep James's foot shape. A pale pixel is the white sole of
    # that foot; the dark upper becomes orange; the ankle stays skin.
    # Painting a whole connected component one colour fused both feet.
    footwear = a & (yy >= g.hem) & ~jersey & ~shorts & ~arms & ~hands & ~fist
    if footwear.any():
        sr = f[..., 0].astype(np.int16)
        sg = f[..., 1].astype(np.int16)
        sb = f[..., 2].astype(np.int16)
        pale = (sr > 170) & (sg > 170) & (sb > 150) & (np.abs(sr - sb) < 80)
        upper = footwear & ~rim & ~pale & ~loose_skin(f)
        rgb = np.where((upper & (L <= 48))[..., None], SHOE_SHADOW, rgb)
        rgb = np.where((upper & (L > 48))[..., None], SHOE_ORANGE, rgb)
        rgb = np.where((footwear & ~rim & pale)[..., None], SOLE, rgb)

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
        # mid-upper back, centered between the collar and the waist.
        # jtop+3 parked the 11 on the neck trim.
        glyph_h = len(big)
        if jtop is not None:
            num_y = int(round((jtop + jbot) / 2 - (glyph_h - 1) / 2))
            num_y = int(np.clip(num_y, jtop + 5, jbot - glyph_h - 1))
        else:
            num_y = g.neck + 10
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

    rgb = _flatten_speckles(rgb, out[..., 3], g.neck)
    out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return out, chest, hands | fist


def _flatten_speckles(rgb: np.ndarray, alpha: np.ndarray, neck: int) -> np.ndarray:
    """Isolated pixels of an odd colour take the majority of their neighbours.

    A one-pixel orange trim or a letter stroke has matching neighbours and
    stays. A single skin pixel in the jersey does not.
    """
    h, w = alpha.shape
    out = rgb
    body = alpha > 200
    for _ in range(2):
        nxt = out.copy()
        changed = False
        ys, xs = np.nonzero(body)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if y <= neck:
                continue
            col = (int(out[y, x, 0]), int(out[y, x, 1]), int(out[y, x, 2]))
            counts: dict[tuple[int, int, int], int] = {}
            same = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if not (0 <= ny < h and 0 <= nx < w and body[ny, nx]):
                        continue
                    key = (int(out[ny, nx, 0]), int(out[ny, nx, 1]), int(out[ny, nx, 2]))
                    counts[key] = counts.get(key, 0) + 1
                    if key == col:
                        same += 1
            if same > 0 or not counts:
                continue
            mode = max(counts, key=counts.get)
            nxt[y, x] = mode
            changed = True
        out = nxt
        if not changed:
            break
    return out


def _dribble_side(direction: str) -> float:
    return float(-TAG_SIDE[direction])


def _layout(g: Geometry, direction: str):
    """Rest pose and the ball's high/low centres.

    The ball leads him in the direction he faces. On a back view that is
    higher on the screen, partly behind the torso. The arm hangs to the
    hand, which sits on the crown of the ball at the top of the bounce.
    """
    side = _ball_side(direction)
    fx, fy = _FACE[direction]
    cx, neck, hem = float(g.head_cx), float(g.neck), float(g.hem)
    floor_y = 98.0 - BALL_R
    if direction in PROFILE:
        face = float(PROFILE[direction])
        # The near arm, on the side he faces. It hangs from that shoulder
        # and bends forward and down onto the ball. The shoulder is not
        # on his back, and nothing reaches behind him.
        shoulder = (cx + face * 5.0, neck + 8.0)
        elbow = (cx + face * 10.0, neck + 18.0)
        hand = (cx + face * 13.0, hem - 10.0)
        ball = (cx + face * 16.0, hem - 3.0)
        low = min(hem + 6.0, floor_y)
    elif direction in BACK:
        # Higher than the hips, and off to the side he is facing, so the
        # ball leads him. North has nowhere to go sideways, so it sits
        # behind the chest. The arm travels one way, down and out to the
        # near side of the ball. A hook back up splits the limb and leaves
        # a navy gap where the shirt shows through.
        if fx == 0.0:
            ball_x = cx + side * 1.0
            high_y = neck + 3.0
            shoulder = (cx + side * 8.0, neck + 6.0)
            hand = (ball_x + side * 4.0, high_y + 4.0)
        else:
            ball_x = cx + fx * 15.0
            high_y = neck + 3.0
            # A near-vertical arm. A sideways one is a wide slab on
            # screen, and the jersey shows through the steps.
            shoulder = (cx + side * 7.0, neck + 5.0)
            # The mitt stops on the ball. A longer arm ran past it and
            # left the hand dangling under the ball.
            hand = (ball_x - side * 8.0, high_y + 7.0)
        low = high_y + 5.0
        # Straight, so the outline is one capsule and not a kink.
        elbow = (
            (shoulder[0] + hand[0]) * 0.5,
            (shoulder[1] + hand[1]) * 0.5,
        )
        ball = (ball_x, high_y)
    elif direction in ("SE", "SW"):
        # In front of him: lower on screen, and to the side he faces.
        shoulder = (cx + fx * 8.5, neck + 7.0)
        elbow = (cx + fx * 13.5, hem - 19.0)
        hand = (cx + fx * 11.5, hem - 14.0)
        ball = (cx + fx * 13.0, hem - 6.0)
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
    # outer radius matches James's arm, about 8px across including the outline
    radius = 4.2 + (3.85 - 4.2) * taper
    fist = np.clip((s - 0.74) / 0.26, 0.0, 1.0)
    fist = fist * fist * (3.0 - 2.0 * fist)
    return radius + (4.15 - 3.85) * fist


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
                     shoulder, elbow, hand, forearm_only: bool = False) -> None:
    """Tapered skin limb drawn on top of the body. Nothing underneath is erased.

    forearm_only draws the hand and forearm (elbow to mitt). James's own
    upper arm stays where his frame put it.
    """
    h, w = rgba.shape[:2]
    if forearm_only:
        p0 = np.array(elbow, dtype=np.float64)
        p2 = np.array(hand, dtype=np.float64)
        t = np.linspace(0.0, 1.0, 18)
        pts = (1.0 - t)[:, None] * p0 + t[:, None] * p2
        step = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        dist = np.concatenate([[0.0], np.cumsum(step)])
        total = float(dist[-1]) or 1.0
        # the forearm half of the taper, widening into the mitt at the end
        frac = 0.42 + 0.58 * (dist / total)
    else:
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
    # three flat skin tones, the same ones as the other arm
    lit = nx * -0.60 + ny * -0.80
    fill = np.where(
        (lit > 0.18)[..., None], SKIN_LIGHT,
        np.where((lit > -0.22)[..., None], SKIN_MID, SKIN_SHADOW),
    )

    skin_zone = best_d <= (radius - 1.0)
    ink_zone = (best_d > (radius - 1.0)) & (best_d <= radius)
    # keep the arm below the chin. No partial fringe: those pixels were
    # colours that aren't in the palette.
    below = Y > (g.neck + 1)
    layer = np.zeros((h, w, 4), dtype=np.float64)
    layer[skin_zone & below, :3] = fill[skin_zone & below] / 255.0
    layer[skin_zone & below, 3] = 1.0
    layer[ink_zone & below, :3] = INK / 255.0
    layer[ink_zone & below, 3] = 1.0

    # the root sits under the jersey so the limb grows out of the body
    # instead of a floating cap. Those pixels are his, put back as they were.
    # A back-view arm is short and lies on the ball. Putting the shirt back
    # over that root was slicing the limb and leaving a navy shard.
    base = premul(rgba)
    tucked = to_u8(over(base, layer))
    if forearm_only:
        ex, ey = elbow
        near = (np.hypot(X - ex, Y - ey) <= 3.0) & (rgba[..., 3] > 200)
        tucked[near] = rgba[near]
    elif direction not in BACK:
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
    """The ball plus its antialiased rim. A tight disc was clipping the edge."""
    Y, X = np.mgrid[0:h, 0:w]
    return (X - bx) ** 2 + (Y - by) ** 2 <= (BALL_R + 3.0) ** 2


def _zone_shadow(h: int, w: int, gx: float, gy: float) -> np.ndarray:
    Y, X = np.mgrid[0:h, 0:w]
    sx = (X - gx) / (BALL_R * 0.70)
    sy = (Y - gy) / 2.1
    return (sx * sx + sy * sy) < 1.3


def _dribble_side(direction: str) -> float:
    """Screen direction of the dribble arm. Negative means the back is low x."""
    return float(-TAG_SIDE[direction])


def _back_of(xs: np.ndarray, side: float) -> int | None:
    if len(xs) == 0:
        return None
    return int(xs.min() if side < 0 else xs.max())


def _further_back(x: int, than: int, side: float) -> bool:
    return x < than if side < 0 else x > than


def _core_edges(xs: np.ndarray, cx: float) -> tuple[int, int] | None:
    """The torso run nearest the chest, ignoring a limb that split off."""
    if len(xs) < 10:
        return None
    xs = np.asarray(xs)
    splits = np.where(np.diff(xs) > 2)[0]
    best = None
    best_key = None
    start = 0
    for b in list(splits) + [len(xs) - 1]:
        chunk = xs[start:int(b) + 1]
        start = int(b) + 1
        if len(chunk) < 10 or int(chunk[-1] - chunk[0]) < 11:
            continue
        if chunk[0] <= cx <= chunk[-1]:
            key = (0, -(int(chunk[-1] - chunk[0])))
        else:
            key = (1, min(abs(int(chunk[0] - cx)), abs(int(chunk[-1] - cx))))
        if best_key is None or key < best_key:
            best_key = key
            best = chunk
    if best is None:
        return None
    return int(best[0]), int(best[-1])


def _torso_back_edge(opaque: np.ndarray, arm_mask: np.ndarray,
                     g: Geometry, side: float) -> int | None:
    """Back edge of the torso, from chest rows the dribble arm does not cover.

    On a side view the arm is drawn over the back half of the shirt, so
    those rows are not a reference. The chest just under the neck still
    shows the real contour, and the hips and legs hang from that edge.
    """
    h = opaque.shape[0]
    backs: list[int] = []
    widths: list[int] = []
    y0 = int(g.neck) + 3
    y1 = int(g.neck) + 16
    for y in range(y0, y1):
        if y < 0 or y >= h:
            continue
        full = np.nonzero(opaque[y])[0]
        body = np.nonzero(opaque[y] & ~arm_mask[y])[0]
        if len(full) < 8 or len(body) < 8:
            continue
        fb = _back_of(full, side)
        bb = _back_of(body, side)
        if fb is None or bb is None or abs(fb - bb) > 3:
            continue
        backs.append(fb)
        widths.append(int(body.max() - body.min() + 1))
    if not backs:
        return None
    wds = np.asarray(widths)
    bks = np.asarray(backs)
    keep = wds >= int(np.median(wds)) - 1
    return int(np.median(bks[keep]))


def body_required(src: np.ndarray, g: Geometry, direction: str,
                  arm_mask: np.ndarray) -> np.ndarray:
    """Full James body: head, torso, shorts, both legs, and the tagging arm.

    Pixels the dribble arm covered are body too, when they sit on that
    contour. The tip that swings out past the torso is not body, so a
    filled outline there still counts as a stray fin.
    """
    opaque = src[..., 3] > 40
    side = _dribble_side(direction)
    required = opaque.copy()
    ref = _torso_back_edge(opaque, arm_mask, g, side)
    if ref is None:
        return required
    h, w = opaque.shape
    xs = np.arange(w)
    y_end = min(h, int(g.bottom) + 1)
    for y in range(int(g.neck) + 3, y_end):
        full_xs = np.nonzero(opaque[y])[0]
        full = _back_of(full_xs, side)
        if full is None:
            continue
        body = _back_of(np.nonzero(opaque[y] & ~arm_mask[y])[0], side)
        target = full
        if _further_back(full, ref, side) and abs(int(full) - ref) > 3:
            # Past the chest. A foot that already reaches back stays;
            # the arm beyond that foot, or beyond the chest, does not.
            if body is not None and _further_back(body, ref, side):
                target = full if abs(int(full) - int(body)) <= 3 else body
            else:
                target = ref
        if side < 0:
            cut = arm_mask[y] & (xs < target)
        else:
            cut = arm_mask[y] & (xs > target)
        required[y, cut] = False
        # a limb hanging beside a full torso is not the shirt, even when
        # it lines up with the shoulder. Rebuilding it draws a second arm.
        core = _core_edges(np.nonzero(opaque[y] & ~arm_mask[y])[0], g.head_cx)
        if core is not None:
            lo, hi = core
            if side < 0:
                required[y, arm_mask[y] & (xs < lo)] = False
            else:
                required[y, arm_mask[y] & (xs > hi)] = False
    return required


def _paint_rgb(color: np.ndarray) -> np.ndarray:
    return np.clip(np.round(np.asarray(color, dtype=np.float64)), 0, 255).astype(np.uint8)


def _row_fill_color(row: np.ndarray, y: int, g: Geometry) -> np.ndarray:
    """Jersey, shorts, leg or shoe colour for one reconstructed row.

    Taken from the pixels of this row that are still there. The orange
    number is not the shirt, and a skin pixel in the shirt is the arm
    we just removed, so those lose to navy when the row is the torso.
    """
    navy_px: list[np.ndarray] = []
    short_px: list[np.ndarray] = []
    orange_px: list[np.ndarray] = []
    white_px: list[np.ndarray] = []
    skin_px: list[np.ndarray] = []
    xs = np.nonzero(row[:, 3] > 200)[0]
    for x in xs:
        if _is_ink_px(row[x]):
            continue
        r = int(row[x, 0])
        gc = int(row[x, 1])
        b = int(row[x, 2])
        if b > r + 12 and b > 45:
            (short_px if b < 110 else navy_px).append(row[x, :3])
        elif r > 170 and gc < 190 and b < 110 and r > gc + 30:
            orange_px.append(row[x, :3])
        elif r > 200 and gc > 200 and b > 190:
            white_px.append(row[x, :3])
        elif r > 150 and gc > 90 and r > b:
            skin_px.append(row[x, :3])

    def med(samples: list[np.ndarray], fallback: np.ndarray) -> np.ndarray:
        if not samples:
            return fallback
        return np.median(np.stack(samples).astype(np.float64), axis=0)

    hem = float(g.hem)
    waist = hem - 9.0
    if y <= waist:
        return med(navy_px, NAVY)
    if y < hem - 1:
        return med(short_px, NAVY_DARK)
    if y < hem + 2:
        if len(orange_px) >= len(skin_px) and orange_px:
            return med(orange_px, ORANGE)
        if len(skin_px) > len(orange_px):
            return med(skin_px, NAVY_DARK)
        return med(short_px, NAVY_DARK)
    if len(white_px) > len(orange_px) and len(white_px) >= len(skin_px) and white_px:
        return med(white_px, SOLE)
    if len(skin_px) > len(orange_px) and skin_px:
        return med(skin_px, np.array([232.0, 164.0, 120.0]))
    if orange_px:
        return med(orange_px, SHOE_ORANGE)
    if skin_px:
        return med(skin_px, SHOE_ORANGE)
    return SHOE_ORANGE


def rebuild_hidden_body(body: np.ndarray, src: np.ndarray, g: Geometry,
                        direction: str, arm_mask: np.ndarray) -> np.ndarray:
    """Paint the torso, shorts and legs back where the dribble arm covered them.

    The new arm is drawn afterwards, on top. The swinging tip past the
    torso is left clear so it does not come back as a navy fin.
    """
    required = body_required(src, g, direction, arm_mask)
    side = _dribble_side(direction)
    out = body.copy()
    h, w = out.shape[:2]
    hem = float(g.hem)
    for y in range(int(g.neck) + 3, h):
        need = required[y] & (out[y, :, 3] <= 40)
        if not need.any():
            continue
        color = _paint_rgb(_row_fill_color(out[y], y, g))
        out[y, need, :3] = color
        out[y, need, 3] = 255
        # the old outline is now inside the shirt. Recolour it, but only
        # the pixels that touched the hole, and not the shoe's dark pixels.
        if y < hem + 1:
            xs = np.nonzero(need)[0]
            lo = max(0, int(xs.min()) - 1)
            hi = min(w - 1, int(xs.max()) + 1)
            for x in range(lo, hi + 1):
                if need[x] or not _is_ink_px(out[y, x]):
                    continue
                touches = (x > 0 and need[x - 1]) or (x + 1 < w and need[x + 1])
                if touches:
                    out[y, x, :3] = color
                    out[y, x, 3] = 255
                    need[x] = True
        edge_xs = np.nonzero(out[y, :, 3] > 200)[0]
        edge = _back_of(edge_xs, side)
        if edge is not None and need[edge]:
            out[y, edge, :3] = _paint_rgb(INK)
            out[y, edge, 3] = 255
    return out


def _is_skin_px(px: np.ndarray) -> np.ndarray:
    r = px[..., 0].astype(np.int16)
    g = px[..., 1].astype(np.int16)
    b = px[..., 2].astype(np.int16)
    return (px[..., 3] > 40) & (r > 160) & (g > 100) & (b > 60) & (r - b > 30) & (g > b)


def stray_fragments(merged: np.ndarray, required: np.ndarray, direction: str,
                    shoulder, elbow, hand, bx: float, by: float,
                    gx: float, gy: float,
                    arm_mask: np.ndarray | None = None) -> np.ndarray:
    """Opaque pixels that are not the full body, the ball, or the new arm.

    `required` is the torso, head and legs. A shard beside that contour
    counts in every direction, not only behind a side-view hip. The old
    dribble limb is one of those shards when it was repainted as a sleeve.
    """
    keep = required
    # inside that silhouette, including a one-pixel outline. A fin that
    # sticks out past it is not inside, so it still counts as a fragment.
    shell = np.where(_dilate(keep, 1), np.uint8(255), np.uint8(0))
    allowed = ~_outside_clear(shell, thresh=24)
    h, w = merged.shape[:2]
    # the drawn arm only. A fatter pad was hiding the old sleeve beside it.
    stroke = _zone_arm(h, w, shoulder, elbow, hand, pad=1.0)
    pose = stroke | _zone_ball(h, w, bx, by) | _zone_shadow(h, w, gx, gy)
    allowed |= pose
    raw = (merged[..., 3] > 80) & ~allowed
    exposed = np.zeros((h, w), dtype=bool)
    if raw.any():
        # a repaired slit sits inside the shirt. A shard is a patch that touches
        # the outside, so only those components count.
        a = merged[..., 3] > 40
        pad = np.pad(~a, 1, constant_values=True)
        touches = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
        for comp in components8(raw):
            if (comp & touches).any():
                exposed |= comp
    # any direction, not only the side-view back edge. The foot on the next
    # row can enclose a fin so the flood above never sees it.
    outside = ~_dilate(required, 1)
    fin = outside & (merged[..., 3] > 40) & ~pose
    # the old dribble limb, repainted navy, reads as a second arm. Skin on
    # that mask is the new arm or the hand, and it stays.
    hanging = np.zeros((h, w), dtype=bool)
    if arm_mask is not None:
        hanging = (
            arm_mask & ~required & ~pose & ~_is_skin_px(merged)
            & (merged[..., 3] > 40)
        )
    return exposed | fin | hanging


def clear_stray_fragments(merged: np.ndarray, stray: np.ndarray) -> np.ndarray:
    if not stray.any():
        return merged
    out = merged.copy()
    out[stray] = 0
    return out


def clear_past_contour(merged: np.ndarray, required: np.ndarray, direction: str,
                       shoulder, elbow, hand, bx: float, by: float,
                       gx: float, gy: float) -> np.ndarray:
    """Drop opaque pixels behind the body contour.

    Filling an enclosed gap repaints the old swinging arm as a navy fin.
    The fin sits past the torso; the rebuilt shirt and the real back foot
    do not. The ball, its shadow and the new dribble arm are allowed past
    that edge.
    """
    side = _dribble_side(direction)
    h, w = merged.shape[:2]
    keep = (
        _zone_arm(h, w, shoulder, elbow, hand)
        | _zone_ball(h, w, bx, by)
        | _zone_shadow(h, w, gx, gy)
    )
    out = merged.copy()
    xs = np.arange(w)
    for y in range(h):
        rb = _back_of(np.nonzero(required[y])[0], side)
        if rb is None:
            continue
        past = xs < rb if side < 0 else xs > rb
        kill = past & (out[y, :, 3] > 0) & ~keep[y]
        out[y, kill] = 0
    return out


def _dribble_skin(src: np.ndarray, g: Geometry, direction: str,
                  side: float | None = None) -> np.ndarray:
    """Skin of the arm on `side` of the chest. The outline is separate so
    the shorts, which are dark, are not eaten."""
    h, w = src.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    if side is None:
        side = float(-TAG_SIDE[direction])
    face = (yy <= g.neck + 1) & skin_mask(src)
    arms, _hands = arms_and_hands(src, g, face)
    on_side = arms & ((xx - g.head_cx) * side > 1.0)
    return on_side & (yy > g.neck + 2)


def _ball_side(direction: str) -> float:
    """Screen side of the hand on the ball.

    That is the way he faces. North and south have no sideways facing, so
    the hand stays on the non-tagging side.
    """
    fx = _FACE[direction][0]
    if fx != 0.0:
        return fx
    return _dribble_side(direction)


def _ball_side_skin(src: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """Skin of the arm on the ball's side, from just under the neck to the hem.

    A reach is skin all the way to the fingertips, including the rows that
    touch the collar. The other arm is on the other side of the chest and
    is not included.
    """
    h, w = src.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    side = _ball_side(direction)
    return (
        loose_skin(src)
        & (yy > g.neck)
        & (yy < g.hem - 1)
        & ((xx - g.head_cx) * side > 0)
    )


def fold_dribble_limb(src: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray]:
    """The ball-side arm is not left in place under a second limb.

    Where that arm crosses the torso, those pixels become cloth so the
    body stays solid. The part that sticks out past the chest is cleared;
    the one drawn arm replaces it. Returns (frame, torso mask that must
    stay opaque).
    """
    f = src.copy()
    h, w = f.shape[:2]
    side = _ball_side(direction)
    limb = _ball_side_skin(f, g, direction)
    yy = np.arange(h)[:, None]

    opaque = alpha_mask(f)
    # The arm's own outline is dark, not skin, and it used to stretch the
    # cloth span out to the fingertips. Then the reach was "inside" the
    # torso, got painted as a shirt, and the sleeve pass turned it back
    # into a second arm. Measure the shirt without that outline.
    near = _dilate(limb, 2)
    cloth = opaque & ~loose_skin(f) & ~near & (yy > g.neck) & (yy < g.hem + 2)
    spans: list[tuple[int, int]] = []
    y_lo = int(g.neck) + 10
    y_hi = int(g.hem) - 4
    for y in range(max(0, y_lo), min(h, y_hi)):
        xs = np.nonzero(cloth[y])[0]
        if len(xs) >= 6:
            spans.append((int(xs.min()), int(xs.max())))
    if spans:
        trunk = (int(np.median([lo for lo, _hi in spans])),
                 int(np.median([hi for _lo, hi in spans])))
    else:
        trunk = (int(g.head_cx) - 8, int(g.head_cx) + 8)
    core = np.zeros((h, w), dtype=bool)
    for y in range(h):
        xs = np.nonzero(cloth[y])[0]
        if len(xs) >= 4:
            lo, hi = int(xs.min()), int(xs.max())
            # a leftover arm pixel must not pull the chest out to the hand
            if side > 0:
                hi = min(hi, trunk[1] + 2)
                lo = min(lo, trunk[0])
            else:
                lo = max(lo, trunk[0] - 2)
                hi = max(hi, trunk[1])
        else:
            lo, hi = trunk
        lo = max(0, lo - 1)
        hi = min(w - 1, hi + 1)
        if g.neck < y < g.hem + 2:
            core[y, lo:hi + 1] = True

    interior = limb & core
    L = lum(f)
    dark = (f[..., 3] > 40) & (L < 70)
    exterior = ((limb | (near & dark)) & ~core)
    # shirt-like, so paint_uniform treats the covered torso as cloth
    # A real jersey colour, so a pixel paint misses is still in the palette.
    f[interior, 0] = int(JERSEY_MID[0])
    f[interior, 1] = int(JERSEY_MID[1])
    f[interior, 2] = int(JERSEY_MID[2])
    f[interior, 3] = 255
    f[exterior] = 0

    for y in range(int(g.neck) + 2, int(g.hem)):
        xs = np.nonzero(f[y, :, 3] > 40)[0]
        if len(xs) < 2:
            continue
        for i in range(len(xs) - 1):
            gap = int(xs[i + 1] - xs[i] - 1)
            if gap <= 0 or gap > 2:
                continue
            x0 = int(xs[i]) + 1
            x1 = int(xs[i + 1])
            if x1 <= x0 or not core[y, x0:x1].all():
                continue
            f[y, x0:x1, 0] = int(JERSEY_MID[0])
            f[y, x0:x1, 1] = int(JERSEY_MID[1])
            f[y, x0:x1, 2] = int(JERSEY_MID[2])
            f[y, x0:x1, 3] = 255
    kept = core & ((src[..., 3] > 40) | interior)
    return f, kept


def _row_core(xs: np.ndarray, chest_w: int, side: float,
              fallback: tuple[int, int]) -> tuple[int, int]:
    """Torso span for one row. A side view whose arm is the back half is
    extended back to the chest width; a limb past that stays outside."""
    if len(xs) < 6:
        return fallback
    lo, hi = int(xs.min()), int(xs.max())
    if hi - lo < chest_w - 2:
        if side < 0:
            lo = hi - chest_w
        else:
            hi = lo + chest_w
    return lo, hi


def prepare_james(src: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray]:
    """James's own pixels, with the dribble limb past the torso removed.

    The lower body is not redrawn. Shorts, legs and shoes keep his alpha.
    Arm pixels that sit on the torso become cloth so the tank can recolor
    them; the tagging arm stays skin. Returns (frame, kept mask).
    """
    f = close_streaks(src, g.neck + 2)
    g = Geometry(f)
    h, w = f.shape[:2]
    limb = _dribble_skin(f, g, direction)
    opaque = alpha_mask(f)
    side = float(-TAG_SIDE[direction])
    chest: list[tuple[int, int]] = []
    for y in range(int(g.neck) + 3, int(g.neck) + 14):
        if y < 0 or y >= h:
            continue
        xs = np.nonzero(opaque[y])[0]
        if len(xs) >= 8:
            chest.append((int(xs.min()), int(xs.max())))
    if chest:
        chest_w = int(np.median([hi - lo for lo, hi in chest]))
        ref = (int(np.median([lo for lo, hi in chest])),
               int(np.median([hi for lo, hi in chest])))
    else:
        chest_w = 16
        ref = (int(g.head_cx) - 8, int(g.head_cx) + 8)
    chest_w = max(chest_w, 12)

    interior = np.zeros((h, w), dtype=bool)
    exterior = np.zeros((h, w), dtype=bool)
    core = np.zeros((h, w), dtype=bool)
    prev = ref
    non = opaque & ~limb
    for y in range(h):
        lo, hi = _row_core(np.nonzero(non[y])[0], chest_w, side, prev)
        prev = (lo, hi)
        lo = max(0, lo)
        hi = min(w - 1, hi)
        core[y, lo:hi + 1] = True
        row = limb[y]
        xs = np.arange(w)
        inside = row & (xs >= lo - 1) & (xs <= hi + 1)
        interior[y] = inside
        exterior[y] = row & ~inside

    # the old arm's outline, outside the torso only. Two steps would walk
    # into the shorts, which are the same darkness as that outline.
    L = lum(f)
    dark = (f[..., 3] > 40) & (L < 60) & ~loose_skin(f)
    outline = _dilate(exterior, 1) & dark & ~core & (np.arange(h)[:, None] < g.hem + 1)
    clear = exterior | outline

    out = f.copy()
    out[clear] = 0
    # cloth tone, not skin, so the covered torso is a shirt the tank can paint
    out[interior & ~clear, 0] = 72
    out[interior & ~clear, 1] = 86
    out[interior & ~clear, 2] = 82
    out[interior & ~clear, 3] = 255

    # 1-2px slits inside the torso. Wider gaps are the space between the
    # legs or between the arm and the hip, and those stay clear.
    yy = np.arange(h)
    for y in range(int(g.neck) + 2, h):
        xs = np.nonzero(out[y, :, 3] > 40)[0]
        xs = xs[(xs >= 0)]
        if len(xs) < 2:
            continue
        for i in range(len(xs) - 1):
            gap = int(xs[i + 1] - xs[i] - 1)
            if gap <= 0 or gap > 2:
                continue
            x0 = int(xs[i]) + 1
            x1 = int(xs[i + 1])
            if not core[y, x0:x1].all():
                continue
            # a slit has body above or below; the open edge of a foot does not
            band = out[max(0, y - 1):min(h, y + 2), x0:x1, 3] > 40
            if not band.any():
                continue
            out[y, x0:x1, :3] = out[y, int(xs[i]), :3]
            out[y, x0:x1, 3] = 255

    kept = out[..., 3] > 40
    out[kept, 3] = 255
    return out, kept


def _lead_x(body: np.ndarray, g: Geometry, face: float) -> float:
    """The toe that is furthest along the way he faces."""
    a = body[..., 3] > 180
    h = a.shape[0]
    y0 = max(0, int(g.hem) - 4)
    y1 = min(h, int(round(g.hem)) + 16)
    best = None
    for y in range(y0, y1):
        xs = np.nonzero(a[y])[0]
        if len(xs) < 3:
            continue
        x = float(xs[-1] if face > 0 else xs[0])
        if best is None or (face > 0 and x > best) or (face < 0 and x < best):
            best = x
    if best is None:
        return float(g.head_cx + face * 12.0)
    return best


def _pose(body: np.ndarray, g0: Geometry, direction: str, anim: str, index: int):
    t = bounce_t(anim, index)
    shoulder, elbow, rest_hand, high, low, _side = _layout(g0, direction)
    hand = _flick_hand(elbow, rest_hand, t)
    bx = high[0] * (1.0 - t) + low[0] * t
    by = high[1] * (1.0 - t) + low[1] * t
    # A run stride leaves the standing dribble inside the legs, at the
    # back knee. Push the ball, and the hand on it, out past the lead toe.
    if anim == "run" and direction in PROFILE:
        face = float(PROFILE[direction])
        target = _lead_x(body, g0, face) + face * 6.0
        if (target - bx) * face > 2.0:
            shift = target - bx
            bx = target
            hand = (hand[0] + shift, hand[1])
            elbow = (elbow[0] + shift * 0.7, elbow[1])
    margin = BALL_R + 0.6
    bx = float(np.clip(bx, margin, 100.0 - margin))
    by = float(np.clip(by, margin, 100.0 - margin))
    return shoulder, elbow, hand, bx, by, t


# Preview grass the contact sheets composite onto. A hole in the shorts
# is this colour once the frame is shown, and partial alpha is the same
# hole with the grass showing through.
PREVIEW_BG = (118, 176, 86)


def silhouette_faults(merged: np.ndarray, kept: np.ndarray, neck: int) -> np.ndarray:
    """Pixels inside the filled body that are see-through or preview-green.

    `kept` is James's body after the swinging arm past the torso is removed.
    A 1px closing catches an open bite the border flood misses, including
    one that touches the outside. Hair spikes above the neck are his outline,
    not a hole in the shorts. The gap between the legs is wider than the
    close and is not a fault.
    """
    inside = _dilate(kept, 1)
    # erode the dilation back, so only gaps the close actually fills remain,
    # not a rim around the outside of the sprite
    p = np.pad(inside, 1, constant_values=False)
    ero = (
        p[1:-1, 1:-1]
        & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    )
    a = merged[..., 3]
    rgb = merged[..., :3].astype(np.int16)
    grass = (
        (np.abs(rgb[..., 0] - PREVIEW_BG[0]) <= 28)
        & (np.abs(rgb[..., 1] - PREVIEW_BG[1]) <= 28)
        & (np.abs(rgb[..., 2] - PREVIEW_BG[2]) <= 28)
        & (a > 20)
    )
    see = (a < 255) | grass
    left = np.zeros_like(kept)
    right = np.zeros_like(kept)
    up = np.zeros_like(kept)
    down = np.zeros_like(kept)
    left[:, 1:] = kept[:, :-1]
    right[:, :-1] = kept[:, 1:]
    up[1:, :] = kept[:-1, :]
    down[:-1, :] = kept[1:, :]
    sandwiched = (left & right) | (up & down)
    bites = ero & ~kept & sandwiched & see
    bites[: int(neck) + 2] = False
    covered = kept & see
    # a 1px slit with body above and below reads as grass even when the
    # border flood can reach it. Hair above the shoulders is left alone.
    solid = a > 200
    slit = np.zeros_like(kept)
    # the ball's antialiased rim sits near 250 and is not a hole in the shorts
    slit[1:-1] = (a[1:-1] < 200) & solid[:-2] & solid[2:]
    slit[: int(neck) + 8] = False
    # a one-pixel crack between two opaque pixels, open to the grass
    crack = np.zeros_like(kept)
    row = (a < 40)
    left = np.zeros_like(kept)
    right = np.zeros_like(kept)
    left[:, 1:] = a[:, :-1] > 80
    right[:, :-1] = a[:, 1:] > 80
    crack = row & left & right
    crack[: int(neck) + 8] = False
    return bites | covered | slit | crack


def baller(frame: np.ndarray, direction: str, anim: str, index: int) -> np.ndarray:
    merged, _kept, _n_hole, _n_stray = compose(frame, direction, anim, index)
    return merged


def _alpha_lost(src: np.ndarray, merged: np.ndarray) -> int:
    """Opaque James pixels that Basketball made see-through."""
    src_a = src[..., 3]
    out_a = merged[..., 3]
    missing = (src_a > 40) & (out_a <= 40)
    weak = (src_a >= 200) & (out_a < 200)
    return int(missing.sum() + weak.sum())


def _snap_body_palette(merged: np.ndarray, g: Geometry, bx: float, by: float) -> np.ndarray:
    """Body pixels outside the ball are exact palette colours, with no
    single-pixel odd colours left where the arm was drawn on top."""
    allowed = np.array(sorted(_body_palette()), dtype=np.int16)
    h, w = merged.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ball = (xx - bx) ** 2 + (yy - by) ** 2 <= (BALL_R + 2.5) ** 2
    rgb = merged[..., :3].astype(np.int16)
    ok = np.zeros((h, w), dtype=bool)
    for col in allowed:
        ok |= (rgb[..., 0] == col[0]) & (rgb[..., 1] == col[1]) & (rgb[..., 2] == col[2])
    body = (yy > g.neck + 1) & (merged[..., 3] > 200) & ~ball
    bad = body & ~ok
    out = merged.copy()
    if bad.any():
        pts = rgb[bad]
        dist = ((pts[:, None, :].astype(np.int32) - allowed[None, :, :].astype(np.int32)) ** 2).sum(-1)
        nearest = allowed[dist.argmin(1)]
        out[bad, :3] = nearest
    flat = _flatten_speckles(out[..., :3].astype(np.float64), np.where(ball, 0, out[..., 3]), g.neck)
    out[..., :3] = np.clip(np.rint(flat), 0, 255).astype(np.uint8)
    return out


def _join_split_skin(merged: np.ndarray, g: Geometry) -> np.ndarray:
    """A bare shoulder a pixel or two above its arm is the same arm.

    Sleeve pixels and the arm below them can be split by one navy row.
    That split counted as a third arm. Bridge it with the mid skin tone
    when the two pieces already overlap in x, and only through pixels
    that are already body, so the silhouette does not grow.
    """
    out = merged
    h, w = out.shape[:2]
    yy = np.arange(h)[:, None]
    skin = _skin_mask_flat(out)
    skin &= (yy > g.neck + 2) & (yy < g.hem - 1)
    comps = [c for c in components8(skin) if int(c.sum()) >= 8]
    if len(comps) < 2:
        return out
    opaque = out[..., 3] > 40
    for i, a in enumerate(comps):
        ay, ax = np.nonzero(a)
        for b in comps[i + 1:]:
            by, bx = np.nonzero(b)
            if int(ax.max()) < int(bx.min()) - 2 or int(bx.max()) < int(ax.min()) - 2:
                continue
            best = 99
            pair = None
            for y1, x1 in zip(ay, ax):
                dist = np.maximum(np.abs(by - int(y1)), np.abs(bx - int(x1)))
                j = int(dist.argmin())
                if int(dist[j]) < best:
                    best = int(dist[j])
                    pair = (int(y1), int(x1), int(by[j]), int(bx[j]))
            if pair is None or best > 2 or best == 0:
                continue
            y1, x1, y2, x2 = pair
            steps = max(abs(y2 - y1), abs(x2 - x1), 1)
            if out is merged:
                out = merged.copy()
            for t in range(steps + 1):
                y = int(round(y1 + (y2 - y1) * t / steps))
                x = int(round(x1 + (x2 - x1) * t / steps))
                if skin[y, x]:
                    continue
                # a one-pixel crack, or a shirt pixel between the two pieces
                near_body = opaque[y, x]
                if not near_body:
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx_ = y + dy, x + dx
                            if 0 <= ny < h and 0 <= nx_ < w and opaque[ny, nx_]:
                                near_body = True
                                break
                        if near_body:
                            break
                if not near_body:
                    continue
                out[y, x, 0] = int(SKIN_MID[0])
                out[y, x, 1] = int(SKIN_MID[1])
                out[y, x, 2] = int(SKIN_MID[2])
                out[y, x, 3] = 255
    return out


def _recolor_hip_slivers(merged: np.ndarray, g: Geometry) -> np.ndarray:
    """A few skin pixels stuck to the hip are the shirt edge, not an arm.

    James's arm is several pixels wide and reaches the shoulder. A sliver
    that starts down by the waist and is only a couple of pixels across
    is recolored to the cloth it touches, so it does not read as a third limb.
    """
    h, w = merged.shape[:2]
    yy = np.arange(h)[:, None]
    skin = _skin_mask_flat(merged)
    band = (yy > g.neck + 2) & (yy < g.hem - 1)
    skin &= band
    cloth_cols = (
        JERSEY_LIGHT, JERSEY_MID, JERSEY_SHADOW,
        SHORTS_LIGHT, SHORTS_MID, SHORTS_SHADOW,
    )
    rgb = merged[..., :3]
    cloth = np.zeros((h, w), dtype=bool)
    for col in cloth_cols:
        cloth |= (rgb[..., 0] == int(col[0])) & (rgb[..., 1] == int(col[1])) & (rgb[..., 2] == int(col[2]))
    cloth &= merged[..., 3] > 200
    out = merged
    for comp in components8(skin):
        n = int(comp.sum())
        if n < 12:
            continue
        ys, xs = np.nonzero(comp)
        width = int(xs.max() - xs.min()) + 1
        top = int(ys.min())
        if width > 4 or top < int(g.neck) + 12:
            continue
        touched = 0
        for y, x in zip(ys.tolist(), xs.tolist()):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and cloth[ny, nx]:
                        touched += 1
                        dy = 99
                        break
                if dy == 99:
                    break
        if touched * 2 < n:
            continue
        if out is merged:
            out = merged.copy()
        waist = g.hem - 9
        for y, x in zip(ys.tolist(), xs.tolist()):
            picked = None
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and cloth[ny, nx] and not comp[ny, nx]:
                        picked = out[ny, nx, :3].copy()
                        break
                if picked is not None:
                    break
            if picked is None:
                picked = SHORTS_MID if y > waist else JERSEY_MID
            out[y, x, 0] = int(picked[0])
            out[y, x, 1] = int(picked[1])
            out[y, x, 2] = int(picked[2])
            out[y, x, 3] = 255
    return out


def _drop_crumbs(merged: np.ndarray, g: Geometry, kept: np.ndarray) -> np.ndarray:
    """An opaque pixel with no opaque neighbour is a speck, not a limb.

    Inside the filled chest it becomes jersey so the torso stays solid.
    Anywhere else it is erased.
    """
    h, w = merged.shape[:2]
    a = merged[..., 3] > 200
    nb = np.zeros((h, w), dtype=np.int16)
    nb[1:, 1:] += a[:-1, :-1]
    nb[1:, :] += a[:-1, :]
    nb[1:, :-1] += a[:-1, 1:]
    nb[:, 1:] += a[:, :-1]
    nb[:, :-1] += a[:, 1:]
    nb[:-1, 1:] += a[1:, :-1]
    nb[:-1, :] += a[1:, :]
    nb[:-1, :-1] += a[1:, 1:]
    yy = np.arange(h)[:, None]
    crumb = a & (yy > g.neck + 1) & (nb == 0)
    if not crumb.any():
        return merged
    out = merged.copy()
    paint = crumb & kept
    out[paint, 0] = int(JERSEY_MID[0])
    out[paint, 1] = int(JERSEY_MID[1])
    out[paint, 2] = int(JERSEY_MID[2])
    out[paint, 3] = 255
    out[crumb & ~kept] = 0
    return out


def _clear_rear_arm(body: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """Drop skin that sticks out past the rear edge of the torso.

    On a side view that is the arm coming straight out of his back.
    The dribbling arm is drawn afterwards, on the side he faces.
    """
    fx = _FACE[direction][0]
    if fx == 0.0 or direction not in PROFILE:
        return body
    h, w = body.shape[:2]
    yy = np.arange(h)[:, None]
    skin = _skin_mask_flat(body)
    skin &= (yy > g.neck + 2) & (yy < g.hem - 1)
    rgb = body[..., :3]
    cloth = np.zeros((h, w), dtype=bool)
    for col in (
        JERSEY_LIGHT, JERSEY_MID, JERSEY_SHADOW,
        SHORTS_LIGHT, SHORTS_MID, SHORTS_SHADOW, ORANGE,
    ):
        cloth |= (
            (rgb[..., 0] == int(col[0]))
            & (rgb[..., 1] == int(col[1]))
            & (rgb[..., 2] == int(col[2]))
        )
    cloth &= body[..., 3] > 200
    kill = np.zeros((h, w), dtype=bool)
    xs = np.arange(w)[None, :]
    for y in range(int(g.neck) + 2, int(g.hem)):
        row = np.nonzero(cloth[y])[0]
        if len(row) < 4:
            continue
        if fx > 0.0:
            edge = int(row.min())
            kill[y] = skin[y] & (xs[0] < edge - 1)
        else:
            edge = int(row.max())
            kill[y] = skin[y] & (xs[0] > edge + 1)
    if not kill.any():
        return body
    out = body.copy()
    out[kill] = 0
    # the outline of that arm, still sitting past the rear edge
    ink = (
        (out[..., 0] == int(INK[0]))
        & (out[..., 1] == int(INK[1]))
        & (out[..., 2] == int(INK[2]))
        & (out[..., 3] > 200)
        & (yy > g.neck + 2)
        & (yy < g.hem)
    )
    pad = np.pad(kill, 1, constant_values=False)
    beside = (
        pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
        | pad[:-2, :-2] | pad[:-2, 2:] | pad[2:, :-2] | pad[2:, 2:]
    )
    rear = (xs - g.head_cx) * (-fx) > 0
    out[ink & beside & rear] = 0
    return out


def compose(frame: np.ndarray, direction: str, anim: str, index: int):
    """Fold the ball-side arm into the torso, recolor with a flat palette,
    then draw one arm from the shoulder to the hand on the ball.
    """
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return src, np.zeros(src.shape[:2], dtype=bool), 0, (0.0, 0.0, 0.0, 0.0)
    g0 = Geometry(src)
    folded, kept = fold_dribble_limb(src, g0, direction)
    body, _chest, _hands = paint_uniform(folded, Geometry(folded), direction)
    body[kept, 3] = 255
    body = _clear_rear_arm(body, g0, direction)
    shoulder, elbow, hand, bx, by, t = _pose(body, g0, direction, anim, index)
    gx, gy, behind = bx, float(min(by + BALL_R, 99.0)), direction in BACK
    shadow = shadow_layer(body.shape[:2], gx, gy, strength=0.35 + 0.65 * t)
    ball = np.zeros_like(shadow)
    _paste(ball, ball_sprite(spin_deg(anim, index)), bx, by)
    if behind:
        solid = body.copy()
        solid[kept, 3] = 255
        merged = to_u8(over(over(shadow, ball), premul(solid)))
    else:
        merged = to_u8(over(premul(body), over(shadow, ball)))
    draw_dribble_arm(merged, g0, direction, shoulder, elbow, hand, forearm_only=False)
    merged = _join_split_skin(merged, g0)
    merged = _recolor_hip_slivers(merged, g0)
    # the chest we filled must stay opaque. The old sticking-out arm does not.
    hole = kept & (merged[..., 3] <= 40)
    if hole.any():
        merged = merged.copy()
        merged[hole] = body[hole]
        merged[hole, 3] = 255
    merged = _snap_body_palette(merged, g0, bx, by)
    merged = _drop_crumbs(merged, g0, kept)
    return merged, kept, int((kept & (merged[..., 3] <= 40)).sum()), (bx, by, hand[0], hand[1])


def _seal_body_slits(merged: np.ndarray, neck: int) -> np.ndarray:
    """Close 1-2px slits that have opaque body directly above and below.

    Those are the green specks in the shorts. The open gap between the
    legs has no body below it, so it stays clear.
    """
    out = merged
    h = out.shape[0]
    y0 = int(neck) + 8
    for _round in range(3):
        changed = False
        for gap in (1, 2):
            solid = out[..., 3] > 200
            for y in range(max(y0, 1), h - gap):
                hole = np.ones(out.shape[1], dtype=bool)
                for k in range(gap):
                    hole &= out[y + k, :, 3] < 200
                hole &= solid[y - 1] & solid[y + gap]
                if not hole.any():
                    continue
                if out is merged:
                    out = out.copy()
                changed = True
                for k in range(gap):
                    out[y + k, hole] = out[y - 1, hole]
                    out[y + k, hole, 3] = 255
        # a one-pixel crack between the ball and the hip still shows grass.
        # Filling it can close the slit above, so the vertical pass runs again.
        solidish = out[..., 3] > 80
        for y in range(y0, h):
            hole = out[y, :, 3] < 40
            left = np.zeros(out.shape[1], dtype=bool)
            right = np.zeros(out.shape[1], dtype=bool)
            left[1:] = solidish[y, :-1]
            right[:-1] = solidish[y, 1:]
            crack = hole & left & right
            if not crack.any():
                continue
            if out is merged:
                out = out.copy()
            changed = True
            xs = np.nonzero(crack)[0]
            for x in xs:
                src_x = x - 1 if out[y, x - 1, 3] >= out[y, x + 1, 3] else x + 1
                out[y, x] = out[y, src_x]
                out[y, x, 3] = 255
        if not changed:
            break
    return out


def anim_of(col: int, meta: dict) -> tuple[str, int]:
    for name, spec in meta["animations"].items():
        if spec["start"] <= col < spec["start"] + spec["count"]:
            return name, col - spec["start"]
    return "idle", 0


def audit_frame(frame: np.ndarray, merged: np.ndarray, direction: str,
                anim: str, index: int) -> tuple[int, int]:
    """See-through pixels inside the copied body, then crumbs outside it.

    compose() already measured these. This re-checks the returned frame
    so a later edit can't paint a hole back in without the scan noticing.
    """
    _merged, kept, _holes, _stray = compose(frame, direction, anim, index)
    # judge the frame main() actually saved, which is `merged`
    g0 = Geometry(pad_frame(frame))
    holes = silhouette_faults(merged, kept, g0.neck)
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return 0, 0
    g0 = Geometry(src)
    shoulder, elbow, hand, bx, by, _t = _pose(merged, g0, direction, anim, index)
    h, w = merged.shape[:2]
    gx, gy = bx, float(min(by + BALL_R, 99.0))
    pose = (
        _zone_arm(h, w, shoulder, elbow, hand, pad=2.2)
        | _zone_ball(h, w, bx, by)
        | _zone_shadow(h, w, gx, gy)
    )
    stray = (merged[..., 3] > 40) & ~_dilate(kept, 1) & ~pose
    return int(holes.sum()), int(stray.sum())


def _rgb_key(px: np.ndarray) -> tuple[int, int, int]:
    return int(px[0]), int(px[1]), int(px[2])


def _body_palette() -> set[tuple[int, int, int]]:
    cols = (
        JERSEY_LIGHT, JERSEY_MID, JERSEY_SHADOW,
        SHORTS_LIGHT, SHORTS_MID, SHORTS_SHADOW,
        SKIN_LIGHT, SKIN_MID, SKIN_SHADOW,
        ORANGE, ORANGE_HOT, SHOE_ORANGE, SHOE_SHADOW, SOLE,
        INK, WHITE, WHITE_SHADE, BAND_EDGE,
    )
    return {(_rgb_key(c)) for c in cols}


def _skin_mask_flat(merged: np.ndarray) -> np.ndarray:
    skin = np.zeros(merged.shape[:2], dtype=bool)
    for col in (SKIN_LIGHT, SKIN_MID, SKIN_SHADOW):
        skin |= (
            (merged[..., 0] == int(col[0]))
            & (merged[..., 1] == int(col[1]))
            & (merged[..., 2] == int(col[2]))
        )
    return skin & (merged[..., 3] > 200)


def count_arms(merged: np.ndarray, g: Geometry) -> int:
    """Skin limbs between the neck and the shorts. Legs are below the hem."""
    yy = np.arange(merged.shape[0])[:, None]
    skin = _skin_mask_flat(merged)
    skin &= (yy > g.neck + 2) & (yy < g.hem - 1)
    return sum(1 for comp in components8(skin) if int(comp.sum()) >= 12)


def palette_off(merged: np.ndarray, g: Geometry, bx: float, by: float) -> int:
    """Opaque body pixels below the neck whose colour is not in the palette.

    The ball is excluded. Hair and the face sit above the neck.
    """
    allowed = _body_palette()
    h, w = merged.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ball = (xx - bx) ** 2 + (yy - by) ** 2 <= (BALL_R + 4.0) ** 2
    body = (yy > g.neck + 1) & (merged[..., 3] > 200) & ~ball
    ok = np.zeros((h, w), dtype=bool)
    rgb = merged[..., :3]
    for col in allowed:
        ok |= (rgb[..., 0] == col[0]) & (rgb[..., 1] == col[1]) & (rgb[..., 2] == col[2])
    return int((body & ~ok).sum())


def isolated_speckles(merged: np.ndarray, g: Geometry, bx: float, by: float) -> int:
    """Opaque pixels below the neck with no neighbour of the same colour."""
    h, w = merged.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = merged[..., 3] > 200
    ball = (xx - bx) ** 2 + (yy - by) ** 2 <= (BALL_R + 4.0) ** 2
    body = a & (yy > g.neck + 1) & ~ball
    n = 0
    ys, xs = np.nonzero(body)
    rgb = merged[..., :3]
    for y, x in zip(ys.tolist(), xs.tolist()):
        col = (int(rgb[y, x, 0]), int(rgb[y, x, 1]), int(rgb[y, x, 2]))
        same = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and a[ny, nx]:
                    if (int(rgb[ny, nx, 0]), int(rgb[ny, nx, 1]), int(rgb[ny, nx, 2])) == col:
                        same += 1
        if same == 0:
            n += 1
    return n


def green_pixels(merged: np.ndarray, g: Geometry, bx: float, by: float) -> int:
    h, w = merged.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ball = (xx - bx) ** 2 + (yy - by) ** 2 <= (BALL_R + 4.0) ** 2
    r = merged[..., 0].astype(np.int16)
    gg = merged[..., 1].astype(np.int16)
    b = merged[..., 2].astype(np.int16)
    green = (
        (merged[..., 3] > 200)
        & (yy > g.neck + 1)
        & ~ball
        & (gg > r + 12)
        & (gg > b + 12)
        & (gg > 80)
    )
    return int(green.sum())


def arm_shard(merged: np.ndarray, g: Geometry, direction: str) -> str:
    """Navy or orange showing through a split in one arm.

    A gap only a few pixels wide, with skin on both sides, is the limb
    folding back on itself. The shirt between the two arms is much wider
    and is not a shard.
    """
    h, w = merged.shape[:2]
    yy = np.arange(h)[:, None]
    skin = _skin_mask_flat(merged)
    skin &= (yy > g.neck + 2) & (yy < g.hem - 1)
    if not skin.any():
        return ""
    rgb = merged[..., :3]
    cloth = np.zeros((h, w), dtype=bool)
    for col in (JERSEY_LIGHT, JERSEY_MID, JERSEY_SHADOW, ORANGE, ORANGE_HOT, INK):
        cloth |= (
            (rgb[..., 0] == int(col[0]))
            & (rgb[..., 1] == int(col[1]))
            & (rgb[..., 2] == int(col[2]))
        )
    cloth &= merged[..., 3] > 200
    # Only the ball side. The jersey between the two arms is not a shard,
    # and a profile keeps both arms close enough to trip a looser test.
    side = _ball_side(direction)
    cx = float(g.head_cx)
    hits = 0
    band = cloth & (yy > g.neck + 2) & (yy < g.hem - 1)
    ys, xs = np.nonzero(band)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if (float(x) - cx) * side <= 0.0:
            continue
        left = right = False
        for d in range(1, 4):
            if x - d >= 0 and skin[y, x - d] and (float(x - d) - cx) * side > 0.0:
                left = True
            if x + d < w and skin[y, x + d] and (float(x + d) - cx) * side > 0.0:
                right = True
        if left and right:
            hits += 1
    if hits < 4:
        return ""
    return f"{hits}px navy shard in the arm"


def _rear_skin(merged: np.ndarray, g: Geometry, direction: str) -> int:
    """Skin pixels past the rear edge of the torso. That is an arm out the back."""
    fx = _FACE[direction][0]
    if fx == 0.0 or direction not in PROFILE:
        return 0
    h, w = merged.shape[:2]
    yy = np.arange(h)[:, None]
    skin = _skin_mask_flat(merged)
    skin &= (yy > g.neck + 2) & (yy < g.hem - 1)
    rgb = merged[..., :3]
    cloth = np.zeros((h, w), dtype=bool)
    for col in (
        JERSEY_LIGHT, JERSEY_MID, JERSEY_SHADOW,
        SHORTS_LIGHT, SHORTS_MID, SHORTS_SHADOW, ORANGE,
    ):
        cloth |= (
            (rgb[..., 0] == int(col[0]))
            & (rgb[..., 1] == int(col[1]))
            & (rgb[..., 2] == int(col[2]))
        )
    cloth &= merged[..., 3] > 200
    n = 0
    xs = np.arange(w)
    for y in range(int(g.neck) + 2, int(g.hem)):
        row = np.nonzero(cloth[y])[0]
        if len(row) < 4:
            continue
        if fx > 0.0:
            edge = int(row.min())
            n += int((skin[y] & (xs < edge - 1)).sum())
        else:
            edge = int(row.max())
            n += int((skin[y] & (xs > edge + 1)).sum())
    return n


def facing_fault(merged: np.ndarray, g: Geometry, bx: float, by: float,
                 hx: float, hy: float, direction: str) -> str:
    """Hand and ball must lead the body along the facing vector.

    E is +x, NE is +x and -y (up the screen), N is -y. A component that
    the facing vector leaves at 0 is free, so a south dribble can sit to
    one side as long as it is in front of him. Skin past the rear edge of
    a side-view torso is an arm sticking out of his back.
    """
    h, w = merged.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ball = (xx - bx) ** 2 + (yy - by) ** 2 <= (BALL_R + 2.0) ** 2
    # Chest and shorts, not the legs. A hand on a low dribble is still in
    # front of the torso even when the feet pull the full-body centre down.
    body = (merged[..., 3] > 200) & ~ball & (yy > g.neck) & (yy < g.hem)
    ys, xs = np.nonzero(body)
    if len(xs) < 40:
        return ""
    cx = float(xs.mean())
    cy = float(ys.mean())
    fx, fy = _FACE[direction]
    bits = []
    dx = bx - cx
    dy = by - cy
    if fx != 0.0 and dx * fx < 6.0:
        bits.append(f"ball dx {dx:.1f} against {fx:+.0f}")
    if fy != 0.0 and dy * fy < 4.0:
        bits.append(f"ball dy {dy:.1f} against {fy:+.0f}")
    hdx = hx - cx
    hdy = hy - cy
    if fx != 0.0 and hdx * fx < 0.0:
        bits.append(f"hand dx {hdx:.1f} against {fx:+.0f}")
    if fy != 0.0 and hdy * fy < 0.0:
        bits.append(f"hand dy {hdy:.1f} against {fy:+.0f}")
    rear = _rear_skin(merged, g, direction)
    if rear > 6:
        bits.append(f"{rear}px arm behind the back")
    if not bits:
        return ""
    return f"({dx:+.1f},{dy:+.1f}) " + ", ".join(bits)


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
    problems: list[str] = []
    for r, direction in enumerate(dirs):
        for c in range(cols):
            anim, index = anim_of(c, meta)
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            cell, kept, holes, ball_xy = compose(fr, direction, anim, index)
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = cell
            if not alpha_mask(pad_frame(fr)).any():
                continue
            g = Geometry(pad_frame(fr))
            bx, by, hx, hy = ball_xy
            arms = count_arms(cell, g)
            off = palette_off(cell, g, bx, by)
            specks = isolated_speckles(cell, g, bx, by)
            green = green_pixels(cell, g, bx, by)
            # the filled chest must stay opaque
            open_chest = int((kept & (cell[..., 3] <= 40)).sum())
            facing = facing_fault(cell, g, bx, by, hx, hy, direction)
            shard = arm_shard(cell, g, direction)
            if arms > 2 or off or specks or green or holes or open_chest or facing or shard:
                problems.append(
                    f"{direction} {anim} {index} (col {c}): "
                    f"{arms} arms, {off} off-palette, {specks} speckles, "
                    f"{green} green, {open_chest} chest holes"
                    + (f", {facing}" if facing else "")
                    + (f", {shard}" if shard else "")
                )
    if problems:
        print("frame check failed:")
        for line in problems[:40]:
            print(" ", line)
        print(f"  ({len(problems)} frames)")
        raise SystemExit(1)
    print(f"frame check ok ({len(dirs) * cols} frames: arms <= 2, palette, facing, no shards)")
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
