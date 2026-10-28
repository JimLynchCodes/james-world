#!/usr/bin/env python3
"""Build the "Boxer James" sprite sheet (public/assets/kid_boxer.png/json)
from the base kid sheet.

Same smooth pipeline as make_tennis_skin.py: flat-colour class maps,
supersampled 4x, outlined, then box-downscaled.

  * James's real face and head, unchanged;
  * bare muscular chest (detailed pecs/abs shading) over his normal build;
  * shiny red boxing trunks with a gold waistband and gold/white side trim,
    baggy shorts, consistent every direction;
  * high-top boxing shoes in red / white / gold with laces;
  * big round glossy RED boxing gloves with white cuffs on BOTH hands in
    every frame (side views: near arm only). Idle / walk / breathe / run
    hold a high guard near the chin with a light boxer bounce;
  * tag is a quick JAB: the near (tagging) glove snaps straight forward in
    the facing direction and retracts over the 6 tag frames. The arm stays
    solid and attached at the shoulder in all 8 directions (NW mirrors NE).
    The torso keeps the idle outline; the far glove stays up in guard.

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
from make_wizard_skin import down, over, premul, to_u8, up_mask

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 10
PAD_SIDE = 28
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}

# outfit
TRUNK = (196, 28, 42)          # shiny deep red
TRUNK_SHADE = (140, 16, 28)
WAIST = (232, 198, 72)         # gold waistband
TRIM = (248, 236, 210)         # white/gold side trim
SHOE_RED = (210, 36, 48)
SHOE_WHITE = (246, 246, 244)
SHOE_GOLD = (220, 180, 56)
SOLE = (60, 48, 44)
LACE = (250, 250, 248)
LINE = (40, 26, 22)
SKIN_LINE = (120, 70, 50)

# gloves
GLOVE = (220, 32, 48)
GLOVE_SHADE = (150, 18, 30)
GLOVE_HI = (255, 120, 130)
CUFF = (248, 248, 246)
CUFF_SHADE = (210, 210, 214)
ARM_LINE = (40, 26, 22)


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
        n = 14
        for i in range(n + 1):
            t = i / n
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            r = r1 + (r2 - r1) * t
            d.ellipse([S(x - r), S(y - r), S(x + r), S(y + r)], fill=255)
    return fn


def disc_fn(c, r):
    return lambda d: d.ellipse([S(c[0] - r), S(c[1] - r), S(c[0] + r), S(c[1] + r)], fill=255)


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
    """Arm components on the given side (+1 right / -1 left). side=0 -> both."""
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
    silhouette stays solid. Head / face / neck pixels are never touched."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = f.copy()
    face = (yy <= g.neck + 1) & skin_mask(out)
    arms, _ = arms_and_hands(out, g, face)
    rm = np.zeros_like(arms)
    for s in sides:
        rm |= arm_comps_on(arms, g, direction, s)
    rm = grow(rm, alpha_mask(out), 1) & (yy > g.neck + 1)
    ai = alpha_mask(out)
    keep = ai & ~rm
    over_t = rm & ai & torso_hull(keep, rm, g)
    # always keep torso core
    ys = np.nonzero(ai.any(1))[0]
    if len(ys):
        hb = ys.max() - 6
        hem = np.nonzero(ai[max(0, hb - 8):hb])[1]
        if len(hem):
            hx = int(np.median(hem))
            core = max(2, (hem.max() - hem.min()) // 2 - 3)
            over_t |= rm & ai & (np.abs(xx - hx) <= core)
    # skin fill colour for chest (median lit skin)
    sk = skin_mask(out) & (yy > g.neck + 2) & (yy < g.hem - 4)
    if sk.any():
        px = out[sk][:, :3].astype(int)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 40)]
        chest_c = tuple(int(v) for v in np.median(px, 0)) if len(px) else (220, 160, 120)
    else:
        chest_c = (220, 160, 120)
    # shorts colour from navy region
    c = out[..., :3].astype(np.int32)
    navy = ai & ~loose_skinlike(out) & (c[..., 2] - c[..., 1] > 11) & (yy >= g.hem - 14)
    sh_c = tuple(int(v) for v in np.median(out[navy][:, :3], 0)) if navy.any() else TRUNK
    waist = int(g.hem - 10)
    if navy.any():
        waist = int(np.median(np.nonzero(navy)[0]) - 2)
    for msk, col in (((yy < waist), chest_c), ((yy >= waist), sh_c)):
        out[over_t & msk, :3] = col
        out[over_t & msk, 3] = 255
    out[rm & ~over_t] = 0
    # close row notches
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


def recolor(f, g):
    """Bare chest + shiny red trunks + red/white/gold high-tops. Head untouched."""
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
    navy = cloth & (b_ - g_ > 11)
    waist = g.hem - 12
    for y in range(g.neck + 6, g.hem):
        row = cloth[y] | skin[y]
        if row.sum() >= 4 and navy[y].sum() / max(row.sum(), 1) > 0.4:
            waist = y
            break
    shirt = cloth & (yy < waist)
    shorts = cloth & (yy >= waist) & (yy < g.hem + 1)
    shoes = cloth & (yy >= g.hem + 1)
    out = f.copy().astype(np.float64)

    # chest: paint shirt area as lit skin, then add pec/abs shading
    sk_src = skin & (yy > g.neck + 2) & (yy < waist)
    if sk_src.any():
        px = f[sk_src][:, :3].astype(float)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 45)]
        base_skin = np.median(px, 0) if len(px) else np.array([220.0, 160.0, 120.0])
    else:
        base_skin = np.array([220.0, 160.0, 120.0])
    if shirt.any():
        ref = np.percentile(lum[shirt], 75) or 1.0
        k = np.clip(0.78 + 0.28 * lum[shirt] / ref, 0.78, 1.06)
        out[shirt, :3] = base_skin[None] * k[:, None]
    # muscle detail on bare torso (shirt + existing skin between neck and waist)
    torso = (shirt | (skin & (yy > g.neck + 3) & (yy < waist))) & a & ~head
    if torso.any():
        cx = g.head_cx
        # pecs: two soft darker discs under the clavicle
        for sx in (-4.2, 4.2):
            d2 = ((xx + 0.5 - (cx + sx)) ** 2) / 18.0 + ((yy + 0.5 - (g.neck + 8.5)) ** 2) / 9.0
            pec = torso & (d2 < 1.0) & (yy > g.neck + 4) & (yy < g.neck + 14)
            out[pec, :3] *= 0.90
        # abs: three horizontal shade bands down the midline
        mid = torso & (np.abs(xx + 0.5 - cx) < 3.2) & (yy > g.neck + 14) & (yy < waist - 1)
        for by in (g.neck + 16, g.neck + 21, g.neck + 26):
            band = mid & (np.abs(yy - by) <= 1)
            out[band, :3] *= 0.86
        # midline crease
        crease = mid & (np.abs(xx + 0.5 - cx) < 0.8)
        out[crease, :3] *= 0.88
        # side serratus hint
        for sx in (-1, 1):
            side = torso & ((xx + 0.5 - cx) * sx > 5.5) & ((xx + 0.5 - cx) * sx < 8.5) & (yy > g.neck + 10) & (yy < waist - 2)
            out[side, :3] *= 0.92

    # trunks: shiny red with gold waistband and side trim
    def paint(m, col, lo=0.78, hi=1.05):
        if not m.any():
            return
        ref = np.percentile(lum[m], 80) or 1.0
        k = np.clip(lo + (hi - lo) * lum[m] / ref, lo, hi)
        out[m, :3] = np.array(col, float)[None] * k[:, None]

    paint(shorts, TRUNK, 0.82, 1.08)
    if shorts.any():
        # gold waistband (top 3 rows of shorts)
        top = shorts & (yy <= waist + 2)
        paint(top, WAIST, 0.88, 1.05)
        # side trim stripes
        for y in range(waist, g.hem + 1):
            xs = np.nonzero(shorts[y])[0]
            if len(xs) < 4:
                continue
            for edge in (xs.min(), xs.max()):
                for dx in range(-1, 2):
                    x = edge + dx
                    if 0 <= x < w and shorts[y, x]:
                        out[y, x, :3] = TRIM
        # shade lower hem of trunks
        bot = shorts & ~np.roll(shorts, -1, 0) & (yy > waist + 4)
        out[bot, :3] = TRUNK_SHADE

    # high-top shoes: red upper, white toe, gold trim, dark sole, white laces
    sole = np.zeros_like(shoes)
    for x in range(w):
        ys = np.nonzero(shoes[:, x] | (line[:, x] & (yy[:, x] > g.hem)))[0]
        if len(ys) and shoes[:, x].any():
            sole[ys.max() - 1:ys.max() + 1, x] = True
    # split each shoe into left/right components for toe/lace placement
    paint(shoes & ~sole, SHOE_RED, 0.85, 1.05)
    out[shoes & sole, :3] = SOLE
    for comp in components8(shoes & ~sole):
        if comp.sum() < 4:
            continue
        ys, xs = np.nonzero(comp)
        # white toe: forward-most third of the shoe (lower y is up)
        y_cut = ys.min() + max(1, int(0.45 * (ys.max() - ys.min() + 1)))
        toe = comp & (yy <= y_cut + 1)  # actually toe is front; use outer x of foot
        # approximate facing: for both feet use outer half as toe-ish white panel
        cx = xs.mean()
        # white cuff / tongue at top of high-top
        top_shoe = comp & (yy <= ys.min() + 2)
        out[top_shoe, :3] = SHOE_WHITE
        # gold mid stripe
        mid = comp & (yy >= ys.min() + 2) & (yy <= ys.min() + 4)
        out[mid, :3] = SHOE_GOLD
        # lace dots
        for ly in range(ys.min() + 1, min(ys.min() + 5, ys.max())):
            for lx in (int(cx) - 1, int(cx) + 1):
                if 0 <= lx < w and comp[ly, lx]:
                    out[ly, lx, :3] = LACE

    near_cloth = line & grow(shirt | shorts | shoes, a, 1) & ~head
    out[near_cloth, :3] = LINE
    return to_u8_simple(out)


def shoulder(g, direction, side):
    if direction in PROFILE:
        return (g.head_cx - PROFILE[direction] * 0.4, g.neck + 4.2)
    return (g.head_cx + (side or 1) * 7.2, g.neck + 4.2)


def guard_hand(sh, direction, side, bounce=0.0):
    """High guard near the chin."""
    if direction in PROFILE:
        fx = PROFILE[direction]
        return (sh[0] + fx * 5.5, sh[1] - 5.5 + bounce)
    # front / back: gloves float near cheeks
    out = (side or 1) * 5.0
    up = -6.0 if direction in FRONT or direction == "S" else -5.0
    if direction in BACK:
        up = -4.5
    return (sh[0] + out * 0.35, sh[1] + up + bounce)


# jab: reach (px from shoulder) and angle (deg, screen y-down) for +side
JAB_REACH = [9.5, 14.0, 20.0, 24.5, 16.0, 10.5]
JAB_ANG = {
    "profile": [-55, -32, -10, 2, -18, -48],
    "front":   [-68, -42, -18, -2, -24, -60],
    "back":    [-100, -78, -48, -22, -55, -92],
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
    R = JAB_REACH[p_idx]
    return math.radians(a), R


def glove_parts(sh, elbow, hand, skin, jabbing=False):
    """Upper arm + forearm + white cuff + big glossy red glove."""
    ex, ey = hand[0] - elbow[0], hand[1] - elbow[1]
    en = math.hypot(ex, ey) or 1.0
    ux, uy = ex / en, ey / en
    # cuff sits just behind the glove
    cuff_c = (hand[0] - ux * 4.2, hand[1] - uy * 4.2)
    wrist = (hand[0] - ux * 3.0, hand[1] - uy * 3.0)
    # highlight offset on glove (upper-leftish)
    hi = (hand[0] - 1.4, hand[1] - 1.6)
    shade = (hand[0] + 1.2, hand[1] + 1.4)
    gr = 5.8 if jabbing else 5.1
    return [
        (capsule_fn(sh, 3.1, elbow, 2.7), skin),
        (capsule_fn(elbow, 2.7, wrist, 2.4), skin),
        (capsule_fn(cuff_c, 2.9, wrist, 2.9), CUFF),
        (disc_fn(hand, gr), GLOVE),
        (disc_fn(shade, gr * 0.55), GLOVE_SHADE),
        (disc_fn(hi, gr * 0.32), GLOVE_HI),
        # cuff highlight ring suggestion
        (disc_fn(cuff_c, 2.2), CUFF),
        (capsule_fn(
            (cuff_c[0] + uy * 1.1, cuff_c[1] - ux * 1.1),
            1.0,
            (wrist[0] + uy * 1.1, wrist[1] - ux * 1.1),
            1.0), CUFF_SHADE),
    ]


def draw_arm(size, sh, hand, skin, jabbing=False):
    e1 = ik(sh, hand, 8.0, 7.6, 1)
    e2 = ik(sh, hand, 8.0, 7.6, -1)
    # prefer the elbow that bends "up" for a guard / jab look
    elbow = e1 if e1[1] <= e2[1] else e2
    if jabbing:
        # straighter arm on the jab: pick elbow closer to the line
        elbow = e1 if abs(e1[1] - (sh[1] + hand[1]) / 2) < abs(e2[1] - (sh[1] + hand[1]) / 2) else e2
    return shapes_layer(size, glove_parts(sh, elbow, hand, skin, jabbing), ARM_LINE, 1.15)


def skin_rgb_of(f):
    sk = skin_mask(f)
    if sk.any():
        px = f[sk][:, :3].astype(int)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 50)]
        rgb = tuple(int(v) for v in np.median(px, 0))
        return tuple(int(v * k) for v, k in zip(rgb, (0.96, 0.86, 0.80)))
    return (246, 182, 132)


def bounce_of(anim, col, meta):
    """Light vertical glove bob on walk / run."""
    if anim not in ("walk", "run"):
        return 0.0
    rng = meta["animations"][anim]
    k = col - rng["start"]
    # two-beat bounce
    return 1.2 * math.sin(k * math.pi / 2.0)


def boxify(frame, direction, anim, col, meta):
    f = pad_frame(frame)
    a = alpha_mask(f)
    if not a.any():
        return f
    g = Geometry(f)
    h, w = a.shape
    size = (h, w)
    yy = np.mgrid[0:h, 0:w][0]
    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    tag = anim == "tag"
    side = TAG_SIDE[direction]
    bounce = bounce_of(anim, col, meta)

    # which arms to strip from the base silhouette
    if direction in PROFILE:
        sides = [side]  # near only; far is hidden in the body
    else:
        sides = [1, -1]

    if tag:
        # steady idle body, near arm removed
        idle = pad_frame(meta["_base_idle"][direction])
        f = strip_arms(idle, Geometry(idle), direction, [side])
        g = Geometry(f)
    else:
        f = strip_arms(f, g, direction, sides)
        g = Geometry(f)

    rc = recolor(f, g)
    skin = skin_rgb_of(f)

    # composite: body first, then arms/gloves on top (back-view gloves go behind? no —
    # gloves are held in front of the chest even from the back for a readable guard)
    base = premul(rc, np.ones((h, w)))
    out = base

    if tag:
        n = rng["count"]
        p = min(k, n - 1)
        # far glove stays in guard (skip on pure profile — only near arm shows)
        if direction not in PROFILE:
            far = -side
            sh_f = shoulder(g, direction, far)
            hd_f = guard_hand(sh_f, direction, far, 0.0)
            out = over(out, down(draw_arm(size, sh_f, hd_f, skin, False)))
        # near jabbing arm
        sh_n = shoulder(g, direction, side)
        ang, R = jab_pose(direction, p, side)
        hd_n = (sh_n[0] + math.cos(ang) * R, sh_n[1] + math.sin(ang) * R)
        out = over(out, down(draw_arm(size, sh_n, hd_n, skin, True)))
    else:
        # guard: both gloves (or near only in profile)
        show = [side] if direction in PROFILE else [1, -1]
        for s in show:
            sh = shoulder(g, direction, s)
            hd = guard_hand(sh, direction, s, bounce)
            out = over(out, down(draw_arm(size, sh, hd, skin, False)))

    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 30:
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
