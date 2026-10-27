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
        # smile centre measured on the base faces (zoomed kid.png rows 42-45)
        mx = {"S": 39.0, "SE": 45.0, "SW": 32.0}.get(d, float(xx.mean()))
        my = 44.5
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

    cv = None
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

    def draw_body():
        nonlocal cv
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

    # head placement (the hood is attached to the head, so it follows the dart)
    nf, ns = neck_fs(zt)
    tx, ty, _ = p(nf, ns, zt)
    z_rest = GY - (NECK_Y + PADY - 7)
    bx, by, _ = p(0, 0, z_rest)
    dx = int(round(tx - bx)); dy = int(round(ty - by))
    x0, y0 = PADX + dx, PADY + dy
    htop = ys.min() + y0
    hcx_now = hcx + dx

    back = fy < -0.3
    front = fy > 0.3
    al = abs(lx)

    # hood: tall rounded spade, in screen space around the head
    top_y = htop + (15 if back else 11)    # about temple / ear height
    chin_y = NECK_Y + y0
    bot_y = chin_y + 30
    W = 27.0 * al + 14.0 * (1 - al)        # broad face-on, flared profile edge-on
    off = -fx * (8.0 * (1 - al) + 2.5 * al)  # sits behind the head

    def neck_x_at(y):
        best = min(neck_pts[1:], key=lambda q: abs(q[1] - y))
        return best[0], best[2]

    rows = []
    for i in range(61):
        v = i / 60
        y = top_y + (bot_y - top_y) * v
        nx, nr = neck_x_at(y)
        if v < 0.3:
            w = W * math.sin(math.pi / 2 * min(1.0, (v + 0.02) / 0.3)) ** 0.55
            c = hcx_now + off
        else:
            q = (v - 0.3) / 0.7
            w = nr + (W - nr) * math.cos(math.pi / 2 * q) ** 1.25
            c = (hcx_now + off) * (1 - q ** 1.5) + nx * q ** 1.5
        rows.append((c, y, max(w, 1.0), v))
    hood_poly = [(c - w, y) for c, y, w, v in rows] + [(c + w, y) for c, y, w, v in rows[::-1]]

    def draw_union(target):
        U = poly(hood_poly) | circles(neck_pts)
        target.paint(dilate(U, 3), LINE)
        H4, W4 = U.shape
        yy, xx = np.mgrid[0:H4, 0:W4]
        # per-row extent of the union -> normalised across-body position t
        anyrow = U.any(1)
        left = np.where(anyrow, U.argmax(1), 0)
        right = np.where(anyrow, W4 - 1 - U[:, ::-1].argmax(1), 1)
        cx = (left + right) / 2.0
        hw = np.maximum((right - left) / 2.0, 1.0)
        t = (xx - cx[:, None]) / hw[:, None]
        sm = lambda e0, e1, x: np.clip((x - e0) / (e1 - e0), 0, 1) ** 2 * (3 - 2 * np.clip((x - e0) / (e1 - e0), 0, 1))
        shade = sm(0.45, 1.0, np.abs(t)) * 0.85 + sm(-0.2, 1.0, -t * 0.7 * (1 if True else 0)) * 0.0
        # light from upper-left: right side a touch darker
        shade = np.clip(shade + 0.18 * sm(0.0, 1.0, t), 0, 1)
        col = np.array(COIL, np.float32) * (1 - shade[..., None]) + np.array(SHADE, np.float32) * shade[..., None]
        # scale texture (small diamonds), stronger on the hood rim
        cell = 3 * SS
        dia = (((xx + yy) // cell + (xx - yy) // cell) % 2 == 0)
        rim = sm(0.55, 0.95, np.abs(t))
        k = (0.05 + 0.17 * rim) * dia
        col = col * (1 - k[..., None]) + np.array(LINE, np.float32) * k[..., None]
        if not back:
            c0 = 0.5 * fx if not front else 0.42 * fx
            bw = 0.36 + 0.14 * max(0.0, fy)
            dd = np.abs(t - c0) / bw
            bel = 1 - sm(0.65, 1.0, dd)
            band = ((yy // SS) % 4 == 0) & (yy > (top_y + 6) * SS)
            bcol = np.where(band[..., None], np.array(BAND, np.float32), np.array(BELLY, np.float32))
            col = col * (1 - bel[..., None]) + bcol * bel[..., None]
        m = U.astype(np.float32)
        target.rgb = target.rgb * (1 - m[..., None]) + col * m[..., None]
        target.a = np.maximum(target.a, m)
        # markings
        def at(v):
            return min(rows, key=lambda r: abs(r[3] - v))
        if back:
            c, y, w, v = at(0.5)
            for kk in (-1, 1):
                ex = c + kk * w * 0.45
                rx = max(1.8, 4.2 * al)
                target.paint(ellipse(ex, y, rx + 1.2, 5.2) & U, SPOT)
                target.paint(ellipse(ex, y, rx * 0.62 + 0.3, 3.4) & U, RIM)
                target.paint(ellipse(ex, y + 0.4, rx * 0.3, 1.7) & U, SPOT)
        elif front:
            c, y, w, v = at(0.56)
            for kk in (-1, 1):
                target.paint(ellipse(c + kk * w * 0.66, y, max(1.4, w * 0.09), 3.4) & U, SPOT)

    lower = Canvas()
    upper = Canvas()
    if back:
        draw_union(upper)
    if behind:
        cv = lower
        draw_body()
    if not back:
        draw_union(lower)
    if not behind:
        cv = upper
        draw_body()
    out = lower.down()
    hd = head.astype(np.float32)
    H = np.zeros((OH, OW, 4), np.float32)
    H[y0:y0 + BH, x0:x0 + BW] = hd
    ha = H[..., 3:4] / 255
    out = np.concatenate([out[..., :3] * (1 - ha) + H[..., :3] * ha,
                          np.maximum(out[..., 3:4], H[..., 3:4])], -1)
    up = upper.down()
    ua = up[..., 3:4] / 255
    out = np.concatenate([out[..., :3] * (1 - ua) + up[..., :3] * ua,
                          np.maximum(out[..., 3:4], up[..., 3:4])], -1)
    if fangs and mouths.get(d):
        mx, my = mouths[d]
        mx += x0; my += y0
        fc = Canvas()
        fc.rgb[:] = 0
        prof = abs(fx) > 0.9
        mw = 3.0 if prof else 4.6
        if prof:
            mx += 0.5 * fx
        o = ellipse(mx, my + 0.9, mw, 2.4)
        fc.paint(dilate(o, 2), LINE)
        fc.paint(o, MOUTH)
        offs = [0.0] if prof else [-2.4, 2.4]
        fl = 7.5 if k == 3 else 6.2
        for ox in offs:
            fx0 = mx + ox + (-0.6 * fx if prof else 0)
            tri = poly([(fx0 - 1.5, my - 0.2), (fx0 + 1.5, my - 0.2), (fx0 + (0.3 * fx if prof else 0), my + fl)])
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
