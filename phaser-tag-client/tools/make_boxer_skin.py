#!/usr/bin/env python3
"""Build the "Boxer James" sprite sheet (public/assets/kid_boxer.png/json)
from the base kid sheet.

Same smooth pipeline as make_tennis_skin.py: flat-colour class maps,
supersampled 4x, outlined, then box-downscaled.

  * James's real face and head, unchanged;
  * bare muscular chest (detailed pecs/abs shading) over his normal build;
  * shiny baggy red boxing trunks with a wide gold/white waistband and gold
    side trim, mid-thigh, consistent every direction;
  * high-top boxing shoes in red / white / gold with laces;
  * BIG round glossy RED boxing gloves (~1/2–2/3 head width) with white
    cuffs on BOTH hands in every frame (side views: near arm only). Idle /
    walk / breathe / run hold a high guard near the chin with a light bounce;
  * tag is a quick JAB: the near (tagging) glove snaps straight forward in
    the facing direction and retracts over the 6 tag frames. The arm stays
    James-thick, shaded, attached at the shoulder in all 8 directions
    (NW mirrors NE). The torso keeps the idle outline; the far glove stays
    up in guard.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_boxer_skin.py [--preview /tmp/boxer_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from make_banana_skin import Geometry, alpha_mask, arms_and_hands, components8, grow, skin_mask
from solid_mask import solidify
from make_pirate_skin import TAG_SIDE, anim_of
from make_wizard_skin import down, over, premul, to_u8

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 12
PAD_SIDE = 28
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}

# outfit
TRUNK = (200, 24, 40)
TRUNK_SHADE = (140, 12, 26)
TRUNK_HI = (236, 70, 82)
WAIST = (236, 204, 78)
WAIST_HI = (252, 236, 160)
TRIM = (250, 240, 210)
SHOE_RED = (214, 32, 46)
SHOE_WHITE = (248, 248, 246)
SHOE_GOLD = (224, 184, 56)
SOLE = (52, 40, 36)
LACE = (252, 252, 250)
LINE = (36, 22, 20)

# gloves — Little-Mac sized
GLOVE = (224, 28, 44)
GLOVE_SHADE = (148, 12, 26)
GLOVE_HI = (255, 140, 150)
GLOVE_SPEC = (255, 210, 214)
CUFF = (250, 250, 248)
CUFF_SHADE = (200, 200, 206)
ARM_LINE = (40, 26, 22)
SKIN_SHADE = (200, 140, 100)


def S(v):
    return v * SS


def pad_frame(frame):
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def shapes_layer(size, parts, line, line_w=0.7):
    h, w = size
    rgb = np.zeros((h * SS, w * SS, 3), np.uint8)
    union = np.zeros((h * SS, w * SS), bool)
    for fn, col in parts:
        m = Image.new("L", (w * SS, h * SS), 0)
        fn(ImageDraw.Draw(m))
        mm = np.asarray(m) > 127
        rgb[mm] = col
        union |= mm
    sil = Image.fromarray((union * 255).astype(np.uint8))
    k = int(round(line_w * SS)) * 2 + 1
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(k))) > 127
    rgb[union & ~inner] = line
    return Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")


def capsule_fn(p1, r1, p2, r2):
    def fn(d):
        n = 18
        for i in range(n + 1):
            t = i / n
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            r = r1 + (r2 - r1) * t
            d.ellipse([S(x - r), S(y - r), S(x + r), S(y + r)], fill=255)
    return fn


def disc_fn(c, r):
    return lambda d: d.ellipse([S(c[0] - r), S(c[1] - r), S(c[0] + r), S(c[1] + r)], fill=255)


def oval_fn(c, rx, ry):
    return lambda d: d.ellipse([S(c[0] - rx), S(c[1] - ry), S(c[0] + rx), S(c[1] + ry)], fill=255)


def loose_skinlike(f):
    r, g, b = (f[..., i].astype(np.int32) for i in range(3))
    return (f[..., 3] >= 128) & (r - b > 25) & (r - g > 14) & (r > 70)


def to_u8_simple(x):
    return np.clip(np.round(x), 0, 255).astype(np.uint8)


def ik(sh, hand, L1, L2, bend):
    dx, dy = hand[0] - sh[0], hand[1] - sh[1]
    dd = math.hypot(dx, dy) or 1.0
    dd2 = min(dd, L1 + L2 - 0.05)
    a = (L1 * L1 - L2 * L2 + dd2 * dd2) / (2 * dd2)
    hh = math.sqrt(max(L1 * L1 - a * a, 0.0))
    ux, uy = dx / dd, dy / dd
    px, py = -uy * bend, ux * bend
    return (sh[0] + ux * a + px * hh, sh[1] + uy * a + py * hh)


def torso_hull(keep, rm, gi):
    h, w = keep.shape
    y0, y1 = int(gi.neck) + 2, int(gi.hem)
    out = np.zeros_like(keep)
    L = np.full(h, np.nan)
    R = np.full(h, np.nan)
    for y in range(y0, y1 + 1):
        xs = np.nonzero(keep[y])[0]
        if not len(xs):
            continue
        ar = np.nonzero(rm[y])[0]
        if not (len(ar) and ar.min() < xs.min()):
            L[y] = xs.min()
        if not (len(ar) and ar.max() > xs.max()):
            R[y] = xs.max()
    ys = np.arange(h)
    for E in (L, R):
        ok = ~np.isnan(E)
        if ok.sum() >= 2:
            E[y0:y1 + 1] = np.interp(ys[y0:y1 + 1], ys[ok], E[ok])
    for y in range(y0, y1 + 1):
        if not (np.isnan(L[y]) or np.isnan(R[y])):
            out[y, int(round(L[y])):int(round(R[y])) + 1] = True
    return out


def arm_comps_on(arms, g, direction, side):
    m = np.zeros_like(arms)
    for comp in components8(arms):
        if comp.sum() < 4:
            continue
        xs = np.nonzero(comp)[1]
        if side == 0 or direction in PROFILE or (xs.mean() + 0.5 - g.head_cx) * side > 0:
            m |= comp
    return m


def strip_arms(f, g, direction, sides):
    """Remove hanging arms on the given sides and fill the torso hull so the
    silhouette stays James-width. Head / face / neck pixels are never touched."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = f.copy()
    face = (yy <= g.neck + 1) & skin_mask(out)
    arms, _ = arms_and_hands(out, g, face)
    rm = np.zeros_like(arms)
    for s in sides:
        rm |= arm_comps_on(arms, g, direction, s)
    rm = grow(rm, alpha_mask(out), 1) & (yy > g.neck + 2)
    ai = alpha_mask(out)
    keep = ai & ~rm
    over_t = rm & ai & torso_hull(keep, rm, g)
    ys = np.nonzero(ai.any(1))[0]
    if len(ys):
        hb = ys.max() - 6
        hem = np.nonzero(ai[max(0, hb - 8):hb])[1]
        if len(hem):
            hx = int(np.median(hem))
            core = max(3, (hem.max() - hem.min()) // 2 - 2)
            over_t |= rm & ai & (np.abs(xx - hx) <= core)
    sk = skin_mask(out) & (yy > g.neck + 2) & (yy < g.hem - 4)
    if sk.any():
        px = out[sk][:, :3].astype(int)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 40)]
        chest_c = tuple(int(v) for v in np.median(px, 0)) if len(px) else (220, 160, 120)
    else:
        chest_c = (220, 160, 120)
    c = out[..., :3].astype(np.int32)
    navy = ai & ~loose_skinlike(out) & (c[..., 2] - c[..., 1] > 11) & (yy >= g.hem - 16)
    sh_c = tuple(int(v) for v in np.median(out[navy][:, :3], 0)) if navy.any() else TRUNK
    waist = int(g.hem - 10)
    if navy.any():
        waist = int(np.median(np.nonzero(navy)[0]) - 2)
    for msk, col in (((yy < waist), chest_c), ((yy >= waist), sh_c)):
        out[over_t & msk, :3] = col
        out[over_t & msk, 3] = 255
    out[rm & ~over_t] = 0
    ai = alpha_mask(out)
    for y in range(int(g.neck) + 2, int(g.hem) + 1):
        xs = np.nonzero(ai[y])[0]
        if len(xs) < 2:
            continue
        hole = np.zeros(w, bool)
        hole[xs.min():xs.max() + 1] = True
        hole &= ~ai[y]
        if hole.any():
            out[y, hole, :3] = chest_c if y < waist else sh_c
            out[y, hole, 3] = 255
    return out


def find_waist(f, g):
    h, w = f.shape[:2]
    yy = np.mgrid[0:h, 0:w][0]
    a = f[..., 3] >= 128
    c = f[..., :3].astype(np.int32)
    skin = loose_skinlike(f)
    lum = c.mean(-1)
    line = lum < 26
    cloth = a & ~skin & ~line
    navy = cloth & (c[..., 2] - c[..., 1] > 11)
    waist = g.hem - 12
    for y in range(g.neck + 6, g.hem):
        row = cloth[y] | skin[y]
        if row.sum() >= 4 and navy[y].sum() / max(row.sum(), 1) > 0.35:
            waist = y
            break
    return waist


def recolor_chest(f, g, waist):
    """Bare chest with pec/abs shading. Does NOT paint trunks (drawn separately)."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = f[..., 3] >= 128
    c = f[..., :3].astype(np.float64)
    lum = c.mean(-1)
    r_, g_, b_ = c[..., 0], c[..., 1], c[..., 2]
    skin = loose_skinlike(f)
    line = lum < 26
    cloth = a & ~skin & ~line
    head = yy <= g.neck + 1
    tee_col = (b_ - r_ > 4) & (lum > 40) & (lum < 140)
    cloth &= ~head | ((yy > g.neck - 3) & tee_col)
    shirt = cloth & (yy < waist) & (yy > g.neck)
    out = f.copy().astype(np.float64)

    sk_src = skin & (yy > g.neck + 2) & (yy < waist)
    if sk_src.any():
        px = f[sk_src][:, :3].astype(float)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 45)]
        base_skin = np.median(px, 0) if len(px) else np.array([220.0, 160.0, 120.0])
    else:
        base_skin = np.array([220.0, 160.0, 120.0])
    if shirt.any():
        ref = np.percentile(lum[shirt], 75) or 1.0
        k = np.clip(0.82 + 0.24 * lum[shirt] / ref, 0.82, 1.06)
        out[shirt, :3] = base_skin[None] * k[:, None]
    torso = (shirt | (skin & (yy > g.neck + 3) & (yy < waist))) & a & ~head
    # slightly warm / even the bare torso so pecs/abs read on top
    if torso.any():
        ref = np.percentile(lum[torso], 70) or 1.0
        k = np.clip(0.92 + 0.14 * lum[torso] / ref, 0.90, 1.06)
        out[torso, :3] = base_skin[None] * k[:, None]
    if torso.any():
        cx = g.head_cx
        for sx in (-4.8, 4.8):
            d2 = ((xx + 0.5 - (cx + sx)) ** 2) / 22.0 + ((yy + 0.5 - (g.neck + 9.5)) ** 2) / 11.0
            pec = torso & (d2 < 1.0) & (yy > g.neck + 4) & (yy < g.neck + 16)
            out[pec, :3] *= 0.82
            # pec highlight above
            hi = torso & (d2 < 0.45) & (yy > g.neck + 4) & (yy < g.neck + 10)
            out[hi, :3] = np.clip(out[hi, :3] * 1.08, 0, 255)
        mid = torso & (np.abs(xx + 0.5 - cx) < 3.6) & (yy > g.neck + 14) & (yy < waist - 1)
        for by in (g.neck + 16, g.neck + 21, g.neck + 26, g.neck + 31):
            band = mid & (np.abs(yy - by) <= 1)
            out[band, :3] *= 0.78
        crease = mid & (np.abs(xx + 0.5 - cx) < 1.0)
        out[crease, :3] *= 0.80
        for sx in (-1, 1):
            side = torso & ((xx + 0.5 - cx) * sx > 4.5) & ((xx + 0.5 - cx) * sx < 9.5)
            side &= (yy > g.neck + 9) & (yy < waist - 2)
            out[side, :3] *= 0.86
    # soften outline next to chest
    near = line & grow(shirt | torso, a, 1) & ~head & (yy < waist)
    out[near, :3] = LINE
    return to_u8_simple(out), base_skin


def foot_centers(f, g):
    """Approximate left/right foot centres from shoe/leg pixels below the hem."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = f[..., 3] >= 128
    feet = a & (yy >= g.hem + 1)
    comps = [c for c in components8(feet) if c.sum() >= 4]
    centres = []
    for comp in comps:
        ys, xs = np.nonzero(comp)
        centres.append((float(xs.mean() + 0.5), float(ys.mean() + 0.5),
                        float(ys.min()), float(ys.max()), float(xs.min()), float(xs.max())))
    centres.sort(key=lambda t: t[0])
    return centres


def rect_capsule_fn(x0, y0, x1, y1, round_r):
    """Filled rounded rect via capsules + discs (SS-space via S())."""
    def fn(d):
        # horizontal bands
        y = y0
        while y <= y1:
            r = round_r
            if y < y0 + round_r:
                # taper not needed; just draw full width discs along midline
                pass
            d.ellipse([S(x0 - r), S(y - r), S(x0 + r), S(y + r)], fill=255)
            d.ellipse([S(x1 - r), S(y - r), S(x1 + r), S(y + r)], fill=255)
            # fill between
            d.rectangle([S(x0), S(y - r), S(x1), S(y + r)], fill=255)
            y += max(0.6, round_r * 0.7)
    return fn


def trunks_layer(size, g, waist, direction):
    """Baggy shiny red trunks mid-thigh, wide gold waistband, gold side trim.
    Strictly below `waist` so they never smear onto the chest."""
    # mid-thigh: leave a clear shin gap above the shoes
    thigh = waist + max(9, int(0.38 * (g.bottom - waist)))
    thigh = min(thigh, g.bottom - 14)
    cx = g.hip_cx
    hw = max(9.5, g.head_hw * 0.90 + 2.0)
    if direction in PROFILE:
        fx = PROFILE[direction]
        cx = g.head_cx + fx * 0.8
        hw = max(7.5, g.head_hw * 0.62 + 1.0)
    top = float(waist) + 0.2   # never above waist
    bot = float(thigh)
    wb = 4.0
    # baggy body: rounded rect via dense capsules
    parts = [
        (rect_capsule_fn(cx - hw, top + wb * 0.7, cx + hw, bot - 0.5, 2.4), TRUNK),
        # lower shade band
        (rect_capsule_fn(cx - hw + 0.5, bot - 4.0, cx + hw - 0.5, bot - 0.3, 2.0), TRUNK_SHADE),
        # gloss streak
        (oval_fn((cx - hw * 0.25, top + wb + 4.0), hw * 0.40, 2.0), TRUNK_HI),
        # wide gold waistband (multi-row for thickness)
        (rect_capsule_fn(cx - hw - 0.3, top, cx + hw + 0.3, top + wb, 1.8), WAIST),
        (capsule_fn((cx - hw + 0.5, top + 1.0), 1.0,
                    (cx + hw - 0.5, top + 1.0), 1.0), WAIST_HI),
        # white drawstring hint
        (disc_fn((cx - 1.2, top + wb * 0.55), 0.7), TRIM),
        (disc_fn((cx + 1.2, top + wb * 0.55), 0.7), TRIM),
        # gold side trim
        (capsule_fn((cx - hw + 0.6, top + wb + 0.5), 1.05,
                    (cx - hw + 0.3, bot - 1.2), 0.95), TRIM),
        (capsule_fn((cx + hw - 0.6, top + wb + 0.5), 1.05,
                    (cx + hw - 0.3, bot - 1.2), 0.95), TRIM),
        # hem
        (capsule_fn((cx - hw + 1.0, bot - 0.5), 0.75,
                    (cx + hw - 1.0, bot - 0.5), 0.75), TRIM),
    ]
    return shapes_layer(size, parts, LINE, 0.85)


def shoes_layer(size, feet, direction):
    """Red/white/gold high-top boxing shoes with laces on each foot."""
    if not feet:
        return None
    parts = []
    for (cx, cy, y0, y1, x0, x1) in feet:
        # tall high-top: rise well above the original shoe pixels
        top = y0 - 5.5
        bot = y1 + 1.0
        mid = (top + bot) / 2
        hw = max(4.2, (x1 - x0) / 2 + 1.4)
        tip_dx = 0.0
        if direction in PROFILE:
            tip_dx = PROFILE[direction] * 1.6
        elif direction in FRONT:
            tip_dx = FRONT[direction] * 0.7
        elif direction in BACK:
            tip_dx = -BACK[direction] * 0.5
        # sole
        parts.append((oval_fn((cx + tip_dx * 0.4, bot - 0.5), hw + 0.6, 1.4), SOLE))
        # red boot shaft (tall)
        parts.append((oval_fn((cx, mid), hw, (bot - top) / 2 + 0.2), SHOE_RED))
        # shade
        parts.append((oval_fn((cx + 0.8, mid + 1.5), hw * 0.55, (bot - top) * 0.28), tuple(int(c*0.75) for c in SHOE_RED)))
        # white toe box
        parts.append((oval_fn((cx + tip_dx * 1.6, bot - 2.4), hw * 0.62, 2.0), SHOE_WHITE))
        # gold collar stripe near top
        parts.append((capsule_fn((cx - hw + 0.4, top + 2.2), 1.2,
                                (cx + hw - 0.4, top + 2.2), 1.2), SHOE_GOLD))
        # white tongue / cuff
        parts.append((oval_fn((cx, top + 0.9), hw * 0.75, 1.5), SHOE_WHITE))
        # laces (3 pairs)
        for ly in (top + 3.4, top + 5.0, top + 6.6):
            if ly < bot - 2.5:
                parts.append((disc_fn((cx - 1.1, ly), 0.6), LACE))
                parts.append((disc_fn((cx + 1.1, ly), 0.6), LACE))
                # lace cross
                parts.append((capsule_fn((cx - 1.1, ly), 0.35, (cx + 1.1, ly + 0.8), 0.35), LACE))
    return shapes_layer(size, parts, LINE, 0.75)


def glove_radius(g):
    """~1/2 to 2/3 of head width → radius ~0.28–0.33 head width."""
    return max(9.5, min(12.5, g.head_hw * 0.65))


def shoulder(g, direction, side):
    if direction in PROFILE:
        return (g.head_cx - PROFILE[direction] * 0.3, g.neck + 4.5)
    return (g.head_cx + (side or 1) * 7.5, g.neck + 4.5)


def guard_hand(sh, direction, side, bounce=0.0, gr=9.0):
    """High guard near the chin; hand far enough out that a thick arm + white
    cuff stay visible and the big glove does not paint red onto the torso."""
    if direction in PROFILE:
        fx = PROFILE[direction]
        # forward and slightly down so the upper-arm capsule is a visible stub
        return (sh[0] + fx * (12.0 + gr * 0.25), sh[1] + 1.0 + bounce)
    out = (side or 1) * (6.0 + gr * 0.10)
    up = -4.5 if direction in FRONT or direction == "S" else -3.5
    if direction in BACK:
        up = -3.0
    return (sh[0] + out * 0.75, sh[1] + up + bounce)


# jab reach includes glove radius so the tip travels clearly
JAB_REACH = [12.0, 17.0, 23.5, 28.5, 19.0, 13.0]
JAB_ANG = {
    "profile": [-52, -30, -8, 4, -16, -46],
    "front":   [-65, -40, -16, 0, -22, -58],
    "back":    [-98, -75, -46, -20, -52, -90],
}


def jab_pose(direction, p_idx, side):
    if direction in PROFILE:
        angs = JAB_ANG["profile"]
        s = PROFILE[direction]
    elif direction in FRONT or direction == "S":
        angs = JAB_ANG["front"]
        s = side or 1
    else:
        angs = JAB_ANG["back"]
        s = side or 1
    a = angs[p_idx]
    if s < 0:
        a = 180 - a
    return math.radians(a), JAB_REACH[p_idx]


def glove_parts(sh, elbow, hand, skin, gr, jabbing=False):
    """Thick upper arm + forearm + white cuff (under) + BIG glossy red glove.
    Cuff is centred behind the glove so a white crescent peeks at the wrist."""
    ex, ey = hand[0] - elbow[0], hand[1] - elbow[1]
    en = math.hypot(ex, ey) or 1.0
    ux, uy = ex / en, ey / en
    # cuff well behind glove edge so it remains visible as a white band
    cuff_c = (hand[0] - ux * (gr + 2.8), hand[1] - uy * (gr + 2.8))
    cuff_r = 4.2
    wrist = (hand[0] - ux * (gr * 0.55), hand[1] - uy * (gr * 0.55))
    hi = (hand[0] - gr * 0.28, hand[1] - gr * 0.32)
    spec = (hand[0] - gr * 0.38, hand[1] - gr * 0.42)
    shade = (hand[0] + gr * 0.22, hand[1] + gr * 0.28)
    if jabbing:
        u0, u1 = 5.8, 5.2
        f0, f1 = 5.0, 4.5
    else:
        u0, u1 = 5.2, 4.6
        f0, f1 = 4.5, 4.0
    skin2 = tuple(int(v * 0.86) for v in skin)
    return [
        (capsule_fn(sh, u0, elbow, u1), skin),
        (capsule_fn(sh, u0 * 0.55, elbow, u1 * 0.55), skin2),
        (capsule_fn(elbow, f0, wrist, f1), skin),
        (capsule_fn(elbow, f0 * 0.55, wrist, f1 * 0.55), skin2),
        # white cuff UNDER the glove, sticking out the back
        (disc_fn(cuff_c, cuff_r), CUFF),
        (disc_fn(cuff_c, cuff_r * 0.65), CUFF_SHADE),
        # big glossy glove on top (unbroken red disc)
        (disc_fn(hand, gr), GLOVE),
        (disc_fn(shade, gr * 0.58), GLOVE_SHADE),
        (disc_fn(hi, gr * 0.36), GLOVE_HI),
        (disc_fn(spec, gr * 0.16), GLOVE_SPEC),
    ]


def draw_arm(size, sh, hand, skin, gr, jabbing=False):
    # longer IK segments so a jab doesn't stretch into a stick
    L1, L2 = 9.5, 9.0
    e1 = ik(sh, hand, L1, L2, 1)
    e2 = ik(sh, hand, L1, L2, -1)
    if jabbing:
        # nearly straight: elbow close to the shoulder→hand line
        def off(e):
            # distance from line sh→hand
            dx, dy = hand[0] - sh[0], hand[1] - sh[1]
            lx = math.hypot(dx, dy) or 1.0
            return abs((hand[0] - sh[0]) * (sh[1] - e[1]) - (sh[0] - e[0]) * (hand[1] - sh[1])) / lx
        elbow = e1 if off(e1) < off(e2) else e2
        # pull elbow toward the line a bit for a cleaner jab
        t = 0.45
        mid = (sh[0] + (hand[0] - sh[0]) * t, sh[1] + (hand[1] - sh[1]) * t)
        elbow = (elbow[0] * 0.35 + mid[0] * 0.65, elbow[1] * 0.35 + mid[1] * 0.65)
    else:
        elbow = e1 if e1[1] <= e2[1] else e2
    return shapes_layer(size, glove_parts(sh, elbow, hand, skin, gr, jabbing), ARM_LINE, 1.05)


def skin_rgb_of(f):
    sk = skin_mask(f)
    if sk.any():
        px = f[sk][:, :3].astype(int)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 50)]
        rgb = tuple(int(v) for v in np.median(px, 0))
        return tuple(int(v * k) for v, k in zip(rgb, (0.97, 0.88, 0.82)))
    return (246, 182, 132)


def bounce_of(anim, col, meta):
    if anim not in ("walk", "run"):
        return 0.0
    rng = meta["animations"][anim]
    k = col - rng["start"]
    return 1.2 * math.sin(k * math.pi / 2.0)


def scrub_red_smears(body, g, waist):
    """Remove stray saturated-red pixels on the torso/legs that aren't trunks.
    Trunks are drawn as a separate layer, so any red on the body plate above
    mid-chest or on bare thighs is a smear."""
    out = body.copy()
    h, w = out.shape[:2]
    yy = np.mgrid[0:h, 0:w][0]
    a = out[..., 3] >= 128
    rgb = out[..., :3].astype(np.int32)
    red = a & (rgb[..., 0] > 150) & (rgb[..., 0] - rgb[..., 1] > 55) & (rgb[..., 0] - rgb[..., 2] > 45)
    # above waistband: never keep red on the body plate
    smear = red & (yy < waist + 1) & (yy > g.neck)
    if smear.any():
        # repaint as neighbouring skin
        sk = loose_skinlike(out) & (yy > g.neck + 2) & (yy < waist) & ~smear
        fill = np.median(out[sk][:, :3], 0) if sk.any() else np.array([220, 160, 120])
        out[smear, :3] = fill
    return out



def scrub_chest_red(body, g, waist, direction, tag_side):
    """Remove glove-bleed red smears on the bare torso above the waistband.
    Keeps large round glove components; erases thin trails on the chest."""
    out = body.copy()
    h, w = out.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = out[..., 3] >= 128
    rgb = out[..., :3].astype(np.int32)
    # true garment/glove red (low green) — does not match skin
    red = a & (rgb[..., 0] > 160) & (rgb[..., 1] < 100) & (rgb[..., 0] - rgb[..., 1] > 80) & (rgb[..., 0] - rgb[..., 2] > 70)
    chest = (yy > g.neck + 2) & (yy < waist + 0.5)
    keep = np.zeros_like(red)
    for comp in components8(red):
        ys, xs = np.nonzero(comp)
        if not len(xs):
            continue
        ww = xs.max() - xs.min() + 1
        hh = ys.max() - ys.min() + 1
        # keep only blob-like gloves (roughly round, big enough)
        if comp.sum() >= 70 and min(ww, hh) >= 10 and max(ww, hh) / max(min(ww, hh), 1) < 2.4:
            keep |= comp
        elif comp.sum() >= 40 and direction in PROFILE:
            fx = PROFILE[direction]
            if (xs.mean() - g.head_cx) * fx > 6 and min(ww, hh) >= 8:
                keep |= comp
        elif comp.sum() >= 40 and abs(xs.mean() - g.head_cx) > 6 and min(ww, hh) >= 8:
            keep |= comp
    smear = red & chest & ~keep
    if smear.any():
        sk = loose_skinlike(out) & chest & ~smear & ~red
        fill = np.median(out[sk][:, :3], 0) if sk.any() else np.array([220, 160, 120])
        out[smear, :3] = fill
    return out



def scrub_profile_trails(body, g, waist, direction):
    """Erase thin red trails on the profile torso that aren't the main glove."""
    out = body.copy()
    h, w = out.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = out[..., 3] >= 128
    rgb = out[..., :3].astype(np.int32)
    red = a & (rgb[..., 0] > 160) & (rgb[..., 1] < 100) & (rgb[..., 0] - rgb[..., 1] > 80)
    fx = PROFILE[direction]
    # torso column near the body axis
    torso_x = (xx + 0.5 - g.head_cx) * fx < 3.0
    chest = (yy > g.neck + 2) & (yy < waist)
    # keep the large forward glove
    keep = np.zeros_like(red)
    for comp in components8(red):
        xs = np.nonzero(comp)[1]
        ys = np.nonzero(comp)[0]
        if not len(xs):
            continue
        ww = xs.max() - xs.min() + 1
        hh = ys.max() - ys.min() + 1
        if comp.sum() >= 70 and min(ww, hh) >= 10 and (xs.mean() - g.head_cx) * fx > 4:
            keep |= comp
    smear = red & chest & torso_x & ~keep
    # also any red component on chest with height<<width (horizontal smear)
    for comp in components8(red & chest & ~keep):
        ys, xs = np.nonzero(comp)
        if not len(xs):
            continue
        ww = xs.max() - xs.min() + 1
        hh = ys.max() - ys.min() + 1
        if hh <= 4 or (ww > hh * 2 and comp.sum() < 80):
            smear |= comp
    if smear.any():
        sk = loose_skinlike(out) & chest & ~smear & ~red
        fill = np.median(out[sk][:, :3], 0) if sk.any() else np.array([220, 160, 120])
        out[smear, :3] = fill
    return out


def boxify(frame, direction, anim, col, meta):
    f = pad_frame(frame)
    a = alpha_mask(f)
    if not a.any():
        return f
    g = Geometry(f)
    h, w = a.shape
    size = (h, w)
    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    tag = anim == "tag"
    side = TAG_SIDE[direction]
    bounce = bounce_of(anim, col, meta)

    if direction in PROFILE:
        sides = [side]
    else:
        sides = [1, -1]

    if tag:
        idle = pad_frame(meta["_base_idle"][direction])
        f = strip_arms(idle, Geometry(idle), direction, [side])
        g = Geometry(f)
    else:
        f = strip_arms(f, g, direction, sides)
        g = Geometry(f)

    waist = find_waist(f, g)
    rc, _ = recolor_chest(f, g, waist)
    rc = scrub_red_smears(rc, g, waist)
    skin = skin_rgb_of(f)
    gr = glove_radius(g)
    feet = foot_centers(f, g)

    # body plate
    base = premul(rc, np.ones((h, w)))
    # drawn trunks over the body (baggy, readable)
    trunks = down(trunks_layer(size, g, waist, direction))
    out = over(base, trunks)
    # high-top shoes
    shoes = shoes_layer(size, feet, direction)
    if shoes is not None:
        out = over(out, down(shoes))

    if tag:
        n = rng["count"]
        p = min(k, n - 1)
        if direction not in PROFILE:
            far = -side
            sh_f = shoulder(g, direction, far)
            hd_f = guard_hand(sh_f, direction, far, 0.0, gr)
            out = over(out, down(draw_arm(size, sh_f, hd_f, skin, gr, False)))
        sh_n = shoulder(g, direction, side)
        ang, R = jab_pose(direction, p, side)
        # tip of jab is the glove centre; add a touch so big glove clears body
        hd_n = (sh_n[0] + math.cos(ang) * R, sh_n[1] + math.sin(ang) * R)
        out = over(out, down(draw_arm(size, sh_n, hd_n, skin, gr * 1.05, True)))
    else:
        show = [side] if direction in PROFILE else [1, -1]
        for s in show:
            sh = shoulder(g, direction, s)
            hd = guard_hand(sh, direction, s, bounce, gr)
            out = over(out, down(draw_arm(size, sh, hd, skin, gr, False)))

    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    # final smear pass: saturated red on the chest (above waist) that is not
    # part of a large glove blob near the hands gets repainted as skin
    res = scrub_chest_red(res, g, waist, direction, side if tag else 0)
    if direction in PROFILE:
        res = scrub_profile_trails(res, g, waist, direction)
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 40:
                res[c] = 0
    res = solidify(res, (int(g.neck), int(g.hem) - 1))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    ap.add_argument("--scale", type=int, default=3)
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    ofw, ofh = fw + 2 * PAD_SIDE, fh + PAD_TOP
    out = np.zeros((len(dirs) * ofh, cols * ofw, 4), dtype=np.uint8)
    meta["_base_idle"] = {d: src[r * fh:(r + 1) * fh, 0:fw] for r, d in enumerate(dirs)}
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = boxify(
                fr, direction, anim_of(meta, c), c, meta)
    assert max(out.shape[:2]) <= 4096, out.shape
    Image.fromarray(out).save(ASSETS / "kid_boxer.png", optimize=True)
    pm = dict(meta)
    pm.pop("_base_idle", None)
    pm["image"] = "kid_boxer.png"
    pm["frameWidth"], pm["frameHeight"] = ofw, ofh
    pm["baselineY"] = meta["baselineY"] + PAD_TOP
    pm["anchorX"] = ofw // 2
    (ASSETS / "kid_boxer.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_boxer.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")

    if args.preview:
        img = Image.fromarray(out)
        scale, pad = args.scale, 40
        picks = [0, 4, 6, 10, 12, 16, 17, 18, 19, 20, 21, 24]
        pv = Image.new("RGBA", (pad + len(picks) * ofw * scale, pad + len(dirs) * ofh * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (ofw, ofh), (120, 170, 120, 255) if (r + i) % 2 else (100, 150, 100, 255))
                cell.alpha_composite(img.crop((c * ofw, r * ofh, (c + 1) * ofw, (r + 1) * ofh)))
                pv.paste(cell.resize((ofw * scale, ofh * scale), Image.NEAREST),
                         (pad + i * ofw * scale, pad + r * ofh * scale))
            d.text((4, pad + r * ofh * scale + 10), dirs[r], fill="white")
        for i, c in enumerate(picks):
            d.text((pad + i * ofw * scale + 4, 12), f"{anim_of(meta, c)} {c}", fill="white")
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
