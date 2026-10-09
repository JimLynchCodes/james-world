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
  4. a pale champagne cape to the calves. On the back (N, NW, NE) it is
     an opaque layer over the arms and hands; from the front and sides the
     arms stay in front of the wings. Dark outline and a 2px gold trim;
  5. striped nemes over the hair. From the front the face shows through a
     smooth oval. The lappets leave the cheek and drape down and inward
     over the chest, with rounded ends. Side views keep James's own
     profile (eye, brow, nose, mouth, ear, jaw) pixel for pixel; stripes
     replace the hair only, and the lappets drape from the nape and the
     chest onto the shoulder. Back views are all headdress;
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


def _face_keep(f: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray]:
    """James's face (skin + eyes + mouth) and the ears, which stay under the cloth.

    The returned face is the real features, used only to *fit* the oval and to
    know which pixels keep their original colour. The hole itself is the oval.
    """
    h, w = f.shape[:2]
    empty = np.zeros((h, w), dtype=bool)
    if direction in BACK:
        return empty, empty
    yy, xx = np.mgrid[0:h, 0:w]
    # skull only: a tagging arm can reach the head zone and must not become the face
    zone = (yy >= g.top + 8) & (yy <= g.neck + 1)
    zone &= np.abs(xx - g.head_cx) <= g.head_hw + 1
    if direction in PROFILE:
        # the back of the skull is hair; the visible face is the nose side
        zone &= (xx - g.head_cx) * PROFILE[direction] >= -4
    comps = [c for c in components8(skin_mask(f) & zone) if c.sum() >= 8]
    if not comps:
        return empty, empty
    comps.sort(key=lambda c: -c.sum())
    face = comps[0]
    ys, xs = np.nonzero(face)
    span_l, span_r = int(xs.min()), int(xs.max())
    ears = np.zeros((h, w), dtype=bool)
    for c in comps[1:]:
        cys, cxs = np.nonzero(c)
        ccx = (float(cxs.min()) + float(cxs.max())) / 2
        if ccx < span_l - 1 or ccx > span_r + 1:
            ears |= c
            continue
        if cys.min() <= int(ys.max()) + 4:
            face |= c
    face = fill_holes(face)
    enclosed = fill_holes(dilate(face, 1)) & ~face & zone
    r, gc, b = (f[..., i].astype(np.int16) for i in range(3))
    lumv = r.astype(np.int32) + gc.astype(np.int32) + b.astype(np.int32)
    features = enclosed & ((lumv < 220) | ((r > 140) & (gc < 130) & (b < 130)))
    hair = (
        alpha_mask(f)
        & ~skin_mask(f)
        & (r > gc + 18)
        & (r > 70)
        & (gc < 175)
        & (b < r - 8)
        & ~features
    )
    shade = loose_skin(f) & dilate(face, 1) & zone & ~dilate(ears, 1) & ~hair
    keep = fill_holes(face | features | shade) & ~hair & ~dilate(ears, 1)
    return fill_holes(keep), ears


def _fit_oval(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """Axis-aligned oval that holds the face. Centres are pixel centres."""
    ys, xs = np.nonzero(mask)
    if xs.size < 20:
        return None
    cx = float(np.median(xs)) + 0.5
    cy = float(np.median(ys)) + 0.5
    dx = np.abs(xs + 0.5 - cx)
    dy = np.abs(ys + 0.5 - cy)
    rx = max(float(np.quantile(dx, 0.9)), 3.5)
    ry = max(float(np.quantile(dy, 0.92)), 4.5)
    radial = np.sqrt(((xs + 0.5 - cx) / rx) ** 2 + ((ys + 0.5 - cy) / ry) ** 2)
    # A box-fitted ellipse misses the diagonal cheek pixels. Grow until the
    # face sits inside, with a little cloth-side padding so the brow and chin
    # aren't cut by the stripe.
    scale = max(1.0, float(np.quantile(radial, 0.99))) * 1.06
    return cx, cy, max(rx * scale, 4.0), max(ry * scale, 5.0)


def _ellipse_coverage(
    h: int, w: int, cx: float, cy: float, rx: float, ry: float, samples: int = 4
) -> np.ndarray:
    """Subpixel coverage of an ellipse. 1 = inside the face hole."""
    cov = np.zeros((h, w), dtype=np.float32)
    y0 = max(0, int(math.floor(cy - ry - 1)))
    y1 = min(h, int(math.ceil(cy + ry + 2)))
    x0 = max(0, int(math.floor(cx - rx - 1)))
    x1 = min(w, int(math.ceil(cx + rx + 2)))
    if y1 <= y0 or x1 <= x0 or rx < 0.5 or ry < 0.5:
        return cov
    yy, xx = np.mgrid[y0:y1, x0:x1]
    acc = np.zeros(yy.shape, dtype=np.float32)
    offs = (np.arange(samples) + 0.5) / samples - 0.5
    for oy in offs:
        for ox in offs:
            acc += ((xx + ox - cx) / rx) ** 2 + ((yy + oy - cy) / ry) ** 2 <= 1.0
    cov[y0:y1, x0:x1] = acc / float(samples * samples)
    return cov


def _profile_face(f: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """James's side-view face, kept as drawn.

    The large skin mass is the brow, nose, mouth, jaw and ear. Pixels
    touching it (the eye, the nostril, the lip) stay too. Stray brown
    specks in the hair are not part of the face. `direction` is unused;
    the ear and the nose are found from the pixels, so east and west
    both work.
    """
    del direction
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    head = (yy >= g.top + 2) & (yy <= g.neck + 2) & alpha_mask(f)
    head &= np.abs(xx - g.head_cx) <= g.head_hw + 1
    comps = [c for c in components8(loose_skin(f) & head) if c.sum() >= 40]
    face = np.zeros((h, w), dtype=bool)
    for c in comps:
        face |= c
    if not face.any():
        return face
    r, gc, b = (f[..., i].astype(np.int16) for i in range(3))
    # reddish hair next to the ear must not be pulled into the face
    red_hair = (r > gc + 12) & (r > 60) & (b + 6 < r)
    red_hair &= (r.astype(np.int32) + gc.astype(np.int32) + b.astype(np.int32)) > 200
    near = dilate(face, 2) & head & ~face & ~red_hair
    return face | near


def face_window(
    f: np.ndarray, g: Geometry, direction: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float, float, float] | None]:
    """Where the nemes opens onto James.

    Front and three-quarter views: a smooth oval (coverage 0..1) fitted to
    the face. Side views: no oval — `opening` is the real profile (eye, brow,
    nose, mouth, ear, jaw) and coverage stays 0 so nothing repaints it.
    Back views: closed headdress.
    """
    h, w = f.shape[:2]
    coverage = np.zeros((h, w), dtype=np.float32)
    if direction in PROFILE:
        face = _profile_face(f, g, direction)
        return coverage, face, face, None
    keep, _ears = _face_keep(f, g, direction)
    oval = _fit_oval(keep) if keep.any() else None
    if oval is None:
        return coverage, np.zeros((h, w), dtype=bool), keep, None
    cx, cy, rx, ry = oval
    coverage = _ellipse_coverage(h, w, cx, cy, rx, ry)
    yy, xx = np.mgrid[0:h, 0:w]
    # room around the head so the curve isn't clipped back to the silhouette
    head = dilate(alpha_mask(f) & (yy <= g.neck + 3) & (yy >= g.top - 2), 3)
    coverage *= head
    opening = coverage >= 0.5
    return coverage, opening, keep, oval


def blend_lappet_edges(
    shown: np.ndarray,
    lcov: np.ndarray,
    g: Geometry,
    face_cov: np.ndarray,
) -> None:
    """Soften the outer edge of the shoulder flaps. The face oval is left alone."""
    band = (lcov > 0.05) & (lcov < 0.98) & (face_cov <= 0.02)
    if not band.any():
        return
    rel = (np.arange(shown.shape[0]) - (g.top - 4))[:, None]
    gold = np.broadcast_to((rel % 5) <= 1, lcov.shape)
    stripe = np.empty(shown.shape[:2] + (3,), dtype=np.float32)
    stripe[:] = NEMES.astype(np.float32)
    stripe[gold] = GOLD.astype(np.float32)
    c = lcov[..., None]
    base = shown[..., :3].astype(np.float32)
    opaque = shown[..., 3] > 20
    mixed = np.where(opaque[..., None], stripe * c + base * (1.0 - c), stripe)
    shown[band, :3] = np.clip(mixed[band], 0, 255).astype(np.uint8)
    soft = (lcov * 255.0).astype(np.uint8)
    shown[band, 3] = np.where(opaque[band], 255, np.maximum(shown[band, 3], soft[band]))


def blend_face_oval(
    shown: np.ndarray,
    original: np.ndarray,
    coverage: np.ndarray,
    keep: np.ndarray,
    g: Geometry,
) -> None:
    """Anti-alias the stripes into the oval.

    The hard 0.5 contour is replaced by a subpixel mix, so the cloth edge is
    a curve instead of a staircase. Gaps inside the oval (a hair pixel, a
    transparent nick) take the face's own skin colour so the hole never shows
    the yard. Stripe rows match paint_stripes.
    """
    band = coverage > 0.02
    if not band.any():
        return
    skin_px = original[keep & skin_mask(original)]
    if len(skin_px):
        skin_rgb = np.median(skin_px[:, :3].astype(np.float32), axis=0)
    else:
        skin_rgb = np.array([232.0, 186.0, 154.0], dtype=np.float32)
    face = original[..., :3].astype(np.float32)
    face[band & ~keep] = skin_rgb
    rel = (np.arange(shown.shape[0]) - (g.top - 4))[:, None]
    gold = np.broadcast_to((rel % 5) <= 1, coverage.shape)
    stripe = np.empty(shown.shape[:2] + (3,), dtype=np.float32)
    stripe[:] = NEMES.astype(np.float32)
    stripe[gold] = GOLD.astype(np.float32)
    c = coverage[..., None]
    mixed = face * c + stripe * (1.0 - c)
    shown[band, :3] = np.clip(mixed[band], 0, 255).astype(np.uint8)
    shown[band, 3] = 255


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


def _cov_span(cov: np.ndarray, y: int, x0: float, x1: float) -> None:
    """Anti-aliased horizontal span. x1 is exclusive."""
    h, w = cov.shape
    if y < 0 or y >= h:
        return
    if x1 < x0:
        x0, x1 = x1, x0
    xa = max(0, int(math.floor(x0)))
    xb = min(w - 1, int(math.floor(x1 - 1e-6)))
    for x in range(xa, xb + 1):
        cover = min(1.0, min(x + 1.0, x1) - max(float(x), x0))
        if cover > cov[y, x]:
            cov[y, x] = cover


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _draped_pair(
    h: int,
    w: int,
    cx: float,
    outer_top: float,
    inner_top: float,
    outer_bot: float,
    inner_bot: float,
    y0: int,
    y1: int,
) -> np.ndarray:
    """Two lappets. The four x values describe the LEFT flap; the right mirrors.

    `outer_top`/`inner_top` sit against the cheek (inside the head, not past
    it). `outer_bot`/`inner_bot` have swung inward so the cloth lies on the
    chest. The lower end rounds off instead of ending in a flat cut.
    """
    cov = np.zeros((h, w), dtype=np.float32)
    y0 = max(0, y0)
    y1 = min(h - 1, y1)
    if y1 - y0 < 4:
        return cov
    span = float(y1 - y0)
    for y in range(y0, y1 + 1):
        t = (y - y0) / span
        s = _smoothstep(t)
        outer = outer_top + (outer_bot - outer_top) * s
        inner = inner_top + (inner_bot - inner_top) * s
        if t > 0.72:
            u = (t - 0.72) / 0.28
            mid = (outer + inner) * 0.5
            half = abs(inner - outer) * 0.5 * math.sqrt(max(0.0, 1.0 - u * u))
            outer, inner = mid - half, mid + half
        if inner - outer < 0.6:
            continue
        _cov_span(cov, y, outer, inner)
        _cov_span(cov, y, (2.0 * cx) - inner, (2.0 * cx) - outer)
    return cov


def _draped_one(
    h: int,
    w: int,
    x0: float,
    x1: float,
    y0: int,
    y1: int,
    width0: float,
    width1: float,
) -> np.ndarray:
    """One lappet. The centreline runs from `x0` to `x1` as the cloth falls.

    Used in profile: the rear flap starts at the nape and drifts onto the
    shoulder, and the near flap starts under the jaw and lies on the chest.
    """
    cov = np.zeros((h, w), dtype=np.float32)
    y0 = max(0, y0)
    y1 = min(h - 1, y1)
    if y1 - y0 < 4:
        return cov
    span = float(y1 - y0)
    for y in range(y0, y1 + 1):
        t = (y - y0) / span
        s = _smoothstep(t)
        centre = x0 + (x1 - x0) * s
        width = width0 + (width1 - width0) * s
        if t > 0.74:
            u = (t - 0.74) / 0.26
            width *= math.sqrt(max(0.0, 1.0 - u * u))
        if width < 0.6:
            continue
        _cov_span(cov, y, centre - width * 0.5, centre + width * 0.5)
    return cov


def _profile_nemes(
    f: np.ndarray, g: Geometry, direction: str, face: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stripes on the hair only. The profile itself is not repainted.

    A rear lappet leaves the nape and settles on the shoulder. A second,
    shorter one leaves the jaw and lies on the chest. Neither covers the
    eye, ear, nose or mouth.
    """
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = alpha_mask(f)
    head = a & (yy >= g.top - 1) & (yy <= g.neck + 1)
    head &= np.abs(xx - g.head_cx) <= g.head_hw + 2
    r, gc, b = (f[..., i].astype(np.int16) for i in range(3))
    red = (r > gc + 10) & (r > 55) & (b + 4 < r) & (gc < 190)
    hair = head & red & ~face
    lumv = r.astype(np.int32) + gc.astype(np.int32) + b.astype(np.int32)
    dark = head & ~loose_skin(f) & (lumv < 210) & ~face
    crown = dark & (yy <= g.top + 8)
    edge = dark & dilate(hair, 2)
    # stop a pixel short of the skin so the nose, ear and jaw keep their line
    cloth = (hair | crown | edge) & ~dilate(face, 1)
    toward = float(PROFILE[direction])

    def _side(y: int, back: bool) -> float:
        """Torso edge at row y. Arms are ignored, so a tag swing cannot pull a flap out."""
        y = max(0, min(h - 1, y))
        xs = np.arange(w)
        band = a[y] & (np.abs(xs - g.head_cx) <= max(12.0, g.head_hw * 0.92))
        cols = np.nonzero(band)[0]
        if len(cols) == 0:
            cols = np.nonzero(a[y])[0]
        if len(cols) == 0:
            return g.head_cx
        return float(cols.min() if (toward > 0) == back else cols.max())

    # Rear flap: from the nape down the back, lying ON the shoulder.
    # A couple of pixels in from the silhouette, so it cannot stand out as a board.
    x_nape = _side(g.neck - 4, True) + toward * 3.4
    x_shoulder = _side(g.neck + 10, True) + toward * 4.2
    rear = _draped_one(h, w, x_nape, x_shoulder, g.neck - 4, g.neck + 16, 5.2, 6.2)
    # Near flap: under the jaw, on the chest, inside the torso.
    x_jaw = _side(g.neck + 3, False) - toward * 4.6
    x_chest = _side(g.neck + 12, False) - toward * 5.2
    near = _draped_one(h, w, x_jaw, x_chest, g.neck + 2, g.neck + 15, 4.4, 5.4)
    lappet_cov = np.maximum(rear, near)
    # never past the body: a real lappet rests on the shoulder, it does not poke out
    lappet_cov *= dilate(a, 1)
    block = dilate(face, 1)
    lappets = (lappet_cov >= 0.5) & ~block
    lappet_cov = lappet_cov * (~block)
    return cloth, lappets, lappet_cov


def nemes_cloth(
    f: np.ndarray,
    g: Geometry,
    direction: str,
    opening: np.ndarray,
    oval: tuple[float, float, float, float] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Striped crown plus two lappets that continue the same stripes.

    The third return is lappet coverage (0..1) so the shoulder edge can be
    anti-aliased instead of a one-pixel staircase.
    """
    h, w = f.shape[:2]
    if direction in PROFILE:
        return _profile_nemes(f, g, direction, opening)
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
    # below the chin, leave a gap between the lappets (neck, not a stripe beard)
    if oval is not None and direction not in PROFILE:
        cx, cy, rx, ry = oval
        bib = (yy > cy + ry * 0.72) & (np.abs(xx + 0.5 - cx) < rx * 0.42)
        cloth &= ~bib

    # Lappets continue the cheek cloth and swing inward onto the chest.
    # The outer edge moves in as it falls, so the flaps are not side boards.
    if oval is not None:
        cx, cy, rx, ry = oval
        outer_top = cx - min(g.head_hw * 0.96, rx + 2.6)
        inner_top = outer_top + 5.2
        outer_bot = cx - max(10.5, rx * 0.72)
        inner_bot = cx - max(4.2, rx * 0.28)
        outer_bot = max(outer_bot, outer_top + 6.0)
        if inner_bot < outer_bot + 5.5:
            inner_bot = outer_bot + 7.4
        y0 = int(round(cy + ry * 0.20))
        lappet_cov = _draped_pair(
            h, w, cx, outer_top, inner_top, outer_bot, inner_bot, y0, g.neck + 20
        )
        lappets = lappet_cov >= 0.5
    else:
        outer_top = g.head_cx - g.head_hw * 0.70
        inner_top = outer_top + 5.0
        outer_bot = g.head_cx - g.head_hw * 0.30
        inner_bot = outer_bot + 6.6
        lappet_cov = _draped_pair(
            h, w, g.head_cx,
            outer_top, inner_top, outer_bot, inner_bot,
            g.neck - 1, g.neck + 16,
        )
        lappets = lappet_cov >= 0.5
    lappets &= ~opening
    if lappet_cov is None:
        lappet_cov = lappets.astype(np.float32)
    else:
        lappet_cov *= ~opening
    # ears (face skin outside the window) stay under the cloth
    face_skin = (yy <= g.neck + 1) & skin_mask(f)
    cloth |= face_skin & ~opening & (yy <= jaw)
    return cloth, lappets, lappet_cov


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

    coverage, opening, face_pixels, oval = face_window(f, g, direction)
    face = (yy <= g.neck + 1) & skin_mask(f)
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

    # Front and sides: the face and the hands stay on top of every layer.
    # Back: the cape is the rear surface, so the arms and hands stay behind it.
    face_keep = opening & (f[..., 3] > 0)
    hand_keep = hands & (img[..., 3] > 0) & (direction not in BACK)
    protect = face_keep | hand_keep
    saved = img.copy()
    saved[opening] = f[opening]  # original eyes, mouth, freckles — not recoloured neighbours

    cloth, lappets, lappet_cov = nemes_cloth(img, g, direction, opening, oval)
    cloth &= ~protect
    lappets &= ~protect & ~hands

    torso = a & ~arms & ~hands & (yy > g.neck) & (yy < g.hem)
    cape = cape_mask(g, torso, direction, phase_sway(anim, col))
    if direction in BACK:
        # fill the cape out to the arms and plug the holes where the limbs were
        limb = (arms | hands) & ~shoes
        rows = np.nonzero(cape.any(axis=1))[0]
        if len(rows):
            for y in range(int(rows.min()), int(rows.max()) + 1):
                xs = np.nonzero(cape[y] | limb[y])[0]
                if len(xs) >= 2:
                    cape[y, int(xs[0]):int(xs[-1]) + 1] = True
        cape &= ~cloth & ~lappets & ~shoes
    else:
        # wings sit behind the body, the arms and the sandals
        cape &= ~cloth & ~lappets & ~protect & ~hands & ~arms & ~shoes
    cape &= yy < g.hem + 8

    shown = img.copy()
    if direction in BACK:
        # tunic, shendyt and the arms all disappear under the cape; feet stay
        cover = (yy > g.neck + 1) & (yy < g.hem + 6) & ~shoes
        shown[cover, 3] = 0
        paint_cape(shown, cape)
        # a limb that still sticks past the cloth must not show as skin
        peek = (arms | hands) & ~shoes & ~cape & (yy > g.neck)
        shown[peek, 3] = 0
    else:
        # wings only: the body is already in `shown` and must stay in front
        paint_cape(shown, cape & (shown[..., 3] == 0))

    collar = paint_collar(shown, g, direction, opening)
    # nemes over the collar at the jaw, lappets over the shoulders
    paint_stripes(shown, cloth & ~protect, g)
    paint_stripes(shown, lappets & ~protect, g)

    paint_belt_eagle(shown, g, direction, (tunic | skirt) & ~arms)
    paint_pendant(shown, g, direction, opening)
    # collar variable kept so a back-view collar isn't covered by the cape fold
    _ = collar

    # face (and, from the front, the hands) always win. Gauntlets stay off the back.
    shown[protect] = saved[protect]
    if direction not in BACK:
        stamp(shown, gaunt & ~protect, GOLD)
        stamp(shown, lip & ~protect, GOLD_BRIGHT)
    # sandals again so the cape hem can't swallow the straps
    paint_sandals(shown, g, shins & ~protect, shoes & ~protect)
    paint_skirt_gold(shown, skirt & (shown[..., 3] > 0) & ~protect, g, direction)
    paint_belt_eagle(shown, g, direction, (tunic | skirt) & ~protect)
    paint_pendant(shown, g, direction, opening)
    # smooth the stripes into the oval last, so nothing restamps a hard edge
    blend_lappet_edges(shown, lappet_cov, g, coverage)
    blend_face_oval(shown, f, coverage, face_pixels, g)

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
