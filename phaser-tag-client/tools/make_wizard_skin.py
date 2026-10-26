#!/usr/bin/env python3
"""Build the "Wizard James" sprite sheet (public/assets/kid_wizard.png/json)
from the base kid sheet.

Modelled on make_pirate_skin.py (same frame padding, tag-hand tracking and
held-item rules) with the smooth 4x rendering of make_trex_skin.py:

  * the body under the robe (white shirt, dark trousers, black shoes) is a
    flat-colour class map, supersampled 4x, blurred + thresholded so every
    edge is smooth, outlined and box-downscaled;
  * a long black hooded school-style robe with crimson lining is drawn as a
    4x vector layer over the body (open at the front over the shirt and a
    red/gold striped tie; hood hanging on the back), its hem flaring and
    swaying with the walk/run cycle;
  * the arms become black robe sleeves with crimson cuffs; hands, face and
    hair are James's own pixels, untouched;
  * round wire-rim spectacles with clear glass (James's real eyes show
    through) and a red lightning-bolt scar centred on the forehead
    (front/side views, hidden from the back);
  * a wand in the tagging hand (in front of the body, behind it in back
    views) that sweeps through an arc on tag with a sparkle burst at the tip.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_wizard_skin.py [--preview /tmp/wizard_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from make_banana_skin import (Geometry, alpha_mask, arms_and_hands, components8, grow,
                              loose_skin, skin_mask)
from make_pirate_skin import TAG_SIDE, anim_of, pick_hand
from make_tuxedo_skin import close_streaks

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 12
PAD_SIDE = 20
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}
FACE_DIRS = {"E", "SE", "S", "SW", "W"}

ROBE = (40, 38, 46)
ROBE_LINE = (12, 10, 16)
CRIMSON = (156, 26, 40)
CRIMSON_DARK = (104, 14, 26)
SHIRT = (242, 240, 234)
TROUSERS = (74, 74, 86)
SHOES = (22, 22, 26)
BODY_LINE = (24, 22, 28)
TIE_RED = (168, 28, 38)
TIE_GOLD = (226, 178, 52)
LENS = (16, 16, 22)
LENS_GLINT = (110, 124, 150)
FRAME = (30, 28, 34)
SCAR = (212, 30, 40)
GLINT = (236, 244, 255, 170)
WAND = (74, 46, 28)
WAND_LINE = (30, 18, 10)
WAND_TIP = (236, 224, 190)
SPARK = (255, 236, 120)
SPARK_HOT = (255, 255, 240)


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def S(v: float) -> float:
    return v * SS


def up_mask(m: np.ndarray) -> np.ndarray:
    """1x bool mask -> smooth SS float (0..1) field."""
    h, w = m.shape
    im = Image.fromarray((m * 255).astype(np.uint8)).resize((w * SS, h * SS), Image.BILINEAR)
    im = im.filter(ImageFilter.GaussianBlur(SS * 0.45))
    return np.asarray(im).astype(np.float64) / 255.0


def class_layer(classes: list[tuple[np.ndarray, tuple]], line, line_w=0.75) -> Image.Image:
    """Smooth flat-colour layer from 1x class masks (SS RGBA)."""
    fields = [up_mask(m) for m, _ in classes]
    union = up_mask(np.any([m for m, _ in classes], axis=0)) >= 0.5
    st = np.stack(fields)
    lab = st.argmax(0)
    h, w = union.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for k, (_, col) in enumerate(classes):
        rgb[lab == k] = col
    sil = Image.fromarray((union * 255).astype(np.uint8))
    k = int(round(line_w * SS)) * 2 + 1
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(k))) > 127
    rgb[union & ~inner] = line
    a = (union * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def down(im: Image.Image) -> np.ndarray:
    """SS RGBA -> 1x premultiplied float (0..1)."""
    arr = np.asarray(im).astype(np.float64) / 255.0
    pm = arr.copy()
    pm[..., :3] *= pm[..., 3:4]
    h, w = arr.shape[0] // SS, arr.shape[1] // SS
    return pm.reshape(h, SS, w, SS, 4).mean((1, 3))


def over(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    return src + dst * (1.0 - src[..., 3:4])


def premul(f: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    x = f.astype(np.float64) / 255.0
    x[..., :3] *= x[..., 3:4]
    if mask is not None:
        x *= mask[..., None]
    return x


def to_u8(pm: np.ndarray) -> np.ndarray:
    a = pm[..., 3:4]
    rgb = np.where(a > 1e-6, pm[..., :3] / np.maximum(a, 1e-6), 0)
    return np.clip(np.concatenate([rgb, a], -1) * 255 + 0.5, 0, 255).astype(np.uint8)


def poly(d: ImageDraw.ImageDraw, pts, fill, outline=None, width=0.8):
    p = [(S(x), S(y)) for x, y in pts]
    d.polygon(p, fill=fill)
    if outline is not None:
        d.line(p + [p[0]], fill=outline, width=max(1, int(round(S(width)))), joint="curve")


def ellipse(d, cx, cy, rx, ry, fill, outline=None, width=0.8):
    d.ellipse([S(cx - rx), S(cy - ry), S(cx + rx), S(cy + ry)], fill=fill, outline=outline,
              width=max(1, int(round(S(width)))) if outline else 0)


def bez(p0, p1, p2, n=8):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in np.linspace(0, 1, n)]


# --- robe ---------------------------------------------------------------------
def robe_layer(direction, size, top_cx, hem_cx, sh_y, hem_y, phase, run) -> Image.Image:
    h, w = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    flare = (2.5 + (1.8 if run else 1.0) * abs(phase))
    sway = phase * (1.6 if run else 1.0)
    if direction in FRONT or direction in BACK:
        lean = FRONT.get(direction, BACK.get(direction, 0))
        sw = 8.6 if lean == 0 else 7.6
        L = [(top_cx - 3.5, sh_y - 1.6), (top_cx - sw + 1.2, sh_y - 0.6), (top_cx - sw - 0.4, sh_y + 3)]
        L += bez((top_cx - sw - 0.4, sh_y + 3), (hem_cx - sw - 1.2, (sh_y + hem_y) / 2),
                 (hem_cx - sw - flare - sway * 0.6, hem_y))
        R = [(top_cx + 3.5, sh_y - 1.6), (top_cx + sw - 1.2, sh_y - 0.6), (top_cx + sw + 0.4, sh_y + 3)]
        R += bez((top_cx + sw + 0.4, sh_y + 3), (hem_cx + sw + 1.2, (sh_y + hem_y) / 2),
                 (hem_cx + sw + flare - sway * 0.6, hem_y))
        # hem: a soft wave
        hem = bez(L[-1], (hem_cx + sway, hem_y + 1.6), R[-1])
        outline = L + hem[1:-1] + R[::-1]
        poly(d, outline, ROBE, ROBE_LINE)
        if direction in FRONT:
            ox = lean * 2.0
            top_l, top_r = (top_cx - 3.2 + ox, sh_y - 1.4), (top_cx + 3.2 + ox, sh_y - 1.4)
            bot_l, bot_r = (hem_cx - 4.8 + ox + sway * 0.5, hem_y + 1.2), (hem_cx + 4.8 + ox + sway * 0.5, hem_y + 1.2)
            wide = [(top_l[0] - 1.5, top_l[1]), (top_r[0] + 1.5, top_r[1]),
                    (bot_r[0] + 1.8, bot_r[1]), (bot_l[0] - 1.8, bot_l[1])]
            poly(d, wide, CRIMSON)
            # the lining also shows a little round the collar
            poly(d, [top_l, top_r, bot_r, bot_l], (0, 0, 0, 0))
            for a_, b_ in ((wide[0], wide[3]), (wide[1], wide[2])):
                d.line([(S(a_[0]), S(a_[1])), (S(b_[0]), S(b_[1]))], fill=ROBE_LINE, width=int(S(0.6)))
        else:
            # hood hanging down the back, crimson inside
            hx = top_cx + lean * 1.2
            ellipse(d, hx, sh_y + 3.6, 6.6, 5.0, ROBE, ROBE_LINE)
            ellipse(d, hx, sh_y + 2.4, 4.4, 2.8, CRIMSON, CRIMSON_DARK, 0.6)
            d.line([(S(hx), S(sh_y + 8.4)), (S(hem_cx + sway * 0.4), S(hem_y - 3))], fill=(30, 28, 36), width=int(S(0.5)))
    else:
        fc = PROFILE[direction]
        back_top = (top_cx - fc * 4.0, sh_y - 0.4)
        front_top = (top_cx + fc * 3.4, sh_y - 1.2)
        back_hem = (hem_cx - fc * (8.0 + flare) - sway * fc * 0.4, hem_y)
        front_hem = (hem_cx + fc * (4.0 + flare * 0.4), hem_y + 0.8)
        back = bez(back_top, (hem_cx - fc * 7.5, (sh_y + hem_y) / 2), back_hem)
        hem = bez(back_hem, ((back_hem[0] + front_hem[0]) / 2, hem_y + 2.0), front_hem)
        front = bez(front_hem, (hem_cx + fc * 2.0, (sh_y + hem_y) / 2), front_top)
        poly(d, back + hem[1:] + front[1:], ROBE, ROBE_LINE)
        # crimson lining along the open front edge
        edge = bez(front_top, (hem_cx + fc * 2.0, (sh_y + hem_y) / 2), front_hem)
        inner = [(x - fc * 1.3, y) for x, y in edge[::-1]]
        poly(d, edge + inner, CRIMSON)
        # hood bunched on the back of the shoulders
        hx = top_cx - fc * 4.6
        ellipse(d, hx, sh_y + 2.0, 3.6, 4.2, ROBE, ROBE_LINE)
        ellipse(d, hx + fc * 0.6, sh_y + 1.2, 2.0, 2.6, CRIMSON, CRIMSON_DARK, 0.5)
    return im


def tie_layer(size, cx, y0, y1, lean) -> Image.Image:
    h, w = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx += lean * 1.5
    # white collar points
    poly(d, [(cx - 3.0, y0 - 1.0), (cx - 0.2, y0 + 0.4), (cx - 2.0, y0 + 2.2)], SHIRT, BODY_LINE, 0.4)
    poly(d, [(cx + 3.0, y0 - 1.0), (cx + 0.2, y0 + 0.4), (cx + 2.0, y0 + 2.2)], SHIRT, BODY_LINE, 0.4)
    knot = [(cx - 1.1, y0 + 0.2), (cx + 1.1, y0 + 0.2), (cx + 0.7, y0 + 1.8), (cx - 0.7, y0 + 1.8)]
    blade = [(cx - 0.7, y0 + 1.8), (cx + 0.7, y0 + 1.8), (cx + 1.5, y1 - 1.0), (cx, y1), (cx - 1.5, y1 - 1.0)]
    stripes = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripes)
    sd.rectangle([0, 0, im.size[0], im.size[1]], fill=TIE_RED)
    for k in range(-40, 40):
        yk = y0 + k * 2.4
        sd.polygon([(S(cx - 4), S(yk)), (S(cx + 4), S(yk - 3)), (S(cx + 4), S(yk - 2.0)), (S(cx - 4), S(yk + 1.0))],
                   fill=TIE_GOLD)
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)
    md.polygon([(S(x), S(y)) for x, y in knot], fill=255)
    md.polygon([(S(x), S(y)) for x, y in blade], fill=255)
    im.paste(stripes, (0, 0), m)
    for p in (knot, blade):
        pp = [(S(x), S(y)) for x, y in p]
        d.line(pp + [pp[0]], fill=(60, 12, 18), width=int(S(0.35)))
    return im


# --- face extras ----------------------------------------------------------------
def find_eyes(f: np.ndarray, g: Geometry):
    rgb = f[..., :3].astype(np.int32)
    a = alpha_mask(f)
    white = a & (rgb.min(-1) > 175) & (rgb.max(-1) - rgb.min(-1) < 50)
    zone = np.zeros_like(white)
    zone[g.top + 14:g.neck - 6] = True
    xs = np.arange(f.shape[1])
    zone &= np.abs(xs[None, :] - g.head_cx) <= g.head_hw
    out = []
    for c in components8(white & zone):
        if c.sum() >= 2:
            ys, xs_ = np.nonzero(c)
            out.append((xs_.mean() + 0.5, ys.mean() + 0.5, c.sum()))
    out.sort(key=lambda e: -e[2])
    return [(x, y) for x, y, _ in out[:2]]


EYE_R = 4.2
EYE_HW = 4.5     # lens half-width / height cover the whole eye
EYE_HH = 3.4


def lens(d, ex, ey, r, rx=None):
    """Round wire-rim lens: clear glass (the real eye shows through), thin
    dark rim and a faint glint."""
    rx = r if rx is None else rx
    d.ellipse([S(ex - rx), S(ey - r), S(ex + rx), S(ey + r)], outline=FRAME, width=max(1, int(round(S(0.55)))))
    d.arc([S(ex - rx + 0.9), S(ey - r + 0.9), S(ex + rx - 0.9), S(ey + r - 0.9)], 200, 250,
          fill=GLINT, width=max(1, int(round(S(0.45)))))


def face_layer(size, direction, eyes, g) -> Image.Image:
    h, w = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if not eyes:
        return im
    eyes = sorted(eyes)
    if direction in PROFILE:
        fc = PROFILE[direction]
        ex, ey = eyes[0] if fc < 0 else eyes[-1]
        r = EYE_R
        d.line([(S(ex - fc * r * 0.75), S(ey - 0.8)), (S(ex - fc * 7.5), S(ey - 0.4))], fill=FRAME, width=int(S(0.6)))
        lens(d, ex + fc * 0.3, ey, r, r * 0.72)
        bolt(d, ex - fc * 1.2, ey - 9.0)
        return im
    if len(eyes) == 1:
        x, y = eyes[0]
        span = 3.6
        other = (x + (span if x < g.head_cx else -span), y)
        eyes = sorted([eyes[0], other])
    (x0, y0), (x1, y1) = eyes
    yc = (y0 + y1) / 2
    gap = x1 - x0
    r = max(3.0, min(EYE_R, gap * 0.45))
    for ex in (x0, x1):
        lens(d, ex, yc, r)
    # bridge and temples
    d.arc([S(x0 + r - 0.3), S(yc - 1.6), S(x1 - r + 0.3), S(yc + 0.6)], 200, 340, fill=FRAME, width=int(S(0.55)))
    for ex, s_ in ((x0, -1), (x1, 1)):
        d.line([(S(ex + s_ * r), S(yc - 0.6)), (S(ex + s_ * (r + 1.3)), S(yc - 1.0))], fill=FRAME, width=int(S(0.55)))
    # scar: centred on the forehead, between the brows and the fringe
    bolt(d, (x0 + x1) / 2, yc - 9.4)
    return im


def bolt(d, x, y):
    """Red 'N' lightning bolt (like the reference photo), ~5px tall."""
    pts = [(x - 1.5, y + 2.4), (x - 0.3, y - 2.0), (x + 0.3, y + 1.0), (x + 1.6, y - 2.5)]
    d.line([(S(px), S(py)) for px, py in pts], fill=SCAR, width=int(round(S(0.9))), joint="curve")


# --- wand -------------------------------------------------------------------------
def wand_layer(size, hand, direc, spark: float) -> Image.Image:
    h, w = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hx, hy = hand
    dx, dy = direc
    p0 = (hx - dx * 2.0, hy - dy * 2.0)
    p1 = (hx + dx * 11.0, hy + dy * 11.0)
    nx, ny = -dy, dx

    def quad(a, b, ra, rb):
        return [(a[0] + nx * ra, a[1] + ny * ra), (b[0] + nx * rb, b[1] + ny * rb),
                (b[0] - nx * rb, b[1] - ny * rb), (a[0] - nx * ra, a[1] - ny * ra)]
    poly(d, quad(p0, p1, 0.95, 0.55), WAND, WAND_LINE, 0.4)
    tip0 = (p1[0] - dx * 1.6, p1[1] - dy * 1.6)
    poly(d, quad(tip0, p1, 0.6, 0.5), WAND_TIP)
    # carved bands near the grip
    for t in (2.6, 3.6):
        c = (hx + dx * t, hy + dy * t)
        d.line([(S(c[0] + nx * 0.9), S(c[1] + ny * 0.9)), (S(c[0] - nx * 0.9), S(c[1] - ny * 0.9))],
               fill=WAND_LINE, width=int(S(0.35)))
    if spark > 0:
        tx, ty = p1[0] + dx * 1.0, p1[1] + dy * 1.0
        star(d, tx, ty, 1.6 + 1.6 * spark, SPARK_HOT, SPARK)
        n = 6
        rad = 2.5 + 4.0 * spark
        for i in range(n):
            a = i * 2 * math.pi / n + spark * 1.3
            r = 0.7 + 0.9 * (1 - abs(spark - 0.5)) * (1.0 if i % 2 else 0.7)
            star(d, tx + math.cos(a) * rad, ty + math.sin(a) * rad, r, SPARK_HOT, SPARK)
    return im


def star(d, x, y, r, core, glow):
    pts = []
    for i in range(8):
        a = i * math.pi / 4
        rr = r if i % 2 == 0 else r * 0.38
        pts.append((S(x + math.cos(a) * rr), S(y + math.sin(a) * rr)))
    d.polygon(pts, fill=glow)
    q = r * 0.3
    d.ellipse([S(x - q), S(y - q), S(x + q), S(y + q)], fill=core)


def reach_tip(a, g, side, waist):
    """Fingertips of an arm stretched out past the head/body outline (the
    tag reach, which can be above the neck line)."""
    rows = np.arange(g.top + 18, waist)
    best = None
    for y in rows:
        xs = np.nonzero(a[y])[0]
        if not len(xs):
            continue
        x = xs.max() + 0.5 if side > 0 else xs.min() + 0.5
        if best is None or side * (x - best[0]) > 0:
            best = (x, y + 0.5)
    if best is None or side * (best[0] - g.head_cx) < g.head_hw + 6:
        return None
    return best[0] - side * 1.5, best[1]


def arm_tip(arms, g, side):
    best = None
    sx, sy = g.head_cx + side * 6.0, g.neck + 6.0
    for comp in components8(arms):
        if comp.sum() < 10:
            continue
        ys, xs = np.nonzero(comp)
        if side * (xs.mean() - g.hip_cx) < 2.0:
            continue
        dd = np.hypot(xs + 0.5 - sx, ys + 0.5 - sy)
        i = int(dd.argmax())
        if dd[i] > 9 and (best is None or dd[i] > best[0]):
            best = (dd[i], xs[i] + 0.5 - side * 1.0, ys[i] + 0.5)
    return None if best is None else best[1:]


# --- per frame ----------------------------------------------------------------------
def wizardify(frame, direction, anim, col, meta, memo, eye_memo):
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

    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & arms, 1)
    head = a & (yy <= g.neck + 1)
    # anything attached to the arm above the neck line (a raised tag arm)
    # stays an arm, not head
    head &= ~(arms & (yy > g.neck - 4))
    waist = g.hem - 9
    shoe_y = g.bottom - 4
    if direction in PROFILE:
        # the far arm (on the back side) is covered by the robe
        far = np.zeros_like(arms)
        for comp in components8(arms):
            ys, xs = np.nonzero(comp)
            if (xs.mean() + 0.5 - g.head_cx) * PROFILE[direction] < -1.0 and ys.min() > g.neck + 3:
                far |= comp
        arms &= ~far
        hands &= ~far
    body = a & ~head & ~arms
    upper = body & (yy <= waist)
    # only the opening of the robe shows the shirt; shoulders and the
    # t-shirt sleeves are robe
    if direction in FRONT:
        shirt = upper & (np.abs(xx + 0.5 - g.head_cx - FRONT[direction] * 2.0) < 5.0)
    elif direction in PROFILE:
        shirt = upper & ((xx + 0.5 - g.head_cx) * PROFILE[direction] > 1.5)
    else:
        shirt = upper & False
    robe_top = upper & ~shirt
    trousers = body & (yy > waist) & (yy < shoe_y)
    shoes = body & (yy >= shoe_y)
    body_im = class_layer([(robe_top, ROBE), (shirt, SHIRT), (trousers, TROUSERS), (shoes, SHOES)], BODY_LINE)
    sleeves = arms & ~hands
    cuffs = sleeves & grow(hands, arms, 2)
    arm_im = class_layer([(sleeves & ~cuffs, ROBE), (cuffs, CRIMSON)], ROBE_LINE, 0.6) if sleeves.any() else None

    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    n = rng["count"]
    if anim in ("walk", "run"):
        phase = math.sin(2 * math.pi * k / n)
    else:
        phase = 0.15 * math.sin(2 * math.pi * k / max(n, 1))
    sh_y = g.neck + 1.0
    hem_y = g.bottom - 6.0
    robe_im = robe_layer(direction, size, g.head_cx, g.hip_cx, sh_y, hem_y, phase, anim == "run")

    # wand
    side = TAG_SIDE[direction]
    pick = pick_hand(hands & (yy > g.neck + 1), g, side, a)
    key = (direction, anim)
    hidden = False
    tip = arm_tip(arms, g, side)
    ext = reach_tip(a, g, side, waist)
    if ext is not None and (tip is None or side * (ext[0] - tip[0]) > 4.0):
        tip = ext
    if pick is not None and tip is not None and side * (tip[0] - pick[0]) > 4.0:
        pick = None          # a stray skin blob, not the reaching hand
    if pick is not None:
        hx, hy, hand_comp = pick
    elif tip is not None:
        # no bare hand found: use the far end of the tag-side arm
        hx, hy = tip
        hand_comp = None
    elif key in memo:
        hx, hy = memo[key]
        hand_comp, hidden = None, True
    else:
        hx, hy = g.hip_cx + side * 9.0, waist + 2.0
        hand_comp, hidden = None, True
    memo[key] = (hx, hy)
    shx = g.head_cx + side * (3.0 if direction in PROFILE else 7.0)
    shy = g.neck + 6.0
    vx, vy = hx - shx, hy - shy
    vn = math.hypot(vx, vy) or 1.0
    reach = float(np.clip((abs(vx) / vn - 0.45) / 0.4, 0.0, 1.0))
    rest_a = math.radians(40)
    rest = (side * math.sin(rest_a), math.cos(rest_a))
    ang = math.atan2(vy, vx) - math.radians(15) * (1 if vx > 0 else -1)
    dx = rest[0] * (1 - reach) + math.cos(ang) * reach
    dy = rest[1] * (1 - reach) + math.sin(ang) * reach
    spark = 0.0
    if anim == "tag":
        p = k / max(n - 1, 1)
        base = math.atan2(dy, dx)
        sgn = 1 if dx >= 0 else -1
        base += sgn * math.radians(-55 + 85 * p)
        dx, dy = math.cos(base), math.sin(base)
        spark = float(np.clip((p - 0.3) / 0.7, 0, 1)) if p > 0.3 else 0.0
    dn = math.hypot(dx, dy) or 1.0
    wand_im = wand_layer(size, (hx, hy), (dx / dn, dy / dn), spark)

    # eyes: per-frame detection, fall back to the direction's last good fit
    eyes = []
    if direction in FACE_DIRS:
        eyes = find_eyes(f, g)
        need = 1 if direction in PROFILE else 2
        rel = [(x - g.head_cx, y - g.top) for x, y in eyes]
        if len(eyes) >= need:
            eye_memo[direction] = rel
        elif direction in eye_memo:
            eyes = [(x + g.head_cx, y + g.top) for x, y in eye_memo[direction]]
    face_im = face_layer(size, direction, eyes, g)

    behind = direction in BACK or hidden
    cv = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    if behind:
        cv.alpha_composite(wand_im)
    cv.alpha_composite(body_im)
    if direction in FRONT:
        cv.alpha_composite(tie_layer(size, g.head_cx, g.neck + 1.5, waist - 1.0, FRONT[direction]))
    cv.alpha_composite(robe_im)
    if arm_im is not None:
        cv.alpha_composite(arm_im)
    out = down(cv)
    out = over(out, premul(f, (head | hands).astype(np.float64)))
    out = over(out, down(face_im))
    if not behind:
        out = over(out, down(wand_im))
        if hand_comp is not None:
            out = over(out, premul(f, hand_comp.astype(np.float64)))
    res = to_u8(out)
    res[res[..., 3] < 8] = 0
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
    for r, direction in enumerate(dirs):
        memo: dict = {}
        eye_memo: dict = {}
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = wizardify(
                fr, direction, anim_of(meta, c), c, meta, memo, eye_memo)
    Image.fromarray(out).save(ASSETS / "kid_wizard.png", optimize=True)
    pm = dict(meta)
    pm["image"] = "kid_wizard.png"
    pm["frameWidth"], pm["frameHeight"] = ofw, ofh
    pm["baselineY"] = meta["baselineY"] + PAD_TOP
    pm["anchorX"] = ofw // 2
    (ASSETS / "kid_wizard.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_wizard.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")

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
