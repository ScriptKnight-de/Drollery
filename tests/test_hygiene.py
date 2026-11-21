"""Keeps the repository clean: no secrets, no personal content, no stray media, no dead translations or leftovers."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SKIP_DIRS = {".git", ".venv", "data", "__pycache__", ".pytest_cache", "drollery.egg-info", "node_modules", "graphify-out"}
TEXT_SUFFIXES = {".py", ".html", ".js", ".css", ".md", ".toml", ".yml", ".yaml", ".txt", ".example", ".cfg", ".svg", ".json"}


def project_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS) and path.name != ".env":
            yield path


def text_files():
    for path in project_files():
        if path.suffix in TEXT_SUFFIXES or path.name in {"Dockerfile", ".gitignore", ".dockerignore", "LICENSE", ".env.example"}:
            if path.name != "htmx.min.js" and path != Path(__file__):
                yield path


def test_no_well_known_secret_formats_are_in_the_project():
    patterns = {
        "GitHub token": r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",
        "GitLab token": r"glpat-[A-Za-z0-9_-]{15,}",
        "OpenAI-style key": r"\bsk-[A-Za-z0-9]{20,}",
        "AWS key": r"AKIA[0-9A-Z]{16}",
        "Slack token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
        "JWT": r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}",
        "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY",
        "Drollery API key": r"\bdrl_[A-Za-z0-9_-]{20,}",
    }
    hits = [f"{p.relative_to(ROOT)}: {name}" for p in text_files() for name, pat in patterns.items() if re.search(pat, p.read_text(errors="ignore"))]
    assert not hits, hits


def test_no_secret_is_assigned_a_real_looking_value():
    pat = re.compile(r"""(api[_-]?key|apikey|secret|token|passw(or)?d|authorization)\s*[:=]\s*["'](?!\s*["'])([A-Za-z0-9_./+=-]{24,})["']""", re.I)
    hits = []
    for p in text_files():
        if p.parts[-2] == "tests":
            continue                                                      # tests use invented keys on purpose
        hits += [f"{p.relative_to(ROOT)}: {m.group(0)[:60]}" for m in pat.finditer(p.read_text(errors="ignore"))]
    assert not hits, hits


def test_no_personal_addresses_or_paths_are_in_the_project():
    bad = {
        "a real e-mail address": r"[\w.+-]+@(?!example\.|localhost|users\.noreply|test\b|drollery)[\w-]+\.(?:de|com|net|org|io|eu)\b",
        "a home folder": r"/home/(?!ubuntu/)[a-z][\w.-]*/",             # (/home/ubuntu is the user inside the Whisper image)
        "a scratch path": r"/tmp/claude",
        "the owner's own network": r"192\.168\.20\.",
    }
    hits = []
    for p in text_files():
        text = p.read_text(errors="ignore")
        for what, pat in bad.items():
            for m in re.finditer(pat, text):
                if what == "a real e-mail address" and m.group(0).startswith("noreply@"):
                    continue
                hits.append(f"{p.relative_to(ROOT)}: {what}: {m.group(0)}")
    assert not hits, hits


def test_no_media_databases_or_environment_files_are_in_the_project():
    forbidden = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm", ".mov", ".zip", ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".keystore"}
    found = [str(p.relative_to(ROOT)) for p in project_files() if p.suffix.lower() in forbidden or p.name in {".env", "config.toml", "setup-code"}]
    assert not found, found
    ignore = (ROOT / ".gitignore").read_text()
    assert ".env" in ignore and "data/" in ignore                           # the places a real library and real keys live stay out of git


def test_the_example_environment_file_holds_no_values_for_secrets():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if re.match(r"\s*[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD|CODE)\s*=\s*\S", line):
            pytest.fail(f"a secret has a value in .env.example: {line.split('=')[0]}")


def test_the_german_catalog_has_no_entries_that_nothing_uses():
    import importlib.util
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("i18n_scan", ROOT / "scripts" / "i18n_scan.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    from drollery import i18n
    used = set(scan.collect())
    corpus = "\n".join(p.read_text() for p in (ROOT / "src/drollery").rglob("*") if p.suffix in {".py", ".html", ".js"} and "locales" not in p.parts)
    by_name = {"Profile saved", "describe", "done", "failed", "fetch", "queued", "running", "transcribe", "transcribe_track"}      # built from variables
    stale = sorted(k for k in i18n.catalog("de") if k not in used and k not in by_name)
    assert not stale, f"entries nothing refers to: {stale[:5]}"
    for name in by_name:                                                      # and the names that are allowed really are still used
        assert re.search(r"(?<![\w])%s(?![\w])" % re.escape(name), corpus), name


def test_no_unused_imports_in_the_source():
    import ast
    problems = []
    for p in sorted((ROOT / "src/drollery").glob("*.py")):
        if p.name == "__init__.py":
            continue
        tree = ast.parse(p.read_text())
        imported = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imported[(a.asname or a.name).split(".")[0]] = n.lineno
            elif isinstance(n, ast.ImportFrom) and n.module != "__future__":
                for a in n.names:
                    imported[a.asname or a.name] = n.lineno
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        strings = " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        problems += [f"{p.name}:{line}: {name}" for name, line in imported.items() if name not in used and not re.search(r"\b%s\b" % re.escape(name), strings)]
    assert not problems, problems


def test_the_old_display_name_column_is_dropped_on_upgrade(client):
    from drollery import db
    with db.tx() as c:
        c.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")             # a database from before it was removed
        assert "display_name" in {r["name"] for r in c.execute("SELECT name FROM pragma_table_info('users')")}
        db._migrate_users(c)
        assert "display_name" not in {r["name"] for r in c.execute("SELECT name FROM pragma_table_info('users')")}
        assert c.execute("SELECT username FROM users").fetchone()["username"] == "admin"            # the account itself is untouched
    assert client.get("/settings/profile").status_code == 200


def test_the_guards_really_catch_what_they_are_for():
    """A guard that never fires proves nothing: feed the patterns examples of what must be caught (and of what must not)."""
    secret = re.compile(r"""(api[_-]?key|apikey|secret|token|passw(or)?d|authorization)\s*[:=]\s*["'](?!\s*["'])([A-Za-z0-9_./+=-]{24,})["']""", re.I)
    assert secret.search('api_key = "abcdefghijklmnopqrstuvwxyz012345"') and secret.search("TOKEN: 'AbCdEfGhIjKlMnOpQrStUvWxYz'")
    assert not secret.search('api_key = ""') and not secret.search('password = "short"') and not secret.search('api_key="${OMDB_KEY}"')
    assert re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", "ghp_" + "a" * 30) and re.search(r"\bsk-[A-Za-z0-9]{20,}", "sk-" + "b" * 24)
    assert re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY", "-----BEGIN RSA PRIVATE KEY-----")
    mail = r"[\w.+-]+@(?!example\.|localhost|users\.noreply|test\b|drollery)[\w-]+\.(?:de|com|net|org|io|eu)\b"
    assert re.search(mail, "write to someone@gmail.com") and not re.search(mail, "me@example.org") and not re.search(mail, "admin@localhost")
    home = r"/home/(?!ubuntu/)[a-z][\w.-]*/"
    assert re.search(home, "/home/alice/projects/x") and not re.search(home, "/home/ubuntu/.cache/huggingface")


# ------------------------------------------------------------ what a public repository needs

def test_the_public_files_exist_and_are_not_empty():
    for name, smallest in (("LICENSE", 900), ("README.md", 2000), ("SECURITY.md", 500), ("CONTRIBUTING.md", 500), ("CHANGELOG.md", 300),
                           ("THIRD_PARTY_NOTICES.md", 1000), (".gitignore", 20), (".env.example", 200)):
        assert (ROOT / name).is_file() and (ROOT / name).stat().st_size >= smallest, name


def test_the_version_is_the_same_everywhere_and_the_changelog_knows_it():
    import tomllib
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    init = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/drollery/__init__.py").read_text()).group(1)
    assert meta["version"] == init
    assert re.search(r"^## \[%s\]" % re.escape(init), (ROOT / "CHANGELOG.md").read_text(), re.M), "add this version to CHANGELOG.md"


def test_the_package_metadata_is_complete_for_publishing():
    import tomllib
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    for key in ("name", "version", "description", "readme", "requires-python", "license", "authors", "classifiers", "keywords", "urls"):
        assert meta.get(key), key
    assert {"Repository", "Issues", "Changelog"} <= set(meta["urls"])
    assert (ROOT / "LICENSE").read_text().startswith("MIT License") and meta["license"]["text"] == "MIT"


def test_vendored_code_and_assets_are_credited():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    htmx = (ROOT / "src/drollery/static/htmx.min.js").read_text()
    version = re.search(r'version:"([\d.]+)"', htmx).group(1)
    assert f"htmx {version}" in notices                                    # the credit names the version that is really bundled
    icons = (ROOT / "src/drollery/templates/icons.html").read_text()
    assert "lucide" in icons.lower() and "Lucide" in notices and "ISC" in notices
    for brand in ("Simple Icons", "Octicons"):
        assert brand in icons and brand in notices
    for dependency in re.findall(r'^\s*"([A-Za-z0-9_.-]+)', (ROOT / "pyproject.toml").read_text().split("dependencies = [")[1].split("]")[0], re.M):
        name = dependency.split(">")[0].split("=")[0]
        assert name.lower().replace("_", "-") in notices.lower().replace("_", "-") or name.lower() == "python-multipart", name


def test_the_readme_promises_match_the_code():
    readme = (ROOT / "README.md").read_text()
    assert "no telemetry" in readme.lower() and "THIRD_PARTY_NOTICES.md" in readme and "SECURITY.md" in readme
    base = (ROOT / "src/drollery/templates/base.html").read_text()
    assert not re.search(r"""(?:src|href)=["']https?://""", base)            # no CDN, font or tracker is loaded by a page
    css = (ROOT / "src/drollery/static/style.css").read_text()
    assert "@import" not in css and "url(http" not in css
    assert "birthday" in readme and "age, gender" not in readme                # the people feature is described as it is now
