#!/usr/bin/env python3
"""Slice the kid presentation spritesheet into a clean Phaser spritesheet.

Source: tools/kid_sheet_source.png (1536x1024 presentation sheet with labels,
cell panels, borders and a notes footer).

Output: public/assets/kid.png - a grid of FRAME_W x FRAME_H frames,
30 columns x 8 rows. Column layout (per row):
    0-3   idle      (4)  one clean standing frame (static)
    4-11  walk      (8)
    12-15 breathing (4)  standing frame with a 1px chest rise (runtime idle)
    16-21 tag       (6)
    22-29 run       (8)  generated (the sheet has no run frames)
Row layout (runtime direction order, matching angle buckets from atan2 in
screen space, 0 = east, increasing clockwise):
    0 E, 1 SE, 2 S, 3 SW, 4 W, 5 NW, 6 N, 7 NE

Also writes public/assets/kid.json with the frame metadata.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/slice_kid_sheet.py [--preview /tmp/preview.png] [--debug DIR]
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "kid_sheet_source.png"
OUT_DIR = HERE.parent / "public" / "assets"

# ---------------------------------------------------------------------------
# Measured layout of the 1536x1024 source sheet (pixel coordinates).
# Row bands are the inner panels between the horizontal border lines.
ROW_BANDS = [  # (y0, y1) exclusive end, per sheet row
    (87, 181),   # N
    (187, 283),  # NE
    (289, 387),  # E
    (393, 495),  # SE
    (502, 600),  # S
    (607, 707),  # SW
    (713, 812),  # W
    (818, 914),  # NW
]
SHEET_ROWS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
# Animation column groups: (name, x0, x1, frame count)
GROUPS = [
    ("idle", 77, 393, 4),
    ("walk", 402, 886, 8),
    ("breathe", 891, 1131, 4),
    ("tag", 1140, 1522, 6),
]

# Which sheet rows feed each runtime direction.
#
# The sheet is an AI-style presentation sheet and is NOT consistent with its
# own labels, so the sources below were picked by inspecting every frame:
#  * every side-view row (NE, E, SE, SW, W, NW) is drawn facing LEFT in the
#    idle/walk/breathing columns (the sheet's own note says to mirror the
#    west-facing rows to get the east-facing ones);
#      - row "E"  = clean left profile            -> W  (mirrored: E)
#      - row "SW" = back-3/4, facing left          -> NW (mirrored: NE)
#  * there is NO front-three-quarter view anywhere in the sheet: every frame
#    in the rows labelled SE / SW / W (and the few right-facing frames in the
#    SE row) is a pure profile.  So SE / SW are built from the S (front)
#    frames with a "head turn" warp (see turn_warp) that slides the face and
#    body towards the facing side, then mirrored for SW.  This reads as a
#    kid facing down-right / down-left toward the camera instead of a profile;
#  * in the TAG columns the arm always swings out to the viewer's RIGHT and
#    the body faces RIGHT in the arm-out frames, while the first/last frames
#    of several rows face the other way.  So each direction gets a hand-picked
#    frame sequence (sheet tag-frame indices 0..5) whose body faces the same
#    way as the arm; west-facing directions are mirrored so the arm always
#    reaches out in FRONT of the kid.  For SE/SW the front-view S tag frames
#    are used (arm out to the facing side), with the same turn warp.
#    Sequence shape: neutral, bent (wind-up), extended, MOST extended, extended, bent.
#
# The optional 3rd/4th value is the turn-warp strength (+ = turn towards the
# viewer's right, applied before mirroring).
TURN = 0.32
BODY_SOURCES = {
    # dir: (sheet row, mirror, turn)
    "E": ("E", True, 0.0),
    "SE": ("S", False, TURN),
    "S": ("S", False, 0.0),
    "SW": ("S", True, TURN),
    "W": ("E", False, 0.0),
    "NW": ("SW", False, 0.0),
    "N": ("N", False, 0.0),
    "NE": ("SW", True, 0.0),
}
TAG_SOURCES = {
    # dir: (sheet row, [tag frame indices], mirror, turn)
    "E": ("E", [0, 2, 1, 3, 1, 2], False, 0.0),
    "SE": ("S", [0, 2, 1, 3, 1, 2], False, TURN),
    "S": ("S", [0, 2, 1, 3, 1, 2], False, 0.0),
    "SW": ("S", [0, 2, 1, 3, 1, 2], True, TURN),
    "W": ("E", [0, 2, 1, 3, 1, 2], True, 0.0),
    "NW": ("NW", [0, 2, 3, 1, 4, 2], True, 0.0),
    "N": ("N", [0, 2, 3, 1, 4, 2], False, 0.0),
    "NE": ("NW", [0, 2, 3, 1, 4, 2], False, 0.0),
}
# Output columns per row (the sheet has no run frames; they are generated).
OUT_GROUPS = [("idle", 4), ("walk", 8), ("breathe", 4), ("tag", 6), ("run", 8)]
# Sheet rows whose walk / run are generated with front_cycle (see below).
FRONT_WALK_ROWS = {"S"}
FRONT_RUN_ROWS = {"S", "N"}
DIRECTIONS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]

FRAME_W = 80
FRAME_H = 100
BASELINE_Y = FRAME_H - 4   # feet rest on this row (exclusive bottom of art)
ANCHOR_X = FRAME_W // 2    # head centre is placed on this column
TARGET_H = 89              # normalise figure height (sheet rows vary 85-93px)

# Background keying parameters.
LOOSE_DIST = 18     # first pass: distance to the panel colour (for bg estimate)
TIGHT_DIST = 16     # bg flood: distance to the *local* smoothed background
STRONG_DIST = 30    # definitely-kid pixels
CLOSE_R = 3         # closing radius for the strong-pixel barrier
UPPER_FRAC = 0.6    # top fraction of a band that is keyed without the barrier
HOLE_DIST = 7       # enclosed pockets this close to the local bg become holes
MIN_HOLE = 10
MIN_PART = 80       # drop stray specks smaller than this (in pixels)
BLUR_R = 7          # box radius used to estimate the local background


def color_dist(a: np.ndarray, ref: np.ndarray) -> np.ndarray:
    return np.sqrt(((a - ref) ** 2).sum(-1))


def flood(cand: np.ndarray, seeds) -> np.ndarray:
    h, w = cand.shape
    seen = np.zeros_like(cand, dtype=bool)
    q = deque()
    for y, x in seeds:
        if cand[y, x] and not seen[y, x]:
            seen[y, x] = True
            q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and cand[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def edge_seeds(h: int, w: int):
    return ([(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)]
            + [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)])


def components(mask: np.ndarray) -> list[np.ndarray]:
    """8-connected components, returned as boolean masks."""
    h, w = mask.shape
    labels = np.zeros(mask.shape, dtype=np.int32)
    out = []
    n = 0
    for sy, sx in zip(*np.nonzero(mask)):
        if labels[sy, sx]:
            continue
        n += 1
        labels[sy, sx] = n
        q = deque([(sy, sx)])
        while q:
            y, x = q.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = n
                        q.append((ny, nx))
        out.append(labels == n)
    return out


def box_sum(a: np.ndarray, r: int) -> np.ndarray:
    """Sum over a (2r+1)^2 window (edge-clamped) using an integral image."""
    pad = np.pad(a, [(r + 1, r)] + [(r + 1, r)] + [(0, 0)] * (a.ndim - 2), mode="edge")
    c = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    return box_sum(m.astype(np.int32), r) > 0


def erode(m: np.ndarray, r: int) -> np.ndarray:
    return box_sum(m.astype(np.int32), r) == (2 * r + 1) ** 2


def key_region(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (foreground mask, local-background distance) for a band region."""
    h, w, _ = rgb.shape
    rgbf = rgb.astype(np.float64)
    # 1) Rough background: flood from the region edge over pixels close to
    #    the panel colour (median of the region border ring).
    r_, g_, b_ = rgbf[..., 0], rgbf[..., 1], rgbf[..., 2]
    navy = (r_ < 30) & (b_ - r_ >= 10) & (r_ + g_ + b_ < 130)
    ref = np.median(rgbf[navy], axis=0)
    rough = flood(color_dist(rgbf, ref) < LOOSE_DIST, edge_seeds(h, w))
    # 2) Smooth local background estimate from the rough bg pixels only
    #    (normalised box blur), so panel gradients/glows are followed.
    known = erode(rough, 1) & ~dilate(~rough, 3)
    wsum = box_sum(known.astype(np.float64), BLUR_R)
    csum = box_sum(rgbf * known[..., None], BLUR_R)
    wbig = box_sum(known.astype(np.float64), BLUR_R * 4)
    cbig = box_sum(rgbf * known[..., None], BLUR_R * 4)
    bgimg = np.where(
        (wsum > 8)[..., None],
        csum / np.maximum(wsum, 1)[..., None],
        np.where((wbig > 0)[..., None], cbig / np.maximum(wbig, 1)[..., None], ref),
    )
    d = color_dist(rgbf, bgimg)
    # The outer 2px of the region may touch the panel border lines: treat
    # it as background so figures never get glued to the border.
    edge = np.ones((h, w), dtype=bool)
    edge[2:-2, 2:-2] = False
    d[edge] = 0.0
    # 3) Barrier: pixels that are clearly the kid (far from the local bg),
    #    morphologically closed and hole-filled.  The dark navy shorts/shoes
    #    are close to the bg colour and their outline is not always closed,
    #    so the flood fill must not be allowed to leak through small gaps.
    strong = d > STRONG_DIST
    barrier = erode(dilate(strong, CLOSE_R), CLOSE_R)
    barrier |= ~flood(~barrier, edge_seeds(h, w))
    # 4) Flood fill the background from the edges against the local bg.
    #    Above the shorts (head, shirt, outstretched arm) there are no
    #    bg-like colours in the art, so the barrier is not needed there; this
    #    peels out concave bg corners such as chin/arm gaps in the tag frames.
    upper = np.zeros((h, w), dtype=bool)
    upper[: int(h * UPPER_FRAC)] = True
    bg = flood((d < TIGHT_DIST) & (~barrier | upper), edge_seeds(h, w))
    fg = ~bg
    # 5) Fill holes, then re-open genuine enclosed background pockets.
    outside = flood(~fg, edge_seeds(h, w))
    fg |= ~outside
    pocket = fg & ~strong & (d < HOLE_DIST)
    for comp in components(pocket):
        if comp.sum() >= MIN_HOLE:
            fg &= ~comp
    fg &= ~edge
    return fg, d


def extract_frames(img: np.ndarray, debug: Path | None):
    """Returns {sheet_row: {group: [ (rgba crop, anchor_x, bottom) ...]}}"""
    result = {}
    for row_name, (y0, y1) in zip(SHEET_ROWS, ROW_BANDS):
        result[row_name] = {}
        for gname, x0, x1, count in GROUPS:
            region = img[y0:y1, x0:x1]
            fg, _d = key_region(region)
            comps = []
            for c in components(fg):
                ys, xs = np.nonzero(c)
                if c.sum() < MIN_PART or xs.max() - xs.min() <= 3:
                    continue  # specks and thin border/separator lines
                comps.append((c, xs.min(), xs.max() + 1, c.sum()))
            # Cluster components by horizontal overlap -> one figure each.
            comps.sort(key=lambda t: t[1])
            clusters: list[list] = []
            for c, l, r, n in sorted(comps, key=lambda t: -t[3]):
                for cl in clusters:
                    ov = min(r, cl[2]) - max(l, cl[1])
                    if ov > 0.5 * min(r - l, cl[2] - cl[1]) or (n < 300 and ov > -2):
                        cl[0] |= c
                        cl[1], cl[2] = min(l, cl[1]), max(r, cl[2])
                        break
                else:
                    clusters.append([c.copy(), l, r])
            clusters = [cl for cl in clusters if cl[0].sum() > 600]
            clusters.sort(key=lambda cl: cl[1])
            if len(clusters) != count:
                raise SystemExit(
                    f"{row_name}/{gname}: expected {count} figures, found {len(clusters)}"
                    f" {[(cl[1], cl[2], int(cl[0].sum())) for cl in clusters]}"
                )
            masks = [cl[0] for cl in clusters]
            frames = []
            for i, m in enumerate(masks):
                ys, xs = np.nonzero(m)
                top, bottom = ys.min(), ys.max() + 1
                left, right = xs.min(), xs.max() + 1
                # Horizontal anchor = centre of the head (top 35% of figure),
                # which stays put even when the arm swings out in the tag anim.
                head_rows = m[top: top + int((bottom - top) * 0.35)]
                hy, hx = np.nonzero(head_rows)
                anchor = float(hx.mean())
                rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
                rgba[..., :3] = region
                rgba[..., 3] = np.where(m, 255, 0)
                crop = rgba[top:bottom, left:right]
                frames.append((crop, anchor - left, bottom - top))
                if debug:
                    Image.fromarray(crop).save(debug / f"{row_name}_{gname}_{i}.png")
            result[row_name][gname] = frames
    return result


TURN_RADIUS = 24.0   # px (source scale) around the head centre affected by the warp
TURN_BODY = 0.55     # warp strength at the feet relative to the head


def turn_warp(crop: np.ndarray, anchor_x: float, k: float) -> np.ndarray:
    """Fake a slight head/body turn towards +x on a front-view frame.

    Each row is remapped with x' = x + k*R*(1-u^2), u = (x-anchor)/R, |u|<1:
    the edges of the figure stay put while the middle (face, shirt front)
    slides toward the facing side, compressing the near side and widening
    the far side, like a three-quarter view.  Strength fades from the head
    (k) to the feet (k*TURN_BODY).  Resampled with premultiplied alpha.
    """
    h, w = crop.shape[:2]
    f = crop.astype(np.float64) / 255.0
    f[..., :3] *= f[..., 3:4]
    out = np.zeros_like(f)
    xs = np.arange(w, dtype=np.float64)
    dense = np.linspace(-1.0, w, (w + 1) * 8)
    for y in range(h):
        t = y / max(1, h - 1)
        ky = k * (1.0 if t < 0.45 else 1.0 - (1.0 - TURN_BODY) * (t - 0.45) / 0.55)
        u = (dense - anchor_x) / TURN_RADIUS
        fwd = dense + np.where(np.abs(u) < 1, ky * TURN_RADIUS * (1 - u * u), 0.0)
        src = np.interp(xs, fwd, dense)
        for ch in range(4):
            out[y, :, ch] = np.interp(src, xs, f[y, :, ch], left=0.0, right=0.0)
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Procedural animation helpers.  These work on placed (unmirrored, unturned)
# FRAME_W x FRAME_H RGBA frames whose head centre is at ANCHOR_X and whose
# feet rest on BASELINE_Y.
#
# The sheet's own walk frames for the front view barely differ from each
# other, and its breathing frames shift pose from frame to frame (so the
# idle loop looked like walking on the spot).  So:
#   * idle/breathing = one clean standing frame per direction with a 1px
#     chest rise (breathe_loop);
#   * front-facing walk (S, and SE/SW which are warped from S) and the
#     front/back run (S, N) are generated from that standing frame by
#     cutting it into legs (below the shorts hem, split between the legs)
#     and arms (skin below the sleeves, beside the torso) and re-posing
#     them per frame (front_cycle);
#   * side / back-three-quarter runs exaggerate the stride frames of the
#     sheet's walk: wider stride, ~2.4x arm swing, forward lean and a
#     flight-phase hop (profile_run).

def _alpha(f: np.ndarray) -> np.ndarray:
    return f[..., 3] > 40


def _skin(f: np.ndarray) -> np.ndarray:
    r, g, b = (f[..., i].astype(np.int32) for i in range(3))
    return _alpha(f) & (r > 150) & (r - b > 60) & (g > 80) & (g < r)


def _cloth(f: np.ndarray) -> np.ndarray:
    """Shirt / shorts pixels: low saturation, not near-black outline or skin."""
    rgb = f[..., :3].astype(np.int32)
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    return _alpha(f) & (mx - mn < 45) & (mx > 38) & (mx < 170)


def find_hem(f: np.ndarray) -> int:
    """First row of the bare legs below the shorts.

    Found from the feet up: the first skin rows above the shoes are the
    shins; their top is the shorts hem.  (Clamped so a hand touching the
    shins can't drag it up into the torso.)
    """
    sk = _skin(f)
    sk[:, :ANCHOR_X - 16] = False
    sk[:, ANCHOR_X + 17:] = False
    rows = sk.sum(axis=1) >= 2
    bottom = _bottom(f)
    y = bottom
    while y > bottom - 25 and not rows[y]:
        y -= 1
    while y > bottom - 16 and rows[y - 1]:
        y -= 1
    return y


def _bottom(f: np.ndarray) -> int:
    rows = np.nonzero(_alpha(f).any(axis=1))[0]
    return int(rows[-1])


def _premul(f: np.ndarray) -> np.ndarray:
    x = f.astype(np.float64) / 255.0
    x[..., :3] *= x[..., 3:4]
    return x


def _unpremul(x: np.ndarray) -> np.ndarray:
    out = x.copy()
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _over(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    return src + dst * (1.0 - src[..., 3:4])


def _sample(img: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    """Bilinear sample a premultiplied image at float coords (0 outside)."""
    h, w = img.shape[:2]
    x0 = np.floor(sx).astype(int)
    y0 = np.floor(sy).astype(int)
    fx = (sx - x0)[..., None]
    fy = (sy - y0)[..., None]
    out = np.zeros(sx.shape + (4,))
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            xi = x0 + dx
            yi = y0 + dy
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            v = np.zeros(sx.shape + (4,))
            v[ok] = img[yi[ok], xi[ok]]
            out += v * wx * wy
    return out


def _remap(layer: np.ndarray, t0: float, t1: float, u0: float, u1: float,
           cx: float = 0.0, sx: float = 1.0, d0: float = 0.0, d1: float = 0.0) -> np.ndarray:
    """Move rows [t0, t1) of a premultiplied layer to [u0, u1) (stretching),
    scale horizontally by sx around cx and shear by d0 (top) .. d1 (bottom)."""
    h, w = layer.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    t = (yy + 0.5 - u0) / max(1e-6, (u1 - u0))
    src_y = t0 + t * (t1 - t0) - 0.5
    shift = d0 + (d1 - d0) * np.clip(t, 0, 1)
    src_x = cx + (xx - shift - cx) / sx
    out = _sample(layer, src_x, src_y)
    inside = (t >= 0) & (t < 1)
    out[~inside] = 0.0
    return out


def _shift_rows(layer: np.ndarray, dy: int) -> np.ndarray:
    out = np.zeros_like(layer)
    if dy < 0:
        out[:dy] = layer[-dy:]
    elif dy > 0:
        out[dy:] = layer[:-dy]
    else:
        out[:] = layer
    return out


def _components8(mask: np.ndarray) -> list[np.ndarray]:
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        comp = np.zeros_like(mask, dtype=bool)
        q = deque([(y, x)])
        seen[y, x] = True
        while q:
            cy, cx = q.popleft()
            comp[cy, cx] = True
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
        comps.append(comp)
    return comps


def _grow(mask: np.ndarray, within: np.ndarray, r: int = 1) -> np.ndarray:
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g & within
    return m


def front_parts(f: np.ndarray):
    """Split a front (or back) view standing frame into body, legs and arms."""
    a = _alpha(f)
    hem = find_hem(f)
    bottom = _bottom(f)
    xs = np.arange(FRAME_W)
    # the gap between the legs: darkest / emptiest column near the centre
    region = _premul(f)[hem:bottom + 1]
    score = (region[..., :3].mean(axis=2) * region[..., 3]).sum(axis=0)
    cand = range(ANCHOR_X - 5, ANCHOR_X + 6)
    gap = min(cand, key=lambda x: score[x])
    legs = np.zeros_like(a)
    legs[hem:] = a[hem:]
    left_leg = legs & (xs[None, :] <= gap)
    right_leg = legs & (xs[None, :] > gap)
    # arms: skin under the sleeves beside the torso, plus their dark outline
    skin = _skin(f)
    zone = np.zeros_like(a)
    zone[48:hem] = True
    zone &= np.abs(xs[None, :] - ANCHOR_X) >= 8
    arms = []
    for side in (-1, 1):
        cand_m = skin & zone & ((xs[None, :] - ANCHOR_X) * side > 0)
        comps = sorted(_components8(cand_m), key=lambda c: -c.sum())
        if not comps:
            arms.append(np.zeros_like(a))
            continue
        arm = comps[0]
        # grow into the hand's outline and shading (anything that isn't cloth)
        arm = arm | _grow(arm, a & ~_cloth(f) & zone, 3)
        arms.append(arm)
    body = a & ~legs & ~arms[0] & ~arms[1]
    return dict(hem=hem, bottom=bottom, gap=gap, body=body, legs=(left_leg, right_leg), arms=tuple(arms))


WALK_FRONT = dict(lift=3.5, fwd=1.5, grow=0.06, bob=1, arm_up=0.3, arm_in=1.5, arm_out=2.0, arm_bend=0.0)
RUN_FRONT = dict(lift=7.0, fwd=3.0, grow=0.12, bob=2, arm_up=0.5, arm_in=3.0, arm_out=5.0, arm_bend=0.15)


def front_cycle(base: np.ndarray, p: dict, n: int = 8) -> list[np.ndarray]:
    """Alternating stride for a front/back view built from one standing frame.

    phase 0: left leg forward (lower, a bit bigger), right leg back;
    then the back leg lifts (shorter) as it passes; arms swing opposite to
    the legs (the forward arm foreshortens upward and in, the back arm swings
    out); the body is highest while a leg passes.
    """
    parts = front_parts(base)
    pm = _premul(base)
    hem, bottom = parts["hem"], parts["bottom"]
    layer = lambda m: pm * m[..., None]
    body = layer(parts["body"])
    legs = [layer(m) for m in parts["legs"]]
    arms = [layer(m) for m in parts["arms"]]
    leg_cx = [np.nonzero(m.any(axis=0))[0].mean() if m.any() else ANCHOR_X for m in parts["legs"]]
    frames = []
    for i in range(n):
        ph = 2 * np.pi * i / n
        fwd = [np.cos(ph), -np.cos(ph)]                      # +1 = forward (toward camera)
        lift = [p["lift"] * max(0.0, -np.sin(ph)), p["lift"] * max(0.0, np.sin(ph))]
        bob = -int(round(p["bob"] * abs(np.sin(ph))))
        out = np.zeros_like(pm)
        order = sorted(range(2), key=lambda k: fwd[k])        # back leg first
        for k in order:
            u1 = bottom + 1 - lift[k] + p["fwd"] * fwd[k]
            out = _over(out, _remap(legs[k], hem, bottom + 1, hem + bob, u1,
                                    cx=leg_cx[k], sx=1 + p["grow"] * fwd[k]))
        out = _over(out, _shift_rows(body, bob))
        for k, side in enumerate((-1, 1)):
            m = parts["arms"][k]
            if not m.any():
                continue
            rows = np.nonzero(m.any(axis=1))[0]
            a0, a1 = rows[0], rows[-1] + 1
            s = -fwd[k]                                       # arms opposite to legs
            length = a1 - a0
            if s >= 0:
                u1 = a1 - length * (p["arm_up"] * s + p["arm_bend"])
                d1 = -side * p["arm_in"] * s
            else:
                u1 = a1 - length * (0.3 * p["arm_up"] * -s + p["arm_bend"])
                d1 = side * p["arm_out"] * -s
            cx = np.nonzero(m.any(axis=0))[0].mean()
            out = _over(out, _remap(arms[k], a0, a1, a0 + bob, u1 + bob, cx=cx, d0=0.0, d1=d1))
        frames.append(clean_specks(_unpremul(out)))
    return frames


def breathe_loop(base: np.ndarray) -> list[np.ndarray]:
    """Calm idle: the upper body rises 1px and settles, legs stay planted."""
    hem, bottom = find_hem(base), _bottom(base)
    pm = _premul(base)
    a = _alpha(base)
    upper = np.zeros_like(a)
    upper[:hem] = a[:hem]
    out = []
    for bob in (0, -1, -1, 0):
        legs = _remap(pm * (~upper)[..., None], hem, bottom + 1, hem + bob, bottom + 1)
        frame = _over(legs, _shift_rows(pm * upper[..., None], bob))
        out.append(_unpremul(frame))
    return out


def medoid(frames: list[np.ndarray]) -> np.ndarray:
    """The frame most similar to all the others (a neutral standing pose)."""
    al = [_alpha(f) for f in frames]
    cost = [sum(np.sum(x ^ y) for y in al) for x in al]
    return frames[int(np.argmin(cost))]


def _inpaint_rows(layer: np.ndarray, hole: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Fill the hole a moved arm leaves in the torso.

    Each hole pixel gets the median cloth colour of its row (plain shirt or
    shorts, no smears); pixels outside the torso become transparent.
    """
    out = layer.copy()
    cloth = _cloth(src) & ~hole
    keep_a = (layer[..., 3] > 0.15) & ~hole
    outline = np.array([0.08, 0.07, 0.09, 1.0])
    for y in np.nonzero(hole.any(axis=1))[0]:
        kx = np.nonzero(keep_a[y])[0]
        if not len(kx):
            continue
        near = cloth[max(0, y - 2):y + 3]
        if cloth[y].any():
            col = np.median(layer[y][cloth[y]], axis=0)
        elif near.any():
            col = np.median(layer[max(0, y - 2):y + 3][near], axis=0)
        else:
            col = outline
        for x in np.nonzero(hole[y])[0]:
            if kx.min() < x < kx.max():
                out[y, x] = col
            else:
                out[y, x] = 0
    return out


PROFILE_RUN = dict(stride=0.9, arm=1.4, lean=3.0, hop=2)
# The sheet's side / back-3/4 walk rows are one stride plus standing frames,
# so the run loops the stride frames only (hand-picked, sheet walk indices).
RUN_FROM_WALK = {
    "E": [2, 3, 4, 5, 2, 3, 4, 5],
    "SW": [2, 3, 4, 5, 2, 3, 4, 5],
}


def _row_segments(row_alpha: np.ndarray):
    segs = []
    x = 0
    w = len(row_alpha)
    while x < w:
        if row_alpha[x]:
            x0 = x
            while x < w and row_alpha[x]:
                x += 1
            segs.append((x0, x))
        else:
            x += 1
    return segs


def profile_run(walk: list[np.ndarray], facing: int, p: dict = PROFILE_RUN) -> list[np.ndarray]:
    """Run frames from side / back-3/4 walk frames (facing -1 = left).

    Exaggerates each walk frame: every row segment of the legs is pushed away
    from the hip (more toward the feet) for a wider stride, the near arm
    (skin under the sleeve) is sheared about the shoulder so the hand swings
    ~2.4x as far, the upper body leans into the run, and the narrowest
    (passing) frames hop up as the flight phase.
    """
    widths = []
    for f in walk:
        hem, bottom = find_hem(f), _bottom(f)
        m = _alpha(f)[hem - 4:bottom + 1]
        xs_ = np.nonzero(m)[1]
        widths.append(float(xs_.std()) if len(xs_) else 0.0)
    wmin, wmax = min(widths), max(widths)
    out = []
    for f, wdt in zip(walk, widths):
        f = clean_specks(f)
        a = _alpha(f)
        hem, bottom = find_hem(f), _bottom(f)
        pm = _premul(f)
        res = np.zeros_like(pm)
        # --- legs: push each row segment away from the hip, more toward the feet
        hip_cols = np.nonzero(a[hem])[0]
        hip = hip_cols.mean() if len(hip_cols) else ANCHOR_X
        for y in range(hem, bottom + 1):
            t = (y - hem) / max(1, bottom - hem)
            for x0, x1 in _row_segments(a[y]):
                c = (x0 + x1 - 1) / 2
                dx = int(round(p["stride"] * (c - hip) * t))
                lo, hi = max(0, x0 + dx), min(FRAME_W, x1 + dx)
                res[y, lo:hi] = pm[y, lo - dx:hi - dx]
        # --- upper body: bigger arm swing, then lean forward
        upper = pm.copy()
        upper[hem:] = 0
        zone = np.zeros_like(a)
        zone[52:min(FRAME_H, hem + 6)] = True
        comps = sorted(_components8(_skin(f) & zone), key=lambda c: -c.sum())
        if comps and comps[0].sum() >= 6:
            arm = comps[0] | _grow(comps[0], a & ~_cloth(f) & zone, 1)
            rows = np.nonzero(arm.any(axis=1))[0]
            a0, a1 = rows[0], rows[-1]
            tcols = np.nonzero(a[a0:hem].any(axis=0))[0]
            shoulder = (tcols[0] + tcols[-1]) / 2 if len(tcols) else ANCHOR_X
            swing = np.nonzero(arm[a1])[0].mean() - shoulder
            arm_layer = pm * arm[..., None]
            upper = _inpaint_rows(upper * (~arm)[..., None], arm & (np.arange(FRAME_H)[:, None] < hem), f)
            yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W].astype(np.float64)
            t = np.clip((yy - a0) / max(1, a1 - a0), 0, 1)
            moved = _sample(arm_layer, xx - p["arm"] * swing * t, yy)
            moved[min(FRAME_H, a1 + 2):] = 0
            upper = _over(upper, moved)
        top = np.nonzero(a.any(axis=1))[0][0]
        yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W].astype(np.float64)
        lean = facing * p["lean"] * np.clip((hem - yy) / max(1, hem - top), 0, 1)
        res = _over(res, _sample(upper, xx - lean, yy))
        k = 0 if wmax == wmin else (wmax - wdt) / (wmax - wmin)
        res = _shift_rows(res, -int(round(p["hop"] * k)))
        out.append(clean_specks(_unpremul(res), 30))
    return out


def clean_specks(f: np.ndarray, min_size: int = 15) -> np.ndarray:
    """Drop tiny detached bits (sheet residue) so they don't get animated."""
    out = f.copy()
    for comp in _components8(_alpha(f)):
        if comp.sum() < min_size:
            out[comp] = 0
    out[f[..., 3] <= 40] = 0
    return out


def place(crop: np.ndarray, anchor_x: float, mirror: bool, scale: float) -> Image.Image:
    im = Image.fromarray(crop)
    if abs(scale - 1.0) > 0.01:
        w0, h0 = im.size
        size = (max(1, round(w0 * scale)), max(1, round(h0 * scale)))
        # Resample with premultiplied alpha so no dark fringes appear.
        im = im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
        anchor_x *= size[0] / w0
    w, h = im.size
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
        anchor_x = w - anchor_x
    frame = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    ox = int(round(ANCHOR_X - anchor_x))
    oy = BASELINE_Y - h
    if ox < 0 or oy < 0 or ox + w > FRAME_W:
        raise SystemExit(f"figure does not fit frame: ox={ox} oy={oy} w={w} h={h}")
    frame.paste(im, (ox, oy), im)
    return frame


def group_scale(frames) -> float:
    return TARGET_H / float(np.median([f[2] for f in frames]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    ap.add_argument("--debug", type=Path, help="dump raw per-frame crops here")
    args = ap.parse_args()
    if args.debug:
        args.debug.mkdir(parents=True, exist_ok=True)

    img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.int32)
    frames = extract_frames(img, args.debug)

    ncols = sum(n for _g, n in OUT_GROUPS)
    sheet = Image.new("RGBA", (FRAME_W * ncols, FRAME_H * len(DIRECTIONS)))

    def placed(row: str, group: str) -> list[np.ndarray]:
        src = frames[row][group]
        scale = group_scale(src)
        return [np.asarray(place(c.astype(np.uint8), ax, False, scale)) for c, ax, _h in src]

    def finish(f: np.ndarray, mirror: bool, turn: float) -> Image.Image:
        if turn:
            f = turn_warp(f, ANCHOR_X, turn)
        im = Image.fromarray(f)
        return im.transpose(Image.FLIP_LEFT_RIGHT) if mirror else im

    for r, direction in enumerate(DIRECTIONS):
        body_row, body_mirror, body_turn = BODY_SOURCES[direction]
        tag_row, tag_idx, tag_mirror, tag_turn = TAG_SOURCES[direction]
        base = clean_specks(medoid(placed(body_row, "breathe")))
        sheet_walk = placed(body_row, "walk")
        walk = front_cycle(base, WALK_FRONT) if body_row in FRONT_WALK_ROWS else sheet_walk
        if body_row in FRONT_RUN_ROWS:
            run = front_cycle(base, RUN_FRONT)
        else:
            pick = RUN_FROM_WALK[body_row]
            run = profile_run([sheet_walk[i] for i in pick], facing=-1)  # these sources face left
        tag = placed(tag_row, "tag")
        seqs = {
            "idle": ([base] * 4, body_mirror, body_turn),
            "walk": (walk, body_mirror, body_turn),
            "breathe": (breathe_loop(base), body_mirror, body_turn),
            "tag": ([tag[i] for i in tag_idx], tag_mirror, tag_turn),
            "run": (run, body_mirror, body_turn),
        }
        c = 0
        for gname, count in OUT_GROUPS:
            seq, mirror, turn = seqs[gname]
            assert len(seq) == count, (direction, gname, len(seq))
            for f in seq:
                sheet.paste(finish(f, mirror, turn), (c * FRAME_W, r * FRAME_H))
                c += 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_DIR / "kid.png", optimize=True)

    meta = {
        "image": "kid.png",
        "frameWidth": FRAME_W,
        "frameHeight": FRAME_H,
        "baselineY": BASELINE_Y,
        "anchorX": ANCHOR_X,
        "columns": ncols,
        "directions": DIRECTIONS,
        "animations": {},
    }
    c = 0
    for gname, count in OUT_GROUPS:
        meta["animations"][gname] = {"start": c, "count": count}
        c += count
    (OUT_DIR / "kid.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {OUT_DIR / 'kid.png'} ({sheet.size[0]}x{sheet.size[1]})")

    if args.preview:
        from PIL import ImageDraw
        scale = 2
        pad = 40
        bgc = (110, 160, 110, 255)  # light green so transparency issues show
        pv = Image.new("RGBA", (pad + sheet.size[0] * scale, pad + sheet.size[1] * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(DIRECTIONS)):
            for col in range(ncols):
                x = pad + col * FRAME_W * scale
                y = pad + r * FRAME_H * scale
                cell = Image.new("RGBA", (FRAME_W, FRAME_H), bgc if (r + col) % 2 == 0 else (200, 200, 120, 255))
                fr = sheet.crop((col * FRAME_W, r * FRAME_H, (col + 1) * FRAME_W, (r + 1) * FRAME_H))
                cell.alpha_composite(fr)
                cd = ImageDraw.Draw(cell)
                cd.line([(0, BASELINE_Y), (FRAME_W, BASELINE_Y)], fill=(255, 0, 0, 255))
                cd.line([(ANCHOR_X, 0), (ANCHOR_X, 6)], fill=(255, 0, 0, 255))
                pv.paste(cell.resize((FRAME_W * scale, FRAME_H * scale), Image.NEAREST), (x, y))
            d.text((4, pad + r * FRAME_H * scale + 10), DIRECTIONS[r], fill="white")
        c = 0
        for gname, count in OUT_GROUPS:
            d.text((pad + c * FRAME_W * scale + 4, 12), gname, fill="white")
            c += count
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
