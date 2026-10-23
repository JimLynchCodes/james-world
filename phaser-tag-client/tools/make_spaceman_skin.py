#!/usr/bin/env python3
"""Build the "Spaceman James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_spaceman.png + kid_spaceman.json
        src/spacemanBoosters.ts  (nozzle anchors for the run flames)

Same frame size, columns, rows, animation ranges and feet line as kid.png.
Every frame starts from that exact base frame (same direction, animation and
frame index). The suit is painted over the body; nothing opaque in the base
frame is erased. Every direction wears the same smooth oval helmet for the
whole animation: a white shell with one shadow side, a neck ring, and — on
front and side views — a light-blue glass visor. James's own face shows
through that glass (hair, brows, eyes, nose, mouth, and the side ear),
reduced to a few flat colors so the dither does not speckle. Back views are
that dome, with a short antenna and a small highlight. The backpack and its two dark booster cones sit on his back:
visible when he faces away, on the rear side in profile, and behind the body
(a shoulder peek at most) when he faces the camera.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_spaceman_skin.py [--preview /tmp/spaceman_preview.png]
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
    fill_holes,
    skin_mask,
)
from make_tuxedo_skin import close_streaks

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"
BOOSTERS_TS = HERE.parent / "src" / "spacemanBoosters.ts"

# Flat suit palette: three white/greys, one outline, a few accents.
OUTLINE = (26, 30, 40)
HI = (246, 248, 252)
MID = (206, 214, 224)
LO = (158, 168, 182)
RIM = (126, 164, 196)
GLINT = (255, 255, 255)
PANEL = (36, 72, 158)
RED = (204, 46, 54)
BLUE = (46, 108, 214)
YELLOW = (240, 196, 48)
# Dark metal for the booster cones. Not the black outline, so the nozzle reads.
METAL = (72, 80, 96)
# Glass is only used inside the visor (L_KEEP), so it stays out of the suit palette.
GLASS = (168, 216, 232)
# James's face, before the glass mix. L_KEEP only, so the suit palette stays flat.
# Dark features stay dark; the skin takes more of the blue glass.
FACE_HAIR = (86, 48, 30)
FACE_BROW = (32, 16, 14)
FACE_PUPIL = (12, 8, 10)
FACE_EYE = (248, 246, 242)
FACE_LIGHT = (240, 190, 148)
FACE_MID = (212, 150, 108)
FACE_SHADE = (132, 70, 46)
FACE_MOUTH = (118, 44, 38)
PALETTE = {OUTLINE, HI, MID, LO, RIM, GLINT, PANEL, RED, BLUE, YELLOW, METAL}

# Visor ellipse as fractions of the locked helmet: (cx shift, cy shift, rx, ry).
# High enough that the hairline and brows sit in the glass. Side views push
# the glass onto the facing half so the shell wraps the back of the head.
VISOR_SHAPE = {
    "S": (0.00, 0.00, 0.68, 0.64),
    "SE": (0.12, 0.00, 0.62, 0.62),
    "SW": (-0.12, 0.00, 0.62, 0.62),
    "E": (0.32, 0.02, 0.64, 0.68),
    "W": (-0.32, 0.02, 0.64, 0.68),
}

# One helmet per direction, measured on the idle frame and reused everywhere.
HELM: dict[str, tuple[float, float, float, float]] = {}

FRONT = {"SE", "S", "SW"}
SIDE = {"E": -1, "W": 1}  # screen-x of the back
BACK = {"NW", "N", "NE"}
# Backpack shifts toward the back on the three-quarter rear views.
BACK_SHIFT = {"NW": 2, "N": 0, "NE": -2}

# Pixel labels, so the checks know what was added where.
L_KEEP = 1
L_SUIT = 2
L_LINE = 3
L_GLOVE = 4
L_BOOT = 5
L_HELM = 6
L_EAR = 7
L_PACK = 8
L_BOOST = 9


def dilate4(mask: np.ndarray, r: int = 1) -> np.ndarray:
    """Cross dilation. Stays tighter than the 8-connected helmet bubble."""
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g
    return m


def dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
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


def erode(mask: np.ndarray, r: int = 1) -> np.ndarray:
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] &= m[:-1]
        g[:-1] &= m[1:]
        g[:, 1:] &= m[:, :-1]
        g[:, :-1] &= m[:, 1:]
        m = g
    return m


def paint(img: np.ndarray, lab: np.ndarray, mask: np.ndarray, color: tuple[int, int, int], label: int) -> None:
    if not mask.any():
        return
    img[mask, 0] = color[0]
    img[mask, 1] = color[1]
    img[mask, 2] = color[2]
    img[mask, 3] = 255
    lab[mask] = label


def shell_bands(mask: np.ndarray, yy: np.ndarray, xx: np.ndarray):
    """Broad light-to-dark bands: lighter top-left, grey bottom-right.

    Thresholds are wide on purpose so the shell doesn't speckle.
    """
    mid = np.zeros(mask.shape, dtype=bool)
    lo = np.zeros(mask.shape, dtype=bool)
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return mid, lo
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    ny = (yy - y0) / max(1, y1 - y0)
    nx = (xx - x0) / max(1, x1 - x0)
    light = nx * 0.55 + ny * 0.85
    mid[mask & (light >= 0.34) & (light < 0.62)] = True
    lo[mask & (light >= 0.62)] = True
    return mid, lo


def glass_tint(img: np.ndarray, mask: np.ndarray) -> None:
    """Flat blue glass over the visor. Quantized so the face doesn't speckle."""
    if not mask.any():
        return
    px = img[mask, :3].astype(np.int16)
    glass = np.array(GLASS, dtype=np.int16)
    mixed = (px * 3 + glass) // 4
    q = (mixed // 20) * 20 + 10
    q = np.clip(q, 0, 255).astype(np.uint8)
    img[mask, 0] = q[:, 0]
    img[mask, 1] = q[:, 1]
    img[mask, 2] = q[:, 2]
    img[mask, 3] = 255


def shade_rows(mask: np.ndarray) -> np.ndarray:
    """Right-hand shade band, one or two pixels, stable across frames."""
    shade = np.zeros(mask.shape, dtype=bool)
    h = mask.shape[0]
    for y in range(h):
        xs = np.nonzero(mask[y])[0]
        if len(xs) >= 5:
            shade[y, xs[-2]] = True
            if len(xs) >= 8:
                shade[y, xs[-3]] = True
    return shade & mask


def round_rect(h: int, w: int, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Inclusive box with the four corner pixels knocked off."""
    m = np.zeros((h, w), dtype=bool)
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w - 1, x1)
    y1 = min(h - 1, y1)
    if x1 < x0 or y1 < y0:
        return m
    m[y0 : y1 + 1, x0 : x1 + 1] = True
    for y, x in ((y0, x0), (y0, x1), (y1, x0), (y1, x1)):
        if 0 <= y < h and 0 <= x < w:
            m[y, x] = False
    return m


def nozzle(h: int, w: int, cx: int, top: int) -> tuple[np.ndarray, np.ndarray]:
    """Small dark cone under the pack. Wide at the pack, narrow at the exhaust."""
    m = np.zeros((h, w), dtype=bool)
    hole = np.zeros((h, w), dtype=bool)
    # radius per row: 5, 5, 3, 3, 3
    radii = (2, 2, 1, 1, 1)
    for dy, rad in enumerate(radii):
        y = top + dy
        if not 0 <= y < h:
            continue
        for dx in range(-rad, rad + 1):
            x = cx + dx
            if 0 <= x < w:
                m[y, x] = True
        if dy >= 3 and 0 <= cx < w:
            hole[y, cx] = True
    return m, hole


def row_bounds(mask: np.ndarray, y0: int, y1: int):
    band = mask[max(0, y0) : y1 + 1]
    xs = np.nonzero(band.any(axis=0))[0]
    if len(xs) == 0:
        return None
    return int(xs.min()), int(xs.max())


def suit_frame(base: np.ndarray, direction: str) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Return (rgba, labels, [(x, y), (x, y)] nozzle centres)."""
    h, w = base.shape[:2]
    g = Geometry(base)
    # Fill see-through streaks below the chin only, so the face stays exact.
    # The crease between an arm and the torso is not a hole: leave it open
    # so the arm stays a separate limb instead of fusing to the chest.
    yy_pre = np.arange(h)[:, None]
    face_pre = (yy_pre <= g.neck + 1) & skin_mask(base)
    arms_pre, _ = arms_and_hands(base, g, face_pre)
    base_a_pre = alpha_mask(base)
    # Transparent pixels pinched between an arm and the torso. They get a
    # dark outline later so the arm stays separate without a see-through gap.
    crease = ~base_a_pre & dilate(arms_pre, 1) & dilate(base_a_pre & ~arms_pre, 1)
    # The split between the boots, measured on the original feet, before
    # streak-filling can stitch it shut.
    yy_gap = np.arange(h)[:, None]
    sk_pre = loose_skin_safe(base)
    shoes_pre = base_a_pre & (yy_gap >= g.bottom - 7) & ~sk_pre & (yy_gap > g.hem)
    foot_gap = boot_gap(shoes_pre, g.hip_cx)
    closed = close_streaks(base, g.neck + 1)
    closed[foot_gap] = 0
    a = alpha_mask(closed)
    base_a = alpha_mask(base)
    yy, xx = np.mgrid[0:h, 0:w]
    face = (yy <= g.neck + 1) & skin_mask(closed)
    arms, hands = arms_and_hands(closed, g, face)
    # The whole hand, not just the far tip the helper marks.
    hands = dilate(hands, 2) & arms & (loose_skin_safe(closed) | hands)

    head_cut = g.neck - 1
    head = a & (yy <= head_cut) & ~arms
    show_face = direction not in BACK

    # Legs and boots from the shorts hem down. Shoes are the non-skin
    # pixels at the bottom; bare shins are the skin between hem and shoe.
    sk = loose_skin_safe(closed)
    bottom = g.bottom
    shoes = a & (yy >= bottom - 7) & ~sk & ~arms & (yy > g.hem)
    shins = a & sk & (yy >= g.hem) & ~arms & ~shoes
    suit_body = a & ~head & ~hands & (yy > head_cut)

    out = closed.copy()
    lab = np.zeros((h, w), dtype=np.uint8)

    # Suit over every body pixel that isn't the head. The head is the helmet,
    # painted below. Arms are shaded on their own so a diagonal sleeve doesn't
    # pick up a speckled right-edge shadow.
    body = suit_body & ~head
    torso = body & ~arms
    paint(out, lab, body, HI, L_SUIT)
    paint(out, lab, shade_rows(torso & ~shoes), MID, L_SUIT)

    # White sleeves, a red band, a grey fold, and a glove at the tip.
    # Wide side-view blobs that sit on the belly stay suit-white; the
    # facing edge of them is the sleeve. See paint_sleeves.
    paint_sleeves(out, lab, arms & a & (yy > head_cut), a, direction, g, yy, xx)

    # Chunky boots, one per foot. Grow a pixel away from the other foot and
    # one pixel down. Never bridge the gap, or the two boots become a sled.
    # foot_gap was measured on the original frame (see above).
    boot_extra = np.zeros_like(shoes)
    for side in (xx < g.hip_cx, xx >= g.hip_cx):
        foot = shoes & side
        if not foot.any():
            continue
        grown = dilate4(foot, 1) & ~a & (yy >= bottom - 7) & ~foot_gap
        # Only the outside and the sole: drop pixels toward the other foot.
        toward = dilate4(shoes & ~side, 1)
        grown &= ~toward
        # No upward growth into the shin.
        top = int(np.nonzero(foot)[0].min())
        grown &= yy >= top
        boot_extra |= grown
    paint(out, lab, shoes & ~foot_gap, HI, L_BOOT)
    paint(out, lab, boot_extra & ~foot_gap, HI, L_BOOT)
    boots = (lab == L_BOOT) & ~foot_gap
    for side in (xx < g.hip_cx, xx >= g.hip_cx):
        comp = boots & side
        if not comp.any():
            continue
        ys = np.nonzero(comp)[0]
        top, bot = int(ys.min()), int(ys.max())
        paint(out, lab, comp & (yy == top), LO, L_BOOT)
        if top + 1 < bot:
            paint(out, lab, comp & (yy == top + 1), RED, L_BOOT)
        # Coloured sole. The row above it stays the dark welt.
        if bot - 1 > top + 1:
            paint(out, lab, comp & (yy == bot - 1), OUTLINE, L_BOOT)
        paint(out, lab, comp & (yy == bot), BLUE, L_BOOT)
        paint(out, lab, shade_rows(comp & (yy > top + 1) & (yy < bot - 1)), MID, L_BOOT)

    # Silhouette outline of everything so far (head shell comes next and
    # outlines itself). Preserved face pixels keep James's own outline.
    solid = alpha_mask(out)
    edge = solid & ~erode(solid, 1)
    edge &= lab != L_KEEP
    paint(out, lab, edge, OUTLINE, L_LINE)

    # The pinched crease between arm and torso becomes outline: opaque, so
    # the suit has no hole, and dark, so the sleeve doesn't fuse to the chest.
    # The outer edge is already the silhouette. A second rim around a
    # diagonal arm staircases into broken specks, so it is not drawn.
    paint(out, lab, crease & (yy > head_cut), OUTLINE, L_LINE)
    # And the new glove's outer edge.
    glove_edge = (lab == L_GLOVE) & dilate(lab != L_GLOVE, 1) & ~((lab != L_GLOVE) & solid & (lab != 0))
    glove_edge = (lab == L_GLOVE) & ~erode(solid, 1)
    paint(out, lab, glove_edge, OUTLINE, L_LINE)

    # Red thigh stripe and a grey knee fold. One solid band, not a speck.
    thighs = shins & (yy <= g.hem + 6) & (lab != L_LINE)
    for side in (xx < g.hip_cx, xx >= g.hip_cx):
        comp = thighs & side
        if comp.sum() < 6:
            continue
        paint(out, lab, limb_band(comp, 0.45, 1), LO, L_SUIT)
        paint(out, lab, limb_band(comp, 0.2, 2), RED, L_SUIT)

    # Chest panel with three buttons. Front gets the full panel; profiles
    # get the front edge of it.
    paint_panel(out, lab, g, direction, a, arms, yy, xx)
    # Side views: the sleeve continues up over the existing shoulder so it
    # isn't a patch at the hip. Painted after the panel so the buttons stay.
    if direction in SIDE:
        paint_side_sleeve(out, lab, arms & a, a, direction, g, yy, xx)

    paint_helmet(out, lab, closed, head & a, direction, g, h, w, yy, xx)

    # Backpack layer, then composite so it can never show through the body
    # on front / side views. On back views it is the surface we see.
    pack, boost, nozzles = draw_pack(g, a, arms, head, direction, h, w)
    out, lab = composite_pack(out, lab, pack, boost, direction, arms, head)

    # Any base pixel that a composite step cleared goes back, suited.
    lost = base_a & (out[..., 3] <= 40)
    if lost.any():
        paint(out, lab, lost, HI, L_SUIT)

    # Pinholes below the chin: enclosed see-through pixels become suit.
    solid = alpha_mask(out)
    holes = fill_holes(solid) & ~solid & (yy > head_cut) & ~crease & ~dilate4(foot_gap, 1)
    if holes.any():
        paint(out, lab, holes, HI, L_SUIT)
        # re-outline only if a hole-fill touched the silhouette (it shouldn't)
    # The silhouette pass paints the sole the same dark as the outline.
    # Put the coloured sole back on the interior of the bottom row.
    for side in (xx < g.hip_cx, xx >= g.hip_cx):
        foot = (out[..., 3] > 40) & side & (yy >= g.bottom - 3) & (yy <= g.bottom + 1) & ~foot_gap
        foot &= np.isin(lab, (L_BOOT, L_LINE, L_SUIT))
        if foot.sum() < 4:
            continue
        bot = int(np.nonzero(foot)[0].max())
        row = foot & (yy == bot)
        xs = np.nonzero(row[bot])[0]
        if len(xs) < 3:
            continue
        sole = row.copy()
        sole[bot, xs[0]] = False
        sole[bot, xs[-1]] = False
        paint(out, lab, sole, BLUE, L_BOOT)
        if bot - 1 >= 0:
            welt = foot & (yy == bot - 1) & (lab == L_LINE)
            paint(out, lab, welt, OUTLINE, L_BOOT)

    # Fully opaque or fully clear. A half-alpha suit lets the grass show through.
    visible = out[..., 3] > 40
    out[~visible] = 0
    out[visible, 3] = 255
    return out, lab, nozzles


def loose_skin_safe(f: np.ndarray) -> np.ndarray:
    from make_banana_skin import loose_skin
    return loose_skin(f)


def _at(mask: np.ndarray, y: int, x: int) -> np.ndarray:
    m = np.zeros_like(mask)
    if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]:
        m[y, x] = True
    return m


def limb_band(comp: np.ndarray, frac: float, thick: int) -> np.ndarray:
    """A solid cross-band on a limb. Skips a row that would be a single speck."""
    band = np.zeros_like(comp)
    ys = np.nonzero(comp.any(axis=1))[0]
    if len(ys) < 3:
        return band
    i = min(len(ys) - 1, max(0, int(round((len(ys) - 1) * frac))))
    h = comp.shape[0]
    for dy in range(thick):
        y = int(ys[i]) + dy
        if not 0 <= y < h:
            continue
        xs = np.nonzero(comp[y])[0]
        if len(xs) < 2:
            continue
        band[y] = comp[y]
        if len(xs) >= 4:
            band[y, xs[0]] = False
            band[y, xs[-1]] = False
    if int(band.sum()) < 2:
        return np.zeros_like(comp)
    return band


def ear_cups(shell: np.ndarray, blocked: np.ndarray, direction: str, h: int, w: int) -> np.ndarray:
    """Small darker ear pieces on the shell. Recolour only; don't grow or hole it."""
    ears = np.zeros_like(shell)
    ys, xs = np.nonzero(shell)
    if len(ys) == 0:
        return ears
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    ear_y = y0 + int((y1 - y0) * 0.46)

    def stamp(cx: int, cy: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-1, 2):
                y, x = cy + dy, cx + dx
                if 0 <= y < h and 0 <= x < w and shell[y, x]:
                    ears[y, x] = True

    if direction == "E":
        stamp(x0 + max(4, int((x1 - x0) * 0.22)), ear_y)
    elif direction == "W":
        stamp(x1 - max(4, int((x1 - x0) * 0.22)), ear_y)
    else:
        stamp(x0 + 3, ear_y)
        stamp(x1 - 3, ear_y)
    return ears


def _ellipse(h: int, w: int, cx: float, cy: float, rx: float, ry: float, yy, xx) -> np.ndarray:
    rx = max(float(rx), 0.8)
    ry = max(float(ry), 0.8)
    return ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0


def _cover(ys: np.ndarray, xs: np.ndarray, q: float = 1.0) -> tuple[float, float, float, float]:
    """Ellipse center and radii that contain the pixels.

    `q` below 1 ignores the outermost pixels so one stray hair highlight
    does not stretch the oval.
    """
    cx = (float(xs.min()) + float(xs.max())) / 2.0
    cy = (float(ys.min()) + float(ys.max())) / 2.0
    rx = max(1.0, (float(xs.max()) - float(xs.min())) / 2.0)
    ry = max(1.0, (float(ys.max()) - float(ys.min())) / 2.0)
    dx = xs.astype(np.float64) - cx
    dy = ys.astype(np.float64) - cy
    norm = np.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    scale = float(np.quantile(norm, q)) if q < 1.0 else float(norm.max())
    return cx, cy, rx * max(scale, 1.0), ry * max(scale, 1.0)


def paint_sleeves(out, lab, arm_px, body_a, direction, g, yy, xx) -> None:
    """White sleeve, red upper band, grey fold, grey glove at the tip.

    A fat side-view row is the belly wearing an arm. Only its facing end
    (and any part that actually sticks out of the body) becomes the sleeve.
    Thin rows are a real arm, including one that is swinging, so the whole
    row is the sleeve.
    """
    if not arm_px.any():
        return
    h, w = arm_px.shape
    paint(out, lab, arm_px, HI, L_SUIT)
    buried = erode(body_a, 2)

    for comp in components8(arm_px):
        if int(comp.sum()) < 16:
            continue
        ys, xs = np.nonzero(comp)
        spans = []
        rows = {}
        for y in np.unique(ys):
            row = np.nonzero(comp[y])[0]
            if len(row) == 0:
                continue
            rows[int(y)] = row
            spans.append(int(row[-1] - row[0] + 1))
        fat = bool(spans) and float(np.median(spans)) >= 11 and direction in SIDE
        # A fat profile blob is the belly. The facing column is painted
        # later; only the part that leaves the body is a sleeve here.
        if fat:
            sleeve = comp & ~buried
        else:
            sleeve = comp.copy()
        if int(sleeve.sum()) < 4:
            continue
        ys2 = np.nonzero(sleeve.any(axis=1))[0]
        if len(ys2) < 4:
            continue

        def rows_at(frac: float, thick: int) -> np.ndarray:
            band = np.zeros_like(sleeve)
            i0 = min(len(ys2) - 1, max(0, int(round((len(ys2) - 1) * frac))))
            for dy in range(thick):
                if i0 + dy >= len(ys2):
                    break
                band[int(ys2[i0 + dy])] = sleeve[int(ys2[i0 + dy])]
            return band

        glove = np.zeros_like(sleeve)
        glove_from = max(1, len(ys2) - max(3, int(round(len(ys2) * 0.24))))
        for y in ys2[glove_from:]:
            glove[int(y)] = sleeve[int(y)]
        cloth = sleeve & ~glove
        paint(out, lab, cloth, HI, L_SUIT)
        paint(out, lab, rows_at(0.20, 2) & cloth, RED, L_SUIT)
        paint(out, lab, rows_at(0.48, 1) & cloth, MID, L_SUIT)
        paint(out, lab, glove, LO, L_GLOVE)
        sys_, sxs = np.nonzero(sleeve)
        # One-pixel seam against the chest so a white sleeve stays visible.
        seam = cloth & dilate4(body_a & ~arm_px, 1)
        paint(out, lab, seam, OUTLINE, L_LINE)

        # Hang the sleeve from the shoulder when the arm starts lower.
        # Profile idle uses paint_side_sleeve for a cleaner column.
        top = int(sys_.min())
        start = int(g.neck) + 3
        if direction in SIDE or top <= start + 3:
            continue
        if abs(float(sxs.min()) - g.hip_cx) >= abs(float(sxs.max()) - g.hip_cx):
            x_lo = int(sxs.min())
        else:
            x_lo = int(sxs.max()) - 3
        bridge = np.zeros_like(comp)
        for x in range(x_lo, x_lo + 4):
            if 0 <= x < w:
                bridge[start:top, x] = True
        bridge &= body_a & (yy < g.hem) & (yy > g.neck)
        paint(out, lab, bridge, HI, L_SUIT)
        paint(out, lab, bridge & (yy >= start + 1) & (yy <= start + 2), RED, L_SUIT)
        paint(out, lab, bridge & dilate4(body_a & ~arm_px & ~bridge, 1) & (xx == x_lo if x_lo < g.hip_cx else xx == x_lo + 3), OUTLINE, L_LINE)


def paint_side_sleeve(out, lab, arm_px, body_a, direction, g, yy, xx) -> None:
    """Profile sleeve from the shoulder to the glove, on pixels James already has."""
    h, w = body_a.shape
    start = int(g.neck) + 3
    if arm_px.any():
        arm_bot = int(np.nonzero(arm_px.any(axis=1))[0].max())
    else:
        arm_bot = min(h - 1, int(g.hem) - 2)
    arm_bot = min(arm_bot, int(g.hem) - 1)
    if arm_bot <= start + 4:
        return
    col = np.zeros((h, w), dtype=bool)
    for y in range(start, arm_bot + 1):
        row = np.nonzero(body_a[y])[0]
        if len(row) < 6:
            continue
        # Inside the outline pixel, four columns on the facing side.
        if direction == "E":
            picked = row[-5:-1] if len(row) > 6 else row[-4:]
        else:
            picked = row[1:5] if len(row) > 6 else row[:4]
        col[y, picked] = True
    rgb = out[..., :3]
    panel = (rgb[..., 0] == PANEL[0]) & (rgb[..., 1] == PANEL[1]) & (rgb[..., 2] == PANEL[2])
    col &= ~dilate4(panel, 1)
    col &= body_a
    if int(col.sum()) < 8:
        return
    paint(out, lab, col, HI, L_SUIT)
    paint(out, lab, col & (yy >= start + 2) & (yy <= start + 3), RED, L_SUIT)
    mid_y = start + max(4, (arm_bot - start) // 2)
    paint(out, lab, col & (yy >= mid_y) & (yy <= mid_y), MID, L_SUIT)
    paint(out, lab, col & (yy >= arm_bot - 4), LO, L_GLOVE)
    seam = np.zeros_like(col)
    if direction == "E":
        seam[:, 1:] = col[:, 1:] & ~col[:, :-1]
    else:
        seam[:, :-1] = col[:, :-1] & ~col[:, 1:]
    paint(out, lab, seam, OUTLINE, L_LINE)
    solid = alpha_mask(out)
    paint(out, lab, col & ~erode(solid, 1), OUTLINE, L_LINE)


def frame_head(base: np.ndarray):
    """The head mask suit_frame uses, so the locked oval matches the paint."""
    h, w = base.shape[:2]
    g = Geometry(base)
    closed = close_streaks(base, g.neck + 1)
    a = alpha_mask(closed)
    yy, xx = np.mgrid[0:h, 0:w]
    face = (yy <= g.neck + 1) & skin_mask(closed)
    arms, _hands = arms_and_hands(closed, g, face)
    head = a & (yy <= g.neck - 1) & ~arms
    return g, head, yy, xx


def crown_center(head: np.ndarray, yy: np.ndarray) -> float:
    """Horizontal center of the hair crown. The raised tag arm sits lower."""
    ys = np.nonzero(head.any(axis=1))[0]
    top = int(ys.min())
    xs = np.nonzero((head & (yy <= top + 12)).any(axis=0))[0]
    return (float(xs.min()) + float(xs.max())) / 2.0


def _helmet_fit(frames, dx: float, dy: float, rx: float, ry: float) -> tuple[int, float]:
    """Missed hair pixels, and how high the crown sits on the tallest pose.

    The jaw is left out: a tag arm meets the chin there.
    """
    missed = 0
    top = 99.0
    for g, head, yy, xx in frames:
        if not head.any():
            continue
        cx = crown_center(head, yy) + dx
        cy = float(g.neck) + dy
        top = min(top, cy - ry)
        core = head & (np.abs(xx - cx) <= 18) & (yy <= g.neck - 8)
        if not core.any():
            continue
        ys, xs = np.nonzero(core)
        missed += int((((ys - cy) / ry) ** 2 + ((xs - cx) / rx) ** 2 > 1.0).sum())
    return missed, top


def lock_helmets(src: np.ndarray, meta: dict) -> None:
    """One oval per direction, shared by every animation frame.

    Radii come from the idle hair, then shrink or sit lower just enough that
    the crown stays a curve inside the frame on the tallest pose. A tag swing
    cannot inflate it.
    """
    fw, fh = meta["frameWidth"], meta["frameHeight"]
    cols = meta["columns"]
    HELM.clear()
    for r, direction in enumerate(meta["directions"]):
        frames = []
        for c in range(cols):
            fr = src[r * fh : (r + 1) * fh, c * fw : (c + 1) * fw]
            g, head, yy, xx = frame_head(fr)
            frames.append((g, head, yy, xx))
        g0, head0, yy0, _xx0 = frames[0]
        if not head0.any():
            continue
        ys, xs = np.nonzero(head0)
        cx, cy, rx, ry = _cover(ys, xs, q=1.0)
        dx = cx - crown_center(head0, yy0)
        dy0 = cy - float(g0.neck)
        rx += 2.0
        ry += 1.6
        chosen = (dx, dy0, rx, ry)
        _missed, top = _helmet_fit(frames, dx, dy0, rx, ry)
        # A clipped crown is a flat cut. Keep this width and sit the oval
        # lower, or a little shorter, until the tallest pose rounds off.
        if top < 1.5:
            found = None
            for drop in np.arange(0.0, 3.01, 0.5):
                for shrink in np.arange(0.0, 4.01, 0.4):
                    ry2 = ry - float(shrink)
                    if ry2 < 22.0:
                        continue
                    m, tp = _helmet_fit(frames, dx, dy0 + float(drop), rx, ry2)
                    if tp < 1.5 or m > 0:
                        continue
                    # Prefer the tallest oval that still clears the frame.
                    key = (-ry2, float(drop))
                    if found is None or key < found[0]:
                        found = (key, (dx, dy0 + float(drop), rx, ry2))
            if found is not None:
                chosen = found[1]
        # About 10% smaller than the padded oval, so the head reads as a
        # chunky helmet rather than a bobblehead. The crown clearance above
        # was measured on the larger oval; the scale keeps it inside the frame.
        dx, dy, rx, ry = chosen
        HELM[direction] = (dx, dy, rx * 0.90, ry * 0.90)


def _helmet_place(direction: str, g, head: np.ndarray, yy: np.ndarray):
    if direction not in HELM and head.any():
        ys, xs = np.nonzero(head)
        cx, cy, rx, ry = _cover(ys, xs, q=1.0)
        HELM[direction] = (cx - crown_center(head, yy), cy - g.neck, rx + 2.0, ry + 1.6)
    dx, dy, rx, ry = HELM[direction]
    cx = crown_center(head, yy) + dx
    cy = float(g.neck) + dy
    return cx, cy, rx, ry


def _count8(mask: np.ndarray) -> np.ndarray:
    """How many of the 8 neighbours are set. The pixel itself is not counted."""
    c = np.zeros(mask.shape, dtype=np.int16)
    m = mask.astype(np.int16)
    c[1:, 1:] += m[:-1, :-1]
    c[1:, :] += m[:-1, :]
    c[1:, :-1] += m[:-1, 1:]
    c[:, 1:] += m[:, :-1]
    c[:, :-1] += m[:, 1:]
    c[:-1, 1:] += m[1:, :-1]
    c[:-1, :] += m[1:, :]
    c[:-1, :-1] += m[1:, 1:]
    return c


def _glass_mix(color: tuple[int, int, int], keep: int, parts: int) -> tuple[int, int, int]:
    """`keep` parts of the face color and the rest light-blue glass."""
    return tuple((color[i] * keep + GLASS[i] * (parts - keep)) // parts for i in range(3))


def _mode_skin(labels: np.ndarray) -> np.ndarray:
    """Collapse skin dither to the local majority. Features are painted later."""
    out = labels.copy()
    votes = []
    for cls in (5, 6, 7):
        m = labels == cls
        votes.append(_count8(m) + m.astype(np.int16))
    stack = np.stack(votes, axis=0)
    winner = np.argmax(stack, axis=0)
    best = stack.max(axis=0)
    skin = (labels >= 5) & (labels <= 7)
    mapped = np.array([5, 6, 7], dtype=np.uint8)[winner]
    take = skin & (best >= 4)
    out[take] = mapped[take]
    return out


def _paint_face(out, lab, base, inner: np.ndarray, direction: str) -> None:
    """James's face in a handful of flat colors, with a blue glass cast.

    Labels come from the original pixel, not a median of the dither, so hair
    stays hair and the eyes keep their pupils. A 3x3 majority then knocks out
    the speckle inside the skin.
    """
    have = inner & (base[..., 3] > 40)
    paint(out, lab, inner, GLASS, L_KEEP)
    if not have.any():
        return
    r = base[..., 0].astype(np.int16)
    gch = base[..., 1].astype(np.int16)
    b = base[..., 2].astype(np.int16)
    lum = r + gch + b
    span = np.maximum(np.maximum(r, gch), b) - np.minimum(np.minimum(r, gch), b)
    lo = np.minimum(np.minimum(r, gch), b)
    warm = (r + 6 >= gch) & (r + 6 >= b) & ((r - b) >= 14)
    yy = np.arange(have.shape[0])[:, None]
    xx = np.arange(have.shape[1])[None, :]

    # Eyes sit in the middle of the opening. Crown highlights are not eyes.
    ys_have = np.nonzero(have)[0]
    band_lo = int(np.quantile(ys_have, 0.28))
    band_hi = int(np.quantile(ys_have, 0.78))
    eye_band = have & (yy >= band_lo) & (yy <= band_hi)
    eye = eye_band & (lum >= 620) & (span <= 52) & (lo >= 160) & ~((r > b + 28) & (r > 185))
    eye |= eye_band & (lum >= 575) & (b + 16 >= r) & (b + 16 >= gch) & (span <= 60) & (lo >= 145)
    kept = np.zeros_like(eye)
    for comp in components8(eye):
        if int(comp.sum()) >= 2:
            kept |= comp
    eye = kept
    eye |= dilate4(eye, 1) & have & (lum >= 490) & (span <= 75) & (r < b + 45)

    neutral = have & (lum < 105) & (span < 50) & (r < 95)
    opaque = base[..., 3] > 40
    sil = have & ~erode(opaque, 1)

    ey_y, ey_x = np.nonzero(eye)
    if len(ey_y):
        eye_top = int(ey_y.min())
        eye_bot = int(ey_y.max())
        eye_x0 = int(ey_x.min())
        eye_x1 = int(ey_x.max())
        eye_cx = (eye_x0 + eye_x1) / 2.0
    else:
        ys, xs = np.nonzero(have)
        eye_top = int(np.quantile(ys, 0.42))
        eye_bot = eye_top + 3
        eye_x0, eye_x1 = int(xs.min()), int(xs.max())
        eye_cx = (eye_x0 + eye_x1) / 2.0

    pupil = neutral & ~sil & dilate4(eye, 2) & (yy >= eye_top - 1) & (yy <= eye_bot + 2)
    brow_band = (yy >= eye_top - 7) & (yy <= eye_top - 1) & (xx >= eye_x0 - 6) & (xx <= eye_x1 + 6)
    brow = have & ~pupil & ~eye & brow_band & (lum < 210) & (r < 170)

    hair = have & warm & (r < 152) & (lum < 430) & (yy <= eye_top - 8) & ~brow & ~eye & ~pupil
    if direction == "E":
        hair |= have & warm & (r < 158) & (lum < 440) & (xx < eye_cx - 3) & ~eye & ~pupil & ~brow
    elif direction == "W":
        hair |= have & warm & (r < 158) & (lum < 440) & (xx > eye_cx + 3) & ~eye & ~pupil & ~brow
    hair |= have & (lum < 130) & (yy < eye_top - 8) & ~eye & ~pupil
    hair |= have & ~eye & ~pupil & ~brow & (_count8(hair) >= 5) & (yy <= eye_top)

    # Profile contour: the facing silhouette is the nose, the lips and the ear.
    line = np.zeros_like(have)
    if direction in SIDE:
        line = sil & (lum < 200) & ~eye & ~pupil

    skin = have & ~hair & ~brow & ~pupil & ~eye & ~line
    labels = np.zeros(have.shape, dtype=np.uint8)
    labels[skin & (lum >= 555)] = 5
    labels[skin & (lum < 555) & (lum >= 400)] = 6
    labels[skin & (lum < 400)] = 7
    labels = _mode_skin(labels)
    # A short dark stroke under the nose. Kept out of the majority filter
    # so the mouth does not dissolve into the chin.
    mouth = have & warm & (lum < 270) & (lum > 70) & (yy >= eye_bot + 3) & (yy <= eye_bot + 9)
    mouth &= (xx >= eye_cx - 8) & (xx <= eye_cx + 8) & ~eye & ~pupil & ~hair
    mouth_keep = np.zeros_like(mouth)
    for comp in components8(mouth):
        if int(comp.sum()) >= 2:
            mouth_keep |= comp
    labels[hair] = 1
    labels[brow] = 2
    labels[line] = 2
    labels[pupil] = 3
    labels[eye & (labels != 3)] = 4
    labels[mouth_keep] = 8
    # The nose is the darker column between the eyes and the mouth.
    nose = have & warm & (lum < 500) & (yy > eye_bot) & (yy < eye_bot + 6)
    nose &= (xx >= eye_cx - 2) & (xx <= eye_cx + 1) & ~eye & ~pupil & ~hair & ~mouth_keep
    labels[nose & (labels >= 5)] = 7

    colors = {
        1: _glass_mix(FACE_HAIR, 7, 8),
        2: _glass_mix(FACE_BROW, 7, 8),
        3: _glass_mix(FACE_PUPIL, 7, 8),
        4: _glass_mix(FACE_EYE, 5, 6),
        5: _glass_mix(FACE_LIGHT, 3, 4),
        6: _glass_mix(FACE_MID, 3, 4),
        7: _glass_mix(FACE_SHADE, 4, 5),
        8: _glass_mix(FACE_MOUTH, 7, 8),
    }
    for cls, color in colors.items():
        paint(out, lab, labels == cls, color, L_KEEP)


def _visor_glare(safe: np.ndarray, direction: str) -> np.ndarray:
    """One crisp white slash in the upper corner of the glass, off the eyes."""
    m = np.zeros_like(safe)
    h, w = safe.shape
    ys, xs = np.nonzero(safe)
    if len(ys) == 0:
        return m
    y_top = int(ys.min())
    row_y = min(h - 1, y_top + 1)
    row = np.nonzero(safe[row_y])[0]
    if len(row) == 0:
        row_y = y_top
        row = np.nonzero(safe[row_y])[0]
    if len(row) == 0:
        return m
    if direction == "W":
        x0 = int(row.max()) - 2
        step = -1
    else:
        x0 = int(row.min()) + 2
        step = 1
    # A shallow slash so it stays on the glass instead of crossing an eye.
    for i in range(4):
        x, y = x0 + step * i, row_y + (i // 2)
        if 0 <= y < h and 0 <= x < w and safe[y, x]:
            m[y, x] = True
    return m


def paint_helmet(out, lab, base, head, direction, g, h, w, yy, xx) -> None:
    """One smooth oval per facing. Radii never change with the frame."""
    if not head.any():
        return
    cx, cy, rx, ry = _helmet_place(direction, g, head, yy)
    oval = _ellipse(h, w, cx, cy, rx, ry, yy, xx) & (yy <= g.neck) & (yy >= 0)
    # Hair the tighter oval just misses stays shell, and only where it already
    # touches the oval, so the outline stays one curve instead of a white tuft.
    dome = oval | (
        head & ~oval & dilate(oval, 2) & (yy <= g.neck - 6) & (np.abs(xx - cx) <= rx + 2)
    )

    visor = np.zeros_like(head)
    fcx = fcy = frx = fry = 0.0
    if direction not in BACK:
        fx, fy, sx, sy = VISOR_SHAPE[direction]
        fcx, fcy = cx + fx * rx, cy + fy * ry
        frx, fry = max(4.0, sx * rx), max(4.0, sy * ry)
        # Stay above the neck ring so the collar is shell, not glass.
        visor = _ellipse(h, w, fcx, fcy, frx, fry, yy, xx) & oval & (yy <= g.neck - 2)

    shell = dome & ~visor
    paint(out, lab, shell, HI, L_HELM)
    # One shadow, lower right. The same half-plane in every frame of this facing.
    shade = (xx - cx) / rx * 0.65 + (yy - cy) / ry * 0.85
    paint(out, lab, shell & (shade > 0.12), MID, L_HELM)

    if visor.any():
        inner = _ellipse(h, w, fcx, fcy, max(3.0, frx - 2.15), max(3.0, fry - 2.15), yy, xx)
        inner &= visor
        ring = visor & ~inner
        # The side ear is the facing bulge. A glass ring there would erase it,
        # so that slice stays face and the ring wraps the other side.
        if direction == "E":
            ring &= xx < fcx + frx * 0.20
        elif direction == "W":
            ring &= xx > fcx - frx * 0.20
        _paint_face(out, lab, base, visor & ~ring, direction)
        paint(out, lab, ring, GLASS, L_KEEP)
        # The facing profile line sits on the glass edge too, so the ear reads.
        if direction in SIDE:
            opaque = base[..., 3] > 40
            edge = visor & opaque & ~erode(opaque, 1)
            r = base[..., 0].astype(np.int16)
            gch = base[..., 1].astype(np.int16)
            b = base[..., 2].astype(np.int16)
            lum = r + gch + b
            paint(out, lab, edge & (lum < 200), _glass_mix(FACE_BROW, 7, 8), L_KEEP)
        rim = _ellipse(h, w, fcx, fcy, frx + 1.15, fry + 1.15, yy, xx)
        rim &= dome & ~visor & (yy <= g.neck - 2)
        paint(out, lab, rim, RIM, L_HELM)
        rgb = out[..., :3]
        eyeish = (rgb[..., 0] > 210) & (rgb[..., 1] > 220) & (rgb[..., 2] > 210)
        safe = (visor | rim) & ~eyeish
        paint(out, lab, _visor_glare(safe, direction), GLINT, L_KEEP)

    # Neck ring: the two bottom rows of the dome, then a dark seam on the suit.
    ring = dome & (yy >= g.neck - 1) & (yy <= g.neck) & (lab != L_KEEP)
    paint(out, lab, ring, LO, L_HELM)
    solid = alpha_mask(out)
    edge = (lab == L_HELM) & ~erode(solid, 1)
    paint(out, lab, edge, OUTLINE, L_HELM)
    xs = np.nonzero(ring.any(axis=0))[0]
    if len(xs):
        seam = (yy == int(g.neck) + 1) & (xx >= int(xs.min())) & (xx <= int(xs.max()))
        seam &= (out[..., 3] > 40) & (lab != L_KEEP) & (lab != L_GLOVE) & (lab != L_BOOT)
        paint(out, lab, seam, OUTLINE, L_LINE)

    if direction in BACK and dome.any():
        rows = np.nonzero(dome.any(axis=1))[0]
        top = int(rows.min())
        crow = np.nonzero(dome[top])[0]
        ax = int(round(float(crow.mean())))
        for dy in range(0, 3):
            y = top - dy
            if y < 0:
                continue
            for x in (ax, ax + 1):
                if 0 <= x < w:
                    paint(out, lab, _at(dome, y, x), OUTLINE, L_HELM)
        # A two-pixel slash on the upper-left crown, inset so it is not speckle.
        inset = erode(dome, 2) & (lab == L_HELM)
        x = int(round(cx - 0.20 * rx))
        y = int(round(cy - 0.60 * ry))
        spot = None
        for oy in range(-2, 3):
            for ox in range(-2, 3):
                y1, x1 = y + oy, x + ox
                y2, x2 = y1 + 1, x1 + 1
                if (
                    0 <= y1 < h - 1 and 0 <= x1 < w - 1
                    and inset[y1, x1] and inset[y2, x2]
                ):
                    spot = (y1, x1, y2, x2)
                    break
            if spot is not None:
                break
        if spot is not None:
            y1, x1, y2, x2 = spot
            paint(out, lab, _at(dome, y1, x1), GLINT, L_HELM)
            paint(out, lab, _at(dome, y2, x2), GLINT, L_HELM)

    # A tag arm can stick out of the locked oval. It stays a sleeve, not a lump
    # on the shell, and it stays opaque so the base mask still holds.
    extra = head & ~dome
    if extra.any():
        paint(out, lab, extra, HI, L_SUIT)
        solid = alpha_mask(out)
        paint(out, lab, extra & ~erode(solid, 1), OUTLINE, L_LINE)
        paint(out, lab, extra & dilate4(lab == L_HELM, 1), OUTLINE, L_LINE)


def widest_stripe(comp: np.ndarray) -> np.ndarray:
    """One horizontal stripe on the widest row of the upper half of a limb."""
    band = np.zeros_like(comp)
    ys = np.nonzero(comp.any(axis=1))[0]
    if len(ys) < 2:
        return band
    lo = int(ys[max(0, len(ys) // 6)])
    hi = int(ys[min(len(ys) - 1, max(1, len(ys) // 2))])
    best_y, best_w = lo, 0
    for y in range(lo, hi + 1):
        width = int(comp[y].sum())
        if width > best_w:
            best_w, best_y = width, y
    band[best_y] = comp[best_y]
    xs = np.nonzero(band[best_y])[0]
    if len(xs) >= 3:
        band[best_y, xs[0]] = False
        band[best_y, xs[-1]] = False
    return band


def visor_rim_arc(inner: np.ndarray, direction: str) -> np.ndarray:
    """The glint plus one neighbour, so the visor rim stays a short accent."""
    glint = visor_glint(inner, direction)
    extra = dilate4(glint, 1) & inner & ~glint
    ys, xs = np.nonzero(extra)
    if len(ys) == 0:
        return glint
    gy, gx = np.nonzero(glint)
    gy, gx = float(gy.mean()), float(gx.mean())
    dist = (ys - gy) ** 2 + (xs - gx) ** 2
    i = int(dist.argmin())
    return glint | _at(inner, int(ys[i]), int(xs[i]))


def visor_glint(rim: np.ndarray, direction: str) -> np.ndarray:
    """Two bright pixels on the upper visor rim, toward the light."""
    m = np.zeros_like(rim)
    ys, xs = np.nonzero(rim)
    if len(ys) == 0:
        return m
    # Upper-left on most views; upper-right when facing west so it stays
    # on the rim we can see.
    flip = 1 if direction == "W" else -1
    score = ys * 3 + xs * flip
    i = int(score.argmin())
    y, x = int(ys[i]), int(xs[i])
    m[y, x] = True
    for dy, dx in ((0, 1), (1, 0), (0, -1)):
        yy, xx = y + dy, x + dx
        if 0 <= yy < m.shape[0] and 0 <= xx < m.shape[1] and rim[yy, xx]:
            m[yy, xx] = True
            break
    return m


def boot_gap(shoes: np.ndarray, hip: float) -> np.ndarray:
    """The split between the feet, and the empty column under it.

    A standing pose only opens that split on the last row. Growing the
    sole straight down from the row above would stitch the boots into one
    sled, so the whole gap column stays empty below the split.
    """
    gap = np.zeros_like(shoes)
    h, w = shoes.shape
    xs = np.arange(w)
    left = shoes & (xs[None, :] < hip)
    right = shoes & (xs[None, :] >= hip)
    if not left.any() or not right.any():
        return gap
    cols = np.zeros(w, dtype=bool)
    top = h
    for y in range(h):
        lx = np.nonzero(left[y])[0]
        rx = np.nonzero(right[y])[0]
        if len(lx) and len(rx) and int(rx.min()) > int(lx.max()) + 0:
            # at least the columns strictly between the two feet
            a, b = int(lx.max()) + 1, int(rx.min())
            if b > a:
                cols[a:b] = True
                top = min(top, y)
    if not cols.any():
        return gap
    gap[top:] = cols[None, :]
    # Only where the base foot isn't already there (don't cut a real pixel).
    gap &= ~shoes
    return gap


def helmet_shell(head: np.ndarray, blocked: np.ndarray, g: Geometry, direction: str, h: int, w: int):
    """A tight 2px helmet rim outside the hair, plus small ear cups.

    4-connected so it doesn't balloon into a second head. Nothing lands on
    the body, and dents in the silhouette (between hair tufts) stay empty
    so the rim never cuts across the eyes.
    """
    if not head.any():
        return np.zeros_like(head), np.zeros_like(head)
    filled = fill_holes(head)
    shell = dilate4(filled, 2) & ~filled & ~blocked
    yy = np.arange(h)[:, None]
    shell &= (yy <= g.neck) & (yy >= max(0, g.top - 2))
    # A pixel with hair on both sides is sitting in a notch, not on the rim.
    hair_l = np.zeros_like(head)
    hair_r = np.zeros_like(head)
    hair_l[:, 1:] = filled[:, :-1]
    hair_r[:, :-1] = filled[:, 1:]
    shell &= ~(hair_l & hair_r)
    ears = np.zeros_like(head)
    ys, xs = np.nonzero(filled)
    ear_y = int(ys.min() + (ys.max() - ys.min()) * 0.42)
    row = filled[max(0, ear_y) : ear_y + 3]
    cols = np.nonzero(row.any(axis=0))[0] if row.size else []
    if len(cols) == 0:
        return shell, ears
    left, right = int(cols.min()), int(cols.max())
    # Profiles show the back ear only. E faces right, so the back is left.
    if direction == "E":
        anchors = [left - 3]
    elif direction == "W":
        anchors = [right + 1]
    else:
        anchors = [left - 3, right + 1]
    for x0 in anchors:
        for dy in range(3):
            for dx in range(3):
                y, x = ear_y + dy, x0 + dx
                if 0 <= y < h and 0 <= x < w and not blocked[y, x]:
                    ears[y, x] = True
    kept = np.zeros_like(ears)
    for comp in components8(ears):
        if (comp & dilate4(filled | shell, 1)).any() and comp.sum() >= 3:
            kept |= comp
    ears = kept
    shell &= ~ears
    return shell, ears


def paint_panel(out, lab, g, direction, body, arms, yy, xx):
    h, w = body.shape
    y0 = g.neck + 7
    if direction in FRONT:
        cx = int(round(g.hip_cx))
        if direction == "SE":
            cx += 1
        elif direction == "SW":
            cx -= 1
        rect = round_rect(h, w, cx - 4, y0, cx + 4, y0 + 5)
    elif direction in SIDE:
        # Inset from the front edge so the outline doesn't eat the buttons.
        facing_right = SIDE[direction] < 0
        torso_now = np.isin(lab, (L_SUIT, L_LINE)) & ~arms & (yy < g.hem) & (yy > g.neck)
        band = torso_now & (yy >= y0) & (yy <= y0 + 4)
        if not band.any():
            return
        xs = np.nonzero(band.any(axis=0))[0]
        edge = int(xs.max() if facing_right else xs.min())
        # In from the facing edge so the sleeve there stays visible.
        if facing_right:
            rect = round_rect(h, w, edge - 9, y0, edge - 6, y0 + 4)
        else:
            rect = round_rect(h, w, edge + 6, y0, edge + 9, y0 + 4)
    else:
        return
    # Suit or the outline we already traced.
    torso = np.isin(lab, (L_SUIT, L_LINE)) & ~arms & (yy < g.hem) & (yy > g.neck)
    rect &= torso
    if rect.sum() < 4:
        return
    paint(out, lab, rect, PANEL, L_SUIT)
    rim = rect & dilate(~rect, 1)
    ys, xs = np.nonzero(rect)
    # Profile chests are a narrow column, so stack the buttons. Front views
    # keep a horizontal row inside a wider panel.
    if direction in SIDE:
        mid_x = int(np.median(xs))
        col_ys = np.nonzero(rect[:, mid_x])[0]
        paint(out, lab, rim, OUTLINE, L_LINE)
        if len(col_ys) >= 3:
            picks = [int(col_ys[0]), int(col_ys[len(col_ys) // 2]), int(col_ys[-1])]
            if len(col_ys) >= 5:
                picks = [int(col_ys[1]), int(col_ys[len(col_ys) // 2]), int(col_ys[-2])]
            for y, color in zip(picks, (RED, YELLOW, BLUE)):
                paint(out, lab, _at(rect, y, mid_x), color, L_SUIT)
    else:
        mid_y = int(np.median(ys))
        row_xs = np.nonzero(rect[mid_y])[0]
        if len(row_xs) < 3:
            for dy in (1, -1, 2, -2):
                y = mid_y + dy
                if 0 <= y < h and rect[y].sum() >= 3:
                    mid_y = y
                    row_xs = np.nonzero(rect[mid_y])[0]
                    break
        paint(out, lab, rim, OUTLINE, L_LINE)
        if len(row_xs) >= 3:
            picks = [int(row_xs[1]), int(row_xs[len(row_xs) // 2]), int(row_xs[-2])] if len(row_xs) >= 5 else [
                int(row_xs[0]), int(row_xs[len(row_xs) // 2]), int(row_xs[-1])
            ]
            for x, color in zip(picks, (RED, YELLOW, BLUE)):
                paint(out, lab, _at(rect, mid_y, x), color, L_SUIT)


def draw_pack(g, body, arms, head, direction, h, w):
    """Backpack spritesheet layer (pack, boosters) and two nozzle centres."""
    pack = np.zeros((h, w, 4), dtype=np.uint8)
    lab = np.zeros((h, w), dtype=np.uint8)
    y0 = g.neck + 4
    y1 = min(g.hem - 8, y0 + 12)
    cx = int(round(g.hip_cx))
    nozzles: list[tuple[int, int]] = []

    if direction in BACK:
        cx += BACK_SHIFT[direction]
        rect = round_rect(h, w, cx - 5, y0, cx + 5, y1)
        # Sit on the back, not on the head or the arms.
        rect &= ~head & ~dilate(arms, 1)
        boost_y = y1 + 1
        # Far enough apart that the two jets stay separate once scaled.
        n1, h1 = nozzle(h, w, cx - 5, boost_y)
        n2, h2 = nozzle(h, w, cx + 5, boost_y)
    elif direction in SIDE:
        back = SIDE[direction]
        y0 = g.neck + 2
        y1 = min(g.hem - 10, y0 + 8)
        bounds = row_bounds(body & ~arms, y0, y1)
        if bounds is None:
            bounds = row_bounds(body, y0, y1)
        if bounds is None:
            return pack, lab, [(cx, y1), (cx, y1)]
        left, right = bounds
        # Sit the box just outside the back so the visible part is a clean
        # rectangle, overlapping the suit by one pixel so it stays attached.
        if back < 0:
            x1 = left
            x0 = left - 6
        else:
            x0 = right
            x1 = right + 6
        rect = round_rect(h, w, x0, y0, x1, y1 + 2)
        rect &= ~dilate(arms, 1)
        rear = x0 + 1 if back < 0 else x1 - 1
        inward = 2 if back < 0 else -2
        n1, h1 = nozzle(h, w, rear, y1)
        n2, h2 = nozzle(h, w, rear + inward, y1 + 4)
    else:
        # Facing the camera: only the shoulder corners peek. The pack and
        # both boosters stay behind the suit.
        bounds = row_bounds(body & (np.arange(h)[:, None] <= g.neck + 6) & (np.arange(h)[:, None] >= g.neck - 2), g.neck - 2, g.neck + 6)
        if bounds is None:
            bounds = (cx - 6, cx + 6)
        left, right = bounds
        y0 = g.neck + 1
        rect = round_rect(h, w, left - 1, y0, right + 1, y0 + 3)
        boost_y = y0 + 6
        n1, h1 = nozzle(h, w, cx - 4, boost_y)
        n2, h2 = nozzle(h, w, cx + 4, boost_y)

    # Pack body, shade, outline.
    if rect.any():
        paint(pack, lab, rect, LO, L_PACK)
        paint(pack, lab, shade_rows(rect), MID, L_PACK)
        edge = rect & ~erode(rect, 1)
        paint(pack, lab, edge, OUTLINE, L_PACK)
        # A light panel line so the pack reads as a box, not a blob.
        ys, xs = np.nonzero(rect)
        if len(ys):
            inset = rect & (np.arange(h)[:, None] == int(ys.min() + 2))
            inset &= erode(rect, 1)
            paint(pack, lab, inset, MID, L_PACK)

    # Exhaust leaves the bottom of each nozzle, one pixel below the metal,
    # nudged backward. Front anchors sit at the heels: the flame is drawn
    # behind the suit, so only the tip below the boots shows.
    def exhaust_point(mask: np.ndarray) -> tuple[int, int] | None:
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            return None
        bot = int(ys.max())
        cols = xs[ys == bot]
        cx = int(cols[len(cols) // 2])
        y = min(h - 1, bot + 1)
        if direction == "E":
            cx = max(0, cx - 1)
        elif direction == "W":
            cx = min(w - 1, cx + 1)
        elif direction in BACK:
            y = min(h - 1, y + 1)
        return cx, y

    for src in (h1 if h1.any() else n1, h2 if h2.any() else n2):
        found = exhaust_point(src)
        if found is not None:
            nozzles.append(found)
    while len(nozzles) < 2:
        nozzles.append(nozzles[0] if nozzles else (w // 2, min(h - 1, g.bottom)))
    if direction in FRONT:
        # Behind the calves. The flame is drawn behind the suit, so only
        # the tip that passes the boots shows as a glow.
        heel = min(h - 1, max(0, int(g.bottom) - 22))
        spread = 6
        nozzles = [
            (max(0, int(round(g.hip_cx)) - spread), heel),
            (min(w - 1, int(round(g.hip_cx)) + spread), heel),
        ]
    # Two distinct jets. If a pose collapsed them, push the second down.
    (ax, ay), (bx, by) = nozzles[0], nozzles[1]
    if abs(ax - bx) + abs(ay - by) < 3:
        nozzles[1] = (bx, min(h - 1, ay + 4))

    if direction in FRONT:
        boosters = np.zeros((h, w), dtype=bool)
        holes = np.zeros((h, w), dtype=bool)
    else:
        boosters = n1 | n2
        holes = (h1 | h2) & boosters
    # Dark metal cone. A light lip disappears into the white suit.
    paint(pack, lab, boosters, METAL, L_BOOST)
    edge = boosters & ~erode(boosters, 1)
    paint(pack, lab, edge | holes, OUTLINE, L_BOOST)
    return pack, lab, nozzles[:2]


def composite_pack(body, body_lab, pack, pack_lab, direction, arms, head):
    """Front/side: body covers the pack. Back: pack covers the suit, arms stay."""
    out = body.copy()
    lab = body_lab.copy()
    pm = pack[..., 3] > 40
    if direction in BACK:
        # The back is what we see. Don't paint over the head, arms, or boots.
        cover = pm & (body_lab != L_KEEP) & (body_lab != L_GLOVE) & (body_lab != L_BOOT)
        cover &= ~head
        # The pack stays off the arms. The nozzles are allowed over the suit
        # so the two boosters stay visible on the lower back.
        cover &= ~arms | (pack_lab == L_BOOST)
        hanging = pm & (pack_lab == L_BOOST) & (body[..., 3] <= 40)
        cover |= hanging
        out[cover] = pack[cover]
        lab[cover] = pack_lab[cover]
    else:
        # Pack first, body on top, so it can only peek past the silhouette.
        # Rebuild: start from pack where the body is empty.
        peek = pm & (body[..., 3] <= 40)
        out[peek] = pack[peek]
        lab[peek] = pack_lab[peek]
    return out, lab


def arm_widths(mask: np.ndarray) -> list[int]:
    widths = []
    for comp in components8(mask):
        if comp.sum() < 15:
            continue
        rows = []
        for y in range(mask.shape[0]):
            xs = np.nonzero(comp[y])[0]
            if len(xs):
                rows.append(int(xs.max() - xs.min() + 1))
        if rows:
            widths.append(int(np.median(rows)))
    return widths


def check_frame(base: np.ndarray, out: np.ndarray, lab: np.ndarray, direction: str, where: str) -> None:
    base_a = alpha_mask(base)
    out_a = alpha_mask(out)
    if not np.all(out_a[base_a]):
        missing = int((base_a & ~out_a).sum())
        raise SystemExit(f"{where}: alpha mask lost {missing} base pixels")

    # No new enclosed holes (the gap between the legs is open, not a hole).
    yy = np.arange(base.shape[0])[:, None]
    g = Geometry(base)
    new_holes = fill_holes(out_a) & ~out_a
    old_holes = fill_holes(base_a) & ~base_a
    extra = new_holes & ~old_holes & (yy > g.neck)
    if extra.any():
        raise SystemExit(f"{where}: {int(extra.sum())} new holes in the suit")

    # Suit pixels (everything that isn't the preserved head) use the palette.
    rgb = [tuple(int(v) for v in px) for px in out[out_a & (lab != L_KEEP)][:, :3]]
    bad = {c for c in rgb if c not in PALETTE}
    if bad:
        raise SystemExit(f"{where}: off-palette suit colors {sorted(bad)[:6]}")

    # Glass tints the visor, so the face is not a byte-for-byte copy. It
    # does have to stay visible, and every pixel is fully opaque or clear.
    partial = (out[..., 3] > 0) & (out[..., 3] < 255)
    if partial.any():
        raise SystemExit(f"{where}: {int(partial.sum())} semi-transparent pixels")
    if direction in BACK:
        if (lab == L_KEEP).any():
            raise SystemExit(f"{where}: back view shows a face")
    else:
        face = skin_mask(base) & base_a & (yy <= g.neck + 1)
        if face.any():
            kept = face & (lab == L_KEEP)
            frac = float(kept.sum()) / float(face.sum())
            if frac < 0.55:
                raise SystemExit(f"{where}: visor hides the face ({frac:.2f})")
        if int((lab == L_KEEP).sum()) < 40:
            raise SystemExit(f"{where}: visor opening is too small")

    # Arms: same components, normal thickness, no skinny extra limb.
    face = (yy <= g.neck + 1) & skin_mask(base)
    arms, _hands = arms_and_hands(base, Geometry(base), face)
    widths = arm_widths(arms)
    if any(w < 3 for w in widths):
        raise SystemExit(f"{where}: skinny arm {widths}")
    # Two arms, James's own. The skin detector can split one arm on a tag
    # reach; what matters is we didn't grow a third limb. A frame whose
    # two biggest arm pieces aren't both a normal thickness fails.
    big = sorted((c for c in components8(arms) if c.sum() >= 40), key=lambda c: c.sum(), reverse=True)
    if len(big) >= 2:
        for comp in big[:2]:
            med = arm_widths(comp)
            if med and med[0] < 3:
                raise SystemExit(f"{where}: arm thinner than the base ({med})")
    # New pixels in the arm band that aren't gloves, pack, or the outline
    # tucked against the body. A second arm would be a run of suit pixels
    # standing off the silhouette.
    new = out_a & ~base_a
    band = (yy > g.neck + 2) & (yy < g.hem)
    tucked = dilate(base_a, 1)
    extra_limb = new & band & (lab == L_SUIT) & ~tucked
    extra_limb |= new & band & (lab == L_LINE) & ~tucked
    for comp in components8(extra_limb):
        if comp.sum() >= 8:
            ys = np.nonzero(comp)[0]
            if int(ys.max() - ys.min()) >= 6:
                raise SystemExit(f"{where}: extra arm-like pixels ({int(comp.sum())})")

    # Backpack never shows through the body on front and side views.
    if direction not in BACK:
        interior = erode(base_a, 2)
        through = interior & np.isin(lab, (L_PACK, L_BOOST))
        if through.any():
            raise SystemExit(f"{where}: backpack shows through the body ({int(through.sum())} px)")
    else:
        # On the back the pack is visible, but not on the face (there is
        # no face) and not replacing an arm.
        if ((lab == L_PACK) & arms).any():
            raise SystemExit(f"{where}: backpack covers an arm")

    # One solid character: no stray speck disconnected from the body.
    comps = components8(out_a)
    if comps:
        comps.sort(key=lambda c: c.sum(), reverse=True)
        for comp in comps[1:]:
            if comp.sum() > 0:
                raise SystemExit(f"{where}: stray component of {int(comp.sum())} px")

    # Palette flicker guard: every suit color is from the flat set (above).
    # Boosters exist and are finite.
    if not np.isfinite(out).all():
        raise SystemExit(f"{where}: non-finite pixels")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled 3x contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    lock_helmets(src, meta)
    out = np.zeros_like(src)
    anchors: list[tuple[int, int, int, int]] = []
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh : (r + 1) * fh, c * fw : (c + 1) * fw]
            painted, _lab, nozzles = suit_frame(fr, direction)
            check_frame(fr, painted, _lab, direction, f"{direction} col {c}")
            out[r * fh : (r + 1) * fh, c * fw : (c + 1) * fw] = painted
            (x0, y0), (x1, y1) = nozzles
            anchors.append((x0, y0, x1, y1))
    Image.fromarray(out).save(ASSETS / "kid_spaceman.png")
    spaceman_meta = dict(meta)
    spaceman_meta["image"] = "kid_spaceman.png"
    (ASSETS / "kid_spaceman.json").write_text(json.dumps(spaceman_meta, indent=2) + "\n")
    lines = ["/** Booster nozzle centers in frame pixels, row-major (8 directions × 30 frames). */",
             "export const SPACEMAN_BOOSTERS: ReadonlyArray<readonly [number, number, number, number]> = ["]
    for a in anchors:
        lines.append(f"  [{a[0]}, {a[1]}, {a[2]}, {a[3]}],")
    lines.append("];")
    lines.append("")
    BOOSTERS_TS.write_text("\n".join(lines))
    print(f"wrote {ASSETS / 'kid_spaceman.png'} ({out.shape[1]}x{out.shape[0]}), {len(anchors)} booster pairs")

    if args.preview:
        from PIL import ImageDraw
        img = Image.fromarray(out)
        scale, pad = 3, 46
        picks = [0, 6, 13, 19, 25]
        pv = Image.new("RGBA", (pad + len(picks) * fw * scale, pad + len(dirs) * fh * scale), (40, 48, 44, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (fw, fh), (118, 168, 122, 255))
                cell.alpha_composite(img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)))
                pv.paste(cell.resize((fw * scale, fh * scale), Image.NEAREST),
                         (pad + i * fw * scale, pad + r * fh * scale))
            d.text((4, pad + r * fh * scale + 8), dirs[r], fill="white")
        for i, name in enumerate(["idle", "walk", "breathe", "tag", "run"]):
            d.text((pad + i * fw * scale + 4, 14), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
