#!/usr/bin/env python3
"""Build the "Gorilla James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_gorilla.png + kid_gorilla.json

Same columns, rows and animation ranges as kid.png. Frames are padded
(PAD_TOP for the rounded ears, PAD_SIDE for shaggy fur past the arms,
PAD_BOTTOM so a fur sole isn't clipped). The kid art stays on the same
feet line (baselineY shifts by PAD_TOP only), so idle / walk / breathe /
tag / run keep the kid's own motion in all 8 directions.

Per frame:
  1. everything but the face and the hands becomes a bulky black fur suit
     (long sleeves, leggings, hood) with a ragged tuft halo;
  2. a round hood with a dark rim frames the face on front and side views
     (back views are all fur) and two rounded ears sit on the hood;
  3. front and 3/4 views get a smooth molded muscle chest (pecs + abs)
     over the fur; profiles get the near pec;
  4. James's hands are put back on the ends of the sleeves (fur cuff at
     the wrist). Walk and run darken the fingertips and add knuckle pads
     so the swing reads a little more ape-like without moving the pose;
  5. sneakers become rounded gorilla feet with three toe nubs, planted
     on the same sole line.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_gorilla_skin.py [--preview /tmp/gorilla_preview.png]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from make_banana_skin import (  # shared frame analysis helpers
    Geometry,
    alpha_mask,
    arms_and_hands,
    components8,
    face_ellipse,
    grow,
)

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 12
PAD_SIDE = 10
PAD_BOTTOM = 3
SS = 3

# Outermost pixels of each arm that stay James's hand (the rest is sleeve).
HAND_REACH = 8

BACK = {"NW", "N", "NE"}
# How much of the molded chest shows, and which way it shifts (screen x).
CHEST = {
    "E": (0.62, 1.0),
    "SE": (0.92, 0.55),
    "S": (1.0, 0.0),
    "SW": (0.92, -0.55),
    "W": (0.62, -1.0),
}
# Toes point along the facing (screen x, y). Back views show the heel.
TOE_DIR = {
    "E": (1.0, 0.25),
    "SE": (0.65, 0.75),
    "S": (0.0, 1.0),
    "SW": (-0.65, 0.75),
    "W": (-1.0, 0.25),
    "NW": (-0.35, 0.15),
    "N": (0.0, 0.2),
    "NE": (0.35, 0.15),
}

C = lambda *v: np.array(v, dtype=np.float64)  # noqa: E731
FUR = C(34, 28, 32)
FUR_DARK = C(12, 9, 12)
FUR_MID = C(58, 50, 56)
FUR_TIP = C(104, 94, 100)
OUTLINE = C(6, 4, 8)
CHEST_COL = C(62, 54, 68)
CHEST_HI = C(186, 176, 196)
CHEST_LO = C(14, 11, 16)
EAR_IN = C(72, 46, 56)
EAR_IN_DARK = C(42, 26, 34)
KNUCKLE = C(120, 78, 58)
KNUCKLE_DARK = C(62, 38, 32)


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP + PAD_BOTTOM, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:PAD_TOP + fh, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        g[1:, 1:] |= m[:-1, :-1]
        g[1:, :-1] |= m[:-1, 1:]
        g[:-1, 1:] |= m[1:, :-1]
        g[:-1, :-1] |= m[1:, 1:]
        m = g
    return m


def erode(mask: np.ndarray) -> np.ndarray:
    m = mask.copy()
    m[1:] &= mask[:-1]
    m[:-1] &= mask[1:]
    m[:, 1:] &= mask[:, :-1]
    m[:, :-1] &= mask[:, 1:]
    return m


def hash01(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    n = (x.astype(np.int64) * 374761393 + y.astype(np.int64) * 668265263) & np.int64(0xFFFFFFFF)
    n = (n ^ (n >> 13)) * np.int64(1274126177) & np.int64(0xFFFFFFFF)
    return (n & 255).astype(np.float64) / 255.0


def anim_of(col: int) -> str:
    if col < 4:
        return "idle"
    if col < 12:
        return "walk"
    if col < 16:
        return "breathe"
    if col < 22:
        return "tag"
    return "run"


def ellipse_mask(shape, ell, scale_x=1.0, scale_y=1.0, dy=0.0) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    ex, ey, rx, ry = ell
    return np.hypot((xx + 0.5 - ex) / (rx * scale_x), (yy + 0.5 - (ey + dy)) / (ry * scale_y)) < 1.0


def full_hands(f: np.ndarray, g: Geometry, face: np.ndarray, arms: np.ndarray) -> np.ndarray:
    """More than the fingertip: the outer HAND_REACH px of each arm."""
    hands = np.zeros(f.shape[:2], dtype=bool)
    sx, sy = g.head_cx, g.neck + 4.0
    for comp in components8(arms):
        if comp.sum() < 8:
            continue
        ys, xs = np.nonzero(comp)
        dist = np.hypot(xs - sx, (ys - sy) * 0.85)
        far = dist >= dist.max() - HAND_REACH
        hands[ys[far], xs[far]] = True
    # drop anything that landed in the face opening
    return hands & ~face & alpha_mask(f)


def foot_components(f: np.ndarray, g: Geometry) -> list[np.ndarray]:
    a = alpha_mask(f)
    zone = np.zeros_like(a)
    y0 = max(0, g.bottom - 14)
    zone[y0:g.bottom + 1] = True
    xs = np.arange(f.shape[1])
    # keep the two shoes; ignore a dangling hand that swung down to the knees
    zone &= np.abs(xs[None, :] - g.hip_cx) < 22
    return [c for c in components8(a & zone) if c.sum() >= 8]


# --- supersampled layers -------------------------------------------------------
def render_layer(size, paint_fn) -> np.ndarray:
    h, w = size
    ys = (np.arange(h * SS) + 0.5) / SS
    xs = (np.arange(w * SS) + 0.5) / SS
    y, x = np.meshgrid(ys, xs, indexing="ij")
    col, alpha = paint_fn(y, x)
    col = np.clip(col, 0, 255) / 255.0
    layer = np.concatenate([col * alpha[..., None], alpha[..., None]], axis=-1)
    return layer.reshape(h, SS, w, SS, 4).mean(axis=(1, 3))


def premul(f: np.ndarray) -> np.ndarray:
    x = f.astype(np.float64) / 255.0
    x[..., :3] *= x[..., 3:4]
    return x


def over(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    return src + dst * (1.0 - src[..., 3:4])


def to_u8(x: np.ndarray) -> np.ndarray:
    out = x.copy()
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0.0)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


def fur_image(f: np.ndarray, g: Geometry, suit: np.ndarray, face: np.ndarray, hands: np.ndarray) -> np.ndarray:
    """Crisp pixel fur: luminance shading, clumps, a dark outline, tuft halo."""
    h, w = suit.shape
    lum = f[..., :3].astype(np.float64) @ np.array([0.3, 0.59, 0.11])
    body = alpha_mask(f)
    ys, xs = np.mgrid[0:h, 0:w]
    # body-relative clumps so the pattern rides with the kid instead of crawling
    qx = (xs - int(g.hip_cx)) // 2
    qy = (ys - int(g.top)) // 3
    hsh = hash01(qx, qy)
    shade = np.where(body, 0.62 + 0.5 * np.clip((lum - 25.0) / 170.0, 0.0, 1.0), 0.78)
    # pull bright sneakers / shirt highlights back down; fur isn't white
    shade = np.where(lum > 170, np.minimum(shade, 0.85), shade)
    speck = 0.72 + 0.55 * hsh
    col = FUR * (shade * speck)[..., None]
    # hanging highlight tufts (top of a clump catches the light)
    col = np.where((hsh > 0.84)[..., None], FUR_MID, col)
    col = np.where((hsh < 0.18)[..., None], FUR_DARK, col)
    edge = suit & ~erode(suit)
    col = np.where(edge[..., None], OUTLINE, col)
    alpha = suit.astype(np.uint8) * 255
    out = np.concatenate([np.clip(col, 0, 255), alpha[..., None]], axis=-1).astype(np.uint8)

    # ragged tufts just outside the suit, biased downward (fur hangs)
    halo = dilate(suit, 3) & ~suit & ~dilate(face, 1) & ~hands
    halo[g.bottom + 1:] = False
    oy, ox = np.nonzero(halo)
    if len(oy) == 0:
        return add_strands(out, suit, g, face, hands)
    # which ring
    d1 = dilate(suit, 1)
    d2 = dilate(suit, 2)
    keep = np.zeros(len(oy), dtype=bool)
    hh = hash01((ox - int(g.hip_cx)) // 2, (oy - int(g.top)) // 2)
    ring1 = d1[oy, ox]
    ring2 = d2[oy, ox] & ~ring1
    ring3 = ~d2[oy, ox]
    keep |= ring1 & (hh > 0.22)
    keep |= ring2 & (hh > 0.48)
    keep |= ring3 & (hh > 0.74)
    # extra long strands along the arms / hood (every few outline pixels)
    oy, ox, hh = oy[keep], ox[keep], hh[keep]
    if len(oy) == 0:
        return out
    tip = hh > 0.62
    dark = hh < 0.4
    rgb = np.where(tip[:, None], FUR_TIP, np.where(dark[:, None], FUR_DARK, FUR_MID))
    # don't paint tufts that would cover the face or a hand
    ok = ~face[oy, ox] & ~hands[oy, ox]
    out[oy[ok], ox[ok], :3] = rgb[ok]
    out[oy[ok], ox[ok], 3] = 255
    return add_strands(out, suit, g, face, hands)


def add_strands(out: np.ndarray, suit: np.ndarray, g: Geometry, face: np.ndarray, hands: np.ndarray) -> np.ndarray:
    """A few longer hairs off the silhouette so the suit reads as shaggy, not fuzzy."""
    outline = suit & ~erode(suit)
    ys, xs = np.nonzero(outline)
    if len(ys) == 0:
        return out
    sel = ((ys * 3 + xs * 5) % 6 == 0)
    ys, xs = ys[sel], xs[sel]
    h, w = suit.shape
    for y, x in zip(ys.tolist(), xs.tolist()):
        nx = ny = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                yy, xx = y + dy, x + dx
                if not (0 <= yy < h and 0 <= xx < w and suit[yy, xx]):
                    nx += dx
                    ny += dy
        # fur hangs; skip tufts aimed into the leg gap or the face
        ny += 0.45
        mag = (nx * nx + ny * ny) ** 0.5
        if mag < 0.5:
            continue
        nx, ny = nx / mag, ny / mag
        length = 3 + int(hash01(np.array([x - int(g.hip_cx)]), np.array([y - int(g.top)]))[0] * 3)
        for i in range(1, length + 1):
            px = int(round(x + nx * i))
            py = int(round(y + ny * i))
            if not (0 <= py < h and 0 <= px < w) or py > g.bottom:
                break
            if face[py, px] or hands[py, px] or suit[py, px]:
                break
            tone = FUR_TIP if i == length else FUR_MID
            out[py, px, :3] = tone
            out[py, px, 3] = 255
    return out


def ear_list(g: Geometry, direction: str) -> list[tuple[float, float, float]]:
    """(cx, cy, radius) of each visible ear. Ears sit above the hood so they
    break the silhouette instead of disappearing into the hair."""
    top = float(g.top)
    cx = g.head_cx
    span = min(max(g.head_hw * 0.58, 11.0), 14.0)
    if direction in ("E", "W"):
        # one ear up off the crown, toward the back of the head
        back = -1.0 if direction == "E" else 1.0
        return [(cx + back * 4.0, top - 5.0, 7.2)]
    if direction in BACK:
        return [
            (cx - span * 0.82, top - 3.0, 6.6),
            (cx + span * 0.82, top - 3.0, 6.6),
        ]
    # front / 3/4: both ears high on the corners, the near one larger
    side = {"SE": 1.0, "SW": -1.0}.get(direction, 0.0)
    ears = []
    for sign in (-1.0, 1.0):
        near = sign * side > 0
        r = 7.5 if near or side == 0 else 6.2
        ears.append((cx + sign * (span + 1.2), top - 3.2, r))
    return ears


def ears_layer(g: Geometry, direction: str, size) -> np.ndarray:
    ears = ear_list(g, direction)

    def paint(y, x):
        col = np.zeros((*y.shape, 3))
        alpha = np.zeros(y.shape)
        for ex, ey, rad in ears:
            e = np.hypot((x - ex) / rad, (y - ey) / (rad * 1.08))
            inside = e < 1.0
            light = np.exp(-((x - ex + rad * 0.28) / (rad * 0.55)) ** 2 - ((y - ey + rad * 0.32) / (rad * 0.5)) ** 2)
            c = FUR_DARK * (0.55 + 0.45 * e)[..., None] + FUR * (1 - e)[..., None]
            c = c * (1 - 0.65 * light[..., None]) + FUR_TIP * (0.65 * light[..., None])
            edge = inside & (e > 0.78)
            c = np.where(edge[..., None], OUTLINE, c)
            # inner ear
            ie = np.hypot((x - ex) / (rad * 0.48), (y - (ey + rad * 0.12)) / (rad * 0.55))
            inner = ie < 1.0
            c = np.where(inner[..., None], EAR_IN, c)
            c = np.where((inner & (ie > 0.72))[..., None], EAR_IN_DARK, c)
            col = np.where(inside[..., None], c, col)
            alpha = np.where(inside, 1.0, alpha)
        return col, alpha

    return render_layer(size, paint)


def chest_layer(g: Geometry, direction: str, size, suit: np.ndarray) -> np.ndarray:
    """Smooth molded pecs and abs, masked to the torso. Back views stay fur."""
    if direction in BACK or direction not in CHEST:
        return np.zeros((*size, 4), dtype=np.float64)
    strength, side = CHEST[direction]
    cx = g.hip_cx + side * 3.2
    pec_cy = float(g.neck + 6.5)
    ab_top = pec_cy + 6.4
    ab_bot = min(float(g.hem - 6), ab_top + 15.0)
    profile = abs(side) > 0.8
    on_body = dilate(suit, 1)

    def paint(y, x):
        col = np.zeros((*y.shape, 3))
        alpha = np.zeros(y.shape)

        def blob(px, py, rx, ry):
            e = ((x - px) / rx) ** 2 + ((y - py) / ry) ** 2
            inside = e < 1.0
            # tight specular on the upper-left of the pec, like molded plastic
            light = np.exp(
                -((x - px + rx * 0.18) / (rx * 0.32)) ** 2
                - ((y - py + ry * 0.42) / (ry * 0.28)) ** 2
            )
            form = np.clip(1.05 - e, 0, 1)
            base = CHEST_LO + (CHEST_COL - CHEST_LO) * form[..., None]
            c = base * (1 - light[..., None]) + CHEST_HI * light[..., None]
            edge = inside & (e > 0.84)
            c = np.where(edge[..., None], OUTLINE, c)
            return c, inside

        signs = ((-1.0, 0.2 if side > 0.8 else 1.0), (1.0, 0.2 if side < -0.8 else 1.0))
        for sign, scale in signs:
            if profile and sign != np.sign(side):
                continue
            px = cx + sign * (6.4 * (0.3 if profile else 1.0))
            rx = 7.0 * scale * (0.8 if profile else 1.0)
            ry = 5.6 * scale
            c, inside = blob(px, pec_cy, rx, ry)
            col = np.where(inside[..., None], c, col)
            alpha = np.where(inside, 1.0, alpha)
        if not profile:
            cleft = (np.abs(x - cx) < 1.25) & (np.abs(y - pec_cy) < 4.6) & (alpha > 0)
            col = np.where(cleft[..., None], CHEST_LO, col)

        if ab_bot - ab_top > 6:
            bands = 3
            ah = (ab_bot - ab_top) / bands
            half = (4.6 if profile else 7.6) * (0.55 + 0.45 * strength)
            ab_cx = cx + side * (2.2 if profile else 0.0)
            for i in range(bands):
                y0 = ab_top + i * ah
                y1 = y0 + ah - 0.85
                taper = 1.0 - 0.14 * i
                rx = half * taper
                cy = (y0 + y1) / 2.0
                ry = max((y1 - y0) / 2.0, 0.8)
                e = ((x - ab_cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                inside = e < 1.0
                # ridge: bright along the top, shadow in the crease below
                light = np.clip((cy + ry * 0.15 - y) / max(ry, 0.5), 0, 1)
                c = CHEST_LO + (CHEST_COL - CHEST_LO) * light[..., None]
                shine = light > 0.78
                c = np.where(shine[..., None], c * 0.35 + CHEST_HI * 0.65, c)
                edge = inside & (e > 0.82)
                c = np.where(edge[..., None], OUTLINE, c)
                seam = inside & (np.abs(x - ab_cx) < 0.65)
                c = np.where(seam[..., None], CHEST_LO, c)
                col = np.where(inside[..., None], c, col)
                alpha = np.where(inside, 1.0, alpha)
        alpha *= 0.5 + 0.5 * strength
        return col, alpha

    layer = render_layer(size, paint)
    # keep the plate on the torso; pecs shouldn't float beside the body
    layer[..., 3] *= on_body
    return layer


def feet_layer(f: np.ndarray, g: Geometry, direction: str, size) -> np.ndarray:
    """Rounded fur feet with three toe nubs, sole on the original ground line."""
    comps = foot_components(f, g)
    blobs = []
    for comp in comps:
        ys, xs = np.nonzero(comp)
        blobs.append((float(xs.mean()), float(ys.mean()), float(xs.max() - xs.min() + 1), float(ys.max() - ys.min() + 1)))
    tx, ty = TOE_DIR[direction]
    sole = float(g.bottom)

    def paint(y, x):
        col = np.zeros((*y.shape, 3))
        alpha = np.zeros(y.shape)
        for cx, cy, bw, bh in blobs:
            rx = max(4.2, bw * 0.55 + 1.2)
            ry = max(3.2, bh * 0.48 + 0.6)
            e = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            inside = (e < 1.0) & (y <= sole + 0.6)
            light = np.exp(-((x - cx) / (rx * 0.7)) ** 2 - ((y - cy + ry * 0.3) / (ry * 0.5)) ** 2)
            c = FUR_DARK * (0.4 + 0.6 * np.clip(e, 0, 1))[..., None] + FUR * 0.45
            c = c * (1 - 0.4 * light[..., None]) + FUR_MID * (0.4 * light[..., None])
            edge = inside & (e > 0.78)
            c = np.where(edge[..., None], OUTLINE, c)
            col = np.where(inside[..., None], c, col)
            alpha = np.where(inside, 1.0, alpha)
            # three toes at the front, bottoms resting on the sole
            for off in (-1.15, 0.0, 1.15):
                # perpendicular spread
                px, py = -ty, tx
                spread = off * (2.0 if abs(tx) > 0.4 else 1.7)
                ox = cx + tx * (rx * 0.72) + px * spread
                oy = min(sole - 1.1, cy + ty * (ry * 0.55) + py * spread * 0.3)
                te = ((x - ox) / 1.55) ** 2 + ((y - oy) / 1.35) ** 2
                toe = (te < 1.0) & (y <= sole + 0.6)
                tc = np.where((te > 0.65)[..., None], OUTLINE, FUR_DARK + (FUR_MID - FUR_DARK) * 0.35)
                col = np.where(toe[..., None], tc, col)
                alpha = np.where(toe, 1.0, alpha)
        return col, alpha

    return render_layer(size, paint)


def knuckle_layer(g: Geometry, hands: np.ndarray, size, strong: bool) -> np.ndarray:
    """Dark fingertip pads. Walk/run push them a little further out."""
    pads = []
    sx, sy = g.head_cx, g.neck + 6.0
    reach = 2.2 if strong else 1.1
    rad = 1.45 if strong else 1.15
    for comp in components8(hands):
        if comp.sum() < 6:
            continue
        ys, xs = np.nonzero(comp)
        dist = np.hypot(xs - sx, (ys - sy) * 0.8)
        tip_i = int(np.argmax(dist))
        tip = np.array([xs[tip_i], ys[tip_i]], dtype=np.float64)
        away = tip - np.array([xs.mean(), ys.mean()])
        norm = float(np.hypot(away[0], away[1])) or 1.0
        ux, uy = away[0] / norm, away[1] / norm
        px, py = -uy, ux
        for off in (-1.5, 0.0, 1.5):
            pads.append((tip[0] + ux * reach + px * off * 0.85, tip[1] + uy * reach + py * off * 0.85, rad))

    def paint(y, x):
        col = np.zeros((*y.shape, 3))
        alpha = np.zeros(y.shape)
        for cx, cy, r in pads:
            e = np.hypot((x - cx) / r, (y - cy) / (r * 0.82))
            inside = e < 1.0
            c = np.where((e > 0.62)[..., None], KNUCKLE_DARK, KNUCKLE)
            col = np.where(inside[..., None], c, col)
            alpha = np.where(inside, 0.92, alpha)
        return col, alpha

    if not pads:
        return np.zeros((*size, 4), dtype=np.float64)
    return render_layer(size, paint)


def suit_mask(f: np.ndarray, g: Geometry, face: np.ndarray, hands: np.ndarray) -> np.ndarray:
    """Body thickened into a fur suit, with the face hole and a gap between the legs."""
    body = alpha_mask(f)
    extra = dilate(body, 1) & ~body
    ys, xs = np.mgrid[0:body.shape[0], 0:body.shape[1]]
    gap = (np.abs(xs - g.hip_cx) <= 1.6) & (ys > g.hem + 1) & (ys < g.bottom - 4)
    extra &= ~gap
    extra &= ~dilate(hands, 2)
    extra &= ~dilate(face, 1)
    # no fur floating under the sole
    extra[g.bottom + 1:] = False
    suit = (body | extra) & ~face & ~hands
    return suit


def darken_fingertips(hand_rgba: np.ndarray, g: Geometry, hands: np.ndarray, strong: bool) -> np.ndarray:
    """Outer half of each hand shifts toward a darker pad; the wrist stays James."""
    out = hand_rgba.copy()
    sx, sy = g.head_cx, g.neck + 6.0
    amount = 0.55 if strong else 0.32
    for comp in components8(hands):
        ys, xs = np.nonzero(comp)
        if len(xs) < 4:
            continue
        dist = np.hypot(xs - sx, (ys - sy) * 0.8)
        d0, d1 = float(dist.min()), float(dist.max())
        t = (dist - d0) / max(1e-3, d1 - d0)
        # only the outer portion
        t = np.clip((t - 0.45) / 0.55, 0, 1) * amount
        pix = out[ys, xs, :3].astype(np.float64)
        target = KNUCKLE_DARK
        out[ys, xs, :3] = np.clip(pix * (1 - t[:, None]) + target * t[:, None], 0, 255)
    return out


def gorillaify(frame: np.ndarray, direction: str, col: int) -> np.ndarray:
    f = pad_frame(frame)
    if not alpha_mask(f).any():
        return f
    g = Geometry(f)
    ell = face_ellipse(f, g, direction)
    face = ellipse_mask(f.shape[:2], ell) if ell is not None else np.zeros(f.shape[:2], dtype=bool)
    arms, _tip = arms_and_hands(f, g, face)
    hands = full_hands(f, g, face, arms)
    strong = anim_of(col) in ("walk", "run")
    suit = suit_mask(f, g, face, hands)

    # face + hands stay; everything else is replaced by fur
    base = np.zeros_like(f)
    keep = face | hands
    base[keep] = f[keep]
    fur = fur_image(f, g, suit, face, hands)
    # wrist cuff: a lighter fur edge where the sleeve meets the hand
    cuff = dilate(hands, 2) & suit & ~hands
    fur[cuff, :3] = np.clip(FUR_MID, 0, 255).astype(np.uint8)
    fur[cuff, 3] = 255

    out = over(premul(base), premul(fur))
    size = f.shape[:2]
    # ears first (hood), then chest, then feet. hands and face go on last.
    out = over(out, ears_layer(g, direction, size))
    out = over(out, chest_layer(g, direction, size, suit))
    out = over(out, feet_layer(f, g, direction, size))

    # hands peeking out of the cuffs, fingertips a little more ape-like
    if hands.any():
        hand_px = np.zeros_like(f)
        hand_px[hands] = f[hands]
        hand_px = darken_fingertips(hand_px, g, hands, strong)
        out = over(out, premul(hand_px))
        out = over(out, knuckle_layer(g, hands, size, strong))

    # face rim: a dark fur ring so the hood opening reads, then James's face
    if face.any():
        rim = dilate(face, 2) & ~face
        rim_layer = np.zeros((*size, 4), dtype=np.float64)
        rim_col = (OUTLINE / 255.0)
        rim_layer[rim, :3] = rim_col
        rim_layer[rim, 3] = 1.0
        out = over(out, rim_layer)
        face_layer = premul(f) * face[..., None]
        out = over(out, face_layer)

    result = to_u8(out)
    result[result[..., 3] < 8] = 0
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet of every direction")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    out_fw = fw + 2 * PAD_SIDE
    out_fh = fh + PAD_TOP + PAD_BOTTOM
    out = np.zeros((len(dirs) * out_fh, cols * out_fw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            y0 = r * out_fh
            out[y0:y0 + out_fh, c * out_fw:(c + 1) * out_fw] = gorillaify(fr, direction, c)
    Image.fromarray(out).save(ASSETS / "kid_gorilla.png", optimize=True)
    gorilla_meta = dict(meta)
    gorilla_meta["image"] = "kid_gorilla.png"
    gorilla_meta["frameWidth"] = out_fw
    gorilla_meta["frameHeight"] = out_fh
    gorilla_meta["baselineY"] = meta["baselineY"] + PAD_TOP
    gorilla_meta["anchorX"] = out_fw // 2
    (ASSETS / "kid_gorilla.json").write_text(json.dumps(gorilla_meta, indent=2) + "\n")
    # art top of the south idle frame (ears), for skins.ts artHeight
    idle = out[dirs.index("S") * out_fh:(dirs.index("S") + 1) * out_fh, :out_fw]
    opaque = np.nonzero(idle[..., 3] > 16)[0]
    top = int(opaque.min()) if len(opaque) else 0
    base = gorilla_meta["baselineY"]
    print(
        f"wrote {ASSETS / 'kid_gorilla.png'} ({out.shape[1]}x{out.shape[0]}) "
        f"frames {out_fw}x{out_fh} baseline {base} artHeight {base - top}"
    )

    if args.preview:
        from PIL import ImageDraw
        img = Image.fromarray(out)
        sample_cols = [0, 7, 25, 19]
        labels = ["idle", "walk", "run", "tag"]
        scale, pad = 3, 46
        cell_w, cell_h = out_fw * scale, out_fh * scale
        pv = Image.new(
            "RGBA",
            (pad + len(sample_cols) * cell_w + 8, pad + len(dirs) * cell_h + 8),
            (40, 44, 48, 255),
        )
        draw = ImageDraw.Draw(pv)
        for r, direction in enumerate(dirs):
            for i, c in enumerate(sample_cols):
                bg = (168, 206, 232, 255) if (r + i) % 2 == 0 else (186, 214, 160, 255)
                cell = Image.new("RGBA", (out_fw, out_fh), bg)
                cell.alpha_composite(img.crop((c * out_fw, r * out_fh, (c + 1) * out_fw, (r + 1) * out_fh)))
                pv.paste(cell.resize((cell_w, cell_h), Image.NEAREST), (pad + i * cell_w, pad + r * cell_h))
            draw.text((4, pad + r * cell_h + 8), direction, fill="white")
        for i, name in enumerate(labels):
            draw.text((pad + i * cell_w + 4, 14), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
