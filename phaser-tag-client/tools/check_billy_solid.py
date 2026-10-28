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
            continue
        # side views (rows 0=E, 4=W): the back of the jacket below the neck
        # must not slant/notch inward 2 px or more from the torso back line
        if r in (0, 4):
            a = al >= 200
            rows = np.nonzero(a.any(1))[0]
            t, h = rows.min(), rows.max() - rows.min()
            wid = {y: np.count_nonzero(a[y]) for y in rows}
            neck = min(range(int(t + 0.25 * h), int(t + 0.5 * h)), key=lambda y: wid.get(y, 999))
            back = {y: (np.nonzero(a[y])[0].min() if r == 0 else -np.nonzero(a[y])[0].max())
                    for y in range(neck + 4, neck + 12) if a[y].any()}
            # inward = further from the back than the line just below the
            # neck; an arm swinging out behind the back is not a notch
            ys_ = sorted(back)
            ref = min(back[y] for y in ys_[:3])
            worst = max(back.values()) - ref
            if worst >= 2:
                print(f"row {r} col {c}: upper-back notch {worst} px")
                bad += 1
print("billy solid: bad frames =", bad)
raise SystemExit(1 if bad else 0)
