"""Draw the app icon (a pixelated jester) and write every size of it.

    python scripts/make_icons.py                   # into src/drollery/static
    python scripts/make_icons.py --also <folder>   # the same sizes (icon.svg, icon-16/32/48/128.png) for another project

The jester is a 16 by 16 picture on a transparent background. Every file draws it at a whole-number scale (1x for 16 pixels,
2x for 32 ...), so the pixels stay sharp. The colours are fixed: they do not follow the highlight colour or the theme. Only the
iPhone/iPad home-screen icon gets an ink background, because iOS paints transparent icons black. Needs rsvg-convert.
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

INK = "#1b1822"
PALETTE = {"R": "#e5383b", "B": "#2f6bff", "Y": "#ffb800", "G": "#1fd65f", "V": "#9b3dff", "S": "#ffd3a8", "P": "#ff5fa8", "K": INK}
JESTER = [
    ".YY..........YY.",
    ".RR..........BB.",
    ".RRR........BBB.",
    ".RRRR......BBBB.",
    ".RRRRRR..BBBBBB.",
    ".RRYRRRRBBBBYBB.",
    "YYYYYYYYYYYYYYYY",
    ".SSSSSSSSSSSSSS.",
    ".SSSKSSSSSSKSSS.",
    ".SPSKSSSSSSKSPS.",
    ".SSSSSSSSSSSSSS.",
    ".SSSKSSSSSSKSSS.",
    ".SSSSKKKKKKSSSS.",
    "..SSSSSSSSSSSS..",
    "GVGVGVGVGVGVGVGV",
    ".GVGVGVGVGVGVGV.",
]
assert len(JESTER) == 16 and all(len(r) == 16 for r in JESTER)


def svg(size: int, scale: int, background: bool = False) -> str:
    """The jester at `scale` pixels per dot, centred in a square of `size` (transparent unless `background`)."""
    off = (size - 16 * scale) // 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">']
    if background:
        out.append(f'<rect width="{size}" height="{size}" fill="{INK}"/>')
    for y, row in enumerate(JESTER):
        x = 0
        while x < 16:
            c = row[x]
            if c == ".":
                x += 1
                continue
            end = x
            while end < 16 and row[end] == c:
                end += 1
            out.append(f'<rect x="{off + x * scale}" y="{off + y * scale}" width="{(end - x) * scale}" height="{scale}" fill="{PALETTE[c]}"/>')
            x = end
    return "".join(out) + "</svg>"


def png(path: Path, size: int, scale: int, background: bool = False) -> bytes:
    source = path.with_suffix(".tmp.svg")
    source.write_text(svg(size, scale, background))
    try:
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(source), "-o", str(path)], check=True)
    finally:
        source.unlink(missing_ok=True)
    return path.read_bytes()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--also", help="another folder that gets icon.svg and icon-16/32/48/128.png")
    args = ap.parse_args()
    static = Path(__file__).resolve().parent.parent / "src" / "drollery" / "static"
    (static / "favicon.svg").write_text(svg(16, 1))              # a vector of 16 dots: any size is a whole multiple
    sizes = {"apple-touch-icon.png": (180, 10, True), "icon-192.png": (192, 10, False), "icon-512.png": (512, 28, False)}
    for name, (size, scale, background) in sizes.items():
        png(static / name, size, scale, background)
    small = {n: png(static / f"_{n}.png", n, n // 16) for n in (16, 32, 48)}
    for n in small:
        (static / f"_{n}.png").unlink()
    entries, data, offset = b"", b"", 6 + 16 * len(small)
    for n, blob in small.items():
        entries += struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    (static / "favicon.ico").write_bytes(struct.pack("<HHH", 0, 1, len(small)) + entries + data)
    if args.also:
        other = Path(args.also)
        other.mkdir(parents=True, exist_ok=True)
        (other / "icon.svg").write_text(svg(16, 1))
        for n, scale in ((16, 1), (32, 2), (48, 3), (128, 7)):
            png(other / f"icon-{n}.png", n, scale)


if __name__ == "__main__":
    sys.exit(main())
