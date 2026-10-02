"""Build a home screen from a layout file, the way the launcher actually behaves.

    {"pages": [["Camera", {"folder": "Social", "apps": ["WhatsApp", "Telegram"]},
                {"widget": ["Spotify"], "size": "medium"}]],
     "dock": ["Phone", "Messages", "Chrome"]}

Each name is the app's name in the drawer. What the builder relies on (ColorOS 16, see the profile):

- A drop from the drawer lands on the FIRST page's first free cell, whatever page is showing. So
  everything is made on the first page and then carried to its page with an edge hold, one hold
  per page, and dropped on an EMPTY cell (a folder dropped on a folder merges them).
- Dropping a drawer result onto an icon makes a folder, and onto a folder adds to it. The new folder
  is found by its position next to the seed icon, never by its name (auto-names collide).
- A folder's contents are checked by opening it with a fresh navigation. Extras are removed from
  inside the folder. Missing apps are added by dropping from the drawer onto the folder.
- Order is fixed with Icon autofill off by a selection sort that makes one swap and then reads the
  screen again. A swap that creates a folder stops the sort.

Progress is saved after every step, so an interrupted build continues where it stopped. Widgets are
listed for placing through the launcher's widget picker.
"""
from __future__ import annotations

import json
from pathlib import Path


def entry_label(entry, prefix: str = "Folder:") -> str:
    if isinstance(entry, dict) and "widget" in entry:
        return f"Widget:{'/'.join(entry['widget'])}"
    return f"{prefix}{entry['folder']}" if isinstance(entry, dict) else entry


def is_widget(entry) -> bool:
    return isinstance(entry, dict) and "widget" in entry


class Builder:
    def __init__(self, launcher, state_file: Path | None = None, log=print, retries: int = 2):
        self.l = launcher
        self.state_file = state_file
        self.log = log
        self.retries = retries
        self.done: list[str] = []
        self.todo: list[dict] = []
        self.problems: list[str] = []
        if state_file and state_file.exists():
            self.done = json.loads(state_file.read_text()).get("done", [])

    @property
    def prefix(self) -> str:
        return self.l.p["labels"]["folder_prefix"] if hasattr(self.l, "p") else "Folder:"

    def _mark(self, key: str) -> None:
        self.done.append(key)
        if self.state_file:
            self.state_file.write_text(json.dumps({"done": self.done}))

    def _find(self, page: int, label: str):
        hits = [i for i in self.l.page(page) if i.label == label]
        return hits[0] if hits else None

    # ---------------------------------------------------------------- placing

    def place_app(self, name: str) -> object | None:
        """Drop an app from the drawer onto the first page. Returns where it landed."""
        before = {(i.label, i.cell) for i in self.l.page(0)}
        hit = self.l.drawer_find(name, want=name)
        if not hit:
            self.problems.append(f"not in the drawer: {name}")
            return None
        self.l.drop_from_drawer(hit)
        new = [i for i in self.l.page(0) if (i.label, i.cell) not in before and i.label == hit.label]
        if not new:
            self.problems.append(f"{name}: no new icon on the first page after the drop (page full?)")
            return None
        return new[0]

    def carry(self, item, to_page: int) -> bool:
        """Move an icon or folder from the first page to another page, onto an empty cell."""
        if to_page == 0:
            return True
        target = self.l.page(to_page) if to_page < len(self.l.pages()) else []
        free = self.l.free_cells(target)
        if target and not free:
            self.problems.append(f"page {to_page + 1} is full, cannot carry {item.label}")
            return False
        for attempt in range(self.retries + 1):
            src = self._find(0, item.label)
            if not src:
                break
            self.l.move_to_page(src, to_page, free[0] if free else None)
            if self._find(to_page, item.label):
                return True
            self.log(f"    carry {item.label} to page {to_page + 1}: retry {attempt + 1}")
        self.problems.append(f"could not carry {item.label} to page {to_page + 1}")
        return False

    def build_folder(self, name: str, apps: list[str]) -> object | None:
        """Make a folder on the first page from apps in the drawer, name it, and check its contents."""
        label = f"{self.prefix}{name}"
        existing = self._find(0, label)
        if not existing:
            seed = self.place_app(apps[0])
            if not seed or len(apps) == 1:
                return seed
            before = {(i.label, i.cell) for i in self.l.page(0) if i.kind == "folder"}
            hit = self.l.drawer_find(apps[1], want=apps[1])
            if not hit:
                self.problems.append(f"not in the drawer: {apps[1]}")
                return seed
            self.l.drop_from_drawer(hit, onto=(seed.x, seed.y))
            made = [i for i in self.l.page(0) if i.kind == "folder" and (i.label, i.cell) not in before]
            if not made:
                self.problems.append(f"folder {name}: dropping {apps[1]} onto {apps[0]} made no folder")
                return None
            folder = min(made, key=lambda f: abs(f.x - seed.x) + abs(f.y - seed.y))
            self.l.tap(folder.x, folder.y)
            self.l.rename_open_folder(name)
            self.l.home()
        self.fill_folder(0, name, apps)
        return self._find(0, label)

    def fill_folder(self, page: int, name: str, apps: list[str]) -> None:
        label = f"{self.prefix}{name}"
        for attempt in range(self.retries + 1):
            inside = self.l.open_folder(page, label)
            if inside is None:
                self.problems.append(f"folder {name} is not on page {page + 1}")
                return
            missing = [a for a in apps if not any(a.lower() == x.lower() for x in inside)]
            extra = [x for x in inside if not any(a.lower() == x.lower() for a in apps)]
            for x in extra:
                self.log(f"    {name}: removing {x}, which does not belong")
                self.l.remove_from_folder(page, label, x)
            if not missing:
                return
            for a in missing:
                folder = self._find(page, label)
                hit = self.l.drawer_find(a, want=a)
                if not hit or not folder:
                    continue
                if page != 0:
                    self.problems.append(f"folder {name}: add {a} on the first page first")
                    continue
                self.l.drop_from_drawer(hit, onto=(folder.x, folder.y))
        inside = self.l.open_folder(page, label) or []
        still = [a for a in apps if not any(a.lower() == x.lower() for x in inside)]
        if still:
            self.problems.append(f"folder {name}: still missing {', '.join(still)}")

    # ---------------------------------------------------------------- the whole layout

    def build(self, layout: dict) -> None:
        # Build back to front, so carrying an item never passes a page that is already finished.
        for page in reversed(range(len(layout.get("pages", [])))):
            for e in layout["pages"][page]:
                key = f"p{page}:{entry_label(e, self.prefix)}"
                if key in self.done:
                    continue
                if is_widget(e):
                    self.todo.append({"page": page + 1, "widget": e["widget"], "size": e.get("size")})
                    self.log(f"  widget {'/'.join(e['widget'])} ({e.get('size')}): place through the widget picker")
                    self._mark(key)
                    continue
                self.log(f"page {page + 1}: {entry_label(e, self.prefix)}")
                item = self.build_folder(e["folder"], e["apps"]) if isinstance(e, dict) else self.place_app(e)
                if item and self.carry(item, page):
                    self._mark(key)

    def order(self, page: int, wanted: list[str]) -> bool:
        """Selection sort with one swap per reading. Returns False when it had to stop."""
        for i, label in enumerate(wanted):
            items = [x for x in self.l.page(page) if x.kind != "widget"]
            names = [x.label for x in items]
            if i >= len(items) or names[i] == label:
                continue
            if label not in names:
                self.problems.append(f"{label} is not on page {page + 1}")
                continue
            folders = {x.label for x in items if x.kind == "folder"}
            self.l.swap(items[names.index(label)], items[i])
            after = {x.label for x in self.l.page(page) if x.kind == "folder"}
            if after - folders:
                self.problems.append(f"page {page + 1}: a swap created a folder {sorted(after - folders)}, stopped")
                return False
        return True

    def order_all(self, layout: dict) -> bool:
        ok = True
        for page, entries in enumerate(layout.get("pages", [])):
            ok = self.order(page, [entry_label(e, self.prefix) for e in entries if not is_widget(e)]) and ok
        return ok

    def check(self, layout: dict) -> list[str]:
        """Compare every page and folder with the layout. Returns the differences (empty when it matches)."""
        diffs = []
        pages = self.l.pages()
        for p, entries in enumerate(layout.get("pages", [])):
            have = [i.label for i in pages[p] if i.kind != "widget"] if p < len(pages) else []
            want = [entry_label(e, self.prefix) for e in entries if not is_widget(e)]
            if have != want:
                diffs.append(f"page {p + 1}: have {have}, want {want}")
            for e in entries:
                if isinstance(e, dict) and "folder" in e:
                    inside = self.l.open_folder(p, entry_label(e, self.prefix)) or []
                    if sorted(x.lower() for x in inside) != sorted(a.lower() for a in e["apps"]):
                        diffs.append(f"folder {e['folder']}: have {inside}, want {e['apps']}")
        return diffs
