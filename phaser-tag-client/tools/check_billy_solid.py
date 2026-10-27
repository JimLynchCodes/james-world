"""Assert no non-opaque pixel inside any Billy frame's silhouette."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

from solid_mask import interior

A = Path(__file__).resolve().parent.parent / "public" / "assets"
m = json.loads((A / "kid_billy.json").read_text())
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
print("billy solid: bad frames =", bad)
raise SystemExit(1 if bad else 0)
