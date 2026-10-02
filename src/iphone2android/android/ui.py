"""Read the phone's screen through uiautomator."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .adb import Adb


@dataclass
class Node:
    label: str
    x: int
    y: int
    cls: str
    clickable: bool

    @property
    def folder(self) -> bool:
        return self.label.startswith("Folder:")


def _center(bounds: str) -> tuple[int, int]:
    m = [int(v) for v in re.findall(r"-?\d+", bounds)]
    return (m[0] + m[2]) // 2, (m[1] + m[3]) // 2


def parse(xml: str) -> list[Node]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for n in root.iter("node"):
        label = (n.get("content-desc") or "").strip() or (n.get("text") or "").strip()
        bounds = n.get("bounds", "")
        if not label or not bounds:
            continue
        x, y = _center(bounds)
        out.append(Node(label, x, y, n.get("class", "").split(".")[-1], n.get("clickable") == "true"))
    return out


def dump(adb: Adb) -> list[Node]:
    adb.shell("uiautomator dump /sdcard/window.xml")
    return parse(adb.shell("cat /sdcard/window.xml"))


def find_button(adb: Adb, labels: set[str]):
    for n in dump(adb):
        if n.label in labels:
            return n.label, (n.x, n.y)
    return None
