"""Assert Tennis James torso width (shoulder and waist rows) matches the base kid
sprite within 1px in all 8 directions; tag frames are compared to the idle frame."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

A = Path(__file__).resolve().parent.parent / "public" / "assets"
bm = json.loads((A / "kid.json").read_text())
tm = json.loads((A / "kid_tennis.json").read_text())
base = np.asarray(Image.open(A / bm["image"]).convert("RGBA")).astype(int)
ten = np.asarray(Image.open(A / tm["image"]).convert("RGBA")).astype(int)
bw, bh, tw, th = bm["frameWidth"], bm["frameHeight"], tm["frameWidth"], tm["frameHeight"]
px, py = (tw - bw) // 2, th - bh


from solid_mask import base_center, torso_span  # noqa: E402
from make_banana_skin import Geometry  # noqa: E402

TAG = range(bm["animations"]["tag"]["start"], bm["animations"]["tag"]["start"] + bm["animations"]["tag"]["count"])


def skinless(f):
    f = f.copy()
    c = f[..., :3]
    sk = (c[..., 0] - c[..., 2] > 25) & (c[..., 0] - c[..., 1] > 14) & (c[..., 0] > 70)
    f[sk, :3] = 0
    return f


TAG_SIDE = {"E": 1, "SE": 1, "S": 1, "SW": -1, "W": -1, "NW": -1, "N": 1, "NE": 1}


def pad(b):
    o = np.zeros((th, tw, 4), np.uint8)
    o[py:, px:px + bw] = b
    return o


def body_px(p):
    r, g, b = int(p[0]), int(p[1]), int(p[2])
    if p[3] < 128:
        return False
    if r - b > 25 and r - g > 14 and r > 70:  # skin (arm / hand)
        return False
    if r > 180 and b < 110:  # racket yellow
        return False
    if g > r + 1 and r + g + b > 450:  # string bed
        return False
    return True


def far(f, rows, h0, step, occluded=False):
    """median distance from the hip line to the body's outer edge (racket
    and arm skin stop the walk)"""
    ext = []
    for y in rows:
        seg = f[max(0, y - 2):y + 3, max(0, min(h0, h0 + 30 * step)):max(h0, h0 + 30 * step) + 1].reshape(-1, 4).astype(int)
        occl = ((seg[:, 0] > 150) & (seg[:, 1] > 120) & (seg[:, 2] < 110)) | ((seg[:, 0] - seg[:, 2] > 25) & (seg[:, 0] - seg[:, 1] > 14))
        occl |= (seg[:, 1] > seg[:, 0] + 1) & (seg[:, :3].sum(-1) > 450)  # string bed
        if occluded and (occl & (seg[:, 3] >= 128)).any():
            continue  # swing arm / racket in front of the torso on this row
        x = h0
        while 0 < x + step < f.shape[1] and body_px(f[y, x + step]):
            x += step
        if abs(x - h0) >= 3:
            ext.append(abs(x - h0))
    return float(np.median(ext)) if len(ext) >= 2 else None


def width(f, rows, cx, thr):
    # skin (arms / hands) bounds the torso the same as an outline does
    f = f.copy()
    c = f[..., :3]
    sk = (c[..., 0] - c[..., 2] > 25) & (c[..., 0] - c[..., 1] > 14) & (c[..., 0] > 70)
    f[sk, :3] = 0
    L, R = torso_span(f, rows, cx, thr)
    return L + R


SH, WA = range(54, 59), range(70, 75)
ROWS = [y + py for y in list(SH) + list(WA)]
bad = 0
for r, d in enumerate(bm["directions"]):
    t0 = ten[r * th:(r + 1) * th, 0:tw]
    b0 = base[r * bh:(r + 1) * bh, 0:bw]
    cx0 = base_center(b0) + px
    for c in range(bm["columns"]):
        b = base[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw]
        t = ten[r * th:(r + 1) * th, c * tw:(c + 1) * tw]
        if c not in TAG:
            # recolour: in the shoulder/waist rows the body silhouette is the
            # base silhouette pixel-for-pixel; only racket pixels may be added
            B = np.zeros(t.shape[:2], bool)
            B[py:, px:px + bw] = b[..., 3] >= 128
            T = t[..., 3] >= 128
            col = t[..., :3]
            cloth = (col.sum(-1) > 600) & (col[..., 0] >= col[..., 1]) & (col[..., 1] >= col[..., 2]) & (col[..., 0] - col[..., 2] < 8)
            lost = (B & ~T)[ROWS].sum()
            nb = np.zeros_like(B)
            for sy, sx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nb |= np.roll(B, (sy, sx), (0, 1))
            grown = 0
            for y in ROWS:
                xs = np.nonzero(B[y])[0]
                if not len(xs):
                    continue
                for x0, st in ((xs.min(), -1), (xs.max(), 1)):
                    n, x = 0, x0 + st
                    while 0 <= x < tw and T[y, x] and cloth[y, x]:
                        n, x = n + 1, x + st
                    # cloth beyond the base row extent = a wider body
                    grown = max(grown, n)
            grown = grown if grown > 1 else 0
            if lost > 1 or grown:
                print(f"{d} col {c}: silhouette lost {lost} px, cloth added {grown} px")
                bad += 1
        else:
            # tag: the swing arm sits on one side, so compare the torso's
            # far-side half width (and the profile back edge) with idle,
            # centred on the idle hips
            sd = TAG_SIDE.get(d, 1) or 1
            gb0, gb = Geometry(pad(b0)), Geometry(pad(b))
            h0 = cx0
            ht = h0  # tag body is the idle body (unshifted, steady)
            for nm, rows in (("shoulder", SH), ("waist", WA)):
                rr = [y + py for y in rows]
                fi, ft = far(t0, rr, h0, -sd), far(t, rr, ht, -sd, True)
                if fi is not None and ft is not None and abs(ft - fi) > 1:
                    print(f"{d} tag col {c} {nm}: idle far edge {fi} tag {ft}")
                    bad += 1
print(f"{bad} width mismatches")
sys.exit(1 if bad else 0)
