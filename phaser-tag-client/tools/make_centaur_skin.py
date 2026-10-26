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

OW, OH = 152, 144          # output frame
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
COAT_LIGHT = (178, 106, 58)
COAT_DARK = (70, 38, 22)
COAT_SHADE = (126, 66, 32)
HOOF = (34, 26, 22)
TAIL = (48, 28, 18)
TAIL_HI = (86, 54, 34)
LINE = (40, 22, 12)
SKIN_LINE = (120, 62, 40)

BODY_L = 44.0              # chest to rump
BODY_R = 11.5
BODY_Z = 30.0
HIP_Z = 28.0
LEG_SIDE = 5.0
WAIST_Z = 37.0
WAIST_FWD = 16.0


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
        return ANCHOR_X + gx, BASE_Y + gy * PROJ - z

    def pt(self, along, side, z):
        gx, gy = self.g(along, side)
        return self.scr(gx, gy, z)

    def depth(self, along, side=0.0):
        return self.g(along, side)[1]


def barrel_layer(h: Horse, split_depth=None):
    """The barrel, and (if split_depth is given) the part of it in front of
    that depth - the full silhouette cut by a mask so there are no inner
    outlines."""
    im, d = layer()
    spheres = []
    n = 16
    for i in range(n + 1):
        t = i / n
        along = BODY_L / 2 - t * BODY_L
        # chest and hindquarters a little fuller, belly slimmer
        r = BODY_R + 1.2 * math.exp(-((t - 0.12) / 0.14) ** 2) + 1.6 * math.exp(-((t - 0.86) / 0.14) ** 2) - 0.4
        z = BODY_Z + h.bob + 0.8 * math.exp(-((t - 0.1) / 0.15) ** 2) + 1.4 * math.exp(-((t - 0.85) / 0.15) ** 2)
        spheres.append((along, z, r))
    for col, extra, lift in ((LINE, 0.75, 0.0), (COAT_SHADE, 0.0, 0.0), (COAT, -1.6, 1.6)):
        for along, z, r in spheres:
            x, y = h.pt(along, 0, z)
            y -= lift
            rr = r + extra
            d.ellipse([S(x - rr), S(y - rr), S(x + rr), S(y + rr)], fill=col)
    if split_depth is None:
        return im, None
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)
    for along, z, r in spheres:
        if h.depth(along) >= split_depth - 0.5:
            x, y = h.pt(along, 0, z)
            rr = r + 0.8
            md.ellipse([S(x - rr), S(y - rr), S(x + rr), S(y + rr)], fill=255)
    front = Image.new("RGBA", im.size, (0, 0, 0, 0))
    front.paste(im, (0, 0), m)
    return im, front


def leg_layer(h: Horse, along, side, swing, lift, hind, run):
    im, d = layer()
    fwd = 1 if not hind else -1
    hip = (along, side, HIP_Z + h.bob)
    foot = (along + swing, side, lift)
    knee_z = 13.5 + lift * 0.4
    k_al = (hip[0] + foot[0]) / 2 + (1.2 if not hind else -1.8) + fwd * lift * 0.5
    knee = (k_al, side, knee_z)
    if hind:
        # gaskin bulge: thigh goes back first
        thigh = (along - 2.0, side, HIP_Z - 7 + h.bob)
        upper = [hip, thigh, knee]
    else:
        upper = [hip, knee]
    P = lambda p: h.pt(*p)
    up = [P(p) for p in upper]
    lo = [P(knee), P((foot[0], side, foot[2] + 1.6))]
    wu, wl = (6.6 if hind else 5.4), 3.4
    for col, ex in ((LINE, 1.5), (None, 0)):
        c1 = COAT if col is None else col
        c2 = COAT_DARK if col is None else col
        d.line([(S(x), S(y)) for x, y in up], fill=c1, width=int(S(wu + ex)), joint="curve")
        for x, y in up:
            r = (wu + ex) / 2
            d.ellipse([S(x - r), S(y - r), S(x + r), S(y + r)], fill=c1)
        d.line([(S(x), S(y)) for x, y in lo], fill=c2, width=int(S(wl + ex)), joint="curve")
        for x, y in lo:
            r = (wl + ex) / 2
            d.ellipse([S(x - r), S(y - r), S(x + r), S(y + r)], fill=c2)
        # hoof
        hx, hy = P((foot[0] + 0.3 * fwd, side, foot[2] + 0.7))
        rx, ry = 2.4 + ex / 2, 1.5 + ex / 2
        d.ellipse([S(hx - rx), S(hy - ry), S(hx + rx), S(hy + ry)], fill=HOOF if col is None else col)
    # redraw the joint so the coat reaches down over the dark sock top
    kx, ky = P(knee)
    r = wl / 2 + 0.3
    d.ellipse([S(kx - r), S(ky - r - 0.6), S(kx + r), S(ky + r - 0.6)], fill=COAT)
    return im


def tail_layer(h: Horse, sway, run, k_phase):
    im, d = layer()
    root = (-BODY_L / 2 - 1.5, 0.0, BODY_Z + BODY_R * 0.75 + h.bob)
    if run:
        mid = (-BODY_L / 2 - 10, sway * 2.0, BODY_Z + 4 + h.bob)
        tip = (-BODY_L / 2 - 22, sway * 3.5, BODY_Z - 4 + 2 * math.sin(k_phase) + h.bob)
    else:
        mid = (-BODY_L / 2 - 6, sway * 1.5, BODY_Z - 2 + h.bob)
        tip = (-BODY_L / 2 - 9, sway * 3.0, 7.0)
    P = lambda p: h.pt(*p)
    c = bez(P(root), P(mid), P(tip), 14)
    # perpendicular widths along the curve
    left, right = [], []
    for i, (x, y) in enumerate(c):
        t = i / (len(c) - 1)
        wdt = 1.6 + 3.4 * math.sin(math.pi * min(1.0, t * 1.15)) + 0.6 * t
        x2, y2 = c[min(i + 1, len(c) - 1)]
        x1, y1 = c[max(i - 1, 0)]
        tx, ty = x2 - x1, y2 - y1
        tn = math.hypot(tx, ty) or 1
        nx, ny = -ty / tn, tx / tn
        left.append((x + nx * wdt, y + ny * wdt))
        right.append((x - nx * wdt, y - ny * wdt))
    shape = left + bez(left[-1], (c[-1][0] + (c[-1][0] - c[-2][0]) * 2, c[-1][1] + (c[-1][1] - c[-2][1]) * 2), right[-1], 6)[1:-1] + right[::-1]
    pts = [(S(x), S(y)) for x, y in shape]
    d.polygon(pts, fill=TAIL)
    d.line(pts + [pts[0]], fill=LINE, width=int(S(0.75)), joint="curve")
    # two strand highlights
    for off in (-0.35, 0.3):
        strand = [(x + (l[0] - x) * off * 1.6, y + (l[1] - y) * off * 1.6)
                  for (x, y), l in zip(c[2:-2], left[2:-2])]
        d.line([(S(x), S(y)) for x, y in strand], fill=TAIL_HI, width=int(S(0.5)), joint="curve")
    return im


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
    # the t-shirt collar at the bottom of the head box is torso, not head
    r_, g_, b_ = (f[..., i].astype(np.int32) for i in range(3))
    collar = head & (yy > g.neck - 5) & ~loose_skin(f) & (np.abs(r_ - b_) < 30)
    head &= ~collar
    if direction in PROFILE:
        # only the near arm: drop arm blobs on the back side, but never the
        # biggest one (in E/W idle the near arm hangs at the back)
        comps = [c for c in components8(arms) if c.sum() >= 6]
        if len(comps) > 1:
            biggest = max(comps, key=lambda c: c.sum())
            far = np.zeros_like(arms)
            for comp in comps:
                if comp is biggest:
                    continue
                ys, xs = np.nonzero(comp)
                if (xs.mean() + 0.5 - g.head_cx) * PROFILE[direction] < -1.0 and ys.min() > g.neck + 3:
                    far |= comp
            arms &= ~far
            hands &= ~far
    body = (a & ~head & ~arms) | collar
    torso = body & (yy <= waist + 4)
    skin_px = f[face][:, :3]
    skin = tuple(int(v) for v in np.median(skin_px, 0)) if len(skin_px) else (236, 182, 140)
    skin_dark = tuple(int(v * 0.8) for v in skin)

    sh = lambda m: shift(m, dx, dy)
    F = shift(f, dx, dy)
    torso_o, arms_o, hands_o, head_o = sh(torso), sh(arms), sh(hands), sh(head)
    torso_im = class_layer([(torso_o, skin)], SKIN_LINE)
    # muscle lines, clipped to the torso
    mus, md = layer()
    cx = g.hip_cx + dx
    y0, y1 = g.neck + 1 + dy, waist + dy
    th = max(6.0, y1 - y0)
    lw = int(S(0.5))
    L = lambda pts: md.line([(S(x), S(y)) for x, y in pts], fill=skin_dark, width=lw, joint="curve")
    if direction in FRONT:
        c = cx + FRONT[direction] * 1.5
        py = y0 + th * 0.42
        L(bez((c - 5.2, py - 1.5), (c - 3.0, py + 1.0), (c - 0.4, py - 0.3)))
        L(bez((c + 5.2, py - 1.5), (c + 3.0, py + 1.0), (c + 0.4, py - 0.3)))
        L([(c, py + 0.3), (c, y1 - 1.0)])
        for q in (0.68, 0.86):
            yq = y0 + th * q
            L([(c - 2.4, yq), (c - 0.6, yq + 0.3)])
            L([(c + 0.6, yq + 0.3), (c + 2.4, yq)])
    elif direction in BACK:
        c = cx + BACK[direction] * 1.0
        L([(c, y0 + 1.5), (c, y1 - 0.5)])
        py = y0 + th * 0.35
        L(bez((c - 5.0, py - 1.5), (c - 3.5, py + 2.0), (c - 1.5, py + 1.5)))
        L(bez((c + 5.0, py - 1.5), (c + 3.5, py + 2.0), (c + 1.5, py + 1.5)))
    else:
        fc = PROFILE[direction]
        py = y0 + th * 0.45
        L(bez((cx + fc * 0.5, py - 2.5), (cx + fc * 2.0, py + 1.2), (cx + fc * 4.6, py - 0.2)))
        L([(cx + fc * 3.2, y0 + th * 0.75), (cx + fc * 4.2, y0 + th * 0.76)])
    clip = (np.asarray(torso_im)[..., 3] > 0) & (np.asarray(Image.fromarray(
        np.asarray(torso_im)[..., 3]).filter(ImageFilter.MinFilter(int(S(1.2)) * 2 + 1))) > 0)
    mus_a = np.asarray(mus).copy()
    mus_a[..., 3] = mus_a[..., 3] * clip
    mus = Image.fromarray(mus_a, "RGBA")
    sleeves = arms_o & ~hands_o
    arm_im = class_layer([(arms_o, skin)], SKIN_LINE, 0.6) if arms_o.any() else None

    # legs
    legs = []
    for name, al, sd in (("LF", BODY_L / 2 - 4, LEG_SIDE), ("RF", BODY_L / 2 - 4, -LEG_SIDE),
                         ("LH", -BODY_L / 2 + 4.5, LEG_SIDE), ("RH", -BODY_L / 2 + 4.5, -LEG_SIDE)):
        hind = name[1] == "H"
        if t is None:
            swing, lift = 0.0, 0.0
            if anim == "tag":
                # a little lunge into the tag
                p = k / max(n - 1, 1)
                swing = (2.0 if not hind else -1.0) * math.sin(math.pi * p) * (1 if name[0] == "L" else 0.6)
        else:
            ph = 2 * math.pi * (t + offs[name])
            swing = amp * math.sin(ph)
            lift = lift_amp * max(0.0, math.cos(ph))
            if run and hind:
                swing *= 0.85
        legs.append((h.depth(al + swing * 0.5, sd), leg_layer(h, al, sd, swing, lift, hind, run)))
    sway = math.sin(2 * math.pi * (k / max(n, 1))) * (1.0 if t is not None else 0.4)
    tail = tail_layer(h, sway, run, 2 * math.pi * k / max(n, 1))
    tail_depth = h.depth(-BODY_L / 2 - 6)
    barrel, barrel_front = barrel_layer(h, h.depth(WAIST_FWD))

    cv = Image.new("RGBA", (OW * SS, OH * SS), (0, 0, 0, 0))
    behind_tail = h.f[1] >= -0.01     # rump away from the viewer (or side view)
    if behind_tail:
        cv.alpha_composite(tail)
    # every leg hangs from under the barrel: paint them all behind it,
    # far ones first
    legs_back = [im for dep, im in sorted(legs, key=lambda x: x[0])]
    for im in legs_back:
        cv.alpha_composite(im)
    cv.alpha_composite(barrel)
    # the human: torso (head pasted on afterwards at 1x) sits in the barrel
    hum = Image.new("RGBA", cv.size, (0, 0, 0, 0))
    hum.alpha_composite(torso_im)
    hum.alpha_composite(mus)
    if direction in BACK and arm_im is not None:
        hum.alpha_composite(arm_im)
    out = down(cv)
    out = over(out, down(hum))
    out = over(out, premul(F, head_o.astype(np.float64)))
    if direction in BACK:
        out = over(out, premul(F, hands_o.astype(np.float64)))
    top, _ = layer()
    top.alpha_composite(barrel_front)
    if not behind_tail:
        top.alpha_composite(tail)
    out = over(out, down(top))
    if direction not in BACK:
        if arm_im is not None:
            out = over(out, down(arm_im))
        out = over(out, premul(F, hands_o.astype(np.float64)))
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
    Image.fromarray(out).save(ASSETS / "kid_centaur.png", optimize=True)
    pm = dict(meta)
    pm["image"] = "kid_centaur.png"
    pm["frameWidth"], pm["frameHeight"] = OW, OH
    pm["baselineY"] = BASE_Y
    pm["anchorX"] = ANCHOR_X
    (ASSETS / "kid_centaur.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_centaur.png'} ({out.shape[1]}x{out.shape[0]}) frames {OW}x{OH}")

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


if __name__ == "__main__":
    main()
