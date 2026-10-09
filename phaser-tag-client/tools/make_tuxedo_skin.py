#!/usr/bin/env python3
"""Build the "Tuxedo James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_tuxedo.png + kid_tuxedo.json

Same frame size, columns, rows, animation ranges and feet line as kid.png:
the tuxedo is a re-colour of the kid's own clothes plus small painted
details, so every animation (idle, walk, breathe, tag, run) in every
direction keeps the kid's exact motion and silhouette. Per frame:
  1. T-shirt -> black jacket; bare arms -> black sleeves with a white shirt
     cuff next to each hand (also on the tag reach);
  2. shorts and bare shins -> black trousers (a touch lighter than the
     jacket so the jacket hem / tails read against them);
  3. sneakers -> shiny black dress shoes (dark soles, a glint on the toe);
  4. front views (SE, S, SW): white shirt V between satin lapels, black bow
     tie under the chin, a white pocket square and a jacket button;
     profiles (E, W): a white shirt-front strip and bow-tie nub on the
     facing side; back views (NW, N, NE): centre seam and split tails.
Face, hair and hands are untouched.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_tuxedo_skin.py [--preview /tmp/tuxedo_preview.png]
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
    grow,
    loose_skin,
    skin_mask,
)

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

FRONT = {"SE": 1, "S": 0, "SW": -1}     # screen-x shift of the shirt V
PROFILE = {"E": 1, "W": -1}             # facing side, screen x
BACK = {"NW", "N", "NE"}

OUTLINE = np.array([14, 14, 20], dtype=np.float64)
SHIRT = np.array([246, 246, 250], dtype=np.float64)
SHIRT_SHADE = np.array([205, 208, 220], dtype=np.float64)
SATIN = np.array([92, 92, 112], dtype=np.float64)
BOW = np.array([10, 10, 14], dtype=np.float64)
BUTTON = np.array([120, 120, 135], dtype=np.float64)
GLINT = np.array([200, 205, 225], dtype=np.float64)


def lum(f: np.ndarray) -> np.ndarray:
    return f[..., :3].astype(np.float64) @ np.array([0.3, 0.55, 0.15])


def fabric(l: np.ndarray, base: float, k: float, tint: float = 5.0) -> np.ndarray:
    """Near-black cloth keeping the original light/shade (cool tint)."""
    v = base + k * l
    return np.stack([v, v, v + tint], axis=-1)


def torso_rows(jacket: np.ndarray):
    rows = np.nonzero(jacket.any(axis=1))[0]
    return (int(rows[0]), int(rows[-1])) if len(rows) else (None, None)


def row_span(mask: np.ndarray, y: int):
    xs = np.nonzero(mask[y])[0]
    return (int(xs.min()), int(xs.max())) if len(xs) else (None, None)


def close_streaks(f: np.ndarray, top: int) -> np.ndarray:
    """The run frames have 1-2px see-through horizontal streaks across the
    arms / legs (slicing artefacts). Barely visible on the T-shirt, they
    flash green through a black suit, so fill gaps that have body pixels
    directly above and below (below the neck only)."""
    f = f.copy()
    h = f.shape[0]
    for gap in (1, 2):
        a = alpha_mask(f)
        for y in range(max(top, 1), h - gap - 1):
            hole = ~a[y]
            for k in range(1, gap):
                hole &= ~a[y + k]
            fill = hole & a[y - 1] & a[y + gap]
            if not fill.any():
                continue
            src = f[y - 1].astype(np.int32) + f[y + gap].astype(np.int32)
            for k in range(gap):
                f[y + k][fill] = (src[fill] // 2).astype(np.uint8)
                f[y + k, fill, 3] = 255
    # pinholes: see-through pixels mostly surrounded by body
    for _ in range(6):
        a = alpha_mask(f)
        nb = np.zeros(a.shape, dtype=np.int32)
        nb[1:] += a[:-1]
        nb[:-1] += a[1:]
        nb[:, 1:] += a[:, :-1]
        nb[:, :-1] += a[:, 1:]
        # small enclosed see-through pockets count as pinholes too, and so
        # do 1-2px notches that a morphological closing would fill
        enclosed = fill_holes(a) & ~a
        dil = a.copy()
        dil[1:] |= a[:-1]; dil[:-1] |= a[1:]; dil[:, 1:] |= a[:, :-1]; dil[:, :-1] |= a[:, 1:]
        ero = dil.copy()
        ero[1:] &= dil[:-1]; ero[:-1] &= dil[1:]; ero[:, 1:] &= dil[:, :-1]; ero[:, :-1] &= dil[:, 1:]
        closed = ero & ~a
        pin = ~a & ((nb >= 3) | ((enclosed | closed) & (nb >= 1)))
        pin[:top] = False
        if not pin.any():
            break
        ys, xs = np.nonzero(pin)
        for y, x in zip(ys, xs):
            ring = [f[yy, xx] for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1))
                    if 0 <= yy < f.shape[0] and 0 <= xx < f.shape[1] and f[yy, xx, 3] > 40]
            f[y, x] = np.mean(ring, axis=0).astype(np.uint8)
            f[y, x, 3] = 255
    return f


def tuxify(frame: np.ndarray, direction: str) -> np.ndarray:
    f = frame.copy()
    a = alpha_mask(f)
    if not a.any():
        return f
    g = Geometry(f)
    f = close_streaks(f, g.neck + 2)
    a = alpha_mask(f)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    L = lum(f)
    out = f[..., :3].astype(np.float64).copy()

    # Face = skin above the neck; arms/hands from the shared helper.
    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & arms, 1)  # whole hand stays bare
    sk = loose_skin(f)
    outline = a & (L < 40)

    waist = g.hem - 9                       # T-shirt bottom ~ 9 rows above the shins
    clothes = a & (yy > g.neck) & ~sk & ~outline
    jacket = clothes & (yy <= waist)
    trousers = clothes & (yy > waist) & (yy < g.hem + 2)
    shins = a & sk & (yy >= g.hem) & ~arms
    # shoes: everything non-skin under the shins
    shoes = a & (yy >= g.hem + 3) & ~sk & ~shins
    # a lower-leg band so the trousers reach the shoes even where the art
    # has outline pixels between shin and shoe
    sleeves = arms & ~hands & sk

    # --- recolour ----------------------------------------------------------
    jacket_col = fabric(L, 26.0, 0.22)
    trouser_col = fabric(L, 40.0, 0.2)
    out = np.where(jacket[..., None], jacket_col, out)
    out = np.where(sleeves[..., None], fabric(L * 0.55, 26.0, 0.22), out)
    out = np.where(trousers[..., None], trouser_col, out)
    # bare shins are much brighter than the shorts: scale them down so the
    # trouser leg is one even colour from hip to shoe
    out = np.where(shins[..., None], fabric(L * 0.38, 40.0, 0.2), out)
    shoe_col = fabric(L, 12.0, 0.12, 4.0)
    soles = shoes & (L > 150)
    out = np.where(shoes[..., None], shoe_col, out)
    out = np.where(soles[..., None], np.array([34.0, 34.0, 40.0]), out)

    # the art's dark shading specks on the clothes (navy / reddish) -> neutral
    specks = outline & (yy > g.neck + 1) & ~hands & ~face & (yy < g.hem + 2)
    grey = np.clip(L * 0.8, 6.0, 30.0)
    out = np.where(specks[..., None], np.stack([grey, grey, grey + 4.0], axis=-1), out)

    # white shirt cuff: sleeve pixels touching the hand
    cuff = grow(hands, sleeves, 2) & sleeves
    out = np.where(cuff[..., None], SHIRT, out)

    # glint on each shoe (top-front pixel of each shoe blob)
    for comp in components8(shoes & ~soles):
        if comp.sum() < 4:
            continue
        ys, xs = np.nonzero(comp)
        top = ys.min()
        row = xs[ys == top + 1] if (ys == top + 1).any() else xs[ys == top]
        side = PROFILE.get(direction, 0)
        x = int(row.max() if side > 0 else row.min() if side < 0 else np.median(row))
        y = int(top + 1)
        if comp[y, x]:
            out[y, x] = GLINT

    # --- details ---------------------------------------------------------------
    jtop, jbot = torso_rows(jacket | (sleeves & (yy < waist)))
    body = jacket.copy()
    # paintable torso: every opaque pixel of the chest except the arms
    chest = a & ~arms & (yy > g.neck - 1) & (yy <= waist)
    if jtop is not None:
        cx = g.head_cx
        if direction in FRONT:
            cx += FRONT[direction] * 1.5
            depth = 12
            for i in range(depth):
                y = jtop + i
                half = 4.6 * (1 - i / depth) + 0.5
                l, r = row_span(body, y)
                if l is not None:
                    # don't touch the outline at the sides of the body
                    l, r = l + 1, r - 1
                if l is None:
                    continue
                for x in range(l, r + 1):
                    if not chest[y, x]:
                        continue
                    d = x + 0.5 - cx
                    if abs(d) < half:
                        out[y, x] = SHIRT if abs(d) < half - 1.2 or i < 2 else SHIRT_SHADE
                    elif abs(d) < half + 1.6:
                        out[y, x] = SATIN        # satin lapel edge
            # bow tie just under the collar
            by = jtop + 1
            for dx, dys in ((-3, (0, 1, 2)), (-2, (0, 1, 2)), (-1, (1,)), (0, (0, 1, 2)),
                            (1, (1,)), (2, (0, 1, 2)), (3, (0, 1, 2))):
                x = int(np.floor(cx)) + dx
                for dy in dys:
                    if 0 <= by + dy < h and 0 <= x < w and a[by + dy, x]:
                        out[by + dy, x] = BOW
            # jacket button below the V, and the pocket square (wearer's left)
            bx, byy = int(np.floor(cx)), jtop + depth + 1
            if byy < h and body[byy, bx]:
                out[byy, bx] = BUTTON
            side = 1 if direction != "SW" else 1
            px = int(round(cx + 6 * side))
            for dx in (0, 1, 2):
                for dy in (0, 1):
                    y, x = jtop + 5 + dy, px + dx
                    if body[y, x] and abs(x + 0.5 - cx) > 5:
                        out[y, x] = SHIRT if dy == 0 or dx == 1 else SHIRT_SHADE
        elif direction in PROFILE:
            s = PROFILE[direction]
            for i in range(9):
                y = jtop + i
                l, r = row_span(body, y)
                if l is None:
                    continue
                edge = r if s > 0 else l
                for k in range(2 if i < 7 else 1):
                    x = edge - k * s
                    if body[y, x]:
                        out[y, x] = SHIRT if k == 0 else SATIN
            # bow-tie nub sticking out at the collar
            l, r = row_span(body, jtop + 1)
            if l is not None:
                x = (r + 1) if s > 0 else (l - 1)
                for dy in (0, 1, 2):
                    if 0 <= x < w:
                        out[jtop + dy, x] = BOW
                        f[jtop + dy, x, 3] = 255
        elif direction in BACK:
            # centre seam down the back
            sx = int(round(g.hip_cx - 0.5))
            for y in range(jtop + 4, waist + 1):
                if body[y, sx]:
                    out[y, sx] = np.array([14.0, 14.0, 18.0])
            # tails: jacket colour continues over the seat, split at the seam
            for y in range(waist + 1, min(g.hem - 1, waist + 6)):
                l, r = row_span(trousers, y)
                if l is None:
                    continue
                inset = (y - waist) // 2
                for x in range(l + inset, r - inset + 1):
                    if trousers[y, x] and abs(x - sx) > (y - waist) // 2:
                        out[y, x] = jacket_col[y, x] * 0.85
                    elif trousers[y, x]:
                        out[y, x] = np.array([14.0, 14.0, 18.0])

    # faint / greenish motion-blur pixels below the neck (run frames) would
    # glow on a black suit: tint them suit-dark
    fr = f[..., :3].astype(np.int32)
    greenish = (fr[..., 1] > fr[..., 0] + 12) & (fr[..., 1] > fr[..., 2])
    faint = (f[..., 3] > 0) & ~a
    blur = (yy > g.neck + 1) & ~hands & (faint | (greenish & a & ~sk))
    out = np.where(blur[..., None], np.array([22.0, 22.0, 28.0]), out)

    res = f.copy()
    res[..., :3] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    # semi-transparent pixels inside the suit (motion-blur blends) let the
    # ground show through as specks: make them solid
    al = res[..., 3].astype(np.int32)
    solid = al > 200
    nb = np.zeros(al.shape, dtype=np.int32)
    nb[1:] += solid[:-1]
    nb[:-1] += solid[1:]
    nb[:, 1:] += solid[:, :-1]
    nb[:, :-1] += solid[:, 1:]
    inner = (al > 0) & ~solid & (nb >= 3) & (yy > g.neck + 1)
    res[..., 3] = np.where(inner, 255, res[..., 3])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled 3x contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    out = np.zeros_like(src)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw] = tuxify(fr, direction)
    Image.fromarray(out).save(ASSETS / "kid_tuxedo.png", optimize=True)
    tux_meta = dict(meta)
    tux_meta["image"] = "kid_tuxedo.png"
    (ASSETS / "kid_tuxedo.json").write_text(json.dumps(tux_meta, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_tuxedo.png'} ({out.shape[1]}x{out.shape[0]})")

    if args.preview:
        from PIL import ImageDraw
        img = Image.fromarray(out)
        scale, pad = 3, 40
        picks = [0, 6, 13, 18, 26]   # idle, walk, breathe, tag reach, run
        pv = Image.new("RGBA", (pad + len(picks) * fw * scale, pad + len(dirs) * fh * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (fw, fh), (120, 170, 120, 255))
                cell.alpha_composite(img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)))
                pv.paste(cell.resize((fw * scale, fh * scale), Image.NEAREST),
                         (pad + i * fw * scale, pad + r * fh * scale))
            d.text((4, pad + r * fh * scale + 10), dirs[r], fill="white")
        for i, name in enumerate(["idle", "walk", "breathe", "tag", "run"]):
            d.text((pad + i * fw * scale + 4, 12), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
