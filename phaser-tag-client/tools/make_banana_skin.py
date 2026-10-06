#!/usr/bin/env python3
"""Build the "Banana James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_banana.png + kid_banana.json

Same columns, rows and animation ranges as kid.png, so the same animation
code drives both skins. Frames are taller (FRAME_H + PAD) because the
banana tip and stem stick up above the head; the kid art is pasted PAD px
lower, so the feet stay PAD px further down (baselineY in the json).

Every frame gets the same treatment, so every animation (idle, walk,
breathing, tag, run) in every direction keeps the kid's own motion:
  1. the outfit underneath turns black: sleeves/arms and legs become dark
     (long sleeves + leggings), hands, face and shoes stay as they are;
  2. a yellow banana costume is drawn on top: a tube from a pointed tip
     (brown stem) above the head down to about the knees (brown end), with
     cylinder shading, two lengthwise ridges and a dark outline. It is
     placed from the frame itself (head top/centre, shorts hem, hip
     centre), so it bobs, leans and hops with the body;
  3. front and side views get an oval opening for the face (fitted to the
     face's skin pixels); back views (NW, N, NE) are all banana;
  4. the arms (re-coloured black, hands kept) are drawn back on top, as if
     they came out of arm holes in the costume.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_banana_skin.py [--preview /tmp/banana_preview.png]
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD = 20            # extra rows on top of every frame for the tip and stem
SS = 4              # supersampling for the costume shape
TIP_RISE = 15       # banana tip this far above the top of the hair (px)
STEM_H = 5
HOOD_FULL = 18      # costume reaches full width this far below the hair top
NECK = 43           # neck row below the hair top (head is ~44px of 89)
SKULL = 34          # rows below the hair top that are only head (no tag arm)
BELOW_HEM = 3       # costume bottom edge below the shorts hem (about the knee)
BOTTOM_TAPER = 9

FACE_DIRS = {"E", "SE", "S", "SW", "W"}
# Screen-x side of each direction's face (profiles cut the hole on the
# facing side only; 0 = both).
FACE_SIDE = {"E": 1, "SE": 0, "S": 0, "SW": 0, "W": -1}
# Which way the tip (and a little the bottom end) curves, in screen x:
# towards the kid's back, so the banana arcs like the real fruit in
# profile; a slight lean in the straight-on views like the reference photo.
BEND = {"E": -1.0, "SE": -0.7, "S": 0.3, "SW": 0.7, "W": 1.0, "NW": 0.7, "N": -0.3, "NE": -0.7}

YELLOW = np.array([255, 216, 48], dtype=np.float64)
YELLOW_DARK = np.array([214, 158, 22], dtype=np.float64)
OUTLINE = np.array([92, 58, 14], dtype=np.float64)
RIM = np.array([170, 112, 18], dtype=np.float64)
BROWN = np.array([96, 60, 26], dtype=np.float64)
BROWN_OUTLINE = np.array([38, 22, 10], dtype=np.float64)


def alpha_mask(f: np.ndarray) -> np.ndarray:
    return f[..., 3] > 40


def skin_mask(f: np.ndarray) -> np.ndarray:
    r, g, b = (f[..., i].astype(np.int32) for i in range(3))
    return alpha_mask(f) & (r > 195) & (g > 130) & (r - b > 70) & (g < r)


def loose_skin(f: np.ndarray) -> np.ndarray:
    """Skin incl. its shaded edges (arms and legs)."""
    r, g, b = (f[..., i].astype(np.int32) for i in range(3))
    return alpha_mask(f) & (r > 150) & (r - b > 55) & (g > 80) & (g < r)


def components8(mask: np.ndarray) -> list[np.ndarray]:
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        comp = np.zeros_like(mask, dtype=bool)
        q = deque([(y, x)])
        seen[y, x] = True
        while q:
            cy, cx = q.popleft()
            comp[cy, cx] = True
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
        out.append(comp)
    return out


def grow(mask: np.ndarray, within: np.ndarray, r: int = 1) -> np.ndarray:
    m = mask.copy()
    for _ in range(r):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g & within
    return m


def fill_holes(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    outside = np.zeros_like(mask)
    q = deque()
    for y in range(h):
        for x in (0, w - 1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and not mask[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                q.append((ny, nx))
    return ~outside


def find_hem(f: np.ndarray, centre: float) -> int:
    """Top row of the bare shins (= bottom of the shorts), from the feet up."""
    sk = skin_mask(f)
    xs = np.arange(f.shape[1])
    sk &= np.abs(xs[None, :] - centre) <= 16
    rows = sk.sum(axis=1) >= 2
    bottom = int(np.nonzero(alpha_mask(f).any(axis=1))[0][-1])
    y = bottom
    while y > bottom - 25 and not rows[y]:
        y -= 1
    while y > bottom - 16 and rows[y - 1]:
        y -= 1
    return y


class Geometry:
    """Where the costume goes in one (padded) frame."""

    def __init__(self, f: np.ndarray):
        a = alpha_mask(f)
        rows = np.nonzero(a.any(axis=1))[0]
        self.top = int(rows[0])
        self.bottom = int(rows[-1])
        head = a[self.top:self.top + SKULL]
        hy, hx = np.nonzero(head)
        self.head_cx = float((hx.min() + hx.max()) / 2)
        self.head_hw = float((hx.max() - hx.min() + 1) / 2)
        self.neck = self.top + NECK
        self.hem = find_hem(f, self.head_cx)
        hip = a[self.hem - 4:self.hem].copy()
        xs = np.arange(f.shape[1])
        hip &= np.abs(xs[None, :] - self.head_cx) <= 14
        cols = np.nonzero(hip.any(axis=0))[0]
        self.hip_cx = float((cols.min() + cols.max()) / 2) if len(cols) else self.head_cx


def costume_profile(g: Geometry, half: float, bend: float, f: np.ndarray | None = None):
    """Centre x and half width of the costume for (float) rows y."""
    tip = g.top - TIP_RISE
    full = g.top + HOOD_FULL
    bot = g.hem + BELOW_HEM

    def centre(y):
        # head -> hip line (lean), plus the banana curve at both ends
        t = np.clip((y - g.neck) / max(1.0, g.hem - g.neck), 0.0, 1.0)
        c = g.head_cx + (g.hip_cx - g.head_cx) * t
        up = np.clip((g.top + 4 - y) / (g.top + 4 - tip), 0.0, 1.0)
        down = np.clip((y - (bot - 12)) / 12.0, 0.0, 1.0)
        return c + bend * (7.0 * up ** 2 + 2.5 * down ** 2)

    # rows of the head that the hood must cover (so no hair pokes out)
    need = {}
    if f is not None:
        a = alpha_mask(f)
        for yi in range(g.top, g.top + SKULL):
            xs = np.nonzero(a[yi])[0]
            if len(xs):
                c = float(centre(np.array([yi + 0.5]))[0])
                need[yi] = max(c - xs.min(), xs.max() + 1 - c) + 1.3
    if need:
        half = max(half, max(need.values()))

    def arch(y):
        u = np.clip((y - tip) / (full - tip), 0.0, 1.0)
        return half * u ** 0.6

    # widen the arch where the head is wider, keeping it monotone
    lift = 0.0
    for yi in sorted(need):
        lift = max(lift, need[yi] - float(arch(np.array([yi + 0.5]))[0]))
    lift = min(lift, half)

    def width(y):
        w = np.minimum(half, arch(y) + lift * np.clip((y - tip) / (full - tip), 0.0, 1.0) ** 0.25)
        body = np.clip((y - g.neck) / max(1.0, bot - g.neck), 0.0, 1.0)
        w = np.where(y >= g.neck, half + 1.0 * np.sin(np.pi * body), w)
        v = np.clip((y - (bot - BOTTOM_TAPER)) / BOTTOM_TAPER, 0.0, 1.0)
        w = np.where(y > bot - BOTTOM_TAPER, np.maximum(3.0, w * np.sqrt(np.maximum(0.0, 1 - v ** 2 * 0.85))), w)
        w = np.where((y < tip) | (y > bot), 0.0, w)
        return w

    return tip, bot, centre, width


def face_ellipse(f: np.ndarray, g: Geometry, direction: str):
    """(cx, cy, rx, ry) of the face opening, or None for back views."""
    if direction not in FACE_DIRS:
        return None
    sk = skin_mask(f)
    zone = np.zeros_like(sk)
    zone[g.top + 12:g.neck + 1] = True
    xs = np.arange(f.shape[1])
    zone &= np.abs(xs[None, :] - g.head_cx) <= g.head_hw
    side = FACE_SIDE[direction]
    if side:
        zone &= (xs[None, :] - g.head_cx) * side >= -2
    comps = sorted(components8(sk & zone), key=lambda c: -c.sum())
    if not comps or comps[0].sum() < 30:
        return None
    face = comps[0]
    for c in comps[1:]:
        if c.sum() >= 12:
            face |= c
    face = fill_holes(face)
    ys, xs_ = np.nonzero(face)
    cx, cy = (xs_.min() + xs_.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2
    rx = (xs_.max() - xs_.min() + 1) / 2
    ry = (ys.max() - ys.min() + 1) / 2
    if side:
        rx *= 0.95
    else:
        rx *= 0.86          # hide the ears under the hood
    return cx, cy + 0.5, rx, ry + 0.5


def black_outfit(f: np.ndarray, keep: np.ndarray, g: Geometry) -> np.ndarray:
    """Black long sleeves and leggings: re-colour skin (except `keep`) and
    every clothing pixel above the shins; shoes stay."""
    out = f.astype(np.float64).copy()
    a = alpha_mask(f)
    yy = np.arange(f.shape[0])[:, None]
    target = a & ~keep & (loose_skin(f) | (yy < g.hem))
    lum = f[..., :3].astype(np.float64) @ np.array([0.3, 0.55, 0.15])
    v = 16.0 + 0.2 * lum
    out[..., 0] = np.where(target, v, out[..., 0])
    out[..., 1] = np.where(target, v, out[..., 1])
    out[..., 2] = np.where(target, v + 6.0, out[..., 2])
    return out


def arms_and_hands(f: np.ndarray, g: Geometry, face: np.ndarray):
    """Arm skin below the neck (not the shins), and the hand end of each arm."""
    a = alpha_mask(f)
    yy = np.arange(f.shape[0])[:, None]
    zone = (yy > g.neck + 2) & (yy < g.hem + 1) & ~face
    sk = loose_skin(f) & zone
    # bridge 1px gaps (dark shading lines across the arm) before splitting
    lum = f[..., :3].astype(np.int32).sum(-1)
    sk = sk | (grow(sk, a & zone, 1) & grow(grow(sk, a & zone, 1) & ~sk, sk, 1) & (lum < 360))
    comps = [c for c in components8(sk) if c.sum() >= 10]
    arms = np.zeros_like(sk)
    hands = np.zeros_like(sk)
    sx, sy = g.head_cx, g.neck + 6.0
    for comp in comps:
        ys, xs = np.nonzero(comp)
        d = np.hypot(xs - sx, (ys - sy) * 0.8)
        far = d >= d.max() - 4.0
        arms |= comp
        hands[ys[far], xs[far]] = True
    hands &= loose_skin(f)
    # the dark outline around the arm belongs to the arm layer too
    arms = arms | grow(arms, a & (lum < 330) & zone, 1)
    return arms, hands


def render_costume(shape_hw, shape_cx, tip, bot, ellipse, size):
    """Premultiplied RGBA costume layer (float 0..1), supersampled."""
    h, w = size
    ys = (np.arange(h * SS) + 0.5) / SS
    xs = (np.arange(w * SS) + 0.5) / SS
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    cx = shape_cx(ys)[:, None]
    hw = shape_hw(ys)[:, None]
    s = (X - cx) / np.maximum(hw, 1e-6)
    inside = (np.abs(s) < 1.0) & (hw > 0)
    edge_d = np.minimum(hw - np.abs(X - cx), np.minimum(Y - tip, bot - Y))
    # cylinder shading with a highlight left of centre
    light = 1.0 - 0.28 * s ** 2 + 0.16 * np.exp(-((s + 0.38) / 0.2) ** 2)
    col = YELLOW[None, None, :] * light[..., None]
    # greenish-brown toward both ends, like a real banana
    endness = np.clip(np.maximum((tip + 9 - Y) / 9.0, (Y - (bot - 4)) / 4.0), 0.0, 1.0)
    col = col * (1 - 0.35 * endness[..., None]) + YELLOW_DARK * 0.35 * endness[..., None]
    # two lengthwise ridges
    ridge = (np.minimum(np.abs(s - 0.5), np.abs(s + 0.5)) * hw < 0.5) & (Y > tip + 10) & (Y < bot - 3)
    col = np.where(ridge[..., None], col * 0.82, col)
    col = np.where((edge_d < 1.1)[..., None], OUTLINE, col)
    alpha = inside.astype(np.float64)
    if ellipse is not None:
        ex, ey, rx, ry = ellipse
        e = np.hypot((X - ex) / rx, (Y - ey) / ry)
        rim = (e >= 1.0) & (e < 1.0 + 1.3 / min(rx, ry))
        col = np.where((rim & inside)[..., None], RIM, col)
        alpha = np.where(e < 1.0, 0.0, alpha)
    col = np.clip(col, 0, 255) / 255.0
    layer = np.concatenate([col * alpha[..., None], alpha[..., None]], axis=-1)
    return layer.reshape(h, SS, w, SS, 4).mean(axis=(1, 3))


def render_rect(cx: float, y0: float, y1: float, half: float, size) -> np.ndarray:
    """Brown stem / end piece (premultiplied, supersampled, outlined)."""
    h, w = size
    ys = (np.arange(h * SS) + 0.5) / SS
    xs = (np.arange(w * SS) + 0.5) / SS
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    dx = np.abs(X - cx)
    inside = (dx < half) & (Y >= y0) & (Y < y1)
    edge = (half - dx < 0.9) | (Y - y0 < 0.9) | (y1 - Y < 0.9)
    col = np.where(edge[..., None], BROWN_OUTLINE, BROWN) / 255.0
    a = inside.astype(np.float64)
    layer = np.concatenate([col * a[..., None], a[..., None]], axis=-1)
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


def bananafy(frame: np.ndarray, direction: str, half: float) -> np.ndarray:
    fw = frame.shape[1]
    f = np.zeros((frame.shape[0] + PAD, fw, 4), dtype=np.uint8)
    f[PAD:] = frame
    if not alpha_mask(f).any():
        return f
    g = Geometry(f)
    bend = BEND[direction]
    tip, bot, cx_of, hw_of = costume_profile(g, half, bend, f)
    ell = face_ellipse(f, g, direction)
    yy, xx = np.mgrid[0:f.shape[0], 0:fw]
    face = np.zeros(f.shape[:2], dtype=bool)
    if ell is not None:
        ex, ey, rx, ry = ell
        face = np.hypot((xx + 0.5 - ex) / (rx + 1), (yy + 0.5 - ey) / (ry + 1)) < 1.0
    arms, hands = arms_and_hands(f, g, face)
    keep = face | hands
    dressed = black_outfit(f, keep, g)
    dressed_u8 = np.clip(dressed + 0.5, 0, 255).astype(np.uint8)
    dressed_u8[..., 3] = f[..., 3]
    base = premul(dressed_u8)
    size = f.shape[:2]
    out = over(base, render_costume(hw_of, cx_of, tip, bot, ell, size))
    # stem on the tip, dark end at the bottom
    out = over(out, render_rect(float(cx_of(np.array([tip]))[0]), tip - STEM_H, tip + 1.5, 1.8, size))
    out = over(out, render_rect(float(cx_of(np.array([bot]))[0]), bot - 1.0, bot + 4.0, 3.5, size))
    # arms (black sleeves, bare hands) in front of the costume
    out = over(out, base * arms[..., None])
    result = to_u8(out)
    result[result[..., 3] < 8] = 0
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled 2x contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    out = np.zeros((len(dirs) * (fh + PAD), cols * fw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        frames = [src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw] for c in range(cols)]
        # one costume width per direction (median head width) so it doesn't
        # pulse from frame to frame
        widths = []
        for fr in frames:
            p = np.zeros((fh + PAD, fw, 4), dtype=np.uint8)
            p[PAD:] = fr
            if alpha_mask(p).any():
                widths.append(Geometry(p).head_hw)
        half = float(np.median(widths)) + 1.5
        for c, fr in enumerate(frames):
            y0 = r * (fh + PAD)
            out[y0:y0 + fh + PAD, c * fw:(c + 1) * fw] = bananafy(fr, direction, half)
    Image.fromarray(out).save(ASSETS / "kid_banana.png", optimize=True)
    banana_meta = dict(meta)
    banana_meta["image"] = "kid_banana.png"
    banana_meta["frameHeight"] = fh + PAD
    banana_meta["baselineY"] = meta["baselineY"] + PAD
    (ASSETS / "kid_banana.json").write_text(json.dumps(banana_meta, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_banana.png'} ({out.shape[1]}x{out.shape[0]})")

    if args.preview:
        from PIL import ImageDraw
        img = Image.fromarray(out)
        scale, pad = 2, 40
        pv = Image.new("RGBA", (pad + img.width * scale, pad + img.height * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for c in range(cols):
                cell = Image.new("RGBA", (fw, fh + PAD), (110, 160, 110, 255) if (r + c) % 2 == 0 else (150, 190, 140, 255))
                cell.alpha_composite(img.crop((c * fw, r * (fh + PAD), (c + 1) * fw, (r + 1) * (fh + PAD))))
                pv.paste(cell.resize((fw * scale, (fh + PAD) * scale), Image.NEAREST),
                         (pad + c * fw * scale, pad + r * (fh + PAD) * scale))
            d.text((4, pad + r * (fh + PAD) * scale + 10), dirs[r], fill="white")
        c = 0
        for name, a in meta["animations"].items():
            d.text((pad + a["start"] * fw * scale + 4, 12), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
