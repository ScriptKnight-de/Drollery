"""Every data file the app serves or renders must be listed in package-data, or a pip-installed copy (the Docker image) lacks it
while a source checkout still works."""
import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "drollery"


def test_every_data_file_is_shipped_in_the_package():
    patterns = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["drollery"]
    missing = []
    for f in sorted(PKG.rglob("*")):
        rel = f.relative_to(PKG).as_posix()
        if not f.is_file() or f.suffix in (".py", ".pyc") or "__pycache__" in rel:
            continue
        # a pattern matches one directory level: "static/*" does not reach "static/pixel-orn/x.svg"
        if not any(fnmatch.fnmatchcase(rel, p) and rel.count("/") == p.count("/") for p in patterns):
            missing.append(rel)
    assert not missing, f"not in package-data (missing from the Docker image): {missing[:10]}"
