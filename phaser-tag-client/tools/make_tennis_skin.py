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
SHORTS = (236, 237, 236)
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
        (capsule_fn(sh, 2.7, elbow, 2.35), skin),
        (capsule_fn(elbow, 2.35, wrist, 2.0), skin),
        (capsule_fn(sh, 3.1, sleeve_end, 2.9), WHITE),
        (capsule_fn(band0, 2.35, wrist, 2.35), BAND),
        (capsule_fn(sh0, 1.3, sh1, 1.3), BAND_SHADE),
        (disc_fn(hand, 2.45), skin),
    ]


# swing: shoulder->hand angle (deg, screen, y down) over the 6 tag frames, for
# a right-hand-side (+1) arm; racket angle = arm angle + lag
SWING = {
    "profile": ([168, 142, 108, 66, 28, 6], [-35, -32, -26, -30, -38, -48]),
    "front": ([-20, 15, 55, 95, 128, 150], [-40, -25, -5, 15, 30, 35]),
    "back": ([120, 88, 55, 22, -2, -18], [25, 0, -20, -35, -45, -50]),
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
def tennify(frame, direction, anim, col, meta, memo, env_memo):
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
    r_, g_, b_ = (f[..., i].astype(np.int32) for i in range(3))
    skinlike = a & (r_ - b_ > 40) & (r_ > 110)

    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    tag = anim == "tag"
    side = TAG_SIDE[direction]

    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    head = a & (yy <= g.neck + 1)
    head &= ~(arms & (yy > g.neck - 4))
    # the base t-shirt's collar shows a little at the bottom of the head mask
    head &= ~((yy > g.neck - 3) & ~skinlike & (np.abs(xx + 0.5 - g.head_cx) < g.head_hw) &
              (b_ - r_ > 8))
    if direction in PROFILE:
        # only the near arm in side views
        far = np.zeros_like(arms)
        cs = [c for c in components8(arms) if c.sum() >= 4]
        if len(cs) > 1:
            near = max(cs, key=lambda c: c.sum())
            for comp in cs:
                if comp is not near:
                    far |= comp
        arms &= ~far
        hands &= ~far
        a &= ~far

    # torso envelope from the direction's idle frame: in tag frames anything
    # of the old reaching arm outside it goes, inside it becomes shirt
    body0 = a & ~head & ~arms
    if not tag:
        env_memo[direction] = ((body0 | arms) if direction in PROFILE else body0.copy(), g.hip_cx, head.copy(), g.head_cx)
    tag_arm = np.zeros_like(a)
    if tag:
        env, ecx, head0, hcx = env_memo[direction]
        env = np.roll(env, int(round(g.hip_cx - ecx)), 1)
        env = grow(env, np.ones_like(env), 1)
        # the head keeps its idle outline: a reaching hand at chin height goes
        head0 = grow(np.roll(head0, int(round(g.head_cx - hcx)), 1), np.ones_like(head0), 1)
        tag_arm |= head & ~head0
        head &= head0
        for comp in components8(arms):
            ys, xs = np.nonzero(comp)
            if direction in PROFILE or side * (xs.mean() + 0.5 - g.head_cx) > 0:
                tag_arm |= comp
        # reach pixels above the neck line outside the skull
        band = head & (yy >= g.neck - 14) & (yy <= g.neck - 9)
        bx = np.nonzero(band)[1]
        if len(bx):
            strip = head & (yy > g.neck - 12) & ((xx < bx.min() - 1) | (xx > bx.max() + 1))
            head &= ~strip
            tag_arm |= strip
        tside = (xx + 0.5 - g.head_cx) * side > 0 if direction not in PROFILE else np.ones_like(a)
        out_env = a & ~head & ~env & (yy > g.neck - 12) & (yy < g.hem + 5) & tside
        tag_arm |= out_env
        arms &= ~tag_arm
        hands &= ~tag_arm
    body = a & ~head & ~arms & ~tag_arm
    if tag:
        # fill the torso where the old arm lay across it
        hole = tag_arm & env & (yy > g.neck) & (yy < g.hem)
        body |= hole
        # thin outline leftovers of the old arm hugging the torso
        for _ in range(3):
            nb = sum(np.roll(np.roll(body, dy, 0), dx, 1).astype(int) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - body.astype(int)
            body &= ~(~env & (nb.astype(int) < 4) & (yy < g.hem + 5))
        for y in range(g.neck + 1, g.hem):
            xs = np.nonzero((env[y] if direction in PROFILE else body[y] & env[y]))[0]
            if len(xs):
                body[y, xs.min():xs.max() + 1] |= env[y, xs.min():xs.max() + 1]

    else:
        for _ in range(3):
            nb = sum(np.roll(np.roll(body, dy, 0), dx, 1).astype(int) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - body.astype(int)
            body &= ~((nb < 4) & (yy > g.neck) & (yy < g.hem + 5))
        for y in range(g.neck + 2, g.hem):
            xs = np.nonzero(body[y])[0]
            if len(xs):
                body[y, xs.min():xs.max() + 1] = True

    if direction not in PROFILE:
        # torso = the base idle shirt between its own outline columns (arms
        # excluded); one width per direction so it never jitters
        if ("tw", direction) not in env_memo:
            b0 = meta["_base_idle"][direction]
            env_memo[("tw", direction)] = torso_span(b0, range(58, 70), base_center(b0)) + (base_center(b0),)
        Lm, Rm, bcx = env_memo[("tw", direction)]
        cx0 = int(round(g.hip_cx))
        x0, x1 = cx0 - int(round(Lm)), cx0 + int(round(Rm)) + 1
        for y in range(g.neck + 2, g.hem - 3):
            body[y, :] = False
            body[y, max(x0, 0):min(x1, w)] = True
        env_memo[("tspan", direction)] = (x0, x1)
    else:
        # canonical torso: per-row half-widths from the direction's first idle frame
        # (monotone from the shoulders down), stamped on every frame so removed
        # arms never leave notches and the torso keeps one shape frame to frame
        tkey = ("tmpl", direction)
        if tkey not in env_memo:
            L, R = [], []
            for y in range(g.neck + 2, g.hem - 3):
                xs = np.nonzero(body[y])[0]
                L.append(g.hip_cx - xs.min() if len(xs) else 0)
                R.append(xs.max() + 1 - g.hip_cx if len(xs) else 0)
            L = np.maximum.accumulate(np.array(L, float))
            R = np.maximum.accumulate(np.array(R, float))
            env_memo[tkey] = (L, R)
        L, R = env_memo[tkey]
        for i in range(len(L)):
            y = g.neck + 2 + i
            if y >= g.hem - 3:
                break
            x0, x1 = int(round(g.hip_cx - L[i])), int(round(g.hip_cx + R[i]))
            body[y, max(x0, 0):min(x1, w)] = True
    # drop thin (<=2 px) outline strands of removed arms: 3x3 opening on the torso rows
    def _nb_all(m):
        e = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                e &= np.roll(np.roll(m, dy, 0), dx, 1)
        return e
    tz0 = (yy > g.neck + 2) & (yy < g.hem - 1)
    opened = grow(_nb_all(body), body, 1)
    body &= ~(tz0 & ~opened)
    # solid torso: close 1-2 px seams and fill pinholes left by removed arms
    tz = (yy > g.neck) & (yy < g.hem)
    for y in range(g.neck + 1, g.hem):
        row = body[y]
        for x in range(1, w - 3):
            if not row[x] and row[x - 1]:
                for gap in (1, 2):
                    if row[x + gap] and not row[x:x + gap].any():
                        row[x:x + gap] = True
                        break
    for x in range(w):
        col_ = body[:, x]
        for y in range(g.neck + 1, g.hem - 2):
            if not col_[y] and col_[y - 1]:
                for gap in (1, 2):
                    if col_[y + gap] and not col_[y:y + gap].any():
                        col_[y:y + gap] = True
                        break
    outside = np.zeros_like(body)
    outside[0, :] = outside[-1, :] = True
    outside[:, 0] = outside[:, -1] = True
    outside &= ~body
    while True:
        nxt = grow(outside, ~body, 1)
        if nxt.sum() == outside.sum():
            break
        outside = nxt
    body |= ~outside & ~body & tz
    # classes
    navy = body & ~skinlike & (b_ - g_ > 11)
    waist = g.hem - 12
    for y in range(g.neck + 6, g.hem):
        row = body[y]
        if row.sum() >= 4 and (navy[y] & row).sum() / row.sum() > 0.4:
            waist = y
            break
    shirt = body & (yy < waist)
    lower = body & (yy >= waist)
    legs_skin = lower & skinlike & (yy >= g.hem - 3)
    shoes = lower & (yy >= g.hem) & ~skinlike & ~(b_ - g_ > 11)
    top_shoe = np.full(w, 10 ** 6)
    for x in range(w):
        ys = np.nonzero(shoes[:, x])[0]
        if len(ys):
            top_shoe[x] = ys.min()
    socks = legs_skin & grow(shoes, legs_skin | shoes, 2) & (yy >= top_shoe[None, :] - 3)
    legs_skin &= ~socks
    shorts = lower & ~legs_skin & ~socks & ~shoes
    # a clear gap between the legs (front / back views)
    if direction not in PROFILE:
        best, gx = -1, None
        for x in range(int(g.hip_cx) - 4, int(g.hip_cx) + 5):
            col_ = lower[g.hem:g.bottom - 1, x]
            dark = ((r_ + g_ + b_)[g.hem:g.bottom - 1, x] < 110) & col_
            sc = int(dark.sum()) * 2 - int(col_.sum()) // 3
            if sc > best:
                best, gx = sc, x
        if gx is not None and best > 2:
            cut_ = (xx == gx) & (yy >= g.hem) & (yy <= g.bottom - 1)
            for m_ in (shoes, socks, legs_skin, lower):
                m_ &= ~cut_
    sole = shoes & ((yy >= g.bottom - 1) | ((r_ + g_ + b_) > 450))
    skin_px = f[face][:, :3]
    skin = tuple(int(v) for v in np.median(skin_px, 0)) if len(skin_px) else (240, 180, 130)
    lum = r_ + g_ + b_
    details = lower & (yy >= g.hem - 2) & (lum < 45) & ~shoes & ~socks
    body_im = class_layer([(shirt, WHITE), (shorts, SHORTS), (legs_skin, skin), (socks, SOCK),
                           (shoes & ~sole, SHOE), (sole, SOLE)], LINE)

    # base arms (non-tag ones): sleeve near the shoulder, skin, wristband, hand
    arm_geo = []
    for comp in components8(arms):
        if comp.sum() < 6:
            continue
        ys, xs = np.nonzero(comp)
        if direction in PROFILE:
            shp = (g.head_cx - PROFILE[direction] * 0.5, g.neck + 4.5)
        else:
            sd = 1 if xs.mean() + 0.5 > g.head_cx else -1
            shp = (g.head_cx + sd * 8.0, g.neck + 4.5)
        hm = hands & comp
        if hm.any():
            hy_, hx_ = np.nonzero(hm)
            hp = (hx_.mean() + 0.5, hy_.mean() + 0.5)
        else:
            dd = (xs + 0.5 - shp[0]) ** 2 + (ys + 0.5 - shp[1]) ** 2
            kk = int(dd.argmax())
            hp = (xs[kk] + 0.5, ys[kk] - 1.0)
        arm_geo.append([comp, shp, hp])

    # headband: a strip across the head at the hairline
    hb0 = g.top + 12
    hband = head & (yy >= hb0) & (yy <= hb0 + 3)
    head_band_im = class_layer([(hband & (yy < hb0 + 3), BAND), (hband & (yy >= hb0 + 3), BAND_SHADE)], LINE, 0.55, seams=False)

    # polo collar: coral V trim at the neck (front views), collar line otherwise
    coll = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    cd = ImageDraw.Draw(coll)
    cy = g.neck + 1.6
    if direction in FRONT:
        cx = g.head_cx + FRONT[direction] * 1.5
        cd.line([(S(cx - 3.4), S(cy)), (S(cx), S(cy + 3.4)), (S(cx + 3.4), S(cy))], fill=TRIM, width=int(S(0.6)), joint="curve")
    elif direction in PROFILE:
        fc = PROFILE[direction]
        cd.line([(S(g.head_cx - fc * 4), S(cy - 0.4)), (S(g.head_cx + fc * 3.2), S(cy + 1.4))], fill=TRIM, width=int(S(0.55)))
    else:
        cd.line([(S(g.head_cx - 4.5), S(cy)), (S(g.head_cx + 4.5), S(cy))], fill=TRIM, width=int(S(0.55)))

    # racket + (tag) the drawn arm
    key = (direction, anim)
    drawn_arm = None
    hand_comp = None
    behind = False
    if tag:
        n = rng["count"]
        ai, ri = swing_pose(direction, min(k, n - 1))
        if direction in PROFILE:
            sh = (g.head_cx - PROFILE[direction] * 0.5, g.neck + 4.5)
        else:
            sh = (g.head_cx + side * ARM_X, g.neck + 4.5)
        reach = 15.0
        hand = (sh[0] + math.cos(ai) * reach, sh[1] + math.sin(ai) * reach)
        # elbow droops (down / away from the head)
        e1 = ik(sh, hand, 8.3, 7.9, 1)
        e2 = ik(sh, hand, 8.3, 7.9, -1)
        elbow = e1 if e1[1] >= e2[1] else e2
        drawn_arm = shapes_layer(size, arm_parts(sh, elbow, hand, skin), LINE, 0.55)
        hx, hy = hand
        rang = ri
    else:
        # procedural pendulum hand: no frame-to-frame pops from pixel detection
        n = rng["count"]
        amp = {"walk": 26.0, "run": 40.0}.get(anim, 0.0)
        phi = math.radians(amp) * math.sin(2 * math.pi * k / max(n, 1))
        sh = racket_shoulder(g, direction, side)
        hx, hy = pend_hand(sh, direction, side, phi)
        if direction in PROFILE:
            rang = math.radians(90 - PROFILE[direction] * 62) - PROFILE[direction] * phi * 0.6
        else:
            rang = math.radians(90 - side * 58)
        behind = direction in BACK
    racket_im = racket_layer(size, (hx, hy), rang)
    base_arm_ims = []
    n_ = rng["count"]
    amp_ = {"walk": 26.0, "run": 40.0}.get(anim, 0.0)
    phi_ = math.radians(amp_) * math.sin(2 * math.pi * k / max(n_, 1))
    geo = []
    if not tag:
        sh = racket_shoulder(g, direction, side)
        geo.append((sh, (hx, hy)))
    if direction not in PROFILE:
        osd = -side if side else -1
        sh2 = (g.head_cx + osd * ARM_X, g.neck + 4.5)
        geo.append((sh2, pend_hand(sh2, direction, osd, -phi_)))
    for shp, hp in geo:
        e1 = ik(shp, hp, 8.0, 7.6, 1)
        e2 = ik(shp, hp, 8.0, 7.6, -1)
        out_sd = 1 if hp[0] >= g.head_cx else -1
        el = e1 if out_sd * e1[0] >= out_sd * e2[0] else e2
        base_arm_ims.append(shapes_layer(size, arm_parts(shp, el, hp, skin, 0.45), LINE, 0.55))
    # base hand pixels closing over the grip (non-tag)
    grip = None
    if hand_comp is not None:
        grip = hand_comp

    cv = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    if behind:
        cv.alpha_composite(racket_im)
    if body_im is not None:
        cv.alpha_composite(body_im)
    cv.alpha_composite(coll)
    out = down(cv)
    dl = np.zeros((h, w, 4))
    dl[details] = (*[c / 255 for c in LINE], 1.0)
    out = over(out, dl * 0.85)
    out = over(out, premul(f, head.astype(np.float64)))
    if head_band_im is not None:
        out = over(out, down(head_band_im))
    if not behind:
        out = over(out, down(racket_im))
    for im_ in base_arm_ims:
        out = over(out, down(im_))
    if drawn_arm is not None:
        out = over(out, down(drawn_arm))
    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    # close 1-2 px seams inside the torso (between body and redrawn arms)
    al = res[..., 3].astype(int)
    for y in range(int(g.neck) + 2, int(g.hem) + 1):
        row = al[y]
        for x in range(1, w - 2):
            if row[x] < 200:
                for gap in (1, 2):
                    if x + gap < w and row[x - 1] >= 200 and row[x + gap] >= 200 and all(row[x:x + gap] < 200):
                        for q in range(gap):
                            res[y, x + q] = res[y, x - 1] if q == 0 else res[y, x + gap]
                        break
        al[y] = res[y, :, 3]
    # drop stray specks not attached to the figure
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 40:
                res[grow(c, np.ones_like(c), 1) & ~grow(big, np.ones_like(big), 1)] = 0
    # every pixel inside the silhouette fully opaque (no see-through holes)
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
