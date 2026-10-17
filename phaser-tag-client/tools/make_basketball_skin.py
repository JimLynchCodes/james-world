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
  6. an orange basketball with dark seams, dribbled on every frame. The
     ball sits in front of the legs (low on the screen, contact at or
     below the feet) with a ground shadow. The dribbling arm is redrawn
     from the shoulder onto the ball so the hand tracks the bounce. Seams
     turn 90 degrees per bounce. North views keep the ball just off the
     dribbling hand, still low and drawn over the body. The sleeve arm
     still reaches on the tag frames.

Face and hair (under the headband) are untouched. The tagging hand stays
the original skin; the dribbling arm is painted over the body.

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


# Bounce amount: 0 = up in the hand, 1 = on the ground in front of the feet.
# Every loop (including idle, which the skins card plays) shows the full
# dribble: hand on the ball, push down, contact, rebound.
def bounce_t(anim: str, index: int) -> float:
    if anim == "tag":
        # squash on the held reach (index 3); the sleeve arm is out tagging
        return (0.0, 0.48, 0.86, 1.0, 0.42, 0.12)[index]
    return (0.0, 0.58, 1.0, 0.30)[index % 4]


# Clockwise quarter-turn per bounce. The seam pattern is 90-degree
# symmetric, so the first frame of the next bounce matches the last step
# and the loop does not pop. Same direction in every facing.
SPIN_PER_BOUNCE = 90.0


def spin_deg(anim: str, index: int) -> float:
    if anim == "tag":
        return index * (SPIN_PER_BOUNCE / 6.0)
    return (index % 4) * (SPIN_PER_BOUNCE / 4.0)


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


def ball_layer(size, cx: float, cy: float, rx: float, ry: float, shadow: float,
               spin: float) -> np.ndarray:
    """Premultiplied basketball + a ground shadow. `shadow` is 0..1 strength.
    `spin` is degrees clockwise; only the seams turn (the highlight stays put)."""
    Y, X = grid(size)
    col = np.zeros((*Y.shape, 3), dtype=np.float64)
    alpha = np.zeros(Y.shape, dtype=np.float64)

    # contact shadow on the ground, under the ball, a hair in front of the feet
    if shadow > 0.02:
        sx = (X - cx) / (rx * (0.55 + 0.28 * shadow))
        sy = (Y - (GROUND + 1.5)) / 2.05
        sd = sx * sx + sy * sy
        sa = np.clip(1.2 - sd, 0.0, 1.0) * (0.28 + 0.55 * shadow)
        # don't let the shadow paint over the ball fill; ball wins later
        alpha = np.maximum(alpha, sa * 0.9)
        col = np.where(sa[..., None] > 0.04, INK, col)

    nx = (X - cx) / max(rx, 0.1)
    ny = (Y - cy) / max(ry, 0.1)
    r = np.hypot(nx, ny)
    # coverage in pixels (rx is the horizontal radius)
    aa = np.clip((1.04 - r) * min(rx, ry), 0.0, 1.0)
    inside = aa > 0.02
    # panel shading: left-lit, a little darker toward the bottom
    light = 0.78 + 0.28 * np.clip(0.55 - 0.65 * nx - 0.35 * ny, -0.35, 0.7)
    base = BALL * light[..., None]
    base = np.where((ny > 0.15)[..., None], base * 0.92 + BALL_DARK * 0.08, base)
    # specular on the upper-left
    spec = np.exp(-((nx + 0.38) ** 2 + (ny + 0.42) ** 2) / 0.08)
    base = base * (1 - 0.65 * spec[..., None]) + BALL_LIGHT * spec[..., None]
    col = np.where(inside[..., None], base, col)
    alpha = np.where(inside, np.maximum(alpha, aa), alpha)

    # seams in normalised ball space, so they follow the squash.
    # Sampled through a clockwise rotation. The motif itself (cross plus
    # four copied panel arcs) has 90-degree symmetry, so a quarter-turn
    # per bounce lands back on the same picture.
    ang = np.deg2rad(spin)
    ca, sa = np.cos(ang), np.sin(ang)
    px = nx * ca + ny * sa
    py = -nx * sa + ny * ca

    def seam(mask: np.ndarray) -> None:
        m = mask & (r < 0.96)
        col[m] = SEAM
        alpha[m] = np.maximum(alpha[m], aa[m])

    band = 0.072
    seam((np.abs(px) < band) | (np.abs(py) < band))
    for k in range(4):
        a = k * (np.pi / 2.0)
        c, s = np.cos(a), np.sin(a)
        qx = px * c + py * s
        qy = -px * s + py * c
        arc = np.abs(np.hypot(qx - 0.20, qy) - 0.68) < 0.055
        seam(arc & (qx > 0.22) & (np.abs(qy) < 0.70))
    # outline
    edge = inside & (r > 0.76)
    col[edge] = BALL_EDGE
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


def place_ball(g: Geometry, direction: str, anim: str, index: int) -> tuple[float, float, float, float]:
    """Ball in front of the kid: overlapping the legs, contact at or below
    the feet line (toward the camera). Back views shift it onto the
    dribbling-hand side so it isn't buried in the torso, but the contact
    stays on the near side of the feet."""
    side = -TAG_SIDE[direction]
    # screen-x of the direction he faces. Depth ("in front") is always +y.
    ahead = {"E": 1.0, "SE": 0.70, "S": 0.0, "SW": -0.70, "W": -1.0,
             "NW": -0.40, "N": 0.0, "NE": 0.40}[direction]
    t = bounce_t(anim, index)
    squashed = t > 0.92
    ry = BALL_R * (0.64 if squashed else 1.0)
    rx = BALL_R * (1.16 if squashed else 1.0)
    if direction in BACK:
        # just off the dribbling hand, still overlapping that leg
        bx = g.head_cx + side * 9.0 + ahead * 2.5
    elif direction in PROFILE:
        bx = g.head_cx + ahead * 3.5 + side * 2.0
    else:
        bx = g.head_cx + side * 3.5 + ahead * 3.0
    # unsquashed contact: bottom ~2px below the feet. The high point only
    # lifts a little, so the ball stays in front of the legs instead of
    # riding up beside the hip. Squash keeps the same bottom.
    contact_y = GROUND + 2.2
    cy_contact = contact_y - BALL_R
    lift = 6.0
    if squashed:
        cy = contact_y - ry
    else:
        cy = (cy_contact - lift) + lift * (t ** 1.05)
    margin = 1.0
    bx = float(np.clip(bx, rx + margin, 100.0 - rx - margin))
    return bx, float(cy), float(rx), float(ry)


def drop_limp_arm(body: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """Remove the hanging arm on the dribble side. The sleeve (tag) arm is
    white, so the skin arm left on that side is the one we replace. The
    tag-side fist stays, including on the reach frames."""
    h, w = body.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :].astype(np.float64)
    side = float(-TAG_SIDE[direction])
    face = (yy <= g.neck + 1) & skin_mask(body)
    arms, _hands = arms_and_hands(body, g, face)
    on_side = (xx - g.head_cx) * side > 3.0
    limp = arms & on_side & (yy > g.neck + 1)
    dark = alpha_mask(body) & (lum(body) < 70) & on_side & (yy > g.neck + 1)
    limp = limp | grow(limp, dark, 1)
    out = body.copy()
    out[limp] = 0
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


def _segment(p0: tuple[float, float], p1: tuple[float, float], n: int = 14) -> np.ndarray:
    ts = np.linspace(0.0, 1.0, n)
    return np.stack([p0[0] * (1 - ts) + p1[0] * ts, p0[1] * (1 - ts) + p1[1] * ts], axis=1)


def draw_dribble_arm(rgba: np.ndarray, g: Geometry, direction: str,
                     bx: float, by: float, ry: float, t: float) -> None:
    """Slim arm from the shoulder to a mitt on the crown of the ball.
    A small outward bow while the ball is up, straightening as the hand
    pushes down. The forearm stops at the wrist so it doesn't stab
    through the ball. Drawn after the ball."""
    side = float(-TAG_SIDE[direction])
    if direction in PROFILE:
        sx = g.head_cx + side * 6.0
        sy = float(g.neck + 14)
    elif direction in BACK:
        sx = g.head_cx + side * 9.0
        sy = float(g.neck + 15)
    else:
        sx = g.head_cx + side * 8.5
        sy = float(g.neck + 13)
    # start inside the shirt so the arm grows out of the shoulder
    sx0, sy0 = sx - side * 2.0, sy

    # mitt centred on the crown, overlapping the leather
    hx = bx
    hy = by - ry * 0.58
    # wrist: a few pixels above the mitt, back toward the shoulder
    wx = hx + (sx0 - hx) * 0.22
    wy = hy - 2.6

    bow = 2.6 * (1.0 - t) + 0.8
    mx = (sx0 + wx) * 0.5 + side * bow
    my = (sy0 + wy) * 0.5 + 0.6
    ts = np.linspace(0.0, 1.0, 22)
    omt = 1.0 - ts
    limb = np.stack([
        omt ** 2 * sx0 + 2 * omt * ts * mx + ts ** 2 * wx,
        omt ** 2 * sy0 + 2 * omt * ts * my + ts ** 2 * wy,
    ], axis=1)

    face = skin_mask(rgba) & (np.arange(rgba.shape[0])[:, None] < g.neck - 2)
    face = face & (np.arange(rgba.shape[0])[:, None] > g.top + 16)
    samples = rgba[face][:, :3].astype(np.float64)
    if len(samples) >= 8:
        tone = np.median(samples, axis=0)
    else:
        tone = np.array([244.0, 190.0, 140.0])
    shade = np.clip(tone * 0.70, 0, 255)
    edge = INK

    # forearm ~6px wide, close to the kid's own arms
    _stamp(rgba, limb, 3.15, 3.15, edge)
    _stamp(rgba, limb, 2.15, 2.15, shade)
    _stamp(rgba, limb, 1.25, 1.25, tone)

    # three short fingers on the leather, then the palm over their base
    fingers = []
    for dx in (-2.5, 0.0, 2.5):
        fingers.append(_segment((hx + dx, hy + 0.2), (hx + dx * 0.75, hy + 3.5), 6))
    fing = np.concatenate(fingers, axis=0)
    _stamp(rgba, fing, 1.35, 1.35, edge)
    _stamp(rgba, fing, 0.75, 0.75, tone)
    _stamp(rgba, np.array([[hx, hy + 0.3]]), 5.3, 3.5, edge)
    _stamp(rgba, np.array([[hx, hy]]), 3.9, 2.4, tone)
    _stamp(rgba, np.array([[hx, hy - 0.7]]), 2.2, 1.15, shade)


def baller(frame: np.ndarray, direction: str, anim: str, index: int) -> np.ndarray:
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return src
    g = Geometry(src)
    body, _chest, _hands = paint_uniform(src, g, direction)
    g = Geometry(body)
    body = drop_limp_arm(body, g, direction)
    t = bounce_t(anim, index)
    bx, by, rx, ry = place_ball(g, direction, anim, index)
    layer = ball_layer(body.shape[:2], bx, by, rx, ry, shadow=0.40 + 0.60 * t, spin=spin_deg(anim, index))
    merged = to_u8(over(premul(body), layer))
    # arm and hand over the body and over the top of the ball
    draw_dribble_arm(merged, g, direction, bx, by, ry, t)
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
