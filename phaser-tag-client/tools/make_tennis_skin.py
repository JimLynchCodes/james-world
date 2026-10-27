#!/usr/bin/env python3
"""Build the "Tennis James" sprite sheet (public/assets/kid_tennis.png/json)
from the base kid sheet.

Same smooth pipeline as make_wizard_skin.py: flat-colour class maps,
supersampled 4x, blurred and thresholded so every edge is smooth, outlined,
then box-downscaled.

  * a white tennis polo (coral collar trim) and white shorts over James's
    normal body, white socks and white sneakers; legs and arms are flat skin;
  * a white headband and white wristbands on both wrists; face and hair are
    James's own pixels;
  * a black-and-yellow racket (strings visible) in the tagging hand in every
    frame, held out in front of the way he faces;
  * tag is a full forehand: in tag frames the tagging arm is redrawn as one
    solid limb (sleeve, upper arm, forearm, wristband, hand) from the
    shoulder, swinging the racket from the back-swing through contact to the
    follow-through. It is drawn over the body, so nothing hides behind it.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_tennis_skin.py [--preview /tmp/tennis_preview.png]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from make_banana_skin import Geometry, alpha_mask, arms_and_hands, components8, grow, skin_mask
from make_pirate_skin import TAG_SIDE, anim_of, pick_hand
from make_tuxedo_skin import close_streaks
from make_wizard_skin import arm_tip, down, over, premul, reach_tip, to_u8, up_mask

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

PAD_TOP = 14
PAD_SIDE = 24
SS = 4

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW": -1, "N": 0, "NE": 1}

WHITE = (247, 247, 243)
SHORTS = (236, 237, 236)
SOCK = (250, 250, 248)
SHOE = (244, 244, 246)
SOLE = (196, 200, 208)
LINE = (70, 74, 84)
TRIM = (240, 112, 92)
BAND = (252, 252, 250)
R_BLACK = (24, 24, 28)
R_YELLOW = (238, 214, 30)
R_GRIP = (40, 40, 44)
STRING = (236, 236, 222)


def S(v):
    return v * SS


def pad_frame(frame):
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def class_layer(classes, line, line_w=0.75, seams=True):
    """Smooth flat-colour layer from 1x class masks (SS RGBA), outlined, with
    a thin seam where two classes meet."""
    classes = [(m, c) for m, c in classes if m.any()]
    if not classes:
        return None
    fields = np.stack([up_mask(m) for m, _ in classes])
    union = up_mask(np.any([m for m, _ in classes], axis=0)) >= 0.5
    lab = fields.argmax(0)
    h, w = union.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for k, (_, col) in enumerate(classes):
        rgb[lab == k] = col
    if seams:
        sm = np.zeros_like(union)
        for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            sm |= np.roll(lab, (dy, dx), (0, 1)) != lab
        sm = np.asarray(Image.fromarray((sm * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 127
        rgb[sm & union] = line
    sil = Image.fromarray((union * 255).astype(np.uint8))
    k = int(round(line_w * SS)) * 2 + 1
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(k))) > 127
    rgb[union & ~inner] = line
    return Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")


def shapes_layer(size, parts, line, line_w=0.7):
    """Vector parts [(draw_fn, colour)] at SS: each part is painted in order,
    the union gets one outline (so a limb reads as a single solid shape)."""
    h, w = size
    rgb = np.zeros((h * SS, w * SS, 3), np.uint8)
    union = np.zeros((h * SS, w * SS), bool)
    for fn, col in parts:
        m = Image.new("L", (w * SS, h * SS), 0)
        fn(ImageDraw.Draw(m))
        mm = np.asarray(m) > 127
        rgb[mm] = col
        union |= mm
    sil = Image.fromarray((union * 255).astype(np.uint8))
    k = int(round(line_w * SS)) * 2 + 1
    inner = np.asarray(sil.filter(ImageFilter.MinFilter(k))) > 127
    rgb[union & ~inner] = line
    return Image.fromarray(np.dstack([rgb, (union * 255).astype(np.uint8)]), "RGBA")


def capsule_fn(p1, r1, p2, r2):
    def fn(d):
        n = 14
        for i in range(n + 1):
            t = i / n
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            r = r1 + (r2 - r1) * t
            d.ellipse([S(x - r), S(y - r), S(x + r), S(y + r)], fill=255)
    return fn


def disc_fn(c, r):
    return lambda d: d.ellipse([S(c[0] - r), S(c[1] - r), S(c[0] + r), S(c[1] + r)], fill=255)


# --- racket --------------------------------------------------------------------
def racket_layer(size, hand, ang):
    """Black frame with yellow accents, open throat, visible string bed. The
    handle starts just behind the hand so the fist closes round the grip."""
    h, w = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ux, uy = math.cos(ang), math.sin(ang)
    nx, ny = -uy, ux

    def P(t, s=0.0):
        return (S(hand[0] + ux * t + nx * s), S(hand[1] + uy * t + ny * s))

    # handle + butt cap
    d.polygon([P(-2.2, 0.9), P(5.0, 0.8), P(5.0, -0.8), P(-2.2, -0.9)], fill=R_GRIP)
    d.ellipse([P(-2.4)[0] - S(1.0), P(-2.4)[1] - S(1.0), P(-2.4)[0] + S(1.0), P(-2.4)[1] + S(1.0)], fill=R_BLACK)
    # throat: two beams opening into the head, yellow inner stripe
    for s in (1, -1):
        d.line([P(4.8, s * 0.6), P(8.9, s * 3.4)], fill=R_BLACK, width=int(S(1.1)))
        d.line([P(5.4, s * 0.6), P(8.6, s * 2.9)], fill=R_YELLOW, width=int(S(0.35)))
    # head
    c = (hand[0] + ux * 14.2, hand[1] + uy * 14.2)
    a, b = 6.2, 4.7
    ring = [(S(c[0] + ux * a * math.cos(t) + nx * b * math.sin(t)),
             S(c[1] + uy * a * math.cos(t) + ny * b * math.sin(t))) for t in np.linspace(0, 2 * math.pi, 48)]
    # string bed (light, semi-clear) + strings
    bed = Image.new("RGBA", im.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bed)
    bd.polygon(ring, fill=(240, 240, 226, 60))
    for k in np.arange(-a + 1.2, a, 1.35):
        bd.line([(S(c[0] + ux * k - nx * b), S(c[1] + uy * k - ny * b)),
                 (S(c[0] + ux * k + nx * b), S(c[1] + uy * k + ny * b))], fill=STRING + (235,), width=max(1, int(S(0.26))))
    for k in np.arange(-b + 1.1, b, 1.3):
        bd.line([(S(c[0] - ux * a + nx * k), S(c[1] - uy * a + ny * k)),
                 (S(c[0] + ux * a + nx * k), S(c[1] + uy * a + ny * k))], fill=STRING + (235,), width=max(1, int(S(0.26))))
    clip = Image.new("L", im.size, 0)
    ImageDraw.Draw(clip).polygon(ring, fill=255)
    bed.putalpha(Image.fromarray(np.minimum(np.asarray(bed.split()[3]), np.asarray(clip))))
    im.alpha_composite(bed)
    d.line(ring + [ring[0]], fill=R_BLACK, width=int(S(1.25)), joint="curve")
    # yellow accents on both sides of the frame and at the tip
    for t0, t1 in ((0.9, 1.5), (-1.5, -0.9), (2.6, 3.7)):
        seg = [(S(c[0] + ux * (a - 0.1) * math.cos(t) + nx * (b - 0.1) * math.sin(t)),
                S(c[1] + uy * (a - 0.1) * math.cos(t) + ny * (b - 0.1) * math.sin(t))) for t in np.linspace(t0, t1, 10)]
        d.line(seg, fill=R_YELLOW, width=int(S(0.55)), joint="curve")
    return im


# --- the drawn tagging arm ----------------------------------------------------------
def ik(sh, hand, L1, L2, bend):
    dx, dy = hand[0] - sh[0], hand[1] - sh[1]
    dd = math.hypot(dx, dy) or 1.0
    dd2 = min(dd, L1 + L2 - 0.05)
    a = (L1 * L1 - L2 * L2 + dd2 * dd2) / (2 * dd2)
    hh = math.sqrt(max(L1 * L1 - a * a, 0.0))
    ux, uy = dx / dd, dy / dd
    px, py = -uy * bend, ux * bend
    return (sh[0] + ux * a + px * hh, sh[1] + uy * a + py * hh)


def arm_parts(sh, elbow, hand, skin):
    ex, ey = hand[0] - elbow[0], hand[1] - elbow[1]
    en = math.hypot(ex, ey) or 1.0
    ux, uy = ex / en, ey / en
    wrist = (hand[0] - ux * 1.6, hand[1] - uy * 1.6)
    band0 = (hand[0] - ux * 3.6, hand[1] - uy * 3.6)
    sx, sy = elbow[0] - sh[0], elbow[1] - sh[1]
    sleeve_end = (sh[0] + sx * 0.4, sh[1] + sy * 0.4)
    return [
        (capsule_fn(sh, 2.4, elbow, 2.0), skin),
        (capsule_fn(elbow, 2.0, wrist, 1.7), skin),
        (capsule_fn(sh, 2.8, sleeve_end, 2.6), WHITE),
        (capsule_fn(band0, 1.95, wrist, 1.95), BAND),
        (disc_fn(hand, 2.1), skin),
    ]


# swing: shoulder->hand angle (deg, screen, y down) over the 6 tag frames, for
# a right-hand-side (+1) arm; racket angle = arm angle + lag
SWING = {
    "profile": ([205, 165, 115, 62, 18, -12], [-35, -30, -25, -30, -38, -55]),
    "front": ([-20, 15, 55, 95, 128, 150], [-40, -25, -5, 15, 30, 35]),
    "back": ([120, 88, 55, 22, -2, -18], [25, 0, -20, -35, -45, -50]),
}


def swing_pose(direction, p_idx):
    if direction in PROFILE:
        arm, lag = SWING["profile"]
        s = PROFILE[direction]
    elif direction in FRONT:
        arm, lag = SWING["front"]
        s = TAG_SIDE[direction]
    else:
        arm, lag = SWING["back"]
        s = TAG_SIDE[direction]
    a, r = arm[p_idx], arm[p_idx] + lag[p_idx]
    if s < 0:
        a, r = 180 - a, 180 - r
    return math.radians(a), math.radians(r)


# --- per frame ----------------------------------------------------------------------
def tennify(frame, direction, anim, col, meta, memo, env_memo):
    f = pad_frame(frame)
    a = alpha_mask(f)
    if not a.any():
        return f
    g = Geometry(f)
    f = close_streaks(f, g.neck + 2)
    a = alpha_mask(f)
    h, w = a.shape
    size = (h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    r_, g_, b_ = (f[..., i].astype(np.int32) for i in range(3))
    skinlike = a & (r_ - b_ > 40) & (r_ > 110)

    rng = meta["animations"].get(anim, {"start": col, "count": 1})
    k = col - rng["start"]
    tag = anim == "tag"
    side = TAG_SIDE[direction]

    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    head = a & (yy <= g.neck + 1)
    head &= ~(arms & (yy > g.neck - 4))
    # the base t-shirt's collar shows a little at the bottom of the head mask
    head &= ~((yy > g.neck - 3) & ~skinlike & (np.abs(xx + 0.5 - g.head_cx) < g.head_hw) &
              (b_ - r_ > 8))
    if direction in PROFILE:
        # only the near arm in side views
        far = np.zeros_like(arms)
        cs = [c for c in components8(arms) if c.sum() >= 4]
        if len(cs) > 1:
            near = max(cs, key=lambda c: c.sum())
            for comp in cs:
                if comp is not near:
                    far |= comp
        arms &= ~far
        hands &= ~far
        a &= ~far

    # torso envelope from the direction's idle frame: in tag frames anything
    # of the old reaching arm outside it goes, inside it becomes shirt
    body0 = a & ~head & ~arms
    if not tag:
        env_memo[direction] = ((body0 | arms) if direction in PROFILE else body0.copy(), g.hip_cx, head.copy(), g.head_cx)
    tag_arm = np.zeros_like(a)
    if tag:
        env, ecx, head0, hcx = env_memo[direction]
        env = np.roll(env, int(round(g.hip_cx - ecx)), 1)
        env = grow(env, np.ones_like(env), 1)
        # the head keeps its idle outline: a reaching hand at chin height goes
        head0 = grow(np.roll(head0, int(round(g.head_cx - hcx)), 1), np.ones_like(head0), 1)
        tag_arm |= head & ~head0
        head &= head0
        for comp in components8(arms):
            ys, xs = np.nonzero(comp)
            if direction in PROFILE or side * (xs.mean() + 0.5 - g.head_cx) > 0:
                tag_arm |= comp
        # reach pixels above the neck line outside the skull
        band = head & (yy >= g.neck - 14) & (yy <= g.neck - 9)
        bx = np.nonzero(band)[1]
        if len(bx):
            strip = head & (yy > g.neck - 12) & ((xx < bx.min() - 1) | (xx > bx.max() + 1))
            head &= ~strip
            tag_arm |= strip
        tside = (xx + 0.5 - g.head_cx) * side > 0 if direction not in PROFILE else np.ones_like(a)
        out_env = a & ~head & ~env & (yy > g.neck - 12) & (yy < g.hem + 5) & tside
        tag_arm |= out_env
        arms &= ~tag_arm
        hands &= ~tag_arm
    body = a & ~head & ~arms & ~tag_arm
    if tag:
        # fill the torso where the old arm lay across it
        hole = tag_arm & env & (yy > g.neck) & (yy < g.hem)
        body |= hole
        # thin outline leftovers of the old arm hugging the torso
        for _ in range(3):
            nb = sum(np.roll(np.roll(body, dy, 0), dx, 1).astype(int) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - body.astype(int)
            body &= ~(~env & (nb.astype(int) < 4) & (yy < g.hem + 5))
        for y in range(g.neck + 1, g.hem):
            xs = np.nonzero((env[y] if direction in PROFILE else body[y] & env[y]))[0]
            if len(xs):
                body[y, xs.min():xs.max() + 1] |= env[y, xs.min():xs.max() + 1]

    # classes
    navy = body & ~skinlike & (b_ - g_ > 11)
    waist = g.hem - 12
    for y in range(g.neck + 6, g.hem):
        row = body[y]
        if row.sum() >= 4 and (navy[y] & row).sum() / row.sum() > 0.4:
            waist = y
            break
    shirt = body & (yy < waist)
    lower = body & (yy >= waist)
    legs_skin = lower & skinlike & (yy >= g.hem - 3)
    shoes = lower & (yy >= g.hem) & ~skinlike
    top_shoe = np.full(w, 10 ** 6)
    for x in range(w):
        ys = np.nonzero(shoes[:, x])[0]
        if len(ys):
            top_shoe[x] = ys.min()
    socks = legs_skin & (yy >= top_shoe[None, :] - 2)
    legs_skin &= ~socks
    shorts = lower & ~legs_skin & ~socks & ~shoes
    sole = shoes & (yy >= g.bottom - 1)
    skin_px = f[face][:, :3]
    skin = tuple(int(v) for v in np.median(skin_px, 0)) if len(skin_px) else (240, 180, 130)
    lum = r_ + g_ + b_
    details = (lower & (yy >= g.hem - 2) & (lum < 70)) | ((shoes | socks) & (lum < 60))
    body_im = class_layer([(shirt, WHITE), (shorts, SHORTS), (legs_skin, skin), (socks, SOCK),
                           (shoes & ~sole, SHOE), (sole, SOLE)], LINE)

    # base arms (non-tag ones): sleeve near the shoulder, skin, wristband, hand
    arm_classes = []
    hands_keep = np.zeros_like(a)
    for comp in components8(arms):
        if comp.sum() < 4:
            continue
        hm = hands & comp
        sk = comp & skinlike & ~hm
        ys = np.nonzero(comp)[0]
        sk_rows = np.nonzero(sk.any(1))[0]
        cut = sk_rows.min() if len(sk_rows) else ys.min() + 6
        cut = min(max(cut, ys.min() + 3), ys.min() + 8)
        sleeve = comp & (yy < cut)
        cuff = comp & ~hm & grow(hm, comp, 2) if hm.any() else np.zeros_like(comp)
        arm_classes += [(sleeve & ~cuff, WHITE), (comp & ~sleeve & ~cuff, skin), (cuff, BAND)]
        hands_keep |= hm
    arm_im = class_layer(arm_classes, LINE, 0.5) if arm_classes else None

    # headband: a strip across the head at the hairline
    hb0 = g.top + 12
    hband = head & (yy >= hb0) & (yy <= hb0 + 3)
    head_band_im = class_layer([(hband, BAND)], LINE, 0.55, seams=False)

    # polo collar: coral V trim at the neck (front views), collar line otherwise
    coll = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    cd = ImageDraw.Draw(coll)
    cy = g.neck + 1.6
    if direction in FRONT:
        cx = g.head_cx + FRONT[direction] * 1.5
        cd.line([(S(cx - 3.4), S(cy)), (S(cx), S(cy + 3.4)), (S(cx + 3.4), S(cy))], fill=TRIM, width=int(S(0.6)), joint="curve")
    elif direction in PROFILE:
        fc = PROFILE[direction]
        cd.line([(S(g.head_cx - fc * 4), S(cy - 0.4)), (S(g.head_cx + fc * 3.2), S(cy + 1.4))], fill=TRIM, width=int(S(0.55)))
    else:
        cd.line([(S(g.head_cx - 4.5), S(cy)), (S(g.head_cx + 4.5), S(cy))], fill=TRIM, width=int(S(0.55)))

    # racket + (tag) the drawn arm
    key = (direction, anim)
    drawn_arm = None
    hand_comp = None
    behind = False
    if tag:
        n = rng["count"]
        ai, ri = swing_pose(direction, min(k, n - 1))
        if direction in PROFILE:
            sh = (g.head_cx - PROFILE[direction] * 0.5, g.neck + 4.5)
        else:
            sh = (g.head_cx + side * 8.0, g.neck + 4.5)
        reach = 15.0
        hand = (sh[0] + math.cos(ai) * reach, sh[1] + math.sin(ai) * reach)
        # elbow droops (down / away from the head)
        e1 = ik(sh, hand, 8.0, 7.6, 1)
        e2 = ik(sh, hand, 8.0, 7.6, -1)
        elbow = e1 if e1[1] >= e2[1] else e2
        drawn_arm = shapes_layer(size, arm_parts(sh, elbow, hand, skin), LINE, 0.6)
        hx, hy = hand
        rang = ri
    else:
        pick = pick_hand(hands & (yy > g.neck + 1), g, side, a)
        tip = arm_tip(arms, g, side)
        ext = reach_tip(a, g, side, waist)
        if ext is not None and (tip is None or side * (ext[0] - tip[0]) > 4.0):
            tip = ext
        if pick is not None and tip is not None and side * (tip[0] - pick[0]) > 4.0:
            pick = None
        if pick is not None:
            hx, hy, hand_comp = pick
        elif tip is not None:
            hx, hy = tip
        elif key in memo:
            hx, hy = memo[key]
        else:
            hx, hy = g.hip_cx + side * 9.0, waist + 2.0
        memo[key] = (hx, hy)
        if direction in PROFILE:
            rang = math.radians(90 - PROFILE[direction] * 62)
        else:
            rang = math.radians(90 - side * 58)
        behind = direction in BACK
    racket_im = racket_layer(size, (hx, hy), rang)
    # base hand pixels closing over the grip (non-tag)
    grip = None
    if hand_comp is not None:
        grip = hand_comp

    cv = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    if behind:
        cv.alpha_composite(racket_im)
    if body_im is not None:
        cv.alpha_composite(body_im)
    cv.alpha_composite(coll)
    if arm_im is not None:
        cv.alpha_composite(arm_im)
    out = down(cv)
    dl = np.zeros((h, w, 4))
    dl[details] = (*[c / 255 for c in LINE], 1.0)
    out = over(out, dl * 0.85)
    out = over(out, premul(f, head.astype(np.float64)))
    if head_band_im is not None:
        out = over(out, down(head_band_im))
    if not behind:
        out = over(out, down(racket_im))
        if grip is not None:
            hand_only = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
            gl = class_layer([(grip, skin)], LINE, 0.55, seams=False)
            if gl is not None:
                out = over(out, down(gl))
    if drawn_arm is not None:
        out = over(out, down(drawn_arm))
    res = to_u8(out)
    res[res[..., 3] < 8] = 0
    # drop stray specks not attached to the figure
    comps = components8(res[..., 3] > 40)
    if comps:
        big = max(comps, key=lambda c: c.sum())
        for c in comps:
            if c is not big and c.sum() < 12:
                res[grow(c, np.ones_like(c), 1) & ~grow(big, np.ones_like(big), 1)] = 0
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    ap.add_argument("--scale", type=int, default=3)
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    ofw, ofh = fw + 2 * PAD_SIDE, fh + PAD_TOP
    out = np.zeros((len(dirs) * ofh, cols * ofw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        memo: dict = {}
        env_memo: dict = {}
        for c in range(cols):
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = tennify(
                fr, direction, anim_of(meta, c), c, meta, memo, env_memo)
    assert max(out.shape[:2]) <= 4096, out.shape
    Image.fromarray(out).save(ASSETS / "kid_tennis.png", optimize=True)
    pm = dict(meta)
    pm["image"] = "kid_tennis.png"
    pm["frameWidth"], pm["frameHeight"] = ofw, ofh
    pm["baselineY"] = meta["baselineY"] + PAD_TOP
    pm["anchorX"] = ofw // 2
    (ASSETS / "kid_tennis.json").write_text(json.dumps(pm, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_tennis.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")
    np.save("/tmp/tennis_full.npy", out)

    if args.preview:
        img = Image.fromarray(out)
        scale, pad = args.scale, 40
        picks = [0, 6, 9, 13, 16, 18, 19, 21, 24, 27]
        pv = Image.new("RGBA", (pad + len(picks) * ofw * scale, pad + len(dirs) * ofh * scale), (40, 40, 40, 255))
        d = ImageDraw.Draw(pv)
        for r in range(len(dirs)):
            for i, c in enumerate(picks):
                cell = Image.new("RGBA", (ofw, ofh), (120, 170, 120, 255) if (r + i) % 2 else (100, 150, 100, 255))
                cell.alpha_composite(img.crop((c * ofw, r * ofh, (c + 1) * ofw, (r + 1) * ofh)))
                pv.paste(cell.resize((ofw * scale, ofh * scale), Image.NEAREST),
                         (pad + i * ofw * scale, pad + r * ofh * scale))
            d.text((4, pad + r * ofh * scale + 10), dirs[r], fill="white")
        for i, c in enumerate(picks):
            d.text((pad + i * ofw * scale + 4, 12), f"{anim_of(meta, c)} {c}", fill="white")
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        pv.convert("RGB").save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
