# SPDX-License-Identifier: GPL-3.0-or-later
"""Point the project at your own GitHub repository.

Usage:
    python tools/set_repo.py USERNAME              # repository name defaults to "aegis-planner"
    python tools/set_repo.py USERNAME/REPO_NAME

Rewrites the ``OWNER/aegis-planner`` placeholder (or the previous value) in the README files, the docs, the
issue-template config and ``aegis_desktop/__init__.py`` (used by the optional update check).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["README.md", "README.fa.md", "CONTRIBUTING.md", "docs/BUILD.md", "docs/PUBLISHING.fa.md",
         ".github/ISSUE_TEMPLATE/config.yml", "aegis_desktop/__init__.py"]
SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:/[A-Za-z0-9._-]{1,100})?$")


def current() -> str:
    text = (ROOT / "aegis_desktop" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^REPO = "([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("REPO constant not found in aegis_desktop/__init__.py")
    return m.group(1)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not SLUG.match(argv[1]):
        print(__doc__)
        return 2
    new = argv[1] if "/" in argv[1] else f"{argv[1]}/aegis-planner"
    old = current()
    if old == new:
        print(f"Already set to {new}")
        return 0
    changed = 0
    for rel in FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        out = text.replace(old, new)
        if out != text:
            p.write_text(out, encoding="utf-8", newline="")
            changed += 1
    print(f"{old} -> {new}  ({changed} files updated)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
