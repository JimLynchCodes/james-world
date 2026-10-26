#!/usr/bin/env python3
"""Build the "T-rex James" (Dino James) skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json
Output: public/assets/kid_trex.png + kid_trex.json

Same rows / columns / animation ranges as kid.png, in a padded cell so the
hood snout and tail fit (baselineY shifts down by PAD_TOP).

Per frame:
  1. the whole kid (clothes, arms, legs, shoes) becomes a solid green onesie
     with flat 3-tone shading; holes are filled so the body reads solid;
  2. a tapered spiked tail grows from the lower back.  It is composited
     BEHIND the body for front and side views (S/SE/SW/E/W) and over the
     body only for back views (N/NE/NW);
  3. a T-rex costume hood covers the head: upper jaw + snout with eyes and
     brow ridge above James's real face, pink mouth lining, white teeth on
     both jaw rims, lower jaw under the chin.  Back views are all hood;
  4. claw mittens on the hands, claw booties on the feet.
Hood / tail anchors use per-direction median offsets from the head so the
costume moves rigidly with the kid's bob instead of jittering.

    python3 tools/make_trex_skin.py [--preview /tmp/trex_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 16
PAD_BOTTOM = 6
PAD_SIDE = 20
SS = 4

FACE_DIRS = {"E", "SE", "S", "SW", "W"}
FACE_SIDE = {"E": 1, "SE": 0, "S": 0, "SW": 0, "W": -1}
FACING = {"E": 1, "SE": 1, "S": 0, "SW": -1, "W": -1, "NW": -1, "N": 0, "NE": 1}
TAIL_BEHIND = {"E", "SE", "S", "SW", "W"}

G_LIGHT = (128, 204, 84)
G_MID = (86, 166, 58)
G_DARK = (54, 118, 42)
G_LINE = (24, 62, 30)
SPIKE = (34, 112, 104)
SPIKE_LINE = (14, 48, 46)
PINK = (232, 120, 140)
PINK_DARK = (176, 66, 92)
TOOTH = (255, 252, 240)
TOOTH_LINE = (150, 140, 120)
EYE = (255, 236, 120)
PUPIL = (20, 24, 20)
CLAW = (246, 238, 214)

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


# ---------------------------------------------------------------- drawing

class Canvas:
    """Supersampled vector layer in frame coordinates."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def _p(self, pts):
        return [(x * SS, y * SS) for x, y in pts]

    def ellipse(self, cx, cy, rx, ry, fill, line=None, lw=1.0):
        if line is not None:
            self.d.ellipse([(cx - rx - lw) * SS, (cy - ry - lw) * SS,
                            (cx + rx + lw) * SS, (cy + ry + lw) * SS], fill=line)
        self.d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=fill)

    def poly(self, pts, fill, line=None, lw=1.0):
        p = self._p(pts)
        self.d.polygon(p, fill=fill)
        if line is not None:
            self.d.line(p + [p[0]], fill=line, width=max(1, int(lw * SS)), joint="curve")

    def line(self, pts, fill, lw=1.0):
        self.d.line(self._p(pts), fill=fill, width=max(1, int(lw * SS)), joint="curve")

    def premul(self) -> np.ndarray:
        small = self.img.resize((self.w, self.h), Image.BOX)
        return premul(np.asarray(small))


def tooth(cv: Canvas, x, y, up: bool, size=2.2):
    s = -1 if up else 1
    cv.poly([(x - size * 0.6, y), (x + size * 0.6, y), (x, y + s * size)], TOOTH, TOOTH_LINE, 0.4)


def claw(cv: Canvas, x, y, dx, dy, size=2.0):
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    px, py = -dy, dx
    cv.poly([(x + px * size * 0.55, y + py * size * 0.55),
             (x - px * size * 0.55, y - py * size * 0.55),
             (x + dx * size, y + dy * size)], CLAW, G_LINE, 0.45)


def spike(cv: Canvas, x, y, dx, dy, size=3.0, base=None):
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    px, py = -dy, dx
    b = base if base is not None else size * 0.7
    cv.poly([(x + px * b, y + py * b), (x - px * b, y - py * b),
             (x + dx * size, y + dy * size)], SPIKE, SPIKE_LINE, 0.6)


def bezier(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def tail(cv: Canvas, p0, p1, p2, w0, up_side, spikes=True):
    n = 24
    left, right, mids = [], [], []
    for i in range(n + 1):
        t = i / n
        x, y = bezier(p0, p1, p2, t)
        a = bezier(p0, p1, p2, max(0, t - 0.02))
        b = bezier(p0, p1, p2, min(1, t + 0.02))
        tx, ty = b[0] - a[0], b[1] - a[1]
        l = math.hypot(tx, ty) or 1
        nx, ny = -ty / l, tx / l
        w = w0 * (1 - t) ** 0.85 + 0.35
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
        mids.append((x, y, nx, ny, w))
    # which normal points "up" on screen
    sgn = 1 if mids[n // 2][3] < 0 else -1
    if spikes:
        for i in (4, 9, 14, 19):
            x, y, nx, ny, w = mids[i]
            spike(cv, x + sgn * nx * w * 0.8, y + sgn * ny * w * 0.8, sgn * nx, sgn * ny,
                  2.2 * (1 - i / n) + 1.0)
    cv.poly(left + right[::-1], G_MID, G_LINE, 0.9)
    # flat shadow band along the lower side
    shade = [(x - sgn * nx * w * 0.35, y - sgn * ny * w * 0.35) for x, y, nx, ny, w in mids[:-2]]
    low = [(x - sgn * nx * w * 0.95, y - sgn * ny * w * 0.95) for x, y, nx, ny, w in mids[:-2]]
    cv.poly(shade + low[::-1], G_DARK)


# ---------------------------------------------------------------- body

def box_blur(x: np.ndarray, r: int) -> np.ndarray:
    p = np.pad(x, r, mode="edge")
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def onesie(f: np.ndarray, solid: np.ndarray) -> np.ndarray:
    rgb = f[..., :3].astype(np.float64)
    lum = rgb @ np.array([0.3, 0.59, 0.11])
    a = alpha_mask(f)
    filled_lum = np.where(a, lum, np.nan)
    m = np.nan_to_num(filled_lum, nan=0)
    w = box_blur(a.astype(float), 3)
    local = box_blur(m, 3) / np.maximum(w, 1e-6)
    out = np.zeros(f.shape, dtype=np.float64)
    col = np.empty(f.shape[:2] + (3,))
    col[:] = G_MID
    rel = np.where(a, lum / np.maximum(local, 1), 1.0)
    tone = np.ones(f.shape[:2], dtype=np.int32)
    tone[rel < 0.62] = 0
    # 3x3 majority filter -> flat shading, no speckle
    votes = np.stack([box_blur((tone == k).astype(float), 1) for k in range(3)])
    votes[1] += 0.12
    tone = votes.argmax(0)
    col[tone == 0] = G_DARK
    col[tone == 2] = G_LIGHT
    # silhouette edge
    inner = solid.copy()
    inner[1:] &= solid[:-1]
    inner[:-1] &= solid[1:]
    inner[:, 1:] &= solid[:, :-1]
    inner[:, :-1] &= solid[:, 1:]
    col[solid & ~inner] = G_LINE
    out[..., :3] = col / 255.0
    out[..., 3] = solid.astype(float)
    out[..., :3] *= out[..., 3:4]
    return out


# ---------------------------------------------------------------- per frame

def measure(f, direction):
    g = Geometry(f)
    ell = face_ellipse(f, g, direction)
    return g, ell


def build(frame: np.ndarray, direction: str, col: int, prof: dict) -> np.ndarray:
    f = pad_frame(frame)
    if not alpha_mask(f).any():
        return f
    H, W = f.shape[:2]
    g = Geometry(f)
    fc = FACING[direction]
    top, hcx = g.top, g.head_cx
    hw = prof["hw"]
    a = alpha_mask(f)
    solid = fill_holes(a)
    yy, xx = np.mgrid[0:H, 0:W]

    # face (exact pixels) from the real sprite
    face = np.zeros((H, W), dtype=bool)
    ell = None
    if direction in FACE_DIRS:
        ex, ey, rx, ry = prof["face"]
        ex += hcx
        ey += top
        ell = (ex, ey, rx, ry)
        inside = ((xx + 0.5 - ex) / rx) ** 2 + ((yy + 0.5 - ey) / ry) ** 2 <= 1.0
        sk = grow(loose_skin(f), solid, 1)
        face = inside & fill_holes(sk & inside) & solid

    hands = np.zeros_like(a)
    try:
        _, hands = arms_and_hands(f, g, face)
    except Exception:
        pass

    body = onesie(f, solid)
    sway = math.sin(col * 2 * math.pi / 8) * 0.8

    # ---- tail
    tcv = Canvas(W, H)
    ax = hcx + prof["hip_dx"]
    ay = top + prof["hem_dy"] - 6
    ground = g.bottom - 1
    if direction in ("E", "W"):
        b = -fc
        p0 = (ax + b * 3, ay)
        p1 = (ax + b * 16, ay + 3)
        p2 = (ax + b * 30, ground + sway * 0.5)
        tail(tcv, p0, p1, p2, 5.0, 0)
    elif direction in ("SE", "SW"):
        b = -fc
        p0 = (ax, ay)
        p1 = (ax + b * 12, ay + 4)
        p2 = (ax + b * 22, ground - 1 + sway * 0.5)
        tail(tcv, p0, p1, p2, 5.0, 0)
    elif direction == "S":
        p0 = (ax, ay)
        p1 = (ax + 10, ay + 6)
        p2 = (ax + 19, ground - 1 + sway * 0.5)
        tail(tcv, p0, p1, p2, 5.0, 0)
    elif direction == "N":
        p0 = (ax, ay - 2)
        p1 = (ax + 4, ay + 10)
        p2 = (ax + 15 + sway, ground + 1)
        tail(tcv, p0, p1, p2, 5.5, 0)
    else:  # NE / NW: tail trails behind, toward the viewer
        b = -fc
        p0 = (ax, ay - 2)
        p1 = (ax + b * 9, ay + 8)
        p2 = (ax + b * 22 + sway, ground + 1)
        tail(tcv, p0, p1, p2, 5.5, 0)
    tail_l = tcv.premul()

    # ---- back spikes (behind the body, peeking out along the spine)
    scv = Canvas(W, H)
    neck = top + prof["neck_dy"]
    hem = top + prof["hem_dy"]
    if direction in ("E", "W", "NE", "NW", "SE", "SW"):
        back = -fc
        for y in np.arange(neck + 1, hem - 3, 5.0):
            row = np.nonzero(solid[int(y)] & (np.abs(np.arange(W) - hcx) < 15))[0]
            if not len(row):
                continue
            x = row.min() if back < 0 else row.max()
            spike(scv, x + 0.5 - back * 1.5, y, back, -0.35, 3.2, 1.8)
    spikes_l = scv.premul()

    # ---- hood
    hb = Canvas(W, H)  # hood shell (under face)
    hf = Canvas(W, H)  # jaws / teeth / eyes (over face)
    if ell is None:
        # back view: whole head in hood
        cx = hcx
        if direction != "N":
            # snout nub peeking on the far side
            hb.ellipse(cx + fc * (hw - 1), top + 12, 7, 5.5, G_MID, G_LINE)
            hb.ellipse(cx + fc * (hw - 3), top + 6, 3.2, 2.6, G_MID, G_LINE)
        hb.ellipse(cx, top + 18, hw + 1.5, 19.5, G_MID, G_LINE)
        hb.ellipse(cx - 2, top + 11, hw - 3, 11, G_LIGHT)
        sx = cx - fc * 2.5
        for i, y in enumerate((top + 2, top + 9, top + 16, top + 23, top + 30)):
            s = 4.6 - i * 0.3
            spike(hf, sx - fc * i * 0.6, y + 2, 0, -1, s, s * 0.6)
        for y in np.arange(neck + 5, hem - 1, 6.0):
            spike(hf, sx - fc * 4, y, 0, -1, 4.0, 2.4)
    else:
        ex, ey, rx, ry = ell
        ftop, chin = ey - ry, ey + ry
        if fc == 0 or direction in ("SE", "SW"):
            s = fc * 1.5
            hb.ellipse(hcx, top + 19, hw + 1.5, 20.5, G_MID, G_LINE)
            hb.ellipse(hcx - 3, top + 9, hw - 4, 8, G_LIGHT)
            # pink mouth lining around the face opening
            hb.ellipse(ex, ey + 0.5, rx + 2.3, ry + 2.0, PINK, PINK_DARK, 0.7)
            # lower jaw under the chin
            hf.ellipse(ex + s * 0.5, chin + 2.2, rx + 1.8, 3.2, G_MID, G_LINE, 0.8)
            for i in range(-2, 3):
                tooth(hf, ex + s * 0.5 + i * rx * 0.38, chin + 0.4, True, 2.8)
            # upper jaw / snout band over the forehead
            jy = ftop - 1.5
            hf.ellipse(ex + s, jy, rx + 4.5, 6.2, G_MID, G_LINE, 0.9)
            hf.ellipse(ex + s - 2, jy - 2.5, rx + 1, 2.6, G_LIGHT)
            for i in range(-3, 4):
                tooth(hf, ex + s + i * (rx + 2) * 0.3, jy + 5.2 - abs(i) * 0.6, False, 3.0)
            # nostrils
            for d in (-1, 1):
                hf.ellipse(ex + s + d * 2.6, jy + 1.2, 0.8, 0.6, G_LINE)
            # eyes + brow ridge on top of the snout
            for d in (-1, 1):
                x = ex + s + d * (rx * 0.62) + s * 0.6
                y = jy - 6.0
                r = 2.5 if d * fc >= 0 else 2.1
                hf.ellipse(x, y, r, r, EYE, G_LINE, 0.7)
                hf.ellipse(x + s * 0.4, y + 0.3, r * 0.45, r * 0.62, PUPIL)
                hf.line([(x - d * 3.2, y - 2.0), (x + d * 2.6, y - 3.6)], G_DARK, 1.6)
        else:
            # side profile, facing fc
            hb.ellipse(hcx - fc * 1.5, top + 18, hw + 1.5, 19.5, G_MID, G_LINE)
            hb.ellipse(hcx - fc * 4, top + 9, hw - 5, 8, G_LIGHT)
            for i, y in enumerate((top + 4, top + 11, top + 18, top + 25)):
                spike(hb, hcx - fc * (hw + 1.0 + (i == 0) * -2), y, -fc, -0.4 + i * 0.15, 3.0, 1.8)
            hb.ellipse(hcx - fc * 1.5, top + 18, hw + 1.5, 19.5, G_MID, G_LINE)
            hb.ellipse(hcx - fc * 4, top + 9, hw - 5, 8, G_LIGHT)
            front = ex + fc * rx
            # mouth lining between the jaws in front of the face
            hb.poly([(front - fc * 3, ftop + 1), (front + fc * 6.5, ftop + 2.5),
                     (front + fc * 4.5, chin + 0.5), (front - fc * 3, chin)],
                    PINK, PINK_DARK, 0.7)
            hb.ellipse(ex + fc * 1, ey + 0.5, rx + 1.2, ry + 1.2, PINK)
            # lower jaw
            hf.poly([(ex - fc * (rx + 1), chin), (front + fc * 5, chin + 0.5),
                     (front + fc * 5.5, chin + 2.2), (front + fc * 3.5, chin + 4.0),
                     (ex - fc * (rx + 1), chin + 4.2)], G_MID, G_LINE, 0.8)
            for i in range(3):
                tooth(hf, front + fc * (0.5 + i * 2.4), chin + 0.6, True, 2.8)
            # upper jaw + snout
            jy = ftop + 1.5
            hf.poly([(hcx - fc * 3, top - 1.5), (ex + fc * rx * 0.6, ftop - 8),
                     (front + fc * 7.5, ftop - 4), (front + fc * 9, ftop - 1),
                     (front + fc * 8.5, jy), (ex - fc * rx * 0.5, jy),
                     (hcx - fc * 4, ftop + 4)], G_MID, G_LINE, 0.9)
            hf.poly([(ex - fc * 1, ftop - 6.5), (front + fc * 6.5, ftop - 3.2),
                     (front + fc * 6, ftop - 1.8), (ex - fc * 2, ftop - 3.8)], G_LIGHT)
            for i in range(4):
                tooth(hf, front + fc * (-0.5 + i * 2.5), jy - 0.1, False, 3.0)
            hf.ellipse(front + fc * 7.2, ftop - 2.6, 0.8, 0.6, G_LINE)
            x, y = ex - fc * 0.5, ftop - 6.0
            hf.ellipse(x, y, 2.5, 2.5, EYE, G_LINE, 0.7)
            hf.ellipse(x + fc * 0.8, y + 0.3, 1.1, 1.6, PUPIL)
            hf.line([(x - fc * 3, y - 2.6), (x + fc * 3, y - 3.4)], G_DARK, 1.7)
    hood_b = hb.premul()
    hood_f = hf.premul()

    # ---- claws: hands and feet
    ccv = Canvas(W, H)
    if hands.any():
        for comp in components8(hands):
            if comp.sum() < 3:
                continue
            ys, xs = np.nonzero(comp)
            cx, cy = xs.mean() + 0.5, ys.mean() + 0.5
            dx, dy = cx - hcx, cy - (neck + 4)
            n = math.hypot(dx, dy) or 1
            dx, dy = dx / n, dy / n
            tip = np.argmax((xs - cx) * dx + (ys - cy) * dy)
            tx, ty = xs[tip] + 0.5, ys[tip] + 0.5
            px, py = -dy, dx
            for k in (-1, 0, 1):
                claw(ccv, tx + px * k * 1.3 - dx * 0.6, ty + py * k * 1.3 - dy * 0.6, dx, dy, 1.8)
    foot = solid & (yy >= g.bottom - 6)
    for comp in components8(foot):
        if comp.sum() < 6:
            continue
        ys, xs = np.nonzero(comp)
        if fc != 0 and direction in ("E", "W"):
            x = (xs.max() + 1) if fc > 0 else xs.min()
            for k in range(3):
                claw(ccv, x - fc * 1.2, g.bottom - 0.8 - k * 1.5, fc, 0.25, 1.9)
        elif direction in ("N", "NE", "NW"):
            continue
        else:
            yb = ys.max() + 0.6
            c = xs.mean() + 0.5 + fc * 1.0
            for k in (-1, 0, 1):
                claw(ccv, c + k * 1.7, yb - 0.6, k * 0.35 + fc * 0.3, 1, 1.7)
    claws_l = ccv.premul()

    facepx = premul(f) * face[..., None]

    out = np.zeros((H, W, 4))
    behind = direction in TAIL_BEHIND
    out = over(out, spikes_l)
    if behind:
        out = over(out, tail_l)
    out = over(out, body)
    if not behind:
        out = over(out, tail_l)
    out = over(out, claws_l)
    out = over(out, hood_b)
    out = over(out, facepx)
    out = over(out, hood_f)
    return to_u8(out)


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP + PAD_BOTTOM, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:PAD_TOP + fh, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def profile(frames, direction):
    """Median head-relative anchors for one direction (rigid costume)."""
    faces, hws, hems = [], [], []
    hips = []
    for fr in frames:
        f = pad_frame(fr)
        if not alpha_mask(f).any():
            continue
        g = Geometry(f)
        hws.append(g.head_hw)
        hems.append(g.hem - g.top)
        hips.append(g.hip_cx - g.head_cx)
        e = face_ellipse(f, g, direction)
        if e is not None:
            faces.append((e[0] - g.head_cx, e[1] - g.top, e[2], e[3]))
    p = {"hw": float(np.median(hws)), "hem_dy": float(np.median(hems)),
         "hip_dx": float(np.median(hips)), "neck_dy": 43.0}
    if faces:
        p["face"] = tuple(float(v) for v in np.median(np.array(faces), axis=0))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled 3x contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    out_fw = fw + 2 * PAD_SIDE
    out_fh = fh + PAD_TOP + PAD_BOTTOM
    out = np.zeros((len(dirs) * out_fh, cols * out_fw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        frames = [src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw] for c in range(cols)]
        prof = profile(frames, direction)
        for c, fr in enumerate(frames):
            y0 = r * out_fh
            out[y0:y0 + out_fh, c * out_fw:(c + 1) * out_fw] = build(fr, direction, c, prof)
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
        from PIL import ImageFont  # noqa: F401
        img = Image.fromarray(out)
        sample_cols = [0, 6, 13, 18, 24]
        labels = ["idle", "walk", "breathe", "tag", "run"]
        scale, pad = 3, 40
        cell_w, cell_h = out_fw * scale, out_fh * scale
        pv = Image.new("RGBA", (pad + len(sample_cols) * cell_w, pad + len(dirs) * cell_h),
                       (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r, direction in enumerate(dirs):
            for i, c in enumerate(sample_cols):
                bg = (150, 190, 230, 255) if (r + i) % 2 == 0 else (200, 200, 170, 255)
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
