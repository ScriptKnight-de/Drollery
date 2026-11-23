"""The look of the pages: a style switch (Playful, Plain, Pixel) next to mode and highlight, and the assets of the Pixel style."""
import importlib.util
import re

from drollery.main import BASE

STATIC = BASE / "static"
DOODLES = BASE / "templates" / "doodles"
SCENES = ("castle", "knight-snail", "dragon-treasure", "wizard", "princess-tower", "king-queen", "burglar", "forest")


def test_the_appearance_menu_offers_the_three_styles(client):
    html = client.get("/").text
    assert re.findall(r'data-style-set="(\w+)"', html) == ["doodle", "plain", "pixel"]
    assert "data-theme-set" in html and "data-accent-set" in html                 # mode and highlight are still there
    for name in ("style-plain.css", "style-pixel.css"):
        assert f'href="/static/{name}?v=' in html and client.get(f"/static/{name}").status_code == 200


def test_the_saved_style_is_applied_before_the_first_paint(client):
    head = client.get("/").text.split("</head>")[0]
    assert 'localStorage.getItem("drollery.style")' in head
    assert 'r.dataset.style = st' in head and '"plain" || st === "pixel"' in head   # only known values reach the attribute


def test_the_buttons_remember_the_choice(client):
    html = client.get("/").text
    assert 'root.dataset.style = sy.dataset.styleSet; save("drollery.style", sy.dataset.styleSet)' in html      # Plain and Pixel are remembered
    assert 'delete root.dataset.style; save("drollery.style", "doodle")' in html                              # the playful style is "no attribute"


def test_the_style_names_are_translated(client):
    from drollery.locales.de import MESSAGES
    for word in ("Style", "Playful", "Plain", "Pixel"):
        assert word in MESSAGES


def test_each_style_rule_is_scoped_to_its_own_style():
    for name, style in (("style-playful.css", None), ("style-plain.css", "plain"), ("style-pixel.css", "pixel")):
        css = (STATIC / name).read_text()
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        css = re.sub(r"@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)          # the steps of an animation are not selectors
        for selector in re.findall(r"(?:^|\})\s*([^{}@]+?)\s*\{", css):
            flat = re.sub(r":(?:is|where)\([^)]*\)", ":is()", selector)                    # commas inside :is() do not separate selectors
            for part in flat.split(","):
                part = part.strip()
                scope = ":root:not([data-style])" if style is None else f'[data-style="{style}"]'
                assert (scope in part) or part in (":root svg.px", ".pK", ".pS", ".ps", ".pd", ".pW", ".pw", ".pG", ".pg", ".pF", ".pY",
                                                                       ".py", ".pR", ".pB", ".pb", ".pE", ".pM", ".pm", ".pO", ".pA", ".pa", ".pq"), (name, part)


def test_plain_has_no_wall_and_no_doodles():
    css = (STATIC / "style-plain.css").read_text()
    assert 'body { background-image: none; }' in css and ".doodle" in css and ".orn" in css


def test_every_scene_exists_and_is_shown_next_to_its_line_doodle(client, anon):
    for name in SCENES:
        assert (DOODLES / f"{name}.svg").is_file() and (DOODLES / "pixel" / f"{name}.svg").is_file()
    assert 'class="px"' in anon.get("/login").text and "<svg" in anon.get("/login").text.split('class="doodle"')[1].split("</div>")[0]
    assert 'class="px"' in client.get("/nope", headers={"accept": "text/html"}).text


def test_scene_colours_are_classes_that_the_pixel_style_defines_and_the_highlight_ones_follow_it():
    css = (STATIC / "style-pixel.css").read_text()
    used = set()
    for name in SCENES:
        svg = (DOODLES / "pixel" / f"{name}.svg").read_text()
        assert "<script" not in svg and "style=" not in svg and "fill=" not in svg
        used |= set(re.findall(r'<rect class="p(\w)"', svg))
    for letter in used:
        assert re.search(rf"\.p{letter}\s*\{{ fill:", css), letter
    assert re.search(r"\.pA \{ fill: var\(--ac\)", css) and "var(--ac)" in re.search(r"\.pa \{[^}]*\}", css).group(0) and "var(--ac)" in re.search(r"\.pq \{[^}]*\}", css).group(0)
    assert "A" in used                                                            # at least one dot of a scene follows the highlight


def test_the_pixel_style_names_only_files_that_exist():
    css = (STATIC / "style-pixel.css").read_text()
    for path in re.findall(r'url\("/static/([^"]+)"\)', css):
        assert (STATIC / path).is_file(), path
    assert (STATIC / "PixelifySans-OFL.txt").read_text().startswith("Copyright")        # the font comes with its licence


def test_the_assets_are_what_the_generator_draws():
    spec = importlib.util.spec_from_file_location("gen_pixel", BASE.parent.parent / "scripts" / "gen_pixel.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    for name, build in gen.SCENES.items():
        assert (DOODLES / "pixel" / f"{name}.svg").read_text() == build().svg(gen.TITLES[name]), name
    made = gen.strips()
    assert len(made) == 20                                                       # five strips for the header, five for the footer, two layers each
    for name, text in made.items():
        assert (STATIC / "pixel-orn" / name).read_text() == text, name
    assert sorted(p.name for p in (STATIC / "pixel-orn").glob("*.svg")) == sorted(made)
    assert (STATIC / "pixel-stone-dark.svg").read_text() == gen.stone(True) and (STATIC / "pixel-stone-light.svg").read_text() == gen.stone(False)


def test_the_pixel_scenes_ship_in_the_package():
    import tomllib
    meta = tomllib.loads((BASE.parent.parent / "pyproject.toml").read_text())
    assert "templates/doodles/pixel/*" in meta["tool"]["setuptools"]["package-data"]["drollery"]


def test_each_page_picks_ornaments_and_the_style_has_a_rule_for_each():
    css = (STATIC / "style-pixel.css").read_text()
    for place in ("top", "foot"):
        for n in range(1, 6):
            assert f'.{place} .orn[data-v="{n}"]' in css and f"pixel-orn/{place}-{n}-s.svg" in css and f"pixel-orn/{place}-{n}-a.svg" in css


def test_the_header_and_footer_ornaments_vary(client):
    client.post("/settings/impressum", data={"text": "An invented notice", "enabled": "1"})     # the footer only exists with an Impressum
    seen_top, seen_foot = set(), set()
    for _ in range(40):
        html = client.get("/").text
        seen_top.add(re.search(r'<header class="top">.*?<div class="orn" data-v="(\d)"', html, re.S).group(1))
        foot = re.findall(r'<div class="orn" data-v="(\d)"', html.split('<footer')[1])
        assert len(foot) == 2 and foot[0] != foot[1]                              # the two footer strips differ
        seen_foot |= set(foot)
    assert len(seen_top) >= 3 and len(seen_foot) >= 3 and seen_top | seen_foot <= set("12345")


def test_the_playful_style_has_its_own_assets_and_follows_the_highlight_colour():
    css = (STATIC / "style-playful.css").read_text()
    for path in re.findall(r'url\("/static/([^"]+)"\)', css):
        assert (STATIC / path).is_file(), path
    assert (STATIC / "Almendra-OFL.txt").read_text().startswith("Copyright")
    bunting = re.search(r"\.top::after[^{]*\{[^}]*\}", css).group(0)
    assert "var(--ac)" in bunting and "var(--pl-b2)" in bunting                       # the bunting is made of the highlight colour and its relatives
    assert "--pl-tape: color-mix(in srgb, var(--ac)" in css and "--pl-shadow: color-mix(in srgb, var(--ac)" in css
    assert "prefers-reduced-motion" in css and "animation: none" in css               # the wobbling stops for people who ask for calm


def test_the_playful_look_reaches_the_pages(client):
    html = client.get("/").text
    assert 'href="/static/style-playful.css?v=' in html and client.get("/static/style-playful.css").status_code == 200
    assert html.index("style-playful.css") < html.index("style-plain.css") < html.index("style-pixel.css")


def test_no_style_uses_a_fixed_background_which_makes_every_scroll_step_repaint_the_wall():
    for name in ("style.css", "style-playful.css", "style-plain.css", "style-pixel.css"):
        css = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(), flags=re.S)
        assert not re.search(r"background-attachment:[^;}]*fixed", css), name
    base = (STATIC / "style.css").read_text()
    assert re.search(r"body::before \{[^}]*position: fixed[^}]*var\(--tex-vig\)", base)           # the dark edges are a layer of their own
    for name, style in (("style-plain.css", "plain"), ("style-pixel.css", "pixel")):
        assert f':root[data-style="{style}"] body::before {{ display: none; }}' in (STATIC / name).read_text()      # they have their own wall


def test_a_card_does_not_start_its_entrance_animation_again_when_the_pointer_leaves_it():
    css = (STATIC / "style-playful.css").read_text()
    hover = re.search(r"\.tile:hover \{[^}]*\}", css).group(0)
    assert "animation" not in hover            # `animation: none` on :hover restarted the fade-in on every mouse-out, so the card vanished
    assert re.search(r"\.tile \{[^}]*animation: pl-pop-in[^}]*backwards", css, re.S)


def test_every_script_and_stylesheet_link_carries_the_version_so_an_update_cannot_meet_an_old_cached_file(client, anon):
    from drollery import __version__
    for html in (client.get("/").text, anon.get("/login").text, client.get("/settings").text):
        links = re.findall(r'(?:src|href)="(/static/[\w.-]+\.(?:js|css))([^"]*)"', html)
        assert links and all(q == f"?v={__version__}" for _, q in links), links
