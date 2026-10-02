"""Launcher profiles: every timing, gesture recipe, label and hazard for one launcher, as data.

A profile is JSON in android/profiles/. `detect` picks the one matching the phone's launcher package
and ROM version, and falls back to `generic.json`, which is marked uncalibrated. For an uncalibrated
launcher, follow the calibration steps in the skill and save a new profile with `launcher calibrate`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .adb import Adb

HERE = Path(__file__).parent / "profiles"


def available() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(HERE.glob("*.json"))}


def launcher_package(adb: Adb) -> str:
    out = adb.shell("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME")
    last = [line.strip() for line in out.splitlines() if "/" in line]
    return last[-1].split("/")[0] if last else ""


def detect(adb: Adb, extra_dir: Path | None = None) -> dict:
    """The profile for the phone's launcher. Profiles in extra_dir (your own calibrations) win."""
    pkg = launcher_package(adb)
    candidates = list(available().values())
    if extra_dir and extra_dir.is_dir():
        candidates = [json.loads(p.read_text()) for p in sorted(extra_dir.glob("*.json"))] + candidates
    for prof in candidates:
        m = prof.get("match") or {}
        if m.get("launcher_package") and m["launcher_package"] != pkg:
            continue
        if m.get("rom_property"):
            rom = adb.shell(f"getprop {m['rom_property']}").strip()
            if not rom.startswith(m.get("rom_prefix", "")):
                continue
        if m:
            return prof
    generic = available()["generic"]
    return dict(generic, detected_package=pkg)


def load(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if p.suffix == ".json" and p.exists():
        return json.loads(p.read_text())
    return available()[name_or_path]
