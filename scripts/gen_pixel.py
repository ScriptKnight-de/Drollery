#!/usr/bin/env python3
"""Draw the assets of the "Pixel" style: block-built medieval scenes, a pixel skyline and the stone tiles.

    python scripts/gen_pixel.py

Writes templates/doodles/pixel/*.svg (eight 20 by 20 scenes), static/pixel-skyline.svg (a mask for the header ornament) and
static/pixel-stone-dark.svg / pixel-stone-light.svg (see-through brick tiles over the page colour, which carries the highlight colour).

A dot of a scene has a letter; the letter is a CSS class (p<letter>, see static/style-pixel.css). Most are fixed colours, but
A, a and q are the highlight colour (normal, dark, light), so the scenes follow the highlight switch. Every scene gets a one-dot
dark outline and stands on a grass block. Drawn in code, so the output is reproducible.
"""
from __future__ import annotations

import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZE = 20


class Canvas:
    def __init__(self, w: int = SIZE, h: int = SIZE):
        self.w, self.h = w, h
        self.d = [["."] * w for _ in range(h)]

    def px(self, x: int, y: int, c: str) -> "Canvas":
        if 0 <= x < self.w and 0 <= y < self.h:
            self.d[y][x] = c
        return self

    def rect(self, x: int, y: int, w: int, h: int, c: str) -> "Canvas":
        for j in range(y, y + h):
            for i in range(x, x + w):
                self.px(i, j, c)
        return self

    def speckle(self, x: int, y: int, w: int, h: int, c: str, seed: int, every: int = 5) -> "Canvas":
        """Scatter a second shade over a block, like the noise of a block texture."""
        rng = random.Random(seed)
        for j in range(y, y + h):
            for i in range(x, x + w):
                if 0 <= i < self.w and 0 <= j < self.h and self.d[j][i] != "." and rng.randrange(every) == 0:
                    self.d[j][i] = c
        return self

    def ground(self) -> "Canvas":
        """A grass block under the scene: green top with dirt drips, then dirt."""
        rng = random.Random(7)
        for x in range(self.w):
            self.d[16][x] = "G"
            self.d[17][x] = "G" if rng.randrange(3) else "W"
            for y in (18, 19):
                self.d[y][x] = "W" if rng.randrange(4) else "w"
        for x in range(self.w):
            if rng.randrange(4) == 0:
                self.d[16][x] = "g"
        return self

    def outline(self) -> "Canvas":
        out = [row[:] for row in self.d]
        for y in range(self.h):
            for x in range(self.w):
                if self.d[y][x] != ".":
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.w and 0 <= ny < self.h and self.d[ny][nx] not in (".", "K"):
                        out[y][x] = "K"
                        break
        self.d = out
        return self

    def svg(self, title: str) -> str:
        parts = [f'<svg class="px" viewBox="0 0 {self.w} {self.h}" shape-rendering="crispEdges" role="img" aria-label="{title}">']
        for y, row in enumerate(self.d):
            x = 0
            while x < self.w:
                c = row[x]
                if c == ".":
                    x += 1
                    continue
                end = x
                while end < self.w and row[end] == c:
                    end += 1
                parts.append(f'<rect class="p{c}" x="{x}" y="{y}" width="{end - x}" height="1"/>')
                x = end
        parts.append("</svg>")
        return "".join(parts)


def castle() -> Canvas:
    c = Canvas()
    c.rect(6, 5, 8, 11, "S").rect(1, 8, 4, 8, "S").rect(15, 8, 4, 8, "S")          # keep and two towers
    for x in (6, 8, 10, 12):
        c.px(x, 4, "S")                                                             # battlements
    for x in (1, 3):
        c.px(x, 7, "S")
    for x in (15, 17):
        c.px(x, 7, "S")
    c.speckle(1, 4, 18, 12, "s", 3, 4)
    c.rect(8, 12, 4, 4, "w").rect(9, 11, 2, 1, "w").px(9, 13, "W").px(10, 13, "W").px(9, 14, "W").px(10, 14, "W")   # gate
    c.px(8, 12, "d").px(11, 12, "d")
    for x, y in ((9, 7), (3, 10), (16, 10)):
        c.px(x, y, "d").px(x, y + 1, "d")                                           # arrow slits
    c.rect(10, 0, 1, 4, "w").rect(11, 0, 4, 2, "A").px(11, 2, "a").px(12, 2, "a")   # flag
    c.ground()
    return c.outline()


def knight_snail() -> Canvas:
    c = Canvas()
    c.rect(3, 2, 4, 4, "M").rect(3, 4, 4, 1, "d").px(4, 3, "m").speckle(3, 2, 4, 4, "m", 1, 4)   # helmet with a visor
    c.px(4, 1, "A").px(5, 0, "A").px(5, 1, "A")                                     # plume
    c.rect(2, 6, 6, 5, "A").rect(4, 6, 2, 5, "Y").rect(2, 8, 6, 1, "Y")             # tabard with a cross
    c.rect(3, 11, 2, 5, "m").rect(5, 11, 2, 5, "M")                                 # legs
    c.rect(0, 7, 2, 4, "B").px(0, 8, "E").px(1, 9, "E")                             # shield
    c.rect(9, 3, 1, 8, "M").px(9, 2, "E").rect(8, 11, 3, 1, "Y").px(9, 12, "w")     # sword
    c.rect(11, 13, 8, 3, "F")                                                       # snail body
    c.rect(14, 8, 5, 5, "A").rect(15, 9, 3, 3, "a").px(16, 10, "q")                 # shell
    c.px(11, 11, "F").px(11, 12, "F").px(13, 11, "F").px(13, 12, "F").px(11, 10, "K").px(13, 10, "K")   # stalks
    c.ground()
    return c.outline()


def dragon_treasure() -> Canvas:
    c = Canvas()
    c.rect(0, 7, 3, 3, "G").rect(2, 5, 5, 5, "G").px(4, 6, "R").px(5, 6, "R")        # head, snout, eye
    c.px(3, 3, "E").px(3, 4, "E").px(6, 3, "E").px(6, 4, "E")                       # horns
    c.rect(1, 9, 2, 1, "E").px(1, 8, "R")                                           # teeth, tongue
    c.rect(6, 8, 3, 6, "G").rect(6, 11, 9, 5, "G").rect(7, 12, 7, 4, "Y")           # neck, body, belly
    c.rect(9, 4, 4, 7, "g").rect(10, 5, 2, 5, "A")                                  # wing
    c.rect(15, 12, 4, 2, "G").px(18, 11, "G").px(19, 11, "G")                       # tail
    c.speckle(6, 5, 12, 9, "g", 5, 4)
    c.rect(7, 14, 2, 2, "g").rect(12, 14, 2, 2, "g")                                # feet
    c.rect(14, 13, 5, 3, "Y").px(15, 12, "Y").px(17, 12, "Y").px(16, 13, "y").px(18, 14, "y")   # gold
    c.ground()
    return c.outline()


def wizard() -> Canvas:
    c = Canvas()
    c.rect(8, 0, 2, 2, "A").rect(7, 2, 4, 2, "A").rect(6, 4, 6, 2, "A").rect(4, 6, 10, 1, "A")   # pointed hat
    c.rect(6, 5, 6, 1, "Y").px(9, 1, "Y").px(8, 3, "q").speckle(4, 0, 10, 7, "a", 2, 6)
    c.rect(6, 7, 6, 4, "F").rect(6, 9, 6, 4, "E").px(7, 8, "K").px(10, 8, "K")      # face and beard
    c.rect(5, 11, 8, 5, "b").rect(5, 11, 8, 1, "B").px(8, 13, "A").px(11, 14, "A")  # robe with stars
    c.rect(4, 13, 1, 3, "b").rect(13, 13, 1, 3, "b")
    c.rect(15, 5, 1, 11, "w").rect(14, 2, 3, 3, "q").px(15, 3, "E")                 # staff and glowing orb
    c.ground()
    return c.outline()


def princess_tower() -> Canvas:
    c = Canvas()
    c.rect(4, 6, 8, 10, "S").speckle(4, 6, 8, 10, "s", 9, 3)
    for x in (4, 6, 8, 10):
        c.px(x, 5, "S")
    for k, col in enumerate(("A", "A", "a", "A", "a")):
        c.rect(7 - k, k, 2 + 2 * k, 1, col)                                         # a cone roof, widening downwards
    c.rect(3, 5, 10, 1, "a")
    c.rect(7, 8, 2, 3, "d").px(7, 9, "F").px(8, 9, "F").px(7, 8, "Y").px(8, 8, "Y")     # princess in the window
    c.rect(6, 13, 4, 3, "w").px(7, 13, "W").px(8, 13, "W")
    c.rect(13, 12, 1, 4, "w").rect(14, 12, 3, 2, "A")                               # pennant
    c.rect(16, 11, 2, 5, "G").rect(15, 9, 4, 3, "G").rect(16, 9, 2, 1, "g")         # bush
    c.ground()
    return c.outline()


def king_queen() -> Canvas:
    c = Canvas()
    for ox, crown, robe in ((1, "Y", "R"), (11, "q", "A")):
        c.rect(ox + 1, 2, 4, 1, crown).px(ox + 1, 1, crown).px(ox + 3, 1, crown).px(ox + 4, 1, crown)   # crown
        c.rect(ox + 1, 3, 4, 4, "F").px(ox + 2, 4, "K").px(ox + 4, 4, "K")
        c.rect(ox, 7, 6, 6, robe).rect(ox, 7, 6, 1, "E").px(ox + 2, 9, "Y").px(ox + 3, 9, "Y")           # robe with ermine collar
        c.rect(ox + 1, 13, 2, 3, "d").rect(ox + 3, 13, 2, 3, "d")
    c.px(3, 6, "E").px(4, 6, "E").px(2, 6, "E")
    c.rect(8, 9, 1, 5, "Y").px(8, 8, "A")                                           # sceptre
    c.ground()
    return c.outline()


def burglar() -> Canvas:
    c = Canvas()
    c.rect(4, 1, 6, 1, "K").rect(4, 2, 6, 4, "F").rect(4, 3, 6, 2, "K").px(5, 4, "E").px(8, 4, "E")      # cap and mask
    c.rect(3, 6, 8, 6, "K").rect(3, 7, 8, 1, "E").rect(3, 9, 8, 1, "E")             # striped shirt
    c.rect(4, 12, 2, 4, "d").rect(7, 12, 2, 4, "d")
    c.rect(11, 7, 2, 3, "F").rect(13, 9, 5, 7, "W").rect(14, 8, 3, 1, "W").px(15, 7, "w")   # sack
    c.rect(14, 11, 3, 3, "Y").px(15, 12, "y").px(17, 6, "Y")
    c.ground()
    return c.outline()


def forest() -> Canvas:
    c = Canvas()
    for ox, top in ((0, 1), (7, 3), (13, 0)):
        c.rect(ox + 3, top + 7, 2, 16 - top - 7, "w").rect(ox + 3, top + 7, 1, 16 - top - 7, "W")
        c.rect(ox + 1, top, 5, 7, "G").rect(ox, top + 2, 7, 3, "G")
        c.speckle(ox, top, 7, 7, "g", ox + 3, 3)
    c.rect(10, 12, 1, 4, "w").rect(10, 10, 1, 2, "O").px(10, 9, "Y")                # a torch
    c.ground()
    return c.outline()


SCENES = {"castle": castle, "knight-snail": knight_snail, "dragon-treasure": dragon_treasure, "wizard": wizard,
          "princess-tower": princess_tower, "king-queen": king_queen, "burglar": burglar, "forest": forest}
TITLES = {"castle": "A castle built of blocks", "knight-snail": "A knight facing a snail", "dragon-treasure": "A dragon on its gold",
          "wizard": "A wizard with a glowing staff", "princess-tower": "A princess in her tower", "king-queen": "A king and a queen",
          "burglar": "A burglar with a sack of loot", "forest": "A forest with a torch"}


def skyline() -> str:
    """A strip of block scenery for the header ornament, used as a mask: 23 dots high, shown at 2 pixels a dot."""
    h = 23
    cols = []
    rng = random.Random(11)
    x = 0
    pieces = []
    for kind in ("tower", "tree", "house", "tree", "castle", "tree", "tower", "house", "tree"):
        pieces.append(kind)
    cells: set[tuple[int, int]] = set()

    def block(x0, y0, w, hh):
        for j in range(y0, y0 + hh):
            for i in range(x0, x0 + w):
                cells.add((i, j))
    for kind in pieces:
        base = h
        if kind == "tower":
            block(x, base - 14, 6, 14)
            for i in (0, 2, 4):
                block(x + i, base - 16, 1, 2)
            block(x + 2, base - 9, 2, 3)
            width = 8
        elif kind == "tree":
            block(x + 3, base - 6, 2, 6)
            block(x + 1, base - 13, 6, 8)
            block(x, base - 11, 8, 4)
            width = 10
        elif kind == "house":
            block(x, base - 8, 8, 8)
            for k in range(4):
                block(x + 3 - k, base - 12 + k, 2 + 2 * k, 1)                   # a roof that widens downwards
            block(x + 3, base - 4, 2, 4)
            width = 11
        else:
            block(x + 5, base - 18, 8, 18)
            block(x, base - 11, 5, 11)
            block(x + 13, base - 11, 5, 11)
            for i in (5, 7, 9, 11):
                block(x + i, base - 20, 1, 2)
            for i in (0, 2, 4):
                block(x + i, base - 13, 1, 2)
                block(x + 13 + i, base - 13, 1, 2)
            block(x + 8, base - 6, 2, 6)
            width = 21
        x += width
        cols.append(x)
        x += rng.randrange(2, 5)
    width = x
    rects = []
    for y in range(h):
        i = 0
        while i < width:
            if (i, y) not in cells:
                i += 1
                continue
            j = i
            while j < width and (j, y) in cells:
                j += 1
            rects.append(f'<rect x="{i}" y="{y}" width="{j - i}" height="1"/>')
            i = j
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="{width * 2}" height="{h * 2}" shape-rendering="crispEdges"><g fill="#000">{"".join(rects)}</g></svg>'


def stone(dark: bool) -> str:
    """A 16 by 16 block of rough stone as a see-through overlay: dark mortar lines and lighter bricks. It lies over the page colour,
    which is tinted with the highlight colour, so the wall follows the highlight switch."""
    rng = random.Random(21 if dark else 22)
    mortar = ('#000', .42) if dark else ('#3c2808', .24)
    light = ('#fff', (.025, .045, .065, .09)) if dark else ('#fff', (.16, .22, .28, .34))
    size = 16
    rects = [f'<rect width="{size}" height="{size}" fill="{mortar[0]}" fill-opacity="{mortar[1]}"/>']
    for row, y in enumerate((0, 8)):                                                # two courses, the second shifted by half a brick
        off = 0 if row == 0 else 8
        for bx in (-8 + off, 0 + off, 8 + off):
            x0, x1 = max(bx + 1, 0), min(bx + 8, size)
            if x1 <= x0:
                continue
            rects.append(f'<rect x="{x0}" y="{y + 1}" width="{x1 - x0}" height="7" fill="{light[0]}" fill-opacity="{rng.choice(light[1])}"/>')
            for _ in range(5):
                px, py = rng.randrange(x0, x1), y + 1 + rng.randrange(7)
                rects.append(f'<rect x="{px}" y="{py}" width="1" height="1" fill="{light[0]}" fill-opacity="{rng.choice(light[1])}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}" shape-rendering="crispEdges">{"".join(rects)}</svg>'


def main() -> None:
    out = ROOT / "src" / "drollery" / "templates" / "doodles" / "pixel"
    out.mkdir(parents=True, exist_ok=True)
    for name, build in SCENES.items():
        (out / f"{name}.svg").write_text(build().svg(TITLES[name]))
    static = ROOT / "src" / "drollery" / "static"
    (static / "pixel-skyline.svg").write_text(skyline())
    (static / "pixel-stone-dark.svg").write_text(stone(True))
    (static / "pixel-stone-light.svg").write_text(stone(False))
    print("wrote", len(SCENES), "scenes, the skyline and two stone tiles")


if __name__ == "__main__":
    main()
