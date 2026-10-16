#!/usr/bin/env python3
"""Derive the cave sprites from the reference picture.

The picture is a filtered blow-up of three sprites (old man, fire, sword).
This finds each one, snaps it back onto that shared pixel grid, and maps
every cell to a small palette so the soft edges become hard pixels. Black
turns transparent. The fire is written twice: the cleaned frame and its
horizontal mirror, which is the second flicker frame.

    python3 tools/make_cave_sprites.py

Input:  tools/cave_sprite_reference.png
Output: public/assets/cave/old-man.png
        public/assets/cave/fire-0.png
        public/assets/cave/fire-1.png
        public/assets/cave/sword.png
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_REFERENCE = HERE / "cave_sprite_reference.png"
DEFAULT_OUT = HERE.parent / "public" / "assets" / "cave"

# A short NES-like palette. Near-black source pixels stay transparent
# instead of being pulled onto one of these.
PALETTE = np.array(
    [
        [252, 252, 252],  # white: beard, brows, mustache, blade, flame core
        [248, 196, 144],  # peach face
        [236, 148, 56],  # orange hair, sleeves, flame, feet
        [255, 208, 48],  # yellow flame
        [188, 40, 32],  # red robe and hilt
        [136, 32, 24],  # dark red shade
        [160, 80, 32],  # brown
        [208, 208, 208],  # blade highlight
        [96, 96, 96],  # blade shade
    ],
    dtype=np.float32,
)

DARK = 90.0


def components(ink: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Return (count, x0, y0, x1, y1) for each connected ink blob."""
    h, w = ink.shape
    seen = np.zeros_like(ink)
    found: list[tuple[int, int, int, int, int]] = []
    for y in range(h):
        for x in range(w):
            if not ink[y, x] or seen[y, x]:
                continue
            q: deque[tuple[int, int]] = deque([(y, x)])
            seen[y, x] = True
            count = 0
            x0 = x1 = x
            y0 = y1 = y
            while q:
                cy, cx = q.popleft()
                count += 1
                x0, x1 = min(x0, cx), max(x1, cx)
                y0, y1 = min(y0, cy), max(y1, cy)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and ink[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            found.append((count, x0, y0, x1, y1))
    found.sort(reverse=True)
    return found


def white_count(src: np.ndarray, box: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = box
    crop = src[y0 : y1 + 1, x0 : x1 + 1]
    return int(((crop[:, :, 0] > 200) & (crop[:, :, 1] > 200) & (crop[:, :, 2] > 170)).sum())


def choose_sprites(src: np.ndarray) -> dict[str, tuple[int, int, int, int]]:
    ink = src.sum(axis=2) > 40
    blobs = [b for b in components(ink) if b[0] > 80]
    if len(blobs) < 3:
        raise SystemExit(f"expected 3 sprites, found {len(blobs)}")
    # The sword is the thin tall one. The old man is the square sprite with
    # the white beard; the other square sprite is the fire.
    def aspect(b: tuple[int, int, int, int, int]) -> float:
        return (b[4] - b[2] + 1) / (b[3] - b[1] + 1)

    sword = max(blobs, key=aspect)
    squares = [b for b in blobs if b is not sword]
    squares.sort(key=lambda b: white_count(src, b[1:]), reverse=True)
    man, fire = squares[0], squares[1]
    # Sparks sit just off the flame. Pull in any small blob that touches
    # the fire's neighborhood so they survive the crop.
    fx0, fy0, fx1, fy1 = fire[1:]
    for blob in blobs:
        if blob is man or blob is fire or blob is sword:
            continue
        x0, y0, x1, y1 = blob[1:]
        if x1 < fx0 - 8 or x0 > fx1 + 8 or y1 < fy0 - 8 or y0 > fy1 + 8:
            continue
        fx0, fy0 = min(fx0, x0), min(fy0, y0)
        fx1, fy1 = max(fx1, x1), max(fy1, y1)
    return {"man": man[1:], "fire": (fx0, fy0, fx1, fy1), "sword": sword[1:]}


def grid_cells(src: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """Pixel size of the blow-up. Prefer a grid near 16 across the old man."""
    x0, y0, x1, y1 = box
    crop = src[y0 : y1 + 1, x0 : x1 + 1]
    height, width, _ = crop.shape
    best_n = 16
    best_score = None
    for n in range(12, 21):
        total = 0.0
        used = 0
        for iy in range(n):
            ys, ye = int(iy * height / n), int((iy + 1) * height / n)
            for ix in range(n):
                xs, xe = int(ix * width / n), int((ix + 1) * width / n)
                cell = crop[ys : max(ys + 1, ye), xs : max(xs + 1, xe)]
                if float(cell.mean()) < 25:
                    continue
                total += float(cell.std())
                used += 1
        score = total / max(used, 1) + abs(n - 16) * 1.5
        if best_score is None or score < best_score:
            best_score = score
            best_n = n
    return ((width / best_n) + (height / best_n)) / 2


def downsample(src: np.ndarray, box: tuple[int, int, int, int], cell: float) -> np.ndarray:
    """One native pixel per cell: the palette color that covers that cell."""
    x0, y0, x1, y1 = box
    x0 = max(0, x0 - 1)
    y0 = max(0, y0 - 1)
    x1 = min(src.shape[1] - 1, x1 + 1)
    y1 = min(src.shape[0] - 1, y1 + 1)
    crop = src[y0 : y1 + 1, x0 : x1 + 1]
    height, width, _ = crop.shape
    native_w = max(1, int(round(width / cell)))
    native_h = max(1, int(round(height / cell)))
    out = np.zeros((native_h, native_w, 4), np.uint8)
    for iy in range(native_h):
        ys = int(round(iy * height / native_h))
        ye = int(round((iy + 1) * height / native_h))
        for ix in range(native_w):
            xs = int(round(ix * width / native_w))
            xe = int(round((ix + 1) * width / native_w))
            block = crop[ys : max(ys + 1, ye), xs : max(xs + 1, xe)]
            # Nearest source pixel: the one at the center of the cell.
            center = block[block.shape[0] // 2, block.shape[1] // 2]
            samples = block.reshape(-1, 3)
            dark = samples.sum(axis=1) < DARK
            if float(dark.mean()) > 0.65 and float(center.sum()) < DARK:
                continue
            dist = ((samples[:, None, :] - PALETTE[None, :, :]) ** 2).sum(axis=2)
            votes = dist.argmin(axis=1)
            lit = votes[~dark] if (~dark).any() else votes
            center_i = int(((PALETTE - center) ** 2).sum(axis=1).argmin())
            values, counts = np.unique(lit, return_counts=True)
            majority = int(values[int(counts.argmax())])
            # Keep the center sample when it is a real color and not a
            # one-pixel fringe. Otherwise the cell's majority color wins,
            # which is what knocks the blur off the edges.
            share = float((lit == center_i).mean()) if len(lit) else 0.0
            chosen = center_i if share >= 0.25 and float(center.sum()) >= DARK else majority
            rgb = PALETTE[chosen]
            out[iy, ix, :3] = rgb.astype(np.uint8)
            out[iy, ix, 3] = 255
    return trim(out)


def trim(image: np.ndarray) -> np.ndarray:
    opaque = image[:, :, 3] > 0
    if not opaque.any():
        return image
    rows = np.where(opaque.any(axis=1))[0]
    cols = np.where(opaque.any(axis=0))[0]
    return image[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]


def save_rgba(image: np.ndarray, path: Path) -> None:
    Image.fromarray(image, "RGBA").save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    src = np.asarray(Image.open(args.reference).convert("RGB")).astype(np.float32)
    boxes = choose_sprites(src)
    cell = grid_cells(src, boxes["man"])
    print(f"pixel scale {cell:.2f}px")
    args.out.mkdir(parents=True, exist_ok=True)
    frames: dict[str, np.ndarray] = {}
    for name in ("man", "fire", "sword"):
        sprite = downsample(src, boxes[name], cell)
        frames[name] = sprite
        print(f"{name:5} box {boxes[name]} -> {sprite.shape[1]}x{sprite.shape[0]}")
    save_rgba(frames["man"], args.out / "old-man.png")
    save_rgba(frames["fire"], args.out / "fire-0.png")
    flipped = np.flip(frames["fire"], axis=1).copy()
    save_rgba(flipped, args.out / "fire-1.png")
    save_rgba(frames["sword"], args.out / "sword.png")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
