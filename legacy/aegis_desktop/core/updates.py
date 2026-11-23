# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional update check.

Disabled by default. When the user enables it, the application asks the public GitHub API for the
latest release tag, at most once per day. The request carries no vault data and no identifier: only a
fixed ``User-Agent``. Nothing is downloaded or installed; the user is shown a link to the releases page.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from .. import REPO, __version__

TIMEOUT_S = 8
MAX_BYTES = 256 * 1024
_TAG = re.compile(r"^[vV]?(\d+(?:\.\d+){0,3})")


@dataclass(frozen=True)
class Release:
    version: str
    url: str


def parse_version(text: str) -> tuple[int, ...] | None:
    """``"v2.11.10"`` -> ``(2, 11, 10)``; ``None`` when the text is not a plain numeric version."""
    m = _TAG.match((text or "").strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def releases_url(repo: str = REPO) -> str:
    return f"https://github.com/{repo}/releases"


def parse_release(payload: bytes, repo: str = REPO) -> Release | None:
    """Extract only the tag and the page address from a GitHub ``releases/latest`` response."""
    try:
        data = json.loads(payload.decode("utf-8"))
        tag = str(data["tag_name"])
    except (ValueError, KeyError, TypeError):
        return None
    if parse_version(tag) is None:
        return None
    url = data.get("html_url")
    if not (isinstance(url, str) and url.startswith(f"https://github.com/{repo}/")):
        url = releases_url(repo)
    return Release(tag.lstrip("vV"), url)


def fetch_latest(repo: str = REPO, opener=urllib.request.urlopen) -> Release | None:
    """Return the latest published release, or ``None`` on any failure (offline, rate limit, bad data)."""
    if repo.startswith("OWNER/"):
        return None                                           # repository not configured
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": "AegisPlanner-update-check", "Accept": "application/vnd.github+json"})
    try:
        with opener(req, timeout=TIMEOUT_S) as r:
            return parse_release(r.read(MAX_BYTES), repo)
    except Exception:                                         # network errors are expected and never fatal
        return None
