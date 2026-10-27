#!/usr/bin/env python3
"""Build the "Tennis James" sprite sheet (public/assets/kid_tennis.png/json)
from the base kid sheet.

Same smooth pipeline as make_wizard_skin.py: flat-colour class maps,
supersampled 4x, blurred and thresholded so every edge is smooth, outlined,
then box-downscaled.

  * a white tennis polo (coral collar trim) and white shorts over James's
    normal body, white socks and white sneakers; legs and arms are flat skin;
  * a white headband and white wristbands on both wrists; face and hair are
    James's own pixels;
  * a black-and-yellow racket (strings visible) in the tagging hand in every
    frame, held out in front of the way he faces;
  * tag is a full forehand: in tag frames the tagging arm is redrawn as one
    solid limb (sleeve, upper arm, forearm, wristband, hand) from the
    shoulder, swinging the racket from the back-swing through contact to the
    follow-through. It is drawn over the body, so nothing hides behind it.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_tennis_skin.py [--preview /tmp/tennis_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from make_banana_skin import Geometry, alpha_mask, arms_and_hands, components8, grow, skin_mask
from solid_mask import base_center, solidify, torso_span
from make_pirate_skin import TAG_SIDE, anim_of, pick_hand
from make_tuxedo_skin import close_streaks
from make_wizard_skin import arm_tip, down, over, premul, reach_tip, to_u8, up_mask

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 14
PAD_SIDE = 24
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}

WHITE = (247, 247, 243)
SHORTS = (210, 214, 222)
WAISTBAND = (140, 148, 164)
ARM_LINE = (40, 26, 22)
SOCK = (250, 250, 248)
SHOE = (244, 244, 246)
SOLE = (196, 200, 208)
LINE = (70, 74, 84)
TRIM = (240, 112, 92)
BAND = (252, 252, 250)
R_BLACK = (24, 24, 28)
R_YELLOW = (238, 214, 30)
R_GRIP = (40, 40, 44)
STRING = (150, 154, 150)
BED = (232, 234, 224)
BAND_SHADE = (214, 218, 226)
SKIN_LINE = (120, 70, 50)


def S(v):
    return v * SS


def pad_frame(frame):
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def class_layer(classes, line, line_w=0.75, seams=True):
    """Smooth flat-colour layer from 1x class masks (SS RGBA), outlined, with
    a thin seam where two classes meet."""
    classes = [(m, c) for m, c in classes if m.any()]
    if not classes:
        return None
    fields = np.stack([up_mask(m) for m, _ in classes])
    union = up_mask(np.any([m for m, _ in classes], axis=0)) >= 0.5
    lab = fields.argmax(0)
    h, w = union.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for k, (_, col) in enumerate(classes):
        rgb[lab == k] = col
    if seams:
        sm = np.zeros_like(union)
        for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            sm |= np.roll(lab, (dy, dx), (0, 1)) != lab
        sm = np.asarray(Image.fromarray((sm * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 127
        rgb[sm & union] = line
    sil = Image.fromarray((union * 255).astype(np.uint8))
    k = int(round(line_w * SS)) * 2 + 1
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(k))) > 127
    rgb[union & ~inner] = line
    return Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")


def shapes_layer(size, parts, line, line_w=0.7):
    """Vector parts [(draw_fn, colour)] at SS: each part is painted in order,
    the union gets one outline (so a limb reads as a single solid shape)."""
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


# --- racket --------------------------------------------------------------------
def racket_layer(size, hand, ang):
    """Black frame with a yellow accent band, yellow throat, black/yellow
    handle with grip wrap, opaque string bed with a visible string grid.
    The handle runs through the hand so the fist closes round the grip."""
    h, w = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ux, uy = math.cos(ang), math.sin(ang)
    nx, ny = -uy, ux

    def P(t, s=0.0):
        return (S(hand[0] + ux * t + nx * s), S(hand[1] + uy * t + ny * s))

    def quad(t0, t1, r0, r1, col):
        d.polygon([P(t0, r0), P(t1, r1), P(t1, -r1), P(t0, -r0)], fill=col)

    # handle: black outline, grip wrap, yellow butt band
    quad(-4.6, 7.6, 1.45, 1.25, R_BLACK)
    quad(-3.9, 5.0, 0.95, 0.85, R_GRIP)
    for t in np.arange(-3.4, 5.0, 1.3):
        d.line([P(t, -0.9), P(t + 0.7, 0.9)], fill=R_BLACK, width=max(1, int(S(0.3))))
    quad(-4.4, -3.6, 1.2, 1.2, R_YELLOW)
    # throat: yellow beams with black edges
    a, b = 11.2, 8.4
    c_t = 7.0 + 2.2 + a
    c = (hand[0] + ux * c_t, hand[1] + uy * c_t)
    for sg in (1, -1):
        d.line([P(7.0, sg * 0.7), P(c_t - a + 1.6, sg * 4.6)], fill=R_BLACK, width=int(S(1.9)))
        d.line([P(7.2, sg * 0.7), P(c_t - a + 1.4, sg * 4.4)], fill=R_YELLOW, width=int(S(0.9)))
    d.polygon([P(7.4, 0.5), P(c_t - a + 2.2, 3.4), P(c_t - a + 2.2, -3.4), P(7.4, -0.5)], fill=R_BLACK)
    ring = [(S(c[0] + ux * a * math.cos(t) + nx * b * math.sin(t)),
             S(c[1] + uy * a * math.cos(t) + ny * b * math.sin(t))) for t in np.linspace(0, 2 * math.pi, 72)]
    # opaque string bed + string grid, clipped to the head
    bed = Image.new("RGBA", im.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bed)
    bd.polygon(ring, fill=BED + (255,))
    sw = max(1, int(S(0.32)))
    for k in np.arange(-a + 1.6, a - 0.8, 1.8):
        bd.line([(S(c[0] + ux * k - nx * b), S(c[1] + uy * k - ny * b)),
                 (S(c[0] + ux * k + nx * b), S(c[1] + uy * k + ny * b))], fill=STRING + (255,), width=sw)
    for k in np.arange(-b + 1.5, b - 0.7, 1.8):
        bd.line([(S(c[0] - ux * a + nx * k), S(c[1] - uy * a + ny * k)),
                 (S(c[0] + ux * a + nx * k), S(c[1] + uy * a + ny * k))], fill=STRING + (255,), width=sw)
    clip = Image.new("L", im.size, 0)
    ImageDraw.Draw(clip).polygon(ring, fill=255)
    bed.putalpha(Image.fromarray(np.minimum(np.asarray(bed.split()[3]), np.asarray(clip))))
    im.alpha_composite(bed)
    # bold black frame, yellow accent band along both sides, black tip
    d.line(ring + [ring[0]], fill=R_BLACK, width=int(S(2.1)), joint="curve")
    for t0, t1 in ((0.75, 2.0), (-2.0, -0.75)):
        seg = [(S(c[0] + ux * a * math.cos(t) + nx * b * math.sin(t)),
                S(c[1] + uy * a * math.cos(t) + ny * b * math.sin(t))) for t in np.linspace(t0, t1, 16)]
        d.line(seg, fill=R_YELLOW, width=int(S(0.95)), joint="curve")
    return im


# --- the drawn tagging arm ----------------------------------------------------------
def ik(sh, hand, L1, L2, bend):
    dx, dy = hand[0] - sh[0], hand[1] - sh[1]
    dd = math.hypot(dx, dy) or 1.0
    dd2 = min(dd, L1 + L2 - 0.05)
    a = (L1 * L1 - L2 * L2 + dd2 * dd2) / (2 * dd2)
    hh = math.sqrt(max(L1 * L1 - a * a, 0.0))
    ux, uy = dx / dd, dy / dd
    px, py = -uy * bend, ux * bend
    return (sh[0] + ux * a + px * hh, sh[1] + uy * a + py * hh)


def arm_parts(sh, elbow, hand, skin, sleeve=0.4):
    ex, ey = hand[0] - elbow[0], hand[1] - elbow[1]
    en = math.hypot(ex, ey) or 1.0
    ux, uy = ex / en, ey / en
    wrist = (hand[0] - ux * 1.7, hand[1] - uy * 1.7)
    band0 = (hand[0] - ux * 3.9, hand[1] - uy * 3.9)
    sx, sy = elbow[0] - sh[0], elbow[1] - sh[1]
    sleeve_end = (sh[0] + sx * sleeve, sh[1] + sy * sleeve)
    # shade the wristband on its lower edge
    nx, ny = -uy, ux
    if ny < 0:
        nx, ny = -nx, -ny
    sh0 = (band0[0] + nx * 1.0, band0[1] + ny * 1.0)
    sh1 = (wrist[0] + nx * 1.0, wrist[1] + ny * 1.0)
    return [
        (capsule_fn(sh, 3.0, elbow, 2.6), skin),
        (capsule_fn(elbow, 2.6, wrist, 2.3), skin),
        (capsule_fn(sh, 3.2, sleeve_end, 3.0), WHITE),
        (capsule_fn(band0, 2.6, wrist, 2.6), BAND),
        (capsule_fn(sh0, 1.3, sh1, 1.3), BAND_SHADE),
        (disc_fn(hand, 2.8), skin),
    ]


# swing: shoulder->hand angle (deg, screen, y down) over the 6 tag frames, for
# a right-hand-side (+1) arm; racket angle = arm angle + lag
def _arc(a0, a1, l0, l1, n=6):
    """n evenly spaced poses on one arc: equal arm steps, linearly changing
    racket lag (so the racket angle changes monotonically)"""
    return ([a0 + (a1 - a0) * i / (n - 1) for i in range(n)],
            [l0 + (l1 - l0) * i / (n - 1) for i in range(n)])


# start near the idle hang (racket low in front), wind back, swing through,
# settle back toward idle so entering / leaving the tag doesn't pop
SWING = {
    "profile": ([95, 150, 115, 45, 15, 70], [-55, -45, -40, -45, -50, -55]),
    "front": ([75, 15, -25, 35, 105, 80], [-40, -40, -35, 5, 25, -35]),
    "back": ([80, 130, 105, 35, -5, 60], [-45, 20, 15, -30, -45, -45]),
}


def swing_pose(direction, p_idx):
    if direction in PROFILE:
        arm, lag = SWING["profile"]
        s = PROFILE[direction]
    elif direction in FRONT:
        arm, lag = SWING["front"]
        s = TAG_SIDE[direction]
    else:
        arm, lag = SWING["back"]
        s = TAG_SIDE[direction]
    a, r = arm[p_idx], arm[p_idx] + lag[p_idx]
    if s < 0:
        a, r = 180 - a, 180 - r
    return math.radians(a), math.radians(r)




ARM_X = 9.5


def racket_shoulder(g, direction, side):
    if direction in PROFILE:
        return (g.head_cx - PROFILE[direction] * 0.5, g.neck + 4.5)
    return (g.head_cx + (side or 1) * ARM_X, g.neck + 4.5)


def pend_hand(sh, direction, side, phi):
    """hand of a hanging arm swung by phi (rad) about the shoulder"""
    R = 15.0
    if direction in PROFILE:
        fx = PROFILE[direction]
        return (sh[0] + fx * R * math.sin(phi) + fx * 1.0, sh[1] + R * math.cos(phi))
    fx = {"SE": 1, "SW": -1, "NE": 1, "NW": -1}.get(direction, 0) * (1 if direction in FRONT else -1)
    out = (side or 1) * 4.5
    return (sh[0] + out + fx * 0.3 * R * math.sin(phi), sh[1] + R * (0.96 - 0.12 * abs(math.sin(phi))))


# --- per frame ----------------------------------------------------------------------
def loose_skinlike(f):
    r, g, b = (f[..., i].astype(np.int32) for i in range(3))
    return (f[..., 3] >= 128) & (r - b > 25) & (r - g > 14) & (r > 70)


def recolor(f, g):
    """Recolour the base kid frame in place of the outfit: slate tee -> white
    polo (short sleeves), navy shorts -> white shorts, shoes -> white sneakers
    with a grey sole. Silhouette, outlines, skin, face and hair stay base."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = f[..., 3] >= 128
    c = f[..., :3].astype(np.float64)
    lum = c.mean(-1)
    r_, g_, b_ = c[..., 0], c[..., 1], c[..., 2]
    skin = loose_skinlike(f)
    line = lum < 26
    cloth = a & ~skin & ~line
    # collar bits of the tee poke into the head mask: slate, bluish, near neck
    head = yy <= g.neck + 1
    tee_col = (b_ - r_ > 4) & (lum > 40) & (lum < 140)
    cloth &= ~head | ((yy > g.neck - 3) & tee_col)
    navy = cloth & (b_ - g_ > 11)
    waist = g.hem - 12
    for y in range(g.neck + 6, g.hem):
        row = cloth[y] | skin[y]
        if row.sum() >= 4 and navy[y].sum() / row.sum() > 0.4:
            waist = y
            break
    shirt = cloth & (yy < waist)
    shorts = cloth & (yy >= waist) & (yy < g.hem + 1)
    shoes = cloth & (yy >= g.hem + 1)
    out = f.copy().astype(np.float64)

    def paint(m, col, lo=0.80, hi=1.0):
        if not m.any():
            return
        ref = np.percentile(lum[m], 80) or 1.0
        k = np.clip(lo + (hi - lo) * lum[m] / ref, lo, hi)
        out[m, :3] = np.array(col, float)[None] * k[:, None]

    paint(shirt, WHITE)
    paint(shorts, SHORTS, 0.82)
    # waistband: the top row of the shorts in every column, a darker grey line
    if shorts.any():
        top = shorts & ~np.roll(shorts, 1, 0)
        top &= yy <= waist + 1
        out[top, :3] = WAISTBAND
    # sneakers: white uppers, the bottom 1-2 rows of each shoe grey sole
    sole = np.zeros_like(shoes)
    for x in range(w):
        ys = np.nonzero(shoes[:, x] | (line[:, x] & (yy[:, x] > g.hem)))[0]
        if len(ys) and shoes[:, x].any():
            sole[ys.max() - 1:ys.max() + 1, x] = True
    paint(shoes & ~sole, SHOE, 0.82)
    out[shoes & sole, :3] = SOLE
    # soften the black outline next to white cloth a little
    near_cloth = line & grow(shirt | shorts | shoes, a, 1) & ~head
    out[near_cloth, :3] = LINE
    return to_u8_simple(out), shirt, skin


def to_u8_simple(x):
    return np.clip(np.round(x), 0, 255).astype(np.uint8)


def wrist_bands(f, g, hands, side_ok, skin):
    """white wristbands on the skin just above each hand"""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = f.copy()
    for comp in components8(hands & (yy > g.neck + 2)):
        if comp.sum() < 3:
            continue
        ys, xs = np.nonzero(comp)
        hcx, hcy = xs.mean() + 0.5, ys.mean() + 0.5
        sd = 1 if hcx > g.head_cx else -1
        sh = (g.head_cx + sd * 7.0, g.neck + 4.0)
        dh = np.hypot(xx + 0.5 - hcx, yy + 0.5 - hcy)
        ds = np.hypot(xx + 0.5 - sh[0], yy + 0.5 - sh[1])
        L = math.hypot(hcx - sh[0], hcy - sh[1])
        y0 = ys.min()
        band = skin & ~comp & (yy >= y0 - 2) & (yy < y0) & (np.abs(xx + 0.5 - hcx) < 3.5)
        if band.any():
            lower = band & ~np.roll(band, 1, 0)
            out[band, :3] = BAND
            out[band & np.roll(band, -1, 0) & ~np.roll(band, 1, 0), :3] = BAND
            bot = band & ~np.roll(band, -1, 0)
            out[bot, :3] = BAND_SHADE
    return out


def arm_comps_on(arms, g, direction, side):
    m = np.zeros_like(arms)
    for comp in components8(arms):
        if comp.sum() < 4:
            continue
        xs = np.nonzero(comp)[1]
        if direction in PROFILE or side == 0 or (xs.mean() + 0.5 - g.head_cx) * side > 0:
            m |= comp
    return m


def headband(f, g, head):
    h, w = f.shape[:2]
    yy = np.mgrid[0:h, 0:w][0]
    hb0 = g.top + 12
    band = head & (yy >= hb0) & (yy <= hb0 + 3) & (f[..., 3] >= 128)
    out = f.copy()
    out[band & (yy < hb0 + 3), :3] = BAND
    out[band & (yy >= hb0 + 3), :3] = BAND_SHADE
    # outline the band's top/bottom edge where it meets hair
    edge = band & ((yy == hb0) | (yy == hb0 + 3))
    out[edge & (yy == hb0), :3] = (200, 202, 206)
    return out


def shift(img, dx, dy):
    o = np.zeros_like(img)
    h, w = img.shape[:2]
    ys0, ys1 = max(dy, 0), h + min(dy, 0)
    xs0, xs1 = max(dx, 0), w + min(dx, 0)
    o[ys0:ys1, xs0:xs1] = img[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return o


def tag_base(f, g, direction, side, idle_f):
    """tag body: the direction's idle frame (head, torso, legs: steady, no
    pops), its swing-side arm removed / painted over and the notches closed,
    so the drawn swing arm is the only arm on that side"""
    gi = Geometry(idle_f)
    # the whole body comes from idle (no shift): steady head/torso/legs
    idl = idle_f.copy()
    gi = Geometry(idl) if alpha_mask(idl).any() else gi
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    face_i = (yy <= gi.neck + 1) & skin_mask(idl)
    arms_i, _ = arms_and_hands(idl, gi, face_i)
    rm_i = arm_comps_on(arms_i, gi, direction, side)
    rm = grow(rm_i, alpha_mask(idl), 1) & (yy > gi.neck + 1)
    # arm pixels lying over the torso (between body pixels on both sides of
    # the row) are painted as tee / shorts so the base silhouette (width) is
    # kept exactly; arm pixels outside the torso are removed
    ai = alpha_mask(idl)
    keep = ai & ~rm
    over_t = np.zeros_like(rm)
    for y in range(h):
        xs = np.nonzero(keep[y])[0]
        if len(xs) >= 2:
            over_t[y, xs.min() + 1:xs.max()] = True
    over_t &= rm
    if direction in PROFILE or direction in ("NE", "NW"):
        # the hanging arm lies over the body here: repaint all of it so the
        # idle silhouette is kept whole (no chunk out of chest / back)
        over_t = rm & ai
    # arm pixels inside the torso core (hip centre +- half hem width - 3)
    # are always torso: repaint, never cut (no chunk out of the body)
    ys = np.nonzero(ai.any(1))[0]
    hb = ys.max() - 6
    hem = np.nonzero(ai[hb - 8:hb])[1]
    if len(hem):
        hx = int(np.median(hem))
        core = (hem.max() - hem.min()) // 2 - 3
        over_t |= rm & ai & (np.abs(xx - hx) <= core)
    inner = ai.copy()
    for sy, sx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        inner &= np.roll(ai & (keep | over_t), (sy, sx), (0, 1))
    c = idl[..., :3].astype(np.int32)
    lum = c.mean(-1)
    sk = loose_skinlike(idl)
    ok = ai & ~sk & ~rm & (lum > 35)
    navy = ok & (c[..., 2] - c[..., 1] > 11)
    tee = ok & ~navy & (yy > gi.neck + 2) & (yy < gi.hem - 8)
    tee_c = np.median(idl[tee][:, :3], 0) if tee.any() else (60, 77, 84)
    sh_c = np.median(idl[navy][:, :3], 0) if navy.any() else (30, 40, 60)
    waist = int(np.median(np.nonzero(navy)[0]) - 3) if navy.any() else gi.hem - 10
    for m, col in (((yy < waist), tee_c), ((yy >= waist), sh_c)):
        idl[over_t & inner & m, :3] = col
    idl[over_t & ~inner, :3] = (22, 24, 30)
    idl[rm & ~over_t] = 0
    # close notches the arm removal left (armpit / chest / back): every
    # transparent pixel between body pixels of a torso row becomes tee/shorts
    ai = alpha_mask(idl)
    for y in range(int(gi.neck) + 2, int(gi.hem) + 1):
        xs = np.nonzero(ai[y])[0]
        if len(xs) < 2:
            continue
        hole = np.zeros(w, bool)
        hole[xs.min():xs.max() + 1] = True
        hole &= ~ai[y]
        if hole.any():
            idl[y, hole, :3] = tee_c if y < waist else sh_c
            idl[y, hole, 3] = 255
    # the outer edge where the arm was cut off gets an outline pixel
    ai = alpha_mask(idl)
    edge = ai & ~np.roll(ai, 1, 1) | ai & ~np.roll(ai, -1, 1)
    cut = edge & grow(rm & ~over_t, np.ones_like(ai), 1) & (yy > gi.neck + 1)
    idl[cut, :3] = (22, 24, 30)
    return idl


def tennify(frame, direction, anim, col, meta, memo, env_memo):
    f = pad_frame(frame)
    a = alpha_mask(f)
    if not a.any():
        return f
    g = Geometry(f)
    h, w = a.shape
    size = (h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    tag = anim == "tag"
    side = TAG_SIDE[direction]

    if tag:
        f = tag_base(f, g, direction, side, pad_frame(meta["_base_idle"][direction]))
        g = Geometry(f)
    a = alpha_mask(f)
    rc, shirt, skin = recolor(f, g)
    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    head = a & (yy <= g.neck + 1)
    rc = headband(rc, g, head)
    rc = wrist_bands(rc, g, hands, None, skin)
    # arm skin colour: the base's own lit skin (face + limbs), never shadows
    sk_all = skin_mask(f)
    if sk_all.any():
        px_ = f[sk_all][:, :3].astype(int)
        px_ = px_[px_.sum(1) >= np.percentile(px_.sum(1), 50)]
        skin_rgb = tuple(int(v) for v in np.median(px_, 0))
        # a touch deeper than the lit face so the arm reads on the white shirt
        skin_rgb = tuple(int(v * k) for v, k in zip(skin_rgb, (0.95, 0.84, 0.78)))
    else:
        skin_rgb = (246, 182, 132)

    behind = False
    drawn = None
    hand_px = None
    if tag:
        n = rng["count"]
        ai, ri = swing_pose(direction, min(k, n - 1))
        sh = racket_shoulder(g, direction, side)
        if direction not in PROFILE:
            sh = (g.head_cx + (side or 1) * 7.5, g.neck + 4.5)
        hand = (sh[0] + math.cos(ai) * 15.0, sh[1] + math.sin(ai) * 15.0)
        e1 = ik(sh, hand, 8.3, 7.9, 1)
        e2 = ik(sh, hand, 8.3, 7.9, -1)
        elbow = e1 if e1[1] >= e2[1] else e2
        drawn = shapes_layer(size, arm_parts(sh, elbow, hand, skin_rgb, 0.3), ARM_LINE, 1.2)
        hx, hy = hand
        rang = ri
    else:
        pick = pick_hand(hands & (yy > g.neck + 1), g, side, a)
        if pick is None:
            hc = [c for c in components8(hands & (yy > g.neck + 1)) if c.sum() >= 3]
            if hc:
                c = max(hc, key=lambda c: c.sum())
                ys_, xs_ = np.nonzero(c)
                pick = (float(xs_.mean() + 0.5), float(ys_.mean() + 0.5), c)
        if pick is not None:
            hx, hy, comp = pick
            hand_px = comp
            memo[(direction, anim)] = (hx, hy)
        else:
            hx, hy = memo.get((direction, anim), (g.hip_cx + (side or 1) * 9.0, g.hem - 6.0))
        if direction in PROFILE:
            rang = math.radians(90 - PROFILE[direction] * 62)
        else:
            rang = math.radians(90 - (side or 1) * 58)
        behind = direction in BACK
    racket = down(racket_layer(size, (hx, hy), rang))
    base = premul(rc, np.ones((h, w)))
    if behind:
        out = over(racket, base)
    else:
        out = over(base, racket)
        if hand_px is not None:
            # fingers close over the grip
            out = over(out, premul(rc, hand_px.astype(np.float64)))
    if drawn is not None:
        out = over(out, down(drawn))
    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 25:
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
        memo: dict = {}
        env_memo: dict = {}
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = tennify(
                fr, direction, anim_of(meta, c), c, meta, memo, env_memo)
    assert max(out.shape[:2]) <= 4096, out.shape
    Image.fromarray(out).save(ASSETS / "kid_tennis.png", optimize=True)
    pm = dict(meta)
    pm.pop("_base_idle", None)
    pm["image"] = "kid_tennis.png"
    pm["frameWidth"], pm["frameHeight"] = ofw, ofh
    pm["baselineY"] = meta["baselineY"] + PAD_TOP
    pm["anchorX"] = ofw // 2
    (ASSETS / "kid_tennis.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_tennis.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")
    np.save("/tmp/tennis_full.npy", out)

    if args.preview:
        img = Image.fromarray(out)
        scale, pad = args.scale, 40
        picks = [0, 6, 9, 13, 16, 18, 19, 21, 24, 27]
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
