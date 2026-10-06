#!/usr/bin/env python3
"""Slice the kid presentation spritesheet into a clean Phaser spritesheet.

Source: tools/kid_sheet_source.png (1536x1024 presentation sheet with labels,
cell panels, borders and a notes footer).

Output: public/assets/kid.png - a grid of FRAME_W x FRAME_H frames,
22 columns x 8 rows. Column layout (per row):
    0-3   idle      (4)
    4-11  walk      (8)
    12-15 breathing (4)
    16-21 tag       (6)
Row layout (runtime direction order, matching angle buckets from atan2 in
screen space, 0 = east, increasing clockwise):
    0 E, 1 SE, 2 S, 3 SW, 4 W, 5 NW, 6 N, 7 NE

Also writes public/assets/kid.json with the frame metadata.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/slice_kid_sheet.py [--preview /tmp/preview.png] [--debug DIR]
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "kid_sheet_source.png"
OUT_DIR = HERE.parent / "public" / "assets"

# ---------------------------------------------------------------------------
# Measured layout of the 1536x1024 source sheet (pixel coordinates).
# Row bands are the inner panels between the horizontal border lines.
ROW_BANDS = [  # (y0, y1) exclusive end, per sheet row
    (87, 181),   # N
    (187, 283),  # NE
    (289, 387),  # E
    (393, 495),  # SE
    (502, 600),  # S
    (607, 707),  # SW
    (713, 812),  # W
    (818, 914),  # NW
]
SHEET_ROWS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
# Animation column groups: (name, x0, x1, frame count)
GROUPS = [
    ("idle", 77, 393, 4),
    ("walk", 402, 886, 8),
    ("breathe", 891, 1131, 4),
    ("tag", 1140, 1522, 6),
]

# Which sheet rows feed each runtime direction.
#
# The sheet is an AI-style presentation sheet and is NOT consistent with its
# own labels, so the sources below were picked by inspecting every frame:
#  * every side-view row (NE, E, SE, SW, W, NW) is drawn facing LEFT in the
#    idle/walk/breathing columns (the sheet's own note says to mirror the
#    west-facing rows to get the east-facing ones);
#      - row "E"  = clean left profile            -> W  (mirrored: E)
#      - row "W"  = left profile, face a bit more  -> SW (mirrored: SE)
#        towards the viewer (closest thing to a front-3/4 view)
#      - row "SW" = back-3/4, facing left          -> NW (mirrored: NE)
#    (rows "NE" and "SE" have frames that flip facing mid-walk, so unused);
#  * in the TAG columns the arm always swings out to the viewer's RIGHT and
#    the body faces RIGHT in the arm-out frames, while the first/last frames
#    of several rows face the other way.  So each direction gets a hand-picked
#    frame sequence (sheet tag-frame indices 0..5) whose body faces the same
#    way as the arm; west-facing directions are mirrored so the arm always
#    reaches out in FRONT of the kid.
#    Sequence shape: neutral, bent (wind-up), extended, MOST extended, extended, bent.
BODY_SOURCES = {
    # dir: (sheet row, mirror)
    "E": ("E", True),
    "SE": ("W", True),
    "S": ("S", False),
    "SW": ("W", False),
    "W": ("E", False),
    "NW": ("SW", False),
    "N": ("N", False),
    "NE": ("SW", True),
}
TAG_SOURCES = {
    # dir: (sheet row, [tag frame indices], mirror)
    "E": ("E", [0, 2, 1, 3, 1, 2], False),
    "SE": ("SE", [0, 2, 3, 1, 4, 2], False),
    "S": ("S", [0, 2, 1, 3, 1, 2], False),
    "SW": ("SE", [0, 2, 3, 1, 4, 2], True),
    "W": ("E", [0, 2, 1, 3, 1, 2], True),
    "NW": ("NW", [0, 2, 3, 1, 4, 2], True),
    "N": ("N", [0, 2, 3, 1, 4, 2], False),
    "NE": ("NW", [0, 2, 3, 1, 4, 2], False),
}
DIRECTIONS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]

FRAME_W = 80
FRAME_H = 100
BASELINE_Y = FRAME_H - 4   # feet rest on this row (exclusive bottom of art)
ANCHOR_X = FRAME_W // 2    # head centre is placed on this column
TARGET_H = 89              # normalise figure height (sheet rows vary 85-93px)

# Background keying parameters.
LOOSE_DIST = 18     # first pass: distance to the panel colour (for bg estimate)
TIGHT_DIST = 16     # bg flood: distance to the *local* smoothed background
STRONG_DIST = 30    # definitely-kid pixels
CLOSE_R = 3         # closing radius for the strong-pixel barrier
UPPER_FRAC = 0.6    # top fraction of a band that is keyed without the barrier
HOLE_DIST = 7       # enclosed pockets this close to the local bg become holes
MIN_HOLE = 10
MIN_PART = 80       # drop stray specks smaller than this (in pixels)
BLUR_R = 7          # box radius used to estimate the local background


def color_dist(a: np.ndarray, ref: np.ndarray) -> np.ndarray:
    return np.sqrt(((a - ref) ** 2).sum(-1))


def flood(cand: np.ndarray, seeds) -> np.ndarray:
    h, w = cand.shape
    seen = np.zeros_like(cand, dtype=bool)
    q = deque()
    for y, x in seeds:
        if cand[y, x] and not seen[y, x]:
            seen[y, x] = True
            q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and cand[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def edge_seeds(h: int, w: int):
    return ([(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)]
            + [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)])


def components(mask: np.ndarray) -> list[np.ndarray]:
    """8-connected components, returned as boolean masks."""
    h, w = mask.shape
    labels = np.zeros(mask.shape, dtype=np.int32)
    out = []
    n = 0
    for sy, sx in zip(*np.nonzero(mask)):
        if labels[sy, sx]:
            continue
        n += 1
        labels[sy, sx] = n
        q = deque([(sy, sx)])
        while q:
            y, x = q.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = n
                        q.append((ny, nx))
        out.append(labels == n)
    return out


def box_sum(a: np.ndarray, r: int) -> np.ndarray:
    """Sum over a (2r+1)^2 window (edge-clamped) using an integral image."""
    pad = np.pad(a, [(r + 1, r)] + [(r + 1, r)] + [(0, 0)] * (a.ndim - 2), mode="edge")
    c = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    return box_sum(m.astype(np.int32), r) > 0


def erode(m: np.ndarray, r: int) -> np.ndarray:
    return box_sum(m.astype(np.int32), r) == (2 * r + 1) ** 2


def key_region(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (foreground mask, local-background distance) for a band region."""
    h, w, _ = rgb.shape
    rgbf = rgb.astype(np.float64)
    # 1) Rough background: flood from the region edge over pixels close to
    #    the panel colour (median of the region border ring).
    r_, g_, b_ = rgbf[..., 0], rgbf[..., 1], rgbf[..., 2]
    navy = (r_ < 30) & (b_ - r_ >= 10) & (r_ + g_ + b_ < 130)
    ref = np.median(rgbf[navy], axis=0)
    rough = flood(color_dist(rgbf, ref) < LOOSE_DIST, edge_seeds(h, w))
    # 2) Smooth local background estimate from the rough bg pixels only
    #    (normalised box blur), so panel gradients/glows are followed.
    known = erode(rough, 1) & ~dilate(~rough, 3)
    wsum = box_sum(known.astype(np.float64), BLUR_R)
    csum = box_sum(rgbf * known[..., None], BLUR_R)
    wbig = box_sum(known.astype(np.float64), BLUR_R * 4)
    cbig = box_sum(rgbf * known[..., None], BLUR_R * 4)
    bgimg = np.where(
        (wsum > 8)[..., None],
        csum / np.maximum(wsum, 1)[..., None],
        np.where((wbig > 0)[..., None], cbig / np.maximum(wbig, 1)[..., None], ref),
    )
    d = color_dist(rgbf, bgimg)
    # The outer 2px of the region may touch the panel border lines: treat
    # it as background so figures never get glued to the border.
    edge = np.ones((h, w), dtype=bool)
    edge[2:-2, 2:-2] = False
    d[edge] = 0.0
    # 3) Barrier: pixels that are clearly the kid (far from the local bg),
    #    morphologically closed and hole-filled.  The dark navy shorts/shoes
    #    are close to the bg colour and their outline is not always closed,
    #    so the flood fill must not be allowed to leak through small gaps.
    strong = d > STRONG_DIST
    barrier = erode(dilate(strong, CLOSE_R), CLOSE_R)
    barrier |= ~flood(~barrier, edge_seeds(h, w))
    # 4) Flood fill the background from the edges against the local bg.
    #    Above the shorts (head, shirt, outstretched arm) there are no
    #    bg-like colours in the art, so the barrier is not needed there; this
    #    peels out concave bg corners such as chin/arm gaps in the tag frames.
    upper = np.zeros((h, w), dtype=bool)
    upper[: int(h * UPPER_FRAC)] = True
    bg = flood((d < TIGHT_DIST) & (~barrier | upper), edge_seeds(h, w))
    fg = ~bg
    # 5) Fill holes, then re-open genuine enclosed background pockets.
    outside = flood(~fg, edge_seeds(h, w))
    fg |= ~outside
    pocket = fg & ~strong & (d < HOLE_DIST)
    for comp in components(pocket):
        if comp.sum() >= MIN_HOLE:
            fg &= ~comp
    fg &= ~edge
    return fg, d


def extract_frames(img: np.ndarray, debug: Path | None):
    """Returns {sheet_row: {group: [ (rgba crop, anchor_x, bottom) ...]}}"""
    result = {}
    for row_name, (y0, y1) in zip(SHEET_ROWS, ROW_BANDS):
        result[row_name] = {}
        for gname, x0, x1, count in GROUPS:
            region = img[y0:y1, x0:x1]
            fg, _d = key_region(region)
            comps = []
            for c in components(fg):
                ys, xs = np.nonzero(c)
                if c.sum() < MIN_PART or xs.max() - xs.min() <= 3:
                    continue  # specks and thin border/separator lines
                comps.append((c, xs.min(), xs.max() + 1, c.sum()))
            # Cluster components by horizontal overlap -> one figure each.
            comps.sort(key=lambda t: t[1])
            clusters: list[list] = []
            for c, l, r, n in sorted(comps, key=lambda t: -t[3]):
                for cl in clusters:
                    ov = min(r, cl[2]) - max(l, cl[1])
                    if ov > 0.5 * min(r - l, cl[2] - cl[1]) or (n < 300 and ov > -2):
                        cl[0] |= c
                        cl[1], cl[2] = min(l, cl[1]), max(r, cl[2])
                        break
                else:
                    clusters.append([c.copy(), l, r])
            clusters = [cl for cl in clusters if cl[0].sum() > 600]
            clusters.sort(key=lambda cl: cl[1])
            if len(clusters) != count:
                raise SystemExit(
                    f"{row_name}/{gname}: expected {count} figures, found {len(clusters)}"
                    f" {[(cl[1], cl[2], int(cl[0].sum())) for cl in clusters]}"
                )
            masks = [cl[0] for cl in clusters]
            frames = []
            for i, m in enumerate(masks):
                ys, xs = np.nonzero(m)
                top, bottom = ys.min(), ys.max() + 1
                left, right = xs.min(), xs.max() + 1
                # Horizontal anchor = centre of the head (top 35% of figure),
                # which stays put even when the arm swings out in the tag anim.
                head_rows = m[top: top + int((bottom - top) * 0.35)]
                hy, hx = np.nonzero(head_rows)
                anchor = float(hx.mean())
                rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
                rgba[..., :3] = region
                rgba[..., 3] = np.where(m, 255, 0)
                crop = rgba[top:bottom, left:right]
                frames.append((crop, anchor - left, bottom - top))
                if debug:
                    Image.fromarray(crop).save(debug / f"{row_name}_{gname}_{i}.png")
            result[row_name][gname] = frames
    return result


def place(crop: np.ndarray, anchor_x: float, mirror: bool, scale: float) -> Image.Image:
    im = Image.fromarray(crop)
    if abs(scale - 1.0) > 0.01:
        w0, h0 = im.size
        size = (max(1, round(w0 * scale)), max(1, round(h0 * scale)))
        # Resample with premultiplied alpha so no dark fringes appear.
        im = im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
        anchor_x *= size[0] / w0
    w, h = im.size
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
        anchor_x = w - anchor_x
    frame = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    ox = int(round(ANCHOR_X - anchor_x))
    oy = BASELINE_Y - h
    if ox < 0 or oy < 0 or ox + w > FRAME_W:
        raise SystemExit(f"figure does not fit frame: ox={ox} oy={oy} w={w} h={h}")
    frame.paste(im, (ox, oy), im)
    return frame


def group_scale(frames) -> float:
    return TARGET_H / float(np.median([f[2] for f in frames]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    ap.add_argument("--debug", type=Path, help="dump raw per-frame crops here")
    args = ap.parse_args()
    if args.debug:
        args.debug.mkdir(parents=True, exist_ok=True)

    img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.int32)
    frames = extract_frames(img, args.debug)

    order = [g[0] for g in GROUPS]
    ncols = sum(g[3] for g in GROUPS)
    sheet = Image.new("RGBA", (FRAME_W * ncols, FRAME_H * len(DIRECTIONS)))
    for r, direction in enumerate(DIRECTIONS):
        c = 0
        body_row, body_mirror = BODY_SOURCES[direction]
        tag_row, tag_idx, tag_mirror = TAG_SOURCES[direction]
        for gname in order:
            if gname == "tag":
                src = frames[tag_row]["tag"]
                seq, mirror = [src[i] for i in tag_idx], tag_mirror
            else:
                src = frames[body_row][gname]
                seq, mirror = src, body_mirror
            scale = group_scale(src)
            for crop, ax, _h in seq:
                frame = place(crop.astype(np.uint8), ax, mirror, scale)
                sheet.paste(frame, (c * FRAME_W, r * FRAME_H))
                c += 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_DIR / "kid.png", optimize=True)

    meta = {
        "image": "kid.png",
        "frameWidth": FRAME_W,
        "frameHeight": FRAME_H,
        "baselineY": BASELINE_Y,
        "anchorX": ANCHOR_X,
        "columns": ncols,
        "directions": DIRECTIONS,
        "animations": {},
    }
    c = 0
    for gname, _x0, _x1, count in GROUPS:
        meta["animations"][gname] = {"start": c, "count": count}
        c += count
    (OUT_DIR / "kid.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {OUT_DIR / 'kid.png'} ({sheet.size[0]}x{sheet.size[1]})")

    if args.preview:
        from PIL import ImageDraw
        scale = 2
        pad = 40
        bgc = (110, 160, 110, 255)  # light green so transparency issues show
        pv = Image.new("RGBA", (pad + sheet.size[0] * scale, pad + sheet.size[1] * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(DIRECTIONS)):
            for col in range(ncols):
                x = pad + col * FRAME_W * scale
                y = pad + r * FRAME_H * scale
                cell = Image.new("RGBA", (FRAME_W, FRAME_H), bgc if (r + col) % 2 == 0 else (200, 200, 120, 255))
                fr = sheet.crop((col * FRAME_W, r * FRAME_H, (col + 1) * FRAME_W, (r + 1) * FRAME_H))
                cell.alpha_composite(fr)
                cd = ImageDraw.Draw(cell)
                cd.line([(0, BASELINE_Y), (FRAME_W, BASELINE_Y)], fill=(255, 0, 0, 255))
                cd.line([(ANCHOR_X, 0), (ANCHOR_X, 6)], fill=(255, 0, 0, 255))
                pv.paste(cell.resize((FRAME_W * scale, FRAME_H * scale), Image.NEAREST), (x, y))
            d.text((4, pad + r * FRAME_H * scale + 10), DIRECTIONS[r], fill="white")
        c = 0
        for gname, _a, _b, count in GROUPS:
            d.text((pad + c * FRAME_W * scale + 4, 12), gname, fill="white")
            c += count
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
