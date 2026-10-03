# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for defects found during the pre-release code audit."""
from __future__ import annotations

import datetime as dt

import pytest

from aegis_desktop.core import certificate, logic, nlp
from aegis_desktop.core.store import normalize


def test_quick_add_survives_out_of_range_year():
    for text in ("9999/12/1 x", "3500/12/5 a", "0001/12/1 b"):
        nlp.parse_quick(text)                                   # must not raise


def test_midnight_with_minutes_is_not_flattened():
    t = nlp.parse_quick("جلسه ساعت 12:30 شب")
    assert t.time_from == "00:30"


def test_series_with_invalid_due_does_not_crash():
    v = {"tasks": [], "settings": {}}
    base = {"id": "t1", "title": "x", "rep": "daily", "due": {"jy": 1405, "jm": 12, "jd": 30}}
    assert logic.materialize_series(v, base) == 0


def test_migrated_notes_get_unique_ids_and_string_fields():
    v = normalize({"journal": [{"id": "x", "body": 5, "title": ["a"]}], "notes": [{"id": "x"}]})
    ids = [n["id"] for n in v["notes"]]
    assert len(ids) == len(set(ids))
    assert all(isinstance(n.get("body", ""), str) and isinstance(n.get("title", ""), str) for n in v["notes"])


@pytest.mark.parametrize("bad", [5, "2026-01-01T00:00:00", "garbage", None, "9999-12-31T23:59:59-23:00"])
def test_certificate_parse_iso_is_total(bad):
    certificate.parse_iso(bad)                                  # never raises


def test_null_revision_does_not_break_saves():
    from aegis_desktop.core.store import _rev
    assert _rev({"revision": None}) == 0 and _rev({"revision": "7"}) == 0 and _rev({"revision": 3}) == 3


def test_null_settings_tolerated():
    v = normalize({"settings": None})
    assert isinstance(v["settings"], dict)
