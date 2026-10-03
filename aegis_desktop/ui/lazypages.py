# SPDX-License-Identifier: GPL-3.0-or-later
"""Pages that are built the first time they are opened.

Every widget alive costs time whenever the style sheet changes (a theme switch re-evaluates every rule for every widget it
has ever built): ~750 widgets, eleven pages, ~175 ms here - and settings alone is 270 of them. Building a page only when
it is first shown keeps a fresh session at a fraction of that, and starts faster.

``LazyPages`` is a mapping, so ``win.pages["notes"]`` keeps working everywhere: the first lookup builds the page (and lets
the owner add it to its stack). Use :meth:`peek` / :meth:`built` for "only if it already exists" - e.g. flushing notes on
lock must not build the notes page just to flush nothing."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Callable


class LazyPages(MutableMapping):
    def __init__(self, ctx, classes: dict, on_build: Callable | None = None):
        self._ctx = ctx
        self._cls = dict(classes)
        self._made: dict = {}
        self._on_build = on_build

    # ------------------------------------------------------------------------------------------ mapping ---
    def __getitem__(self, key):
        page = self._made.get(key)
        if page is not None:
            return page
        if key not in self._cls:
            raise KeyError(key)
        page = self._made[key] = self._cls[key](self._ctx)
        if self._on_build is not None:
            self._on_build(key, page)
        return page

    def __setitem__(self, key, value) -> None:
        self._made[key] = value
        self._cls.setdefault(key, lambda _ctx, v=value: v)

    def __delitem__(self, key) -> None:
        self._made.pop(key, None)
        self._cls.pop(key, None)

    def __iter__(self):
        return iter(self._cls)

    def __len__(self) -> int:
        return len(self._cls)

    def __contains__(self, key) -> bool:
        return key in self._cls

    # ---------------------------------------------------------------------------------------- inspection ---
    def is_built(self, key) -> bool:
        return key in self._made

    def peek(self, key):
        """The page if it has been built, else None (never builds)."""
        return self._made.get(key)

    def built(self) -> list:
        """[(key, page)] of the pages that exist now, in navigation order."""
        return [(k, self._made[k]) for k in self._cls if k in self._made]

    def title(self, key) -> str:
        return getattr(self._cls[key], "title", key)
