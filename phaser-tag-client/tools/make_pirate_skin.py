#!/usr/bin/env python3
"""Build the "Pirate James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_pirate.png + kid_pirate.json

Same columns, rows and animation ranges as kid.png. Frames are padded
(PAD_SIDE on both sides for the cutlass, PAD_TOP for the tricorn hat), so
the frame size and feet line differ from James (see src/skins.ts).

Per frame:
  1. T-shirt -> dark brown vest; front views show the cream shirt in a deep
     V, profiles a cream strip at the chest; bare arms -> cream puffy
     sleeves with a ruffled cuff next to each hand;
  2. black bandolier strap across the chest/back with a gold buckle, red
     sash round the waist with a hanging tail;
  3. shorts -> maroon / cream vertical striped breeches; shins and
     sneakers -> black knee-high boots with a turned-down cuff;
  4. brown tricorn hat with gold trim, red bandana under it (knot + tails
     on the back views) and a red feather;
  5. a curved cutlass (silver blade, gold guard) in the hand James tags
     with (the hand that reaches in the tag animation, per direction). It
     hangs blade down/out while idle, walking and running and swings
     forward with the reaching arm when tagging. It is drawn behind the
     body on the back views and in front (under the fist) otherwise.
Face, hair below the hat and hands are untouched.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_pirate_skin.py [--preview /tmp/pirate_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
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
from make_tuxedo_skin import close_streaks, lum, row_span, torso_rows

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 12
PAD_SIDE = 20
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW", "N", "NE"}
# Screen side (+1 right, -1 left) of the hand that reaches in the tag
# animation, per direction (read off kid.png).
TAG_SIDE = {"E": 1, "SE": 1, "S": 1, "SW": -1, "W": -1, "NW": -1, "N": 1, "NE": 1}
# which way the hat brim's front point / feather lean, per direction
FACING = {"E": 1, "SE": 0.55, "S": 0, "SW": -0.55, "W": -1, "NW": -0.55, "N": 0, "NE": 0.55}

C = lambda *v: np.array(v, dtype=np.float64)  # noqa: E731
OUTLINE = C(26, 16, 12)
VEST = C(84, 52, 30)
VEST_TRIM = C(132, 92, 52)
SHIRT = C(236, 222, 190)
SHIRT_SHADE = C(196, 176, 140)
STRAP = C(24, 22, 24)
GOLD = C(236, 186, 60)
GOLD_DARK = C(160, 112, 30)
SASH = C(204, 36, 40)
SASH_DARK = C(140, 20, 28)
MAROON = C(112, 32, 44)
CREAM = C(214, 188, 150)
BOOT = C(30, 28, 32)
BOOT_CUFF = C(62, 56, 58)
HAT = C(92, 62, 40)
HAT_DARK = C(58, 38, 24)
HAT_LIGHT = C(124, 88, 58)
BANDANA = C(214, 40, 44)
FEATHER = C(232, 52, 52)
BLADE = C(206, 214, 226)
BLADE_EDGE = C(250, 252, 255)
BLADE_DARK = C(86, 92, 108)


def shade(col: np.ndarray, l: np.ndarray, lo: float = 0.62, hi: float = 1.12) -> np.ndarray:
    """Base colour lit by the original art's luminance (keeps folds)."""
    k = lo + (hi - lo) * np.clip((l - 40.0) / 150.0, 0.0, 1.0)
    return col[None, None, :] * k[..., None]


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


# --- supersampled vector layers ------------------------------------------------
def grid(size):
    h, w = size
    ys = (np.arange(h * SS) + 0.5) / SS
    xs = (np.arange(w * SS) + 0.5) / SS
    return np.meshgrid(ys, xs, indexing="ij")


def down(col: np.ndarray, alpha: np.ndarray, size) -> np.ndarray:
    """(rgb, alpha) at SS resolution -> premultiplied float RGBA layer."""
    h, w = size
    col = np.clip(col, 0, 255) / 255.0
    layer = np.concatenate([col * alpha[..., None], alpha[..., None]], axis=-1)
    return layer.reshape(h, SS, w, SS, 4).mean(axis=(1, 3))


def premul(f: np.ndarray) -> np.ndarray:
    x = f.astype(np.float64) / 255.0
    x[..., :3] *= x[..., 3:4]
    return x


def over(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    return src + dst * (1.0 - src[..., 3:4])


def to_u8(x: np.ndarray) -> np.ndarray:
    out = x.copy()
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


def paint(col, alpha, mask, colour):
    col[mask] = colour
    alpha[mask] = 1.0


def seg_dist(X, Y, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy or 1e-9
    t = np.clip(((X - x0) * dx + (Y - y0) * dy) / L2, 0.0, 1.0)
    return np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy)), t


def hat_layer(g: Geometry, f: np.ndarray, direction: str, size):
    """Tricorn: crown dome + upturned brim with gold trim, red bandana under
    it, a red feather. Returns (layer, erase mask for hair above the brim)."""
    Y, X = grid(size)
    a = alpha_mask(f)
    # head extent near the top
    top = g.top
    rows = [np.nonzero(a[y])[0] for y in range(top, top + 14)]
    l = min(r.min() for r in rows if len(r))
    r = max(r.max() for r in rows if len(r)) + 1
    face = FACING[direction]
    cx = (l + r) / 2 + 0.8 * face
    hw = (r - l) / 2 + 4.5
    brim_y = top + 11.0                      # brim bottom (centre)
    col = np.zeros((*Y.shape, 3))
    alpha = np.zeros(Y.shape)

    u = (X - cx) / hw                        # -1..1 across the brim
    side = abs(face) > 0.9
    # brim edges: rises towards the corners ("upturned"); in front views a
    # point dips down at the centre front, in profiles the front corner
    up = 7.5 * np.abs(u) ** 2.2
    dip = np.zeros_like(u)
    if direction in FRONT or direction in BACK:
        k = 2.4 if direction in FRONT else 1.0
        dip = k * np.clip(1 - np.abs(u - 0.35 * face) / 0.38, 0, 1)
    if side:
        # profile: low at the middle, corners up front and back, front
        # corner a bit lower/longer
        up = 6.5 * np.abs(u) ** 2.0 - 1.2 * np.clip(u * face, 0, 1)
    bot = brim_y - up + dip
    brim_top = bot - 4.2 - 1.2 * (1 - np.abs(u))
    brim = (np.abs(u) <= 1.0) & (Y >= brim_top) & (Y <= bot)
    # crown dome
    crx = (r - l) / 2 * 0.82 + 1.0
    ccy = brim_y - 3.0
    cry = 12.5
    crown = (((X - (cx - 0.6 * face)) / crx) ** 2 + ((Y - ccy) / cry) ** 2 < 1.0) & (Y < brim_y - 1.0)
    shape = brim | crown
    # outline = shape minus shape eroded (distance based on SS grid)
    edge = shape & ~(
        np.roll(shape, SS, 0) & np.roll(shape, -SS, 0) & np.roll(shape, SS, 1) & np.roll(shape, -SS, 1))
    paint(col, alpha, crown, HAT)
    # crown light on the upper left, dark toward the brim
    paint(col, alpha, crown & (Y < ccy - 5) & (X < cx - 0.6 * face - 1), HAT_LIGHT)
    paint(col, alpha, brim, HAT_DARK)
    # gold trim along the top edge of the brim
    trim = brim & (Y < brim_top + 1.3)
    paint(col, alpha, trim, GOLD)
    paint(col, alpha, edge & ~trim, OUTLINE)

    # red bandana band under the brim on the head (all views) - only over
    # existing head pixels
    head_a = np.repeat(np.repeat(a, SS, 0), SS, 1)
    band = head_a & (Y > bot) & (Y < bot + 3.2) & (np.abs(X - cx) < hw - 3.0)
    paint(col, alpha, band, BANDANA)
    paint(col, alpha, band & (Y > bot + 2.2), SASH_DARK)

    # bandana knot + tails at the back of the head
    if direction in BACK or side:
        if side:
            kx = cx - face * (hw - 4.0)
            tdir = -face
        else:
            kx = cx + 0.4 * face * hw
            tdir = 0.3
        ky = brim_y + (-6.5 * 0.7 + 2.0 if side else 1.0)
        knot = np.hypot(X - kx, Y - ky) < 2.0
        paint(col, alpha, knot, BANDANA)
        for i, (dx, ln) in enumerate(((tdir * 1.5 - 1.2, 9.0), (tdir * 1.5 + 1.4, 7.0))):
            d, t = seg_dist(X, Y, kx, ky, kx + dx * 2.2, ky + ln)
            tail = d < 1.15 - 0.3 * t
            paint(col, alpha, tail, BANDANA if i == 0 else SASH_DARK)

    # red feather tucked in the crown on the hat's left side, curling back
    fs = -1 if face >= 0 else 1
    if direction in BACK:
        fs = 1 if face <= 0 else -1
    fx0, fy0 = cx + fs * crx * 0.55, ccy - 4.0
    pts = [(fx0, fy0), (fx0 + fs * 2.5, fy0 - 5.0), (fx0 + fs * 6.0, fy0 - 7.5), (fx0 + fs * 9.0, fy0 - 7.0)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d, _ = seg_dist(X, Y, x0, y0, x1, y1)
        paint(col, alpha, d < 2.0, FEATHER)
        paint(col, alpha, d < 0.5, SASH_DARK)

    layer = down(col, alpha, size)
    # hair that sticks up above the brim / out of the crown is hidden
    h, w = size
    cover = layer[..., 3] > 0.35
    yy = np.arange(h)[:, None]
    xs = np.arange(w)[None, :]
    bot_px = (brim_y - 7.5 * np.abs((xs + 0.5 - cx) / hw) ** 2.2)
    erase = a & ~cover & (yy < bot_px - 1) & (yy < top + 14)
    return layer, erase


def sword_layer(hand: tuple[float, float], d: tuple[float, float], size, side: int):
    """Cutlass: grip at `hand`, blade along unit vector d, curving towards
    `side` of the blade's back. Returns (hilt+blade layer, guard layer)."""
    Y, X = grid(size)
    hx, hy = hand
    dx, dy = d
    nx, ny = -dy, dx                  # normal
    # curve the blade so its tip bends "up" (towards -y), like a cutlass
    if ny > 0:
        nx, ny = -nx, -ny
    L = 19.0
    pts = []
    for i in range(13):
        t = i / 12
        s = 2.5 + t * L
        bend = 2.6 * t * t
        pts.append((hx + dx * s + nx * bend, hy + dy * s + ny * bend))
    col = np.zeros((*Y.shape, 3))
    alpha = np.zeros(Y.shape)
    dist = np.full(Y.shape, 1e9)
    tt = np.zeros(Y.shape)
    side_n = np.zeros(Y.shape)
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(pts, pts[1:])):
        dd, t = seg_dist(X, Y, x0, y0, x1, y1)
        better = dd < dist
        dist = np.where(better, dd, dist)
        tt = np.where(better, (i + t) / (len(pts) - 1), tt)
        sx, sy = x1 - x0, y1 - y0
        side_n = np.where(better, np.sign((X - x0) * -sy + (Y - y0) * sx), side_n)
    half = 1.55 - 0.85 * tt ** 1.5
    # tip: wider just before the point (cutlass "clip"), then sharp point
    half = np.where(tt > 0.82, half * np.clip((1.0 - tt) / 0.18, 0.15, 1.0) + 0.25, half)
    blade = dist < half + 0.7
    paint(col, alpha, blade, BLADE_DARK)
    inner = dist < half
    paint(col, alpha, inner, BLADE)
    paint(col, alpha, inner & (side_n * np.sign(ny if ny else 1) > 0) & (dist > half * 0.2), BLADE_EDGE)

    # grip (dark) through the fist, pommel behind it
    d0, _ = seg_dist(X, Y, hx - dx * 3.5, hy - dy * 3.5, hx + dx * 2.0, hy + dy * 2.0)
    paint(col, alpha, d0 < 1.2, C(70, 40, 22))
    pm = np.hypot(X - (hx - dx * 4.0), Y - (hy - dy * 4.0)) < 1.4
    paint(col, alpha, pm, GOLD)
    body = down(col, alpha, size)

    # gold guard: crossbar at the blade root + knuckle bow round the fist
    gcol = np.zeros((*Y.shape, 3))
    ga = np.zeros(Y.shape)
    gx, gy = hx + dx * 2.6, hy + dy * 2.6
    d1, _ = seg_dist(X, Y, gx - nx * 2.6, gy - ny * 2.6, gx + nx * 2.6, gy + ny * 2.6)
    paint(gcol, ga, d1 < 1.25, GOLD_DARK)
    paint(gcol, ga, d1 < 0.75, GOLD)
    # bow: arc from the guard end round the knuckles to the pommel
    bx0, by0 = gx - nx * 2.4, gy - ny * 2.4
    bx1, by1 = hx - dx * 3.6 - nx * 1.0, hy - dy * 3.6 - ny * 1.0
    mx, my = hx - nx * 3.6, hy - ny * 3.6
    for (x0, y0), (x1, y1) in (((bx0, by0), (mx, my)), ((mx, my), (bx1, by1))):
        d2, _ = seg_dist(X, Y, x0, y0, x1, y1)
        paint(gcol, ga, d2 < 0.75, GOLD)
    guard = down(gcol, ga, size)
    return body, guard


def pick_hand(hands: np.ndarray, g: Geometry, side: int, a: np.ndarray):
    comps = [c for c in components8(hands) if c.sum() >= 3]
    if not comps:
        return None
    best = None
    for comp in comps:
        ys, xs = np.nonzero(comp)
        score = side * (xs.mean() - g.hip_cx)
        if best is None or score > best[0]:
            best = (score, comp)
    score, comp = best
    if score < 1.0:
        return None
    ys, xs = np.nonzero(comp)
    return float(xs.mean() + 0.5), float(ys.mean() + 0.5), comp


def piratify(frame: np.ndarray, direction: str, anim: str, memo: dict) -> np.ndarray:
    f = pad_frame(frame)
    a = alpha_mask(f)
    if not a.any():
        return f
    g = Geometry(f)
    f = close_streaks(f, g.neck + 2)
    a = alpha_mask(f)
    h, w = a.shape
    size = (h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    L = lum(f)
    out = f[..., :3].astype(np.float64).copy()

    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & arms, 1)
    sk = loose_skin(f)
    outline = a & (L < 40)

    waist = g.hem - 9
    clothes = a & (yy > g.neck) & ~sk & ~outline
    vest = clothes & (yy <= waist)
    # breeches run over the knee (top rows of the bare shins), boots below
    knee = g.hem + 3
    breeches = a & (yy > waist) & (yy < knee) & ~arms & ~hands & ~(outline & (yy >= g.hem))
    breeches &= clothes | sk
    boots = a & (yy >= knee) & ~arms
    sleeves = arms & ~hands & sk

    # --- recolour ---------------------------------------------------------------
    out = np.where(vest[..., None], shade(VEST, L), out)
    out = np.where(sleeves[..., None], shade(SHIRT, L * 0.8 + 30, 0.78, 1.04), out)
    # stripes: 2 maroon : 1 cream, vertical, lit by the original shading
    stripe = ((xx + 1) % 3 == 0)
    pants = np.where(stripe[..., None], shade(CREAM, L * 0.8 + 40, 0.72, 1.0), shade(MAROON, L * 0.8 + 40, 0.7, 1.1))
    out = np.where(breeches[..., None], pants, out)
    out = np.where(boots[..., None], shade(BOOT, L * 0.6, 0.8, 1.7), out)
    # boot cuff: the first two rows of the boot
    cuff = boots & (yy <= knee + 1) & ~outline
    out = np.where(cuff[..., None], BOOT_CUFF, out)
    # dark specks on the clothes -> warm dark outline
    specks = outline & (yy > g.neck + 1) & ~hands & ~face
    out = np.where(specks[..., None], OUTLINE, out)
    # ruffled shirt cuff next to the hand
    ruff = grow(hands, sleeves, 2) & sleeves
    out = np.where(ruff[..., None], np.where(((xx + yy) % 2 == 0)[..., None], SHIRT, SHIRT_SHADE), out)
    # boot glint
    for comp in components8(boots & ~outline):
        if comp.sum() < 6:
            continue
        ys, xs = np.nonzero(comp)
        y = ys.max() - 2
        row = xs[ys == y]
        if len(row):
            out[y, int(np.median(row))] = C(110, 106, 116)

    # --- vest / shirt / bandolier / sash details ----------------------------------
    jtop, _ = torso_rows(vest | (sleeves & (yy < waist)))
    chest = a & ~arms & (yy > g.neck - 1) & (yy <= waist)
    if jtop is not None:
        cx = g.head_cx
        if direction in FRONT:
            cx += FRONT[direction] * 1.5
            depth = 13
            for i in range(depth + 1):
                y = jtop + i
                half = 4.2 * (1 - i / depth) + 0.8
                for x in range(w):
                    if not chest[y, x]:
                        continue
                    dd = x + 0.5 - cx
                    if abs(dd) < half:
                        out[y, x] = SHIRT if abs(dd) < half - 1.0 else SHIRT_SHADE
                    elif abs(dd) < half + 1.2:
                        out[y, x] = VEST_TRIM
            # lacing at the top of the shirt V
            for y in (jtop + 2, jtop + 4):
                x = int(np.floor(cx))
                if chest[y, x]:
                    out[y, x] = SHIRT_SHADE * 0.75
        elif direction in PROFILE:
            s = PROFILE[direction]
            for i in range(10):
                y = jtop + i
                l, r = row_span(vest, y)
                if l is None:
                    continue
                edge = r if s > 0 else l
                for k in range(2 if i < 8 else 1):
                    x = edge - k * s
                    if vest[y, x]:
                        out[y, x] = SHIRT if k == 0 else VEST_TRIM
        else:
            # back seam of the vest
            sx = int(round(g.hip_cx - 0.5))
            for y in range(jtop + 3, waist):
                if vest[y, sx]:
                    out[y, sx] = VEST * 0.7

        # bandolier: from the shoulder on one side to the hip on the other
        # (wearer's left shoulder -> right hip: screen right -> left from
        # the front, mirrored from the back)
        s0 = 1 if direction in FRONT else -1 if direction in BACK else PROFILE[direction] * -1
        tl, tr = row_span(chest, jtop + 1)
        bl, br = row_span(chest, waist - 1)
        if tl is not None and bl is not None:
            x0 = (tr - 2.5) if s0 > 0 else (tl + 2.5)
            x1 = (bl + 1.5) if s0 > 0 else (br - 1.5)
            y0, y1 = jtop + 0.5, waist - 0.5
            if direction in PROFILE:
                x0, x1 = (tl + tr) / 2 + 2 * s0, (bl + br) / 2 - 3 * s0
            mid_t = 0.45
            for y in range(int(y0), int(y1) + 1):
                t = (y + 0.5 - y0) / (y1 - y0)
                xc = x0 + (x1 - x0) * t
                for x in range(int(math.floor(xc - 1.6)), int(math.ceil(xc + 1.6))):
                    if 0 <= x < w and chest[y, x] and abs(x + 0.5 - xc) < 1.6:
                        out[y, x] = STRAP
            # buckle
            if direction not in BACK:
                by = int(y0 + (y1 - y0) * mid_t)
                bx = x0 + (x1 - x0) * mid_t
                for y in (by - 1, by, by + 1):
                    for x in range(int(bx - 1.5), int(bx + 2.5)):
                        if chest[y, x]:
                            edge_px = y in (by - 1, by + 1) or x in (int(bx - 1.5), int(bx + 1.5))
                            out[y, x] = GOLD if edge_px else STRAP

        # red sash round the waist
        body_rows = a & ~arms & ~hands
        for y in range(waist - 1, waist + 2):
            l, r = row_span(body_rows, y)
            if l is None:
                continue
            for x in range(l, r + 1):
                if body_rows[y, x]:
                    out[y, x] = SASH if y < waist + 1 else SASH_DARK
        # the sash's hanging tail, on the hip away from the sword (the back
        # hip in profile)
        ts = -TAG_SIDE[direction] if direction not in PROFILE else -PROFILE[direction]
        for i, y in enumerate(range(waist + 2, waist + 10)):
            l, r = row_span(body_rows & (yy < knee + 2), y)
            if l is None:
                continue
            x0 = (l + 1 + i // 3) if ts < 0 else (r - 3 - i // 3)
            for k in range(3 if i < 6 else 2):
                x = x0 + k
                if body_rows[y, x]:
                    out[y, x] = SASH if k < 2 else SASH_DARK

    # --- layers: sword, hat ------------------------------------------------------
    side = TAG_SIDE[direction]
    pick = pick_hand(hands & (yy > g.neck + 1), g, side, a)
    key = (direction, anim)
    hidden = False
    if pick is not None:
        hx, hy, hand_comp = pick
    elif key in memo:
        hx, hy = memo[key]
        hand_comp = None
        hidden = True
    else:
        hx, hy = g.hip_cx + side * 9.0, waist + 2.0
        hand_comp = None
        hidden = True
    memo[key] = (hx, hy)
    # shoulder: where the arm starts
    shx = g.head_cx + side * (3.0 if direction in PROFILE else 7.0)
    shy = g.neck + 6.0
    vx, vy = hx - shx, hy - shy
    vn = math.hypot(vx, vy) or 1.0
    reach = np.clip((abs(vx) / vn - 0.45) / 0.4, 0.0, 1.0)
    rest = (side * math.sin(math.radians(38)), math.cos(math.radians(38)))
    # reaching: along the arm, lifted ~20 deg
    ang = math.atan2(vy, vx)
    ang -= math.radians(20) * (1 if vx > 0 else -1)
    reach_d = (math.cos(ang), math.sin(ang))
    dx = rest[0] * (1 - reach) + reach_d[0] * reach
    dy = rest[1] * (1 - reach) + reach_d[1] * reach
    dn = math.hypot(dx, dy) or 1.0
    sword, guard = sword_layer((hx, hy), (dx / dn, dy / dn), size, side)

    res = f.copy()
    res[..., :3] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    # same see-through clean-up as the tuxedo (motion-blur blends)
    al = res[..., 3].astype(np.int32)
    solid = al > 200
    nb = np.zeros(al.shape, dtype=np.int32)
    nb[1:] += solid[:-1]
    nb[:-1] += solid[1:]
    nb[:, 1:] += solid[:, :-1]
    nb[:, :-1] += solid[:, 1:]
    inner = (al > 0) & ~solid & (nb >= 3) & (yy > g.neck + 1)
    res[..., 3] = np.where(inner, 255, res[..., 3])

    hat, erase = hat_layer(g, res, direction, size)
    res[erase] = 0
    base = premul(res)
    behind = direction in BACK or hidden
    if behind:
        out_l = over(over(sword, guard), base)   # body covers the sword
    else:
        out_l = over(base, sword)
        if hand_comp is not None:
            # the fist wraps the grip: hand pixels back on top
            fist = premul(res) * hand_comp[..., None]
            out_l = over(out_l, fist)
        out_l = over(out_l, guard)
    out_l = over(out_l, hat)
    result = to_u8(out_l)
    result[result[..., 3] < 8] = 0
    return result


ANIMS = None


def anim_of(meta, c: int) -> str:
    for name, rng in meta["animations"].items():
        if rng["start"] <= c < rng["start"] + rng["count"]:
            return name
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled 3x contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    ofw, ofh = fw + 2 * PAD_SIDE, fh + PAD_TOP
    out = np.zeros((len(dirs) * ofh, cols * ofw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        memo: dict = {}
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = piratify(fr, direction, anim_of(meta, c), memo)
    Image.fromarray(out).save(ASSETS / "kid_pirate.png", optimize=True)
    pm = dict(meta)
    pm["image"] = "kid_pirate.png"
    pm["frameWidth"], pm["frameHeight"] = ofw, ofh
    pm["baselineY"] = meta["baselineY"] + PAD_TOP
    pm["anchorX"] = ofw // 2
    (ASSETS / "kid_pirate.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_pirate.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")

    if args.preview:
        from PIL import ImageDraw
        img = Image.fromarray(out)
        scale, pad = 2, 40
        picks = [0, 6, 13, 16, 18, 20, 24, 27]
        names = ["idle", "walk", "breathe", "tag0", "tag2", "tag4", "run", "run"]
        pv = Image.new("RGBA", (pad + len(picks) * ofw * scale, pad + len(dirs) * ofh * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (ofw, ofh), (120, 170, 120, 255) if (r + i) % 2 else (100, 150, 100, 255))
                cell.alpha_composite(img.crop((c * ofw, r * ofh, (c + 1) * ofw, (r + 1) * ofh)))
                pv.paste(cell.resize((ofw * scale, ofh * scale), Image.NEAREST),
                         (pad + i * ofw * scale, pad + r * ofh * scale))
            d.text((4, pad + r * ofh * scale + 10), dirs[r], fill="white")
        for i, name in enumerate(names):
            d.text((pad + i * ofw * scale + 4, 12), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
