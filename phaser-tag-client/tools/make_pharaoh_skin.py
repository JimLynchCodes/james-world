#!/usr/bin/env python3
"""Build the "Pharaoh James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_pharaoh.png + kid_pharaoh.json

Same columns, rows and animation ranges as kid.png. Frames are padded
(PAD_SIDE each side for the cape flare, PAD_TOP for the nemes crown), so
the frame size and feet line differ from James (see src/skins.ts).

Costume pixels are hard-edged (no supersampled haze) so the black-and-gold
read at game zoom. Every frame keeps the kid's own motion:
  1. sleeveless black tunic, black shendyt with a gold hem and front sash;
  2. bare upper arms, solid gold forearm gauntlets, bare hands;
  3. black gladiator sandals — straps and round gold studs up the calf;
  4. a pale champagne cape to the calves, behind the body (it covers the
     back). Dark outline and a 2px gold trim;
  5. striped nemes over the hair and ears, two lappets on the shoulders,
     James's face (eyes and all) put back in the opening. Back views are
     all headdress;
  6. wide black collar with a gold rim, gold belt, jeweled eagle, pyramid
     pendant.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_pharaoh_skin.py [--preview /tmp/pharaoh_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from make_banana_skin import (  # shared frame analysis helpers
    Geometry,
    alpha_mask,
    arms_and_hands,
    components8,
    fill_holes,
    grow,
    loose_skin,
    skin_mask,
)
from make_tuxedo_skin import close_streaks, lum

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 6
PAD_SIDE = 12

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW", "N", "NE"}
FACING = {"E": 1.0, "SE": 0.65, "S": 0.0, "SW": -0.65, "W": -1.0, "NW": -0.55, "N": 0.0, "NE": 0.55}

C = lambda *v: np.array(v, dtype=np.uint8)  # noqa: E731
NEMES = C(12, 10, 14)
NEMES_EDGE = C(4, 3, 6)
GOLD = C(228, 176, 42)
GOLD_BRIGHT = C(255, 214, 86)
GOLD_DARK = C(140, 92, 22)
CAPE = C(236, 208, 148)
CAPE_SHADE = C(196, 158, 96)
CAPE_EDGE = C(96, 62, 22)
BLACK = C(16, 14, 18)
RED = C(200, 36, 42)
RED_DARK = C(130, 16, 24)
SANDAL = C(22, 18, 16)


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g
    return m


def erode(mask: np.ndarray, r: int) -> np.ndarray:
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] &= m[:-1]
        g[:-1] &= m[1:]
        g[:, 1:] &= m[:, :-1]
        g[:, :-1] &= m[:, 1:]
        m = g
    return m


def stamp(img: np.ndarray, mask: np.ndarray, colour) -> None:
    img[mask, :3] = colour
    img[mask, 3] = 255


def ellipse(yy, xx, cx, cy, rx, ry) -> np.ndarray:
    return ((xx - cx) / max(rx, 0.4)) ** 2 + ((yy - cy) / max(ry, 0.4)) ** 2 <= 1.0


def face_window(f: np.ndarray, g: Geometry, direction: str):
    """Ellipse of James's face, or None on back views. Inset past the ears."""
    if direction in BACK:
        return None
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    face = (yy <= g.neck + 1) & skin_mask(f)
    ys, xs = np.nonzero(face)
    if len(xs) < 40:
        return None
    if direction in PROFILE:
        s = PROFILE[direction]
        cx = float(np.median(xs)) + s * 1.2
        cy = float(np.percentile(ys, 55))
        rx = max(6.5, (np.percentile(xs, 88) - np.percentile(xs, 22)) / 2)
        ry = max(7.0, (np.percentile(ys, 92) - np.percentile(ys, 30)) / 2)
        brow = g.top + 14
        if cy - ry < brow:
            ry = max(6.0, cy - brow)
    else:
        cx = float(np.median(xs)) + FRONT[direction] * 0.8
        cy = float(np.percentile(ys, 52)) + 0.4
        rx = max(8.0, (np.percentile(xs, 82) - np.percentile(xs, 18)) / 2)
        ry = max(8.5, (np.percentile(ys, 94) - np.percentile(ys, 12)) / 2)
    return cx, cy, float(rx), float(ry)


def opening_mask(shape, g: Geometry, direction: str, window) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    if window is None:
        return np.zeros((h, w), dtype=bool)
    opening = ellipse(yy + 0.0, xx + 0.0, *window)
    opening &= yy >= g.top + (12 if direction in PROFILE else 9)
    return opening


def phase_sway(anim: str, col: int) -> float:
    if anim == "walk":
        return math.sin(((col - 4) % 8) / 8.0 * math.tau) * 3.0
    if anim == "run":
        return math.sin(((col - 22) % 8) / 8.0 * math.tau) * 4.5
    return 0.0


def torso_span(torso: np.ndarray, y0: int, y1: int):
    h = torso.shape[0]
    y0 = max(0, min(h - 1, y0))
    y1 = max(y0 + 1, min(h, y1))
    xs = np.nonzero(torso[y0:y1].any(axis=0))[0]
    if len(xs) < 2:
        return None
    return float(xs.min()), float(xs.max())


def cape_mask(g: Geometry, torso: np.ndarray, direction: str, sway: float) -> np.ndarray:
    """Hard-edged cape from the shoulders to the calves."""
    h, w = torso.shape
    shoulder = torso_span(torso, g.neck + 1, g.neck + 8)
    hip = torso_span(torso, max(0, g.hem - 12), max(1, g.hem - 2))
    if shoulder is None:
        shoulder = (g.head_cx - g.head_hw * 0.65, g.head_cx + g.head_hw * 0.65)
    if hip is None:
        hip = shoulder
    y0 = int(g.neck + 2)
    y1 = int(min(h - 2, g.hem + 7))
    mask = np.zeros((h, w), dtype=bool)
    face = FACING[direction]
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, y1 - y0)
        scx = (shoulder[0] + shoulder[1]) / 2
        hcx = (hip[0] + hip[1]) / 2
        cx = scx * (1 - t) + hcx * t
        cx += -face * (2.0 + 8.0 * t) + sway * t
        half_s = (shoulder[1] - shoulder[0]) / 2 + 4.0
        half_b = (hip[1] - hip[0]) / 2 + (8.0 if direction in BACK or direction in PROFILE else 10.0)
        if direction in PROFILE:
            half_s = max(6.0, half_s * 0.7)
            half_b = max(12.0, (hip[1] - hip[0]) / 2 + 6.0)
        half = half_s * (1 - t) + half_b * t
        x0 = int(round(cx - half))
        x1 = int(round(cx + half))
        x0 = max(0, x0)
        x1 = min(w - 1, x1)
        if x1 > x0:
            mask[y, x0:x1 + 1] = True
    # hem dips a couple of pixels in the middle
    if y1 + 1 < h and mask[y1].any():
        xs = np.nonzero(mask[y1])[0]
        mid = (float(xs.min()) + float(xs.max())) / 2
        half = max(1.0, (float(xs.max()) - float(xs.min())) / 2)
        for dy in range(1, 4):
            span = half * (1 - dy / 4.0)
            x0 = int(round(mid - span))
            x1 = int(round(mid + span))
            mask[min(h - 1, y1 + dy), max(0, x0):min(w, x1 + 1)] = True
    return mask


def paint_cape(img: np.ndarray, mask: np.ndarray) -> None:
    if not mask.any():
        return
    edge = mask & ~erode(mask, 1)
    inner = erode(mask, 1) & ~erode(mask, 3)  # 2px gold trim
    body = mask & ~edge & ~inner
    stamp(img, body, CAPE)
    # a darker fold just off centre so the cloth isn't one flat patch
    h, w = mask.shape
    ys, xs = np.nonzero(body)
    if len(xs):
        cx = int(np.median(xs))
        fold = np.zeros_like(mask)
        fold[:, max(0, cx - 1):min(w, cx + 1)] = True
        stamp(img, body & fold, CAPE_SHADE)
    stamp(img, inner, GOLD)
    # top pixel of the trim catches light
    lip = inner & ~np.pad(inner, ((1, 0), (0, 0)))[:-1]
    stamp(img, lip, GOLD_BRIGHT)
    stamp(img, edge, CAPE_EDGE)


def paint_collar(img: np.ndarray, g: Geometry, direction: str, opening: np.ndarray) -> np.ndarray:
    """Wide black collar, 2px gold rim. Returns the collar mask."""
    h, w = opening.shape
    yy, xx = np.mgrid[0:h, 0:w]
    face = FACING[direction]
    cx = g.head_cx + face * (3.0 if direction in PROFILE else g.head_hw * 0.08)
    cy = float(g.neck + (5 if direction in BACK else 7))
    if direction in PROFILE:
        rx, ry = g.head_hw * 0.72, 6.5
    elif direction in BACK:
        rx, ry = g.head_hw * 0.92, 6.0
    else:
        rx, ry = g.head_hw * 0.98, 7.6
    outer = ellipse(yy + 0.0, xx + 0.0, cx, cy, rx, ry)
    inner = ellipse(yy + 0.0, xx + 0.0, cx, cy - 0.4, rx * 0.55, max(ry * 0.42, 2.0))
    band = outer & ~inner & (yy >= g.neck) & (yy < g.neck + 13) & ~opening
    rim = band & ~ellipse(yy + 0.0, xx + 0.0, cx, cy, max(rx - 2.2, 1.0), max(ry - 1.8, 1.0))
    stamp(img, band & ~rim, BLACK)
    stamp(img, rim, GOLD)
    stamp(img, rim & (yy <= cy), GOLD_BRIGHT)
    return band


def nemes_cloth(f: np.ndarray, g: Geometry, direction: str, opening: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Striped crown (stops at the jaw) plus two separate lappets."""
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = alpha_mask(f)
    head = a & (yy <= g.neck + 1) & (yy >= g.top - 1)
    cloth = dilate(head, 2)
    xs = np.nonzero((head & (yy < g.top + 8)).any(axis=0))[0]
    if len(xs):
        mid = (float(xs.min()) + float(xs.max())) / 2
        half = (float(xs.max()) - float(xs.min())) / 2 + 2.0
        dome = ellipse(yy + 0.0, xx + 0.0, mid, g.top + 1.0, half, 6.5)
        dome &= (yy >= g.top - 4) & (yy <= g.top + 6)
        cloth |= dome
    # crown ends at the jaw so it doesn't become a gold bib
    if opening.any():
        jaw = int(np.nonzero(opening)[0].max()) + 1
    else:
        jaw = g.neck + 1
    cloth &= yy <= jaw
    cloth &= ~opening

    # lappets: narrow striped panels, a clear gap between them
    lappets = np.zeros((h, w), dtype=bool)
    y0 = max(0, jaw - 2)
    y1 = min(h - 1, g.neck + 16)
    if direction in PROFILE:
        s = PROFILE[direction]
        centers = [g.head_cx + s * g.head_hw * 0.22]
        width = 5.0
    elif opening.any():
        oys, oxs = np.nonzero(opening)
        left, right = float(oxs.min()), float(oxs.max())
        centers = [left - 3.2, right + 3.2]
        width = 5.2
    else:
        centers = [g.head_cx - g.head_hw * 0.58, g.head_cx + g.head_hw * 0.58]
        width = 5.4
    for i, cx0 in enumerate(centers):
        sign = -1 if i == 0 and len(centers) == 2 else 1
        for y in range(y0, y1 + 1):
            t = (y - y0) / max(1, y1 - y0)
            cx = cx0 + sign * 1.6 * t
            half = width * (1 - 0.15 * t) / 2
            x0 = int(round(cx - half))
            x1 = int(round(cx + half))
            lappets[y, max(0, x0):min(w, x1 + 1)] = True
    lappets &= ~opening
    # ears (face skin outside the window) stay under the cloth
    face_skin = (yy <= g.neck + 1) & skin_mask(f)
    cloth |= face_skin & ~opening & (yy <= jaw)
    return cloth, lappets


def paint_stripes(img: np.ndarray, mask: np.ndarray, g: Geometry) -> None:
    if not mask.any():
        return
    yy = np.arange(img.shape[0])[:, None]
    rel = yy - (g.top - 4)
    stripe = np.broadcast_to((rel % 5) <= 1, mask.shape)
    stamp(img, mask & ~stripe, NEMES)
    stamp(img, mask & stripe, GOLD)
    lip = (mask & stripe) & ~np.pad(mask & stripe, ((1, 0), (0, 0)))[:-1]
    stamp(img, lip, GOLD_BRIGHT)
    edge = mask & ~erode(mask, 1)
    stamp(img, edge & ~stripe, NEMES_EDGE)
    stamp(img, edge & stripe, GOLD_DARK)


def gauntlet_mask(arms: np.ndarray, hands: np.ndarray, g: Geometry) -> np.ndarray:
    out = np.zeros_like(arms)
    sx, sy = g.head_cx, float(g.neck + 5)
    for comp in components8(arms & ~hands):
        if comp.sum() < 8:
            continue
        ys, xs = np.nonzero(comp)
        d = np.hypot(xs - sx, (ys - sy) * 0.85)
        if d.max() < 4:
            continue
        keep = d > np.quantile(d, 0.42)
        out[ys[keep], xs[keep]] = True
    return grow(out, arms, 1) & ~hands


def paint_sandals(img: np.ndarray, g: Geometry, shins: np.ndarray, shoes: np.ndarray) -> None:
    h, w = img.shape[:2]
    L = lum(img)
    shoe_col = np.clip(SANDAL.astype(np.float64) * (0.85 + 0.5 * np.clip((L - 40) / 140, 0, 1))[..., None], 0, 255)
    img[shoes, :3] = shoe_col[shoes].astype(np.uint8)
    img[shoes, 3] = 255
    region = (shins | shoes) & (img[..., 3] > 20)
    for comp in components8(region):
        if comp.sum() < 8:
            continue
        ys, xs = np.nonzero(comp)
        y0, y1 = int(ys.min()), int(ys.max())
        span = max(1, y1 - y0)
        bands = 4 if span >= 8 else 3
        for i in range(bands):
            y = min(h - 2, max(0, y0 + int(round((i + 0.45) * span / bands))))
            row = comp[y] | comp[min(h - 1, y + 1)]
            xb = np.nonzero(row)[0]
            if len(xb) < 2:
                continue
            x0, x1 = int(xb.min()), int(xb.max())
            for yy in (y, min(h - 1, y + 1)):
                sel = comp[yy, x0:x1 + 1]
                img[yy, x0:x1 + 1][sel, :3] = BLACK
                img[yy, x0:x1 + 1][sel, 3] = 255
            stud = x1 - 1 if x1 - x0 > 3 else (x0 + x1) // 2
            for dy in (0, 1):
                for dx in (0, 1):
                    yy, xx = min(h - 1, y + dy), min(w - 1, stud + dx)
                    if img[yy, xx, 3] > 20:
                        img[yy, xx, :3] = GOLD_BRIGHT if (dx, dy) == (0, 0) else GOLD
        if y1 - y0 >= 5:
            mx = int(np.median(xs))
            for y in range(y0 + 1, y1):
                if comp[y, mx]:
                    img[y, mx, :3] = BLACK
                    img[y, mx, 3] = 255


def paint_skirt_gold(img: np.ndarray, skirt: np.ndarray, g: Geometry, direction: str) -> None:
    h, w = skirt.shape
    yy, xx = np.mgrid[0:h, 0:w]
    hem = np.zeros_like(skirt)
    for y in range(g.hem - 2, g.hem + 1):
        if 0 <= y < h:
            hem[y] = skirt[y]
    stamp(img, hem, GOLD)
    stamp(img, hem & (yy == g.hem - 2), GOLD_BRIGHT)
    for y in range(max(0, g.hem - 10), min(h, g.hem)):
        xs = np.nonzero(skirt[y])[0]
        if len(xs) < 2:
            continue
        img[y, int(xs.min()), :3] = GOLD_DARK
        img[y, int(xs.max()), :3] = GOLD_DARK
    if direction in BACK:
        return
    cx = g.hip_cx + FACING[direction] * 2.0
    sash = skirt & (np.abs(xx + 0.5 - cx) <= 1.5) & (yy >= g.hem - 11) & (yy < g.hem - 1)
    stamp(img, sash, GOLD)
    edge = skirt & (np.abs(xx + 0.5 - cx) > 1.5) & (np.abs(xx + 0.5 - cx) <= 2.4) & (yy >= g.hem - 11)
    stamp(img, edge, GOLD_DARK)


def paint_belt_eagle(img: np.ndarray, g: Geometry, direction: str, chest: np.ndarray) -> None:
    if direction in BACK:
        return
    h, w = chest.shape
    waist = g.hem - 9
    for y in (waist - 1, waist, waist + 1):
        if not (0 <= y < h) or not chest[y].any():
            continue
        xs = np.nonzero(chest[y])[0]
        if len(xs) < 4:
            continue
        colour = GOLD_BRIGHT if y == waist - 1 else GOLD
        for x in range(int(xs.min()) + 1, int(xs.max())):
            if chest[y, x] or img[y, x, 3] > 20:
                img[y, x, :3] = colour
                img[y, x, 3] = 255
    if direction in PROFILE:
        return
    cx = int(round(g.hip_cx + FACING[direction] * 1.5))
    by = waist - 1
    for dx, dy, col in (
        (-6, 1, GOLD_DARK), (-5, 0, GOLD), (-4, 0, GOLD_BRIGHT), (-3, 0, GOLD),
        (-2, -1, GOLD_BRIGHT), (-1, -1, GOLD_BRIGHT), (0, -1, GOLD_BRIGHT),
        (1, -1, GOLD_BRIGHT), (2, -1, GOLD_BRIGHT),
        (3, 0, GOLD), (4, 0, GOLD_BRIGHT), (5, 0, GOLD), (6, 1, GOLD_DARK),
        (-4, 1, GOLD), (-3, 1, GOLD_DARK), (3, 1, GOLD_DARK), (4, 1, GOLD),
        (-1, 0, GOLD), (0, 0, GOLD), (1, 0, GOLD),
    ):
        x, y = cx + dx, by + dy
        if 0 <= y < h and 0 <= x < w and img[y, x, 3] > 0:
            img[y, x, :3] = col
    for dx in (-3, 0, 3):
        x, y = cx + dx, by
        if 0 <= y < h and 0 <= x < w:
            img[y, x, :3] = RED
            img[y, x, 3] = 255
            if y + 1 < h:
                img[y + 1, x, :3] = RED_DARK


def paint_pendant(img: np.ndarray, g: Geometry, direction: str, opening: np.ndarray) -> None:
    if direction in BACK or direction in PROFILE:
        return
    h, w = img.shape[:2]
    cx = int(round(g.head_cx + FACING[direction] * 1.2))
    y0 = g.neck + 12
    for y in range(y0, y0 + 4):
        for dx in (0,):
            x = cx + dx
            if 0 <= y < h and 0 <= x < w and not opening[y, x]:
                img[y, x, :3] = GOLD
                img[y, x, 3] = 255
                if 0 <= x + 1 < w and not opening[y, x + 1]:
                    img[y, x + 1, :3] = GOLD_DARK
                    img[y, x + 1, 3] = 255
    apex = y0 + 4
    for i, half in enumerate((0, 1, 2)):
        y = apex + i
        for x in range(cx - half, cx + half + 1):
            if 0 <= y < h and 0 <= x < w and not opening[y, x]:
                img[y, x, :3] = GOLD_BRIGHT if abs(x - cx) < half else GOLD
                img[y, x, 3] = 255
    y, x = apex + 1, cx
    if 0 <= y < h and 0 <= x < w:
        img[y, x, :3] = RED


def pharaohify(frame: np.ndarray, direction: str, anim: str, col: int) -> np.ndarray:
    f = pad_frame(frame)
    if not alpha_mask(f).any():
        return f
    g = Geometry(f)
    f = close_streaks(f, g.neck + 2)
    a = alpha_mask(f)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    L = lum(f)

    window = face_window(f, g, direction)
    opening = opening_mask((h, w), g, direction, window)
    # eyes and mouth sit in holes of the skin mask: fill those, clipped to the ellipse
    face_skin = (yy <= g.neck + 1) & skin_mask(f)
    # eyes and mouth are holes in the skin mask; keep them inside the window
    holes = fill_holes(dilate(face_skin, 1)) & ~face_skin & (yy <= g.neck + 1)
    opening = opening | (holes & dilate(opening, 1))

    face = face_skin
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & arms, 1)
    sk = loose_skin(f)
    outline = a & (L < 40)

    waist = g.hem - 9
    clothes = a & (yy > g.neck) & ~sk & ~outline & ~arms
    tunic = clothes & (yy <= waist)
    skirt = clothes & (yy > waist) & (yy <= g.hem)
    shins = a & sk & (yy >= g.hem) & (yy < g.hem + 6) & ~arms
    shoes = a & (yy >= g.hem + 2) & ~sk & ~arms & ~hands

    img = f.copy()
    # tunic / skirt, keeping a hint of the original shade so folds survive
    for mask, base in ((tunic, 20.0), (skirt, 26.0)):
        if not mask.any():
            continue
        v = base + 0.10 * L
        img[mask, 0] = np.clip(v[mask], 0, 255).astype(np.uint8)
        img[mask, 1] = np.clip(v[mask] - 1, 0, 255).astype(np.uint8)
        img[mask, 2] = np.clip(v[mask] + 2, 0, 255).astype(np.uint8)
        img[mask, 3] = 255
    specks = outline & (yy > g.neck + 1) & ~hands & ~face & (yy < g.hem + 2)
    stamp(img, specks, NEMES_EDGE)

    # green motion-blur on the run frames
    fr = f[..., :3].astype(np.int32)
    greenish = (fr[..., 1] > fr[..., 0] + 12) & (fr[..., 1] > fr[..., 2])
    blur = (yy > g.neck + 1) & ~hands & ~face & greenish & a & ~sk
    stamp(img, blur, BLACK)

    gaunt = gauntlet_mask(arms, hands, g)
    stamp(img, gaunt, GOLD)
    lip = gaunt & ~np.pad(gaunt, ((1, 0), (0, 0)), constant_values=False)[:-1]
    stamp(img, lip, GOLD_BRIGHT)
    stamp(img, gaunt & outline, GOLD_DARK)

    paint_sandals(img, g, shins, shoes)
    paint_skirt_gold(img, skirt, g, direction)

    # solidify see-through specks inside the body
    al = img[..., 3]
    solid = al > 200
    nb = np.zeros(al.shape, dtype=np.int32)
    nb[1:] += solid[:-1]
    nb[:-1] += solid[1:]
    nb[:, 1:] += solid[:, :-1]
    nb[:, :-1] += solid[:, 1:]
    pin = (al > 0) & ~solid & (nb >= 3) & (yy > g.neck + 1)
    img[pin, 3] = 255

    # what must survive every layer: the original face window and the hands
    protect = (opening & (f[..., 3] > 0)) | (hands & (img[..., 3] > 0))
    saved = img.copy()
    saved[opening] = f[opening]  # original eyes, mouth, freckles — not recoloured neighbours

    cloth, lappets = nemes_cloth(img, g, direction, opening)
    cloth &= ~protect
    lappets &= ~protect & ~hands

    torso = a & ~arms & ~hands & (yy > g.neck) & (yy < g.hem)
    cape = cape_mask(g, torso, direction, phase_sway(anim, col))
    # cape stays behind the head, arms, hands and sandals
    cape &= ~cloth & ~lappets & ~protect & ~hands & ~arms & ~shoes
    cape &= yy < g.hem + 8

    # back: the cape covers the tunic and shendyt; arms, head and feet stay
    shown = img.copy()
    if direction in BACK:
        cover = (yy > g.neck + 1) & (yy < g.hem + 6) & ~arms & ~hands & ~protect & ~shoes
        shown[cover, 3] = 0

    if direction in BACK:
        paint_cape(shown, cape)
    else:
        # wings only: the body is already in `shown` and must stay in front
        paint_cape(shown, cape & (shown[..., 3] == 0))

    collar = paint_collar(shown, g, direction, opening)
    # nemes over the collar at the jaw, lappets over the shoulders
    paint_stripes(shown, cloth & ~protect, g)
    paint_stripes(shown, lappets & ~protect, g)
    # gold rim around the face opening
    if opening.any():
        rim = dilate(opening, 1) & ~opening & ~protect & (cloth | dilate(cloth, 1) | (yy <= g.neck))
        rim &= yy < g.neck + 2
        stamp(shown, rim & (shown[..., 3] > 0), GOLD)

    paint_belt_eagle(shown, g, direction, (tunic | skirt) & ~arms)
    paint_pendant(shown, g, direction, opening)
    # collar variable kept so a back-view collar isn't covered by the cape fold
    _ = collar

    # face, hands, gauntlets and sandals always win
    shown[protect] = saved[protect]
    stamp(shown, gaunt & ~protect, GOLD)
    stamp(shown, lip & ~protect, GOLD_BRIGHT)
    # sandals again so the cape hem can't swallow the straps
    paint_sandals(shown, g, shins & ~protect, shoes & ~protect)
    paint_skirt_gold(shown, skirt & (shown[..., 3] > 0) & ~protect, g, direction)
    paint_belt_eagle(shown, g, direction, (tunic | skirt) & ~protect)
    paint_pendant(shown, g, direction, opening)

    shown[shown[..., 3] < 8] = 0
    return shown


def anim_of(meta, c: int) -> str:
    for name, rng in meta["animations"].items():
        if rng["start"] <= c < rng["start"] + rng["count"]:
            return name
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    ofw, ofh = fw + 2 * PAD_SIDE, fh + PAD_TOP
    out = np.zeros((len(dirs) * ofh, cols * ofw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = pharaohify(
                fr, direction, anim_of(meta, c), c
            )
    Image.fromarray(out).save(ASSETS / "kid_pharaoh.png", optimize=True)
    pm = dict(meta)
    pm["image"] = "kid_pharaoh.png"
    pm["frameWidth"], pm["frameHeight"] = ofw, ofh
    pm["baselineY"] = meta["baselineY"] + PAD_TOP
    pm["anchorX"] = ofw // 2
    (ASSETS / "kid_pharaoh.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_pharaoh.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")

    idle = out[2 * ofh:3 * ofh, 0:ofw]
    ys = np.nonzero(idle[..., 3] > 20)[0]
    if len(ys):
        print(f"south idle opaque y {int(ys.min())}-{int(ys.max())}  above-feet {pm['baselineY'] - int(ys.min())}")

    if args.preview:
        from PIL import ImageDraw
        img = Image.fromarray(out)
        scale, pad = 3, 36
        picks = [0, 6, 13, 18, 20, 26]
        names = ["idle", "walk", "breathe", "tag", "tag", "run"]
        pv = Image.new("RGBA", (pad + len(picks) * ofw * scale, pad + len(dirs) * ofh * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (ofw, ofh), (118, 176, 112, 255) if (r + i) % 2 == 0 else (96, 158, 96, 255))
                cell.alpha_composite(img.crop((c * ofw, r * ofh, (c + 1) * ofw, (r + 1) * ofh)))
                pv.paste(cell.resize((ofw * scale, ofh * scale), Image.NEAREST),
                         (pad + i * ofw * scale, pad + r * ofh * scale))
            d.text((4, pad + r * ofh * scale + 8), dirs[r], fill="white")
        for i, name in enumerate(names):
            d.text((pad + i * ofw * scale + 4, 10), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
