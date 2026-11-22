from conftest import create_user
import importlib.util
import re
from pathlib import Path

import pytest

from drollery import accounts, db, i18n
from test_share import link_token, make_item

DE = {"accept-language": "de-DE,de;q=0.9,en;q=0.8"}


def _scan():
    spec = importlib.util.spec_from_file_location("i18n_scan", Path(__file__).parent.parent / "scripts" / "i18n_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ the catalogs

@pytest.mark.parametrize("code", i18n.LOCALES)
def test_catalog_has_every_string_used_in_the_code(code):
    scan, cat = _scan(), i18n.catalog(code)
    found = scan.collect()
    missing = sorted(k for k in found if k not in cat)
    assert not missing, f"{code} lacks {len(missing)} string(s), e.g. {missing[:3]}  (run scripts/i18n_scan.py)"


@pytest.mark.parametrize("code", i18n.LOCALES)
def test_translations_keep_their_placeholders_and_plurals(code):
    scan, cat = _scan(), i18n.catalog(code)
    for key, entry in scan.collect().items():
        want = scan.placeholders(key)
        if isinstance(entry["plural"], str):                  # a plural pair in the code needs a pair in the catalog
            assert isinstance(cat[key], tuple) and len(cat[key]) == i18n.forms(code), f"{key!r}: expected {i18n.forms(code)} plural forms"
            for form in cat[key]:
                assert scan.placeholders(form) == scan.placeholders(entry["plural"]), f"{key!r}: placeholders differ in {form!r}"
        else:
            assert isinstance(cat[key], str), f"{key!r}: a plural pair is only for tn()"
            assert scan.placeholders(cat[key]) == want, f"{key!r}: placeholders differ in {cat[key]!r}"


@pytest.mark.parametrize("code", i18n.LOCALES)
def test_catalog_entries_are_not_left_untranslated_by_accident(code):
    same = [k for k, v in i18n.catalog(code).items() if isinstance(v, str) and v == k and len(k) > 24]
    assert not same, f"long strings that are identical to English: {same[:3]}"


# ------------------------------------------------------------ the helpers

def test_t_falls_back_to_english_and_formats():
    token = i18n.set_language("de")
    try:
        assert i18n.t("Sign in") == "Anmelden"
        assert i18n.t("A string nobody translated") == "A string nobody translated"
        assert i18n.t("Use at least {n} characters", n=10) == "Verwende mindestens 10 Zeichen"
        assert i18n.tn("{n} day", "{n} days", 1) == "1 Tag" and i18n.tn("{n} day", "{n} days", 3) == "3 Tage"
    finally:
        i18n._current.reset(token)
    assert i18n.t("Sign in") == "Sign in" and i18n.tn("{n} day", "{n} days", 2) == "2 days"


def test_accept_language_picks_the_best_supported_language():
    pick = i18n.from_accept_language
    assert pick("de-AT,de;q=0.9,en;q=0.8") == "de" and pick("ja, en;q=0.5") == "en" and pick("ja, de;q=0.4") == "de" and pick("fr-CA, de;q=0.4") == "de" and pick("fr, es;q=0.8") == "en"
    assert pick("") == "en" and pick("xx") == "en" and pick("de;q=0") == "en" and pick("de;q=abc") == "en"
    assert i18n.normalize("DE_ch") == "de" and i18n.normalize("klingon") == "" and i18n.normalize("en-GB") == "en"
    assert list(i18n.languages())[0] == "en" and i18n.languages()["de"] == "Deutsch"


# ------------------------------------------------------------ pages

def test_anonymous_pages_follow_the_browser_language(anon):
    create_user("boss", "a-long-enough-pass")
    assert "Halt! Who goes there?" in anon.get("/login").text and 'lang="en"' in anon.get("/login").text
    page = anon.get("/login", headers=DE)
    assert "Halt! Wer da?" in page.text and "Benutzername" in page.text and 'lang="de"' in page.text
    wrong = anon.post("/login", data={"username": "boss", "password": "nope-nope-nope"}, headers=DE)
    assert wrong.status_code == 401 and "Benutzername oder Passwort falsch" in wrong.text


def test_the_language_cookie_beats_the_browser_header(anon):
    create_user("boss", "a-long-enough-pass")
    anon.cookies.set(i18n.COOKIE, "en")
    assert "Halt! Who goes there?" in anon.get("/login", headers=DE).text
    anon.cookies.set(i18n.COOKIE, "de")
    assert "Halt! Wer da?" in anon.get("/login").text
    anon.cookies.set(i18n.COOKIE, "klingon")                  # nonsense falls back to the header
    assert "Halt! Wer da?" in anon.get("/login", headers=DE).text


def test_setup_page_and_its_errors_are_translated(anon):
    page = anon.get("/setup", headers=DE)
    assert "Willkommen bei Drollery" in page.text and "Einrichtungscode" in page.text
    bad = anon.post("/setup", data={"code": "wrong", "username": "boss", "password": "a-long-enough-pass", "password2": "a-long-enough-pass"}, headers=DE)
    assert bad.status_code == 422 and "Einrichtungscode ist nicht richtig" in bad.text


def test_choosing_a_language_in_settings(client):
    page = client.get("/settings/profile")
    assert "Automatic (follow the browser)" in page.text and '<option value="de" >Deutsch' in page.text
    r = client.post("/settings/profile", data={"email": "", "language": "de"}, follow_redirects=False)
    assert r.status_code == 303 and f"{i18n.COOKIE}=de" in r.headers["set-cookie"]
    assert accounts.get_user_by_name("admin")["language"] == "de"
    after = client.get("/settings/profile")
    assert "Profil gespeichert" in after.text and "Sprache" in after.text and '<option value="de" selected>Deutsch' in after.text
    assert 'lang="de"' in after.text and "Einstellungen" in after.text
    # the saved choice outranks the browser header, and "automatic" hands control back to the browser
    assert "Profil" in client.get("/settings/profile", headers={"accept-language": "en"}).text
    client.post("/settings/profile", data={"email": "", "language": ""})
    assert accounts.get_user_by_name("admin")["language"] == "" and "Language" in client.get("/settings/profile").text
    bad = client.post("/settings/profile", data={"email": "x", "language": "de"})
    assert bad.status_code == 422 and "E-Mail-Adresse sieht nicht richtig aus" in bad.text


def test_a_language_not_on_offer_is_ignored(client):
    client.post("/settings/profile", data={"email": "", "language": "tlh"})
    assert accounts.get_user_by_name("admin")["language"] == ""


def test_signing_in_brings_the_accounts_language_to_a_new_browser(client, anon):
    client.post("/settings/profile", data={"email": "", "language": "de"})
    r = anon.post("/login", data={"username": "admin", "password": "correct horse battery"})
    assert r.status_code == 303 and f"{i18n.COOKIE}=de" in "; ".join(r.headers.get_list("set-cookie"))


def test_every_page_renders_in_german_without_stray_placeholders(client):
    client.post("/settings/profile", data={"email": "", "language": "de"})
    item = make_item(client)
    token = link_token(client, item)
    pages = ["/", f"/items/{item}", f"/items/{item}/card", "/jobs", "/settings/profile", "/settings/security", "/settings/keys",
             "/settings/ai", "/settings/ai/models/new", "/settings/shares", "/settings/impressum"]
    for url in pages:
        r = client.get(url)
        assert r.status_code == 200, url
        assert 'lang="de"' in r.text, url
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<pre.*?</pre>|<code.*?</code>|data-[\w-]+=\"[^\"]*\"", "", r.text, flags=re.S)
        assert not re.search(r"\{(n|name|base|url|id|tag|title|when|path|file|link|target|browse|t)\}", text), f"raw placeholder on {url}"
    shared = client.get(f"/s/{token}")
    assert shared.status_code == 200 and "Herunterladen" in shared.text and "Geteilt mit Drollery" in shared.text


def test_share_state_and_durations_are_translated(client):
    item = make_item(client)
    client.post("/settings/profile", data={"email": "", "language": "de"})
    client.post(f"/items/{item}/shares", data={"preset": "1d", "label": "", "next": f"/items/{item}"})
    html = client.get(f"/items/{item}").text
    assert "Läuft in 23 Stunden ab" in html or "Läuft in 1 Tag ab" in html
    assert "Läuft nie ab" in html and "24 Stunden" in html            # the preset menu
    assert "0 Aufrufe" in html and "Teilen" in html


def test_json_api_messages_stay_in_english(client):
    r = client.get("/api/v1/items/99999", headers=DE)
    assert r.status_code == 404 and r.json()["detail"] == "item not found"


def test_locales_ship_with_the_package():
    """The Docker image installs the package; a missing locale folder would fail every German page at runtime."""
    import tomllib
    root = Path(__file__).parent.parent
    cfg = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]
    assert cfg["packages"]["find"]["where"] == ["src"]
    for code in i18n.LOCALES:
        assert (root / f"src/drollery/locales/{code}.py").exists()
    assert (root / "src/drollery/locales/__init__.py").exists()           # so packages.find picks the folder up


def test_language_menu_in_the_header_on_every_page(anon):
    create_user("boss", "a-long-enough-pass")
    page = anon.get("/login")
    assert 'id="lang-menu"' in page.text and 'action="/language"' in page.text and ">English<" in page.text and ">Deutsch<" in page.text
    assert page.text.index('id="theme-menu"') < page.text.index('id="lang-menu"')                    # the globe sits right of the palette
    assert re.search(r'value="en"[^>]*aria-current', page.text)                                      # the current language is marked
    assert 'name="next" value="/login"' in page.text
    r = anon.post("/language", data={"language": "de", "next": "/login"})
    assert r.status_code == 303 and r.headers["location"] == "/login" and f"{i18n.COOKIE}=de" in r.headers["set-cookie"]
    after = anon.get("/login")                                                                       # the cookie now decides, whatever the browser sends
    assert "Halt! Wer da?" in after.text and re.search(r'value="de"[^>]*aria-current', after.text)
    anon.post("/language", data={"language": "en", "next": "/login"})
    assert "Halt! Who goes there?" in anon.get("/login", headers=DE).text


def test_language_menu_returns_to_the_same_page_and_is_safe(anon):
    create_user("boss", "a-long-enough-pass")
    assert anon.post("/language", data={"language": "de", "next": "https://evil.example"}).headers["location"] == "/login"
    assert anon.post("/language", data={"language": "de", "next": "//evil.example"}).headers["location"] == "/login"
    assert "set-cookie" not in anon.post("/language", data={"language": "klingon"}).headers          # unknown codes are ignored
    assert anon.post("/language", data={"language": "de"}, headers={"origin": "https://evil.example"}).status_code == 403


def test_language_menu_is_in_the_signed_in_header_too(client):
    html = client.get("/jobs").text
    assert 'id="lang-menu"' in html and 'name="next" value="/jobs"' in html


def test_switching_while_signed_in_also_updates_the_account(client):
    client.post("/language", data={"language": "de", "next": "/"})
    assert accounts.get_user_by_name("admin")["language"] == "de"


def test_every_language_has_a_flag_that_ships_and_shows_in_the_menu(anon):
    import tomllib
    root = Path(__file__).parent.parent
    assert "templates/flags/*" in tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["drollery"]
    for code in i18n.languages():
        assert (root / f"src/drollery/templates/flags/{i18n.flag(code)}.svg").exists(), code
    assert i18n.flag("en") == "gb" and i18n.flag("de") == "de"
    create_user("boss", "a-long-enough-pass")
    menu = anon.get("/login").text.split('id="lang-menu"')[1].split("</details>")[0]
    assert menu.count('class="flag"') == len(i18n.languages())


@pytest.fixture()
def extra_languages(monkeypatch):
    """Two made-up languages with the plural rules the machinery is there for (as Polish and French have them), so the rules stay
    tested although Drollery itself only ships English and German."""
    import sys
    import types
    def make(name, forms, rule, messages):
        mod = types.ModuleType(f"drollery.locales.{name}")
        mod.NAME, mod.FLAG, mod.MESSAGES, mod.FORMS, mod.plural = name.upper(), "de", messages, forms, staticmethod(rule)
        mod.plural = rule
        monkeypatch.setitem(sys.modules, f"drollery.locales.{name}", mod)
        i18n._load()
        monkeypatch.setitem(i18n._catalogs, name, {"name": mod.NAME, "messages": messages})
    make("zp", 3, lambda n: 0 if n == 1 else 1 if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 2,
         {"{n} hour": ("{n} godzina", "{n} godziny", "{n} godzin")})
    make("zf", 2, lambda n: 0 if n in (0, 1) else 1, {"{n} day": ("{n} jour", "{n} jours")})


def test_plural_rules_of_the_languages_that_need_more_than_one_or_other(extra_languages):
    pl = lambda n: i18n.plural_index("zp", n)                                    # noqa: E731
    assert [pl(n) for n in (1, 2, 4, 5, 12, 14, 21, 22, 25, 112, 0)] == [0, 1, 1, 2, 2, 2, 2, 1, 2, 2, 2]
    assert i18n.forms("zp") == 3 and i18n.forms("de") == 2 and i18n.forms("en") == 2
    assert [i18n.plural_index("zf", n) for n in (0, 1, 2)] == [0, 0, 1]          # zero counts as singular there
    token = i18n.set_language("zp")
    try:
        got = [i18n.tn("{n} hour", "{n} hours", n) for n in (1, 2, 5, 12, 22)]
    finally:
        i18n._current.reset(token)
    assert got == ["1 godzina", "2 godziny", "5 godzin", "12 godzin", "22 godziny"]
    token = i18n.set_language("zf")
    try:
        assert i18n.tn("{n} day", "{n} days", 0) == "0 jour" and i18n.tn("{n} day", "{n} days", 2) == "2 jours"
    finally:
        i18n._current.reset(token)


def test_only_english_and_german_are_offered(client):
    assert list(i18n.languages()) == ["en", "de"] and i18n.LOCALES == ("de",)
    menu = client.get("/").text.split('id="lang-menu"')[1].split("</details>")[0]
    assert menu.count('class="flag"') == 2 and 'value="de"' in menu and 'value="en"' in menu
    for gone in ("es", "fr", "it", "nl", "pl", "sv", "el"):
        assert f'value="{gone}"' not in menu
    root = Path(__file__).parent.parent
    assert sorted(p.name for p in (root / "src/drollery/templates/flags").glob("*.svg")) == ["de.svg", "gb.svg"]
    assert sorted(p.name for p in (root / "src/drollery/locales").glob("*.py")) == ["__init__.py", "de.py"]


def test_a_removed_language_in_a_cookie_an_account_or_a_browser_falls_back_instead_of_breaking(client):
    from drollery import accounts
    with db.tx() as c:
        c.execute("UPDATE users SET language='fr'")                                  # an account from when French existed
    assert "Library" in client.get("/").text or "Search" in client.get("/").text      # English
    page = client.get("/", headers={"Cookie": "drollery_lang=pl"}).text
    assert "<html lang=\"en\"" in page
    assert i18n.from_accept_language("pl, es;q=0.9, de;q=0.5") == "de"                # the next best language the browser lists
    assert i18n.normalize("el") == "" and i18n.normalize("sv-SE") == ""
    assert client.post("/settings/profile", data={"email": "", "language": "it"}, follow_redirects=True).status_code == 200


@pytest.mark.parametrize("code", i18n.LOCALES)
def test_every_page_renders_in_every_language(client, code):
    client.post("/settings/profile", data={"email": "", "language": code})
    item = make_item(client)
    from test_album import make_mp3, upload
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        upload(client, [make_mp3(Path(td) / "a.mp3", "Song", 1, cover=None)], title="Album A")
    from drollery import db as _db
    with _db.tx() as c:
        album = c.execute("SELECT id FROM items WHERE kind='album'").fetchone()["id"]
    for url in ("/", f"/items/{item}", f"/items/{album}", "/albums/new", "/jobs", "/settings/profile", "/settings/security", "/settings/keys", "/settings/ai", "/settings/shares", "/settings/about"):
        r = client.get(url)
        assert r.status_code == 200 and f'lang="{code}"' in r.text, (code, url)
        assert "&lt;code" not in r.text and "&lt;u&gt;" not in r.text and "&lt;b " not in r.text, (code, url)      # inline markup in a translation must not show as text
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<pre.*?</pre>|<code.*?</code>|data-[\w-]+=\"[^\"]*\"", "", r.text, flags=re.S)
        assert not re.search(r"\{(n|name|base|url|id|tag|title|when|path|file|link|target|browse|t)\}", text), (code, url)
    menu = client.get("/").text.split('id="lang-menu"')[1].split("</details>")[0]
    assert menu.count('class="flag"') == len(i18n.languages())                 # every language is offered, each with its flag


def test_language_menu_lists_every_language_with_its_own_name(anon):
    create_user("boss", "a-long-enough-pass")
    menu = anon.get("/login").text.split('id="lang-menu"')[1].split("</details>")[0]
    for name in ("English", "Deutsch"):
        assert f"<span>{name}</span>" in menu, name
    assert menu.count("<span>") == 2
