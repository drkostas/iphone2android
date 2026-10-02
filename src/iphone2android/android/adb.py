"""A small adb wrapper.

stdin is always closed. `adb shell` reads stdin, so inside a shell `while read` loop it would eat the
rest of the list and only the first item would be processed.
"""
from __future__ import annotations

import os
import shutil
import subprocess


class DeviceUnavailable(RuntimeError):
    """adb could not reach the phone. Raised instead of returning empty output, which would read as "nothing installed"."""


class Adb:
    def __init__(self, serial: str | None = None, binary: str | None = None):
        self.serial = serial
        self.binary = binary or os.environ.get("IPHONE2ANDROID_ADB") or shutil.which("adb") or "adb"

    def run(self, *args: str, timeout: float = 90) -> subprocess.CompletedProcess:
        cmd = [self.binary] + (["-s", self.serial] if self.serial else []) + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)

    def screenshot(self, timeout: float = 30) -> bytes:
        """The screen as PNG bytes (binary output, so not through run's text decoding)."""
        cmd = [self.binary] + (["-s", self.serial] if self.serial else []) + ["exec-out", "screencap", "-p"]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not r.stdout.startswith(b"\x89PNG"):
            raise DeviceUnavailable((r.stderr or b"").decode("utf-8", "replace").strip()[:200] or "no screenshot returned")
        return r.stdout

    def shell(self, cmd: str, timeout: float = 90) -> str:
        try:
            r = self.run("shell", cmd, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise DeviceUnavailable(f"adb shell timed out after {timeout}s") from e
        # adb's own failures start with "adb:" or "error:". A failing command on the phone does not.
        if r.returncode != 0 and r.stderr.lstrip().startswith(("adb:", "error:")):
            raise DeviceUnavailable(r.stderr.strip()[:200])
        return r.stdout

    def installed(self, package: str) -> bool:
        return f"package:{package}\n" in self.shell(f"pm list packages {package}") + "\n"

    def screen_size(self) -> tuple[int, int]:
        """The size touches are measured in: the override size when one is set, else the physical size."""
        out = self.shell("wm size").strip()
        if "x" not in out:
            raise DeviceUnavailable(f"cannot read the screen size: {out[:80]!r}")
        w, h = out.splitlines()[-1].split(":")[-1].strip().split("x")
        return int(w), int(h)
