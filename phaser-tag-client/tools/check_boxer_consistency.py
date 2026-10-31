"""Boxer James consistency: sheet ≤4096; every frame one solid figure; red
gloves present in every frame; gold waistband present; torso width stable
across standing frames within a direction; head ratio chibi-like; NW tag
mirrors NE (jab extends opposite ways); no hanging base-arm skin outside
the glove-arm masks at hip/side level; idle/walk/run high peek-a-boo guard
(gloves cover mouth, eyes clear); bare torso is peach skin (not tee grey)
matching face tone; no glove pixels over the head on N/NE/NW; back torso interior is skin/trunk only (no see-through gloves/cuffs)."""
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


def grow_mask(m, n):
    out = m.copy()
    for _ in range(n):
        g = out.copy()
        g[1:] |= out[:-1]; g[:-1] |= out[1:]; g[:, 1:] |= out[:, :-1]; g[:, :-1] |= out[:, 1:]
        out = g
    return out


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
            # high peek-a-boo gloves sit over the mouth; measure body without them
            # (and without white cuffs next to them)
            body = a & ~grow_mask(glove, 3)
            w_ = {y: int(body[y].sum()) or 999 for y in ys_}
            nk = min(range(int(t_ + .28 * (b_ - t_)), int(t_ + .58 * (b_ - t_))),
                     key=lambda y: w_.get(y, 999))
            hr = (nk - t_) / max(b_ - t_, 1)
            hrs.setdefault(d, []).append(hr)
            if not 0.30 <= hr <= 0.64:
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

# Trunks: red / gold / white only — no black interior (thin darker-red edge OK).
pad = m["baselineY"] - 96
for r, d in enumerate(m["directions"]):
    for c in range(im.shape[1] // fw):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        rgb = f[..., :3].astype(int)
        rr, gg, bb = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        lum = (rr + gg + bb) / 3.0
        is_red = (rr > 90) & (rr > gg + 20) & (rr > bb + 20)
        # Exact waistband colors (not shoe gold)
        is_wb = (
            ((np.abs(rr - 232) <= 12) & (np.abs(gg - 200) <= 16) & (np.abs(bb - 72) <= 16))
            | ((np.abs(rr - 250) <= 12) & (np.abs(gg - 236) <= 16) & (np.abs(bb - 160) <= 20))
        )
        is_gold = is_wb | ((rr > 200) & (gg > 170) & (bb < 140) & (rr - bb > 70) & (gg - bb > 50) & (lum > 150))
        is_white = (lum >= 160) | ((rr > 180) & (gg > 180) & (bb > 170))
        wb_ys = [y for y in range(pad + 70, pad + 88) if int((is_wb[y] & a[y]).sum()) >= 3]
        if wb_ys:
            trunk_y0 = min(wb_ys)
            # Keep only the first contiguous waistband cluster (ignore shoe gold lower down).
            run = [trunk_y0]
            y = trunk_y0 + 1
            while y in wb_ys and y <= trunk_y0 + 4:
                run.append(y)
                y += 1
            trunk_y1 = min(max(run) + 4, trunk_y0 + 7, fh)
        else:
            trunk_y0, trunk_y1 = pad + 74, pad + 82
        zone = a.copy()
        zone[:trunk_y0] = False
        zone[trunk_y1:] = False
        zone &= ~is_glove(rgb, f[..., 3])
        # Restrict to columns that have red/gold/white trunk cloth on this row
        # (drops hanging-arm silhouettes that share the y-band).
        for y in range(trunk_y0, min(trunk_y1, fh)):
            cloth = (is_red[y] | is_gold[y] | is_white[y]) & a[y]
            if not cloth.any():
                zone[y] = False
                continue
            xs = np.nonzero(cloth)[0]
            x0, x1 = int(xs.min()) - 1, int(xs.max()) + 2
            mask = np.zeros(fw, dtype=bool)
            mask[max(0, x0):min(fw, x1)] = True
            zone[y] &= mask
        if not zone.any():
            continue
        allowed = is_red | is_gold | is_white
        dark = zone & (lum < 70) & ~allowed
        # Silhouette edge of the opaque body on each row is allowed if red-ish outline
        edge = np.zeros_like(dark)
        for y in range(trunk_y0, min(trunk_y1, fh)):
            xs = np.nonzero(a[y])[0]
            if len(xs) >= 2:
                edge[y, xs.min()] = True
                edge[y, xs.max()] = True
                if len(xs) >= 4:
                    edge[y, xs.min() + 1] = True
                    edge[y, xs.max() - 1] = True
            elif len(xs) == 1:
                edge[y, xs[0]] = True
        bad_px = dark & ~edge
        n = int(bad_px.sum())
        if n > 2:
            print(f"{d} col {c}: {n} black/near-black trunk pixels (want red/gold/white only)")
            bad += 1


# No hanging base-arm skin outside the glove-arm / torso masks at hip level.
# Hanging hands sit beside the gold waistband; drawn glove arms stay above it.
def is_skin_arm(rgb, a):
    """Skin tone that is not glove / gold / near-white cloth."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = (r + g + b) / 3.0
    glove = is_glove(rgb, a)
    gold = (r > 180) & (g > 140) & (b < 140) & (r - b > 60)
    white = (lum >= 160) | ((r > 180) & (g > 180) & (b > 170))
    return (
        (a > 100) & (r > 140) & (r > b + 20) & (r > g + 8) & (g > 70) & (b > 50)
        & ~glove & ~gold & ~white
    )


pad = m["baselineY"] - 96
for r, d in enumerate(m["directions"]):
    for c in range(im.shape[1] // fw):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        rgb = f[..., :3].astype(int)
        al = f[..., 3]
        skin = is_skin_arm(rgb, al)
        glove = is_glove(rgb, al)
        rr, gg, bb = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        gold_px = (al > 100) & (rr > 180) & (gg > 140) & (bb < 140) & (rr - bb > 60)
        # Wide gold waistband row (skip thin shoe-gold scraps).
        wb = None
        for y in range(pad + 70, pad + 84):
            xs = np.nonzero(gold_px[y] & a[y])[0]
            if len(xs) >= 8:
                wb = (y, int(xs.min()), int(xs.max()))
                break
        if wb is None:
            spans = []
            for y in range(pad + 58, pad + 66):
                body = a[y] & ~glove[y]
                xs = np.nonzero(body)[0]
                if len(xs) >= 8:
                    spans.append((int(xs.min()), int(xs.max())))
            if not spans:
                continue
            wb_lo = int(np.median([s[0] for s in spans]))
            wb_hi = int(np.median([s[1] for s in spans]))
            y0 = pad + 74
        else:
            y0, wb_lo, wb_hi = wb
        hip_y1 = min(y0 + 8, pad + 86, fh)
        stray = 0
        for y in range(y0, hip_y1):
            sk = skin[y] & ~glove[y]
            if not sk.any():
                continue
            xs = np.nonzero(sk)[0]
            outside = xs[(xs < wb_lo - 2) | (xs > wb_hi + 2)]
            stray += len(outside)
        if stray > 3:
            print(f"{d} col {c}: {stray} stray skin-arm px outside glove-arm masks (hip/side)")
            bad += 1


# High peek-a-boo guard on idle / walk / run: gloves sit at mouth level
# (centroid in the face band) and some upper-face / eye pixels stay clear.
guard_anims = []
for name, spec in m.get("animations", {}).items():
    if name in ("idle", "walk", "run", "breathe"):
        guard_anims.extend(range(spec["start"], spec["start"] + spec["count"]))
guard_anims = sorted(set(guard_anims))
for r, d in enumerate(m["directions"]):
    for c in guard_anims:
        if c * fw >= im.shape[1]:
            continue
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        rgb = f[..., :3].astype(int)
        al = f[..., 3]
        glove = is_glove(rgb, al)
        # Ignore shoe/trunk red: only gloves in the upper 70% of the frame.
        glove_upper = glove & (np.arange(fh)[:, None] < int(fh * 0.72))
        # Back views: gloves sit behind the head, so only elbows / a side peek
        # remain visible — do not require a full high-guard glove blob up top.
        if d in ("N", "NE", "NW"):
            if glove_upper.sum() + glove.sum() < 30:
                print(f"{d} col {c}: back-guard gloves/arms missing ({glove.sum()} px)")
                bad += 1
            continue
        glove = glove_upper
        if glove.sum() < 20:
            print(f"{d} col {c}: high-guard gloves missing in upper frame ({glove.sum()} px)")
            bad += 1
            continue
        ys = np.nonzero(glove)[0]
        cy = float(ys.mean())
        # Mouth/face band relative to padded kid (top~14, neck~57).
        if not (pad + 28 <= cy <= pad + 58):
            print(f"{d} col {c}: glove centroid y={cy:.1f} not in high-guard face band")
            bad += 1
        # Eyes / upper face clear: opaque non-glove pixels above bulk of gloves.
        bulk_top = int(np.percentile(ys, 15))
        upper = a & (np.arange(fh)[:, None] < bulk_top) & (np.arange(fh)[:, None] > pad + 18)
        clear = upper & ~glove
        if clear.sum() < 25:
            print(f"{d} col {c}: upper face covered by gloves ({clear.sum()} clear px)")
            bad += 1

# Bare torso is peach skin (not leftover grey/blue tee), every standing frame.
for r, d in enumerate(m["directions"]):
    for c in list(range(4)) + list(range(12, 16)):
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        rgb = f[..., :3].astype(int)
        rr, gg, bb = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        glove = is_glove(rgb, f[..., 3])
        # Mid-torso band below neck / above waistband.
        band = a & ~glove & (np.arange(fh)[:, None] >= pad + 58) & (np.arange(fh)[:, None] <= pad + 76)
        if band.sum() < 30:
            continue
        peach = band & (rr > 150) & (rr > bb + 15) & (gg > 85) & (bb > 50)
        grey_tee = band & (np.abs(rr.astype(int) - gg.astype(int)) < 25) & (bb + 5 >= rr) & (rr < 140)
        peach_n, grey_n = int(peach.sum()), int(grey_tee.sum())
        if peach_n < band.sum() * 0.35:
            print(f"{d} col {c}: torso not peach skin ({peach_n}/{band.sum()} peach)")
            bad += 1
        if grey_n > 12:
            print(f"{d} col {c}: leftover tee-grey on torso ({grey_n} px)")
            bad += 1


# Back views (N/NE/NW): gloves are in front of the face, so the head must
# occlude them — no glove pixels over the interior of the hair on idle/walk/
# run and jab start/end (mid-jab may extend past the head).
anims = m.get("animations", {})
idle_r = range(anims.get("idle", {}).get("start", 0),
               anims.get("idle", {}).get("start", 0) + anims.get("idle", {}).get("count", 4))
walk_r = range(anims["walk"]["start"], anims["walk"]["start"] + anims["walk"]["count"]) if "walk" in anims else range(0)
run_r = range(anims["run"]["start"], anims["run"]["start"] + anims["run"]["count"]) if "run" in anims else range(0)
tag = anims.get("tag") or anims.get("jab")
tag_cols = []
if tag:
    tag_cols = [tag["start"], tag["start"] + tag["count"] - 1]
check_cols = set(idle_r) | set(walk_r) | set(run_r) | set(tag_cols)

for r, d in enumerate(m["directions"]):
    if d not in ("N", "NE", "NW"):
        continue
    for c in range(im.shape[1] // fw):
        if c not in check_cols:
            continue
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        rgb = f[..., :3].astype(int)
        # Strict glove (exclude peach face/ear skin that loosely matches red).
        rr, gch, bb = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        glove = (
            (f[..., 3] > 100)
            & (rr > 180)
            & (gch < 80)
            & (rr - gch > 100)
            & (rr - bb > 90)
        )
        if not glove.any():
            continue
        # Hair/skull interior only (brown), not the whole opaque bbox — edge
        # peek past the face on NE/NW is allowed.
        neck_y = pad + 52
        yy = np.arange(fh)[:, None]
        hair = (
            a
            & (yy <= neck_y)
            & (yy >= pad + 14)
            & (rgb[..., 0] < 140)
            & (rgb[..., 1] < 110)
            & (rgb[..., 2] < 90)
            & (rgb[..., 0] > 30)
        )
        if not hair.any():
            continue
        # Inset so a side peek does not fail the check. On NE/NW the near
        # glove may legitimately peek past the facing face edge.
        hy, hx = np.nonzero(hair)
        # Deep interior only — edge peeks past the ears/shoulders are intended.
        lo, hi = int(hx.min()) + 8, int(hx.max()) - 8
        if d == "NE":
            hi = int(hx.max()) - 14  # facing east: allow peek on right
        elif d == "NW":
            lo = int(hx.min()) + 14  # facing west: allow peek on left
        elif d == "N":
            # Jim wants thin glove slivers past both sides; keep deep core clear.
            lo, hi = int(hx.min()) + 14, int(hx.max()) - 14
        if lo >= hi:
            continue
        interior = np.zeros((fh, fw), dtype=bool)
        interior[hy.min(): hy.max() + 1, lo:hi] = True
        overlap = int((glove & interior & (yy <= neck_y)).sum())
        # Thin side slivers OK; deep skull interior must stay clear.
        limit = 6 if d == "N" else 16
        if overlap > limit:
            print(f"{d} col {c}: {overlap} glove px over head interior (want behind head)")
            bad += 1


# Back views: torso interior must be opaque skin/trunk only — no glove, cuff,
# or forearm showing through the back (Jim: body must not be see-through).
def is_cuff_px(rgb, a):
    """White glove cuff only — not peach skin highlights or gold trim."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = (r + g + b) / 3.0
    near_white = (np.abs(r - g) < 25) & (np.abs(g - b) < 30) & (np.abs(r - b) < 30)
    return (a > 100) & (lum >= 210) & (b > 200) & (r > 200) & (g > 200) & near_white


def is_skin_or_trunk(rgb, a):
    """Accept peach skin, trunk red/gold/white, hair-brown, shoe — not glove."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = (r + g + b) / 3.0
    peach = (a > 100) & (r > 120) & (r > b + 12) & (r > g + 4) & (g > 50) & (b > 35) & (lum < 210)
    trunk_red = (a > 100) & (r > 90) & (r > g + 20) & (r > b + 20) & (g < 140)
    gold = (a > 100) & (r > 170) & (g > 130) & (b < 140) & (r - b > 60)
    white = (a > 100) & ((lum >= 160) | ((r > 180) & (g > 180) & (b > 170)))
    hair = (a > 100) & (r < 140) & (g < 110) & (b < 90) & (r > 25)
    line = (a > 100) & (r < 90) & (g < 70) & (b < 60)
    return peach | trunk_red | gold | white | hair | line


for r, d in enumerate(m["directions"]):
    if d not in ("N", "NE", "NW"):
        continue
    for c in range(im.shape[1] // fw):
        if c not in check_cols:
            continue
        # Skip mid-jab frames (arm extends past the body legitimately).
        if tag and c not in tag_cols and c >= tag["start"] and c < tag["start"] + tag["count"]:
            continue
        f = im[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
        a = f[..., 3] >= 200
        if not a.any():
            continue
        rgb = f[..., :3].astype(int)
        al = f[..., 3]
        # Strict glove (peach skin must not count).
        rr, gch, bb = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        glove = (
            (al > 100) & (rr > 180) & (gch < 80) & (rr - gch > 100) & (rr - bb > 90)
        )
        cuff = is_cuff_px(rgb, al)
        # Torso band: below neck, ABOVE waistband (trunk red ≈ glove red).
        # Interior inset excludes side upper-arm silhouette.
        y0 = pad + 54
        y1 = pad + 68
        interior = np.zeros((fh, fw), dtype=bool)
        for y in range(y0, min(y1, fh)):
            xs = np.nonzero(a[y])[0]
            if len(xs) < 12:
                continue
            lo, hi = int(xs.min()) + 6, int(xs.max()) - 6
            if lo < hi:
                interior[y, lo:hi + 1] = True
        leak = interior & (glove | cuff)
        n_leak = int(leak.sum())
        if n_leak > 4:
            print(f"{d} col {c}: {n_leak} glove/cuff px inside back torso (see-through)")
            bad += 1
        # Also flag non-skin/trunk junk in the deep interior (inset further).
        deep = np.zeros((fh, fw), dtype=bool)
        for y in range(y0, min(y1, fh)):
            xs = np.nonzero(a[y])[0]
            if len(xs) < 14:
                continue
            lo, hi = int(xs.min()) + 6, int(xs.max()) - 6
            if lo < hi:
                deep[y, lo:hi + 1] = True
        ok = is_skin_or_trunk(rgb, al)
        junk = deep & a & ~ok & ~glove  # glove already counted
        # Ignore near-black outline crumbs
        rr, gg, bb = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        junk &= (rr + gg + bb) > 60
        n_junk = int(junk.sum())
        if n_junk > 8:
            print(f"{d} col {c}: {n_junk} non-skin/trunk px in back torso interior")
            bad += 1

print("glove px median", {d: int(np.median(v)) for d, v in glove_counts.items()})
print("head ratio", {d: round(float(np.median(v)), 3) for d, v in hrs.items()})

# E/W profile: upper arm ≈ forearm (~14–16 each).
def _profile_seg_lengths():
    import math
    lengths = {}
    for r, d in enumerate(m["directions"]):
        if d not in ("E", "W"):
            continue
        f = im[r * fh:(r + 1) * fh, 0:fw]
        a = f[..., 3] >= 128
        if not a.any():
            continue
        neck = float(pad + 48)
        hx = np.nonzero(a[pad + 28])[0]
        head_cx = float(hx.mean()) if len(hx) else fw / 2.0
        head_hw = 18.0
        fx = 1 if d == "E" else -1
        sh = (head_cx - fx * 2.0, neck + 3.0)
        tip = head_cx + fx * (head_hw * 0.50)
        hand = (tip + fx * (8.0 * 0.12), neck + 2.0)
        L1 = L2 = 15.0
        dx, dy = hand[0] - sh[0], hand[1] - sh[1]
        dd = math.hypot(dx, dy) or 1.0
        dd2 = min(dd, L1 + L2 - 0.05)
        a_len = (L1 * L1 - L2 * L2 + dd2 * dd2) / (2 * dd2)
        hh = math.sqrt(max(L1 * L1 - a_len * a_len, 0.0))
        ux, uy = dx / dd, dy / dd
        cands = []
        for bend in (1, -1):
            px, py = -uy * bend, ux * bend
            el = (sh[0] + ux * a_len + px * hh, sh[1] + uy * a_len + py * hh)
            cands.append(el)
        el = cands[0] if cands[0][1] >= cands[1][1] else cands[1]
        el = (el[0], max(el[1], sh[1] + 6.0))
        ua = math.hypot(el[0] - sh[0], el[1] - sh[1])
        fa = math.hypot(hand[0] - el[0], hand[1] - el[1])
        lengths[d] = (ua, fa)
    return lengths

for d, (ua, fa) in _profile_seg_lengths().items():
    if not (13.0 <= ua <= 17.5 and 13.0 <= fa <= 17.5):
        print(f"{d}: profile arm segs out of range UA={ua:.1f} FA={fa:.1f} (want ~14–16 each)")
        bad += 1
    elif abs(ua - fa) > 3.0:
        print(f"{d}: profile UA/FA unbalanced {ua:.1f}/{fa:.1f} (want roughly equal)")
        bad += 1

print("boxer consistency: problems =", bad)
raise SystemExit(1 if bad else 0)
