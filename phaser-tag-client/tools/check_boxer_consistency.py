"""Boxer James consistency: sheet ≤4096; every frame one solid figure; red
gloves present in every frame; gold waistband present; torso width stable
across standing frames within a direction; head ratio chibi-like; NW tag
mirrors NE (jab extends opposite ways)."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

from make_banana_skin import components8

A = Path(__file__).resolve().parent.parent / "public" / "assets"
m = json.loads((A / "kid_boxer.json").read_text())
im = np.asarray(Image.open(A / m["image"]).convert("RGBA")).astype(int)
fw, fh = m["frameWidth"], m["frameHeight"]
bad = 0
if im.shape[0] > 4096 or im.shape[1] > 4096:
    print("sheet too large", im.shape)
    bad += 1


def is_glove(rgb, a):
    """Red glove pixels: saturated red, not the darker trunk red (lower sat / lower in frame)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (a > 100) & (r > 160) & (r - g > 70) & (r - b > 60) & (g < 110)


def is_gold(rgb, a):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (a > 100) & (r > 180) & (g > 140) & (b < 120) & (r - b > 80)


hrs = {}
glove_counts = {}
for r, d in enumerate(m["directions"]):
    for c in range(im.shape[1] // fw):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        comps = [k for k in components8(a) if k.sum() >= 6]
        if len(comps) != 1:
            print(f"{d} col {c}: {len(comps)} pieces")
            bad += 1
        rgb = f[..., :3]
        al = f[..., 3]
        glove = is_glove(rgb, al)
        glove_counts.setdefault(d, []).append(int(glove.sum()))
        if glove.sum() < 25:
            print(f"{d} col {c}: missing red gloves ({glove.sum()} px)")
            bad += 1
        gold = is_gold(rgb, al)
        if gold.sum() < 8 and c < 22:  # run frames still have waistband
            # trunks waistband
            if gold.sum() < 4:
                print(f"{d} col {c}: missing gold waistband ({gold.sum()} px)")
                bad += 1
        # standing frames: head ratio
        if c < 4 or 12 <= c < 16:
            ys_ = np.nonzero(a.any(1))[0]
            t_, b_ = ys_.min(), ys_.max()
            w_ = {y: int(a[y].sum()) for y in ys_}
            nk = min(range(int(t_ + .28 * (b_ - t_)), int(t_ + .58 * (b_ - t_))),
                     key=lambda y: w_.get(y, 999))
            hr = (nk - t_) / max(b_ - t_, 1)
            hrs.setdefault(d, []).append(hr)
            if not 0.40 <= hr <= 0.60:
                print(f"{d} col {c}: head ratio {hr:.2f}")
                bad += 1

# torso width consistency across idle cols within a direction (gloves excluded
# from the mid-torso band so a high guard doesn't inflate the measure)
pad_top = m["baselineY"] - 96
torso_rows = list(range(pad_top + 54, pad_top + 62))
for r, d in enumerate(m["directions"]):
    widths = []
    for c in range(4):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        gmask = is_glove(f[..., :3], f[..., 3])
        a = (f[..., 3] > 128) & ~gmask
        vals = []
        for y in torso_rows:
            if 0 <= y < fh and a[y].any():
                xs = np.nonzero(a[y])[0]
                vals.append(xs.max() - xs.min() + 1)
        if vals:
            widths.append(float(np.median(vals)))
    if widths and (max(widths) - min(widths)) > 6:
        print(f"{d}: idle torso width varies {widths}")
        bad += 1

# NW tag mirrors NE: jab glove centroid x relative to body centre should flip
t0 = m["animations"]["tag"]["start"]
# impact frame (fullest reach) ≈ col t0+3
impact = t0 + 3
for label, d, d_mirror in (("NW/NE", "NW", "NE"),):
    r1, r2 = m["directions"].index(d), m["directions"].index(d_mirror)
    f1 = im[r1 * fh:(r1 + 1) * fh, impact * fw:(impact + 1) * fw]
    f2 = im[r2 * fh:(r2 + 1) * fh, impact * fw:(impact + 1) * fw]
    g1 = is_glove(f1[..., :3], f1[..., 3])
    g2 = is_glove(f2[..., :3], f2[..., 3])
    if g1.any() and g2.any():
        # body centre from non-glove mid rows
        def cx(f, g):
            a = (f[..., 3] > 128) & ~g
            ys = list(range(pad_top + 50, pad_top + 70))
            xs = []
            for y in ys:
                if a[y].any():
                    xx = np.nonzero(a[y])[0]
                    xs.append(0.5 * (xx.min() + xx.max()))
            return float(np.median(xs)) if xs else fw / 2
        c1, c2 = cx(f1, g1), cx(f2, g2)
        j1 = float(np.nonzero(g1)[1].mean())
        j2 = float(np.nonzero(g2)[1].mean())
        off1, off2 = j1 - c1, j2 - c2
        # should be opposite signs and similar magnitude
        if off1 * off2 > 0 or abs(abs(off1) - abs(off2)) > 10:
            print(f"{label} jab offsets not mirrored: {off1:.1f} vs {off2:.1f}")
            bad += 1
        else:
            print(f"{label} jab offsets OK: {off1:.1f} vs {off2:.1f}")

print("glove px median", {d: int(np.median(v)) for d, v in glove_counts.items()})
print("head ratio", {d: round(float(np.median(v)), 3) for d, v in hrs.items()})
print("boxer consistency: problems =", bad)
raise SystemExit(1 if bad else 0)
