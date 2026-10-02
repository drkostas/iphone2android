"""Drive a stock home screen through its UI, which is the only way on locked-down launchers.

On ColorOS (OPPO, OnePlus) the launcher database, its content provider and shortcut pinning are all
closed to adb without root, so icons are moved the way a person moves them. Positions scale with
the screen size. Tested on ColorOS 16 (Android 16). Other launchers need their own tuning.

Rules learned the hard way:
- Re-read the screen before every drag. The grid moves after each change.
- Dropping an icon onto another makes a folder. Dropping onto a folder adds to it.
- A folder is renamed by tapping its title, selecting all, typing and pressing BACK (not ENTER).
- Icons cannot be dragged out of a folder. Long-press inside the open folder and choose Remove.
"""
from __future__ import annotations

import time

from . import ui
from .adb import Adb


class Launcher:
    def __init__(self, adb: Adb, pause: float = 1.0):
        self.adb = adb
        self.pause = pause
        self.w, self.h = adb.screen_size()

    def _sleep(self, s: float) -> None:
        time.sleep(s * self.pause)

    # positions as fractions of the screen, measured on a 1264x2780 screen
    def at(self, fx: float, fy: float) -> tuple[int, int]:
        return int(self.w * fx), int(self.h * fy)

    def dock_top(self) -> int:
        return int(self.h * 0.845)

    def in_dock(self, n: ui.Node) -> bool:
        return n.y > self.dock_top()

    def dump(self) -> list[ui.Node]:
        return ui.dump(self.adb)

    def home(self) -> None:
        for _ in range(2):
            self.adb.shell("input keyevent KEYCODE_HOME")
            self._sleep(1.6)

    def page_next(self) -> None:
        (x1, y), (x2, _) = self.at(0.87, 0.58), self.at(0.16, 0.58)
        # 250 ms. A slower swipe is read as a drag and does not change page.
        self.adb.shell(f"input swipe {x1} {y} {x2} {y} 250")
        self._sleep(1.8)

    def goto(self, page: int) -> None:
        self.home()  # HOME is page 0; swiping left from it opens the feed, not a page
        for _ in range(page):
            self.page_next()

    def drag(self, x1: int, y1: int, x2: int, y2: int, ms: int = 600) -> None:
        # About 600 ms merges reliably. A long hover opens the folder under the finger instead.
        self.adb.shell(f"input draganddrop {x1} {y1} {x2} {y2} {ms}")
        self._sleep(2.5)

    def tap(self, x: int, y: int) -> None:
        self.adb.shell(f"input tap {x} {y}")
        self._sleep(1.8)

    def icons(self, page: int) -> list[ui.Node]:
        """Icons and folders on a page, in reading order, without the dock and the label nodes of folders."""
        self.goto(page)
        nodes = self.dump()
        folder_names = {n.label for n in nodes if n.folder}
        items = [n for n in nodes if n.clickable and n.cls in ("TextView", "FrameLayout")
                 and not self.in_dock(n) and f"Folder:{n.label}" not in folder_names]
        return sorted(items, key=lambda n: (n.y, n.x))

    def drawer_search(self, term: str) -> ui.Node | None:
        """Open the app drawer, search, and return the first result whose name contains the first word."""
        self.home()
        (x, y1), (_, y2) = self.at(0.5, 0.83), self.at(0.5, 0.32)
        self.adb.shell(f"input swipe {x} {y1} {x} {y2} 300")
        self._sleep(2.5)
        nodes = self.dump()
        field = [n for n in nodes if n.cls == "EditText"] or [n for n in nodes if n.label.lower().startswith("search")]
        if not field:
            return None
        self.tap(field[0].x, field[0].y)
        self.adb.shell("input keycombination 113 29")  # ctrl+a
        self.adb.shell("input text " + term.replace(" ", "%s"))
        self._sleep(2.2)
        first = term.split()[0].lower()
        for n in self.dump():
            if n.cls == "TextView" and n.y < self.dock_top() and first in n.label.lower():
                return n
        return None

    def rename_open_folder(self, name: str) -> bool:
        field = [n for n in self.dump() if n.cls == "EditText"]
        if not field:
            return False
        self.tap(field[0].x, field[0].y)
        self.adb.shell("input keycombination 113 29")
        self.adb.shell("input text " + name.replace(" ", "%s"))
        self._sleep(1.2)
        self.adb.shell("input keyevent KEYCODE_BACK")  # ENTER does not commit the name, BACK does
        self._sleep(2.0)
        return True

    def long_press(self, x: int, y: int, seconds: float = 1.4) -> None:
        # One shell, so the finger stays down for the whole gesture.
        self.adb.shell(f"input motionevent DOWN {x} {y}; sleep {seconds}; input motionevent UP {x} {y}")
        self._sleep(1.5)

    def set_autofill(self, on: bool) -> str:
        """Toggle Home screen settings > Icon autofill. Build with it off, then turn it on once to pack the grid."""
        self.home()
        self.long_press(*self.at(0.5, 0.54))
        settings = [n for n in self.dump() if n.label == "Home screen settings" and n.clickable]
        if not settings:
            self.home()
            return "not found"
        self.tap(settings[0].x, settings[0].y)
        nodes = self.dump()
        row = [n for n in nodes if n.label == "Icon autofill"]
        switch = [n for n in nodes if n.cls == "Switch" and row and abs(n.y - row[0].y) < 60]
        state = "not found"
        if switch:
            current = switch[0].label.lower() == "on"
            if current != on:
                self.tap(switch[0].x, switch[0].y)
            state = "on" if on else "off"
        self.adb.shell("input keyevent KEYCODE_BACK")
        self.home()
        return state
