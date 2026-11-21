#!/usr/bin/env python3
"""Generate the seamless stone-wall backdrop tiles (static/stone-dark.svg, static/stone-light.svg).

Irregular, hand-built-looking masonry: rows of different heights, stones of different widths,
wobbly edges, chipped corners, cracks, moss and water stains. Seeded, so output is reproducible.
Usage: python scripts/gen_stone.py
"""
import random
from pathlib import Path

W, H = 960, 480
ROWS = [52, 64, 44, 80, 58, 70, 46, 66]   # row heights, sum == H
GAP = 6                           # mortar width

THEMES = {
    "dark": dict(
        mortar="#0d0d10", stones=["#24242a", "#2a2a31", "#202026", "#2d2d34", "#26262c", "#2b2a2f", "#222127"],
        hi="rgba(255,255,255,.075)", shade="rgba(0,0,0,.45)", crack="rgba(0,0,0,.55)",
        moss="rgba(80,112,62,.40)", stain="rgba(0,0,0,.28)", chip="#0d0d10"),
    "light": dict(
        mortar="#dfd4bb", stones=["#f5eedf", "#f1e9d6", "#f7f2e6", "#ece3cd", "#f3ecdb", "#eee5d1", "#f6f0e2"],
        hi="rgba(255,255,255,.7)", shade="rgba(120,90,40,.28)", crack="rgba(105,78,38,.45)",
        moss="rgba(110,138,72,.28)", stain="rgba(120,90,40,.13)", chip="#dfd4bb"),
}


def partition(rng, total, lo=70, hi=175):
    while True:
        parts, left = [], total
        while left > hi + lo:
            w = rng.randint(lo, hi)
            parts.append(w); left -= w
        if lo <= left <= hi + 20:
            parts.append(left)
            return parts


def j(rng, v, a):
    return v + rng.uniform(-a, a)


def stone_points(rng, x0, y0, x1, y1):
    """Wobbly rectangle: jittered corners plus jittered edge midpoints, one chipped corner sometimes."""
    pts = [(j(rng, x0, 2.2), j(rng, y0, 2.2)), (j(rng, (x0 + x1) / 2, 6), j(rng, y0, 1.4)),
           (j(rng, x1, 2.2), j(rng, y0, 2.2)), (j(rng, x1, 1.4), j(rng, (y0 + y1) / 2, 4)),
           (j(rng, x1, 2.2), j(rng, y1, 2.2)), (j(rng, (x0 + x1) / 2, 6), j(rng, y1, 1.4)),
           (j(rng, x0, 2.2), j(rng, y1, 2.2)), (j(rng, x0, 1.4), j(rng, (y0 + y1) / 2, 4))]
    if rng.random() < 0.3:                                   # chipped corner
        c = rng.choice([0, 2, 4, 6]); px, py = pts[c]
        dx = 9 if px < (x0 + x1) / 2 else -9
        dy = 8 if py < (y0 + y1) / 2 else -8
        pts[c:c + 1] = [(px + dx, py), (px + dx * .35, py + dy * .35), (px, py + dy)]
    return pts


def poly(pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def stone_svg(rng, th, x, y, w, rh):
    """One stone with all its weathering, as SVG, positioned at (x, y)."""
    x0, y0, x1, y1 = x + GAP / 2, y + GAP / 2, x + w - GAP / 2, y + rh - GAP / 2
    pts = stone_points(rng, x0, y0, x1, y1)
    fill = rng.choice(th["stones"])
    out = [f'<polygon points="{poly(pts)}" fill="{fill}" stroke="{fill}" stroke-width="2" stroke-linejoin="round"/>']
    if rng.random() < 0.85:                                           # tonal patch so no two stones read the same
        px, py = rng.uniform(x0 + 8, x1 - 8), rng.uniform(y0 + 6, y1 - 6)
        out.append(f'<ellipse cx="{px:.1f}" cy="{py:.1f}" rx="{rng.uniform(10, w / 3):.1f}" ry="{rng.uniform(5, rh / 3):.1f}" fill="{th["shade"]}" opacity="{rng.uniform(.10, .30):.2f}"/>')
    out.append(f'<polyline points="{poly(pts[6:] + pts[:3])}" fill="none" stroke="{th["hi"]}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>')
    out.append(f'<polyline points="{poly(pts[2:7])}" fill="none" stroke="{th["shade"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>')
    for _crack in range(2 if rng.random() < 0.12 else 1):
      if rng.random() < 0.40:                                         # crack
        cx, cy = rng.uniform(x0 + 12, x1 - 12), y0 + rng.uniform(1, 5)
        seg = [(cx, cy)]
        for _ in range(rng.randint(4, 7)):
            cx = min(max(cx + rng.uniform(-8, 8), x0 + 6), x1 - 6); cy = min(cy + rng.uniform(5, 12), y1 - 3)
            seg.append((cx, cy))
        out.append(f'<polyline points="{poly(seg)}" fill="none" stroke="{th["crack"]}" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>')
    if rng.random() < 0.36:                                           # moss creeping up from the mortar
        mx = rng.uniform(x0 + 10, x1 - 10)
        out.append(f'<ellipse cx="{mx:.1f}" cy="{y1 - 1:.1f}" rx="{rng.uniform(16, 34):.1f}" ry="{rng.uniform(7, 14):.1f}" fill="url(#m)"/>')
    if rng.random() < 0.30:                                           # water stain running down
        sx = rng.uniform(x0 + 8, x1 - 20)
        out.append(f'<rect x="{sx:.1f}" y="{y0:.1f}" width="{rng.uniform(8, 18):.1f}" height="{(y1 - y0) * rng.uniform(.6, 1):.1f}" fill="url(#s)"/>')
    if rng.random() < 0.35:                                           # grime in a corner
        gx = rng.choice([x0 + 6, x1 - 6]); gy = rng.choice([y0 + 5, y1 - 5])
        out.append(f'<ellipse cx="{gx:.1f}" cy="{gy:.1f}" rx="{rng.uniform(10, 22):.1f}" ry="{rng.uniform(5, 11):.1f}" fill="{th["shade"]}" opacity="{rng.uniform(.15, .35):.2f}"/>')
    return "".join(out)


def build(name, th, seed):
    rng = random.Random(seed)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           '<defs>'
           f'<radialGradient id="m"><stop offset="0" stop-color="{th["moss"]}"/><stop offset="1" stop-color="{th["moss"]}" stop-opacity="0"/></radialGradient>'
           f'<linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{th["stain"]}"/><stop offset="1" stop-color="{th["stain"]}" stop-opacity="0"/></linearGradient>'
           '</defs>',
           f'<rect width="{W}" height="{H}" fill="{th["mortar"]}"/>']
    y, prev_joints = 0, []
    for rh in ROWS:
        # every row starts at its own random offset and wraps around the tile edge, so no joint
        # lines up with the previous row's (that would read as a long vertical crack in the wall)
        for _ in range(200):
            widths, ox = partition(rng, W), rng.uniform(0, W)
            joints, acc = [], 0
            for w in widths:
                joints.append((ox + acc) % W); acc += w
            if all(min(abs(a - b), W - abs(a - b)) > 24 for a in joints for b in prev_joints):
                break
        prev_joints = joints
        acc = 0
        for w in widths:
            xs = (ox + acc) % W
            svg = stone_svg(rng, th, xs, y, w, rh)
            out.append(svg)
            if xs + w > W:                                            # stone straddles the tile edge: draw its other half
                out.append(f'<g transform="translate({-W},0)">{svg}</g>')
            acc += w
        y += rh
    out.append('</svg>')
    return "\n".join(out)


if __name__ == "__main__":
    dest = Path(__file__).resolve().parent.parent / "src" / "drollery" / "static"
    for i, (name, th) in enumerate(THEMES.items()):
        (dest / f"stone-{name}.svg").write_text(build(name, th, seed=11 + i * 7))
        print("wrote", dest / f"stone-{name}.svg")
