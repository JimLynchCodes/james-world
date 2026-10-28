#!/usr/bin/env python3
"""Build the "Boxer James" sprite sheet (public/assets/kid_boxer.png/json)
from the base kid sheet.

Composite onto James's real base frame (do NOT redraw the body):

  * James's face, head, neck, torso silhouette, arms, and legs stay the base;
  * tee → bare chest with light pec/abs shading on his real skin tone;
  * navy shorts → shiny red boxing trunks with a gold/white waistband that
    sits ON the hips (same width as the torso), gold side trim, mid-thigh;
  * shoes → red / white / gold high-tops with laces (same footprint);
  * glossy RED boxing gloves (~½ head width) with white cuffs. Idle / walk /
    breathe / run: high-ish guard at chest/shoulder height so the whole face
    stays visible; side views show the near glove only;
  * tag is a 6-frame JAB: near arm strips, then a shaded James-thick arm with
    a big glove snaps forward and retracts. Far glove stays in guard.
    NW mirrors NE.

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


def recolor(f, g):
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

    # --- chest: paint shirt as James's own skin, then pec/abs ---
    sk_src = skin & (yy > g.neck + 2) & (yy < waist)
    if sk_src.any():
        px = f[sk_src][:, :3].astype(float)
        px = px[px.sum(1) >= np.percentile(px.sum(1), 45)]
        base_skin = np.median(px, 0) if len(px) else np.array([220.0, 160.0, 120.0])
    else:
        base_skin = np.array([220.0, 160.0, 120.0])
    if shirt.any():
        ref = np.percentile(lum[shirt], 75) or 1.0
        k = np.clip(0.88 + 0.18 * lum[shirt] / ref, 0.86, 1.05)
        out[shirt, :3] = base_skin[None] * k[:, None]
    torso = (shirt | (skin & (yy > g.neck + 3) & (yy < waist))) & a & ~head
    if torso.any():
        cx = g.head_cx
        for sx in (-4.5, 4.5):
            d2 = ((xx + 0.5 - (cx + sx)) ** 2) / 20.0 + ((yy + 0.5 - (g.neck + 9.0)) ** 2) / 10.0
            pec = torso & (d2 < 1.0) & (yy > g.neck + 4) & (yy < g.neck + 15)
            out[pec, :3] *= 0.86
        mid = torso & (np.abs(xx + 0.5 - cx) < 3.4) & (yy > g.neck + 14) & (yy < waist - 1)
        for by in (g.neck + 16, g.neck + 21, g.neck + 26):
            band = mid & (np.abs(yy - by) <= 1)
            out[band, :3] *= 0.82
        crease = mid & (np.abs(xx + 0.5 - cx) < 0.85)
        out[crease, :3] *= 0.84
        for sx in (-1, 1):
            side = torso & ((xx + 0.5 - cx) * sx > 5.0) & ((xx + 0.5 - cx) * sx < 9.0)
            side &= (yy > g.neck + 10) & (yy < waist - 2)
            out[side, :3] *= 0.90

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
    if direction in PROFILE:
        return (g.head_cx - PROFILE[direction] * 0.3, g.neck + 4.5)
    return (g.head_cx + (side or 1) * 7.2, g.neck + 4.5)


def guard_hand(sh, direction, side, bounce=0.0, gr=8.0):
    """Mid-chest / upper-rib guard — whole face + chin stay clear."""
    if direction in PROFILE:
        fx = PROFILE[direction]
        return (sh[0] + fx * (6.5 + gr * 0.1), sh[1] + 11.0 + bounce)
    out = (side or 1) * (8.0 + gr * 0.05)
    return (sh[0] + out * 0.85, sh[1] + 11.0 + bounce)


JAB_REACH = [10.0, 14.5, 20.0, 25.0, 16.5, 11.0]
JAB_ANG = {
    "profile": [-48, -28, -8, 4, -16, -42],
    "front":   [-60, -38, -14, 0, -20, -54],
    "back":    [-95, -72, -44, -18, -50, -88],
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
    ex, ey = hand[0] - elbow[0], hand[1] - elbow[1]
    en = math.hypot(ex, ey) or 1.0
    ux, uy = ex / en, ey / en
    cuff_c = (hand[0] - ux * (gr + 2.2), hand[1] - uy * (gr + 2.2))
    wrist = (hand[0] - ux * (gr * 0.55), hand[1] - uy * (gr * 0.55))
    hi = (hand[0] - gr * 0.28, hand[1] - gr * 0.32)
    spec = (hand[0] - gr * 0.38, hand[1] - gr * 0.42)
    shade = (hand[0] + gr * 0.22, hand[1] + gr * 0.28)
    # Thumb bump: top-inner of the fist (toward shoulder / body center, above midline).
    inward_x = 1.0 if sh[0] >= hand[0] else -1.0
    # Slight mix with arm-perpendicular so jabbing gloves still read.
    nx, ny = -uy, ux
    if nx * (sh[0] - hand[0]) + ny * (sh[1] - hand[1]) < 0:
        nx, ny = -nx, -ny
    nx = 0.55 * nx + 0.45 * inward_x
    ny = 0.35 * ny - 0.75  # strong upward bias (y+ is down)
    nn = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nn, ny / nn
    tr = max(3.0, gr * 0.52)
    thumb = (hand[0] + nx * (gr * 1.05), hand[1] + ny * (gr * 1.00))
    thumb_shade = (thumb[0] + nx * 0.6 + ux * 0.2, thumb[1] + ny * 0.6 + uy * 0.2)
    thumb_hi = (thumb[0] - nx * 0.55 - 0.15, thumb[1] - ny * 0.55 - 0.35)
    seam_a = (hand[0] + nx * (gr * 0.42), hand[1] + ny * (gr * 0.28))
    seam_b = (thumb[0] - nx * (tr * 0.25), thumb[1] - ny * (tr * 0.25))
    if jabbing:
        u0, u1, f0, f1 = 5.0, 4.5, 4.3, 3.8
    else:
        u0, u1, f0, f1 = 4.4, 3.9, 3.7, 3.3
    skin2 = tuple(int(v * 0.86) for v in skin)
    return [
        (capsule_fn(sh, u0, elbow, u1), skin),
        (capsule_fn(sh, u0 * 0.55, elbow, u1 * 0.55), skin2),
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


def draw_arm(size, sh, hand, skin, gr, jabbing=False):
    L1, L2 = 9.0, 8.5
    e1 = ik(sh, hand, L1, L2, 1)
    e2 = ik(sh, hand, L1, L2, -1)
    if jabbing:
        def off(e):
            dx, dy = hand[0] - sh[0], hand[1] - sh[1]
            lx = math.hypot(dx, dy) or 1.0
            return abs((hand[0] - sh[0]) * (sh[1] - e[1]) - (sh[0] - e[0]) * (hand[1] - sh[1])) / lx
        elbow = e1 if off(e1) < off(e2) else e2
        t = 0.45
        mid = (sh[0] + (hand[0] - sh[0]) * t, sh[1] + (hand[1] - sh[1]) * t)
        elbow = (elbow[0] * 0.35 + mid[0] * 0.65, elbow[1] * 0.35 + mid[1] * 0.65)
    else:
        # prefer elbow that hangs a bit below for a natural guard
        elbow = e1 if e1[1] >= e2[1] else e2
    return shapes_layer(size, glove_parts(sh, elbow, hand, skin, gr, jabbing), ARM_LINE, 1.0)


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
    return 1.0 * math.sin(k * math.pi / 2.0)


def trim_lateral_arms(f, g, sides):
    """Erase only hanging-arm pixels that stick OUTSIDE the torso silhouette.
    Never touch the torso core, shorts, or legs — James's body stays intact."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = f.copy()
    ai = alpha_mask(out)
    face = (yy <= g.neck + 1) & skin_mask(out)
    arms, _ = arms_and_hands(out, g, face)
    rm = np.zeros_like(arms)
    for s in sides:
        rm |= arm_comps_on(arms, g, 'S', s)  # side filter only; direction unused for L/R
    # Build per-row torso x-span from opaque non-arm rows near mid-torso, then
    # erase arm pixels outside that span (true hanging arms / hands only).
    L = np.full(h, np.nan)
    R = np.full(h, np.nan)
    for y in range(int(g.neck) + 4, int(g.hem) - 1):
        xs = np.nonzero(ai[y] & ~arms[y])[0]
        if len(xs) < 4:
            xs = np.nonzero(ai[y])[0]
        if len(xs) >= 4:
            L[y] = xs.min() + 1
            R[y] = xs.max() - 1
    ys = np.arange(h)
    for E in (L, R):
        ok = ~np.isnan(E)
        if ok.sum() >= 2:
            E[:] = np.interp(ys, ys[ok], E[ok])
    lateral = np.zeros_like(ai)
    for y in range(int(g.neck) + 3, int(g.hem)):
        if np.isnan(L[y]) or np.isnan(R[y]):
            continue
        lo, hi = int(round(L[y])), int(round(R[y]))
        row = arms[y].copy()
        row[lo:hi + 1] = False  # keep torso core
        lateral[y] |= row
    # also drop any leftover hand blobs below mid-torso that sit outside hips
    lateral |= rm & ((xx < np.nanmin(L)) | (xx > np.nanmax(R)))
    lateral &= yy < int(g.hem) - 1
    lateral &= yy > int(g.neck) + 2
    out[lateral] = 0
    return out


def boxify(frame, direction, anim, col, meta):
    """Composite Boxer onto James: recolor tee/shorts/shoes in place, trim only
    lateral hanging arms, then draw guard/jab gloves. Body is never redrawn."""
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

    # 1) Recolor James in place FIRST (tee→chest, navy→trunks+gold waistband,
    #    shoes→high-tops). Legs, face, silhouette stay his.
    if tag:
        idle = pad_frame(meta["_base_idle"][direction])
        gi = Geometry(idle)
        body = idle
        g = gi
    else:
        body = f

    rc, waist = recolor(body, g)
    g = Geometry(rc)

    # 2) Trim only lateral hanging arms (outside torso). Core body untouched.
    sides = [side] if (tag or direction in PROFILE) else [1, -1]
    rc = trim_lateral_arms(rc, g, sides)
    g = Geometry(rc)

    skin = skin_rgb_of(rc)
    gr = glove_radius(g)
    out = premul(rc, np.ones((h, w)))

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
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 30:
                res[c] = 0
    res = solidify(res, (int(g.neck), int(g.hem) - 1))
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
