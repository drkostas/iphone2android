"""The iPhone home screen, read from SpringBoard/IconState.plist, and turned into an Android layout.

An iPhone layout lists bundle ids (com.spotify.client). The Android launcher is driven through its
app drawer search, so the Android layout lists the name to search for. A mapping file joins the two:

    {"com.spotify.client": {"package": "com.spotify.music", "label": "Spotify"}}

`label` is what to type in the drawer search and how the icon is named on the home screen. Apps
with no Android equivalent are left out of the target layout and listed separately.
"""
from __future__ import annotations

import json
import plistlib
from pathlib import Path


def _bundle(item) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and "displayName" not in item:
        return item.get("bundleIdentifier") or item.get("displayIdentifier")
    return None


def _entry(item):
    """A loose app (its bundle id) or a folder {"folder": name, "apps": [...]}; None for widgets."""
    if isinstance(item, dict) and "displayName" in item:
        apps = [b for page in item.get("iconLists", []) for x in page if (b := _bundle(x))]
        return {"folder": item["displayName"], "apps": apps}
    return _bundle(item)


def read_iconstate(path: Path) -> dict:
    with open(path, "rb") as f:
        d = plistlib.load(f)
    return {
        "dock": [e for x in d.get("buttonBar", []) if (e := _entry(x))],
        "pages": [[e for x in page if (e := _entry(x))] for page in d.get("iconLists", [])],
    }


def to_android(ios_layout: dict, mapping: dict) -> tuple[dict, list[str]]:
    """Map an iPhone layout to an Android one. Returns (layout, bundle ids with no mapping)."""
    missing: list[str] = []

    def label(bundle: str) -> str | None:
        m = mapping.get(bundle)
        if not m or not m.get("label"):
            missing.append(bundle)
            return None
        return m["label"]

    def entry(e):
        if isinstance(e, dict):
            apps = [a for b in e["apps"] if (a := label(b))]
            return {"folder": e["folder"], "apps": apps} if apps else None
        return label(e)

    out = {
        "dock": [x for e in ios_layout.get("dock", []) if (x := entry(e)) and isinstance(x, str)],
        "pages": [[x for e in page if (x := entry(e))] for page in ios_layout.get("pages", [])],
    }
    out["pages"] = [p for p in out["pages"] if p]
    return out, sorted(set(missing))


def packages_in(mapping: dict) -> list[str]:
    return sorted({m["package"] for m in mapping.values() if m.get("package")})


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
