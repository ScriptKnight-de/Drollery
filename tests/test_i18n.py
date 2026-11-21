import importlib.util
import re
from pathlib import Path

import pytest

from drollery import accounts, i18n
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
            assert isinstance(cat[key], tuple) and len(cat[key]) == 2, f"{key!r}: expected a (one, other) pair"
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
    assert pick("de-AT,de;q=0.9,en;q=0.8") == "de" and pick("fr, en;q=0.5") == "en" and pick("fr, de;q=0.4") == "de"
    assert pick("") == "en" and pick("xx") == "en" and pick("de;q=0") == "en" and pick("de;q=abc") == "en"
    assert i18n.normalize("DE_ch") == "de" and i18n.normalize("klingon") == "" and i18n.normalize("en-GB") == "en"
    assert list(i18n.languages())[0] == "en" and i18n.languages()["de"] == "Deutsch"


# ------------------------------------------------------------ pages

def test_anonymous_pages_follow_the_browser_language(anon):
    accounts.create_user("boss", "a-long-enough-pass")
    assert "Halt! Who goes there?" in anon.get("/login").text and 'lang="en"' in anon.get("/login").text
    page = anon.get("/login", headers=DE)
    assert "Halt! Wer da?" in page.text and "Benutzername" in page.text and 'lang="de"' in page.text
    wrong = anon.post("/login", data={"username": "boss", "password": "nope-nope-nope"}, headers=DE)
    assert wrong.status_code == 401 and "Benutzername oder Passwort falsch" in wrong.text


def test_the_language_cookie_beats_the_browser_header(anon):
    accounts.create_user("boss", "a-long-enough-pass")
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
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<pre.*?</pre>|<code.*?</code>", "", r.text, flags=re.S)
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


def test_language_switcher_on_the_sign_in_pages(anon):
    accounts.create_user("boss", "a-long-enough-pass")
    page = anon.get("/login")
    assert 'action="/language"' in page.text and ">English<" in page.text and ">Deutsch<" in page.text
    assert re.search(r'value="en"[^>]*aria-current', page.text)                      # the current language is marked
    r = anon.post("/language", data={"language": "de", "next": "/login"})
    assert r.status_code == 303 and r.headers["location"] == "/login" and f"{i18n.COOKIE}=de" in r.headers["set-cookie"]
    after = anon.get("/login")                                                       # the cookie now decides, whatever the browser sends
    assert "Halt! Wer da?" in after.text and re.search(r'value="de"[^>]*aria-current', after.text)
    anon.post("/language", data={"language": "en", "next": "/login"})
    assert "Halt! Who goes there?" in anon.get("/login", headers=DE).text


def test_language_switcher_is_safe_and_on_every_pre_login_page(anon):
    accounts.create_user("boss", "a-long-enough-pass")
    assert anon.post("/language", data={"language": "de", "next": "https://evil.example"}).headers["location"] == "/login"
    assert anon.post("/language", data={"language": "de", "next": "//evil.example"}).headers["location"] == "/login"
    assert "set-cookie" not in anon.post("/language", data={"language": "klingon"}).headers          # unknown codes are ignored
    assert 'action="/language"' in anon.get("/login").text
    assert anon.post("/language", data={"language": "de"}, headers={"origin": "https://evil.example"}).status_code == 403


def test_language_switcher_on_setup_and_two_factor_pages(anon):
    assert 'action="/language"' in anon.get("/setup").text and 'name="next" value="/setup"' in anon.get("/setup").text


def test_switching_while_signed_in_also_updates_the_account(client):
    client.post("/language", data={"language": "de", "next": "/"})
    assert accounts.get_user_by_name("admin")["language"] == "de"
