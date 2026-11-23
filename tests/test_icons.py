"""The app icon: one fixed picture (it does not follow the highlight colour), named by every page and found at the habitual paths."""
import re
import struct

from drollery.main import BASE

STATIC = BASE / "static"


def test_pages_name_the_icons_and_each_file_exists(client, anon):
    for r in (client.get("/"), anon.get("/login")):
        html = r.text
        hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*href="(/static/[^"]+)"', html)
        assert {"/static/favicon.svg", "/static/apple-touch-icon.png", "/static/icon-192.png"} <= set(hrefs)
        for h in hrefs:
            assert client.get(h).status_code == 200


def test_the_svg_icon_is_a_fixed_picture_with_no_theme_variables():
    svg = (STATIC / "favicon.svg").read_text()
    assert "var(" not in svg and "currentColor" not in svg and "light-dark" not in svg
    assert 'viewBox="0 0 16 16"' in svg and "crispEdges" in svg and "#e5383b" in svg and "#2f6bff" in svg
    assert 'width="16" height="16"' not in svg and "#1b1822" not in svg.split("<rect", 1)[1].split("/>")[0]     # no background square: the icon is transparent


def test_the_icons_are_transparent_except_the_one_ios_paints_black():
    colour_type = lambda name: (STATIC / name).read_bytes()[25]                    # 6 = with a transparency channel, 2 = without
    assert colour_type("icon-192.png") == 6 and colour_type("icon-512.png") == 6
    assert colour_type("apple-touch-icon.png") == 2
    ico = (STATIC / "favicon.ico").read_bytes()
    assert ico[ico.index(b"\x89PNG") + 25] == 6                                    # the 16 pixel image inside the .ico


def test_png_sizes_are_what_their_names_say():
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        data = (STATIC / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", data[16:24]) == (size, size)


def test_favicon_ico_is_served_without_signing_in(anon):
    r = anon.get("/favicon.ico")
    assert r.status_code == 200 and r.headers["content-type"] == "image/vnd.microsoft.icon"
    assert r.content[:4] == b"\x00\x00\x01\x00" and struct.unpack("<H", r.content[4:6])[0] == 3


def test_the_header_shows_the_fixed_icon_not_a_themed_drawing(client):
    brand = re.search(r'<a class="brand".*?</a>', client.get("/").text, re.S).group(0)
    assert 'src="/static/favicon.svg"' in brand and "<svg" not in brand
