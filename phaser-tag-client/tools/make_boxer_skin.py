#!/usr/bin/env python3
"""Build the "Boxer James" sprite sheet (public/assets/kid_boxer.png/json)
from the base kid sheet.

Composite onto James's real base frame (do NOT redraw the body):

  * James's face, head, neck, torso silhouette, and legs stay the base;
  * hanging base arms/hands are fully erased (filled with torso/shorts/bg);
  * tee → bare chest with light pec/abs shading on his real skin tone;
  * navy shorts → shiny red boxing trunks with a gold/white waistband that
    sits ON the hips (same width as the torso), gold side trim, mid-thigh;
  * shoes → red / white / gold high-tops with laces (same footprint);
  * bare torso painted in EXACT face/arm skin tone with cartoon pecs,
    six-pack, obliques (front) and scapulae/spine shading (back);
  * glossy RED boxing gloves (~½ head width) with white cuffs + thumbs on a
    single complete shaded arm from each shoulder. Idle / walk / breathe /
    run: tight peek-a-boo guard — both gloves side-by-side covering mouth/
    chin just below the eyes (eyes + upper face stay visible); elbows
    tucked; side views show the near glove IN FRONT of the face (past
    the nose); back views draw gloves behind the head (elbows visible,
    optional side peek on NE/NW);
  * tag is a 6-frame JAB: near arm snaps out from the high guard and
    returns to it. Far glove stays in guard. NW mirrors NE.

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

PAD_TOP = 8
PAD_SIDE = 24
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}

TRUNK = (200, 28, 42)
TRUNK_SHADE = (168, 36, 48)       # soft red shade — never black
TRUNK_HI = (236, 78, 90)
TRUNK_LINE = (120, 18, 28)        # thin darker-red outline (no black)
WAIST = (232, 200, 72)
WAIST_HI = (250, 236, 160)
TRIM = (248, 240, 210)            # white / cream seams + leg openings
TRIM_SHADE = (210, 210, 214)      # light grey shading in place of black
SHOE_RED = (214, 36, 48)
SHOE_WHITE = (248, 248, 246)
SHOE_GOLD = (224, 184, 56)
SOLE = (52, 40, 36)
LACE = (252, 252, 250)
LINE = (36, 22, 20)

GLOVE = (224, 28, 44)
GLOVE_SHADE = (148, 12, 26)
GLOVE_HI = (255, 140, 150)
GLOVE_SPEC = (255, 210, 214)
CUFF = (250, 250, 248)
CUFF_SHADE = (200, 200, 206)
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
        n = 16
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


def arm_comps_on(arms, g, direction, side):
    m = np.zeros_like(arms)
    for comp in components8(arms):
        if comp.sum() < 4:
            continue
        xs = np.nonzero(comp)[1]
        if side == 0 or direction in PROFILE or (xs.mean() + 0.5 - g.head_cx) * side > 0:
            m |= comp
    return m


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


def strip_arms(f, g, direction, sides, waist=None, hem=None):
    """Remove hanging arms on the given sides WITHOUT erasing the torso/shorts.
    Only pixels outside the torso core are stripped. Holes that sit over the
    torso are filled with nearby tee/shorts colours so recolor still sees James
    cloth. Never touch the head or the leg band below the hem."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = f.copy()
    face = (yy <= g.neck + 1) & skin_mask(out)
    arms, _ = arms_and_hands(out, g, face)
    rm = np.zeros_like(arms)
    for s in sides:
        rm |= arm_comps_on(arms, g, direction, s)
    # drop any "arm" blob whose centroid sits in the leg band
    cleaned = np.zeros_like(rm)
    for comp in components8(rm):
        ys = np.nonzero(comp)[0]
        if ys.mean() < g.hem - 6:
            cleaned |= comp
    rm = cleaned
    rm = grow(rm, alpha_mask(out), 1) & (yy > g.neck + 2)
    if waist is None:
        waist = int((hem if hem is not None else g.hem) - 9)
    hem_y = int(hem if hem is not None else g.hem)
    rm &= yy < hem_y - 1  # leave the last shorts row + all legs alone

    ai = alpha_mask(out)
    # Torso CORE: shrink each body row by a few px so hanging arms (outside
    # the silhouette core) are the only thing we strip. Protects tee + shorts.
    core = np.zeros_like(ai)
    for y in range(int(g.neck) + 3, hem_y):
        xs = np.nonzero(ai[y])[0]
        if len(xs) < 6:
            continue
        lo = int(xs.min()) + 3
        hi = int(xs.max()) - 3
        if hi > lo:
            core[y, lo:hi + 1] = True
    # Never erase the torso/shorts core — only true lateral hanging arms
    rm = rm & ~core

    keep = ai & ~rm
    over_t = rm & ai & torso_hull(keep, rm, g)
    # sample fill colours from James himself (tee grey / navy shorts), NOT trunk red
    sk = skin_mask(out) & (yy > g.neck + 2) & (yy < waist - 2)
    if sk.any():
        px = out[sk][:, :3].astype(int)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 40)]
        chest_c = tuple(int(v) for v in np.median(px, 0)) if len(px) else (220, 160, 120)
    else:
        chest_c = (220, 160, 120)
    # tee sample (grey cloth above waist, not skin)
    tee_band = ai & ~skin_mask(out) & (yy > g.neck + 4) & (yy < waist) & ~rm
    if tee_band.any():
        tee_c = tuple(int(v) for v in np.median(out[tee_band][:, :3], 0))
    else:
        tee_c = (90, 90, 95)
    shorts_band = ai & ~skin_mask(out) & (yy >= waist) & (yy < hem_y) & ~rm
    if shorts_band.any():
        sh_c = tuple(int(v) for v in np.median(out[shorts_band][:, :3], 0))
    else:
        sh_c = (40, 40, 55)  # navy placeholder so recolor still sees dark cloth
    chest_fill = over_t & (yy < waist)
    trunk_fill = over_t & (yy >= waist) & (yy < hem_y)
    out[chest_fill, :3] = tee_c   # keep tee-coloured so recolor → chest works
    out[chest_fill, 3] = 255
    out[trunk_fill, :3] = sh_c
    out[trunk_fill, 3] = 255
    out[rm & ~over_t] = 0
    # close holes in chest + shorts only — NEVER below hem_y (legs)
    ai = alpha_mask(out)
    for y in range(int(g.neck) + 2, hem_y):
        xs = np.nonzero(ai[y])[0]
        if len(xs) < 2:
            continue
        hole = np.zeros(w, bool)
        hole[xs.min():xs.max() + 1] = True
        hole &= ~ai[y]
        if hole.any():
            col = tee_c if y < waist else sh_c
            out[y, hole, :3] = col
            out[y, hole, 3] = 255
    return out



def sculpt_torso(out, torso, g, direction, base_skin, waist, xx, yy):
    """Cartoon pecs / six-pack / obliques (front) or V-taper back (N/NE/NW).

    Every shade is a multiple of base_skin so the torso matches face + arms.
    Soft and sparse — readable at sprite scale, not a photo redraw.
    """
    cx = g.head_cx
    base = np.asarray(base_skin, dtype=float)

    def mul(mask, k):
        if mask.any():
            out[mask, :3] = np.clip(out[mask, :3] * k, 0, 255)

    def add_hi(mask, k):
        if mask.any():
            out[mask, :3] = np.clip(out[mask, :3] * k, 0, 255)

    if direction in BACK or direction == "N":
        # Flatten to face peach first so residual tee/arm light peach cannot
        # leave the back brighter than the head/ears. Stay inside the torso
        # core — lateral arm-fill stubs at the hips must not become peach or
        # they trip the hanging-arm consistency check.
        core = torso & (np.abs(xx + 0.5 - cx) < 10.0)
        if core.any():
            out[core, :3] = base[None]

        # Broad traps: soft ridge from neck base out toward each shoulder.
        for sx in (-1.0, 1.0):
            trap = torso & (yy > g.neck + 1) & (yy < g.neck + 10)
            dx = (xx + 0.5 - cx) * sx
            trap &= (dx > 0.8) & (dx < 9.0)
            # Under-trap shade (lower edge of the trap shelf)
            under = trap & (yy > g.neck + 5.5) & (dx > 2.0)
            mul(under, 0.88)
            # Upper trap highlight near the neck→shoulder slope
            ridge = trap & (yy < g.neck + 5.5) & (dx > 1.5) & (dx < 7.0)
            add_hi(ridge, 1.04)

        # Deltoid / outer-shoulder mass (reads as broad shoulders)
        for sx in (-1.0, 1.0):
            cy = g.neck + 5.0
            px = cx + sx * 7.8
            d2 = ((xx + 0.5 - px) ** 2) / 10.0 + ((yy + 0.5 - cy) ** 2) / 8.0
            delt = torso & (d2 < 1.0) & (yy > g.neck + 1) & (yy < g.neck + 12)
            mul(delt & (d2 > 0.40), 0.90)
            add_hi(delt & (d2 < 0.28), 1.05)

        # Shoulder blades — oval pads either side of the spine
        for sx in (-4.6, 4.6):
            cy = g.neck + 11.0
            d2 = ((xx + 0.5 - (cx + sx)) ** 2) / 16.0 + ((yy + 0.5 - cy) ** 2) / 14.0
            blade = torso & (d2 < 1.0) & (yy > g.neck + 5) & (yy < g.neck + 22)
            mul(blade & (d2 > 0.32), 0.87)          # blade rim shadow
            add_hi(blade & (d2 < 0.28) & (yy < cy + 1), 1.05)

        # Defined spine groove (full length of the bare back)
        spine = torso & (np.abs(xx + 0.5 - cx) < 1.15) & (yy > g.neck + 4) & (yy < waist - 1)
        mul(spine, 0.82)
        # Soft para-spinal shade just beside the groove
        for sx in (-1.0, 1.0):
            para = torso & (np.abs(xx + 0.5 - (cx + sx * 1.8)) < 1.1)
            para &= (yy > g.neck + 6) & (yy < waist - 2)
            mul(para, 0.93)

        # Lat V-taper: outer mid-back darkens and angles in toward the waist
        for sx in (-1.0, 1.0):
            dx = (xx + 0.5 - cx) * sx
            lat = torso & (dx > 4.2) & (dx < 11.5)
            lat &= (yy > g.neck + 10) & (yy < waist - 0.5)
            # Stronger shade farther out + lower (V read)
            mul(lat & (dx > 6.5), 0.86)
            mul(lat & (dx <= 6.5), 0.91)
            # Soft diagonal lat slash (cartoon lat fiber)
            for i in range(3):
                yy0 = g.neck + 12 + i * 3.4
                slash = lat & (np.abs(yy - yy0 + dx * 0.22) < 0.75)
                mul(slash, 0.88)

        # Narrow waist shade just above the trunks (locks the V)
        waist_band = torso & (yy > waist - 4) & (yy < waist)
        mul(waist_band & (np.abs(xx + 0.5 - cx) > 3.5), 0.90)

    else:
        # Front / profile / ¾ — pecs
        for sx in (-4.2, 4.2):
            # On profile, only the near pec reads; bias toward facing.
            if direction in PROFILE and sx * PROFILE[direction] < 0:
                continue
            cy = g.neck + 8.5
            px = cx + sx
            if direction in FRONT:
                px += FRONT[direction] * 1.2
            d2 = ((xx + 0.5 - px) ** 2) / 17.0 + ((yy + 0.5 - cy) ** 2) / 8.5
            pec = torso & (d2 < 1.0) & (yy > g.neck + 3) & (yy < g.neck + 15)
            mul(pec & (yy >= cy + 0.5), 0.88)          # under-pec shadow
            add_hi(pec & (yy < cy - 0.5) & (d2 < 0.40), 1.06)  # upper highlight
            # Outer pec falloff toward armpit
            outer = pec & ((xx + 0.5 - cx) * (1 if sx > 0 else -1) > abs(sx) * 0.55)
            mul(outer, 0.92)

        # Sternum cleft
        sternum = torso & (np.abs(xx + 0.5 - cx) < 1.0) & (yy > g.neck + 5) & (yy < g.neck + 14)
        if direction not in PROFILE:
            mul(sternum, 0.84)

        # Six-pack: linea alba + 3 horizontal grooves + soft pads
        abs_top = g.neck + 14.5
        abs_bot = float(waist) - 1.5
        if abs_bot > abs_top + 4 and direction not in PROFILE:
            linea = torso & (np.abs(xx + 0.5 - cx) < 0.85) & (yy > abs_top) & (yy < abs_bot)
            mul(linea, 0.84)
            n_rows = 3
            for i in range(n_rows):
                by = abs_top + 2.0 + i * max((abs_bot - abs_top - 2.0) / n_rows, 3.5)
                if by >= abs_bot - 0.5:
                    break
                groove = torso & (np.abs(yy - by) <= 0.65) & (np.abs(xx + 0.5 - cx) < 5.2)
                mul(groove, 0.86)
                # Pad highlight just above each groove (left + right)
                for sx in (-2.6, 2.6):
                    pad = torso & (np.abs(xx + 0.5 - (cx + sx)) < 2.0)
                    pad &= (yy > by - 3.2) & (yy < by - 0.6)
                    add_hi(pad, 1.05)

        # Obliques / serratus — soft V along the sides
        for sx in (-1, 1):
            if direction in PROFILE and sx * PROFILE[direction] < 0:
                continue
            obl = torso & ((xx + 0.5 - cx) * sx > 4.8) & ((xx + 0.5 - cx) * sx < 9.2)
            obl &= (yy > g.neck + 11) & (yy < waist - 1)
            mul(obl, 0.92)
            # slight diagonal slash for serratus read
            for i in range(3):
                yy0 = g.neck + 12 + i * 3.2
                slash = obl & (np.abs(yy - yy0 - (xx + 0.5 - cx) * sx * 0.15) < 0.7)
                mul(slash, 0.90)

    # Lock torso median luminance to base_skin so face/arms/torso match.
    over = torso & (out[..., :3].mean(-1) < base.mean() * 0.70)
    if over.any():
        out[over, :3] = base * 0.82
    if torso.any():
        cur = float(np.median(out[torso, :3].mean(-1)))
        tgt = float(base.mean())
        if cur > 1 and abs(cur - tgt) > 6:
            # Gentle lift/sink toward face peach; keep relative sculpt contrast.
            k = np.clip(0.55 + 0.45 * (tgt / cur), 0.88, 1.14)
            out[torso, :3] = np.clip(out[torso, :3] * k, 0, 255)


def recolor(f, g, direction="S"):
    """In-place: tee → bare chest + pec/abs; dark shorts → red trunks with
    gold waistband ON the hips (same width as the torso); shoes → R/W/G
    high-tops. Legs, silhouette, face, hair untouched."""
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
    # collar bits of the tee poke into the head mask
    tee_col = (b_ - r_ > 4) & (lum > 40) & (lum < 140)
    cloth &= ~head | ((yy > g.neck - 3) & tee_col)

    # James shorts sit ~9px above the shoe-line hem. Trust that, then refine
    # ONLY inside a tight band so hanging-arm skin never pulls the waist up
    # into the tee.
    dark = cloth & (lum < 55)
    waist = int(g.hem - 9)
    for y in range(max(int(g.hem) - 11, int(g.neck) + 12), int(g.hem) - 5):
        row = cloth[y] | dark[y]
        if row.sum() >= 8 and dark[y].sum() / max(int(row.sum()), 1) > 0.45:
            waist = y
            break
    waist = int(np.clip(waist, g.hem - 11, g.hem - 7))

    shirt = cloth & (yy < waist)
    # Trunks end mid-thigh: leave a clear peach-leg band above the shoes.
    # Prefer a short trunk (waist..waist+6) so legs read clearly like James.
    trunk_bot = min(max(waist + 6, g.hem - 6), g.hem - 3)
    shorts = cloth & (yy >= waist) & (yy <= trunk_bot) & (lum < 120)
    # also catch near-black navy the cloth detector missed
    shorts |= a & ~skin & ~head & (yy >= waist) & (yy <= trunk_bot) & (lum < 70)
    shorts |= (line & (yy >= waist) & (yy <= trunk_bot) & (lum < 30)
               & grow(shorts if shorts.any() else dark, a, 1))
    # shoes: cloth below the leg band (don't start until past the legs)
    shoes = cloth & (yy >= g.hem + 1)
    # shoe pixels sometimes include leftover navy — keep only below hem
    out = f.copy().astype(np.float64)

    # --- chest: paint shirt as EXACT face/arm peach skin, then sculpt ---
    # Strict peach sample only (loose_skinlike on the back catches hair → brown).
    strict = skin_mask(f)
    rr0, gg0, bb0 = f[..., 0].astype(float), f[..., 1].astype(float), f[..., 2].astype(float)
    peach = (
        (rr0 > 150) & (rr0 > bb0 + 18) & (rr0 > gg0 + 4) & (gg0 > 90) & (bb0 > 55)
        & (f[..., 3] >= 128)
    )
    face_sk = strict & peach & (yy > g.top + 8) & (yy <= g.neck - 2)
    leg_sk = strict & peach & (yy >= int(g.hem)) & (yy < int(g.hem) + 12)
    if face_sk.sum() >= 12:
        sk_src = face_sk
    elif leg_sk.sum() >= 12:
        sk_src = leg_sk
    else:
        sk_src = strict & peach
    if sk_src.any():
        px = f[sk_src][:, :3].astype(float)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 35)]
        base_skin = np.median(px, 0) if len(px) else np.array([230.0, 160.0, 115.0])
    else:
        base_skin = np.array([230.0, 160.0, 115.0])
    if shirt.any():
        # Flat skin fill — shading comes from sculpt, not tee luminance (avoids grey).
        out[shirt, :3] = base_skin[None]
        # Soft top-light so the chest isn't a flat stamp. Back views stay flatter
        # so face/ear peach and the torso stay in the same palette.
        ref_y = float(g.neck + 4)
        span = max(float(waist - g.neck), 1.0)
        if direction in BACK or direction == "N":
            k = np.clip(1.01 - 0.06 * (yy[shirt] - ref_y) / span, 0.94, 1.02)
        else:
            k = np.clip(1.04 - 0.10 * (yy[shirt] - ref_y) / span, 0.92, 1.06)
        out[shirt, :3] = np.clip(out[shirt, :3] * k[:, None], 0, 255)
    torso = (shirt | (skin & (yy > g.neck + 3) & (yy < waist))) & a & ~head
    # Also recolor any residual mid-tone tee cloth the shirt mask missed.
    leftover = a & ~skin & ~head & (yy > g.neck + 2) & (yy < waist)
    leftover &= (lum > 35) & (lum < 150) & (np.abs(r_ - g_) < 35) & (b_ >= r_ - 10)
    if leftover.any():
        out[leftover, :3] = base_skin[None]
        torso |= leftover
    if torso.any():
        sculpt_torso(out, torso, g, direction, base_skin, waist, xx, yy)

    def paint(m, col, lo=0.82, hi=1.05):
        if not m.any():
            return
        ref = np.percentile(lum[m], 80) or 1.0
        k = np.clip(lo + (hi - lo) * lum[m] / ref, lo, hi)
        out[m, :3] = np.array(col, float)[None] * k[:, None]

    # Cover hanging-arm skin that sits over the shorts (inside the hip span)
    # so peach arms don't float on top of the trunks after we skip a full strip.
    arm_over = skin & a & (yy >= waist) & (yy <= trunk_bot) & (yy < g.hem - 2)
    shorts |= arm_over

    # --- trunks: recolor existing shorts pixels (keeps legs!) ---
    paint(shorts, TRUNK, 0.84, 1.08)
    # Gold waistband ON the hips: same x-span as the opaque body at the waist,
    # 3 rows tall. Painted by geometry so it never floats wider or goes missing
    # when the shorts mask is thin.
    y_ref = max(int(waist) - 2, int(g.neck) + 8)
    body_xs = np.nonzero(a[y_ref])[0]
    if len(body_xs) < 2:
        body_xs = np.nonzero(a[min(int(waist), h - 1)])[0]
    if len(body_xs) >= 2:
        x_lo, x_hi = int(body_xs.min()), int(body_xs.max())
        for dy in range(3):
            y = int(waist) + dy
            if y >= h:
                break
            band = a[y].copy()
            band[:x_lo] = False
            band[x_hi + 1:] = False
            # only paint over trunk/cloth rows (not peach legs)
            band &= (yy[y] >= 0)  # keep shape
            if dy == 0:
                out[y, band, :3] = WAIST_HI
            else:
                out[y, band, :3] = WAIST
            out[y, band, 3] = 255
        # Erase leftover peach arm-fill stubs beside the hips (outside the
        # waistband span). Recolor painted them when erase_base_arms filled
        # hanging-arm holes with tee colour.
        for y in range(int(waist), min(int(waist) + 10, h)):
            row_a = out[y, :, 3] >= 128
            rr = out[y, :, 0]; gg = out[y, :, 1]; bb = out[y, :, 2]
            peach = row_a & (rr > 140) & (rr > bb + 20) & (rr > gg + 8) & (gg > 70) & (bb > 50)
            peach &= (rr + gg + bb) / 3.0 < 160  # not white trim / gold hi
            outside = np.zeros(w, dtype=bool)
            outside[: max(x_lo - 1, 0)] = True
            outside[min(x_hi + 2, w):] = True
            kill = peach & outside
            if kill.any():
                out[y, kill, :3] = TRUNK
                out[y, kill, 3] = 255
    if shorts.any():
        top = np.zeros_like(shorts)
        for x in range(w):
            ys = np.nonzero(shorts[:, x])[0]
            if len(ys):
                top[ys.min():min(ys.min() + 3, ys.max() + 1), x] = True
        top &= shorts
        # white side seams + white leg-opening trim (no black)
        for y in range(h):
            xs = np.nonzero(shorts[y] & ~top[y])[0]
            if len(xs) < 3:
                continue
            out[y, xs.min(), :3] = TRIM
            out[y, xs.max(), :3] = TRIM
        bot = shorts & ~np.roll(shorts, -1, 0) & (yy > waist + 3)
        out[bot, :3] = TRIM
        seam = shorts & ~top & (np.abs(xx + 0.5 - g.hip_cx) < 1.2) & (yy > waist + 2)
        out[seam, :3] = TRIM_SHADE
        gloss = shorts & ~top & (np.abs(xx + 0.5 - g.hip_cx) < 4) & (yy < waist + 6)
        out[gloss, :3] = np.clip(out[gloss, :3] * 1.08, 0, 255)

    # Scrub leftover black / near-black in the trunk band → white or soft red.
    # Trunks must be red + gold + white only (Jim: "no black in the shorts").
    trunk_zone = a & (yy >= waist) & (yy <= trunk_bot + 1) & (yy < g.hem - 1)
    if trunk_zone.any():
        rr, gg, bb = out[..., 0].astype(float), out[..., 1].astype(float), out[..., 2].astype(float)
        t_lum = (rr + gg + bb) / 3.0
        # anything darker than soft red shade gets scrubbed
        dark = trunk_zone & (t_lum < 100)
        is_gold = (rr > 170) & (gg > 130) & (bb < 140) & (rr - bb > 60)
        is_white = (t_lum >= 160) | ((rr > 180) & (gg > 180) & (bb > 170))
        is_red = (rr > 100) & (rr > gg + 25) & (rr > bb + 25) & (t_lum >= 70)
        dark = dark & ~is_gold & ~is_white & ~is_red
        edge = np.zeros_like(dark)
        for y in range(h):
            xs = np.nonzero(trunk_zone[y])[0]
            if len(xs) < 2:
                continue
            edge[y, xs.min()] = True
            edge[y, xs.max()] = True
        out[dark & edge, :3] = TRUNK_LINE
        interior_dark = dark & ~edge
        reddish = interior_dark & (rr > gg + 15) & (rr > bb + 15)
        out[interior_dark & ~reddish, :3] = TRIM
        out[reddish, :3] = TRUNK_SHADE

    # --- high-top shoes on existing shoe pixels ---
    sole = np.zeros_like(shoes)
    for x in range(w):
        ys = np.nonzero(shoes[:, x] | (line[:, x] & (yy[:, x] > g.hem)))[0]
        if len(ys) and shoes[:, x].any():
            sole[ys.max() - 1:ys.max() + 1, x] = True
    paint(shoes & ~sole, SHOE_RED, 0.85, 1.05)
    out[shoes & sole, :3] = SOLE
    for comp in components8(shoes & ~sole):
        if comp.sum() < 4:
            continue
        ys, xs = np.nonzero(comp)
        cx = xs.mean()
        top_shoe = comp & (yy <= ys.min() + 2)
        out[top_shoe, :3] = SHOE_WHITE
        mid = comp & (yy >= ys.min() + 2) & (yy <= ys.min() + 4)
        out[mid, :3] = SHOE_GOLD
        for ly in range(ys.min() + 1, min(ys.min() + 5, ys.max())):
            for lx in (int(cx) - 1, int(cx) + 1):
                if 0 <= lx < w and comp[ly, lx]:
                    out[ly, lx, :3] = LACE

    # 1px high-top cuff onto the ankle only — never climb into the shin
    for comp in components8(shoes):
        if comp.sum() < 4:
            continue
        ys, xs = np.nonzero(comp)
        cuff = (a & skin & (yy == ys.min() - 1)
                & (xx >= xs.min()) & (xx <= xs.max()))
        if cuff.any():
            out[cuff, :3] = SHOE_GOLD

    # Outline: black LINE on tee/shoes only. Trunks get thinner darker-red edge.
    near_tee_shoe = line & grow(shirt | shoes, a, 1) & ~head & ~shorts
    out[near_tee_shoe, :3] = LINE
    near_trunk = line & grow(shorts, a, 1) & ~head & shorts
    out[near_trunk, :3] = TRUNK_LINE
    # Re-scrub waistband rows that LINE might still have blackened
    wb_rows = a & (yy >= waist) & (yy <= waist + 2)
    line_on_wb = wb_rows & (out[..., 0] < 60) & (out[..., 1] < 50) & (out[..., 2] < 50)
    out[line_on_wb, :3] = WAIST
    # Final trunk scrub after outline so no black survives on shorts
    trunk_zone2 = a & (yy >= waist) & (yy <= trunk_bot + 1) & (yy < g.hem - 1)
    if trunk_zone2.any():
        rr, gg, bb = out[..., 0].astype(float), out[..., 1].astype(float), out[..., 2].astype(float)
        t_lum = (rr + gg + bb) / 3.0
        is_gold = (rr > 170) & (gg > 130) & (bb < 140) & (rr - bb > 60)
        is_white = (t_lum >= 160) | ((rr > 180) & (gg > 180) & (bb > 170))
        is_red = (rr > 90) & (rr > gg + 20) & (rr > bb + 20)
        bad = trunk_zone2 & (t_lum < 70) & ~is_gold & ~is_white & ~is_red
        edge = np.zeros_like(bad)
        for y in range(h):
            xs = np.nonzero(trunk_zone2[y])[0]
            if len(xs) >= 2:
                edge[y, xs.min()] = True
                edge[y, xs.max()] = True
        out[bad & edge, :3] = TRUNK_LINE
        out[bad & ~edge & ((rr > gg + 10) & (rr > bb + 10)), :3] = TRUNK_SHADE
        out[bad & ~edge & ~((rr > gg + 10) & (rr > bb + 10)), :3] = TRIM
    return to_u8_simple(out), waist


def glove_radius(g):
    """~½ head width → diameter ≈ head_hw, radius ≈ head_hw/2."""
    return max(6.5, min(8.5, g.head_hw * 0.45))


def shoulder(g, direction, side):
    """Attach at the deltoid — not flared out past the torso."""
    s = side or 1
    if direction in PROFILE:
        # Slightly rear of center so the forearm runs forward past the nose.
        return (g.head_cx - PROFILE[direction] * 2.0, g.neck + 3.0)
    if direction in BACK or direction == "N":
        # On the outer deltoid of the back — upper arm hangs straight down
        # hugging the lat (no gap that reads as a chicken wing).
        return (g.head_cx + s * 7.5, g.neck + 3.5)
    # Front / ¾
    return (g.head_cx + s * 6.8, g.neck + 2.5)


def guard_hand(sh, direction, side, bounce=0.0, gr=8.0, g=None):
    """Tight peek-a-boo: gloves at mouth/chin; elbows hang DOWN (not flared).

    Profile: glove in FRONT of the face, past the nose on the facing side.
    Back (N/NE/NW): hands under each side of the skull (not centered) so the
    short visible forearm stubs hang nearly vertical — no inward diamond.
    """
    neck = g.neck if g is not None else sh[1] - 2.2
    cx = g.head_cx if g is not None else sh[0]
    hw = g.head_hw if g is not None else 18.0
    mouth_y = neck - 9.0 + bounce * 0.35
    s = side or 1
    if direction in PROFILE:
        fx = PROFILE[direction]
        # Fist past the nose so the glove clearly sits in front of the face.
        tip = cx + fx * (hw * 0.95)
        return (tip + fx * (gr * 0.45), mouth_y + 1.0)
    if direction == "N":
        # Deep under the skull, X-aligned with the hanging upper arm so any
        # leftover stub is vertical (not an inward diamond / chicken wing).
        return (sh[0] + s * 0.3, mouth_y + 4.0)
    if direction in BACK:
        # Chin under the head; stay inside the skull so stamp_head covers them.
        chin_y = neck - 4.0 + bounce * 0.35
        facing = BACK[direction]
        if s == facing:
            # Slight peek allowed on the facing cheek for NE/NW.
            return (cx + s * (hw * 0.40), chin_y)
        return (cx + s * (hw * 0.20), chin_y + 0.5)
    # Front / ¾: fists nearly touching in front of the mouth.
    face_bias = FRONT.get(direction, 0) * 1.0
    return (cx + s * (gr * 0.85) + face_bias, mouth_y)


JAB_REACH = [11.0, 15.5, 21.5, 27.0, 17.5, 12.0]
JAB_ANG = {
    "profile": [-48, -28, -8, 4, -16, -42],
    "front":   [-60, -38, -14, 0, -20, -54],
    "back":    [-95, -72, -44, -18, -50, -88],
}
# Blend from high-guard → full extend → back to guard across the 6 jab frames.
JAB_BLEND = [0.10, 0.42, 0.82, 1.00, 0.52, 0.12]


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


def jab_hand(g, direction, side, p_idx, gr):
    """Jab extends from the high guard and returns to it."""
    sh = shoulder(g, direction, side)
    guard = guard_hand(sh, direction, side, 0.0, gr, g)
    ang, R = jab_pose(direction, p_idx, side)
    ext = (sh[0] + math.cos(ang) * R, sh[1] + math.sin(ang) * R)
    t = JAB_BLEND[min(p_idx, len(JAB_BLEND) - 1)]
    return (guard[0] + (ext[0] - guard[0]) * t,
            guard[1] + (ext[1] - guard[1]) * t)


def glove_parts(sh, elbow, hand, skin, gr, jabbing=False):
    ex, ey = hand[0] - elbow[0], hand[1] - elbow[1]
    en = math.hypot(ex, ey) or 1.0
    ux, uy = ex / en, ey / en
    cuff_c = (hand[0] - ux * (gr + 2.2), hand[1] - uy * (gr + 2.2))
    wrist = (hand[0] - ux * (gr * 0.55), hand[1] - uy * (gr * 0.55))
    hi = (hand[0] - gr * 0.28, hand[1] - gr * 0.32)
    spec = (hand[0] - gr * 0.38, hand[1] - gr * 0.42)
    shade = (hand[0] + gr * 0.22, hand[1] + gr * 0.28)
    # Thumb bump: inner side of the fist (toward face / body center). Mild
    # upward bias so high-guard thumbs don't climb over the eyes.
    inward_x = 1.0 if sh[0] >= hand[0] else -1.0
    nx, ny = -uy, ux
    if nx * (sh[0] - hand[0]) + ny * (sh[1] - hand[1]) < 0:
        nx, ny = -nx, -ny
    nx = 0.60 * nx + 0.50 * inward_x
    ny = 0.40 * ny - 0.30
    nn = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nn, ny / nn
    tr = max(3.0, gr * 0.52)
    thumb = (hand[0] + nx * (gr * 1.05), hand[1] + ny * (gr * 1.00))
    thumb_shade = (thumb[0] + nx * 0.6 + ux * 0.2, thumb[1] + ny * 0.6 + uy * 0.2)
    thumb_hi = (thumb[0] - nx * 0.55 - 0.15, thumb[1] - ny * 0.55 - 0.35)
    seam_a = (hand[0] + nx * (gr * 0.42), hand[1] + ny * (gr * 0.28))
    seam_b = (thumb[0] - nx * (tr * 0.25), thumb[1] - ny * (tr * 0.25))
    if jabbing:
        u0, u1, f0, f1 = 5.4, 4.8, 4.6, 4.0
    else:
        u0, u1, f0, f1 = 5.2, 4.6, 4.2, 3.7
    skin2 = tuple(int(v * 0.86) for v in skin)
    skin3 = tuple(int(v * 0.80) for v in skin)
    # Inner triceps shade (inside the capsule) — mass without widening hips.
    mid = (sh[0] * 0.55 + elbow[0] * 0.45, sh[1] * 0.55 + elbow[1] * 0.45)
    return [
        (capsule_fn(sh, u0, elbow, u1), skin),
        (capsule_fn(sh, u0 * 0.55, elbow, u1 * 0.55), skin2),
        (disc_fn(mid, u0 * 0.35), skin3),
        (capsule_fn(elbow, f0, wrist, f1), skin),
        (capsule_fn(elbow, f0 * 0.55, wrist, f1 * 0.55), skin2),
        (disc_fn(cuff_c, 3.4), CUFF),
        (disc_fn(cuff_c, 2.2), CUFF_SHADE),
        (disc_fn(hand, gr), GLOVE),
        (disc_fn(shade, gr * 0.55), GLOVE_SHADE),
        (disc_fn(thumb, tr), GLOVE),
        (disc_fn(thumb_shade, tr * 0.55), GLOVE_SHADE),
        (capsule_fn(seam_a, 0.7, seam_b, 0.55), GLOVE_SHADE),
        (disc_fn(thumb_hi, tr * 0.32), GLOVE_HI),
        (disc_fn(hi, gr * 0.34), GLOVE_HI),
        (disc_fn(spec, gr * 0.15), GLOVE_SPEC),
    ]


def guard_elbow_target(sh, hand, direction, side, head_cx):
    """Elbow DOWN and only slightly out — no chicken-wing flare.

    Upper arm hangs from the shoulder close to the torso to about the
    bottom of the ribs/lats; forearm then angles up/forward to the glove.
    From behind: hanging upper arms + tucked side elbows (no horizontal flare).
    Profile: clear V/L — upper arm down, forearm up/forward to the glove.
    """
    s = side or 1
    if direction in PROFILE:
        fx = PROFILE[direction]
        # Down and clearly REAR of the shoulder — readable L/V: upper arm
        # down to bottom of ribs, forearm forward-up past the nose.
        ex = sh[0] - fx * 4.5
        ey = sh[1] + 13.0
    elif direction == "N":
        # Almost straight under the deltoid — hang close to the torso.
        # Only a hair outward so the elbow reads at the lat edge, not flared.
        ex = sh[0] + s * 0.5
        ey = sh[1] + 11.5
    elif direction in BACK:
        # NE/NW: hang down the lat, slightly out, elbows at bottom of ribs.
        ex = sh[0] + s * 1.0
        ey = sh[1] + 11.5
    else:
        # Front / ¾: elbows tucked down at the sides of the ribcage.
        ex = sh[0] + s * 1.0
        ey = sh[1] + 11.5
    # Always below the shoulder so the bend reads as down-then-up.
    ey = max(ey, sh[1] + 9.0)
    return (ex, ey)


def draw_arm(size, sh, hand, skin, gr, jabbing=False, head_cx=None,
             direction=None, side=None):
    """Draw a complete shoulder→elbow→glove arm.

    Guard: elbows hang DOWN and slightly out (Jim: no chicken-wing flare).
    Jab: straighten toward the punch while keeping a readable bend early on.
    """
    # Segment lengths guide jab IK only; guard elbows use an explicit target.
    L1, L2 = 13.0, 16.0
    e1 = ik(sh, hand, L1, L2, 1)
    e2 = ik(sh, hand, L1, L2, -1)
    cx = head_cx if head_cx is not None else sh[0]
    if jabbing:
        def off(e):
            dx, dy = hand[0] - sh[0], hand[1] - sh[1]
            lx = math.hypot(dx, dy) or 1.0
            return abs((hand[0] - sh[0]) * (sh[1] - e[1]) - (sh[0] - e[0]) * (hand[1] - sh[1])) / lx
        elbow = e1 if off(e1) < off(e2) else e2
        t = 0.45
        mid = (sh[0] + (hand[0] - sh[0]) * t, sh[1] + (hand[1] - sh[1]) * t)
        elbow = (elbow[0] * 0.35 + mid[0] * 0.65, elbow[1] * 0.35 + mid[1] * 0.65)
        # Keep a readable downward bend on partial extensions.
        if direction is not None:
            tgt = guard_elbow_target(sh, hand, direction, side if side is not None else 1, cx)
            reach = math.hypot(hand[0] - sh[0], hand[1] - sh[1])
            t_ext = max(0.0, min(1.0, (reach - 10.0) / 18.0))
            k = 0.55 * (1.0 - t_ext)
            elbow = (elbow[0] * (1 - k) + tgt[0] * k,
                     max(elbow[1] * (1 - k) + tgt[1] * k, sh[1] + 4.0))
    else:
        # Guard pose: lock the elbow to the down-tucked target. Pure IK
        # prefers a high/lateral "chicken-wing" when the glove sits high in
        # front of the face, so do not let IK pull the joint back out.
        tgt = guard_elbow_target(sh, hand, direction or "S",
                                 side if side is not None else 1, cx)
        elbow = (tgt[0], max(tgt[1], sh[1] + 9.0))
        # Tiny outward clamp relative to the shoulder — keep "slightly out"
        # but never a horizontal flare past ~4px from the shoulder.
        s = side if side is not None else (1 if elbow[0] >= sh[0] else -1)
        if direction not in PROFILE:
            max_out = abs(sh[0] - cx) + 4.0
            if abs(elbow[0] - cx) > max_out:
                elbow = (cx + math.copysign(max_out, elbow[0] - cx), elbow[1])
            # Never allow an inboard elbow on back/front (diamond silhouette).
            if direction in BACK or direction == "N" or direction in FRONT or direction == "S":
                # Keep a hair outside the shoulder so the arm doesn't collapse
                # into the torso, but allow the tight N tuck (0.5px).
                min_out = 0.4 if direction == "N" else 0.8
                if s > 0 and elbow[0] < sh[0] + min_out:
                    elbow = (sh[0] + min_out, elbow[1])
                if s < 0 and elbow[0] > sh[0] - min_out:
                    elbow = (sh[0] - min_out, elbow[1])
    # Back views: only a short forearm stub should show below the head.
    # Aim the capsule at a point on the shoulder→hand segment near the neck
    # so the visible bend is upper-arm + elbow, not a long inward diamond.
    draw_hand = hand
    if (not jabbing) and direction is not None and (direction in BACK or direction == "N"):
        skin2 = tuple(int(v * 0.86) for v in skin)
        skin3 = tuple(int(v * 0.80) for v in skin)
        real = glove_parts(sh, elbow, hand, skin, gr, False)
        if direction == "N":
            # Pure back: only hanging upper arms + tucked elbow caps.
            # No forearm tubes (they read as chicken-wing diamonds). Gloves
            # stay under the skull and get stamped over.
            u0, u1 = 5.2, 4.6
            mid = (sh[0] * 0.55 + elbow[0] * 0.45, sh[1] * 0.55 + elbow[1] * 0.45)
            tubes = [
                (capsule_fn(sh, u0, elbow, u1), skin),
                (capsule_fn(sh, u0 * 0.55, elbow, u1 * 0.55), skin2),
                (disc_fn(mid, u0 * 0.35), skin3),
                (disc_fn(elbow, 3.6), skin),
                (disc_fn(elbow, 2.2), skin2),
            ]
            parts = tubes + real[5:]
            return shapes_layer(size, parts, ARM_LINE, 1.0)
        # NE/NW: short vertical-ish forearm stub only.
        neck_y = sh[1] - 3.0
        dy = hand[1] - elbow[1]
        if abs(dy) > 1.0 and hand[1] < neck_y:
            t = (neck_y - elbow[1]) / dy
            t = max(0.12, min(0.40, t))
            # Bias stub X toward the elbow so it hangs up, not inward.
            stub = (elbow[0] * 0.75 + hand[0] * 0.25,
                    elbow[1] + (hand[1] - elbow[1]) * t)
            arm_only = glove_parts(sh, elbow, stub, skin, max(3.0, gr * 0.35), False)
            tubes = arm_only[:5]
            parts = tubes + real[5:]
            return shapes_layer(size, parts, ARM_LINE, 1.0)
    return shapes_layer(size, glove_parts(sh, elbow, hand, skin, gr, jabbing), ARM_LINE, 1.0)


def skin_rgb_of(f):
    """Median peach face/leg skin — same palette used for torso + glove arms."""
    sk = skin_mask(f)
    if not sk.any():
        return (230, 160, 115)
    rr, gg, bb = f[..., 0].astype(int), f[..., 1].astype(int), f[..., 2].astype(int)
    peach = sk & (rr > 150) & (rr > bb + 18) & (rr > gg + 4) & (gg > 90) & (bb > 55)
    src = peach if peach.sum() >= 12 else sk
    px = f[src][:, :3].astype(int)
    px = px[px.sum(1) >= np.percentile(px.sum(1), 40)]
    return tuple(int(v) for v in np.median(px, 0)) if len(px) else (230, 160, 115)


def bounce_of(anim, col, meta):
    if anim not in ("walk", "run"):
        return 0.0
    rng = meta["animations"][anim]
    k = col - rng["start"]
    return 1.0 * math.sin(k * math.pi / 2.0)


def erase_base_arms(f, g):
    """Fully erase James's hanging base arms/hands BEFORE recolor.

    Detect arms while the tee still separates them from the torso, clear
    anything outside a chest→hip silhouette to transparency, and fill only the
    interior (hand-over-shorts / arm-over-tee) with tee or shorts colour so
    recolor still sees cloth. Legs below the hem are never touched.
    """
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = f.copy()
    face = (yy <= g.neck + 1) & skin_mask(out)
    arms, hands = arms_and_hands(out, g, face)
    rm = arms | hands
    ai = alpha_mask(out)
    rm = grow(rm, ai, 1) & (yy > g.neck + 2) & (yy < int(g.hem) - 1)
    cleaned = np.zeros_like(rm)
    for comp in components8(rm):
        ys = np.nonzero(comp)[0]
        if len(ys) and ys.mean() < g.hem - 4:
            cleaned |= comp
    rm = cleaned
    keep = ai & ~rm

    chest_spans, hip_spans, pre_hip = [], [], []
    for y in range(int(g.neck) + 3, int(g.neck) + 12):
        xs = np.nonzero(keep[y])[0]
        if len(xs) >= 6:
            chest_spans.append((int(xs.min()), int(xs.max())))
    for y in range(int(g.hem) - 6, int(g.hem) - 1):
        xs = np.nonzero(keep[y])[0]
        if len(xs) >= 6:
            hip_spans.append((int(xs.min()), int(xs.max())))
        xs = np.nonzero(ai[y])[0]
        if len(xs) >= 8:
            pre_hip.append((int(xs.min()), int(xs.max())))

    if chest_spans:
        cL = float(np.median([s[0] for s in chest_spans]))
        cR = float(np.median([s[1] for s in chest_spans]))
    else:
        cL, cR = w * 0.35, w * 0.65
    if hip_spans:
        hL = float(np.median([s[0] for s in hip_spans]))
        hR = float(np.median([s[1] for s in hip_spans]))
    else:
        hL, hR = cL - 2, cR + 2
    # Hands often occlude shorts sides — if keep-hip collapsed, restore toward
    # the pre-erase hip span (inset 1px) so trunks keep torso width.
    if pre_hip and (hR - hL) < (cR - cL) + 2:
        pL = float(np.median([s[0] for s in pre_hip]))
        pR = float(np.median([s[1] for s in pre_hip]))
        hL = min(hL, pL + 1)
        hR = max(hR, pR - 1)

    y_c = int(g.neck) + 7
    y_h = int(g.hem) - 3
    L = np.full(h, np.nan)
    R = np.full(h, np.nan)
    for y in range(int(g.neck) + 2, int(g.hem) + 1):
        t = 0.0 if y_h == y_c else float(np.clip((y - y_c) / (y_h - y_c), 0, 1))
        L[y] = cL + t * (hL - cL)
        R[y] = cR + t * (hR - cR)

    waist = int(g.hem - 9)
    sk = skin_mask(out)
    tee_band = keep & ~sk & (yy > g.neck + 4) & (yy < waist)
    tee_c = tuple(int(v) for v in np.median(out[tee_band][:, :3], 0)) if tee_band.any() else (90, 90, 95)
    shorts_band = keep & ~sk & (yy >= waist) & (yy < g.hem)
    sh_c = tuple(int(v) for v in np.median(out[shorts_band][:, :3], 0)) if shorts_band.any() else (40, 40, 55)

    fill = np.zeros_like(rm)
    for y in range(int(g.neck) + 2, int(g.hem)):
        if np.isnan(L[y]):
            continue
        lo, hi = int(round(L[y])), int(round(R[y]))
        inside = rm[y].copy()
        inside[:lo] = False
        inside[hi + 1:] = False
        fill[y] |= inside
    clear = rm & ~fill
    out[clear] = 0
    chest_fill = fill & (yy < waist)
    trunk_fill = fill & (yy >= waist)
    out[chest_fill, :3] = tee_c
    out[chest_fill, 3] = 255
    out[trunk_fill, :3] = sh_c
    out[trunk_fill, 3] = 255

    ai2 = alpha_mask(out)
    for y in range(int(g.neck) + 2, int(g.hem)):
        if np.isnan(L[y]):
            continue
        lo, hi = int(round(L[y])), int(round(R[y]))
        hole = np.zeros(w, bool)
        hole[lo:hi + 1] = True
        hole &= ~ai2[y]
        if hole.any():
            col = tee_c if y < waist else sh_c
            out[y, hole, :3] = col
            out[y, hole, 3] = 255
    return out



def head_occluder_mask(rc, g):
    """Head/hair occlusion for back-view gloves held in front of the face.

    Opaque head silhouette, grown, plus a filled ellipse over the skull so
    gloves beside a tapered crown still hide under hair.
    """
    h, w = rc.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    sil = (rc[..., 3] >= 128) & (yy <= g.neck + 2)
    sil = grow(sil, np.ones((h, w), dtype=bool), 2) & (yy <= g.neck + 5)
    top = max(0, int(g.neck) - 38)
    cy = (top + g.neck) * 0.52
    rx = max(g.head_hw * 1.15, 18.0)
    ry = max((g.neck - top) * 0.58, 15.0)
    ellipse = ((xx - g.head_cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    ellipse &= yy <= g.neck + 4
    return sil | ellipse


def stamp_head_over(res, rc, g, direction=None):
    """Put James's head back on top so back-view gloves sit behind it.

    Restores opaque head/hair over anything under it, then clears only
    leftover glove/cuff pixels that still sit inside the head's span
    (arms/elbows outside the hair are kept so jab forearms stay connected).
    """
    head = head_occluder_mask(rc, g)
    out = res.copy()
    opaque = rc[..., 3] >= 128
    # Restore James's real head/hair wherever the base was opaque.
    out[head & opaque] = rc[head & opaque]

    h, w = res.shape[:2]
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    rgb = out[..., :3].astype(int)
    a = out[..., 3]
    glove = (a >= 200) & (rgb[..., 0] > 160) & (rgb[..., 1] < 110) & (
        rgb[..., 0] > rgb[..., 1] + 60
    )
    cuff = (a >= 200) & (rgb.sum(-1) / 3.0 > 200) & (yy < g.neck + 2) & (yy > g.neck - 30)
    band = (yy <= g.neck + 1) & (yy >= g.neck - 36)
    # Pure N: wipe gloves across a generous head width so nothing peeks
    # beside the ears (those peeks read as chicken-wing high elbows).
    if direction == "N":
        half = g.head_hw * 1.35
    else:
        half = g.head_hw * 1.05
    span = (xx >= g.head_cx - half) & (xx <= g.head_cx + half)
    # NE/NW: leave a peek strip past the facing face edge.
    if direction in ("NE", "NW"):
        facing = BACK[direction]
        if facing > 0:
            span &= xx <= g.head_cx + g.head_hw * 0.85
        else:
            span &= xx >= g.head_cx - g.head_hw * 0.85
    # Also clear glove/cuff in the occluder but outside opaque hair (crown gap).
    hide = (band & span & (glove | cuff)) | (head & ~opaque & (glove | cuff))
    restore = hide & opaque
    out[restore] = rc[restore]
    out[hide & ~opaque] = 0
    return out


def boxify(frame, direction, anim, col, meta):
    """Composite Boxer onto James: erase base arms, recolor tee/shorts/shoes,
    then draw complete shoulder→glove arms. Body silhouette is never redrawn."""
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

    # 1) Start from James (idle body for tag so the jab pose is stable).
    if tag:
        idle = pad_frame(meta["_base_idle"][direction])
        body = idle
        g = Geometry(idle)
    else:
        body = f

    # 2) Fully erase hanging base arms/hands WHILE tee still separates them
    #    from the torso; fill torso/shorts holes so recolor sees cloth.
    body = erase_base_arms(body, Geometry(body))
    g = Geometry(body)

    # 3) Recolor in place (tee→chest, navy→trunks+gold waistband, shoes→high-tops).
    rc, waist = recolor(body, g, direction)
    g = Geometry(rc)

    skin = skin_rgb_of(rc)
    gr = glove_radius(g)
    out = premul(rc, np.ones((h, w)))

    if tag:
        n = rng["count"]
        p = min(k, n - 1)
        # Start/end of the jab stay in the down-elbow guard; only mid frames
        # straighten into the punch.
        jabbing = JAB_BLEND[min(p, len(JAB_BLEND) - 1)] > 0.35
        if direction not in PROFILE:
            far = -side
            sh_f = shoulder(g, direction, far)
            hd_f = guard_hand(sh_f, direction, far, 0.0, gr, g)
            out = over(out, down(draw_arm(
                size, sh_f, hd_f, skin, gr, False, g.head_cx,
                direction=direction, side=far)))
        sh_n = shoulder(g, direction, side)
        hd_n = jab_hand(g, direction, side, p, gr)
        out = over(out, down(draw_arm(
            size, sh_n, hd_n, skin, gr * 1.05, jabbing, g.head_cx,
            direction=direction, side=side)))
    else:
        show = [side] if direction in PROFILE else [1, -1]
        for s in show:
            sh = shoulder(g, direction, s)
            hd = guard_hand(sh, direction, s, bounce, gr, g)
            out = over(out, down(draw_arm(
                size, sh, hd, skin, gr, False, g.head_cx,
                direction=direction, side=s)))

    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    # Back views: gloves are held in FRONT of the face, so the head must
    # occlude them. Stamp James's head/hair back on top (elbows below the
    # neck stay visible; NE/NW may keep a side peek past the head edge).
    if direction in BACK or direction == "N":
        res = stamp_head_over(res, rc, g, direction)
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 30:
                res[c] = 0
    res = solidify(res, (int(g.neck), int(g.hem) - 1))
    # Solidify can re-bleed glove into the skull — re-stamp head after it.
    if direction in BACK or direction == "N":
        res = stamp_head_over(res, rc, g, direction)
    # Final trunk scrub after gloves/ARM_LINE so shorts stay red/gold/white.
    yy = np.arange(h)[:, None]
    trunk_bot = min(int(g.hem) - 4, int(waist) + 12)
    zone = (res[..., 3] >= 200) & (yy >= int(waist)) & (yy <= trunk_bot)
    if zone.any():
        rr = res[..., 0].astype(float)
        gg = res[..., 1].astype(float)
        bb = res[..., 2].astype(float)
        lum = (rr + gg + bb) / 3.0
        is_gold = (rr > 170) & (gg > 130) & (bb < 140) & (rr - bb > 60)
        is_white = (lum >= 160) | ((rr > 180) & (gg > 180) & (bb > 170))
        is_red = (rr > 90) & (rr > gg + 20) & (rr > bb + 20)
        is_glove = (rr > 140) & (rr > gg + 40) & (rr > bb + 40) & (gg < 120)
        bad = zone & (lum < 70) & ~is_gold & ~is_white & ~is_red & ~is_glove
        edge = np.zeros_like(bad)
        for y in range(h):
            xs = np.nonzero(zone[y])[0]
            if len(xs) >= 2:
                edge[y, xs.min()] = True
                edge[y, xs.max()] = True
        res[bad & edge, :3] = TRUNK_LINE
        reddish = bad & ~edge & (rr > gg + 10) & (rr > bb + 10)
        res[reddish, :3] = TRUNK_SHADE
        res[bad & ~edge & ~reddish, :3] = TRIM
    # Final hip scrub AFTER solidify (which can re-bleed peach stubs). Convert
    # mid-tone peach beside the gold waistband into trunk red so the
    # hanging-arm check stays clean. Match the consistency checker's gold
    # waistband scan (pad+70..pad+84) so ¾-view narrow bands aren't missed.
    rr0 = res[..., 0].astype(np.float64)
    gg0 = res[..., 1].astype(np.float64)
    bb0 = res[..., 2].astype(np.float64)
    al0 = res[..., 3]
    gold0 = (al0 >= 128) & (rr0 > 180) & (gg0 > 140) & (bb0 < 140) & (rr0 - bb0 > 60)
    wb_lo = wb_hi = wb_y = None
    # Prefer the same Y window the checker uses (baseline pad ≈ PAD_TOP).
    scan_lo = max(PAD_TOP + 70, 0)
    scan_hi = min(PAD_TOP + 84, h)
    for y in range(scan_lo, scan_hi):
        xs = np.nonzero(gold0[y])[0]
        if len(xs) >= 8:
            wb_lo, wb_hi, wb_y = int(xs.min()), int(xs.max()), y
            break
    if wb_lo is None:
        for y in range(max(int(waist) - 2, 0), min(int(waist) + 5, h)):
            xs = np.nonzero(gold0[y])[0]
            if len(xs) >= 8:
                wb_lo, wb_hi, wb_y = int(xs.min()), int(xs.max()), y
                break
    if wb_lo is not None:
        y_top = max(int(wb_y) - 4, 0)
        y_bot = min(int(wb_y) + 12, h)
        keep_lo = max(wb_lo - 2, 0)
        keep_hi = min(wb_hi + 2, w - 1)
        for y in range(y_top, y_bot):
            peach = (
                (al0[y] >= 100) & (rr0[y] > 115) & (rr0[y] > bb0[y] + 12)
                & (rr0[y] > gg0[y] + 4) & (gg0[y] > 50) & (bb0[y] > 35)
                & ((rr0[y] + gg0[y] + bb0[y]) / 3.0 < 210)
            )
            line = (
                (al0[y] >= 100) & (rr0[y] < 90) & (gg0[y] < 60) & (bb0[y] < 50)
                & (rr0[y] >= gg0[y]) & (rr0[y] >= bb0[y])
            )
            # Skip saturated glove red
            peach &= ~((rr0[y] > 160) & (rr0[y] - gg0[y] > 70) & (gg0[y] < 110))
            kill = peach | line
            kill[keep_lo: keep_hi + 1] = False
            if kill.any():
                res[y, kill, :3] = TRUNK
                res[y, kill, 3] = 255
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
