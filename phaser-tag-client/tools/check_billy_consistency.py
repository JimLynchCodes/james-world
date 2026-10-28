"""Billy consistency: sheet fits one texture; every frame is one solid figure
(alpha>=200, specks <6 px ignored); head/height ~0.47 like James (chibi); the torso
is 1.05-1.55x James's width in each direction (chubby, never skinny
or ballooning); and the iced coffee (orange straw or the clear lid/ice) is in every frame.
Head/height matches James's chibi ratio (~0.47) instead of a taller-than-James rule."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

from make_banana_skin import components8

A = Path(__file__).resolve().parent.parent / "public" / "assets"
m = json.loads((A / "kid_billy.json").read_text())
im = np.asarray(Image.open(A / m["image"]).convert("RGBA")).astype(int)
base = np.asarray(Image.open(A / "kid.png").convert("RGBA")).astype(int)
fw, fh = m["frameWidth"], m["frameHeight"]
BW, BH = 80, 100
bad = 0
if im.shape[0] > 4096 or im.shape[1] > 4096:
    print("sheet too large", im.shape); bad += 1


def torso_w(f, rows):
    a = f[..., 3] > 128
    return float(np.median([np.ptp(np.nonzero(a[y])[0]) + 1 for y in rows if a[y].any()]))


ratios = {}
hrs = {}


def nocup(f):
    g = f.copy()
    rgb = f[..., :3]
    cupish = (rgb.min(-1) > 150) | ((rgb[..., 0] - rgb[..., 2] > 60) & (rgb[..., 0] > 150) & (rgb[..., 1] > 90))
    g[cupish, 3] = 0
    return g


for r, d in enumerate(m["directions"]):
    for c in range(im.shape[1] // fw):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        b = base[r * BH:(r + 1) * BH, c * BW:(c + 1) * BW]
        if not (b[..., 3] > 0).any():
            continue
        a = f[..., 3] >= 200
        comps = [k for k in components8(a) if k.sum() >= 6]
        if len(comps) != 1:
            print(f"{d} col {c}: {len(comps)} pieces"); bad += 1
        hb = np.ptp(np.nonzero((b[..., 3] > 0).any(1))[0])
        hf = np.ptp(np.nonzero(a.any(1))[0])
        # chibi proportions like James: head (top to the neck, the narrowest
        # row in the middle band) is 0.46-0.48 of the height in the standing
        # frames (0.45-0.51 tolerance for the per-frame pixel rounding)
        if c < 4 or 12 <= c < 16:
            ys_ = np.nonzero(a.any(1))[0]
            t_, b_ = ys_.min(), ys_.max()
            w_ = {y: a[y].sum() for y in ys_}
            nk = min(range(int(t_ + .3 * (b_ - t_)), int(t_ + .6 * (b_ - t_))), key=lambda y: w_.get(y, 999))
            hr = (nk - t_) / (b_ - t_)
            hrs.setdefault(d, []).append(hr)
            if not 0.45 <= hr <= 0.51:
                print(f"{d} col {c}: head ratio {hr:.2f}"); bad += 1
        # upper torso band (James rows 54..60), cup pixels excluded; the
        # tag arm reaches out, so only the standing frames are measured
        if c < 4 or 12 <= c < 16:
            rows = [int(round(118 - (96 - y) * 1.10)) for y in range(54, 61)]
            ratio = torso_w(nocup(f), rows) / torso_w(b, range(54, 61))
            ratios.setdefault(d, []).append(ratio)
            if not 1.05 <= ratio <= 1.55:
                print(f"{d} col {c}: torso width ratio {ratio:.2f}"); bad += 1
        rgb = f[..., :3]
        straw = (rgb[..., 0] > 150) & (rgb[..., 0] - rgb[..., 1] > 60) & (rgb[..., 1] - rgb[..., 2] > 25) & (f[..., 3] > 100)
        lid = (rgb.min(-1) > 195) & (rgb[..., 2] - rgb[..., 0] >= 6) & (f[..., 3] > 100)
        if straw.sum() < 1 and lid.sum() < 3 and d not in ("N", "NE", "NW"):  # held behind him from the back
            print(f"{d} col {c}: no iced coffee"); bad += 1
print({d: round(float(np.median(v)), 2) for d, v in ratios.items()})
print("head ratio", {d: round(float(np.median(v)), 3) for d, v in hrs.items()})
for d, v in hrs.items():
    if not 0.46 <= float(np.median(v)) <= 0.495:
        print(f"{d}: median head ratio {np.median(v):.3f}"); bad += 1

print("billy consistency: problems =", bad)
raise SystemExit(1 if bad else 0)
