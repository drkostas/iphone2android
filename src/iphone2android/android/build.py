"""Build a home screen from a layout file, and put each page in order.

    {"pages": [["Camera", "Photos", {"folder": "Social", "apps": ["WhatsApp", "Telegram"]}]],
     "dock": ["Phone", "Messages", "Chrome"]}

Each name is what to type in the app drawer search. Building never assumes where a drop landed: it
reads the screen again after every drop and uses the real position. Progress is saved after every
step, so an interrupted build continues where it stopped.

Order is fixed afterwards by a selection sort that makes one swap and then reads the screen again.
Several swaps from one reading do not converge, because every move shifts the grid. A swap that
creates a folder by accident stops the sort.
"""
from __future__ import annotations

import json
from pathlib import Path


def _label(entry) -> str:
    if isinstance(entry, dict) and "widget" in entry:
        return f"Widget:{'/'.join(entry['widget'])}"
    return f"Folder:{entry['folder']}" if isinstance(entry, dict) else entry


def _is_widget(entry) -> bool:
    return isinstance(entry, dict) and "widget" in entry


class Builder:
    def __init__(self, launcher, state_file: Path | None = None, log=print):
        self.l = launcher
        self.state_file = state_file
        self.log = log
        self.done: list[str] = []
        self.todo: list[dict] = []
        if state_file and state_file.exists():
            self.done = json.loads(state_file.read_text()).get("done", [])

    def _mark(self, key: str) -> None:
        self.done.append(key)
        if self.state_file:
            self.state_file.write_text(json.dumps({"done": self.done}))

    def add(self, name: str, page: int, onto: tuple[int, int] | None = None):
        """Drag an app from the drawer to the page (onto a position to merge). Returns where it landed."""
        hit = self.l.drawer_search(name)
        if not hit:
            self.log(f"  not in the drawer: {name}")
            return None
        tx, ty = onto if onto else self.l.at(0.5, 0.71)
        self.l.drag(hit.x, hit.y, tx, ty, 1800)
        landed = [n for n in self.l.icons(page) if n.label == hit.label]
        return landed[0] if landed else None

    def build_page(self, page: int, entries: list) -> None:
        for e in entries:
            key = f"p{page}:{_label(e)}"
            if key in self.done:
                continue
            if _is_widget(e):
                # Widget pickers differ between launchers, so a widget is placed through the screen
                # (see the skill), and the builder records it as still to do.
                self.todo.append({"page": page + 1, "widget": e["widget"], "size": e.get("size")})
                self.log(f"  widget {'/'.join(e['widget'])} ({e.get('size')}): to place by hand")
                continue
            if isinstance(e, str):
                r = self.add(e, page)
                self.log(f"  {e}: {'placed' if r else 'FAILED'}")
            else:
                self._build_folder(page, e["folder"], e["apps"])
            self._mark(key)

    def _build_folder(self, page: int, name: str, apps: list[str]) -> None:
        if not apps:
            return
        before = {n.label for n in self.l.icons(page) if n.folder}
        first = self.add(apps[0], page)
        if not first:
            self.log(f"  folder {name}: cannot place {apps[0]}")
            return
        if len(apps) == 1:
            self.log(f"  folder {name} has one app, placed it loose")
            return
        self.add(apps[1], page, onto=(first.x, first.y))
        new = [n for n in self.l.icons(page) if n.folder and n.label not in before]
        if not new:
            self.log(f"  folder {name}: no folder formed")
            return
        # Identify the new folder by being new, never by its auto-name (two can share one).
        self.l.tap(new[0].x, new[0].y)
        self.l.rename_open_folder(name)
        for app in apps[2:]:
            target = [n for n in self.l.icons(page) if n.label == f"Folder:{name}"]
            if not target:
                self.log(f"  folder {name}: lost it after renaming")
                return
            self.add(app, page, onto=(target[0].x, target[0].y))
        self.log(f"  folder {name}: {len(apps)} apps")

    def build(self, layout: dict) -> None:
        for page, entries in enumerate(layout.get("pages", [])):
            self.log(f"page {page + 1}")
            self.build_page(page, entries)

    def order(self, page: int, wanted: list[str]) -> bool:
        """Selection sort with one swap per reading. Returns False when it had to stop."""
        for i, label in enumerate(wanted):
            items = self.l.icons(page)
            names = [n.label for n in items]
            if i >= len(items) or names[i] == label:
                continue
            if label not in names:
                self.log(f"  {label} is not on page {page + 1}")
                continue
            folders = {n.label for n in items if n.folder}
            j = names.index(label)
            self.l.drag(items[j].x, items[j].y, items[i].x, items[i].y, 2000)
            after = {n.label for n in self.l.icons(page) if n.folder}
            if after - folders:
                self.log(f"  stopped: the swap created a folder {sorted(after - folders)}")
                return False
        return True

    def order_all(self, layout: dict) -> bool:
        ok = True
        for page, entries in enumerate(layout.get("pages", [])):
            ok = self.order(page, [_label(e) for e in entries if not _is_widget(e)]) and ok
        return ok
