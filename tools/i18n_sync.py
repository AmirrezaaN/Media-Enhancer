"""Update locale/fa/LC_MESSAGES/django.po from the source code without GNU gettext.

Collects {% trans %} / {% blocktrans %} strings from templates and _("...") strings from Python files,
adds new ones to the .po file (existing translations are kept) and lists the ones still untranslated.

    .venv\\Scripts\\python tools\\i18n_sync.py            # report only
    .venv\\Scripts\\python tools\\i18n_sync.py --write    # add new entries to the .po file
"""

import re
import sys
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent
PO_FILE = ROOT / "locale" / "fa" / "LC_MESSAGES" / "django.po"
PY_DIRS = ["accounts", "appapi", "enhancer", "config"]

TPL_TRANS = re.compile(r"""{%\s*trans(?:late)?\s+(["'])(.*?)\1(?:\s+as\s+\w+)?\s*%}""", re.S)
TPL_BLOCK = re.compile(
    r"{%\s*blocktrans(?:late)?(.*?)%}(.*?)(?:{%\s*plural\s*%}(.*?))?{%\s*endblocktrans(?:late)?\s*%}", re.S
)
PY_CALL = re.compile(r"""\b_\(\s*(["'])((?:\\.|(?!\1).)*)\1""", re.S)
PLACEHOLDER = re.compile(r"%\(\w+\)[sd]|%s")


def _block_id(text):
    # Django turns {{ var }} into %(var)s in blocktrans msgids.
    return re.sub(r"{{\s*(\w+)\s*}}", r"%(\1)s", text)


def collect():
    found = {}
    for path in sorted(ROOT.glob("templates/**/*.html")):
        text = path.read_text(encoding="utf-8")
        for m in TPL_TRANS.finditer(text):
            found.setdefault(m.group(2), None)
        for m in TPL_BLOCK.finditer(text):
            found.setdefault(_block_id(m.group(2)), _block_id(m.group(3)) if m.group(3) else None)
    for folder in PY_DIRS:
        for path in sorted((ROOT / folder).glob("**/*.py")):
            if "migrations" in path.parts or path.name == "tests.py":
                continue
            for m in PY_CALL.finditer(path.read_text(encoding="utf-8")):
                found.setdefault(m.group(2).encode().decode("unicode_escape").encode("latin-1").decode("utf-8"), None)
    return found


def main():
    po = polib.pofile(str(PO_FILE))
    known = {e.msgid for e in po}
    added = 0
    for msgid, plural in collect().items():
        if msgid in known:
            continue
        flags = ["python-format"] if PLACEHOLDER.search(msgid) else []
        if plural:
            po.append(polib.POEntry(msgid=msgid, msgid_plural=plural, msgstr_plural={0: "", 1: ""}, flags=flags))
        else:
            po.append(polib.POEntry(msgid=msgid, msgstr="", flags=flags))
        added += 1
    missing = [e.msgid for e in po if not e.translated() and not e.obsolete]
    print(f"{added} new strings, {len(missing)} untranslated")
    for msgid in missing:
        print("  -", msgid)
    if "--write" in sys.argv:
        po.save(str(PO_FILE))
        print(f"saved {PO_FILE}")


if __name__ == "__main__":
    main()
