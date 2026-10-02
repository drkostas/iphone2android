"""Drive a stock home screen through its UI, with every timing and gesture taken from a profile.

Many launchers close their layout to adb (on ColorOS the launcher database, its content provider and
shortcut pinning are all refused without root), so icons are moved the way a person moves them. The
profile (android/profiles/*.json) holds the gesture recipes, timings, grid and labels for one launcher,
with the evidence for each. This module turns them into operations the builder can rely on, and every
operation reads the screen again afterwards rather than assuming what happened.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import ui
from .adb import Adb, DeviceUnavailable
from .profile import detect


class EmptyScreen(RuntimeError):
    """The screen dump came back empty: the phone is asleep, locked or disconnected. It is not an empty page."""


@dataclass
class Item:
    label: str  # app name, "Folder:<name>", or "Widget:<name>"
    x: int
    y: int
    kind: str  # app, folder or widget
    cell: tuple  # (column, row), or the first cell of a widget
    cells: tuple = ()  # every cell a widget covers


class Launcher:
    def __init__(self, adb: Adb, profile: dict | None = None, speed: float = 1.0):
        self.adb = adb
        self.p = profile or detect(adb)
        self.g = self.p["gestures"]
        self.t = self.p["timing"]
        self.speed = speed
        self.w, self.h = adb.screen_size()

    # ---------------------------------------------------------------- basics

    def wait(self, key_or_seconds) -> None:
        s = self.t[key_or_seconds] if isinstance(key_or_seconds, str) else key_or_seconds
        time.sleep(s * self.speed)

    def px(self, fx: float, fy: float) -> tuple[int, int]:
        return int(self.w * fx), int(self.h * fy)

    def dump(self, allow_empty: bool = False) -> list[ui.Node]:
        nodes = ui.dump(self.adb)
        if not nodes and not allow_empty:
            raise EmptyScreen("the screen dump is empty (asleep, locked or disconnected)")
        return nodes

    def launcher_in_front(self) -> bool:
        """The launcher is the resumed activity AND nothing (shade, dialog) is drawn over it."""
        out = self.adb.shell("dumpsys activity activities | grep topResumedActivity")
        return bool(self.package) and self.package in out and not self.overlay()

    def home(self) -> None:
        g = self.g["home"]
        self.adb.shell(f"; sleep {g.get('gap', 0.25)}; ".join(f"input keyevent {k}" for k in g["keys"]))
        self.wait("after_home")

    def tap(self, x: int, y: int) -> None:
        self.adb.shell(f"input tap {x} {y}")
        self.wait("after_tap")

    def back(self) -> None:
        self.adb.shell("input keyevent KEYCODE_BACK")
        self.wait("after_tap")

    def page_next(self) -> None:
        g = self.g["page_next"]
        (x1, y1), (x2, y2) = self.px(*g["from"]), self.px(*g["to"])
        self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {g['ms']}")
        self.wait("after_swipe")

    def goto(self, page: int) -> None:
        self.home()
        for _ in range(page):
            self.page_next()

    def long_press(self, x: int, y: int) -> None:
        hold = self.g["long_press"]["hold"]
        # One shell, so the finger stays down. Separate adb calls lift it in between.
        self.adb.shell(f"input motionevent DOWN {x} {y}; sleep {hold}; input motionevent UP {x} {y}")
        self.wait("after_tap")

    def drag(self, x1: int, y1: int, x2: int, y2: int, ms: int) -> None:
        self.adb.shell(f"input draganddrop {x1} {y1} {x2} {y2} {ms}")
        self.wait("after_drag")

    # ---------------------------------------------------------------- reading the home screen

    def cell_of(self, x: int, y: int) -> tuple[int, int]:
        g = self.p["grid"]
        col = round((x / self.w - g["first_col_x"]) / g["col_step"])
        row = round((y / self.h - g["first_row_y"]) / g["row_step"])
        return col, row

    def cell_center(self, col: int, row: int) -> tuple[int, int]:
        g = self.p["grid"]
        return self.px(g["first_col_x"] + col * g["col_step"], g["first_row_y"] + row * g["row_step"])

    @property
    def package(self) -> str:
        return self.p.get("match", {}).get("launcher_package") or self.p.get("detected_package", "")

    def own(self, nodes: list[ui.Node]) -> list[ui.Node]:
        """Only what the launcher itself drew. The notification shade, dialogs and keyboards sit on top
        of the launcher in the same dump, and their tiles must never be read as icons."""
        if not self.package or not any(n.package for n in nodes):
            return nodes
        return [n for n in nodes if n.package == self.package]

    def overlay(self) -> list[str]:
        """Packages drawing over the launcher right now (a shade, a dialog). Empty when the home screen is clear."""
        return sorted({n.package for n in self.dump() if n.package and n.package != self.package})

    def items(self, nodes: list[ui.Node] | None = None) -> list[Item]:
        """Apps, folders and widgets on the page showing now, in reading order, without the dock."""
        nodes = self.own(self.dump() if nodes is None else nodes)
        dock_top = self.h * self.p["geometry"]["dock_top"]
        prefix = self.p["labels"]["folder_prefix"]
        folder_names = {n.label[len(prefix):] for n in nodes if n.label.startswith(prefix)}
        out: list[Item] = []
        for n in nodes:
            if "AppWidgetHostView" in n.cls:
                x1, y1, x2, y2 = n.bounds
                covered = tuple(sorted({self.cell_of(cx, cy)
                                        for cx in range(x1 + 20, x2, max(1, int(self.w * self.p["grid"]["col_step"] / 2)))
                                        for cy in range(y1 + 20, y2, max(1, int(self.h * self.p["grid"]["row_step"] / 2)))}))
                out.append(Item(f"Widget:{n.label}", n.x, n.y, "widget", self.cell_of(x1 + 20, y1 + 20), covered))
                continue
            if n.y >= dock_top or not n.clickable:
                continue
            if n.label.startswith(prefix):
                out.append(Item(n.label, n.x, n.y, "folder", self.cell_of(n.x, n.y)))
            elif n.cls in ("TextView", "FrameLayout") and n.label not in folder_names:
                out.append(Item(n.label, n.x, n.y, "app", self.cell_of(n.x, n.y)))
        return sorted(out, key=lambda i: (i.cell[1], i.cell[0]))

    def page(self, page: int) -> list[Item]:
        self.goto(page)
        return self.items()

    def free_cells(self, items: list[Item]) -> list[tuple[int, int]]:
        g = self.p["grid"]
        used = {i.cell for i in items if i.kind != "widget"} | {c for i in items for c in i.cells}
        return [(c, r) for r in range(g["rows"]) for c in range(g["columns"]) if (c, r) not in used]

    def pages(self, limit: int = 10) -> list[list[Item]]:
        """Every page, walking right from the first until a page repeats."""
        self.home()
        out, seen = [], None
        for _ in range(limit):
            items = self.items()
            sig = tuple((i.label, i.cell) for i in items)
            if sig == seen:
                break
            out.append(items)
            seen = sig
            self.page_next()
        self.home()
        return out

    def dock(self) -> list[str]:
        dock_top = self.h * self.p["geometry"]["dock_top"]
        return [n.label for n in sorted(self.own(self.dump()), key=lambda n: n.x) if n.y >= dock_top and n.clickable and n.label]

    # ---------------------------------------------------------------- folders

    def open_folder(self, page: int, label: str) -> list[str] | None:
        """Open a folder with a fresh navigation, read its apps, and close it. None if the folder is not there.

        Fresh navigation matters: after a folder closes, this launcher can jump back to the first
        page, so reading folders one after another without navigating reads the wrong page (#2383).
        """
        target = [i for i in self.page(page) if i.label == label]
        if not target:
            return None
        self.tap(target[0].x, target[0].y)
        nodes = self.dump()
        name = [n for n in nodes if n.cls == "EditText"]
        top = name[0].bounds[3] if name else 0
        apps = [n.label for n in nodes if n.clickable and n.cls == "TextView" and n.y > top]
        self.back()
        return apps

    def rename_open_folder(self, name: str) -> bool:
        g = self.g["rename_folder"]
        field = [n for n in self.dump() if n.cls == "EditText"]
        if not field:
            return False
        self.tap(field[0].x, field[0].y)
        a, b = g["select_all"]
        self.adb.shell(f"input keycombination {a} {b}")
        self.adb.shell("input text " + name.replace(" ", "%s"))
        self.wait("after_text")
        self.adb.shell(f"input keyevent {g['commit']}")  # ENTER does not commit on ColorOS
        self.wait("after_tap")
        return True

    def _menu(self, x: int, y: int, item: str, confirm: str) -> bool:
        """Long-press, choose a menu item, and confirm. The dialog can take a second to appear."""
        self.long_press(x, y)
        hit = [n for n in self.dump() if n.label == item]
        if not hit:
            self.back()
            return False
        self.tap(hit[0].x, hit[0].y)
        tries, gap = self.t["dialog_poll"]
        for _ in range(int(tries)):
            buttons = [n for n in self.dump(allow_empty=True) if n.label == confirm and n.cls.endswith("Button")]
            if buttons:
                self.tap(buttons[0].x, buttons[0].y)
                return True
            self.wait(gap)
        return False

    def remove(self, x: int, y: int) -> bool:
        g = self.g["remove_icon"]
        return self._menu(x, y, g["menu_item"], g["confirm_button"])

    def remove_from_folder(self, page: int, folder: str, app: str) -> bool:
        """The only way an app leaves a folder: long-press it inside the open folder and remove it."""
        target = [i for i in self.page(page) if i.label == folder]
        if not target:
            return False
        self.tap(target[0].x, target[0].y)
        inside = [n for n in self.dump() if n.label == app and n.clickable]
        if not inside:
            self.back()
            return False
        return self.remove(inside[0].x, inside[0].y)

    def ungroup(self, x: int, y: int) -> bool:
        g = self.g["ungroup_folder"]
        return self._menu(x, y, g["menu_item"], g["confirm_button"])

    # ---------------------------------------------------------------- the drawer

    def drawer_find(self, term: str, want: str | None = None) -> ui.Node | None:
        """Open the drawer, search, and return the result to drag. Leaves the drawer open.

        An exact label match wins over a substring match: search is by substring, so 'WHAT'
        finds WhatsApp before WHAT'S UP (#1955).
        """
        g = self.g["drawer_open"]
        self.home()
        (x1, y1), (x2, y2) = self.px(*g["from"]), self.px(*g["to"])
        self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {g['ms']}")
        self.wait("after_drawer_open")
        nodes = self.dump()
        field = [n for n in nodes if n.cls == "EditText"] or [n for n in nodes if n.label.lower().startswith("search")]
        if not field:
            return None
        self.tap(field[0].x, field[0].y)
        self.adb.shell("input keycombination 113 29")  # the field keeps the previous query
        self.adb.shell("input text " + term.replace(" ", "%s"))
        self.wait("after_text")
        results = [n for n in self.dump() if n.cls == "TextView" and n.y < self.h * self.p["geometry"]["dock_top"] and n.clickable]
        want_l = (want or term).lower()
        exact = [n for n in results if n.label.lower() == want_l]
        if exact:
            return exact[0]
        first = term.split()[0].lower()
        loose = [n for n in results if first in n.label.lower()]
        return loose[0] if loose else None

    def drop_from_drawer(self, node: ui.Node, onto: tuple[int, int] | None = None) -> None:
        """Drag a drawer result to the home screen. Without `onto`, it lands on the FIRST page's first free cell."""
        key = "drawer_onto_icon" if onto else "drawer_to_home"
        tx, ty = onto if onto else self.px(self.p["geometry"]["safe_drop_x"], self.p["geometry"]["safe_drop_y"])
        self.drag(node.x, node.y, tx, ty, self.g[key]["ms"])

    # ---------------------------------------------------------------- moving icons

    def swap(self, a: Item, b: Item) -> None:
        self.drag(a.x, a.y, b.x, b.y, self.g["swap"]["ms"])

    def hover_merge(self, src: Item, folder: Item) -> None:
        g = self.g["merge_into_folder"]
        mx, my = (src.x + folder.x) // 2, (src.y + folder.y) // 2
        parts = []
        for step, pause in g["steps"]:
            x, y = {"down": (src.x, src.y), "move_start": (src.x, src.y), "move_mid": (mx, my),
                    "move_target": (folder.x, folder.y), "up": (folder.x, folder.y)}[step]
            verb = "DOWN" if step == "down" else "UP" if step == "up" else "MOVE"
            parts.append(f"input motionevent {verb} {x} {y}" + (f"; sleep {pause}" if pause else ""))
        self.adb.shell("; ".join(parts))
        self.wait("after_drag")

    def merge_fallback(self, src: Item, folder: Item) -> None:
        f = self.g["merge_into_folder"]["fallback"]
        self.drag(src.x, src.y, folder.x, folder.y, f["ms"])

    def move_to_page(self, src: Item, flips: int, drop_cell: tuple[int, int] | None) -> None:
        """Carry an icon or folder to the right edge and hold, once per page to move.

        Each hold flips exactly one page; holding longer overshoots (#2797 #2805). The drop must be
        an EMPTY cell, because a folder dropped onto a folder merges the two (#2400).
        """
        g = self.g["page_flip_with_icon"]
        edge = int(self.w * self.p["geometry"]["page_edge_right_x"])
        lead = int(self.w * g["lead_x"])
        y = src.y
        dx, dy = self.cell_center(*drop_cell) if drop_cell else self.px(*g["drop"])
        parts = [f"input motionevent DOWN {src.x} {y}; sleep {g['down_hold']}",
                 f"input motionevent MOVE {src.x} {y}; sleep 0.15",
                 f"input motionevent MOVE {lead} {y}; sleep 0.2"]
        for i in range(flips):
            parts.append(f"input motionevent MOVE {edge} {y}; sleep {g['hold_per_flip']}")
            if i < flips - 1:
                parts.append(f"input motionevent MOVE {lead} {y}; sleep 0.3")
        parts.append(f"input motionevent MOVE {dx} {dy}; sleep 0.4")
        parts.append(f"input motionevent UP {dx} {dy}")
        self.adb.shell("; ".join(parts))
        self.wait(g["settle"])

    # ---------------------------------------------------------------- settings

    def set_autofill(self, on: bool) -> str:
        """Home screen settings > Icon autofill. Build with it off; turn it on once at the end and check."""
        label = self.p["labels"].get("autofill")
        if not label:
            return "this launcher has no autofill setting in its profile"
        self.home()
        self.long_press(*self.px(0.5, 0.54))
        settings = [n for n in self.dump() if n.label == self.p["labels"]["home_settings"]]
        if not settings:
            self.home()
            return "not found"
        self.tap(settings[0].x, settings[0].y)
        nodes = self.dump()
        row = [n for n in nodes if n.label == label]
        switch = [n for n in nodes if n.cls == "Switch" and row and abs(n.y - row[0].y) < 60]
        state = "not found"
        if switch:
            if (switch[0].label.lower() == "on") != on:
                self.tap(switch[0].x, switch[0].y)
            state = "on" if on else "off"
        self.back()
        self.home()
        return state


__all__ = ["Launcher", "Item", "EmptyScreen", "DeviceUnavailable"]
