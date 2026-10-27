"""Shared silhouette helpers for the tennis skin: interior = not reachable from
the frame border through background (alpha < 128) pixels."""
import numpy as np


def _shift(m, dy, dx):
    o = np.zeros_like(m)
    h, w = m.shape
    o[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = m[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return o


def dilate(m):
    o = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            o |= _shift(m, dy, dx)
    return o


def erode(m):
    return ~dilate(~m)


def outside(bg):
    """pixels of bg 4-connected to the border"""
    seed = np.zeros_like(bg)
    seed[0, :] = seed[-1, :] = True
    seed[:, 0] = seed[:, -1] = True
    cur = seed & bg
    while True:
        nxt = (cur | _shift(cur, 1, 0) | _shift(cur, -1, 0) | _shift(cur, 0, 1) | _shift(cur, 0, -1)) & bg
        if (nxt == cur).all():
            return cur
        cur = nxt


def interior(alpha, close_rows=None):
    solid = alpha >= 128
    if close_rows is not None:
        c = erode(dilate(solid))
        rows = np.zeros_like(solid)
        rows[close_rows[0]:close_rows[1]] = True
        solid = solid | (c & rows)
    return ~outside(~solid)


def solidify(res, close_rows=None):
    al = res[..., 3]
    inside = interior(al, close_rows)
    todo = inside & (al < 255)
    if not todo.any():
        return res
    res = res.copy()
    known = inside & (al == 255)
    col = res[..., :3].astype(np.float64) * known[..., None]
    for _ in range(64):
        if not (todo & ~known).any():
            break
        acc = np.zeros_like(col)
        cnt = np.zeros(al.shape)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    k = _shift(known, dy, dx)
                    acc += np.where(k[..., None], np.roll(np.roll(col, dy, 0), dx, 1), 0)
                    cnt += k
        new = todo & ~known & (cnt > 0)
        col[new] = acc[new] / cnt[new][:, None]
        known = known | new
    res[todo, :3] = np.clip(col[todo], 0, 255).astype(np.uint8)
    res[todo, 3] = 255
    return res


def torso_span(f, rows, cx, thr=120):
    """median left/right torso extent from cx: scan outward to the first dark
    outline pixel (after >=3 lit ones) or the silhouette edge"""
    c = f[..., :3].astype(int)
    lum = c.sum(-1)
    # racket string bed / strings (slightly yellow-green, b < g) count as an edge
    lum = np.where((c[..., 1] - c[..., 2] >= 6) & (lum > 300), 0, lum)
    al = f[..., 3] >= 128
    Ls, Rs = [], []
    for y in rows:
        def scan(dx):
            x, seen = cx, 0
            while 0 < x < f.shape[1] - 1:
                x += dx
                if not al[y, x]:
                    return x - dx
                if lum[y, x] < thr:
                    if seen >= 3:
                        return x
                else:
                    seen += 1
            return x
        Ls.append(cx - scan(-1))
        Rs.append(scan(1) - cx)
    return float(np.median(Ls)), float(np.median(Rs))


def base_center(b):
    ys, xs = np.nonzero(b[..., 3][60:72] >= 128)
    return int(round((xs.min() + xs.max()) / 2))
