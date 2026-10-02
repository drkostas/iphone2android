"""Copy photos and other media out of the backup and onto the phone, in batches.

Each batch is decrypted to a temp folder, pushed with adb and deleted, so the computer never needs
room for the whole camera roll.

The camera roll is often already in Google Photos. These are not, and are easy to lose:
iMessage attachments, photo edits (Mutations) and media kept inside apps.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from .android.adb import Adb
from .backup import Backup

# Android's shared storage refuses these in file names, and adb push then fails for the whole folder
# while still returning success for the files it did copy.
BAD_CHARS = re.compile(r'[:*?"<>|\\]')


def safe_name(name: str) -> str:
    return BAD_CHARS.sub("_", name)

MEDIA_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".mov", ".mp4", ".dng", ".cr2", ".gif",
             ".m4v", ".webp", ".m4a", ".wav", ".aac", ".caf", ".pdf"}

# name -> (domain, path prefix, destination on the phone)
SETS = {
    "camera-roll": ("CameraRollDomain", "Media/DCIM/", "/sdcard/DCIM/iPhone"),
    "message-attachments": ("MediaDomain", "Library/SMS/Attachments/", "/sdcard/Pictures/iPhone_Messages"),
    "photo-edits": ("CameraRollDomain", "Media/PhotoData/Mutations/", "/sdcard/Pictures/iPhone_PhotoEdits"),
}


def app_set(domain: str, dest: str) -> tuple[str, str, str]:
    """Media kept inside one app, for example AppDomainGroup-group.net.whatsapp.WhatsApp.shared."""
    return (domain, "", dest)


def media_rows(b: Backup, domain: str, prefix: str) -> list[dict]:
    rows = b.rows("flags=1 AND domain=? AND relativePath LIKE ?", (domain, prefix + "%"))
    return [r for r in rows if os.path.splitext(r["relativePath"] or "")[1].lower() in MEDIA_EXT]


def push_set(b: Backup, adb: Adb, domain: str, prefix: str, dest: str, batch: int = 60, log=print) -> dict:
    rows = media_rows(b, domain, prefix)
    adb.run("shell", "mkdir", "-p", dest)
    done = pushed_bytes = 0
    failed: list[str] = []
    for i in range(0, len(rows), batch):
        stage = Path(tempfile.mkdtemp(prefix="iphone2android-"))
        try:
            used: set[str] = set()
            for r in rows[i:i + batch]:
                name = safe_name(os.path.basename(r["relativePath"]))
                if name in used:  # the same name from two folders
                    base, ext = os.path.splitext(name)
                    name = f"{base}_{r['fileID'][:6]}{ext}"
                used.add(name)
                try:
                    p = b.copy_entry(r, stage, name)
                    done += 1
                    pushed_bytes += p.stat().st_size
                except Exception as e:  # noqa: BLE001
                    failed.append(f"{r['relativePath']}\t{type(e).__name__}")
            p = adb.run("push", f"{stage}/.", dest + "/", timeout=3600)
            if p.returncode != 0:
                failed.append(f"batch {i // batch}\t{p.stderr.strip()[:80]}")
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        log(f"  {done}/{len(rows)} files, {pushed_bytes / 1e9:.2f} GB, {len(failed)} failed")
    return {"files": len(rows), "copied": done, "bytes": pushed_bytes, "failed": failed}
