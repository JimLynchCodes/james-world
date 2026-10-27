"""Assert no non-opaque pixel inside any Tennis James frame's silhouette, and
no chunk / concave notch in tag-frame bodies vs the base idle silhouette."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from solid_mask import interior

A = Path(__file__).resolve().parent.parent / "public" / "assets"
m = json.loads((A / "kid_tennis.json").read_text())
im = np.asarray(Image.open(A / m["image"]).convert("RGBA"))
fw, fh = m["frameWidth"], m["frameHeight"]
bad = 0
for r in range(im.shape[0] // fh):
    for c in range(im.shape[1] // fw):
        al = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw, 3]
        n = int((interior(al) & (al < 255)).sum())
        if n:
            print(f"row {r} col {c}: {n} interior non-opaque px")
            bad += 1
# tag frames: every base-idle body pixel in the torso rows must still be
# body, except the swing-side arm cut off at the outer edge (anything
# missing inside the torso core is a chunk / notch)
bm = json.loads((A / "kid.json").read_text())
base = np.asarray(Image.open(A / bm["image"]).convert("RGBA"))
bw, bh = bm["frameWidth"], bm["frameHeight"]
px, py = (fw - bw) // 2, fh - bh
t0 = bm["animations"]["tag"]["start"]
ARMLESS = ("E", "W", "NE", "NW")
SIDE = {"E": 1, "SE": 1, "S": 1, "SW": -1, "W": -1, "NW": -1, "N": 1, "NE": 1}
for r, d in enumerate(bm["directions"]):
    B = np.zeros((fh, fw), bool)
    B[py:, px:px + bw] = base[r * bh:(r + 1) * bh, 0:bw, 3] >= 128
    ys = np.nonzero(B.any(1))[0]
    top, bot = ys.min(), ys.max()
    y0, y1 = top + int(0.48 * (bot - top)), bot - 6  # shoulders .. hem
    hem = np.nonzero(B[y1 - 8:y1])[1]
    hx = int(np.median(hem))
    core = (hem.max() - hem.min()) // 2 - 3  # swing-side torso core half width
    for c in range(t0, t0 + bm["animations"]["tag"]["count"]):
        T = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw, 3] >= 128
        n = 0
        for y in range(y0, y1):
            for x in np.nonzero(B[y] & ~T[y])[0]:
                st = 1 if x >= hx else -1
                far_side = st != SIDE[d]
                if d in ARMLESS:
                    continue  # judged against the arm-less idle body in check_tennis_body
                if far_side or abs(x - hx) <= core:
                    n += 1
                    if "-v" in sys.argv: print(d, c, x, y)
        if n:
            print(f"{d} tag col {c}: {n} px missing / notched vs base idle")
            bad += 1
print(f"{bad} bad frames")
sys.exit(1 if bad else 0)
