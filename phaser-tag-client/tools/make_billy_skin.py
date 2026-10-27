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
    the facing direction, pulls it back and sips from the straw (tag frame 4;
    no puff or sparkle). The other arms are drawn jacket sleeves from the
    shoulders to James's hand positions, and a short neck joins head and collar;
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
HEAD_SCALE = 1.40
ARM_R = 3.5
BACK_D = 12.5
TORSO_D = 15.0
OBASE = 118                # feet line in the output frame
SRC_BASE = 96              # feet line in kid.png
SRC_CX = 40
HS = 0.82                  # head scale
BSY = 1.10                 # body: taller ...
BSX = 1.4                  # ... and stocky

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}
# facing: screen x and "toward the viewer"
FACE = {"E": (1, 0), "SE": (0.7, 0.7), "S": (0, 1), "SW": (-0.7, 0.7),
        "W": (-1, 0), "NW": (-0.7, -0.7), "N": (0, -1), "NE": (0.7, -0.7)}

BG, HAIR, SKIN, HAND, SLEEVE, JACKET, PANTS, SHOE = range(8)
COL = {
    HAIR: (22, 24, 32),
    SKIN: (210, 158, 128),
    HAND: (210, 158, 128),
    SLEEVE: (96, 99, 114),
    JACKET: (76, 78, 90),
    PANTS: (24, 24, 28),
    SHOE: (30, 30, 34),
}
LINE = (10, 10, 13)
SLEEVE_LINE = (28, 28, 36)
SKIN_LINE = (96, 58, 40)
SKIN_SHADE = (190, 136, 108)
SOLE = (240, 240, 234)
SHIRT = (132, 134, 141)
SHIRT_DARK = (104, 106, 114)
POCKET = (96, 98, 112)
POCKET_HI = (128, 131, 146)
ZIP = (170, 173, 182)
HEM = (62, 64, 75)
PANTS_BACK = (16, 16, 19)
HAIR_HI = (72, 78, 98)
GLASS = (14, 14, 17)
BROW = (22, 18, 18)
STACHE = (22, 16, 14)
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


def render_body(lab, wp, back_fx=0):
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
        if back_fx:
            # side view: square the jacket back off to the torso's back line
            # (the warp slants the shoulder and the removed far arm notches it)
            y0, y1 = int(S(wp.yn_o - 0.5)), jr.max() + 1
            wrows = range(int(S(wp.yn_o - 4)), int(S(wp.yn_o + 4)))
            wid = [(union[y].sum() if union[y].any() else 10 ** 6, y) for y in wrows]
            if wid:
                y0 = min(y0, min(wid)[1] + SS // 2)
            J = np.isin(L, (JACKET, SLEEVE))
            xs_ = np.arange(L.shape[1])
            edges = {y: (xs_[J[y]].min() if back_fx > 0 else xs_[J[y]].max())
                     for y in range(y0, y1) if J[y].any()}
            if edges:
                lower = [v for y, v in edges.items() if y > (y0 + y1) / 2]
                # fixed torso depth behind the neck in every side frame
                wy = min(wid)[1] if wid else y0
                nx_ = xs_[union[wy]]
                ncx_ = (nx_.min() + nx_.max()) / 2 if len(nx_) else np.median(list(edges.values()))
                # fixed torso depth behind the neck; follow the lean of the
                # back (slope of the existing back line)
                # torso axis: neck centre -> centre of the jacket hem row
                hy_ = y1 - 1
                hx_ = xs_[(L[hy_] == JACKET)]
                if len(hx_) and hy_ > wy:
                    slope = float(np.clip(((hx_.min() + hx_.max()) / 2 - ncx_) / (hy_ - wy), -0.05, 0.05))
                else:
                    slope = 0.0
                for y, e in edges.items():
                    ref = ncx_ - back_fx * BACK_D * SS + slope * (y - wy)
                    Rr = 4.5 * SS
                    dy_ = min(Rr, y - y0)
                    rb = Rr - math.sqrt(max(0.0, Rr * Rr - (Rr - dy_) ** 2))
                    bx = int(round(ref + back_fx * rb))
                    # cut anything behind the rounded back line
                    if back_fx > 0:
                        cut = (xs_ < bx) & np.isin(L[y], (JACKET, SLEEVE))
                    else:
                        cut = (xs_ > bx) & np.isin(L[y], (JACKET, SLEEVE))
                    L[y, cut] = BG
                    union[y, cut] = False
                    if back_fx > 0 and e > bx:
                        sl = slice(bx, e)
                    elif back_fx < 0 and e < bx:
                        sl = slice(e + 1, bx + 1)
                    else:
                        continue
                    seg = ~union[y, sl] | (L[y, sl] == JACKET)
                    L[y, sl][seg] = JACKET
                    union[y, sl] = True
            # chubby: a soft rounded belly out front, lower half of the jacket
            Jf = L == JACKET
            for y in range(y0, y1):
                tt = (y - y0) / max(1, (y1 - y0))
                bul = 2.6 * SS * max(0.0, math.sin(math.pi * min(1.0, max(0.0, (tt - 0.2) / 0.85))))
                if bul < 1 or not Jf[y].any():
                    continue
                jx_ = xs_[Jf[y]]
                f_ = jx_.max() if back_fx > 0 else jx_.min()
                if back_fx > 0:
                    sl = slice(f_ + 1, int(f_ + 1 + bul))
                else:
                    sl = slice(max(0, int(f_ - bul)), f_)
                seg = ~union[y, sl]
                L[y, sl][seg] = JACKET
                union[y, sl] = True
            cps = components8(union)
            if cps:
                big_ = max(cps, key=lambda c_: c_.sum())
                for c_ in cps:
                    if c_ is not big_ and c_.sum() < 40 * SS * SS:
                        L[c_] = BG
                        union[c_] = False
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
        bot = max(bot, ey_m + 9.3)
        top = min(top, ey_m - 10.0)
        hw = min(hw, (bot - top) / 1.22 / 2) if direction not in PROFILE else min(hw, (bot - top) / 1.16 / 2)
    hh = (bot - top) / 2
    cy = (top + bot) / 2
    fx = FACE[direction][0]
    # jaw a touch narrower than the cranium
    t = np.clip((Yo - cy) / hh, 0, 1)
    # chubby cheeks: soft jaw + fuller bulge at smile height
    bulge = np.exp(-(((Yo - (cy + 0.32 * hh)) / (0.38 * hh)) ** 2))
    Xs = cx + (Xo - cx) / ((1 - 0.10 * t * t) * (1 + 0.12 * bulge))
    sdf = _rbox_sdf(Xs, Yo, cx, cy, hw * 1.04, hh, hw * 0.98)
    head = sdf < 0
    # erase the old head
    L[old] = BG
    union[old] = False
    if direction in PROFILE:
        ey = eyes_o[0][1] if eyes_o else top + 0.55 * (bot - top)
        nose = ((Xo - (cx + fx * (hw + 0.2))) / 1.1) ** 2 + ((Yo - (ey + 2.6)) / 1.4) ** 2 < 1
        head |= nose
    hair_cap = _rbox_sdf(Xs, Yo, cx, cy - 0.35, hw + 0.45, hh + 0.65, (hw + 0.45) * 0.96) < 0
    # Cloud-Strife style base hairline: solid cap, then big drawn spikes
    # and long bangs layered on top.
    if direction in BACK:
        ey = top + 0.55 * (bot - top)
        hl = top + 0.78 * (bot - top)
        hair = hair_cap & (Yo < hl + 1.0 * np.cos(np.clip((Xo - cx) / hw, -1, 1) * 1.2))
        ear_y = top + 0.55 * (bot - top)
        ears = [(cx - hw - 0.5, ear_y), (cx + hw + 0.5, ear_y)]
    elif direction in PROFILE:
        ey = eyes_o[0][1] if eyes_o else top + 0.55 * (bot - top)
        # short base fringe toward the face; long bangs drawn as polygons below
        hl = ey - 5.5
        back = fx * (Xo - cx) < -hw * 0.4
        hair = hair_cap & ((Yo < hl + 1.2 * np.clip(-fx * (Xo - cx) / hw, 0, 1)) | (back & (Yo < ey + 2.4)))
        ears = [(cx - fx * hw * 0.22, ey + 1.0)]
    else:
        ey = np.mean([e[1] for e in eyes_o]) if eyes_o else top + 0.55 * (bot - top)
        # base hair sits above the brows; bangs are drawn as long spikes
        hl = ey - 7.2
        edge = np.clip((np.abs(Xo - (cx + fx * 0.8)) / hw - 0.70) / 0.30, 0, 1)
        hair = hair_cap & (Yo < hl + 2.4 * edge)
        ears = [(cx - hw - 0.1, ey + 0.8), (cx + hw + 0.1, ey + 0.8)]
        if fx:
            ears = [ears[0] if fx > 0 else ears[1]]
    # --- Cloud-style big spikes (black) ---
    # few LARGE spikes sweeping UP AND BACK (Cloud), long bangs to the
    # top of the glasses, side flares. Tips clipped to stay in-frame.
    # Lengths kept modest so the head-ratio check stays <= 0.495.
    sp_im = Image.new("L", (W, H), 0)
    sp_d = ImageDraw.Draw(sp_im)
    y_glass = ey - 3.6  # bangs stop at ~top of glasses, never cover eyes

    def spike(base, tip, half_w):
        bx, by = base
        tx, ty = tip
        tx = float(np.clip(tx, 1.5, (W / SS) - 1.5))
        ty = float(np.clip(ty, 1.2, (H / SS) - 1.5))
        dx, dy = tx - bx, ty - by
        L_ = math.hypot(dx, dy) or 1.0
        px_, py_ = -dy / L_ * half_w, dx / L_ * half_w
        sp_d.polygon([(S(bx + px_), S(by + py_)), (S(tx), S(ty)),
                      (S(bx - px_), S(by - py_))], fill=255)

    if direction in BACK:
        # big radiating spikes (sunburst) — longer out, moderate up
        for u, ln, ang, bw in (
            (-1.0, 8.0, -70, 3.0), (-0.65, 9.0, -42, 3.3),
            (-0.3, 9.8, -18, 3.5), (0.05, 10.0, 5, 3.6),
            (0.4, 9.5, 28, 3.4), (0.75, 8.2, 52, 3.1),
            (1.05, 6.8, 72, 2.7),
        ):
            bx = cx + u * hw * 0.55
            by = top + 3.2 + 1.0 * u * u
            rad = math.radians(ang)
            tip = (bx + math.sin(rad) * ln, by - math.cos(rad) * ln * 0.78)
            spike((bx, by), tip, bw)
        for sd in (-1, 1):
            spike((cx + sd * hw * 0.75, top + hh * 0.4),
                  (cx + sd * (hw + 5.0), top + hh * 0.22), 2.5)
            spike((cx + sd * hw * 0.7, top + hh * 0.55),
                  (cx + sd * (hw + 3.5), top + hh * 0.55), 2.0)
    elif direction in PROFILE:
        # dramatic swept-BACK Cloud spikes + bangs toward the face
        back_sign = -fx
        for (u, back, lift, bw) in (
            (0.0, 4.5, 7.5, 3.6), (0.3, 7.5, 6.5, 3.4),
            (0.55, 9.5, 4.5, 3.1), (0.8, 10.5, 2.5, 2.8),
            (1.05, 9.0, 0.5, 2.4),
        ):
            bx = cx + back_sign * hw * (0.0 + 0.45 * u)
            by = top + 2.6 + 2.2 * u
            tip = (bx + back_sign * back, by - lift)
            spike((bx, by), tip, bw)
        # thick bangs falling over the forehead (stop at glasses)
        for (u, drop, bw) in ((-0.15, -0.3, 3.0), (0.2, 0.1, 2.9), (0.5, 0.6, 2.6), (0.75, 1.2, 2.3)):
            bx = cx + fx * hw * (0.0 + 0.28 * abs(u))
            by = top + 2.8
            tip = (cx + fx * (hw * 0.65 + 1.4 * u), min(y_glass + drop, ey - 2.0))
            spike((bx, by), tip, bw)
        # upper side flare + cheek lock
        spike((cx - fx * hw * 0.05, top + hh * 0.28),
              (cx - fx * (hw + 4.5), top - 0.5), 2.4)
        spike((cx - fx * hw * 0.15, top + hh * 0.5),
              (cx - fx * (hw + 2.0), ey + 4.0), 2.0)
    else:
        # FRONT / DIAG: few LARGE crown spikes (Cloud asymmetry) + thick bangs
        for (u, ln, sweep, bw) in (
            (-1.0, 6.5, -3.8, 2.8), (-0.6, 8.5, -2.2, 3.3),
            (-0.2, 9.5, -0.6, 3.6), (0.2, 9.0, 1.6, 3.5),
            (0.55, 7.5, 3.0, 3.1), (0.9, 5.5, 4.0, 2.7),
        ):
            bx = cx + u * hw * 0.7 + fx * 0.5
            by = top + 2.6 + 1.3 * u * u
            tip = (bx + sweep + fx * 0.8, by - ln)
            spike((bx, by), tip, bw)
        # thick triangular bangs — stop at top of glasses, never cover eyes
        for (u, tip_y_off, bw) in (
            (-0.8, 0.5, 2.8), (-0.4, -0.1, 3.2), (0.0, -0.3, 3.3),
            (0.4, 0.0, 3.1), (0.75, 0.5, 2.7), (1.05, 1.1, 2.3),
        ):
            bx = cx + u * hw * 0.48 + fx * 0.35
            by = top + 2.5
            tipy = min(y_glass + tip_y_off, ey - 2.0)
            tip = (cx + u * hw * 0.28 + fx * 1.0, tipy)
            spike((bx, by), tip, bw)
        # side flares + long cheek locks (Cloud jaw framing)
        for sd in (-1, 1):
            spike((cx + sd * hw * 0.85 + fx * 0.25, top + hh * 0.28),
                  (cx + sd * (hw + 4.5) + fx * 0.25, top + hh * 0.0), 2.6)
            spike((cx + sd * hw * 0.8 + fx * 0.25, top + hh * 0.4),
                  (cx + sd * (hw + 2.0) + fx * 0.25, ey + 4.5), 2.2)
    tuft = np.asarray(sp_im) > 127
    hair |= tuft & (Yo < bot + 0.2)
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
    # Cloud-style flat shading: blue-black / dark-grey highlights along
    # the upper edges of the big spikes (no noisy texture, no side-part).
    sp_hi = Image.new("L", (W, H), 0)
    shd = ImageDraw.Draw(sp_hi)
    if direction in BACK:
        for u, ln, ang in ((-0.45, 8.0, -35), (-0.1, 8.8, -10), (0.25, 8.5, 22), (0.6, 7.5, 45)):
            bx = cx + u * hw * 0.7
            by = top + 3.2
            rad = math.radians(ang)
            shd.line([(S(bx), S(by)),
                      (S(bx + math.sin(rad) * ln * 0.85), S(by - math.cos(rad) * ln * 0.85))],
                     fill=255, width=max(1, int(S(0.85))))
    elif direction in PROFILE:
        back_sign = -fx
        for u, back, lift in ((0.15, 5.5, 6.5), (0.45, 8.0, 5.0), (0.75, 9.0, 3.0)):
            bx = cx + back_sign * hw * (0.1 + 0.45 * u)
            by = top + 3.0 + 1.8 * u
            shd.line([(S(bx), S(by)), (S(bx + back_sign * back * 0.85), S(by - lift * 0.85))],
                     fill=255, width=max(1, int(S(0.85))))
        # bang highlight
        shd.line([(S(cx + fx * hw * 0.2), S(top + 3.5)),
                  (S(cx + fx * hw * 0.5), S(ey - 3.8))], fill=255, width=max(1, int(S(0.7))))
    else:
        for u, ln, sweep in ((-0.55, 7.5, -1.8), (-0.1, 8.5, -0.5), (0.3, 8.2, 1.4), (0.7, 6.5, 2.7)):
            bx = cx + u * hw * 0.7 + fx * 0.5
            by = top + 2.5
            shd.line([(S(bx), S(by)), (S(bx + sweep), S(by - ln * 0.85))],
                     fill=255, width=max(1, int(S(0.85))))
        # bang highlights
        for u in (-0.35, 0.1, 0.5):
            shd.line([(S(cx + u * hw * 0.5), S(top + 3.2)),
                      (S(cx + u * hw * 0.3), S(ey - 3.8))],
                     fill=255, width=max(1, int(S(0.65))))
    rgb[(np.asarray(sp_hi) > 127) & hair & allm] = HAIR_HI
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
    # the neck: a short skin column from under the jaw into the jacket
    # collar; any other skin below the chin (James's warped shoulders) is
    # jacket
    below = (Yo > bot - 0.8) & ~allm
    stray = below & (L == SKIN)
    Jk = L == JACKET
    inside_j = np.zeros_like(stray)
    for y in np.nonzero(stray.any(1))[0]:
        xj = np.nonzero(Jk[y])[0]
        if len(xj):
            inside_j[y, xj.min():xj.max() + 1] = True
    L[stray & inside_j] = JACKET
    rgb[stray & inside_j] = COL[JACKET]
    gone = stray & ~inside_j
    L[gone] = BG
    union[gone] = False
    ncx = cx - fx * (0.6 if direction in PROFILE else -0.2)
    nhw = 2.0 if direction in PROFILE else 2.5
    J = np.isin(L, (JACKET, SLEEVE)) & (np.abs(Xo - ncx) < nhw)
    jr = np.nonzero(J.any(1))[0]
    jt = (jr[jr > S(bot - 2)].min() / SS) if (jr > S(bot - 2)).any() else bot + 2.5
    if direction not in BACK:
        neck_t = bot - 2.5
        neck_b = max(jt + 1.2, bot + 1.6)
        neck = (np.abs(Xo - ncx) < nhw) & (Yo > neck_t) & (Yo < neck_b) & ~allm
        L[neck] = SKIN
        union |= neck
        rgb[neck] = COL[SKIN]
        edge = neck & (np.abs(Xo - ncx) > nhw - 0.75)
        rgb[edge] = SKIN_LINE
        sh_ = neck & (Yo < bot + 1.3)
        rgb[sh_ & ~edge] = SKIN_SHADE
    else:
        neck = (np.abs(Xo - ncx) < nhw) & (Yo > bot - 2.5) & (Yo < jt + 1.0) & ~allm & ~union
        L[neck] = SKIN
        union |= neck
        rgb[neck] = SKIN_SHADE
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
        (capsule_fn(hip, 6.0, knee, 5.8), pc),
        (capsule_fn(knee, 5.8, ankle, 5.6), pc),
        # loose hem bunched over the sneaker
        (capsule_fn((ankle[0] - fx * 0.4, ankle[1] - 1.6), 6.0, (ankle[0] + fx * 0.6, ankle[1] + 0.2), 5.8), pc),
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


CHEEK = (220, 148, 118)
LENS = (214, 170, 142)
MOUTH = (82, 38, 36)


def _blend(c, k, t):
    return tuple(int(round(a * (1 - t) + b * t)) for a, b in zip(c, k))


def smile_eye(d, ex, ey, hw, side=0, ry=2.55, half=False, fx=0):
    """big open cartoon eyeballs (James-scale or bigger): white sclera,
    dark-brown iris, pupil, catchlight; happy lid curve + smile crease."""
    img = d._image
    n = 17
    ts = np.linspace(-1, 1, n)
    # rounder eyeball: nearly circular aperture, outer corner lifted a touch
    up = [(ex + hw * t, ey - ry * 1.05 * (1 - t * t) ** 0.55 - 0.22 * side * t) for t in ts]
    lo = [(ex + hw * t, ey + ry * 0.95 * (1 - t * t) ** 0.7 - 0.1 * side * t) for t in ts]
    if half:
        # profile: keep the front half of the eye
        keep = [i for i, t in enumerate(ts) if (t * fx) >= -0.15]
        up = [up[i] for i in keep]
        lo = [lo[i] for i in keep]
        ts = [ts[i] for i in keep]
    poly = [(S(x), S(y)) for x, y in up + lo[::-1]]
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon(poly, fill=255)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.polygon(poly, fill=(252, 250, 246, 255))
    ix = ex + (0.35 * fx if half else 0.12 * fx) + 0.1 * side
    r = ry * 0.68
    iy = ey + 0.15
    # dark-brown iris
    ld.ellipse([S(ix - r), S(iy - r), S(ix + r), S(iy + r)], fill=(78, 48, 30, 255))
    # pupil
    ld.ellipse([S(ix - r * 0.48), S(iy - r * 0.48), S(ix + r * 0.48), S(iy + r * 0.48)], fill=(14, 10, 10, 255))
    # catchlight
    ld.ellipse([S(ix - r * 0.55), S(iy - r * 0.7), S(ix - r * 0.55 + 0.7), S(iy - r * 0.7 + 0.7)],
               fill=(255, 255, 255, 255))
    la = np.asarray(lay).copy()
    la[..., 3] = np.minimum(la[..., 3], np.asarray(m))
    img.alpha_composite(Image.fromarray(la, "RGBA"))
    d2 = ImageDraw.Draw(img)
    # bold happy upper lid, soft lower
    d2.line([(S(x), S(y - 0.12)) for x, y in up], fill=EYE, width=max(1, int(S(0.85))), joint="curve")
    d2.line([(S(x), S(y + 0.05)) for x, y in lo[1:-1]], fill=EYE, width=max(1, int(S(0.45))), joint="curve")
    # smile crease under the eye
    d2.line([(S(ex + hw * t * 0.75), S(ey + ry * 1.05 - ry * 0.2 * (1 - t * t)))
             for t in np.linspace(-0.7, 0.7, 7)],
            fill=SKIN_LINE, width=max(1, int(S(0.35))), joint="curve")



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
        # photo: thick rectangular frames, wide lenses
        sp = float(np.clip(rx - lx, 8.2, 8.6))
        mid = (lx + rx) / 2 + fx * 0.25
        lx, rx = mid - sp / 2, mid + sp / 2
        hw_l = 4.35 * (0.82 if fx > 0 else 1.0)
        hw_r = 4.35 * (0.82 if fx < 0 else 1.0)
        mx = mid + fx * 0.35
        my = ey + 7.0
        # full round smiling cheeks
        for ex, hw in ((lx, hw_l), (rx, hw_r)):
            ell(d, ex + (ex - mid) * 0.4, ey + 4.6, hw * 0.95, 2.1, CHEEK)
            ell(d, ex + (ex - mid) * 0.6, ey + 5.9, hw * 0.6, 1.5, CHEEK)
        # broad soft nose (photo) — a bit more contrast so it reads
        ell(d, mx, ey + 3.55, 2.35, 1.35, SKIN_SHADE)
        ell(d, mx, ey + 2.95, 1.2, 0.8, COL[SKIN])
        for k in (-1, 1):
            ell(d, mx + k * 1.2, ey + 4.25, 0.55, 0.4, SKIN_LINE)
        # soft bridge hint
        tline(d, [(mx - 0.35, ey + 1.6), (mx, ey + 2.5), (mx + 0.35, ey + 1.6)], SKIN_SHADE, 0.55)
        # larger lenses framing big open eyeballs
        gh, gv = 3.55, 3.25
        for ex, hw in ((lx, hw_l), (rx, hw_r)):
            d.rounded_rectangle([S(ex - hw), S(ey - gh), S(ex + hw), S(ey + gv)],
                                radius=S(0.55), fill=LENS)
            smile_eye(d, ex + fx * 0.25, ey + 0.1, hw * 0.78, ry=2.7,
                      side=(1 if ex > mid else -1), fx=fx)
        # brows just above the taller frames
        for ex, hw, sg in ((lx, hw_l, -1), (rx, hw_r, 1)):
            tline(d, [(ex - sg * hw * 0.95, ey - gh - 1.15),
                      (ex - sg * hw * 0.15, ey - gh - 1.95),
                      (ex + sg * hw * 0.35, ey - gh - 2.0),
                      (ex + sg * hw * 0.95, ey - gh - 1.35)], BROW, 1.45)
        # thick black rectangular frames matching the photo
        for ex, hw in ((lx, hw_l), (rx, hw_r)):
            d.rounded_rectangle([S(ex - hw), S(ey - gh), S(ex + hw), S(ey + gv)],
                                radius=S(0.5), outline=GLASS, width=W_(1.25))
            tline(d, [(ex - hw + 0.25, ey - gh + 0.4), (ex + hw - 0.25, ey - gh + 0.4)], GLASS, 0.55)
            tline(d, [(ex + hw * 0.4, ey - gh + 0.85), (ex + hw * 0.72, ey - gh + 1.15)], (235, 240, 245), 0.4)
        tline(d, [(lx + hw_l - 0.15, ey - 0.7), (mid, ey - 1.05), (rx - hw_r + 0.15, ey - 0.7)], GLASS, 1.3)
        tline(d, [(lx - hw_l, ey - 0.85), (max(x0 + 0.4, lx - hw_l - 2.5), ey - 1.2)], GLASS, 1.15)
        tline(d, [(rx + hw_r, ey - 0.85), (min(x1 - 0.4, rx + hw_r + 2.5), ey - 1.2)], GLASS, 1.15)
        # photo smile: wide upper-teeth grin, shallow cavity, lip corners up
        mw = 5.6 if fx == 0 else 4.7
        d.chord([S(mx - mw), S(my - 1.7), S(mx + mw), S(my + 2.35)], 0, 180, fill=MOUTH)
        d.chord([S(mx - mw + 0.45), S(my - 1.55), S(mx + mw - 0.45), S(my + 1.55)], 0, 180, fill=TEETH)
        d.arc([S(mx - mw), S(my - 1.7), S(mx + mw), S(my + 2.35)], 8, 172, fill=SKIN_LINE, width=W_(0.45))
        tline(d, [(mx - mw * 0.75, my + 1.85), (mx, my + 2.15), (mx + mw * 0.75, my + 1.85)], (168, 96, 86), 0.55)
        # thin mustache hugging the upper lip curve (no soul patch)
        tline(d, [(mx - mw - 0.1, my + 0.3), (mx - mw * 0.6, my - 0.9),
                  (mx, my - 1.05), (mx + mw * 0.6, my - 0.9),
                  (mx + mw + 0.1, my + 0.3)], STACHE, 1.2)
        return (mx, my)
    # profile
    if not eyes_o:
        return None
    ex, ey, _ = eyes_o[0]
    ex += fx * 0.2
    my = ey + 7.2
    yi = int(S(my))
    row = np.nonzero(np.isin(L[yi], (SKIN,)))[0]
    front = ((row.max() if fx > 0 else row.min()) / SS) if len(row) else ex + fx * 4
    mx = front - fx * 1.7
    # full cheek + broad nose
    ell(d, ex - fx * 0.4, ey + 4.4, 2.8, 2.1, CHEEK)
    ell(d, ex - fx * 0.7, ey + 5.6, 1.9, 1.4, CHEEK)
    ell(d, ex + fx * 2.7, ey + 3.2, 1.4, 1.0, SKIN_SHADE)
    ell(d, ex + fx * 2.5, ey + 3.65, 0.38, 0.28, SKIN_LINE)
    my = ey + 6.6
    lx0, lx1 = sorted((ex - fx * 1.5, ex + fx * 1.5))
    # shift frame forward a touch so the lens sits on the face
    ex2 = ex - fx * 0.4
    lx0, lx1 = sorted((ex2 - fx * 2.5, ex2 + fx * 2.0))
    # shift frame a bit wider/taller for the big eyeball
    lx0, lx1 = sorted((ex2 - fx * 2.9, ex2 + fx * 2.35))
    gh, gv = 3.4, 3.15
    d.rounded_rectangle([S(lx0), S(ey - gh), S(lx1), S(ey + gv)], radius=S(0.5), fill=LENS)
    smile_eye(d, ex2 + fx * 0.2, ey + 0.1, 2.35, ry=2.55, side=fx, half=True, fx=fx)
    tline(d, [(ex2 - fx * 1.9, ey - gh - 1.2), (ex2, ey - gh - 1.75), (ex2 + fx * 1.7, ey - gh - 1.25)], BROW, 1.35)
    d.rounded_rectangle([S(lx0), S(ey - gh), S(lx1), S(ey + gv)], radius=S(0.45), outline=GLASS, width=W_(1.15))
    tline(d, [(lx0 + 0.35, ey - gh + 0.35), (lx1 - 0.35, ey - gh + 0.35)], GLASS, 0.5)
    tline(d, [(ex2 + fx * 0.2, ey - 0.85), (ex2 + fx * 0.8, ey - 0.85)], (255, 255, 255), 0.4)
    tline(d, [(ex2 - fx * 1.5, ey - 0.8), (wp.hcx_o + fx * 0.2, ey - 1.35)], GLASS, 1.0)
    # smile + thin mustache (no soul patch)
    a0, a1 = sorted((mx + fx * 0.1, mx - fx * 4.0))
    d.chord([S(a0), S(my - 1.5), S(a1), S(my + 2.0)], 0, 180, fill=MOUTH)
    d.chord([S(a0 + 0.25), S(my - 1.35), S(a1 - 0.2), S(my + 1.2)], 0, 180, fill=TEETH)
    tline(d, [(mx - fx * 3.2, my + 0.35), (mx - fx * 3.6, my - 0.25)], SKIN_LINE, 0.45)
    tline(d, [(mx - fx * 3.4, my - 0.35), (mx - fx * 1.4, my - 1.15), (mx + fx * 0.35, my - 0.85)], STACHE, 1.05)
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
    """natural jacket sleeve: shoulder -> elbow -> cuff, the hand at the end"""
    dx, dy = hand[0] - elbow[0], hand[1] - elbow[1]
    dd = math.hypot(dx, dy) or 1.0
    cuff = (hand[0] - dx / dd * 1.6, hand[1] - dy / dd * 1.6)
    parts = [
        (capsule_fn(sh, ARM_R, elbow, ARM_R - 0.3), COL[SLEEVE]),
        (capsule_fn(elbow, ARM_R - 0.3, cuff, ARM_R - 0.5), COL[SLEEVE]),
    ]
    return shapes_layer((OH, OW), parts, SLEEVE_LINE, 0.8)


def hand_layer(hand):
    return shapes_layer((OH, OW), [(disc_fn(hand, 2.4), COL[SKIN])], SKIN_LINE, 0.6)


def elbow_of(sh, hand, out_x):
    """elbow for a relaxed arm of fixed segment length, bent outward/back"""
    d = math.hypot(hand[0] - sh[0], hand[1] - sh[1]) or 1.0
    seg = max(d / 2 + 0.05, 8.6)
    a = d / 2
    h = math.sqrt(max(0.0, seg * seg - a * a))
    ux, uy = (hand[0] - sh[0]) / d, (hand[1] - sh[1]) / d
    px, py = -uy, ux
    if px * out_x < 0:
        px, py = -px, -py
    return (sh[0] + ux * a + px * h, sh[1] + uy * a + py * h)


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
    # James's chunky warped arms are replaced by drawn sleeves: find his hands,
    # drop the sleeve/hand labels (the jacket closes over the gap)
    yy_ = np.mgrid[0:f.shape[0], 0:f.shape[1]][0]
    _, hm_src = arms_and_hands(f, g, (yy_ <= g.neck + 1) & skin_mask(f))
    hcomps = [c_ for c_ in components8(hm_src & (yy_ > g.neck + 3)) if c_.sum() >= 3]
    hcent = []
    for c_ in hcomps:
        ys_, xs_ = np.nonzero(c_)
        hcent.append((float(xs_.mean() + 0.5), float(ys_.max() - 0.5), int(c_.sum())))
    arm_px = np.isin(lab, (SLEEVE, HAND))
    xs_all = np.arange(f.shape[1])
    lab = lab.copy()
    jk = lab == JACKET
    los, his = [], []
    for y in range(g.neck + 3, g.hem):
        if jk[y].any() and not arm_px[y].any():
            los.append(xs_all[jk[y]].min()); his.append(xs_all[jk[y]].max())
    if not los:
        for y in range(g.neck + 3, g.hem):
            if jk[y].any():
                los.append(xs_all[jk[y]].min()); his.append(xs_all[jk[y]].max())
    tlo, thi = (np.median(los), np.median(his)) if los else (g.head_cx - 6, g.head_cx + 6)
    for y in range(f.shape[0]):
        row = arm_px[y]
        if not row.any():
            continue
        tor = jk[y] & (xs_all >= tlo - 1) & (xs_all <= thi + 1)
        lab[y, row] = BG
        lab[y, jk[y] & ~tor & (y > g.neck + 3)] = BG
        if tor.any():
            lo, hi = xs_all[tor].min(), xs_all[tor].max()
            inside = row & (xs_all > lo) & (xs_all < hi)
            lab[y, inside] = JACKET
    # drop stray bits of James's arm outline left beside the body
    comps_ = components8(lab > 0)
    if comps_:
        keep_ = max(comps_, key=lambda c_: c_.sum())
        lab[(lab > 0) & ~keep_] = BG
    free = []  # (shoulder_out, hand_out, outward_x, side)
    sides = [0] if direction in PROFILE else [-1, 1]
    for s_ in sides:
        if tag and (s_ == side or direction in PROFILE):
            continue
        if direction in PROFILE:
            sh_src = (g.head_cx - fx * 0.5, g.neck + 4.5)
            cand = hcent
        else:
            sh_src = (g.head_cx + s_ * (6.6 if fx == 0 else ((5.4 if s_ * fx > 0 else 6.2) - (0.6 if direction in BACK else 0))), g.neck + 4.0)
            cand = [h_ for h_ in hcent if s_ * (h_[0] - g.head_cx) > 2]
        if cand:
            hb = max(cand, key=lambda h_: h_[2])
            hand_o = wp.pt((hb[0], hb[1] - 1.0))
            memo[(direction, anim, s_, k)] = hand_o
            memo[(direction, "hand", s_)] = hand_o
        else:
            hand_o = memo.get((direction, anim, s_, k), memo.get((direction, "hand", s_),
                              wp.pt((g.head_cx + s_ * 8.5 - fx * 1.0, g.hem - 3))))
        sh_o = wp.pt(sh_src)
        if direction not in PROFILE:
            # sleeve's outer edge on the jacket's shoulder line: no flap of
            # jacket sticking out past the arm
            jr_ = lab[int(round(g.neck + 5))] == JACKET
            if jr_.any():
                xs_j = xs_all[jr_]
                e_src = (xs_j.max() + 1.0) if s_ > 0 else float(xs_j.min())
                e_o = wp.pt((e_src, g.neck + 5))[0]
                sh_o = (e_o - s_ * (ARM_R - (-0.3 if direction in ("NW", "NE") else 0.7)), wp.pt((sh_src[0], g.neck + 3.4))[1])
        if direction not in PROFILE:
            hand_o = (sh_o[0] + s_ * min(1.8, max(0.8, s_ * (hand_o[0] - sh_o[0]))), hand_o[1])
        out_x = s_ if direction not in PROFILE else -fx
        free.append((sh_o, hand_o, out_x, s_))
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
    def draw_free_arms(free, _unused=0):
        res = []
        for sh_o, hand_o, out_x, s_ in free:
            el = elbow_of(sh_o, hand_o, out_x)
            res.append((s_, pm(arm_layer(sh_o, hand_o, el)), pm(hand_layer(hand_o)), hand_o))
        return res

    if direction in ("NW", "NE"):
        # back diagonals: the kid's own arm sits inside the torso and leaves
        # seam lines once the new arms are drawn; it is all jacket from behind
        lab = lab.copy()
        lab[np.isin(lab, (SLEEVE, HAND)) & (np.mgrid[0:lab.shape[0], 0:lab.shape[1]][0] < g.hem - 8)] = JACKET
        # the kid's arm was cut out of the torso: fill the torso back to the
        # shoulder-row width down to the waist
        jy = np.nonzero((lab == JACKET).any(1))[0]
        if len(jy):
            y_s = int(jy.min()) + 3
            xs_r = np.nonzero(lab[y_s] == JACKET)[0]
            if len(xs_r):
                xl, xr = xs_r.min(), xs_r.max()
                for y_ in range(y_s, int(jy.max()) + 1):
                    seg_ = lab[y_, xl:xr + 1]
                    seg_[np.isin(seg_, (BG,))] = JACKET
        # the kid's hip-height hand was labelled pants: inside the jacket it
        # is jacket (pants pixels with jacket on both sides in the row)
        for y_ in range(lab.shape[0]):
            jx = np.nonzero(lab[y_] == JACKET)[0]
            if len(jx) < 2:
                continue
            row = lab[y_]
            px_ = np.nonzero(row == PANTS)[0]
            inside = px_[(px_ > jx.min()) & (px_ < jx.max())]
            row[inside] = JACKET
    L, union, rgb, lines = render_body(lab, wp, fx if direction in PROFILE else 0)
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
    # bigger head, closer to James's chibi head:body ratio, scaled about the
    # chin so it stays on the neck
    hm2 = grow(hm, np.ones_like(hm), 3)
    ba = np.asarray(body).copy()
    hl_ = ba.copy()
    hl_[~hm2] = 0
    cyb = hy.max()
    ax = float(np.median(hx[hy >= cyb - 2 * SS]))
    ay = float(cyb)
    k_ = HEAD_SCALE * (0.94 if direction in BACK else 1.0)
    big = Image.fromarray(hl_, "RGBA").transform(
        body.size, Image.AFFINE, (1 / k_, 0, ax - ax / k_, 0, 1 / k_, ay - ay / k_), resample=Image.NEAREST)
    body = Image.alpha_composite(body, big)
    mouth = (ax / SS + (mouth[0] - ax / SS) * k_, ay / SS + (mouth[1] - ay / SS) * k_)

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
        for _, al, hl, _h in draw_free_arms(free):
            out = over(over(out, al), hl)
        if behind:
            # back views: arm and cup behind the body
            res = over(over(over(cup, handl), arm), np.zeros_like(out))
            out = over(res, out)
        else:
            out = over(over(over(out, arm), cup), handl)
    else:
        arms_l = draw_free_arms(free)
        cup_i = 0
        if direction not in PROFILE:
            cup_i = max(range(len(arms_l)), key=lambda i: arms_l[i][0] == side)
        hand = arms_l[cup_i][3]
        c = (hand[0] + (fx * 1.0 if direction in PROFILE else side * 1.4), hand[1] - 0.4)
        cup = pm(cup_layer(c))
        if behind:
            out = over(cup, out)
        for i, (_, al, hl, _h) in enumerate(arms_l):
            out = over(out, al)
            if i == cup_i and not behind:
                out = over(out, cup)
            out = over(out, hl)
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
