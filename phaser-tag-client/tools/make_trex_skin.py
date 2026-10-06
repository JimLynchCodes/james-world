#!/usr/bin/env python3
"""Build the "T-rex James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json
Output: public/assets/kid_trex.png + kid_trex.json

Same columns, rows and animation ranges as kid.png. Frames are taller and
wider (PAD_TOP / PAD_BOTTOM / PAD_SIDE) so the dino head crest, dorsal
spikes and long tail fit. The kid art is centred in the padded cell;
baselineY shifts down by PAD_TOP so feet stay correctly anchored.

Every frame gets the same treatment so idle / walk / run / tag / breathe
in every direction keep the kid's own motion:
  1. paste the kid into a padded canvas;
  2. recolour clothing (and shoes) into olive onesie fabric; keep the face;
  3. draw a T-rex costume on top: hooded head with white teeth around a
     mouth opening (front/side views only — back views are all costume),
     lime belly panel, dark-green dorsal spikes, claw mittens over the
     hands, claw booties over the feet, and a prominent spiked tail
     (reads best in side profile; shorter stub on front/back);
  4. put the face back in the mouth opening so it bobs with the body.

Requires: Python 3 + Pillow + numpy.
    python3 tools/make_trex_skin.py [--preview /tmp/trex_preview.png]
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

PAD_TOP = 16
PAD_BOTTOM = 6
PAD_SIDE = 20
SS = 3

FACE_DIRS = {"E", "SE", "S", "SW", "W"}
FACE_SIDE = {"E": 1, "SE": 0, "S": 0, "SW": 0, "W": -1}
# Tail points toward the kid's back (screen-x). Front/back get a short stub.
TAIL_DIR = {
    "E": -1.0, "SE": -0.85, "S": 0.0, "SW": 0.85,
    "W": 1.0, "NW": 0.7, "N": 0.0, "NE": -0.7,
}
TAIL_LEN = {
    "E": 1.0, "SE": 0.9, "S": 0.45, "SW": 0.9,
    "W": 1.0, "NW": 0.75, "N": 0.5, "NE": 0.75,
}

OLIVE = np.array([88, 110, 52], dtype=np.float64)
OLIVE_DARK = np.array([58, 74, 34], dtype=np.float64)
OLIVE_LIGHT = np.array([118, 140, 72], dtype=np.float64)
BELLY = np.array([170, 200, 90], dtype=np.float64)
BELLY_DARK = np.array([130, 160, 60], dtype=np.float64)
SPIKE = np.array([40, 58, 28], dtype=np.float64)
SPIKE_TIP = np.array([28, 40, 18], dtype=np.float64)
TEETH = np.array([245, 245, 240], dtype=np.float64)
OUTLINE = np.array([28, 36, 18], dtype=np.float64)
CLAW = np.array([36, 48, 24], dtype=np.float64)
EYE = np.array([20, 22, 16], dtype=np.float64)


def alpha_mask(f: np.ndarray) -> np.ndarray:
    return f[..., 3] > 40


def skin_mask(f: np.ndarray) -> np.ndarray:
    r, g, b = (f[..., i].astype(np.int32) for i in range(3))
    return alpha_mask(f) & (r > 195) & (g > 130) & (r - b > 70) & (g < r)


def loose_skin(f: np.ndarray) -> np.ndarray:
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
    def __init__(self, f: np.ndarray):
        a = alpha_mask(f)
        rows = np.nonzero(a.any(axis=1))[0]
        self.top = int(rows[0])
        self.bottom = int(rows[-1])
        head = a[self.top:self.top + 34]
        hy, hx = np.nonzero(head)
        self.head_cx = float((hx.min() + hx.max()) / 2)
        self.head_hw = float((hx.max() - hx.min() + 1) / 2)
        self.neck = self.top + 43
        self.hem = find_hem(f, self.head_cx)
        hip = a[self.hem - 4:self.hem].copy()
        xs = np.arange(f.shape[1])
        hip &= np.abs(xs[None, :] - self.head_cx) <= 14
        cols = np.nonzero(hip.any(axis=0))[0]
        self.hip_cx = float((cols.min() + cols.max()) / 2) if len(cols) else self.head_cx
        # feet: bottom-most opaque rows, split left/right of hip
        foot = a[self.bottom - 8:self.bottom + 1]
        fy, fx = np.nonzero(foot)
        self.foot_y = self.bottom - 2
        left = fx[fx < self.hip_cx]
        right = fx[fx >= self.hip_cx]
        self.foot_lx = float(left.mean()) if len(left) else self.hip_cx - 8
        self.foot_rx = float(right.mean()) if len(right) else self.hip_cx + 8


def face_ellipse(f: np.ndarray, g: Geometry, direction: str):
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
        rx *= 0.9
    return cx, cy + 0.5, rx + 0.5, ry + 1.0


def arms_and_hands(f: np.ndarray, g: Geometry, face: np.ndarray):
    a = alpha_mask(f)
    yy = np.arange(f.shape[0])[:, None]
    zone = (yy > g.neck + 2) & (yy < g.hem + 1) & ~face
    sk = loose_skin(f) & zone
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
    arms = arms | grow(arms, a & (lum < 330) & zone, 1)
    return arms, hands


def recolor_onesie(f: np.ndarray, keep: np.ndarray, g: Geometry) -> np.ndarray:
    """Turn clothing + shoes into olive onesie fabric; keep face/skin in `keep`."""
    out = f.astype(np.float64).copy()
    a = alpha_mask(f)
    yy = np.arange(f.shape[0])[:, None]
    # clothing above shins + shoe region (bottom of feet)
    target = a & ~keep & ((loose_skin(f) & (yy < g.hem + 2)) | (yy < g.hem) | (yy > g.bottom - 10))
    # also recolour non-skin opaque pixels that aren't face
    clothes = a & ~keep & ~loose_skin(f) & (yy < g.bottom + 1)
    target = target | clothes
    lum = f[..., :3].astype(np.float64) @ np.array([0.3, 0.55, 0.15])
    shade = 0.55 + 0.45 * (lum / 255.0)
    for i, c in enumerate(OLIVE):
        out[..., i] = np.where(target, np.clip(c * shade, 0, 255), out[..., i])
    # slightly darker toward feet (bootie feel)
    boot = target & (yy > g.hem + 4)
    for i, c in enumerate(OLIVE_DARK):
        out[..., i] = np.where(boot, np.clip(c * shade, 0, 255), out[..., i])
    return out


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


def render_layer(size, paint_fn) -> np.ndarray:
    """Supersampled RGBA premultiplied layer via paint_fn(Y, X) -> (rgb, alpha)."""
    h, w = size
    ys = (np.arange(h * SS) + 0.5) / SS
    xs = (np.arange(w * SS) + 0.5) / SS
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    col, alpha = paint_fn(Y, X)
    col = np.clip(col, 0, 255) / 255.0
    layer = np.concatenate([col * alpha[..., None], alpha[..., None]], axis=-1)
    return layer.reshape(h, SS, w, SS, 4).mean(axis=(1, 3))


def hood_layer(g: Geometry, ell, size, direction: str) -> np.ndarray:
    """T-rex head/hood with mouth opening and teeth; snout leans with facing."""
    h, w = size
    tip = g.top - 10
    bot = g.neck + 6
    cx = g.head_cx
    hw = g.head_hw + 5.0
    # snout stretch toward facing side
    snout = FACE_SIDE.get(direction, 0)
    if direction in ("NW", "N", "NE"):
        snout = 0  # no snout forward on back

    def paint(Y, X):
        # egg-shaped head, slightly elongated forward
        sx = (X - cx) / hw
        if snout:
            # stretch on facing side
            stretch = np.where(np.sign(X - cx) == snout, 1.35, 1.0)
            sx = sx / stretch
        sy = (Y - (tip + bot) / 2) / ((bot - tip) / 2)
        e = sx * sx + sy * sy
        inside = e < 1.0
        # cylinder-ish shading
        light = 1.0 - 0.22 * sx ** 2 + 0.12 * np.exp(-((sx + 0.35) / 0.25) ** 2)
        col = OLIVE[None, None, :] * light[..., None]
        # darker toward top (crest shadow)
        topness = np.clip((tip + 8 - Y) / 8.0, 0, 1)
        col = col * (1 - 0.25 * topness[..., None]) + OLIVE_DARK * 0.25 * topness[..., None]
        edge = (e > 0.82) & inside
        col = np.where(edge[..., None], OUTLINE, col)
        alpha = inside.astype(np.float64)

        # mouth opening (face hole)
        if ell is not None:
            ex, ey, rx, ry = ell
            # make opening a bit taller / wider like a dino mouth
            rx2, ry2 = rx + 1.5, ry + 2.0
            # shift opening slightly down into chin for mouth look
            ey2 = ey + 1.0
            ee = np.hypot((X - ex) / rx2, (Y - ey2) / ry2)
            alpha = np.where(ee < 1.0, 0.0, alpha)
            # white teeth along upper lip of opening
            upper = (ee >= 1.0) & (ee < 1.0 + 1.6 / min(rx2, ry2)) & (Y < ey2) & inside
            # tooth triangles: periodic along x
            tooth = ((X - (ex - rx2)) / max(2.2, rx2 / 3.5)) % 1.0
            tooth_on = (tooth < 0.55) & (ee < 1.0 + 1.4 / min(rx2, ry2))
            col = np.where((upper & tooth_on)[..., None], TEETH, col)
            # dark rim around mouth
            rim = (ee >= 1.0) & (ee < 1.0 + 1.1 / min(rx2, ry2)) & inside
            col = np.where((rim & ~tooth_on)[..., None], OUTLINE, col)

        # small dark dino eyes on the hood (sides of head), skip if opening covers
        for ex_off, ey_off in ((-hw * 0.55, tip + 14), (hw * 0.55, tip + 14)):
            if direction in FACE_DIRS and snout:
                # only show the eye on the facing/back-of-snout side
                if snout > 0 and ex_off < 0:
                    continue
                if snout < 0 and ex_off > 0:
                    continue
            if direction in ("NW", "N", "NE"):
                # both eyes on back? hide — back is spikes
                continue
            er = 1.6
            eye_m = np.hypot(X - (cx + ex_off), Y - ey_off) < er
            col = np.where(eye_m[..., None], EYE, col)
            alpha = np.where(eye_m, np.maximum(alpha, 1.0), alpha)

        return col, alpha

    return render_layer(size, paint)


def belly_layer(g: Geometry, size, direction: str) -> np.ndarray:
    """Lime chest panel — strongest on front (S), fades on sides, none on back."""
    if direction in ("NW", "N", "NE"):
        return np.zeros((*size, 4), dtype=np.float64)
    strength = {"S": 1.0, "SE": 0.75, "SW": 0.75, "E": 0.35, "W": 0.35}.get(direction, 0.5)
    side = FACE_SIDE.get(direction, 0)

    def paint(Y, X):
        cx = g.hip_cx + side * 3
        top = g.neck + 2
        bot = g.hem + 1
        hw = 9.0 * strength + 2
        # oval panel
        sx = (X - cx) / hw
        sy = (Y - (top + bot) / 2) / ((bot - top) / 2 * 0.95)
        e = sx * sx + sy * sy
        inside = e < 1.0
        light = 1.0 - 0.15 * e
        col = BELLY[None, None, :] * light[..., None]
        col = np.where((e > 0.78)[..., None], BELLY_DARK, col)
        alpha = inside.astype(np.float64) * (0.55 + 0.45 * strength)
        return col, alpha

    return render_layer(size, paint)


def spikes_layer(g: Geometry, size, direction: str, tail_pts=None) -> np.ndarray:
    """Dark triangular spikes along the spine / top of head / tail ridge."""
    h, w = size
    # spine x: center for front/back, offset toward back for sides
    td = TAIL_DIR[direction]
    spine_x = g.head_cx - td * (g.head_hw * 0.15 if abs(td) > 0.3 else 0)
    # y positions from crest through back
    ys = list(np.linspace(g.top - 8, g.hem - 2, 7))
    if abs(td) < 0.2:
        # front/back: spikes only on top of head + upper back
        ys = list(np.linspace(g.top - 8, g.neck + 8, 5))
    pts = [(spine_x, float(y), 4.5 - 0.15 * i) for i, y in enumerate(ys)]
    if tail_pts:
        pts.extend(tail_pts)

    def paint(Y, X):
        col = np.zeros((*Y.shape, 3), dtype=np.float64)
        alpha = np.zeros(Y.shape, dtype=np.float64)
        for px, py, sz in pts:
            # triangle pointing up: tip at (px, py - sz), base at py + sz*0.3
            tip_y = py - sz
            base_y = py + sz * 0.35
            half = sz * 0.55
            # distance along height
            t = (Y - tip_y) / max(1e-6, base_y - tip_y)
            in_h = (t >= 0) & (t <= 1)
            half_at = half * t
            in_w = np.abs(X - px) <= half_at
            inside = in_h & in_w
            # tip darker
            tipness = 1.0 - t
            c = SPIKE * (1 - 0.35 * tipness[..., None]) + SPIKE_TIP * 0.35 * tipness[..., None]
            edge = inside & ((np.abs(X - px) > half_at - 0.7) | (t < 0.12))
            c = np.where(edge[..., None], OUTLINE, c)
            col = np.where(inside[..., None], c, col)
            alpha = np.where(inside, 1.0, alpha)
        return col, alpha

    return render_layer(size, paint)


def tail_layer(g: Geometry, size, direction: str):
    """Spiked olive tail. Returns (layer, spike_pts along ridge)."""
    td = TAIL_DIR[direction]
    length = TAIL_LEN[direction]
    if length < 0.2:
        return np.zeros((*size, 4), dtype=np.float64), []

    # attach at mid-back / hip
    ax = g.hip_cx - td * 4
    ay = g.hem - 6
    # tip: back and slightly up
    tip_len = 14 + 18 * length
    tip_x = ax - td * tip_len
    tip_y = ay - 4 - 6 * length

    # clamp tip into frame
    tip_x = float(np.clip(tip_x, 2, size[1] - 3))
    tip_y = float(np.clip(tip_y, 2, size[0] - 3))

    def paint(Y, X):
        # thick tapered sausage from attach to tip
        dx = tip_x - ax
        dy = tip_y - ay
        L = max(1e-6, np.hypot(dx, dy))
        ux, uy = dx / L, dy / L
        # local coords along / across
        along = (X - ax) * ux + (Y - ay) * uy
        across = -(X - ax) * uy + (Y - ay) * ux
        t = along / L
        inside_t = (t >= -0.05) & (t <= 1.05)
        # half-width: thick at base, taper to tip
        hw = (5.5 + 2.5 * length) * np.clip(1.0 - t * 0.85, 0.15, 1.0)
        inside = inside_t & (np.abs(across) < hw)
        light = 1.0 - 0.2 * (across / np.maximum(hw, 1e-6)) ** 2
        col = OLIVE[None, None, :] * light[..., None]
        # darker underside
        under = across > 0
        col = np.where(under[..., None], OLIVE_DARK * light[..., None], col)
        edge = inside & (hw - np.abs(across) < 0.9)
        col = np.where(edge[..., None], OUTLINE, col)
        alpha = inside.astype(np.float64)
        return col, alpha

    layer = render_layer(size, paint)
    # spike points along the top ridge of the tail
    n = max(3, int(4 * length + 2))
    spike_pts = []
    for i in range(n):
        t = (i + 0.5) / n
        px = ax + (tip_x - ax) * t
        py = ay + (tip_y - ay) * t - 2.5  # sit on top ridge
        sz = 3.2 * (1.0 - t * 0.5)
        spike_pts.append((px, py, sz))
    return layer, spike_pts


def claws_layer(g: Geometry, hands: np.ndarray, size, direction: str) -> np.ndarray:
    """Three-toed claw mittens over hands + bulky claw booties on feet."""
    h, w = size
    hand_pts = []
    if hands.any():
        comps = [c for c in components8(hands) if c.sum() >= 4]
        for comp in comps:
            ys, xs = np.nonzero(comp)
            hand_pts.append((float(xs.mean()), float(ys.mean())))
    # if no hands detected (back views often), skip mittens
    foot_pts = [
        (g.foot_lx, float(g.foot_y), True),
        (g.foot_rx, float(g.foot_y), False),
    ]

    def paint(Y, X):
        col = np.zeros((*Y.shape, 3), dtype=np.float64)
        alpha = np.zeros(Y.shape, dtype=np.float64)

        def claw_blob(cx, cy, scale, facing_right):
            # palm oval
            sx = (X - cx) / (4.0 * scale)
            sy = (Y - cy) / (3.2 * scale)
            palm = sx * sx + sy * sy < 1.0
            c = OLIVE_DARK[None, None, :]
            edge = palm & ((sx * sx + sy * sy) > 0.7)
            c = np.where(edge[..., None], OUTLINE, c)
            nonlocal col, alpha
            col = np.where(palm[..., None], c, col)
            alpha = np.where(palm, 1.0, alpha)
            # three toe nails
            for k, ang in enumerate((-0.55, 0.0, 0.55)):
                ox = cx + (1 if facing_right else -1) * (3.2 * scale) * np.cos(ang)
                # feet point down-ish; hands point outward
                oy = cy + 2.8 * scale * (0.4 + abs(ang))
                if not facing_right and scale > 1.2:
                    pass
                nsx = (X - ox) / (1.4 * scale)
                nsy = (Y - oy) / (1.8 * scale)
                nail = nsx * nsx + nsy * nsy < 1.0
                nc = CLAW[None, None, :]
                col = np.where(nail[..., None], nc, col)
                alpha = np.where(nail, 1.0, alpha)

        for hx, hy in hand_pts:
            # hands face outward from body
            facing_right = hx >= g.hip_cx
            claw_blob(hx, hy, 0.95, facing_right)

        for fx, fy, is_left in foot_pts:
            # bulky bootie
            facing_right = not is_left
            # prefer facing the direction of travel for side views
            if direction in ("E", "SE", "NE"):
                facing_right = True
            elif direction in ("W", "SW", "NW"):
                facing_right = False
            claw_blob(fx, fy + 1.0, 1.35, facing_right)

        return col, alpha

    return render_layer(size, paint)


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP + PAD_BOTTOM, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:PAD_TOP + fh, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def trexify(frame: np.ndarray, direction: str) -> np.ndarray:
    f = pad_frame(frame)
    if not alpha_mask(f).any():
        return f
    g = Geometry(f)
    ell = face_ellipse(f, g, direction)
    yy, xx = np.mgrid[0:f.shape[0], 0:f.shape[1]]
    face = np.zeros(f.shape[:2], dtype=bool)
    if ell is not None:
        ex, ey, rx, ry = ell
        face = np.hypot((xx + 0.5 - ex) / (rx + 1.2), (yy + 0.5 - ey) / (ry + 1.5)) < 1.0
    arms, hands = arms_and_hands(f, g, face)
    keep = face  # face shows through mouth; claws cover hands/feet
    dressed = recolor_onesie(f, keep, g)
    dressed_u8 = np.clip(dressed + 0.5, 0, 255).astype(np.uint8)
    dressed_u8[..., 3] = f[..., 3]
    # preserve face pixels exactly
    dressed_u8 = np.where(face[..., None], f, dressed_u8)
    base = premul(dressed_u8)
    size = f.shape[:2]

    # draw order: body (already olive) -> tail (behind) -> hood -> belly -> spikes -> claws -> face on top
    out = base
    tail, spike_pts = tail_layer(g, size, direction)
    # for front views, draw tail behind body (already under since we start from base... 
    # actually over() puts src on top. For S, tail should be behind — draw it under by composing carefully.
    if direction in ("S", "SE", "SW"):
        # tail behind: put tail under current body
        out = over(tail, out)
    else:
        out = over(out, tail)

    out = over(out, hood_layer(g, ell, size, direction))
    out = over(out, belly_layer(g, size, direction))
    out = over(out, spikes_layer(g, size, direction, spike_pts))
    out = over(out, claws_layer(g, hands, size, direction))

    # put original face back through the mouth (sharp)
    if face.any():
        face_layer = premul(f) * face[..., None]
        out = over(out, face_layer)

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
    out_fw = fw + 2 * PAD_SIDE
    out_fh = fh + PAD_TOP + PAD_BOTTOM
    out = np.zeros((len(dirs) * out_fh, cols * out_fw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            y0 = r * out_fh
            out[y0:y0 + out_fh, c * out_fw:(c + 1) * out_fw] = trexify(fr, direction)
    Image.fromarray(out).save(ASSETS / "kid_trex.png", optimize=True)
    trex_meta = dict(meta)
    trex_meta["image"] = "kid_trex.png"
    trex_meta["frameWidth"] = out_fw
    trex_meta["frameHeight"] = out_fh
    trex_meta["baselineY"] = meta["baselineY"] + PAD_TOP
    trex_meta["anchorX"] = out_fw // 2
    (ASSETS / "kid_trex.json").write_text(json.dumps(trex_meta, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_trex.png'} ({out.shape[1]}x{out.shape[0]}) frames {out_fw}x{out_fh}")

    if args.preview:
        from PIL import ImageDraw, ImageFont
        img = Image.fromarray(out)
        # sample key columns: idle0, walk2, run2, tag2
        sample_cols = [0, 6, 24, 18]
        labels = ["idle", "walk", "run", "tag"]
        scale, pad = 2, 48
        cell_w, cell_h = out_fw * scale, out_fh * scale
        pv = Image.new("RGBA",
                       (pad + len(sample_cols) * cell_w + 8,
                        pad + len(dirs) * cell_h + 8),
                       (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r, direction in enumerate(dirs):
            for i, c in enumerate(sample_cols):
                bg = (100, 140, 100, 255) if (r + i) % 2 == 0 else (70, 100, 70, 255)
                cell = Image.new("RGBA", (out_fw, out_fh), bg)
                cell.alpha_composite(img.crop((c * out_fw, r * out_fh,
                                               (c + 1) * out_fw, (r + 1) * out_fh)))
                pv.paste(cell.resize((cell_w, cell_h), Image.NEAREST),
                         (pad + i * cell_w, pad + r * cell_h))
            d.text((4, pad + r * cell_h + 10), direction, fill="white")
        for i, name in enumerate(labels):
            d.text((pad + i * cell_w + 4, 12), name, fill="white")
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
