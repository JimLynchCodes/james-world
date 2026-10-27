#!/usr/bin/env python3
"""Build the "Billy" sprite sheet (public/assets/kid_billy.png/json): James's
friend Billy, the first non-James character, on the base kid rig.

Pipeline (same family as make_tennis_skin.py):
  * every base kid frame is split into flat-colour classes (hair, skin, hand,
    sleeve, jacket, pants, shoe), James's own outline pixels going to the
    nearest class;
  * the classes are warped into an adult build: the head at 0.82x, the body
    below the neck 1.42x taller and 1.2x wider (stocky), about a fixed point
    per direction, so the bob / swing of every base animation is kept and the
    torso is the same build in all 8 directions;
  * rendered at 4x (smooth fields, seams between classes, one outline), then
    the details are drawn on top at 4x: a newly drawn face (black rectangular
    glasses, brows, mustache, chin patch, toothy smile), the open black zip
    jacket over a grey hoodie (zip strip, flap chest pockets, hood collar),
    black pants, black sneakers with white soles;
  * a clear iced coffee (tan coffee, ice, dome lid, orange straw, small
    orange/pink logo dot) in his near hand in every frame; on tag the near arm
    is redrawn as one solid limb from the shoulder: it reaches the cup out in
    the facing direction, pulls it back, sips from the straw and lets out a
    small "ahh" puff;
  * box-downscaled to 1x and solidified (no holes).

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_billy_skin.py [--preview /tmp/billy_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from make_banana_skin import Geometry, alpha_mask, arms_and_hands, components8, fill_holes, grow, skin_mask
from make_pirate_skin import TAG_SIDE, anim_of, pick_hand
from make_tennis_skin import capsule_fn, disc_fn, ik, loose_skinlike, shapes_layer, tag_base
from make_wizard_skin import down, over, to_u8
from solid_mask import solidify

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

SS = 4
OW, OH = 128, 124          # output frame
OBASE = 118                # feet line in the output frame
SRC_BASE = 96              # feet line in kid.png
SRC_CX = 40
HS = 0.82                  # head scale
BSY = 1.42                 # body: taller ...
BSX = 1.2                  # ... and stocky

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}
# facing: screen x and "toward the viewer"
FACE = {"E": (1, 0), "SE": (0.7, 0.7), "S": (0, 1), "SW": (-0.7, 0.7),
        "W": (-1, 0), "NW": (-0.7, -0.7), "N": (0, -1), "NE": (0.7, -0.7)}

BG, HAIR, SKIN, HAND, SLEEVE, JACKET, PANTS, SHOE = range(8)
COL = {
    HAIR: (46, 40, 40),
    SKIN: (206, 152, 122),
    HAND: (206, 152, 122),
    SLEEVE: (76, 78, 90),
    JACKET: (76, 78, 90),
    PANTS: (24, 24, 28),
    SHOE: (30, 30, 34),
}
LINE = (10, 10, 13)
SKIN_LINE = (96, 58, 40)
SKIN_SHADE = (184, 128, 100)
SOLE = (240, 240, 234)
SHIRT = (132, 134, 141)
SHIRT_DARK = (104, 106, 114)
POCKET = (96, 98, 112)
POCKET_HI = (128, 131, 146)
ZIP = (170, 173, 182)
HEM = (62, 64, 75)
PANTS_BACK = (16, 16, 19)
HAIR_HI = (100, 86, 78)
GLASS = (14, 14, 17)
BROW = (22, 18, 18)
STACHE = (40, 30, 28)
TEETH = (250, 248, 240)
EYE = (30, 24, 26)
# cup
CUP_LINE = (92, 104, 118)
COFFEE = (198, 148, 100)
COFFEE_LIGHT = (222, 190, 150)
ICE = (234, 240, 244)
LID = (242, 246, 250)
STRAW = (255, 116, 18)
STRAW_LINE = (178, 64, 8)
LOGO_O = (246, 128, 40)
LOGO_P = (238, 96, 152)
PUFF = (252, 252, 254)
PUFF_LINE = (196, 204, 216)
SPARK = (255, 234, 130)


def S(v):
    return v * SS


# --- source classes -----------------------------------------------------------------
def classify(f, g, direction=None, eye_y=None):
    """1x label map of a base kid frame (outline pixels -> nearest class)."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = alpha_mask(f)
    c = f[..., :3].astype(np.int32)
    lum = c.mean(-1)
    r_, g_, b_ = c[..., 0], c[..., 1], c[..., 2]
    skin = loose_skinlike(f) & a
    line = (lum < 30) & a
    head = (yy <= g.neck + 1) & a
    lab = np.zeros((h, w), np.uint8)
    # face: James's lit skin (strict), holes (eyes, brows, mouth) closed;
    # the brown hair is darker and stays hair
    strict = skin_mask(f) & head
    strict = grow(strict, head & loose_skinlike(f) & (lum > 120), 1) | strict
    face = fill_holes(strict) & head
    tee_col = (b_ - r_ > 4) & (lum > 40) & (lum < 140)
    collar = head & ~face & (yy > g.neck - 3) & tee_col
    lab[head & ~face & ~line] = HAIR
    lab[face] = SKIN
    lab[collar] = JACKET
    # short hair: James's side/jaw hair below the brow line becomes cheek
    if eye_y is not None and direction not in BACK:
        low = head & (yy > eye_y - 2) & (yy <= g.neck - 1) & (lab == HAIR) & ~line
        if direction in PROFILE:
            fx = FACE[direction][0]
            low &= fx * (xx - g.head_cx) > -1.5
        lab[low] = SKIN
    body = a & (yy > g.neck + 1)
    face_i = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face_i)
    hands &= body
    cloth = body & ~skin & ~arms & ~line
    navy = cloth & (b_ - g_ > 11)
    waist = g.hem - 12
    for y in range(g.neck + 6, g.hem):
        row = cloth[y] | skin[y]
        if row.sum() >= 4 and navy[y].sum() / row.sum() > 0.4:
            waist = y
            break
    lab[cloth & (yy < waist)] = JACKET
    lab[cloth & (yy >= waist) & (yy < g.hem + 1)] = PANTS
    lab[cloth & (yy >= g.hem + 1)] = SHOE
    legs = body & skin & ~arms & (yy >= waist)
    lab[legs] = PANTS
    neck = body & skin & ~arms & (yy < waist)
    lab[neck] = SKIN
    lab[arms & body & ~line] = SLEEVE
    lab[hands & ~line] = HAND
    # outline / unlabelled opaque pixels: take the most common labelled neighbour
    todo = a & (lab == BG)
    for _ in range(6):
        if not todo.any():
            break
        votes = np.zeros((9, h, w), np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                n = np.roll(lab, (dy, dx), (0, 1))
                for k in range(1, 8):
                    votes[k] += n == k
        best = votes[1:].argmax(0) + 1
        has = votes[1:].max(0) > 0
        fill = todo & has
        # feet outline: shoes, not pants
        lab[fill] = best[fill]
        todo = a & (lab == BG)
    lab[todo] = JACKET
    return lab


# --- the warp -------------------------------------------------------------------------
class Warp:
    """Fixed per direction: head scaled HS about (hcx, yn), body BSX x BSY
    about the feet line, joined at the neck row yn."""

    def __init__(self, hcx, yn):
        self.hcx, self.yn = hcx, yn
        self.hcx_o = OW / 2 + (hcx - SRC_CX)
        self.yn_o = OBASE - (SRC_BASE - yn) * BSY

    def sx(self, y):
        t = np.clip((y - (self.yn - 2.0)) / 5.0, 0, 1)
        t = t * t * (3 - 2 * t)
        return HS + (BSX - HS) * t

    def fwd(self, x, y):
        Y = np.where(y >= self.yn, self.yn_o + (y - self.yn) * BSY, self.yn_o - (self.yn - y) * HS)
        X = self.hcx_o + (x - self.hcx) * self.sx(y)
        return X, Y

    def inv(self, X, Y):
        y = np.where(Y >= self.yn_o, self.yn + (Y - self.yn_o) / BSY, self.yn - (self.yn_o - Y) / HS)
        x = self.hcx + (X - self.hcx_o) / self.sx(y)
        return x, y

    def pt(self, p):
        X, Y = self.fwd(np.float64(p[0]), np.float64(p[1]))
        return float(X), float(Y)


def bilinear(m, x, y):
    """sample float image m (pixel centres at i+.5) at float coords"""
    h, w = m.shape
    fx, fy = x - 0.5, y - 0.5
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - x0, fy - y0
    out = 0
    for oy, wy in ((0, 1 - ty), (1, ty)):
        for ox, wx in ((0, 1 - tx), (1, tx)):
            xi, yi = x0 + ox, y0 + oy
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            v = np.where(ok, m[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], 0.0)
            out = out + v * wx * wy
    return out


_GRID = None


def grid():
    global _GRID
    if _GRID is None:
        Y, X = np.mgrid[0:OH * SS, 0:OW * SS]
        _GRID = ((X + 0.5) / SS, (Y + 0.5) / SS)
    return _GRID


def render_body(lab, wp):
    """warped class map at SS -> (label SS, union SS, rgb SS, outline SS)"""
    X, Y = grid()
    xs, ys = wp.inv(X, Y)
    fields = []
    for k in range(1, 8):
        m = (lab == k).astype(np.float64)
        if not m.any():
            fields.append(np.zeros(X.shape))
            continue
        v = bilinear(m, xs, ys)
        im = Image.fromarray(np.clip(v * 255, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(SS * 0.5))
        fields.append(np.asarray(im).astype(np.float64) / 255)
    F = np.stack(fields)
    union = F.sum(0) >= 0.5
    L = F.argmax(0) + 1
    L[~union] = BG
    # close small notches in the jacket silhouette (between neck and hem)
    J = np.isin(L, (JACKET, SLEEVE))
    if J.any():
        jr = np.nonzero(J.any(1))[0]
        k = 2 * SS + 1
        u8 = Image.fromarray((union * 255).astype(np.uint8))
        closed = np.asarray(u8.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))) > 127
        band = np.zeros_like(union)
        band[max(int(S(wp.yn_o + 3)), jr.min()):jr.max() - SS] = True
        add = closed & ~union & band
        L[add] = JACKET
        union |= add
    rgb = np.zeros(X.shape + (3,), np.uint8)
    for k, col in COL.items():
        rgb[L == k] = col
    seam = np.zeros_like(union)
    for dy, dx in ((0, 1), (1, 0)):
        seam |= np.roll(L, (dy, dx), (0, 1)) != L
    seam = np.asarray(Image.fromarray((seam * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 127
    seam &= union
    # hand/sleeve and skin/hand are one limb colour family: thin skin line
    rgb[seam] = LINE
    sk_seam = seam & np.isin(L, (SKIN, HAND)) & np.isin(np.roll(L, 1, 1), (SKIN, HAND)) & np.isin(np.roll(L, 1, 0), (SKIN, HAND))
    rgb[sk_seam] = COL[SKIN]
    sil = Image.fromarray((union * 255).astype(np.uint8))
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(int(round(0.8 * SS)) * 2 + 1))) > 127
    outline = union & ~inner
    rgb[outline] = LINE
    sk_out = outline & np.isin(L, (SKIN, HAND))
    rgb[sk_out] = SKIN_LINE
    return L, union, rgb, outline | seam



# --- adult head (replaces the kid's warped head) ------------------------------------
def _rbox_sdf(X, Y, cx, cy, hw, hh, r):
    qx = np.abs(X - cx) - hw + r
    qy = np.abs(Y - cy) - hh + r
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def rebuild_head(L, rgb, union, direction, wp, eyes_o):
    """Swap the warped kid head (tall hair peak) for a rounder adult head with
    short neat hair. Works at SS on L/rgb/union in place; returns the head
    mask (SS)."""
    H, W = L.shape
    Y, X = np.mgrid[0:H, 0:W]
    Xo, Yo = (X + 0.5) / SS, (Y + 0.5) / SS
    old = np.isin(L, (HAIR, SKIN)) & (Yo < wp.yn_o)
    if not old.any():
        return old
    widths = old.sum(1)
    mw = widths.max()
    rows = np.nonzero(widths >= 0.72 * mw)[0]
    ys = np.nonzero(old.any(1))[0]
    top = rows.min() / SS - 1.2
    bot = ys.max() / SS + 0.3
    xs = np.nonzero(old[rows].any(0))[0]
    cxs = [np.nonzero(old[y])[0] for y in rows]
    cx = float(np.median([(c.min() + c.max() + 1) / 2 for c in cxs])) / SS
    hw = mw / SS / 2 * 1.0
    if eyes_o and direction not in BACK:
        ey_m = float(np.mean([e[1] for e in eyes_o]))
        bot = max(bot, ey_m + 9.6)
        top = min(top, ey_m - 10.8)
        hw = min(hw, (bot - top) / 1.26 / 2) if direction not in PROFILE else min(hw, (bot - top) / 1.12 / 2)
    hh = (bot - top) / 2
    cy = (top + bot) / 2
    fx = FACE[direction][0]
    # jaw a touch narrower than the cranium
    t = np.clip((Yo - cy) / hh, 0, 1)
    Xs = cx + (Xo - cx) / (1 - 0.2 * t * t)
    sdf = _rbox_sdf(Xs, Yo, cx, cy, hw, hh, hw * 0.96)
    head = sdf < 0
    # erase the old head
    L[old] = BG
    union[old] = False
    if direction in PROFILE:
        ey = eyes_o[0][1] if eyes_o else top + 0.55 * (bot - top)
        nose = ((Xo - (cx + fx * (hw + 0.2))) / 1.1) ** 2 + ((Yo - (ey + 2.6)) / 1.4) ** 2 < 1
        head |= nose
    hair_cap = _rbox_sdf(Xs, Yo, cx, cy - 0.35, hw + 0.45, hh + 0.65, (hw + 0.45) * 0.96) < 0
    if direction in BACK:
        hl = top + 0.74 * (bot - top)
        hair = hair_cap & (Yo < hl + 1.2 * np.cos(np.clip((Xo - cx) / hw, -1, 1) * 1.4))
        ear_y = top + 0.55 * (bot - top)
        ears = [(cx - hw - 0.5, ear_y), (cx + hw + 0.5, ear_y)]
    elif direction in PROFILE:
        ey = eyes_o[0][1] if eyes_o else top + 0.55 * (bot - top)
        hl = ey - 6.2
        back = fx * (Xo - cx) < -hw * 0.5
        hair = hair_cap & ((Yo < hl + 1.6 * np.clip(-fx * (Xo - cx) / hw, 0, 1)) | (back & (Yo < ey + 2.0)))
        ears = [(cx - fx * hw * 0.22, ey + 1.0)]
    else:
        ey = np.mean([e[1] for e in eyes_o]) if eyes_o else top + 0.55 * (bot - top)
        ph_ = ((Xo - cx + 0.6 * fx) / 2.6) % 1
        hl = ey - 8.3 + 0.8 * np.clip((Xo - (cx - 0.3 * hw)) / hw, -1, 1) + 1.8 * (1 - ph_) ** 1.6
        edge = np.clip((np.abs(Xo - (cx + fx * 0.8)) / hw - 0.74) / 0.26, 0, 1)
        hair = hair_cap & (Yo < hl + 3.4 * edge)
        ears = [(cx - hw - 0.1, ey + 0.8), (cx + hw + 0.1, ey + 0.8)]
        if fx:
            ears = [ears[0] if fx > 0 else ears[1]]  # the far ear is hidden in 3/4
    # messy tufts sticking up along the crown (a fixed pattern per view)
    rng = np.random.RandomState(7 + len(direction) * 3 + (fx > 0))
    tuft = np.zeros_like(head)
    for i in range(7):
        tx = cx + (i - 3) * hw * 0.3 + rng.uniform(-0.4, 0.4)
        ty = top + 0.25 + 0.9 * ((i - 3) / 3.0) ** 2 * hh * 0.35
        rx_, ry_ = rng.uniform(1.3, 1.9), rng.uniform(1.1, 1.6)
        tuft |= ((Xo - tx) / rx_) ** 2 + ((Yo - ty) / ry_) ** 2 < 1
    hair |= tuft & (Yo < top + hh * 0.7)
    ear = np.zeros_like(head)
    for ex_, ey_ in ears:
        ear |= ((Xo - ex_) / 1.3) ** 2 + ((Yo - ey_) / 1.9) ** 2 < 1
    allm = head | hair | ear
    # do not grow over the body below the chin
    allm &= Yo < bot + 0.6
    skinm = (head & ~hair) | ear
    L[allm & skinm] = SKIN
    L[allm & ~skinm] = HAIR
    union |= allm
    rgb[allm & skinm] = COL[SKIN]
    rgb[allm & ~skinm] = COL[HAIR]
    # hair texture: a side part and a few flat highlight strands (no noise)
    tex = Image.new("L", (W, H), 0)
    td = ImageDraw.Draw(tex)
    px = cx - 0.35 * hw * (1 if fx >= 0 else -1) if direction not in PROFILE else cx - fx * 0.2 * hw
    strands = []
    rows_ = [0.0] + ([0.3, 0.55] if direction in BACK else [])
    for j, rr in [(j, rr) for rr in rows_ for j in range(-3, 4)]:
        sx = px + j * hw * 0.24 + rr * 3
        if rr:
            strands.append([(sx, top + rr * 2 * hh), (sx + 0.8, top + rr * 2 * hh + 1.6), (sx + 0.6, top + rr * 2 * hh + 3.0)])
            continue
        sgn = -1 if sx < px else 1
        strands.append([(sx, top + 1.0 + 0.2 * abs(j)), (sx + sgn * 1.4, top + 2.6), (sx + sgn * 2.4, top + 3.9)])
    for st in strands:
        td.line([(S(a), S(b)) for a, b in st], fill=255, width=max(1, int(S(0.7))), joint="curve")
    hm_ = (np.asarray(tex) > 127) & hair & allm
    rgb[hm_] = HAIR_HI
    if direction not in PROFILE:
        part = Image.new("L", (W, H), 0)
        ImageDraw.Draw(part).line([(S(px), S(top + 0.6)), (S(px - 0.3), S(top + 3.6))], fill=255, width=max(1, int(S(0.55))))
        rgb[(np.asarray(part) > 127) & hair & allm] = LINE
    for ex_, ey_ in ears:
        inner_e = ((Xo - ex_) / 0.6) ** 2 + ((Yo - ey_) / 1.0) ** 2 < 1
        rgb[inner_e & allm & ~hair] = SKIN_SHADE
    # outlines: head silhouette, ear edge, hairline
    u8 = Image.fromarray((allm * 255).astype(np.uint8))
    k = int(round(0.8 * SS)) * 2 + 1
    inner = np.asarray(u8.filter(ImageFilter.MinFilter(k))) > 127
    out_ = allm & ~inner
    rgb[out_ & ~skinm] = LINE
    rgb[out_ & skinm] = SKIN_LINE
    em = Image.fromarray((ear * 255).astype(np.uint8))
    ein = np.asarray(em.filter(ImageFilter.MinFilter(k - 2))) > 127
    rgb[ear & ~ein & ~hair] = SKIN_LINE
    hs = Image.fromarray((hair * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))
    hline = (np.asarray(hs) > 127) & ~hair & skinm & allm
    rgb[hline] = LINE
    # the neck: chin line over the neck top
    return allm


# --- clean profile legs -----------------------------------------------------------------
def feet_of(lab):
    sh = lab == SHOE
    comps = [c for c in components8(sh) if c.sum() >= 3]
    feet = []
    for c in comps:
        ys, xs = np.nonzero(c)
        if xs.max() - xs.min() + 1 >= 11:
            mid = np.median(xs)
            for part in (xs < mid, xs >= mid):
                feet.append((float(xs[part].mean() + 0.5), float(ys[part].max() + 1)))
        else:
            feet.append((float(xs.mean() + 0.5), float(ys.max() + 1)))
    return feet


def leg_layer(hip, foot, fx, back, L_leg):
    ankle = (foot[0] - fx * 0.8, foot[1] - 2.7)
    knee = ik(hip, ankle, L_leg * 0.5, L_leg * 0.5, -fx)
    pc = PANTS_BACK if back else COL[PANTS]
    toe = (foot[0] + fx * 2.5, foot[1] - 1.5)
    heel = (foot[0] - fx * 1.4, foot[1] - 1.7)
    parts = [
        (capsule_fn(hip, 3.4, knee, 2.9), pc),
        (capsule_fn(knee, 2.9, ankle, 2.5), pc),
        (capsule_fn(heel, 1.75, toe, 1.55), COL[SHOE]),
    ]
    im = shapes_layer((OH, OW), parts, LINE, 0.75)
    arr = np.asarray(im).copy()
    Yi = np.mgrid[0:arr.shape[0], 0:arr.shape[1]][0]
    Xi = np.mgrid[0:arr.shape[0], 0:arr.shape[1]][1]
    sole = (arr[..., 3] > 0) & (Yi > S(foot[1] - 1.1)) & (Yi < S(foot[1] - 0.55)) & \
           (np.abs(Xi - S((heel[0] + toe[0]) / 2)) < S(3.2))
    arr[sole, :3] = SOLE
    return Image.fromarray(arr, "RGBA")


def lean(f, dx, g):
    """shear the upper body by dx px at the head (0 at the hem)"""
    if abs(dx) < 0.5:
        return f
    out = np.zeros_like(f)
    for y in range(f.shape[0]):
        t = np.clip((g.hem - y) / max(1, g.hem - g.top), 0, 1)
        sft = int(round(dx * t))
        out[y] = np.roll(f[y], sft, 0)
    return out


# --- details --------------------------------------------------------------------------
def eyes_of(f, g):
    h, w = f.shape[:2]
    yy = np.mgrid[0:h, 0:w][0]
    c = f[..., :3].astype(int)
    wm = alpha_mask(f) & (c.min(-1) > 196) & (yy < g.neck) & (yy > g.top + 15)
    out = []
    for comp in components8(wm):
        if comp.sum() < 3:
            continue
        ys, xs = np.nonzero(comp)
        out.append((xs.mean() + 0.5, ys.mean() + 0.5, xs.max() - xs.min() + 1))
    return sorted(out)


def rrect(d, x0, y0, x1, y1, r, width, col):
    d.rounded_rectangle([S(x0), S(y0), S(x1), S(y1)], radius=S(r), outline=col, width=max(1, int(round(S(width)))))


def tline(d, pts, col, width):
    d.line([(S(x), S(y)) for x, y in pts], fill=col, width=max(1, int(round(S(width)))), joint="curve")


def ell(d, cx, cy, rx, ry, col, outline=None, width=0.5):
    d.ellipse([S(cx - rx), S(cy - ry), S(cx + rx), S(cy + ry)], fill=col,
              outline=outline, width=max(1, int(round(S(width)))) if outline else 0)


CHEEK = (200, 142, 112)
LENS = (214, 166, 138)
MOUTH = (96, 34, 34)


def _blend(c, k, t):
    return tuple(int(round(a * (1 - t) + b * t)) for a, b in zip(c, k))


def smile_eye(d, ex, ey, hw):
    """a natural open eye: white, dark-brown iris with a pupil and catchlight,
    and a soft upper lid line"""
    ell(d, ex, ey, hw * 1.05, 1.0, (250, 248, 244))
    ell(d, ex, ey + 0.05, 0.62, 0.72, (60, 38, 28))
    ell(d, ex, ey + 0.05, 0.3, 0.34, (18, 14, 14))
    ell(d, ex - 0.25, ey - 0.3, 0.2, 0.2, (255, 255, 255))
    d.arc([S(ex - hw - 0.1), S(ey - 1.05), S(ex + hw + 0.1), S(ey + 1.0)], 190, 350, fill=EYE, width=max(1, int(S(0.5))))


def draw_face(img, L, direction, eyes_o, wp, head_box):
    """detailed face over the flat skin (at SS): returns the mouth point (out px)"""
    d = ImageDraw.Draw(img)
    fx = FACE[direction][0]
    x0, y0, x1, y1 = head_box
    if direction in BACK:
        return ((x0 + x1) / 2 + fx * 3, y0 + 0.72 * (y1 - y0))
    W_ = lambda v: max(1, int(round(S(v))))
    if direction in FRONT:
        if len(eyes_o) >= 2:
            (lx, ly, lw), (rx, ry, rw) = eyes_o[0], eyes_o[-1]
        elif eyes_o:
            ex, ey, ew = eyes_o[0]
            lx, ly, lw, rx, ry, rw = ex - 5, ey, ew, ex + 5, ey, ew
        else:
            return None
        ey = (ly + ry) / 2
        sp = float(np.clip(rx - lx, 6.2, 6.6))
        mid = (lx + rx) / 2 + fx * 0.3
        lx, rx = mid - sp / 2, mid + sp / 2
        hw_l = 2.4 * (0.8 if fx > 0 else 1.0)
        hw_r = 2.4 * (0.8 if fx < 0 else 1.0)
        mx = mid + fx * 0.9
        my = ey + 6.4
        # full rounded cheeks: soft flat shade
        for ex, hw in ((lx, hw_l), (rx, hw_r)):
            ell(d, ex + (ex - mid) * 0.15, ey + 4.0, hw * 0.55, 1.1, CHEEK)
        # broad nose
        ell(d, mx, ey + 3.4, 1.5, 1.0, SKIN_SHADE)
        ell(d, mx, ey + 2.8, 0.8, 0.6, COL[SKIN])
        for k in (-1, 1):
            ell(d, mx + k * 0.8, ey + 3.95, 0.38, 0.3, SKIN_LINE)
        # lenses (warm tint) with the smiling eyes behind them
        for ex, hw in ((lx, hw_l), (rx, hw_r)):
            d.rounded_rectangle([S(ex - hw), S(ey - 1.9), S(ex + hw), S(ey + 1.8)], radius=S(0.6), fill=LENS)
            smile_eye(d, ex + fx * 0.3, ey + 0.1, hw * 0.62)
        # defined dark eyebrows, slightly arched
        for ex, hw, sg in ((lx, hw_l, -1), (rx, hw_r, 1)):
            tline(d, [(ex - sg * hw * 0.8, ey - 3.75), (ex + sg * hw * 0.1, ey - 4.15), (ex + sg * hw * 0.95, ey - 3.55)], BROW, 1.2)
        # thick black rectangular frames + bridge + temples
        for ex, hw in ((lx, hw_l), (rx, hw_r)):
            d.rounded_rectangle([S(ex - hw), S(ey - 1.9), S(ex + hw), S(ey + 1.8)], radius=S(0.6), outline=GLASS, width=W_(0.8))
            # glint
            tline(d, [(ex + hw * 0.35, ey - 1.0), (ex + hw * 0.62, ey - 1.0)], (235, 240, 245), 0.5)
        tline(d, [(lx + hw_l - 0.2, ey - 1.0), (mid, ey - 1.35), (rx - hw_r + 0.2, ey - 1.0)], GLASS, 1.2)
        tline(d, [(lx - hw_l, ey - 1.2), (max(x0 + 0.4, lx - hw_l - 2.4), ey - 1.5)], GLASS, 1.1)
        tline(d, [(rx + hw_r, ey - 1.2), (min(x1 - 0.4, rx + hw_r + 2.4), ey - 1.5)], GLASS, 1.1)
        # wide toothy smile
        mw = 3.3 if fx == 0 else 2.9
        def curve(y_end, y_mid, n=9):
            return [(mx + mw * t, my + y_end + (y_mid - y_end) * (1 - t * t)) for t in np.linspace(-1, 1, n)]
        top_c = curve(-0.55, 0.05)
        bot_c = curve(-0.55, 1.45)
        mid_c = curve(-0.45, 0.75)
        d.polygon([(S(x), S(y)) for x, y in top_c + bot_c[::-1]], fill=MOUTH)
        d.polygon([(S(x), S(y)) for x, y in top_c + mid_c[::-1]], fill=TEETH)
        tline(d, bot_c[1:-1], SKIN_LINE, 0.4)
        # thin dark mustache, a small chin patch
        tline(d, [(mx - mw * 0.95, my - 0.75), (mx - mw * 0.5, my - 1.15), (mx, my - 1.05),
                  (mx + mw * 0.5, my - 1.15), (mx + mw * 0.95, my - 0.75)], STACHE, 0.85)
        ell(d, mx, my + 3.7, 0.8, 0.6, STACHE)
        return (mx, my)
    # profile
    if not eyes_o:
        return None
    ex, ey, _ = eyes_o[0]
    ex += fx * 0.2
    my = ey + 6.4
    yi = int(S(my))
    row = np.nonzero(np.isin(L[yi], (SKIN,)))[0]
    front = ((row.max() if fx > 0 else row.min()) / SS) if len(row) else ex + fx * 4
    mx = front - fx * 1.7
    # cheek and nose shade
    ell(d, ex - fx * 0.6, ey + 4.2, 2.0, 1.5, CHEEK)
    ell(d, ex + fx * 2.6, ey + 3.3, 1.2, 0.9, SKIN_SHADE)
    ell(d, ex + fx * 2.4, ey + 3.7, 0.35, 0.28, SKIN_LINE)
    lx0, lx1 = sorted((ex - fx * 1.6, ex + fx * 1.4))
    d.rounded_rectangle([S(lx0), S(ey - 2.0), S(lx1), S(ey + 1.9)], radius=S(0.5), fill=LENS)
    smile_eye(d, ex + fx * 0.3, ey + 0.1, 0.8)
    tline(d, [(ex - fx * 1.7, ey - 3.1), (ex, ey - 3.7), (ex + fx * 1.6, ey - 3.4)], BROW, 1.25)
    d.rounded_rectangle([S(lx0), S(ey - 2.0), S(lx1), S(ey + 1.9)], radius=S(0.5), outline=GLASS, width=W_(0.95))
    tline(d, [(ex + fx * 0.3, ey - 1.15), (ex + fx * 0.9, ey - 1.15)], (255, 255, 255), 0.45)
    # glasses arm back to the ear
    tline(d, [(ex - fx * 1.6, ey - 1.0), (wp.hcx_o + fx * 0.2, ey - 1.5)], GLASS, 0.9)
    # smile, mustache, chin patch
    a0, a1 = sorted((mx, mx - fx * 2.6))
    d.chord([S(a0), S(my - 1.0), S(a1), S(my + 1.3)], 0, 180, fill=MOUTH)
    d.chord([S(a0 + 0.3), S(my - 0.9), S(a1 - 0.3), S(my + 0.6)], 0, 180, fill=TEETH)
    tline(d, [(mx - fx * 3.0, my + 0.4), (mx - fx * 3.2, my - 0.1)], SKIN_LINE, 0.45)
    tline(d, [(mx - fx * 3.0, my - 0.3), (mx - fx * 1.3, my - 1.15), (mx + fx * 0.4, my - 0.85)], STACHE, 0.85)
    ell(d, mx - fx * 1.1, my + 3.2, 0.9, 0.72, STACHE)
    return (mx, my)


def torso_details(rgb, L, outline, direction, wp):
    """open zip jacket over the grey hoodie: zip strip, chest pockets, hood"""
    J = L == JACKET
    if not J.any():
        return
    ys = np.nonzero(J.any(1))[0]
    top = ys.min() / SS
    bot = ys.max() / SS
    h, w = L.shape
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fx = FACE[direction][0]
    cx = wp.hcx_o + fx * 2.0
    if direction in FRONT:
        hw = 2.3 if fx == 0 else 1.9
        d.polygon([(S(cx - hw + 0.4), S(top)), (S(cx + hw - 0.4), S(top)),
                   (S(cx + hw), S(bot + 1)), (S(cx - hw), S(bot + 1))], fill=SHIRT)
        for sd in (-1, 1):
            tline(d, [(cx + sd * (hw - 0.2), top + 1), (cx + sd * hw, bot + 1)], LINE, 0.7)
        tline(d, [(cx, top + 3.5), (cx, bot)], SHIRT_DARK, 0.5)
        # zip teeth along both jacket edges
        for sd in (-1, 1):
            tline(d, [(cx + sd * (hw + 0.55), top + 2), (cx + sd * (hw + 0.75), bot - 0.5)], ZIP, 0.45)
        # hood collar round the neck
        ell(d, cx - fx * 0.5, top + 0.6, 6.6 - abs(fx) * 1.2, 2.4, SHIRT, LINE, 0.6)
        # chest pockets with flaps
        for sd in (-1, 1):
            k = 0.72 if sd * fx < 0 else 1.0
            pc = cx + sd * (hw + 3.6 * k)
            py = top + 7.5
            pw = 2.6 * k
            d.rectangle([S(pc - pw), S(py - 1.2), S(pc + pw), S(py + 3.2)], outline=POCKET, width=max(1, int(S(0.5))))
            d.rectangle([S(pc - pw), S(py - 1.2), S(pc + pw), S(py + 0.6)], fill=POCKET)
            tline(d, [(pc - pw + 0.3, py - 1.0), (pc + pw - 0.3, py - 1.0)], POCKET_HI, 0.45)
            ell(d, pc, py + 0.2, 0.45, 0.45, ZIP)
    elif direction in BACK:
        ell(d, wp.hcx_o + fx * 1.0, top + 2.6, 6.4, 3.6, SHIRT, LINE, 0.6)
        tline(d, [(wp.hcx_o - 3.5, top + 3.0), (wp.hcx_o + fx * 1.0, top + 5.2), (wp.hcx_o + 3.5, top + 3.0)], SHIRT_DARK, 0.5)
    else:
        ell(d, wp.hcx_o - fx * 4.0, top + 2.2, 3.2, 3.0, SHIRT, LINE, 0.6)
        tline(d, [(wp.hcx_o + fx * 3.2, top + 4), (wp.hcx_o + fx * 3.4, bot - 1)], (70, 72, 82), 0.5)
    arr = np.asarray(im)
    m = (arr[..., 3] > 127) & J & ~outline
    rgb[m] = arr[m, :3]
    # ribbed hem band just above the jacket bottom: a clear waistline
    yy = np.mgrid[0:h, 0:w][0]
    jb = np.where(J, yy, -1).max(0)
    hem = J & (yy > jb[None, :] - S(1.6)) & (jb[None, :] > S(wp.yn_o + 12)) & ~outline
    rgb[hem & (np.asarray(im)[..., 3] < 128)] = HEM


def soles(rgb, L, outline):
    sh = L == SHOE
    if not sh.any():
        return
    yy = np.mgrid[0:L.shape[0], 0:L.shape[1]][0]
    bot = np.where(sh, yy, -1).max(0)
    sole = sh & (yy > bot[None, :] - S(1.5)) & ~outline
    rgb[sole] = SOLE


# --- cup, arm, puff ---------------------------------------------------------------------
CUP_H = 9.0
CUP_TW, CUP_BW = 3.6, 2.7   # half widths


def cup_layer(c, straw_tilt=0.0, shade=1.0, sc=1.0):
    """clear iced coffee cup centred at c (out px): tan coffee with ice, dome
    lid, orange straw, small orange/pink logo"""
    im = Image.new("RGBA", (OW * SS, OH * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = c
    y0, y1 = cy - CUP_H / 2, cy + CUP_H / 2
    # straw first (behind the lid rim), tilted toward the mouth
    st = (cx + straw_tilt * 0.5, y0 - 1.6)
    tip = (cx + straw_tilt * 5.5, y0 - 1.6 - math.sqrt(max(0.0, 6.8 ** 2 - (straw_tilt * 5) ** 2)))
    body = [(S(cx - CUP_TW), S(y0)), (S(cx + CUP_TW), S(y0)), (S(cx + CUP_BW), S(y1)), (S(cx - CUP_BW), S(y1))]
    d.polygon(body, fill=CUP_LINE)
    ins = 0.55
    inner = [(S(cx - CUP_TW + ins), S(y0 + ins)), (S(cx + CUP_TW - ins), S(y0 + ins)),
             (S(cx + CUP_BW - ins), S(y1 - ins)), (S(cx - CUP_BW + ins), S(y1 - ins))]
    d.polygon(inner, fill=ICE)
    cf = y0 + 1.7
    wtop = CUP_TW - ins - (CUP_TW - CUP_BW) * (cf - y0) / CUP_H
    d.polygon([(S(cx - wtop), S(cf)), (S(cx + wtop), S(cf)), (S(cx + CUP_BW - ins), S(y1 - ins)),
               (S(cx - CUP_BW + ins), S(y1 - ins))], fill=COFFEE)
    # ice cubes in the coffee
    for ox, oy in ((-1.5, 2.2), (1.2, 3.0), (-0.4, 4.4)):
        d.rectangle([S(cx + ox - 0.7), S(y0 + oy - 0.6), S(cx + ox + 0.7), S(y0 + oy + 0.6)], fill=COFFEE_LIGHT)
    # glint down one side, logo dots
    tline(d, [(cx - CUP_TW + 1.2, y0 + 1.4), (cx - CUP_BW + 1.0, y1 - 1.4)], (240, 230, 214), 0.45)
    ell(d, cx + 0.5, cy + 0.9, 0.75, 0.75, LOGO_O)
    ell(d, cx + 0.5, cy + 2.3, 0.6, 0.45, LOGO_P)
    # dome lid
    d.pieslice([S(cx - 2.8), S(y0 - 2.6), S(cx + 2.8), S(y0 + 1.6)], 180, 360, fill=LID, outline=CUP_LINE,
               width=max(1, int(S(0.5))))
    d.rounded_rectangle([S(cx - CUP_TW - 0.5), S(y0 - 0.7), S(cx + CUP_TW + 0.5), S(y0 + 0.6)], radius=S(0.5),
                        fill=LID, outline=CUP_LINE, width=max(1, int(S(0.5))))
    # orange straw out through the dome (drawn over the lid so it always shows)
    st = (cx + straw_tilt * 0.3, y0 - 1.2)
    tline(d, [st, tip], STRAW_LINE, 2.0)
    tline(d, [st, tip], STRAW, 1.25)
    if sc != 1.0:
        a = 1.0 / sc
        im = im.transform(im.size, Image.AFFINE, (a, 0, S(cx) * (1 - a), 0, a, S(cy) * (1 - a)), Image.BICUBIC)
    return im


def straw_tip(c, tilt):
    y0 = c[1] - CUP_H / 2
    return (c[0] + tilt * 5.5, y0 - 1.6 - math.sqrt(max(0.0, 6.8 ** 2 - (tilt * 5) ** 2)))


def arm_layer(sh, hand, elbow):
    skin = COL[SKIN]
    parts = [
        (capsule_fn(sh, 3.3, elbow, 3.0), COL[SLEEVE]),
        (capsule_fn(elbow, 3.0, hand, 2.6), COL[SLEEVE]),
        (disc_fn(hand, 2.3), skin),
    ]
    return shapes_layer((OH, OW), parts, LINE, 0.75)


def hand_layer(hand):
    return shapes_layer((OH, OW), [(disc_fn(hand, 2.3), COL[SKIN])], SKIN_LINE, 0.6)


def puff_layer(p, side, alpha, spark=False):
    im = Image.new("RGBA", (OW * SS, OH * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if spark:
        x, y = p
        for (ax, ay) in ((1, 0), (0, 1)):
            d.polygon([(S(x - ax * 2.6), S(y - ay * 2.6)), (S(x + ay * 0.8), S(y + ax * 0.8)),
                       (S(x + ax * 2.6), S(y + ay * 2.6)), (S(x - ay * 0.8), S(y - ax * 0.8))], fill=SPARK + (255,))
        return im
    x, y = p
    for ox, oy, r in ((0, 0, 1.7), (side * 1.8, -1.0, 1.35), (side * 3.2, -2.3, 1.0)):
        ell(d, x + ox, y + oy, r, r, PUFF + (int(255 * alpha),), PUFF_LINE + (int(255 * alpha),), 0.4)
    return im


def pm(im):
    return down(im)


# tag poses: hand offset from the shoulder (out px), per view family; k=4 is
# the sip (computed from the mouth)
POSES = {
    "profile": [(3, 18), (14, 8), (19, 2), (10, 3), None, (7, 10)],
    "front": [(4.5, 18), (5, 12), (6, 8), (4, 5), None, (5, 12)],
    "back": [(4.5, 18), (5.5, 9), (6.0, 4), (4.5, 4), None, (5, 12)],
}


def billyfy(src_f, direction, anim, col, meta, memo, wp, idle_f):
    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    tag = anim == "tag"
    side = TAG_SIDE[direction]
    fx, fz = FACE[direction]
    f = src_f
    if not alpha_mask(f).any():
        return np.zeros((OH, OW, 4), np.uint8)
    g = Geometry(f)
    if tag:
        gi0 = Geometry(idle_f)
        dx_lean = float(np.clip(g.head_cx - gi0.head_cx, -3, 3))
        idle_f = lean(idle_f, dx_lean, gi0)
        f = tag_base(idle_f, Geometry(idle_f), direction, side, idle_f)
        # clip the hand stub tag_base leaves just under the removed arm
        fa, ia = f[..., 3] > 0, idle_f[..., 3] > 0
        cut = np.nonzero((ia & ~fa).any(1))[0]
        if len(cut) and direction not in PROFILE:
            xs = np.arange(f.shape[1])
            ext = [(xs[fa[y]] * side).max() for y in cut if fa[y].any()]
            lim = np.median(ext) + 1
            for y in range(cut.min(), min(cut.max() + 5, f.shape[0])):
                f[y, (xs * side) > lim] = 0
        g = Geometry(f)
    ey_src = eyes_of(src_f if not tag else idle_f, g if not tag else Geometry(idle_f))
    if tag:
        f = f.copy()
        keep = grow(alpha_mask(idle_f), np.ones(alpha_mask(idle_f).shape, bool), 1)
        f[~keep] = 0
        g = Geometry(f)
    lab = classify(f, g, direction, min(e[1] for e in ey_src) if ey_src else None)
    legs = []
    if direction in PROFILE:
        feet = feet_of(lab)
        prow = np.nonzero((lab == PANTS).any(1))[0]
        waist_src = prow.min() if len(prow) else g.hem - 10
        hip_y = wp.pt((g.hip_cx, waist_src))[1] + 1.5
        hip_x = wp.pt((g.hip_cx, waist_src))[0]
        lab = lab.copy()
        lab[np.isin(lab, (PANTS, SHOE))] = BG
        if not feet:
            feet = [(g.hip_cx, SRC_BASE)]
        fo = [wp.pt(ft) for ft in feet]
        if len(fo) == 1:
            fo = [(fo[0][0] - 1.0, fo[0][1]), (fo[0][0] + 1.0, fo[0][1])]
        fo = sorted(fo[:2], key=lambda p: fx * p[0])
        lift = OBASE - max(p[1] for p in fo)
        fo = [(p[0], p[1] + lift) for p in fo]
        L_leg = (OBASE - 2.7) - hip_y + 0.6
        for i, ft in enumerate(fo):
            back = i == 0 if len(fo) == 2 and abs(fo[0][0] - fo[1][0]) > 1.5 else i == 0
            h_ = (hip_x + fx * (0.9 if not back else -0.9), hip_y)
            legs.append(pm(leg_layer(h_, (ft[0], min(ft[1], OBASE)), fx, back, L_leg)))
    L, union, rgb, lines = render_body(lab, wp)
    eyes = eyes_of(src_f if not tag else idle_f, g if not tag else Geometry(idle_f))
    eyes_o = [wp.pt((x, y)) + (ew,) for x, y, ew in eyes]
    if direction not in BACK and len(eyes_o) == 0:
        eyes_o = memo.get((direction, "eyes"), [])
    memo[(direction, "eyes")] = eyes_o
    if direction not in BACK:
        eyes_o = [(e[0], e[1] - 1.0) + tuple(e[2:]) for e in eyes_o]
    rebuild_head(L, rgb, union, direction, wp, eyes_o)
    torso_details(rgb, L, lines, direction, wp)
    soles(rgb, L, lines)
    body = Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")
    # head box (out px) and the face
    hm = np.isin(L, (HAIR, SKIN)) & (np.mgrid[0:L.shape[0], 0:L.shape[1]][0] < S(wp.yn_o))
    hy, hx = np.nonzero(hm)
    head_box = (hx.min() / SS, hy.min() / SS, hx.max() / SS, hy.max() / SS)
    # draw the face clipped to the head
    fl = Image.new("RGBA", body.size, (0, 0, 0, 0))
    mouth = draw_face(fl, L, direction, eyes_o, wp, head_box)
    fa = np.asarray(fl).copy()
    fa[~hm & ~grow(hm, np.ones_like(hm), 2), 3] = 0
    body = Image.alpha_composite(body, Image.fromarray(fa, "RGBA"))
    if mouth is None:
        mouth = memo.get((direction, "mouth"), ((head_box[0] + head_box[2]) / 2, head_box[3] - 5))
    memo[(direction, "mouth")] = mouth

    out = pm(body)
    if legs:
        lg = legs[0]
        for l2 in legs[1:]:
            lg = over(lg, l2)
        out = over(lg, out)
    behind = direction in BACK
    if tag:
        gi = g
        if direction in PROFILE:
            sh_s = (gi.head_cx - fx * 0.5, gi.neck + 4.5)
        else:
            sh_s = (gi.head_cx + side * 7.5, gi.neck + 4.5)
        sh = wp.pt(sh_s)
        fam = "profile" if direction in PROFILE else ("front" if direction in FRONT else "back")
        pose = POSES[fam][k]
        tilt = 0.0
        if pose is None:
            # sip: straw tip at the mouth
            if direction in PROFILE:
                tilt = -fx * 0.45
                c = (mouth[0] + fx * 3.8, 0)
            elif direction in FRONT:
                tilt = -side * 0.15
                c = (mouth[0] + side * 0.8, 0)
            else:
                c = (mouth[0] + side * 1.0, 0)
            tipy = straw_tip((c[0], 0.0), tilt)[1]
            c = (c[0], mouth[1] + 0.6 - tipy)
            hand = (c[0] - (fx * 2.6 if direction in PROFILE else -side * 2.4), c[1] + 0.8)
        else:
            ox, oy = pose
            if direction in PROFILE:
                hand = (sh[0] + fx * ox, sh[1] + oy)
            else:
                hand = (sh[0] + side * ox + fx * (0 if k in (0, 5) else 4.0), sh[1] + oy)
            c = (hand[0] + (fx * 1.2 if direction in PROFILE else side * 1.6), hand[1] - 0.6)
            if direction in PROFILE and k in (1, 2):
                tilt = fx * 0.15
        e1 = ik(sh, hand, 9.6, 9.0, 1)
        e2 = ik(sh, hand, 9.6, 9.0, -1)
        elbow = e1 if e1[1] >= e2[1] else e2
        arm = pm(arm_layer(sh, hand, elbow))
        cup = pm(cup_layer(c, tilt))
        handl = pm(hand_layer(hand))
        if behind:
            # back views: arm and cup behind the body
            res = over(over(over(cup, handl), arm), np.zeros_like(out))
            out = over(res, pm(body))
        else:
            out = over(over(over(out, arm), cup), handl)
        if k == 4 and direction not in BACK:
            if direction in PROFILE:
                sp = (mouth[0] + fx * 6.5, mouth[1] - 4.5)
            else:
                sp = (mouth[0] - side * 6.5, mouth[1] - 3.5)
            out = over(out, pm(puff_layer(sp, 1, 1.0, spark=True)))
        if k == 5 and direction not in BACK:
            if direction in PROFILE:
                p = (mouth[0] + fx * 3.5, mouth[1] - 1.5)
                ps = fx
            else:
                p = (mouth[0] - side * 5.0, mouth[1] - 1.0)
                ps = -side
            out = over(out, pm(puff_layer(p, ps, 0.8)))
    else:
        yy = np.mgrid[0:f.shape[0], 0:f.shape[1]][0]
        face_i = (yy <= g.neck + 1) & skin_mask(f)
        _, hands = arms_and_hands(f, g, face_i)
        a = alpha_mask(f)
        pick = pick_hand(hands & (yy > g.neck + 1), g, side, a)
        if pick is None:
            hc = [c_ for c_ in components8(hands & (yy > g.neck + 1)) if c_.sum() >= 3]
            if hc:
                c_ = max(hc, key=lambda c_: (side * (np.nonzero(c_)[1].mean() - g.hip_cx), c_.sum()))
                ys_, xs_ = np.nonzero(c_)
                pick = (float(xs_.mean() + 0.5), float(ys_.mean() + 0.5), c_)
        if pick is not None:
            hand = wp.pt((pick[0], pick[1]))
            memo[(direction, anim)] = hand
        else:
            hand = memo.get((direction, anim), memo.get((direction, "idle"), wp.pt((g.head_cx + side * 9, g.hem - 4))))
        c = (hand[0] + (fx * 1.0 if direction in PROFILE else side * 1.4), hand[1] - 0.4)
        cup = pm(cup_layer(c))
        handl = pm(hand_layer(hand))
        if behind:
            out = over(over(cup, handl), out)
        else:
            out = over(over(out, cup), handl)
    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    a = res[..., 3] > 40
    rows = np.nonzero(a.any(1))[0]
    res = solidify(res, (int(wp.yn_o) + 1, OBASE - 12))
    # drop 1-2 px tall ground dashes left of / right of the shoes
    a = res[..., 3] > 0
    for y in range(OBASE - 4, OH):
        for x in range(OW):
            if a[y, x] and not a[y - 3:y, x].any():
                run = a[max(0, y - 2):y + 1, x]
                res[y, x] = 0
        a = res[..., 3] > 0
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path)
    ap.add_argument("--only", help="comma list of directions (debug)")
    args = ap.parse_args()
    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    out = np.zeros((len(dirs) * OH, cols * OW, 4), np.uint8)
    only = set(args.only.split(",")) if args.only else None
    for r, d in enumerate(dirs):
        if only and d not in only:
            continue
        idle = src[r * fh:(r + 1) * fh, 0:fw]
        gi = Geometry(idle)
        wp = Warp(gi.head_cx, gi.neck - 0.5)
        memo: dict = {}
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * OH:(r + 1) * OH, c * OW:(c + 1) * OW] = billyfy(fr, d, anim_of(meta, c), c, meta, memo, wp, idle)
    assert max(out.shape[:2]) <= 4096, out.shape
    Image.fromarray(out).save(ASSETS / "kid_billy.png", optimize=True)
    pm_ = dict(meta)
    pm_["image"] = "kid_billy.png"
    pm_["frameWidth"], pm_["frameHeight"] = OW, OH
    pm_["baselineY"] = OBASE
    pm_["anchorX"] = OW // 2
    (ASSETS / "kid_billy.json").write_text(json.dumps(pm_, indent=2) + "\n")
    print(f"wrote kid_billy.png ({out.shape[1]}x{out.shape[0]}) frames {OW}x{OH}")


if __name__ == "__main__":
    main()
