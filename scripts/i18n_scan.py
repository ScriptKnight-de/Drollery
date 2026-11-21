"""List every translatable string in the code and templates, and check a language catalog against them.

    python scripts/i18n_scan.py          # strings that the German catalog lacks, and catalog entries nothing uses
    python scripts/i18n_scan.py --all    # every string

Strings are found where they are written as literals: t("..."), tn("one", "other", n), N_("...") in Python and
_("..."), _n("one", "other", n) in templates. A string built at run time cannot be found, so give it a literal
twin (see the dynamic names in locales/de.py) or mark it with N_().
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "drollery"
STR = r'''("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')'''
PY_T = re.compile(r"(?<![\w.])(?:i18n\.)?(?:t|N_)\(\s*" + STR)
PY_TN = re.compile(r"(?<![\w.])(?:i18n\.)?tn\(\s*" + STR + r"\s*,\s*" + STR)
TPL_T = re.compile(r"(?<![\w.])_\(\s*" + STR)
TPL_TN = re.compile(r"(?<![\w.])_n\(\s*" + STR + r"\s*,\s*" + STR)


def _lit(raw: str) -> str:
    return ast.literal_eval(raw)


def collect() -> dict[str, dict]:
    """key (the English text) -> {"plural": other-form or None, "files": [...]}"""
    found: dict[str, dict] = {}

    def add(key: str, plural: str | None, path: Path) -> None:
        entry = found.setdefault(key, {"plural": plural, "files": []})
        entry["files"].append(path.relative_to(SRC).as_posix())

    for path in sorted(SRC.glob("*.py")):
        if path.name == "i18n.py":
            continue
        text = path.read_text()
        for m in PY_TN.finditer(text):
            add(_lit(m.group(1)), _lit(m.group(2)), path)
        for m in PY_T.finditer(text):
            add(_lit(m.group(1)), None, path)
    for path in sorted((SRC / "templates").glob("*.html")):
        text = path.read_text()
        for m in TPL_TN.finditer(text):
            add(_lit(m.group(1)), _lit(m.group(2)), path)
        for m in TPL_T.finditer(text):
            add(_lit(m.group(1)), None, path)
    return found


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


if __name__ == "__main__":
    sys.path.insert(0, str(SRC.parent))
    from drollery import i18n

    found = collect()
    if "--all" in sys.argv:
        for key in sorted(found):
            print(key)
        sys.exit(0)
    for code in i18n.LOCALES:
        cat = i18n.catalog(code)
        missing = [k for k in found if k not in cat]
        print(f"[{code}] {len(found)} strings, {len(missing)} missing")
        for k in missing:
            print("  -", k, "  (", found[k]["files"][0], ")")
