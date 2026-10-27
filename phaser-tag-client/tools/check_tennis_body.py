"""Tag frames for E, W, NE, NW: the body silhouette (torso + shorts, without
the swing arm and racket) must match the idle body with its swing-side
hanging arm taken off (torso edge interpolated over the arm rows). No pixel
may bulge past it (belly / hip puff) and none may be missing inside it.
Pixels covered by the drawn arm / racket (skin, arm outline, racket colours,
or within 4px of them: sleeve, wristband) are not judged."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import make_tennis_skin as mt
from make_banana_skin import Geometry, alpha_mask, arms_and_hands, grow, skin_mask

A = Path(__file__).resolve().parent.parent / "public" / "assets"
m = json.loads((A / "kid_tennis.json").read_text())
im = np.asarray(Image.open(A / m["image"]).convert("RGBA"))
bm = json.loads((A / "kid.json").read_text())
base = np.asarray(Image.open(A / bm["image"]).convert("RGBA"))
fw, fh = m["frameWidth"], m["frameHeight"]
bw, bh = bm["frameWidth"], bm["frameHeight"]
t0, tn = m["animations"]["tag"]["start"], m["animations"]["tag"]["count"]


def reference(idle):
    gi = Geometry(idle)
    h, w = idle.shape[:2]
    yy = np.mgrid[0:h, 0:w][0]
    ai = alpha_mask(idle)
    face = (yy <= gi.neck + 1) & skin_mask(idle)
    arms, _ = arms_and_hands(idle, gi, face)
    rm = grow(mt.arm_comps_on(arms, gi, d, mt.TAG_SIDE[d]), ai, 1) & (yy > gi.neck + 1)
    keep = ai & ~rm
    body = keep | (rm & ai & mt.torso_hull(keep, rm, gi))
    rows = (yy >= gi.neck + 3) & (yy <= gi.hem - 1)
    return body, rows


bad = 0
for r, d in enumerate(m["directions"]):
    if d not in ("E", "W", "NE", "NW"):
        continue
    ref, rows = reference(mt.pad_frame(base[r * bh:(r + 1) * bh, 0:bw]))
    edge = grow(ref, np.ones_like(ref), 1) & ~grow(~ref, np.ones_like(ref), 1) | \
        (grow(ref, np.ones_like(ref), 1) & ~ref)
    for c in range(t0, t0 + tn):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw].astype(int)
        R, G, B, al = (f[..., i] for i in range(4))
        op = al >= 128
        drawn = op & (((R - B > 25) & (R - G > 14) & (R > 70)) | ((R > 180) & (B < 110))
                      | ((G > R + 1) & (R + G + B > 450)) | ((R - B > 10) & (R + G + B < 150))
                      | (R + G + B < 60))
        skip = grow(drawn, np.ones_like(drawn), 4) | edge | ~rows
        bulge = int((op & ~ref & ~skip).sum())
        hole = int((~op & ref & ~skip).sum())
        if bulge or hole:
            print(f"{d} tag col {c}: {bulge} px bulge past idle body, {hole} px missing")
            bad += 1
print(f"{bad} tag frames off the idle body")
sys.exit(1 if bad else 0)
