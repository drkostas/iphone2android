"""A simulated home screen that behaves like the ColorOS 16 launcher did during the real migration.

Its traps are the real ones:
- a drop from the drawer lands on the FIRST page's first free cell, whatever page is showing
- dropping a drawer result onto an icon makes a folder auto-named "Social" (names collide)
- dropping onto a folder adds to it
- drawer search is by substring, so "WHAT" finds WhatsApp first
- a swap gesture onto an icon swaps the two
- a folder carried onto another folder merges into it
- icons cannot be dragged out of a folder, only removed inside it
"""
from iphone2android.android.launcher import Item
from iphone2android.android.ui import Node

COLS, ROWS = 4, 6


class SimLauncher:
    def __init__(self, drawer, pages=None):
        self.drawer = list(drawer)  # app names in drawer order
        self.grid = pages or [{}]  # page -> {(col, row): label}
        self.folders = {}  # label -> [apps]
        self.shown = 0
        self.open = None
        self.p = {"labels": {"folder_prefix": "Folder:"}}
        self.gestures = []

    # reading
    def _items(self, page):
        out = []
        for (c, r), label in sorted(self.grid[page].items(), key=lambda kv: (kv[0][1], kv[0][0])):
            kind = "folder" if label.startswith("Folder:") else "app"
            out.append(Item(label, c * 100 + page * 10000, r * 100, kind, (c, r)))
        return out

    def page(self, page):
        self.shown = page
        return self._items(page) if page < len(self.grid) else []

    def pages(self):
        return [self._items(p) for p in range(len(self.grid))]

    def free_cells(self, items):
        used = {i.cell for i in items}
        return [(c, r) for r in range(ROWS) for c in range(COLS) if (c, r) not in used]

    def home(self):
        self.shown, self.open = 0, None

    def _at(self, x, y):
        page, col, row = x // 10000, (x % 10000) // 100, y // 100
        return page, (col, row)

    # drawer
    def drawer_find(self, term, want=None):
        exact = [a for a in self.drawer if a.lower() == (want or term).lower()]
        loose = [a for a in self.drawer if term.split()[0].lower() in a.lower()]
        pick = (exact or loose or [None])[0]
        return Node(pick, -1, -1, "TextView", True) if pick else None

    def drop_from_drawer(self, node, onto=None):
        page0 = self.grid[0]
        if onto is None:
            free = self.free_cells(self._items(0))
            page0[free[0]] = node.label
            return
        _, cell = self._at(*onto)
        target = page0.get(cell)
        if target and target.startswith("Folder:"):
            self.folders[target].append(node.label)
        elif target:
            name = "Folder:Social"
            while name in self.folders:  # the real launcher allows duplicates; keep labels unique here
                name += "'"
            self.folders[name] = [target, node.label]
            page0[cell] = name

    # folders
    def tap(self, x, y):
        page, cell = self._at(x, y)
        self.open = self.grid[page].get(cell)

    def rename_open_folder(self, name):
        old, new = self.open, f"Folder:{name}"
        self.folders[new] = self.folders.pop(old)
        for page in self.grid:
            for cell, label in list(page.items()):
                if label == old:
                    page[cell] = new
        self.open = new
        return True

    def open_folder(self, page, label):
        if page >= len(self.grid) or label not in self.grid[page].values():
            return None
        return list(self.folders[label])

    def remove_from_folder(self, page, label, app):
        if app in self.folders.get(label, []):
            self.folders[label].remove(app)
            return True
        return False

    # moving
    def swap(self, a, b):
        page, ca = self._at(a.x, a.y)
        _, cb = self._at(b.x, b.y)
        g = self.grid[page]
        g[ca], g[cb] = g[cb], g[ca]
        self.gestures.append(("swap", a.label, b.label))

    def move_to_page(self, src, flips, drop_cell):
        _, cell = self._at(src.x, src.y)
        label = self.grid[0].pop(cell)
        while len(self.grid) <= flips:
            self.grid.append({})
        target = self.grid[flips]
        dest = drop_cell or self.free_cells(self._items(flips))[0]
        if dest in target and target[dest].startswith("Folder:") and label.startswith("Folder:"):
            self.folders[target[dest]] += self.folders.pop(label)  # the merge hazard
            return
        target[dest] = label
        self.gestures.append(("carry", label, flips))
