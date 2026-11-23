#!/usr/bin/env python3
"""Draw the assets of the "Pixel" style: block-built medieval scenes, a pixel skyline and the stone tiles.

    python scripts/gen_pixel.py

Writes templates/doodles/pixel/*.svg (eight 20 by 20 scenes), static/pixel-orn/*.svg (five strips for the header and five for the footer,
each in two layers that the page uses as masks: stone, and the highlight colour) and
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
    """A dragon in profile, facing left: horned head, a burst of fire, a wing of the highlight colour, a scaly body with a pale belly,
    claws, a spade tail and a pile of gold. Every part touches the next, so the outline stays one clean line."""
    c = Canvas()
    for y, x0, x1 in ((2, 15, 16), (3, 14, 17), (4, 13, 17), (5, 12, 17), (6, 12, 16), (7, 12, 15), (8, 12, 14)):
        c.rect(x0, y, x1 - x0 + 1, 1, "A")                                          # the wing
    for x, y in ((12, 8), (13, 7), (14, 6), (15, 5), (16, 4), (16, 3)):
        c.px(x, y, "a")                                                             # its bones
    c.rect(7, 9, 10, 6, "G")                                                        # body
    c.rect(8, 12, 8, 3, "Y")                                                        # pale belly
    c.rect(7, 7, 3, 3, "G")                                                         # neck
    c.rect(3, 3, 6, 4, "G").rect(1, 5, 3, 2, "G").rect(2, 7, 5, 1, "g")             # head, snout, lower jaw
    c.px(6, 4, "E").px(5, 4, "R").px(2, 5, "g")                                     # eye and nostril
    c.px(4, 1, "E").px(4, 2, "E").px(7, 1, "E").px(7, 2, "E")                       # horns
    c.px(2, 7, "E").px(5, 8, "E")                                                   # fangs
    for x, y in ((0, 8), (0, 9), (1, 9), (2, 9), (1, 10), (0, 10)):
        c.px(x, y, "O")
    c.px(1, 8, "Y").px(1, 9, "Y")                                                   # fire
    c.rect(17, 11, 3, 3, "G").rect(18, 8, 2, 3, "G").px(18, 7, "a").px(19, 7, "a").px(19, 6, "a")   # tail and its spade
    c.rect(8, 15, 3, 1, "g").rect(13, 15, 3, 1, "g").px(7, 15, "E").px(12, 15, "E")  # feet and claws
    c.speckle(7, 9, 10, 3, "g", 6, 3)
    c.rect(1, 13, 5, 3, "Y").px(2, 12, "Y").px(4, 12, "Y").px(3, 14, "y").px(5, 15, "y")   # a pile of gold
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


class Strip:
    """A border strip in two layers: neutral stone and the highlight colour. Dots are cells; y counts from the top."""

    def __init__(self, h: int):
        self.h = h
        self.layer: dict[str, set[tuple[int, int]]] = {"S": set(), "A": set()}

    def block(self, layer: str, x: int, up: int, w: int, hh: int) -> None:
        """A block whose bottom edge is `up` dots above the base line."""
        for j in range(self.h - up - hh, self.h - up):
            for i in range(x, x + w):
                self.layer[layer].add((i, j))

    def cut(self, x: int, up: int, w: int, hh: int) -> None:
        for j in range(self.h - up - hh, self.h - up):
            for i in range(x, x + w):
                for cells in self.layer.values():
                    cells.discard((i, j))

    def width(self) -> int:
        return max((i for cells in self.layer.values() for i, _ in cells), default=0) + 1

    def svg(self, layer: str, width: int) -> str:
        rects = []
        for y in range(self.h):
            x = 0
            while x < width:
                if (x, y) not in self.layer[layer]:
                    x += 1
                    continue
                e = x
                while e < width and (e, y) in self.layer[layer]:
                    e += 1
                rects.append(f'<rect x="{x}" y="{y}" width="{e - x}" height="1"/>')
                x = e
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {self.h}" width="{width * 2}" height="{self.h * 2}" '
                f'shape-rendering="crispEdges"><g fill="#000">{"".join(rects)}</g></svg>')


# ---- things that stand on the base line; each draws itself at x and returns how wide it is
def tower(s, x, hh=14):
    s.block("S", x, 0, 6, hh)
    for i in (0, 2, 4):
        s.block("S", x + i, hh, 1, 2)
    s.cut(x + 2, hh - 6, 2, 3)
    s.block("S", x + 3, hh + 2, 1, 4)
    s.block("A", x + 4, hh + 4, 3, 2)
    return 8


def house(s, x):
    s.block("S", x, 0, 8, 7)
    for k in range(4):
        s.block("A", x + 3 - k, 7 + k, 2 + 2 * k, 1)                                # a roof that widens downwards
    s.cut(x + 3, 0, 2, 4)
    s.cut(x + 1, 4, 1, 2)
    return 11


def tree(s, x):
    s.block("S", x + 3, 0, 2, 6)
    s.block("S", x + 1, 5, 6, 8)
    s.block("S", x, 7, 8, 4)
    return 10


def pine(s, x, hh=15):
    s.block("S", x + 4, 0, 2, 3)
    for k in range(hh - 3):
        half = min(1 + k // 2, 5)
        s.block("S", x + 5 - half, 3 + (hh - 4 - k), half * 2, 1)
    return 12


def keep(s, x):
    s.block("S", x + 5, 0, 8, 18)
    s.block("S", x, 0, 5, 11)
    s.block("S", x + 13, 0, 5, 11)
    for i in (5, 7, 9, 11):
        s.block("S", x + i, 18, 1, 2)
    for i in (0, 2, 4):
        s.block("S", x + i, 11, 1, 2)
        s.block("S", x + 13 + i, 11, 1, 2)
    s.cut(x + 8, 0, 2, 6)
    s.cut(x + 8, 12, 2, 3)
    s.block("S", x + 9, 20, 1, 3)
    s.block("A", x + 10, 21, 4, 2)
    return 21


def rampart(s, x, length=36):
    s.block("S", x, 0, length, 8)
    for i in range(0, length, 3):
        s.block("S", x + i, 8, 2, 2)
    for i in range(6, length - 4, 10):
        s.block("A", x + i, 1, 3, 6)                                                # a banner hanging on the wall
        s.cut(x + i + 1, 1, 1, 1)
        s.block("S", x + i, 7, 3, 1)
    s.cut(x + length // 2 - 2, 0, 4, 5)
    return length + 3


def mountain(s, x, w=22, hh=16):
    for k in range(hh):
        half = (w * (k + 1)) // (2 * hh)
        s.block("S", x + w // 2 - half, hh - 1 - k, max(half * 2, 1), 1)
    s.cut(x + w // 2 - 2, hh - 6, 4, 1)
    return w + 2


def dragon_flying(s, x, up):
    art = ["....A.........",
           "...AA......A..",
           "..AAA.....AA..",
           ".AAAAA...AAA..",
           "AAAAAAAAAAAAAA",
           ".AA.AAAAAAA.A.",
           "........AA..AA"]
    for j, row in enumerate(art):
        for i, ch in enumerate(row):
            if ch == "A":
                s.block("A", x + i, up + len(art) - 1 - j, 1, 1)
    return 16


def tent(s, x):
    for k in range(9):
        w = max(2, min(k, 5) * 2)
        s.block("A", x + 6 - w // 2, 8 - k, w, 1)                                    # a tent that widens downwards
    s.block("A", x, 0, 12, 1)
    s.cut(x + 4, 0, 4, 5)
    s.block("S", x + 5, 9, 2, 3)
    return 14


def campfire(s, x):
    s.block("S", x, 0, 8, 2)
    s.block("A", x + 2, 2, 4, 2)
    s.block("A", x + 3, 4, 2, 3)
    s.block("A", x + 4, 7, 1, 2)
    return 10


def windmill(s, x):
    s.block("S", x + 2, 0, 8, 3)
    for k in range(12):
        s.block("S", x + 3 + k // 6, 3 + k, 6 - 2 * (k // 6), 1)
    for k in range(-5, 6):
        s.block("A", x + 6 + k, 14 + k, 1, 1)
        s.block("A", x + 6 - k, 14 + k, 1, 1)                                       # the sails
    s.cut(x + 5, 0, 2, 4)
    return 13


def haystack(s, x):
    for k in range(6):
        s.block("A", x + k // 2, k, 10 - k, 1)
    return 12


def moon(s, x, up):
    for j in range(7):
        for i in range(7):
            if (i - 3) ** 2 + (j - 3) ** 2 <= 10 and (i - 5) ** 2 + (j - 2) ** 2 > 9:
                s.block("S", x + i, up + j, 1, 1)
    return 8


def flower(s, x, hh=6):
    s.block("S", x + 1, 0, 1, hh)
    s.block("A", x, hh, 3, 1)
    s.block("A", x + 1, hh - 1, 1, 3)
    s.cut(x + 1, hh, 1, 1)
    return 5


def mushroom(s, x):
    s.block("S", x + 1, 0, 2, 3)
    s.block("A", x, 3, 4, 2)
    s.cut(x + 1, 4, 1, 1)
    return 6


def sheep(s, x):
    s.block("S", x + 1, 2, 6, 4)
    s.block("S", x + 7, 4, 3, 3)
    s.block("S", x + 2, 0, 1, 2)
    s.block("S", x + 5, 0, 1, 2)
    s.cut(x + 8, 5, 1, 1)
    s.block("A", x + 9, 3, 1, 1)
    return 12


def chest(s, x):
    s.block("S", x, 0, 8, 5)
    s.block("A", x, 5, 8, 1)
    s.block("A", x + 3, 1, 2, 3)
    return 10


def barrel(s, x):
    s.block("S", x, 0, 5, 6)
    s.block("A", x, 1, 5, 1)
    s.block("A", x, 4, 5, 1)
    return 7


def torch(s, x, hh=9):
    s.block("S", x + 1, 0, 1, hh)
    s.block("A", x, hh, 3, 2)
    s.block("A", x + 1, hh + 2, 1, 2)
    return 5


def knight(s, x):
    s.block("S", x, 0, 1, 4)
    s.block("S", x + 2, 0, 1, 4)
    s.block("S", x - 1, 4, 5, 5)
    s.block("S", x, 9, 3, 3)
    s.cut(x + 1, 10, 2, 1)
    s.block("A", x + 1, 12, 1, 1)
    s.block("S", x + 5, 0, 1, 17)
    s.block("A", x + 6, 14, 4, 3)
    return 12


def signpost(s, x):
    s.block("S", x + 3, 0, 1, 9)
    s.block("A", x, 6, 8, 3)
    s.cut(x + 2, 7, 4, 1)
    return 10


def lantern(s, x):
    s.block("S", x + 2, 0, 1, 11)
    s.block("S", x, 11, 5, 1)
    s.block("A", x + 1, 8, 3, 3)
    s.cut(x + 2, 9, 1, 1)
    return 7


def bush(s, x):
    s.block("S", x + 1, 0, 6, 3)
    s.block("S", x, 1, 8, 2)
    s.block("S", x + 2, 3, 4, 1)
    return 10


def reed(s, x, hh=9):
    s.block("S", x, 0, 1, hh)
    s.block("A", x, hh, 1, 3)
    s.block("S", x + 2, 0, 1, hh - 3)
    return 4


def duck(s, x):
    s.block("A", x, 0, 6, 3)
    s.block("A", x + 4, 3, 3, 3)
    s.block("A", x + 7, 4, 2, 1)
    s.cut(x + 5, 4, 1, 1)
    return 11


def lilypad(s, x):
    s.block("S", x, 0, 4, 1)
    s.block("A", x + 1, 1, 1, 1)
    return 7


def fence(s, x, n=4):
    for i in range(n):
        s.block("S", x + i * 4, 0, 1, 6)
    s.block("S", x, 4, n * 4 - 3, 1)
    s.block("S", x, 1, n * 4 - 3, 1)
    return n * 4 + 1


def sword_stone(s, x):
    s.block("S", x, 0, 8, 4)
    s.block("S", x + 1, 4, 6, 1)
    s.block("A", x + 3, 5, 2, 8)
    s.block("A", x + 1, 8, 6, 1)
    return 10


def grass(s, x):
    s.block("S", x, 0, 1, 2)
    s.block("S", x + 2, 0, 1, 3)
    s.block("S", x + 4, 0, 1, 2)
    return 6


TOP_H, FOOT_H = 23, 22
TOP = {
    "town": [(tower, {}), (tree, {}), (house, {}), (tree, {}), (keep, {}), (tree, {}), (tower, {}), (house, {}), (pine, {"hh": 14}), (house, {}), (tree, {})],
    "ramparts": [(rampart, {"length": 40}), (tower, {"hh": 15}), (rampart, {"length": 28}), (keep, {}), (rampart, {"length": 30}), (tower, {"hh": 12}), (rampart, {"length": 34})],
    "mountains": [(mountain, {"w": 26, "hh": 17}), (pine, {"hh": 9}), (mountain, {"w": 30, "hh": 21}), (pine, {"hh": 11}), (pine, {"hh": 8}), (mountain, {"w": 22, "hh": 14}), (tower, {"hh": 8}), (mountain, {"w": 28, "hh": 19}), (pine, {"hh": 10})],
    "camp": [(pine, {"hh": 17}), (pine, {"hh": 13}), (tent, {}), (campfire, {}), (tent, {}), (pine, {"hh": 16}), (pine, {"hh": 12}), (pine, {"hh": 18}), (tent, {}), (campfire, {}), (pine, {"hh": 14})],
    "windmills": [(windmill, {}), (haystack, {}), (house, {}), (tree, {}), (windmill, {}), (house, {}), (haystack, {}), (tree, {}), (house, {}), (windmill, {})],
}
FOOT = {
    "meadow": [(flower, {"hh": 5}), (grass, {}), (mushroom, {}), (flower, {"hh": 7}), (sheep, {}), (grass, {}), (flower, {"hh": 4}), (mushroom, {}), (bush, {}), (flower, {"hh": 6}), (grass, {}), (sheep, {})],
    "treasury": [(chest, {}), (barrel, {}), (torch, {}), (barrel, {}), (chest, {}), (sword_stone, {}), (torch, {"hh": 7}), (barrel, {}), (chest, {})],
    "march": [(knight, {}), (knight, {}), (knight, {}), (signpost, {}), (knight, {}), (knight, {}), (lantern, {}), (knight, {})],
    "village": [(lantern, {}), (fence, {"n": 5}), (signpost, {}), (bush, {}), (lantern, {}), (fence, {"n": 4}), (barrel, {}), (bush, {}), (signpost, {}), (fence, {"n": 5})],
    "pond": [(reed, {"hh": 10}), (reed, {"hh": 8}), (duck, {}), (lilypad, {}), (reed, {"hh": 11}), (duck, {}), (lilypad, {}), (lilypad, {}), (reed, {"hh": 9}), (reed, {"hh": 12}), (duck, {})],
}


def build_strip(pieces, h: int, target: int, seed: int) -> Strip:
    """Place the things left to right with small gaps, and repeat the row until it is about `target` dots wide."""
    rng = random.Random(seed)
    s = Strip(h)
    x = 2
    while x < target:
        for fn, kw in pieces:
            x += fn(s, x, **kw) + rng.randrange(1, 4)
    return s


def strips() -> dict[str, str]:
    """name -> svg text: pixel-orn/<place>-<name>-s.svg (stone) and -a.svg (highlight colour)."""
    out: dict[str, str] = {}
    for place, table, h, target in (("top", TOP, TOP_H, 300), ("foot", FOOT, FOOT_H, 230)):
        for n, (name, pieces) in enumerate(table.items(), 1):
            st = build_strip(pieces, h, target, 40 + n + (0 if place == "top" else 20))
            width = st.width() + 3
            if name == "mountains":
                for k, up in ((0, 15), (1, 16)):
                    dragon_flying(st, 36 + k * 130, up)
                width = st.width() + 3
            for layer in ("S", "A"):
                out[f"{place}-{n}-{layer.lower()}.svg"] = st.svg(layer, width)
    return out


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
    orn = static / "pixel-orn"
    orn.mkdir(exist_ok=True)
    for old in orn.glob("*.svg"):
        old.unlink()
    for name, text in strips().items():
        (orn / name).write_text(text)
    (static / "pixel-stone-dark.svg").write_text(stone(True))
    (static / "pixel-stone-light.svg").write_text(stone(False))
    print("wrote", len(SCENES), "scenes,", len(strips()) // 2, "border strips and two stone tiles")


if __name__ == "__main__":
    main()
