#!/usr/bin/env python3
"""Build the "Basketball James" skin from the normal kid spritesheet.

Input:  public/assets/kid.png + kid.json (made by tools/slice_kid_sheet.py)
Output: public/assets/kid_basketball.png + kid_basketball.json

Same columns, rows and animation ranges as kid.png. Frames are padded
(PAD_SIDE each side so the ball never clips the cell). Feet stay on the
same row as James (see src/skins.ts).

Per frame:
  1. T-shirt -> navy jersey with orange neck, armhole and hem trim;
     front views get an orange NEW YORK wordmark and number 11, back
     views a larger 11, profiles a 1 on the facing flank;
  2. shorts -> navy with an orange leg hem;
  3. the arm James tags with -> white compression sleeve (hand stays bare);
  4. white headband across the forehead (wraps the hair on back views);
  5. sneakers -> orange with a white sole, side stripe and toe;
  6. an orange basketball with dark seams, dribbled on every frame by the
     other hand. It bounces from that hand to the ground in step with the
     animation, sits beside the body, and is drawn behind the body when
     James faces away.

Face, hair (under the headband) and hands are untouched.

Requires: Python 3 + Pillow + numpy.  Usage:
    python3 tools/make_basketball_skin.py [--preview /tmp/basketball_preview.png]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from make_banana_skin import (  # shared frame analysis helpers
    Geometry,
    alpha_mask,
    arms_and_hands,
    components8,
    grow,
    loose_skin,
    skin_mask,
)
from make_pirate_skin import down, grid, over, premul, to_u8
from make_tuxedo_skin import close_streaks, lum, row_span, torso_rows

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "public" / "assets"

# 10px each side -> 100px frames. 1.2 / 1 / 0.9 / 0.82 / 0.8 / 0.72 of 100
# are whole pixels, so the skins card stays crisp (same trick as pharaoh).
PAD_SIDE = 10
PAD_TOP = 0

FRONT = {"SE": 1, "S": 0, "SW": -1}
PROFILE = {"E": 1, "W": -1}
BACK = {"NW", "N", "NE"}
# Screen side of the hand that reaches in the tag clip (read off kid.png).
# The ball stays in the other hand so the tag arm still reads.
TAG_SIDE = {"E": 1, "SE": 1, "S": 1, "SW": -1, "W": -1, "NW": -1, "N": 1, "NE": 1}

# Feet line of the unpadded kid. The ball rests on this row.
GROUND = 96.0
# A touch bigger than a fist, still narrower than the torso.
BALL_R = 7.3

C = lambda *v: np.array(v, dtype=np.float64)  # noqa: E731
NAVY = C(16, 48, 148)
NAVY_DARK = C(8, 22, 78)
ORANGE = C(242, 96, 18)
ORANGE_HOT = C(255, 138, 42)
WHITE = C(246, 246, 250)
WHITE_SHADE = C(206, 210, 222)
BAND_EDGE = C(36, 40, 58)
SHOE_ORANGE = C(232, 108, 28)
SOLE = C(244, 244, 246)
BALL = C(232, 108, 26)
BALL_DARK = C(186, 72, 16)
BALL_LIGHT = C(255, 176, 92)
SEAM = C(52, 28, 16)
BALL_EDGE = C(92, 40, 12)
INK = C(12, 16, 36)


def shade(col: np.ndarray, l: np.ndarray, lo: float = 0.62, hi: float = 1.16) -> np.ndarray:
    k = lo + (hi - lo) * np.clip((l - 28.0) / 150.0, 0.0, 1.0)
    return col[None, None, :] * k[..., None]


def pad_frame(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    out = np.zeros((fh + PAD_TOP, fw + 2 * PAD_SIDE, 4), dtype=np.uint8)
    out[PAD_TOP:, PAD_SIDE:PAD_SIDE + fw] = frame
    return out


def stamp_pattern(rgb: np.ndarray, ok: np.ndarray, pattern: tuple[str, ...], x0: int, y0: int,
                  fill, edge=None) -> None:
    """Paint a '#' pattern. Optional 1px edge is drawn first so a gap of 3
    stays a 1px split instead of the two glyphs melting together."""
    h, w = ok.shape
    pts = []
    for dy, row in enumerate(pattern):
        for dx, ch in enumerate(row):
            if ch == "#" and 0 <= y0 + dy < h and 0 <= x0 + dx < w:
                pts.append((x0 + dx, y0 + dy))
    if edge is not None:
        seen = set(pts)
        for x, y in pts:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if (xx, yy) in seen:
                        continue
                    if 0 <= xx < w and 0 <= yy < h and ok[yy, xx]:
                        rgb[yy, xx] = edge
    for x, y in pts:
        if ok[y, x]:
            rgb[y, x] = fill


def centered_pattern(pattern: tuple[str, ...], cx: float, y: int) -> tuple[int, int]:
    width = max(len(row) for row in pattern)
    return int(round(cx - (width - 1) / 2)), y


# Bounce amount: 0 = up in the hand, 1 = on the ground.
# Idle, breathe and walk (the skins-card preview) stay up by the hand.
# A full rest on the floor reads as the ball just sitting by the feet.
# Run and tag still bounce all the way down.
def bounce_t(anim: str, index: int) -> float:
    if anim in ("idle", "breathe", "walk"):
        return (0.0, 0.38, 0.62, 0.22)[index % 4]
    if anim == "run":
        return (0.0, 0.70, 1.0, 0.28)[index % 4]
    # tag: 6 frames, squash on the held reach (index 3)
    return (0.08, 0.42, 0.82, 1.0, 0.48, 0.14)[index]


def dribble_hand(f: np.ndarray, g: Geometry, direction: str) -> tuple[float, float]:
    """Hand on the non-tagging side, or a hip fallback."""
    h, w = f.shape[:2]
    yy = np.arange(h)[:, None]
    face = (yy <= g.neck + 1) & skin_mask(f)
    _arms, hands = arms_and_hands(f, g, face)
    side = -TAG_SIDE[direction]
    best: tuple[float, float] | None = None
    best_out = -1e9
    for comp in components8(hands):
        if comp.sum() < 6:
            continue
        ys, xs = np.nonzero(comp)
        cy, cx = float(ys.mean()), float(xs.mean())
        if cy > g.hem - 2:
            continue  # knee / shin false positives
        outward = (cx - g.head_cx) * side
        if outward < 3:
            continue
        if outward > best_out:
            best_out = outward
            best = (cx, cy)
    if best is None:
        return g.head_cx + side * 15.0, float(g.hem - 8)
    return best


def silhouette(alpha: np.ndarray) -> np.ndarray:
    """Opaque pixels that touch transparency. These stay a dark outline
    so a recolor can't leave a white or orange fringe."""
    a = alpha
    pad = np.pad(a, 1, constant_values=False)
    neighbor_clear = (
        ~pad[:-2, 1:-1] | ~pad[2:, 1:-1] | ~pad[1:-1, :-2] | ~pad[1:-1, 2:]
    )
    return a & neighbor_clear


def tagging_arm(arms: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """The arm James tags with, or the tag-side half when both arms touch."""
    h, w = arms.shape
    xx = np.arange(w)[None, :]
    tag = TAG_SIDE[direction]
    comps = [c for c in components8(arms) if c.sum() >= 12]
    if not comps:
        return np.zeros(arms.shape, dtype=bool)

    def score(c: np.ndarray) -> float:
        _ys, xs = np.nonzero(c)
        return (float(xs.mean()) - g.head_cx) * tag

    best = max(comps, key=score)
    if score(best) < 1:
        return np.zeros(arms.shape, dtype=bool)
    _ys, xs = np.nonzero(best)
    if xs.min() < g.head_cx - 3 and xs.max() > g.head_cx + 3:
        best = best & ((xx - g.head_cx) * tag > 1)
    within = arms & ((xx - g.head_cx) * tag > -1)
    return grow(best, within, 1)


def fist_mask(arm: np.ndarray, g: Geometry, direction: str) -> np.ndarray:
    """The outer end of the tagging arm. Wide enough that the hand still
    reads at the end of the sleeve on the reach frame."""
    if not arm.any():
        return np.zeros(arm.shape, dtype=bool)
    h, w = arm.shape
    xx = np.arange(w)[None, :]
    tag = TAG_SIDE[direction]
    ys, xs = np.nonzero(arm)
    outward = (xs.astype(np.float64) - g.head_cx) * tag
    cut = float(outward.max()) - 7.0
    return arm & ((xx - g.head_cx) * tag >= cut) & (np.arange(h)[:, None] > g.neck)


def ball_layer(size, cx: float, cy: float, rx: float, ry: float, shadow: float) -> np.ndarray:
    """Premultiplied basketball + a ground shadow. `shadow` is 0..1 strength."""
    Y, X = grid(size)
    col = np.zeros((*Y.shape, 3), dtype=np.float64)
    alpha = np.zeros(Y.shape, dtype=np.float64)

    # contact shadow, sitting on the ground line
    if shadow > 0.02:
        sx = (X - cx) / (rx * (0.62 + 0.45 * shadow))
        sy = (Y - (GROUND - 0.6)) / 1.55
        sd = sx * sx + sy * sy
        sa = np.clip(1.15 - sd, 0.0, 1.0) * (0.16 + 0.42 * shadow)
        # don't let the shadow paint over the ball fill; ball wins later
        alpha = np.maximum(alpha, sa * 0.85)
        col = np.where(sa[..., None] > 0.04, INK, col)

    nx = (X - cx) / max(rx, 0.1)
    ny = (Y - cy) / max(ry, 0.1)
    r = np.hypot(nx, ny)
    # coverage in pixels (rx is the horizontal radius)
    aa = np.clip((1.04 - r) * min(rx, ry), 0.0, 1.0)
    inside = aa > 0.02
    # panel shading: left-lit, a little darker toward the bottom
    light = 0.78 + 0.28 * np.clip(0.55 - 0.65 * nx - 0.35 * ny, -0.35, 0.7)
    base = BALL * light[..., None]
    base = np.where((ny > 0.15)[..., None], base * 0.92 + BALL_DARK * 0.08, base)
    # specular on the upper-left
    spec = np.exp(-((nx + 0.38) ** 2 + (ny + 0.42) ** 2) / 0.08)
    base = base * (1 - 0.65 * spec[..., None]) + BALL_LIGHT * spec[..., None]
    col = np.where(inside[..., None], base, col)
    alpha = np.where(inside, np.maximum(alpha, aa), alpha)

    # seams in normalised ball space, so they follow the squash
    def seam(mask: np.ndarray) -> None:
        m = mask & (r < 0.96)
        col[m] = SEAM
        alpha[m] = np.maximum(alpha[m], aa[m])

    seam(np.abs(ny) < 0.055)
    seam(np.abs(nx - 0.12 * np.sin(ny * np.pi)) < 0.05)
    seam((np.abs(np.abs(nx) - 0.55) < 0.045) & (np.abs(ny) < 0.62))
    # outline
    edge = inside & (r > 0.84)
    col[edge] = BALL_EDGE
    return down(col, alpha, size)


def paint_uniform(f: np.ndarray, g: Geometry, direction: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Recolour clothes. Returns (rgba, jersey mask, hand mask)."""
    f = close_streaks(f, g.neck + 2)
    g = Geometry(f)
    a = alpha_mask(f)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    L = lum(f)
    out = f.copy()
    rgb = out[..., :3].astype(np.float64)

    face = (yy <= g.neck + 1) & skin_mask(f)
    arms, hands = arms_and_hands(f, g, face)
    hands = grow(hands, loose_skin(f) & (yy > g.neck), 1)
    sk = loose_skin(f)
    outline = a & (L < 42)

    waist = g.hem - 9
    clothes = a & (yy > g.neck) & ~sk & ~outline & ~hands
    jersey = clothes & (yy <= waist + 1)
    shorts = clothes & (yy > waist) & (yy < g.hem + 2)
    shins = a & sk & (yy >= g.hem) & ~arms & ~hands
    shoes = a & (yy >= g.hem + 2) & ~sk & ~shins & ~arms

    rim = silhouette(a)
    # interior cloth only. The 1px rim is painted last, one dark colour,
    # so anti-aliased shirt pixels can't turn into a speckled halo.
    rgb = np.where((jersey & ~rim)[..., None], shade(NAVY, L, 0.78, 1.12), rgb)
    rgb = np.where((shorts & ~rim)[..., None], shade(NAVY_DARK, L, 0.85, 1.15), rgb)

    arm = tagging_arm(arms | (outline & grow(arms, a, 1)), g, direction)
    fist = fist_mask(arm & ~rim, g, direction)
    # the original hand detector, so a hanging arm still ends in skin
    fist = fist | (hands & arm & ~rim)
    sleeve = arm & ~fist & ~rim & (yy > g.neck)
    if sleeve.any():
        rgb = np.where(sleeve[..., None], shade(WHITE, L, 0.92, 1.02), rgb)
        cuff = grow(fist, sleeve, 1) & sleeve
        rgb = np.where(cuff[..., None], WHITE_SHADE, rgb)
    # put the fist back in the kid's own skin, on top of the sleeve
    rgb = np.where(fist[..., None], f[..., :3].astype(np.float64), rgb)

    # orange trim sits one pixel in from the silhouette
    inner = ~rim
    jtop, jbot = torso_rows(jersey & inner)
    if jtop is not None:
        neck = jersey & inner & (yy <= jtop + 1) & (yy > g.neck + 1)
        hem = jersey & inner & (yy >= jbot - 1)
        rgb = np.where(neck[..., None], ORANGE, rgb)
        rgb = np.where(hem[..., None], ORANGE, rgb)
    # armhole: only the shoulder, not a trail of orange down the sleeve
    shoulder = jersey & inner & grow(sleeve, a, 1) & (yy <= g.neck + 8)
    rgb = np.where(shoulder[..., None], ORANGE, rgb)
    if shorts.any():
        ys = np.nonzero((shorts & inner).any(axis=1))[0]
        if len(ys):
            cuff_rows = np.zeros_like(shorts)
            cuff_rows[ys[-1]] = shorts[ys[-1]] & inner[ys[-1]]
            if len(ys) > 3:
                cuff_rows[ys[-2]] = shorts[ys[-2]] & inner[ys[-2]]
            rgb = np.where(cuff_rows[..., None], ORANGE, rgb)

    # sneakers: the tan ankle and the dark shoe both become jersey orange.
    # Shading from the original near-black pixels was reading as brown.
    footwear = a & (yy >= g.hem) & ~jersey & ~shorts & ~arms & ~hands & ~fist
    if footwear.any():
        rgb = np.where((footwear & ~rim)[..., None], ORANGE, rgb)
        for comp in components8(footwear):
            if comp.sum() < 4:
                continue
            ys, xs = np.nonzero(comp)
            y1 = int(ys.max())
            sole = comp & ~rim & (yy >= y1 - 2)
            rgb = np.where(sole[..., None], SOLE, rgb)
            stripe_y = int(ys.min() + max(1, (y1 - int(ys.min())) * 0.42))
            stripe = comp & ~rim & (yy == stripe_y)
            rgb = np.where(stripe[..., None], WHITE, rgb)
            face_side = PROFILE.get(direction, FRONT.get(direction, 0))
            if face_side == 0:
                left, right = int(xs.min()), int(xs.max())
                toe = comp & ~rim & ((xx <= left + 1) | (xx >= right - 1)) & (yy <= y1 - 3)
            else:
                end = int(xs.max() if face_side > 0 else xs.min())
                toe = comp & ~rim & (np.abs(xx - end) <= 1) & (yy <= y1 - 3)
            rgb = np.where(toe[..., None], WHITE, rgb)

    # headband: a white wrap on the hairline, above the eyes. Filled
    # across each row so hair spikes don't poke holes through it.
    band0 = g.top + 14
    band1 = g.top + 17
    for y in range(band0, band1):
        if not (0 <= y < h):
            continue
        xs = np.nonzero(a[y] & (np.abs(np.arange(w) - g.head_cx) <= g.head_hw + 2))[0]
        if len(xs) < 5:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        if y == band0:
            col = BAND_EDGE
        elif y == band1 - 1:
            col = WHITE_SHADE
        else:
            col = WHITE
        for x in range(x0, x1 + 1):
            # the hair's own outline stays dark; painting it white is the halo
            if rim[y, x]:
                continue
            # stay inside the head: don't bridge a real gap beside an ear
            if x0 < x < x1 and not a[y, x]:
                # only fill 1-2px holes
                if not (a[y, x - 1] and a[y, min(w - 1, x + 1)]):
                    continue
            rgb[y, x] = col
            out[y, x, 3] = 255

    # chest lettering. At this scale "NEW YORK" is a readable NY wordmark
    # over a blocky 11; the back is just 11; profiles show a 1 on the
    # flank that faces the camera. Gaps are wide enough that the outline
    # doesn't glue the digits together.
    painted = np.abs(rgb - ORANGE).sum(-1) > 40
    chest = jersey & painted & (yy > (jtop + 1 if jtop is not None else g.neck))
    cx = g.head_cx + FRONT.get(direction, 0) * 2.0
    # N and Y, one column apart. Reads as the NEW YORK wordmark.
    ny = ("#.#.#.#", "###.#.#", "#.#..#.")
    num = ("##...##", "##...##", "##...##", "##...##", "##...##")
    big = ("##....##", "##....##", "##....##", "##....##", "##....##", "##....##", "##....##")
    one = ("##", "##", "##", "##", "##", "##")
    # No outline: a 1px gap is the whole letter at this scale, and the
    # outline was gluing NY and the two 1s into one orange blob.
    if direction in FRONT:
        name_y = (jtop + 3) if jtop is not None else g.neck + 4
        stamp_pattern(rgb, chest, ny, *centered_pattern(ny, cx, name_y), ORANGE_HOT)
        stamp_pattern(rgb, chest, num, *centered_pattern(num, cx, name_y + 4), ORANGE_HOT)
    elif direction in BACK:
        num_y = (jtop + 3) if jtop is not None else g.neck + 4
        shift = {"NW": -1.5, "N": 0.0, "NE": 1.5}[direction]
        stamp_pattern(rgb, chest, big, *centered_pattern(big, cx + shift, num_y), ORANGE_HOT)
    else:
        side = PROFILE[direction]
        num_y = (jtop + 4) if jtop is not None else g.neck + 5
        flank = int(round(g.head_cx + side * 5 - (1 if side > 0 else 0)))
        stamp_pattern(rgb, chest, one, flank, num_y, ORANGE_HOT)

    # one dark rim around the body, after every recolor, so jersey, shorts,
    # sleeve and shoe edges match the other skins' crisp outline
    body_rim = rim & (yy > g.neck + 1)
    rgb = np.where(body_rim[..., None], INK, rgb)
    soft = (out[..., 3] > 0) & (out[..., 3] < 240) & (yy > g.neck + 1)
    rgb = np.where(soft[..., None], INK, rgb)
    out[..., 3] = np.where(soft, np.uint8(255), out[..., 3])

    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out, chest, hands | fist


def place_ball(body: np.ndarray, g: Geometry, direction: str, anim: str, index: int) -> tuple[float, float, float, float, bool]:
    """cx, cy, rx, ry, behind."""
    side = -TAG_SIDE[direction]
    _hx, hy = dribble_hand(body, g, direction)
    behind = direction in BACK or direction in PROFILE
    t = bounce_t(anim, index)
    squashed = t > 0.92
    ry = BALL_R * (0.74 if squashed else 1.0)
    rx = BALL_R * (1.12 if squashed else 1.0)
    # Inner edge tucks into the silhouette. Front views tuck more so the
    # hand reads as gripping the ball; back/profile views only hide a sliver.
    # Fixed offset from the head, not the swinging hip. A step used to
    # drag the ball sideways; it should only bounce. Profiles and the
    # back sit a little further out so the rear foot doesn't swallow the
    # ball, and the tag / run clips nudge it out with the wider stance.
    outward = {"E": 18.4, "SE": 17.2, "S": 17.6, "SW": 17.2,
               "W": 18.4, "NW": 17.8, "N": 20.2, "NE": 17.8}[direction]
    if anim == "tag":
        outward += 2.4
    elif anim == "run":
        outward += 1.4
    bx = g.head_cx + side * outward
    if squashed:
        bx += side * (rx - BALL_R) * 0.4
    # Top of the bounce sits in the hand. Clamped so a raised run arm
    # can't carry the ball up to the chest.
    cy_hand = float(np.clip(hy + 1.2, g.hem - 18.0, g.hem - 8.0))
    cy_ground = GROUND - ry
    cy = cy_hand + (cy_ground - cy_hand) * (t ** 1.15)
    margin = 1.2
    bx = float(np.clip(bx, rx + margin, body.shape[1] - rx - margin))
    return bx, float(cy), float(rx), float(ry), behind


def baller(frame: np.ndarray, direction: str, anim: str, index: int) -> np.ndarray:
    src = pad_frame(frame)
    if not alpha_mask(src).any():
        return src
    g = Geometry(src)
    body, _chest, hands = paint_uniform(src, g, direction)
    # geometry may have shifted a pixel after streak-filling; re-read it
    g = Geometry(body)
    bx, by, rx, ry, behind = place_ball(body, g, direction, anim, index)
    t = bounce_t(anim, index)
    layer = ball_layer(body.shape[:2], bx, by, rx, ry, shadow=0.25 + 0.75 * t)
    body_p = premul(body)
    if behind:
        merged = to_u8(over(layer, body_p))
    else:
        merged = to_u8(over(body_p, layer))
        # the dribbling hand stays in front of the ball
        grip = grow(hands, alpha_mask(body), 1)
        merged[grip] = body[grip]
    return merged


def anim_of(col: int, meta: dict) -> tuple[str, int]:
    for name, spec in meta["animations"].items():
        if spec["start"] <= col < spec["start"] + spec["count"]:
            return name, col - spec["start"]
    return "idle", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=Path, help="write a labelled contact sheet")
    args = ap.parse_args()

    meta = json.loads((ASSETS / "kid.json").read_text())
    fw, fh, cols = meta["frameWidth"], meta["frameHeight"], meta["columns"]
    dirs = meta["directions"]
    src = np.asarray(Image.open(ASSETS / meta["image"]).convert("RGBA"))
    ofh = fh + PAD_TOP
    ofw = fw + 2 * PAD_SIDE
    out = np.zeros((len(dirs) * ofh, cols * ofw, 4), dtype=np.uint8)
    for r, direction in enumerate(dirs):
        for c in range(cols):
            anim, index = anim_of(c, meta)
            fr = src[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            out[r * ofh:(r + 1) * ofh, c * ofw:(c + 1) * ofw] = baller(fr, direction, anim, index)
    Image.fromarray(out).save(ASSETS / "kid_basketball.png", optimize=True)
    bb = dict(meta)
    bb["image"] = "kid_basketball.png"
    bb["frameWidth"] = ofw
    bb["frameHeight"] = ofh
    bb["baselineY"] = meta["baselineY"] + PAD_TOP
    bb["anchorX"] = meta["anchorX"] + PAD_SIDE
    (ASSETS / "kid_basketball.json").write_text(json.dumps(bb, indent=2) + "\n")
    print(f"wrote {ASSETS / 'kid_basketball.png'} ({out.shape[1]}x{out.shape[0]}) frames {ofw}x{ofh}")

    if args.preview:
        from PIL import ImageDraw
        scale, pad = 3, 46
        # one cell per animation frame that the game actually plays, plus idle
        groups = [("idle", 0, 4), ("breathe", 12, 4), ("walk", 4, 8), ("run", 22, 8), ("tag", 16, 6)]
        picks: list[tuple[str, int]] = []
        for name, start, count in groups:
            for i in range(count):
                picks.append((name, start + i))
        pv = Image.new("RGB", (pad + len(picks) * ofw * scale, pad + len(dirs) * ofh * scale), (46, 120, 72))
        d = ImageDraw.Draw(pv)
        sheet = Image.fromarray(out)
        for r in range(len(dirs)):
            for i, (_name, c) in enumerate(picks):
                cell = sheet.crop((c * ofw, r * ofh, (c + 1) * ofw, (r + 1) * ofh))
                bg = Image.new("RGBA", (ofw, ofh), (120, 186, 96, 255))
                bg.alpha_composite(cell)
                pv.paste(bg.resize((ofw * scale, ofh * scale), Image.NEAREST).convert("RGB"),
                         (pad + i * ofw * scale, pad + r * ofh * scale))
            d.text((4, pad + r * ofh * scale + 8), dirs[r], fill="white")
        label_x = pad
        for name, _start, count in groups:
            d.text((label_x + 4, 8), name, fill="white")
            label_x += count * ofw * scale
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        pv.save(args.preview)
        print(f"wrote {args.preview} ({pv.size[0]}x{pv.size[1]})")


if __name__ == "__main__":
    main()
