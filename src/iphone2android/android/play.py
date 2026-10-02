"""Play Store checks and installs.

Guessed package names are often wrong (a bank's Android package rarely matches its iOS bundle id),
so every mapping is checked against the live Play Store page before anything is installed.
Installs are free apps only, by opening the store page and pressing Install, like a person would.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from .adb import Adb
from .ui import find_button

PLAY_URL = "https://play.google.com/store/apps/details?id={package}&hl=en"
INSTALL_LABELS = {"Install", "Εγκατάσταση", "Instalar", "Installer", "Installieren", "Installa"}
DONE_LABELS = {"Open", "Play", "Uninstall", "Update", "Άνοιγμα", "Abrir", "Ouvrir", "Öffnen", "Apri"}


def listed(package: str, url: str = PLAY_URL, timeout: float = 15.0) -> bool | None:
    """True when the Play Store has a page for the package, False when it does not, None on network errors."""
    req = urllib.request.Request(url.format(package=package), headers={"user-agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except (urllib.error.URLError, TimeoutError):
        return None


def install(adb: Adb, package: str, log=print, wait_s: float = 240, poll_s: float = 6) -> str:
    """Install one free app through the Play Store app. Returns installed, present, no-button or timeout."""
    if adb.installed(package):
        return "present"
    # market:// can open an OEM store chooser, so the Play Store is named explicitly.
    adb.run("shell", "am", "start", "-a", "android.intent.action.VIEW",
            "-d", f"https://play.google.com/store/apps/details?id={package}", "-p", "com.android.vending")
    button = None
    for _ in range(10):  # the store page renders slowly under load
        time.sleep(2.5)
        button = find_button(adb, INSTALL_LABELS | DONE_LABELS)
        if button:
            break
    if not button:
        adb.shell("input keyevent KEYCODE_BACK")
        return "no-button"
    label, (x, y) = button
    if label in DONE_LABELS:
        adb.shell("input keyevent KEYCODE_BACK")
        return "present"
    adb.shell(f"input tap {x} {y}")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(poll_s)
        if adb.installed(package):
            adb.shell("input keyevent KEYCODE_BACK")
            return "installed"
    adb.shell("input keyevent KEYCODE_BACK")
    return "timeout"
