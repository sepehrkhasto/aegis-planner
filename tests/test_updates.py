# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional update check: version comparison, response parsing, and the opt-in behaviour."""
import io
import json


from test_gui import setup_vault, win  # noqa: F401
from aegis_desktop.core import updates
from aegis_desktop.core.updates import Release, is_newer, parse_release, parse_version


def test_parse_version():
    assert parse_version("v2.11.10") == (2, 11, 10)
    assert parse_version("2.5") == (2, 5)
    assert parse_version("nightly") is None
    assert parse_version("") is None


def test_numeric_not_lexicographic():
    assert is_newer("2.11.10", "2.5.0")
    assert not is_newer("2.5.0", "2.11.10")
    assert not is_newer("2.5.0", "2.5.0")
    assert is_newer("2.5.1", "2.5")
    assert not is_newer("garbage", "2.5.0")


def _payload(tag="v9.0.0", url="https://github.com/me/app/releases/tag/v9.0.0"):
    return json.dumps({"tag_name": tag, "html_url": url, "body": "ignored"}).encode()


def test_parse_release_accepts_only_repo_urls():
    assert parse_release(_payload(), "me/app") == Release("9.0.0", "https://github.com/me/app/releases/tag/v9.0.0")
    r = parse_release(_payload(url="https://evil.example/x"), "me/app")
    assert r.url == "https://github.com/me/app/releases"
    assert parse_release(b"not json", "me/app") is None
    assert parse_release(_payload(tag="beta"), "me/app") is None


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_latest_uses_only_user_agent_and_survives_errors():
    seen = {}

    def opener(req, timeout):
        seen["headers"] = dict(req.header_items())
        seen["timeout"] = timeout
        return _Resp(_payload())
    rel = updates.fetch_latest("me/app", opener)
    assert rel.version == "9.0.0" and seen["timeout"] == updates.TIMEOUT_S
    assert set(k.lower() for k in seen["headers"]) == {"user-agent", "accept"}

    def boom(req, timeout):
        raise OSError("offline")
    assert updates.fetch_latest("me/app", boom) is None
    assert updates.fetch_latest("OWNER/aegis-planner", opener) is None      # unconfigured repository: no request at all


def test_check_is_opt_in(win, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "fetch_latest", lambda *a, **k: calls.append(1))
    win.prefs.pop("update_check", None)
    win.maybe_check_updates()
    assert not calls
    win.prefs["update_check"] = True
    win.prefs["last_update_check"] = __import__("datetime").date.today().isoformat()
    win.maybe_check_updates()
    assert not calls                                                      # at most once per day


def test_result_shows_toast_only_when_newer(win):
    pushed = []
    win.toasts.push = lambda *a, **k: pushed.append((a, k))
    win._on_update_result(Release("99.0.0", "https://github.com/me/app/releases"), False)
    assert len(pushed) == 1 and pushed[0][1]["action"][0]
    win._on_update_result(Release("0.0.1", "https://github.com/me/app/releases"), False)
    assert len(pushed) == 1                                               # silent when not asked and nothing new
    win._on_update_result(Release("0.0.1", "https://github.com/me/app/releases"), True)
    assert len(pushed) == 2


def test_only_the_update_module_touches_the_network():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent / "aegis_desktop"
    pat = re.compile(r"^\s*(?:import|from)\s+(?:urllib\.request|socket|http\.client|requests|PyQt6\.QtNetwork)\b", re.M)
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if p.name != "updates.py" and pat.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_core_has_no_qt_dependency():
    import pathlib
    core = pathlib.Path(__file__).resolve().parent.parent / "aegis_desktop" / "core"
    assert [p.name for p in core.glob("*.py") if "PyQt6" in p.read_text(encoding="utf-8")] == []
