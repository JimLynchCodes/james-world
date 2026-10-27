#!/usr/bin/env python3
"""Build the "Centaur James" sprite sheet (public/assets/kid_centaur.png/json)
from the base kid sheet.

James from the waist up (his own head, hair, face and hands, untouched) on a
chestnut horse body:

  * the shirt above the waist becomes a bare, flat-shaded torso with light
    muscle lines (pecs/abs from the front, spine and shoulder blades from the
    back); arms keep their pose from the base frame, so tag still reaches with
    the real arm; in E/W only the near arm is kept;
  * the horse is a small pseudo-3D model (barrel of spheres, four jointed
    legs, a flowing tail) projected per facing direction - long in side
    views, foreshortened in N/S, angled in diagonals - drawn at 4x as flat
    colour layers with an outline and box-downscaled;
  * legs do a four-beat walk and a gallop on run, with body bob; the tail
    sways and streams out behind on run;
  * parts are painted back to front so the rump covers the lower back in
    back views and the far legs sit behind the barrel.

Frames are bigger than the base kid (152x144); the anchor is the centre of
the horse on the ground.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_centaur_skin.py [--preview /tmp/centaur_preview.png]
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
from make_pirate_skin import anim_of
from make_tuxedo_skin import close_streaks

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

OW, OH = 152, 150          # output frame
BASE_Y = 134               # ground line (baselineY)
ANCHOR_X = OW // 2
SS = 4
PROJ = 0.36                # ground depth -> screen y

FWD = {"E": (1, 0), "SE": (0.707, 0.707), "S": (0, 1), "SW": (-0.707, 0.707),
       "W": (-1, 0), "NW": (-0.707, -0.707), "N": (0, -1), "NE": (0.707, -0.707)}
FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}

COAT = (156, 86, 42)
COAT_LIGHT = (192, 120, 68)
COAT_DARK = (70, 38, 22)
COAT_SHADE = (126, 66, 32)
HOOF = (34, 26, 22)
TAIL = (48, 28, 18)
TAIL_HI = (86, 54, 34)
LINE = (40, 22, 12)
SKIN_LINE = (110, 56, 36)

BODY_L = 42.0              # chest to rump
BODY_R = 11.5
BODY_Z = 30.0
HIP_Z = 28.0
LEG_SIDE = 5.6
HIND_SIDE = 6.6
# the horse sits a little behind the anchor (and the rider a little in front)
# so turning round doesn't throw the rider a whole body length
CENTER_BACK = 7.0
HS = 1.3                  # the horse model is drawn this much bigger
LIFT = 6                  # rider's chest is this much taller than the kid's
LEAD_COLS = 16            # columns 0-15 in kid_centaur.png, 16-29 in kid_centaur_b.png
WAIST_Z = 37.0
WAIST_FWD = 18.0


def S(v):
    return v * SS


def up_mask(m):
    h, w = m.shape
    im = Image.fromarray((m * 255).astype(np.uint8)).resize((w * SS, h * SS), Image.BILINEAR)
    im = im.filter(ImageFilter.GaussianBlur(SS * 0.45))
    return np.asarray(im).astype(np.float64) / 255.0


def class_layer(classes, line, line_w=0.75):
    fields = [up_mask(m) for m, _ in classes]
    union = up_mask(np.any([m for m, _ in classes], axis=0)) >= 0.5
    lab = np.stack(fields).argmax(0)
    h, w = union.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for k, (_, col) in enumerate(classes):
        rgb[lab == k] = col
    sil = Image.fromarray((union * 255).astype(np.uint8))
    k = int(round(line_w * SS)) * 2 + 1
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(k))) > 127
    rgb[union & ~inner] = line
    return Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")


def down(im):
    arr = np.asarray(im).astype(np.float64) / 255.0
    pm = arr.copy()
    pm[..., :3] *= pm[..., 3:4]
    h, w = arr.shape[0] // SS, arr.shape[1] // SS
    return pm.reshape(h, SS, w, SS, 4).mean((1, 3))


def over(dst, src):
    return src + dst * (1.0 - src[..., 3:4])


def premul(f, mask=None):
    x = f.astype(np.float64) / 255.0
    x[..., :3] *= x[..., 3:4]
    if mask is not None:
        x *= mask[..., None]
    return x


def to_u8(pm):
    a = pm[..., 3:4]
    rgb = np.where(a > 1e-6, pm[..., :3] / np.maximum(a, 1e-6), 0)
    return np.clip(np.concatenate([rgb, a], -1) * 255 + 0.5, 0, 255).astype(np.uint8)


def layer():
    im = Image.new("RGBA", (OW * SS, OH * SS), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def bez(p0, p1, p2, n=10):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in np.linspace(0, 1, n)]


def shift(arr, dx, dy):
    """Place a source-frame array into an output-size canvas at (dx, dy)."""
    h, w = arr.shape[:2]
    out = np.zeros((OH, OW) + arr.shape[2:], dtype=arr.dtype)
    x0, y0 = max(0, dx), max(0, dy)
    x1, y1 = min(OW, dx + w), min(OH, dy + h)
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = arr[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


# --- horse model ----------------------------------------------------------------
class Horse:
    def __init__(self, direction, bob):
        self.f = FWD[direction]
        fx, fy = self.f
        n = math.hypot(fx, fy)
        self.f = (fx / n, fy / n)
        self.s = (-self.f[1], self.f[0])     # the horse's left side
        self.bob = bob

    def g(self, along, side=0.0):
        return (self.f[0] * along + self.s[0] * side, self.f[1] * along + self.s[1] * side)

    def scr(self, gx, gy, z):
        gx -= self.f[0] * CENTER_BACK
        gy -= self.f[1] * CENTER_BACK
        return ANCHOR_X + gx, BASE_Y + gy * PROJ - z

    def pt(self, along, side, z):
        along, side, z = along * HS, side * HS, z * HS
        gx, gy = self.g(along, side)
        return self.scr(gx, gy, z)

    def depth(self, along, side=0.0):
        return self.g(along, side)[1]



# --- drawing helpers ---------------------------------------------------------------
def hull(pts):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in pts))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def circle_pts(c, r, n=16):
    return [(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def capsule(p1, r1, p2, r2):
    return hull(circle_pts(p1, r1) + circle_pts(p2, r2))


def new_mask():
    return Image.new("L", (OW * SS, OH * SS), 0)


def poly_mask(polys, m=None):
    m = m or new_mask()
    d = ImageDraw.Draw(m)
    for p in polys:
        if len(p) >= 3:
            d.polygon([(S(x), S(y)) for x, y in p], fill=255)
    return m


def ell_mask(cx, cy, rx, ry, m=None):
    m = m or new_mask()
    ImageDraw.Draw(m).ellipse([S(cx - rx), S(cy - ry), S(cx + rx), S(cy + ry)], fill=255)
    return m


def B(m):
    return np.asarray(m) > 127


def nshift(a, dx, dy):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    ys, ye = max(0, dy), min(h, h + dy)
    xs, xe = max(0, dx), min(w, w + dx)
    out[ys:ye, xs:xe] = a[ys - dy:ye - dy, xs - dx:xe - dx]
    return out


def rim(mask, dx, dy):
    """the band of mask that faces (dx, dy) in SS pixels: flat form shadow"""
    return mask & ~nshift(mask, -dx, -dy)


def paint(regions, line, line_w=0.75, outline=True):
    """regions: [(bool mask, colour)], later wins. Outline the union."""
    union = np.zeros((OH * SS, OW * SS), bool)
    rgb = np.zeros((OH * SS, OW * SS, 3), np.uint8)
    for m, col in regions:
        union |= m
        rgb[m] = col
    if outline:
        k = int(round(line_w * SS)) * 2 + 1
        inner = B(Image.fromarray((union * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(k)))
        rgb[union & ~inner] = line
    return Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")


def strokes(im, lines, width=0.6):
    """draw detail lines, clipped to im's alpha"""
    tmp = im.copy()
    d = ImageDraw.Draw(tmp)
    for pts, col in lines:
        d.line([(S(x), S(y)) for x, y in pts], fill=col, width=max(1, int(S(width))), joint="curve")
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(tmp, (0, 0), im.getchannel("A"))
    return out


def catmull(rows, n):
    """resample a list of tuples (first item = along) smoothly to n rows"""
    rows = [rows[0]] + rows + [rows[-1]]
    out = []
    segs = len(rows) - 3
    for i in range(n):
        u = i / (n - 1) * segs
        j = min(int(u), segs - 1)
        t = u - j
        p0, p1, p2, p3 = rows[j], rows[j + 1], rows[j + 2], rows[j + 3]
        out.append(tuple(0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                               + (-a + 3 * b - 3 * c + d) * t ** 3) for a, b, c, d in zip(p0, p1, p2, p3)))
    return out


# --- horse body ---------------------------------------------------------------------
# (along, top z, bottom z, half width). Arched chest in front, withers under
# the rider, a gently sloping back, a high round croup and buttocks, and a
# belly that tucks up towards the flank.
SECTIONS = [
    (25.0, 30.5, 24.5, 3.0),
    (23.6, 34.6, 20.8, 7.0),
    (21.0, 37.0, 17.6, 9.6),
    (16.0, 38.0, 15.6, 11.0),
    (9.0, 36.6, 15.2, 11.4),
    (1.0, 35.4, 16.4, 11.0),
    (-7.0, 35.4, 19.0, 10.6),
    (-14.0, 37.0, 20.0, 11.4),
    (-19.5, 37.4, 20.4, 11.6),
    (-23.4, 35.4, 21.6, 9.6),
    (-25.8, 31.6, 24.4, 5.0),
    (-26.6, 28.6, 26.0, 1.6),
]
TAIL_ROOT = (-24.6, 0.0, 35.6)
FRONT_LEG = 16.0
HIND_LEG = -18.0


def body_rings(h):
    secs = catmull(SECTIONS, 34)
    rings = []
    for al, top, bot, w in secs:
        zc, hz = (top + bot) / 2 + h.bob, (top - bot) / 2
        rings.append((al, [(th, h.pt(al, w * math.cos(th), zc + hz * math.sin(th)))
                           for th in np.linspace(0, 2 * math.pi, 28, endpoint=False)]))
    return secs, rings


def body_masks(h, rings, keep=lambda al: True, smin=-1.1, smax=1.1):
    polys = []
    for (a1, r1), (a2, r2) in zip(rings, rings[1:]):
        if not (keep(a1) or keep(a2)):
            continue
        pts = [p for th, p in r1 + r2 if smin <= math.sin(th) <= smax]
        polys.append(hull(pts))
    return B(poly_mask(polys))


def near_side(h):
    d = h.depth(0, 1) - h.depth(0, -1)
    return 0 if abs(d) < 0.3 else (1 if d > 0 else -1)


def surf(h, secs, al, z, ns):
    """a point on the near flank of the body at (along, z)"""
    al_list = [s[0] for s in secs][::-1]
    top = np.interp(al, al_list, [s[1] for s in secs][::-1])
    bot = np.interp(al, al_list, [s[2] for s in secs][::-1])
    w = np.interp(al, al_list, [s[3] for s in secs][::-1])
    zc, hz = (top + bot) / 2, (top - bot) / 2
    q = max(-0.98, min(0.98, (z - zc) / hz))
    return h.pt(al, ns * w * math.sqrt(1 - q * q), z + h.bob)


def body_layer(h, split_depth):
    secs, rings = body_rings(h)
    full = body_masks(h, rings)
    upper = body_masks(h, rings, smin=-0.3)
    band = body_masks(h, rings, keep=lambda al: -25 < al < 14, smin=0.68)
    regions = [(full, COAT_SHADE), (upper, COAT), (band & full, COAT_LIGHT)]
    im = paint(regions, LINE)
    ns = near_side(h)
    lines = []
    if ns:
        # shoulder blade, elbow, stifle and the hamstring groove
        lines.append(([surf(h, secs, a, z, ns) for a, z in bez((12.5, 35.5), (12.0, 26.0), (17.0, 19.5), 9)], COAT_SHADE))
        lines.append(([surf(h, secs, a, z, ns) for a, z in bez((-10.0, 33.5), (-12.5, 25.0), (-9.5, 21.5), 9)], COAT_SHADE))
        lines.append(([surf(h, secs, a, z, ns) for a, z in bez((-20.0, 34.0), (-24.0, 28.0), (-22.0, 22.5), 9)], COAT_SHADE))
        lines.append(([surf(h, secs, a, z, ns) for a, z in bez((-4.0, 21.0), (2.0, 19.0), (9.0, 19.0), 7)], COAT_SHADE))
    elif h.f[1] > 0:
        # facing us: the cleft between the two halves of the chest
        lines.append(([h.pt(a, 0, z + h.bob) for a, z in bez((24.4, 33.5), (25.4, 27.0), (23.8, 21.5), 7)], COAT_SHADE))
    else:
        # from behind: the cleft between the buttocks
        lines.append(([h.pt(a, 0, z + h.bob) for a, z in bez((-25.6, 33.0), (-26.6, 27.0), (-24.4, 21.5), 7)], COAT_SHADE))
    if lines:
        im = Image.alpha_composite(im, strokes(im, lines, 0.65))
    # the part of the body in front of the rider (covers his waist)
    fm = body_masks(h, rings, keep=lambda al: h.depth(al) >= split_depth + 3.0)
    k = int(round(1.2 * SS)) * 2 + 1
    fm = B(Image.fromarray((fm * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k)))
    front = Image.new("RGBA", im.size, (0, 0, 0, 0))
    front.paste(im, (0, 0), Image.fromarray((fm * 255).astype(np.uint8)))
    return im, front


def leg_layer(h: Horse, along, side, swing, lift, hind, run, far):
    """A slender leg: forearm/gaskin in coat, knee or hock, dark cannon,
    fetlock, pastern and a hoof."""
    P = lambda a, z: h.pt(a, side, z)
    fwd = -1 if hind else 1
    foot_a, foot_z = along + swing, lift
    if hind:
        top = P(along + 1.0, 30 + h.bob)
        stifle = P(along + 3.0, 21 + h.bob)
        hock = P(along - 3.2 + swing * 0.45 - lift * 0.35, 13.5 + lift * 0.55)
        fet = P(foot_a - 0.6 - lift * 0.45, 4.6 + lift)
        pieces = [(top, 7.0, stifle, 5.8), (stifle, 5.4, hock, 2.4)]
        joint = hock
    else:
        top = P(along, 26 + h.bob)
        elbow = P(along - 1.0, 19 + h.bob)
        knee = P(along + swing * 0.5 + lift * 0.55, 11.5 + lift * 0.5)
        fet = P(foot_a - lift * 0.6, 4.4 + lift)
        pieces = [(top, 5.8, elbow, 5.0), (elbow, 4.4, knee, 2.6)]
        joint = knee
    hoof_c = P(foot_a + 0.25 * fwd * 0 + 0.2, foot_z + 1.3)
    coat = [capsule(a, r1, b, r2) for a, r1, b, r2 in pieces]
    dark = [capsule(joint, 2.3, fet, 1.75), circle_pts(fet, 2.25)]
    pastern = [capsule(fet, 1.9, (hoof_c[0], hoof_c[1] - 0.8), 1.8)]
    tx = 0.0
    hx, hy = hoof_c
    toe = 0.8 * (h.f[0] if not hind else h.f[0])
    hoof = [[(hx - 2.0, hy - 1.5), (hx + 2.0, hy - 1.5), (hx + 2.5 + toe, hy + 1.5), (hx - 2.5 + min(0, toe), hy + 1.5)]]
    cm = B(poly_mask(coat))
    dm = B(poly_mask(dark + pastern))
    hm = B(poly_mask(hoof))
    c1 = COAT_SHADE if far else COAT
    regions = [(cm, c1), (dm, COAT_DARK), (hm, HOOF)]
    regions.append((rim(cm, int(S(1.2)), 0) & cm & ~dm, COAT_SHADE if not far else COAT_DARK))
    im = paint(regions, LINE)
    return im


def tail_layer(h: Horse, sway, run, k_phase):
    im, d = layer()
    root = (TAIL_ROOT[0], 0.0, TAIL_ROOT[2] + h.bob)
    if run:
        mid = (root[0] - 9, sway * 2.0, root[2] + 2.0)
        tip = (root[0] - 17, sway * 3.5, root[2] - 8 + 2 * math.sin(k_phase))
    else:
        mid = (root[0] - 6.5, sway * 1.5, root[2] - 4.0)
        tip = (root[0] - 6.0, sway * 3.0, 8.5)
    P = lambda p: h.pt(*p)
    c = bez(P(root), P(mid), P(tip), 16)
    left, right = [], []
    for i, (x, y) in enumerate(c):
        t = i / (len(c) - 1)
        wdt = 1.4 + 3.0 * math.sin(math.pi * min(1.0, t * 1.1)) + 0.5 * t
        x2, y2 = c[min(i + 1, len(c) - 1)]
        x1, y1 = c[max(i - 1, 0)]
        tx, ty = x2 - x1, y2 - y1
        tn = math.hypot(tx, ty) or 1
        nx, ny = -ty / tn, tx / tn
        left.append((x + nx * wdt, y + ny * wdt))
        right.append((x - nx * wdt, y - ny * wdt))
    end = (c[-1][0] + (c[-1][0] - c[-2][0]) * 2.5, c[-1][1] + (c[-1][1] - c[-2][1]) * 2.5)
    shape = left + bez(left[-1], end, right[-1], 6)[1:-1] + right[::-1]
    pts = [(S(x), S(y)) for x, y in shape]
    d.polygon(pts, fill=TAIL)
    d.line(pts + [pts[0]], fill=LINE, width=int(S(0.75)), joint="curve")
    for off in (-0.4, 0.05, 0.45):
        strand = [(x + (l[0] - x) * off * 1.5, y + (l[1] - y) * off * 1.5)
                  for (x, y), l in zip(c[2:-1], left[2:-1])]
        d.line([(S(x), S(y)) for x, y in strand], fill=TAIL_HI, width=int(S(0.5)), joint="curve")
    return im


# --- rider ---------------------------------------------------------------------------
def tone(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def torso_shape(direction, c, y0, y1):
    """outline of neck + torso, shoulder points, torso half width"""
    th = max(8.0, y1 - y0)
    yb = y1 + 4.0
    if direction in PROFILE:
        fc = PROFILE[direction]
        back = [(c - fc * 1.6, y0 - 7.0)]
        back += bez((c - fc * 1.8, y0 - 3.0), (c - fc * 3.6, y0 + 0.2), (c - fc * 7.2, y0 + 3.0), 7)
        back += bez((c - fc * 7.2, y0 + 3.0), (c - fc * 7.4, y0 + th * 0.5), (c - fc * 5.2, yb), 7)[1:]
        front = bez((c + fc * 5.0, yb), (c + fc * 4.8, y0 + th * 0.62), (c + fc * 6.6, y0 + th * 0.42), 6)
        front += bez((c + fc * 6.6, y0 + th * 0.42), (c + fc * 8.4, y0 + 2.6), (c + fc * 2.8, y0 - 0.6), 7)[1:]
        front += [(c + fc * 2.6, y0 - 7.0)]
        return back + front, [(c - fc * 0.8, y0 + 3.2)], 5.5
    lean = FRONT.get(direction, BACK.get(direction, 0))
    W = 12.0 if lean == 0 else 10.6
    c += lean * 0.8
    wl, wr = (W * (0.9 if lean > 0 else 1.0), W * (0.9 if lean < 0 else 1.0))
    def side(sg, ww):
        pts = [(c + sg * 3.3, y0 - 7.0), (c + sg * 3.4, y0 - 3.0)]
        pts += bez((c + sg * 3.4, y0 - 3.0), (c + sg * 4.6, y0 + 0.4), (c + sg * (ww - 2.8), y0 + 1.3), 7)[1:]
        pts += bez((c + sg * (ww - 2.8), y0 + 1.3), (c + sg * (ww + 0.8), y0 + 1.8), (c + sg * (ww - 0.2), y0 + 6.0), 6)[1:]
        pts += bez((c + sg * (ww - 0.2), y0 + 6.0), (c + sg * (ww - 1.0), y0 + th * 0.66), (c + sg * 5.8, yb), 7)[1:]
        return pts
    R, L = side(1, wr), side(-1, wl)
    return R + L[::-1], [(c + wr - 2.4, y0 + 3.2), (c - wl + 2.4, y0 + 3.2)], W


def torso_layer(direction, c, y0, y1, skin):
    shade, dark, light = tone(skin, 0.84), tone(skin, 0.68), tone(skin, 1.07)
    outline, shoulders, W = torso_shape(direction, c, y0, y1)
    th = max(8.0, y1 - y0)
    py = y0 + th * 0.40
    yb = y1 + 4.0
    m = B(poly_mask([outline]))
    regions = [(m, skin)]
    lines = []
    if direction in PROFILE:
        fc = PROFILE[direction]
        regions.append((m & B(poly_mask([[(c - fc * 9, y0 - 8), (c - fc * 2.4, y0 - 8), (c - fc * 1.8, yb), (c - fc * 9, yb)]])), shade))
        pec = bez((c + fc * 0.8, y0 + 2.4), (c + fc * 2.2, py + 2.2), (c + fc * 5.8, py + 0.6), 8)
        regions.append((m & B(poly_mask([pec + [(c + fc * 5.2, py + 2.6), (c + fc * 2.0, py + 3.0)]])), shade))
        lines += [(pec, dark), ([(c + fc * 1.6, y0 - 0.5), (c + fc * 4.2, y0 + 0.6)], shade)]
        for q in (0.3, 0.55, 0.8):
            yq = py + (yb - 3 - py) * q
            lines.append(([(c + fc * 2.8, yq), (c + fc * 4.6, yq + 0.2)], dark))
        lines.append((bez((c - fc * 1.8, y0 - 6.5), (c - fc * 1.6, y0 - 2.0), (c - fc * 3.0, y0 + 0.4), 5), shade))
    else:
        lean = FRONT.get(direction, BACK.get(direction, 0))
        cc = c + lean * 1.4
        # light from the upper left: right flank and right half of the neck in shade
        regions.append((m & B(poly_mask([[(cc + W * 0.6, y0 + 4), (cc + W + 3, y0 + 4), (cc + W + 3, yb + 1), (cc + 4.4, yb + 1), (cc + W * 0.5, py + 2.5)]])), shade))
        regions.append((m & B(poly_mask([[(cc + 1.2, y0 - 8), (cc + 4.5, y0 - 8), (cc + 4.5, y0 + 0.2), (cc + 1.4, y0 - 0.4)]])), shade))
        if direction in FRONT:
            for sg in (-1, 1):
                pec = bez((cc + sg * (W - 2.0), py - 3.2), (cc + sg * 4.4, py + 2.0), (cc + sg * 0.6, py - 0.2), 9)
                regions.append((m & B(poly_mask([pec + [(cc + sg * 0.6, py + 1.3), (cc + sg * 4.4, py + 3.0), (cc + sg * (W - 2.4), py - 1.2)]])), shade))
                lines.append((pec, dark))
                lines.append((bez((cc + sg * 0.8, y0 + 0.4), (cc + sg * 3.4, y0 + 0.2), (cc + sg * 6.4, y0 - 0.6), 6), shade))   # collarbone
                lines.append((bez((cc + sg * 2.0, y0 + 2.6), (cc + sg * 4.5, y0 + 1.8), (cc + sg * 7.0, y0 + 3.0), 6), light))     # top of pec
                lines.append((bez((cc + sg * (W - 2.2), py + 1.4), (cc + sg * 5.0, py + 5.0), (cc + sg * 4.6, yb - 0.8), 7), shade))  # obliques
                nx, ny = cc + sg * 4.6, py - 1.4
                lines.append(([(nx - 0.25, ny), (nx + 0.25, ny)], dark))                                                         # nipple
            lines.append(([(cc, y0 + 1.2), (cc, py + 0.4)], shade))                                                            # sternum
            lines.append(([(cc, py + 0.6), (cc, yb - 2.6)], dark))                                                              # linea alba
            for q in (0.0, 0.33, 0.66):
                yq = py + 1.4 + (yb - 4.0 - py) * q
                for sg in (-1, 1):
                    lines.append(([(cc + sg * 0.5, yq + 0.4), (cc + sg * 3.2, yq - 0.1)], dark))
        else:
            lines.append(([(cc, y0 + 0.4), (cc, yb - 2.0)], dark))                                                               # spine
            for sg in (-1, 1):
                lines.append((bez((cc + sg * 3.4, y0 - 4.0), (cc + sg * 4.0, y0 + 0.8), (cc + sg * (W - 2.6), y0 + 2.0), 6), shade))  # trapezius
                lines.append((bez((cc + sg * 1.6, y0 + 2.0), (cc + sg * 2.2, py + 2.6), (cc + sg * 6.6, py + 1.0), 8), dark))   # shoulder blade
                lines.append((bez((cc + sg * 6.8, y0 + 4.2), (cc + sg * 5.0, py - 1.0), (cc + sg * 3.0, py + 0.4), 6), shade))
                lines.append((bez((cc + sg * 6.8, py + 3.0), (cc + sg * 4.6, py + 5.5), (cc + sg * 3.4, yb - 1.5), 6), shade))  # lats
    im = paint(regions, SKIN_LINE)
    return Image.alpha_composite(im, strokes(im, lines, 0.55)), shoulders, W


def ik_elbow(sh, hand, L1, L2, bend):
    dx, dy = hand[0] - sh[0], hand[1] - sh[1]
    d = math.hypot(dx, dy) or 1e-3
    if d > L1 + L2 - 0.3:
        k = (L1 + L2 - 0.3) / d
        hand = (sh[0] + dx * k, sh[1] + dy * k)
        dx, dy, d = dx * k, dy * k, L1 + L2 - 0.3
    a = (L1 * L1 - L2 * L2 + d * d) / (2 * d)
    hgt = math.sqrt(max(0.0, L1 * L1 - a * a))
    ux, uy = dx / d, dy / d
    px, py = -uy, ux
    if px * bend[0] + py * bend[1] < 0:
        px, py = -px, -py
    return (sh[0] + ux * a + px * hgt, sh[1] + uy * a + py * hgt), hand


def arm_layers(sh, elbow, wrist, out_dir, skin):
    """a muscular arm and the deltoid cap that joins it to the torso"""
    shade = tone(skin, 0.84)
    ux, uy = elbow[0] - sh[0], elbow[1] - sh[1]
    n = math.hypot(ux, uy) or 1
    ux, uy = ux / n, uy / n
    bic = (sh[0] + ux * n * 0.45, sh[1] + uy * n * 0.45)
    fx, fy = wrist[0] - elbow[0], wrist[1] - elbow[1]
    fn = math.hypot(fx, fy) or 1
    fore = (elbow[0] + fx * 0.28, elbow[1] + fy * 0.28)
    polys = [capsule(sh, 3.9, elbow, 2.8), circle_pts(bic, 3.9), capsule(elbow, 2.8, wrist, 2.0),
             circle_pts(fore, 3.2)]
    m = B(poly_mask(polys))
    sdx, sdy = int(S(1.1)) * (1 if out_dir >= 0 else -1), int(S(0.9))
    arm = paint([(m, skin), (rim(m, sdx, sdy) & m, shade)], SKIN_LINE, 0.7)
    # deltoid: rounds over the top of the shoulder and flows into the arm
    dc = (sh[0] + ux * 1.6 + out_dir * 0.3, sh[1] + uy * 1.6)
    dm = B(poly_mask([capsule((sh[0], sh[1] - 1.0), 4.3, dc, 3.9)]))
    delt = paint([(dm, skin), (rim(dm, sdx, sdy) & dm, shade)], SKIN_LINE, 0.7)
    # no line where the deltoid runs into the arm: the cap's lower end is open
    cut = B(poly_mask([capsule(dc, 3.2, (dc[0] + ux * 5, dc[1] + uy * 5), 3.0)]))
    da = np.asarray(delt).copy()
    lo = cut & (np.asarray(arm)[..., 3] > 0)
    da[lo, :3] = np.asarray(arm)[lo, :3]
    da[lo, 3] = 255
    return arm, Image.fromarray(da, "RGBA")


def gait(anim, k, n):
    """(phase offsets per leg LF, RF, LH, RH, swing amp, lift amp, bob)."""
    if anim == "walk":
        t = k / n
        offs = {"LH": 0.0, "LF": 0.25, "RH": 0.5, "RF": 0.75}
        return t, offs, 5.5, 3.2, 0.7 * abs(math.sin(4 * math.pi * t))
    if anim == "run":
        t = k / n
        offs = {"LH": 0.0, "RH": 0.1, "LF": 0.5, "RF": 0.6}
        return t, offs, 9.0, 6.5, 2.6 * (0.5 + 0.5 * math.cos(2 * math.pi * (t - 0.3)))
    return None, None, 0, 0, (0.4 * math.sin(2 * math.pi * k / max(n, 1)) if anim == "breathe" else 0.0)


# --- per frame ----------------------------------------------------------------------
def centaurify(frame, direction, anim, col, meta):
    a0 = alpha_mask(frame)
    if not a0.any():
        return np.zeros((OH, OW, 4), np.uint8)
    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k, n = col - rng["start"], rng["count"]
    t, offs, amp, lift_amp, bob = gait(anim, k, n)
    run = anim == "run"
    h = Horse(direction, bob)

    g = Geometry(frame)
    f = close_streaks(frame, g.neck + 2)
    waist = g.hem - 9
    tx, ty = h.pt(WAIST_FWD, 0, WAIST_Z + bob)
    dx, dy = int(round(tx - g.hip_cx)), int(round(ty - waist))

    a = alpha_mask(f)
    fh, fw = a.shape
    yy, xx = np.mgrid[0:fh, 0:fw]
    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & arms, 1)
    head = a & (yy <= g.neck + 1)
    head &= ~(arms & (yy > g.neck - 4))
    r_, g_, b_ = (f[..., i].astype(np.int32) for i in range(3))
    head &= ~((yy > g.neck - 5) & ~loose_skin(f) & (np.abs(r_ - b_) < 30))
    if direction in FRONT:
        head &= ~((yy > g.neck - 3) & ~loose_skin(f))
    if direction in PROFILE:
        head &= ~((yy > g.neck - 3) & ~loose_skin(f) & ((xx + 0.5 - g.head_cx) * PROFILE[direction] > -2))
    # any orange t-shirt collar left at the nape
    head &= ~((yy > g.neck - 4) & ~loose_skin(f) & (r_ - b_ > 70) & (r_ > 150))
    comps = [c for c in components8(arms) if c.sum() >= 6]
    if direction in PROFILE and len(comps) > 1:
        biggest = max(comps, key=lambda c: c.sum())
        keep = [biggest]
        for comp in comps:
            if comp is biggest:
                continue
            ys, xs = np.nonzero(comp)
            if not ((xs.mean() + 0.5 - g.head_cx) * PROFILE[direction] < -1.0 and ys.min() > g.neck + 3):
                keep.append(comp)
        comps = [biggest]
    skin_px = f[face][:, :3]
    skin = tuple(int(v) for v in np.median(skin_px, 0)) if len(skin_px) else (236, 182, 140)
    tc = (g.head_cx + g.hip_cx) / 2

    # torso, then a drawn arm per base arm, from the torso's shoulder to
    # where the kid's hand is (scaled for the longer arms)
    y0 = g.neck + 1 + dy - LIFT
    y1 = waist + dy
    torso_im, shoulders, W = torso_layer(direction, tc + dx, y0, y1, skin)
    arm_ims = []
    hand_px = np.zeros((OH, OW, 4), np.uint8)
    hand_m = np.zeros((OH, OW), bool)
    for comp in comps[:2]:
        ys, xs = np.nonzero(comp)
        hm = hands & comp
        if hm.sum() >= 2:
            hy_, hx_ = np.nonzero(hm)
        else:
            sel = ys >= ys.max() - 2
            hy_, hx_ = ys[sel], xs[sel]
        hb = (hx_.mean() + 0.5, hy_.mean() + 0.5)
        side = 1 if xs.mean() + 0.5 > tc else -1
        if direction in PROFILE:
            sh = shoulders[0]
            sb = (tc, g.neck + 3.0)
            bend = (-PROFILE[direction], 0.3)
        else:
            sh = shoulders[0] if side > 0 or len(shoulders) == 1 else shoulders[1]
            if side < 0:
                sh = shoulders[1]
            sb = (tc + side * 6.0, g.neck + 3.0)
            bend = (side, 0.2) if direction not in BACK else (side, 0.2)
        hand = (sh[0] + 1.25 * (hb[0] - sb[0]), sh[1] + 1.3 * (hb[1] - sb[1]))
        # hands never rest on the horse: at most down at the hip
        hand = (hand[0], min(hand[1], y1 + 1.0))
        if direction not in PROFILE and abs(hand[0] - (tc + dx)) < W + 1.5 and hand[1] > y0 + 8:
            hand = ((tc + dx) + side * (W + 1.5), hand[1])
        elbow, hand = ik_elbow(sh, hand, 9.5, 9.0, bend)
        wx_, wy_ = hand[0] + (elbow[0] - hand[0]) * 0.16, hand[1] + (elbow[1] - hand[1]) * 0.16
        arm, delt = arm_layers(sh, elbow, (wx_, wy_), side if direction not in PROFILE else -PROFILE[direction], skin)
        arm_ims.append((arm, delt))
        # base hand pixels moved onto the new wrist
        if hm.sum() >= 2:
            mdx = int(round(hand[0] - hb[0]))
            mdy = int(round(hand[1] - hb[1]))
            moved = shift(hm, mdx, mdy)
            px = shift(f, mdx, mdy)
            hand_px[moved] = px[moved]
            hand_m |= moved

    head_o = shift(head, dx, dy - LIFT)
    Fhead = shift(f, dx, dy - LIFT)

    # legs
    ns = near_side(h)
    legs = []
    for name, al, sd in (("LF", FRONT_LEG, LEG_SIDE), ("RF", FRONT_LEG, -LEG_SIDE),
                         ("LH", HIND_LEG, HIND_SIDE), ("RH", HIND_LEG, -HIND_SIDE)):
        hind = name[1] == "H"
        if t is None:
            swing, lift = 0.0, 0.0
            if anim == "tag":
                p = k / max(n - 1, 1)
                swing = (2.0 if not hind else -1.0) * math.sin(math.pi * p) * (1 if name[0] == "L" else 0.6)
        else:
            ph = 2 * math.pi * (t + offs[name])
            swing = amp * math.sin(ph)
            lift = lift_amp * max(0.0, math.cos(ph))
            if run and hind:
                swing *= 0.85
        far = ns != 0 and sd * ns < 0
        legs.append((h.depth(al + swing * 0.5, sd), leg_layer(h, al, sd, swing, lift, hind, run, far)))
    sway = math.sin(2 * math.pi * (k / max(n, 1))) * (1.0 if t is not None else 0.4)
    tail = tail_layer(h, sway, run, 2 * math.pi * k / max(n, 1))
    body, body_front = body_layer(h, h.depth(WAIST_FWD))

    # coat fringe where the rider's waist goes into the horse
    wx, wy = h.pt(WAIST_FWD, 0, WAIST_Z + bob)
    fw_ = 5.4 if direction in PROFILE else 6.8
    top = []
    xs_ = np.linspace(wx - fw_, wx + fw_, 11)
    for i, x in enumerate(xs_):
        top.append((x, y1 + (1.2 if i % 2 else 3.0) - (0.8 if 2 < i < 8 else 0)))
    fringe_poly = top + [(wx + fw_ + 0.6, y1 + 7.5), (wx - fw_ - 0.6, y1 + 7.5)]
    fr = B(poly_mask([fringe_poly])) & B(poly_mask([[(wx - 30, y1 - 2), (wx + 30, y1 - 2), (wx + 30, OH), (wx - 30, OH)]]))
    fringe = paint([(fr, COAT)], LINE, 0.6)
    # keep only the top (zigzag) line of the fringe: below the horse's top it melts into the coat
    bm = np.asarray(body)[..., 3] > 0
    fa = np.asarray(fringe).copy()
    inner = bm & B(poly_mask([[(x, y + 1.6) for x, y in top] + [(wx + fw_ + 4, y1 + 9), (wx - fw_ - 4, y1 + 9)]]))
    fa[inner & (fa[..., 3] > 0), :3] = COAT
    fringe = Image.fromarray(fa, "RGBA")

    cv = Image.new("RGBA", (OW * SS, OH * SS), (0, 0, 0, 0))
    behind_tail = h.f[1] >= -0.01
    if behind_tail:
        cv.alpha_composite(tail)
    for dep, im in sorted(legs, key=lambda x: x[0]):
        cv.alpha_composite(im)
    cv.alpha_composite(body)
    if direction in BACK:
        for arm, delt in arm_ims:
            cv.alpha_composite(arm)
    cv.alpha_composite(torso_im)
    cv.alpha_composite(fringe)
    if direction in BACK:
        for arm, delt in arm_ims:
            cv.alpha_composite(delt)
    out = down(cv)
    out = over(out, premul(Fhead, head_o.astype(np.float64)))
    if direction in BACK:
        out = over(out, premul(hand_px, hand_m.astype(np.float64)))
    top_l, _ = layer()
    top_l.alpha_composite(body_front)
    if not behind_tail:
        top_l.alpha_composite(tail)
    out = over(out, down(top_l))
    if direction not in BACK:
        al, _ = layer()
        for arm, delt in arm_ims:
            al.alpha_composite(arm)
            al.alpha_composite(delt)
        out = over(out, down(al))
        out = over(out, premul(hand_px, hand_m.astype(np.float64)))
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
    out = np.zeros((len(dirs) * OH, cols * OW, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * OH:(r + 1) * OH, c * OW:(c + 1) * OW] = centaurify(
                fr, direction, anim_of(meta, c), c, meta)
    # two textures so neither side passes 4096px (mobile WebGL)
    split = LEAD_COLS * OW
    for name, part in (("kid_centaur.png", out[:, :split]), ("kid_centaur_b.png", out[:, split:])):
        assert max(part.shape[:2]) <= 4096, part.shape
        Image.fromarray(np.ascontiguousarray(part)).save(ASSETS / name, optimize=True)
        print(f"wrote {ASSETS / name} ({part.shape[1]}x{part.shape[0]})")
    pm = dict(meta)
    pm["image"] = "kid_centaur.png"
    pm["frameWidth"], pm["frameHeight"] = OW, OH
    pm["baselineY"] = BASE_Y
    pm["anchorX"] = ANCHOR_X
    pm["columns"] = LEAD_COLS
    pm["logicalColumns"] = cols
    pm["extraImage"] = "kid_centaur_b.png"
    pm["extraColumns"] = cols - LEAD_COLS
    (ASSETS / "kid_centaur.json").write_text(json.dumps(pm, indent=2) + "\n")

    if args.preview:
        img = Image.fromarray(out)
        scale, pad = args.scale, 40
        picks = [0, 6, 9, 13, 16, 18, 19, 21, 24, 27]
        pv = Image.new("RGBA", (pad + len(picks) * OW * scale, pad + len(dirs) * OH * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (OW, OH), (120, 170, 120, 255) if (r + i) % 2 else (100, 150, 100, 255))
                cell.alpha_composite(img.crop((c * OW, r * OH, (c + 1) * OW, (r + 1) * OH)))
                pv.paste(cell.resize((OW * scale, OH * scale), Image.NEAREST),
                         (pad + i * OW * scale, pad + r * OH * scale))
            d.text((4, pad + r * OH * scale + 10), dirs[r], fill="white")
        for i, c in enumerate(picks):
            d.text((pad + i * OW * scale + 4, 12), f"{anim_of(meta, c)} {c}", fill="white")
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")
        np.save("/tmp/centaur_full.npy", out)


if __name__ == "__main__":
    main()
