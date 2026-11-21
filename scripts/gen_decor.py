#!/usr/bin/env python3
"""Generate the wall decorations shown in the side margins of wide screens.

Writes into src/drollery/static/:
  wall-left.svg / wall-right.svg          iron work: torch with flickering flame + glow, rod, swords / chain, shield
  wall-left-still.svg / wall-right-still.svg   same without animation (prefers-reduced-motion)
  banner-mask.svg                          banner silhouette; CSS paints it in the highlight color

Each tile is 280x960 (wide enough for the torch glow to fade out inside it) and repeats vertically down the page.
Usage: python scripts/gen_decor.py
"""
from pathlib import Path

W, H = 280, 960
CX = W // 2
IRON, IRON_HI, IRON_DK = "#868694", "#a9a9b8", "#2c2c33"
WOOD = "#5b4630"

DEFS = ('<defs>'
        '<radialGradient id="glow"><stop offset="0" stop-color="#ffa646" stop-opacity=".42"/>'
        '<stop offset=".45" stop-color="#ff8a2e" stop-opacity=".14"/><stop offset="1" stop-color="#ff8a2e" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="soot" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset="1" stop-color="#000" stop-opacity="0"/></linearGradient>'
        '<linearGradient id="rust" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8a4b22" stop-opacity=".40"/><stop offset="1" stop-color="#8a4b22" stop-opacity="0"/></linearGradient>'
        '</defs>')


def torch(y, animate):
    """Wall torch whose flame base sits at (CX, y); bracket and handle hang below it."""
    a_glow = '<animate attributeName="opacity" values=".92;1;.8;1;.88" dur="2.3s" repeatCount="indefinite"/>' if animate else ""
    a_flame = ('<animateTransform attributeName="transform" type="scale" values="1 1;1.05 .93;.96 1.06;1.02 .97;1 1" '
               'dur="1.25s" repeatCount="indefinite"/>') if animate else ""
    a_op = '<animate attributeName="opacity" values="1;.86;1;.93;1" dur="1.7s" repeatCount="indefinite"/>' if animate else ""
    return f'''
  <ellipse cx="{CX}" cy="{y - 120}" rx="11" ry="64" fill="url(#soot)"/>
  <circle cx="{CX}" cy="{y - 30}" r="128" fill="url(#glow)">{a_glow}</circle>
  <rect x="{CX - 6}" y="{y}" width="12" height="74" rx="2" fill="{WOOD}" stroke="#2b2118"/>
  <rect x="{CX - 8}" y="{y + 12}" width="16" height="5" rx="1" fill="{IRON_DK}" stroke="{IRON}"/>
  <rect x="{CX - 8}" y="{y + 36}" width="16" height="5" rx="1" fill="{IRON_DK}" stroke="{IRON}"/>
  <path d="M{CX - 17} {y + 2} L{CX - 11} {y - 16} H{CX + 11} L{CX + 17} {y + 2} Z" fill="{IRON_DK}" stroke="{IRON}" stroke-width="1.5" stroke-linejoin="round"/>
  <path d="M{CX - 6} {y + 74} C{CX - 6} {y + 100} {CX - 24} {y + 96} {CX - 24} {y + 116}" fill="none" stroke="{IRON}" stroke-width="3" stroke-linecap="round"/>
  <path d="M{CX + 6} {y + 74} C{CX + 6} {y + 100} {CX + 24} {y + 96} {CX + 24} {y + 116}" fill="none" stroke="{IRON}" stroke-width="3" stroke-linecap="round"/>
  <rect x="{CX - 12}" y="{y + 104}" width="24" height="38" rx="4" fill="{IRON_DK}" stroke="{IRON}" stroke-width="1.5"/>
  <circle cx="{CX}" cy="{y + 114}" r="2" fill="{IRON_HI}"/><circle cx="{CX}" cy="{y + 132}" r="2" fill="{IRON_HI}"/>
  <g transform="translate({CX} {y - 14})"><g>{a_flame}<g>{a_op}
    <path d="M0 -62 C13 -44 19 -30 13 -16 C9 -7 4 -2 0 -2 C-4 -2 -9 -7 -13 -16 C-19 -30 -13 -44 0 -62Z" fill="#ff8a1f"/>
    <path d="M0 -44 C8 -33 11 -24 8 -15 C6 -9 3 -6 0 -6 C-3 -6 -6 -9 -8 -15 C-11 -24 -8 -33 0 -44Z" fill="#ffc94d"/>
    <path d="M0 -26 C4 -20 5 -15 3 -11 C2 -9 1 -8 0 -8 C-1 -8 -2 -9 -3 -11 C-5 -15 -4 -20 0 -26Z" fill="#fff4c2"/>
  </g></g></g>'''


def swords(y):
    def sword(sign):
        x0, x1 = CX - 30 * sign, CX + 30 * sign
        return (f'<line x1="{x0}" y1="{y - 34}" x2="{x1}" y2="{y + 34}" stroke="{IRON_HI}" stroke-width="3.5" stroke-linecap="round"/>'
                f'<line x1="{x0}" y1="{y - 34}" x2="{x1}" y2="{y + 34}" stroke="{IRON_DK}" stroke-width="1" stroke-linecap="round"/>'
                f'<line x1="{CX + 14 * sign - 8}" y1="{y + 14}" x2="{CX + 14 * sign + 8}" y2="{y + 14}" stroke="{IRON}" stroke-width="3" stroke-linecap="round" transform="rotate({-sign * 28} {CX + 14 * sign} {y + 14})"/>'
                f'<circle cx="{x1}" cy="{y + 36}" r="3.5" fill="{IRON}"/>')
    return f'<g>{sword(1)}{sword(-1)}</g>'


def rod(y):
    return (f'<rect x="{CX - 50}" y="{y}" width="100" height="6" rx="3" fill="{IRON}" stroke="{IRON_DK}"/>'
            f'<circle cx="{CX - 52}" cy="{y + 3}" r="6" fill="{IRON_HI}" stroke="{IRON_DK}"/><circle cx="{CX + 52}" cy="{y + 3}" r="6" fill="{IRON_HI}" stroke="{IRON_DK}"/>'
            f'<rect x="{CX - 40}" y="{y - 6}" width="6" height="12" rx="2" fill="{IRON_DK}" stroke="{IRON}"/><rect x="{CX + 34}" y="{y - 6}" width="6" height="12" rx="2" fill="{IRON_DK}" stroke="{IRON}"/>')


def chain(y, links=8):
    parts = [f'<rect x="{CX - 11}" y="{y - 12}" width="22" height="22" rx="4" fill="{IRON_DK}" stroke="{IRON}" stroke-width="1.5"/>',
             f'<circle cx="{CX}" cy="{y - 1}" r="3" fill="{IRON_HI}"/>',
             f'<rect x="{CX - 6}" y="{y + 10}" width="12" height="{links * 26 + 40}" fill="url(#rust)"/>']
    yy = y + 6
    for i in range(links):
        if i % 2 == 0:
            parts.append(f'<ellipse cx="{CX}" cy="{yy + 12}" rx="7" ry="12" fill="none" stroke="{IRON}" stroke-width="3.2"/>'
                         f'<path d="M{CX - 5} {yy + 6} Q{CX - 6} {yy + 12} {CX - 5} {yy + 18}" fill="none" stroke="{IRON_HI}" stroke-width="1.2" stroke-linecap="round"/>')
        else:
            parts.append(f'<rect x="{CX - 2.2}" y="{yy + 2}" width="4.4" height="20" rx="2.2" fill="{IRON}" stroke="{IRON_DK}" stroke-width=".8"/>')
        yy += 22
    parts.append(f'<path d="M{CX - 17} {yy + 4} A17 17 0 1 0 {CX + 17} {yy + 4}" fill="none" stroke="{IRON}" stroke-width="5" stroke-linecap="round" transform="translate(0 20)"/>'
                 f'<rect x="{CX - 20}" y="{yy + 20}" width="40" height="9" rx="3" fill="{IRON_DK}" stroke="{IRON}" stroke-width="1.5"/>'
                 f'<circle cx="{CX}" cy="{yy + 24.5}" r="2" fill="{IRON_HI}"/>')
    return "".join(parts)


def shield(y):
    return (f'<path d="M{CX - 26} {y} H{CX + 26} V{y + 34} C{CX + 26} {y + 58} {CX + 10} {y + 70} {CX} {y + 76} C{CX - 10} {y + 70} {CX - 26} {y + 58} {CX - 26} {y + 34} Z" '
            f'fill="{IRON_DK}" stroke="{IRON}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<path d="M{CX} {y + 6} V{y + 66} M{CX - 20} {y + 26} H{CX + 20}" stroke="{IRON_HI}" stroke-width="3" stroke-linecap="round"/>'
            f'<circle cx="{CX}" cy="{y + 26}" r="4" fill="{IRON}"/>')


def wall(side, animate):
    body = DEFS
    if side == "left":
        body += torch(330, animate) + rod(580) + swords(850)
    else:
        body += torch(330, animate) + chain(560) + shield(862)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{body}</svg>'


def banner_mask():
    """Alpha mask: banner body with a castle crest and two stripes cut out (evenodd)."""
    y0 = 586
    outline = f"M{CX - 40} {y0} H{CX + 40} V{y0 + 170} L{CX} {y0 + 138} L{CX - 40} {y0 + 170} Z"
    crest = (f"M{CX - 15} {y0 + 70} V{y0 + 38} H{CX - 10} V{y0 + 44} H{CX - 4} V{y0 + 38} H{CX + 4} V{y0 + 44} H{CX + 10} V{y0 + 38} H{CX + 15} V{y0 + 70} Z "
             f"M{CX - 4} {y0 + 70} V{y0 + 60} A4 4 0 0 1 {CX + 4} {y0 + 60} V{y0 + 70} Z")
    stripes = (f"M{CX - 40} {y0 + 12} H{CX + 40} V{y0 + 16} H{CX - 40} Z "
               f"M{CX - 40} {y0 + 86} H{CX + 40} V{y0 + 90} H{CX - 40} Z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<path fill-rule="evenodd" d="{outline} {crest} {stripes}"/></svg>')


if __name__ == "__main__":
    dest = Path(__file__).resolve().parent.parent / "src" / "drollery" / "static"
    for side in ("left", "right"):
        (dest / f"wall-{side}.svg").write_text(wall(side, True))
        (dest / f"wall-{side}-still.svg").write_text(wall(side, False))
    (dest / "banner-mask.svg").write_text(banner_mask())
    print("wrote wall-left/right(.still).svg and banner-mask.svg to", dest)
