"""Assert Tennis James torso width matches the base kid sprite (front/back/diagonal views)."""
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

TAG = range(bm["animations"]["tag"]["start"], bm["animations"]["tag"]["start"] + bm["animations"]["tag"]["count"])


def width(f, rows, cx, thr):
    L, R = torso_span(f, rows, cx, thr)
    return L + R


bad = 0
for r, d in enumerate(bm["directions"]):
    if d in ("E", "W"):
        continue
    b0 = base[r * bh:(r + 1) * bh, 0:bw]
    wb = width(b0, range(58, 70), base_center(b0), 120)
    for c in range(bm["columns"]):
        if c in TAG:
            continue  # the base tag arm lies across the torso; not comparable
        b = base[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw]
        t = ten[r * th:(r + 1) * th, c * tw:(c + 1) * tw]
        band = t[58 + py:70 + py]
        wy, wx = np.nonzero((band[..., :3].astype(int).sum(-1) > 720) & (band[..., 3] == 255))
        tcx = int(np.median(wx)) if len(wx) else base_center(b) + px
        wt = width(t, range(58 + py, 70 + py), tcx, 450)
        if abs(wb - wt) > 1.5:
            print(f"{d} col {c}: base {wb} tennis {wt}")
            bad += 1
print(f"{bad} width mismatches")
sys.exit(1 if bad else 0)
