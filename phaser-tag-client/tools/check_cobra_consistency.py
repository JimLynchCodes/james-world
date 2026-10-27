"""Cobra James consistency: sheet fits one texture, James's real base head is
present in every frame (face kept), and the raised neck is the same smooth
width in every frame of a direction (no lumps)."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_cobra_skin import head_of, PADX, PADY, DIRS, GY  # noqa: E402

A = Path(__file__).resolve().parent.parent / "public" / "assets"
m = json.loads((A / "kid_cobra.json").read_text())
im = np.asarray(Image.open(A / m["image"]).convert("RGBA")).astype(int)
base = np.asarray(Image.open(A / "kid.png").convert("RGBA"))
fw, fh = m["frameWidth"], m["frameHeight"]
bad = 0
if im.shape[0] > 4096 or im.shape[1] > 4096:
    print("sheet too large", im.shape); bad += 1
for r, d in enumerate(DIRS):
    head = head_of(base, d).astype(int)
    hm = head[..., 3] == 255
    hy, hx = np.nonzero(hm)
    widths = []
    for c in range(im.shape[1] // fw):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        best = 0.0
        for dy in range(-12, 13):
            for dx in range(-16, 17):
                ys, xs = hy + PADY + dy, hx + PADX + dx
                ok = (ys >= 0) & (ys < fh) & (xs >= 0) & (xs < fw)
                if not ok.all():
                    continue
                eq = (np.abs(f[ys, xs, :3] - head[hy, hx, :3]).max(1) <= 2).mean()
                best = max(best, eq)
        if best < 0.95:
            print(f"{d} col {c}: base head match {best:.3f}"); bad += 1
        # neck width a little above the coils: the opaque run nearest the centre
        y = GY - 24
        row = f[y, :, 3] > 128
        runs, x = [], 0
        while x < fw:
            if row[x]:
                x0 = x
                while x < fw and row[x]:
                    x += 1
                runs.append((x0, x))
            x += 1
        cx = fw / 2
        widths.append(min(((abs((a + b) / 2 - cx), b - a) for a, b in runs), default=(0, 0))[1])
    w = np.array(widths)
    med = np.median(w)
    for c, wv in enumerate(w):
        if abs(wv - med) > (7 if 16 <= c < 22 else 3):  # tag dart drops the hood
            print(f"{d} col {c}: neck width {wv} vs median {med}"); bad += 1
print("cobra consistency: problems =", bad)
raise SystemExit(1 if bad else 0)
