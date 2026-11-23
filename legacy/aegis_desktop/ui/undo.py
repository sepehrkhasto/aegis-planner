# SPDX-License-Identifier: GPL-3.0-or-later
"""Single-step, safe undo for destructive task actions (delete, bulk done, status change).

Only the tasks an action touches are copied, so it costs nothing even with thousands of tasks. The undo stays valid
until ANY other change happens - undoing after unrelated edits could silently drop those edits, so we never allow it.
"""
from __future__ import annotations

import copy


class UndoRecord:
    def __init__(self, vault: dict, ids):
        ids = set(ids)
        self.before_ids = {t.get("id") for t in vault.get("tasks", [])}
        self.copies = [copy.deepcopy(t) for t in vault.get("tasks", []) if t.get("id") in ids]
        self.skips = copy.deepcopy((vault.get("settings") or {}).get("seriesSkips"))     # deleted-on-purpose dates of series

    def apply(self, vault: dict) -> None:
        tasks = vault.setdefault("tasks", [])
        cur = {t.get("id"): t for t in tasks}
        revived = set()
        for cp in self.copies:
            live = cur.get(cp.get("id"))
            if live is None:
                tasks.append(cp)                                   # it was deleted: bring it back...
                revived.add(cp.get("id"))
            else:
                live.clear()                                       # ...or put its old fields back in place
                live.update(cp)
        if revived:                                                # ...and take it out of the trash again
            vault["trash"] = [t for t in vault.get("trash", [])
                              if not (t.get("kind") == "task" and (t.get("item") or {}).get("id") in revived)]
        st = vault.setdefault("settings", {})
        if self.skips is None:
            st.pop("seriesSkips", None)
        else:
            st["seriesSkips"] = copy.deepcopy(self.skips)                # an undone delete must not stay "skipped"
        vault["tasks"] = [t for t in tasks if t.get("id") in self.before_ids]   # drop occurrences created meanwhile
