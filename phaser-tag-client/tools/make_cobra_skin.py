#!/usr/bin/env python3
"""Generate the "Cobra James" skin: James's real head (from kid.png) on a
raised cobra body with a wide hood. The body is a pseudo-3D tube projected
per facing direction and painted at 4x, then downsampled.

Animations follow kid.json: idle (sway), walk/run (S-wave slither), breathe,
tag (head darts forward, fangs out).

    python3 tools/make_cobra_skin.py   # writes public/assets/kid_cobra.png/json
"""
import json, math, os
import numpy as np
from PIL import Image, ImageDraw

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solid_mask import solidify  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "public", "assets")
BW, BH = 80, 100            # base frame
OW, OH = 136, 124           # output frame (30*136 = 4080 <= 4096)
PADX, PADY = (OW - BW) // 2, 14
GY = 96 + PADY              # ground / baseline in output
SS = 4
PROJ = 0.42                 # ground depth -> screen y
COLS = 30
DIRS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
R2 = math.sqrt(0.5)
FWD = {"E": (1, 0), "SE": (R2, R2), "S": (0, 1), "SW": (-R2, R2),
       "W": (-1, 0), "NW": (-R2, -R2), "N": (0, -1), "NE": (R2, -R2)}

LINE = (52, 40, 32)
COIL = (186, 168, 140)
SHADE = (142, 126, 104)
SCALE = (160, 142, 116)
BELLY = (238, 228, 206)
BAND = (198, 182, 156)
SPOT = (54, 40, 32)
RIM = (232, 220, 198)
FANG = (252, 252, 246)
MOUTH = (110, 30, 34)
NECK_Y = 50                 # base head bottom (Geometry.neck)


def anim_of(col):
    if col < 4: return "idle", col, 4
    if col < 12: return "walk", col - 4, 8
    if col < 16: return "breathe", col - 12, 4
    if col < 22: return "tag", col - 16, 6
    return "run", col - 22, 8


class Canvas:
    """4x RGBA paint surface."""
    def __init__(self):
        self.rgb = np.zeros((OH * SS, OW * SS, 3), np.float32)
        self.a = np.zeros((OH * SS, OW * SS), np.float32)

    def paint(self, mask, colour):
        m = mask.astype(np.float32)
        self.rgb = self.rgb * (1 - m[..., None]) + np.array(colour, np.float32) * m[..., None]
        self.a = np.maximum(self.a, m)

    def down(self):
        h, w = OH, OW
        a = self.a.reshape(h, SS, w, SS).mean((1, 3))
        pm = (self.rgb * self.a[..., None]).reshape(h, SS, w, SS, 3).mean((1, 3))
        rgb = np.where(a[..., None] > 0, pm / np.maximum(a[..., None], 1e-6), 0)
        return np.dstack([rgb, a * 255]).clip(0, 255)


def new_mask():
    return Image.new("L", (OW * SS, OH * SS), 0)


def arr(im):
    return np.asarray(im) > 127


def circles(pts, grow=0.0, off=(0, 0), scale=1.0):
    im = new_mask(); d = ImageDraw.Draw(im)
    for x, y, r in pts:
        rr = max(0.3, r * scale + grow) * SS
        cx, cy = (x + off[0] * r) * SS, (y + off[1] * r) * SS
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    return arr(im)


def poly(points):
    im = new_mask()
    ImageDraw.Draw(im).polygon([(x * SS, y * SS) for x, y in points], fill=255)
    return arr(im)


def ellipse(cx, cy, rx, ry):
    im = new_mask()
    ImageDraw.Draw(im).ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=255)
    return arr(im)


def dilate(m, n):
    out = m.copy()
    for _ in range(n):
        o = out.copy()
        o[1:] |= out[:-1]; o[:-1] |= out[1:]; o[:, 1:] |= out[:, :-1]; o[:, :-1] |= out[:, 1:]
        out = o
    return out


class Proj:
    def __init__(self, d, ax):
        self.fx, self.fy = FWD[d]
        self.lx, self.ly = -self.fy, self.fx
        self.ax = ax

    def __call__(self, f, s, z):
        gx = f * self.fx + s * self.lx
        gy = f * self.fy + s * self.ly
        return self.ax + gx, GY + gy * PROJ - z, gy


def tube(cv, pts, outline=0.85, dots=True):
    """pts: list of (x, y, r) in screen px. Ring then fill (single outline)."""
    ring = circles(pts, grow=0)
    fill = circles(pts, grow=-outline)
    light = circles(pts, grow=-outline, off=(-0.12, -0.26), scale=0.66) & fill
    cv.paint(ring, LINE)
    cv.paint(fill, SHADE)
    cv.paint(light, COIL)
    if dots:
        dm = new_mask(); dd = ImageDraw.Draw(dm)
        for i, (x, y, r) in enumerate(pts[::5]):
            for k in (-1, 1):
                ox = x + k * 0.3 * r * (1 if (i % 2) else 0.6)
                oy = y - 0.15 * r
                rr = 0.55 * SS
                dd.ellipse([ox * SS - rr, oy * SS - rr, ox * SS + rr, oy * SS + rr], fill=255)
        cv.paint(arr(dm) & light, SCALE)
    return ring


def body_path(p, anim, k, n):
    """Trailing body on the ground, S-wave slither. Returns (x,y,r,depth)."""
    if anim == "walk":
        phase, amp, cyc = 2 * math.pi * k / n, 6.5, 1.25
    elif anim == "run":
        phase, amp, cyc = 4 * math.pi * k / n, 9.0, 1.5
    else:
        sway = math.sin(2 * math.pi * k / max(n, 1))
        phase, amp, cyc = 0.35 * sway, 4.0, 1.0
    L = 50.0 if anim != "run" else 54.0
    pts = []
    N = 140
    for i in range(N + 1):
        u = i / N
        a = amp * min(1.0, u * 2.2)
        s = a * math.sin(2 * math.pi * cyc * u - phase) - amp * 0.0
        f = -L * u + 1.5
        r = 6.4 * (1 - u) ** 0.55 + 0.7
        x, y, dep = p(f, s, 0)
        pts.append((x, y - r * 0.55, r, dep))
    return pts


def mouth_of(head_rgba, d):
    """Locate the mouth on the base idle head (front-ish views only)."""
    h = head_rgba
    a = h[..., 3] > 0
    r, g, b = [h[..., i].astype(int) for i in range(3)]
    lum = (r + g + b) / 3
    ys, xs = np.nonzero(a)
    chin = ys.max()
    cand = a & (r > g + 28) & (lum < 150)
    cand[: chin - 16] = False
    cand[chin - 3:] = False
    yy, xx = np.nonzero(cand)
    if len(xx) == 0:
        return None
    my = 43.5                       # smile row on every base head
    fx = FWD[d][0]
    if abs(fx) > 0.9:               # profile: just inside the front edge
        row = np.nonzero(a[int(my)])[0]
        mx = (row.max() - 2.5) if fx > 0 else (row.min() + 2.5)
    else:
        mx = float(xx.mean())
    return float(mx), my


def head_of(base, d):
    """Head pixels of the base idle frame (hair + face, no shirt)."""
    row = DIRS.index(d)
    f = base[row * BH:(row + 1) * BH, 0:BW].copy()
    r, g, b, a = [f[..., i].astype(int) for i in range(4)]
    keep = a > 0
    yy = np.arange(BH)[:, None]
    keep &= yy <= NECK_Y + 1
    # drop the grey tee collar under the chin
    tee = (abs(r - g) < 14) & (abs(g - b) < 16) & (yy >= NECK_Y - 7) & (r < 140)
    keep &= ~tee
    f[~keep] = 0
    return f


def render(base, d, col, mouths):
    anim, k, n = anim_of(col)
    head = head_of(base, d)
    ys, xs = np.nonzero(head[..., 3])
    hcx = (xs.min() + xs.max()) / 2 + PADX
    p = Proj(d, hcx)
    fx, fy = p.fx, p.fy
    lx = p.lx

    # pose
    sway = lean = dart = bob = 0.0
    fangs = False
    if anim in ("idle", "breathe"):
        sway = 1.6 * math.sin(2 * math.pi * k / n)
        bob = 0.6 * math.sin(2 * math.pi * k / n + 1)
    elif anim == "walk":
        sway = 1.4 * math.sin(2 * math.pi * k / n)
        bob = 0.8 * math.sin(4 * math.pi * k / n)
        lean = 1.5
    elif anim == "run":
        sway = 2.0 * math.sin(4 * math.pi * k / n)
        bob = 1.0 * math.sin(4 * math.pi * k / n)
        lean = 4.0
    elif anim == "tag":
        dart = [0.0, -3.0, 9.0, 14.0, 8.0, 2.0][k]
        fangs = k in (2, 3, 4)
    zt = GY - (NECK_Y + PADY - 7) + bob - (1.5 if anim == "tag" and k in (2, 3) else 0)

    def neck_fs(z):
        u = max(0.0, min(1.0, z / zt))
        return lean * u ** 1.5 + dart * u ** 2.2 - 1.0 * math.sin(math.pi * u), sway * u

    def neck_r(z):
        u = max(0.0, min(1.0, z / zt))
        return 6.4 - 1.4 * u

    cv = Canvas()
    body = body_path(p, anim, k, n)
    neck_pts = []
    for i in range(80):
        z = zt * i / 79
        f, s = neck_fs(z)
        x, y, _ = p(f, s, z)
        neck_pts.append((x, y - 0.0, neck_r(z)))
    # neck base merges into the body start
    neck_pts.insert(0, (body[0][0], body[0][1], body[0][2]))

    behind = fy > 0.3 or abs(fy) <= 0.3     # body trails away from viewer (or sideways)

    # hood geometry
    z0, z1 = zt - 40, zt + 8
    edgeL, edgeR, centre = [], [], []
    Wmax = 29.0
    for i in range(41):
        u = i / 40
        z = z0 + (z1 - z0) * u
        w = Wmax * math.sin(math.pi * min(1, u ** 0.85)) ** 0.75
        w = max(w, neck_r(z) + 0.5)
        f, s = neck_fs(z)
        f -= 1.5 if abs(lx) > 0.3 else 4.5
        cx, cy, _ = p(f, s, z)
        hw = max(w * abs(lx), neck_r(z) + 1.0 + 6.5 * (1 - abs(lx)) * math.sin(math.pi * min(1, u ** 0.85)) ** 0.75)
        # lateral vector on screen (x only, y compression)
        sx = 1 if lx >= 0 else -1
        dy = w * p.ly * PROJ * sx if abs(lx) > 0.3 else 0
        edgeL.append((cx - hw, cy - dy * 0))
        edgeR.append((cx + hw, cy + dy * 0))
        centre.append((cx, cy, hw, u))
    hood_poly = edgeL + edgeR[::-1]

    def draw_hood():
        outer = poly(hood_poly)
        cv.paint(dilate(outer, 3), LINE)
        front = fy > 0.3
        back = fy < -0.3
        cv.paint(outer, SHADE)
        inner = poly([(cx - hw * 0.78, cy) for cx, cy, hw, u in centre] +
                     [(cx + hw * 0.78, cy) for cx, cy, hw, u in centre[::-1]]) & outer
        if front:
            cv.paint(inner, COIL)
            bel = poly([(cx - hw * 0.42, cy) for cx, cy, hw, u in centre] +
                       [(cx + hw * 0.42, cy) for cx, cy, hw, u in centre[::-1]]) & outer
            cv.paint(bel, BELLY)
            # bands
            bm = new_mask(); bd = ImageDraw.Draw(bm)
            for cx, cy, hw, u in centre[1::4]:
                bd.line([((cx - hw * 0.42) * SS, cy * SS), ((cx + hw * 0.42) * SS, cy * SS)], fill=255, width=3)
            cv.paint(arr(bm) & bel, BAND)
            # dark throat spots like the reference
            for cx, cy, hw, u in centre:
                if abs(u - 0.42) < 0.013:
                    for kk in (-1, 1):
                        cv.paint(ellipse(cx + kk * hw * 0.6, cy, max(1.2, hw * 0.1), 3.2) & inner, SPOT)
        else:
            cv.paint(inner, COIL)
            if back:
                for cx, cy, hw, u in centre:
                    if abs(u - 0.36) < 0.013:
                        for kk in (-1, 1):
                            ex = cx + kk * hw * 0.42
                            rx = max(1.6, 3.6 * abs(lx))
                            cv.paint(ellipse(ex, cy, rx + 1.1, 4.6) & outer, SPOT)
                            cv.paint(ellipse(ex, cy, rx * 0.62 + 0.3, 3.0) & outer, RIM)
                            cv.paint(ellipse(ex, cy + 0.3, rx * 0.3, 1.5) & outer, SPOT)

    def draw_neck():
        tube(cv, neck_pts, dots=False)
        if fy > -0.3:
            # pale banded belly on the front of the neck
            off = 0.45 * fx
            wsc = 0.42 + 0.28 * max(0.0, fy)
            bp = [(x + off * r, y, r * wsc) for x, y, r in neck_pts[3:]]
            fill = circles(neck_pts, grow=-0.85)
            bel = circles(bp) & fill
            cv.paint(bel, BELLY)
            bm = new_mask(); bd = ImageDraw.Draw(bm)
            for x, y, r in neck_pts[6::7]:
                bd.line([((x - r) * SS, y * SS), ((x + r) * SS, y * SS)], fill=255, width=3)
            cv.paint(arr(bm) & bel, BAND)

    def draw_body():
        pts = [(x, y, r) for x, y, r, _ in body]
        # chunk for self-overlap (painter order with seamless joins)
        CH = 20
        chunks = []
        for i in range(0, len(pts), CH):
            lo, hi = i, min(len(pts), i + CH + 1)
            dep = np.mean([b[3] for b in body[lo:hi]])
            chunks.append((dep, lo, hi))
        chunks.sort()
        for dep, lo, hi in chunks:
            seg = pts[lo:hi]
            ring = circles(seg)
            ext = pts[max(0, lo - 4):min(len(pts), hi + 4)]
            fill = circles(ext, grow=-0.85)
            cv.paint(ring, LINE)
            cv.paint(fill & dilate(ring, 6), SHADE)
            light = circles(ext, grow=-0.85, off=(-0.1, -0.3), scale=0.62) & fill & dilate(ring, 6)
            cv.paint(light, COIL)
            dm = new_mask(); dd = ImageDraw.Draw(dm)
            for j, (x, y, r) in enumerate(ext[::5]):
                rr = 0.5 * SS
                ox, oy = x + (0.25 * r if j % 2 else -0.25 * r), y - 0.3 * r
                dd.ellipse([ox * SS - rr, oy * SS - rr, ox * SS + rr, oy * SS + rr], fill=255)
            cv.paint(arr(dm) & light, SCALE)

    profile = abs(lx) <= 0.3
    if behind:
        draw_body()
    if profile:
        draw_hood(); draw_neck()
    else:
        draw_neck(); draw_hood()
    if not behind:
        draw_body()

    out = cv.down()
    # paste James's real head
    nf, ns = neck_fs(zt)
    tx, ty, _ = p(nf, ns, zt)
    bx, by, _ = p(neck_fs(GY - (NECK_Y + PADY - 7))[0] * 0, 0, GY - (NECK_Y + PADY - 7))
    dx = int(round(tx - bx)); dy = int(round(ty - by))
    hd = head.astype(np.float32)
    H = np.zeros((OH, OW, 4), np.float32)
    x0, y0 = PADX + dx, PADY + dy
    H[y0:y0 + BH, x0:x0 + BW] = hd
    ha = H[..., 3:4] / 255
    out = np.concatenate([out[..., :3] * (1 - ha) + H[..., :3] * ha,
                          np.maximum(out[..., 3:4], H[..., 3:4])], -1)
    if fangs and mouths.get(d):
        mx, my = mouths[d]
        mx += x0; my += y0
        fc = Canvas()
        fc.rgb[:] = 0
        prof = abs(fx) > 0.9
        mw = 2.2 if prof else 3.2
        if prof:
            mx += 0.5 * fx
        o = ellipse(mx, my + 0.6, mw, 1.7)
        fc.paint(dilate(o, 2), LINE)
        fc.paint(o, MOUTH)
        offs = [0.0] if prof else [-1.6, 1.6]
        fl = 4.2 if k == 3 else 3.4
        for ox in offs:
            fx0 = mx + ox + (-0.6 * fx if prof else 0)
            tri = poly([(fx0 - 0.9, my - 0.2), (fx0 + 0.9, my - 0.2), (fx0 + (0.3 * fx if prof else 0), my + fl)])
            fc.paint(dilate(tri, 2), LINE)
            fc.paint(tri, FANG)
        fd = fc.down()
        fa = fd[..., 3:4] / 255
        out = np.concatenate([out[..., :3] * (1 - fa) + fd[..., :3] * fa,
                              np.maximum(out[..., 3:4], fd[..., 3:4])], -1)
    return solidify(out.clip(0, 255).astype(np.uint8))


def main():
    base = np.asarray(Image.open(os.path.join(ASSETS, "kid.png")).convert("RGBA"))
    mouths = {}
    for d in ["E", "SE", "S", "SW", "W"]:
        m = mouth_of(head_of(base, d), d)
        if m: mouths[d] = m
    sheet = np.zeros((OH * 8, OW * COLS, 4), np.uint8)
    for r, d in enumerate(DIRS):
        for c in range(COLS):
            sheet[r * OH:(r + 1) * OH, c * OW:(c + 1) * OW] = render(base, d, c, mouths)
    Image.fromarray(sheet, "RGBA").save(os.path.join(ASSETS, "kid_cobra.png"), optimize=True)
    meta = json.load(open(os.path.join(ASSETS, "kid.json")))
    meta.update(image="kid_cobra.png", frameWidth=OW, frameHeight=OH, baselineY=GY, anchorX=OW // 2)
    json.dump(meta, open(os.path.join(ASSETS, "kid_cobra.json"), "w"), indent=2)
    print("mouths", mouths)


if __name__ == "__main__":
    main()
