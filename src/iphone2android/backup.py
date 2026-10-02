"""Open an encrypted iPhone backup made by Finder or iTunes, and copy files out of it.

Backups live in ~/Library/Application Support/MobileSync/Backup/<UDID>/ on macOS and in
%APPDATA%\\Apple Computer\\MobileSync\\Backup on Windows. Info.plist and Manifest.plist can be read
without the password. Everything else needs the backup password.

A file is named by its domain and its relative path. The same relative path can exist in several
domains, so files are looked up in the decrypted manifest by both, and the manifest row is handed
to the decryptor (it has no domain parameter).
"""
from __future__ import annotations

import os
import plistlib
import shutil
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Library/Application Support/MobileSync/Backup"

# The files worth pulling, by what they are and where each can go on Android.
KNOWN = [
    ("HomeDomain", "Library/SMS/sms.db", "sms.db", "Messages", "SMS Backup & Restore XML"),
    ("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata", "CallHistory.storedata", "Call history", "SMS Backup & Restore XML"),
    ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb", "AddressBook.sqlitedb", "Contacts", "vCard"),
    ("HomeDomain", "Library/Calendar/Calendar.sqlitedb", "Calendar.sqlitedb", "Calendars", "ICS"),
    ("HomeDomain", "Library/Safari/Bookmarks.db", "Safari_Bookmarks.db", "Safari bookmarks", "bookmarks HTML"),
    ("AppDomainGroup-group.com.apple.notes", "NoteStore.sqlite", "NoteStore.sqlite", "Apple Notes", "read with an Apple Notes parser"),
    ("AppDomainGroup-group.net.whatsapp.WhatsApp.shared", "ChatStorage.sqlite", "ChatStorage.sqlite", "WhatsApp chats", "a WhatsApp iOS-to-Android migrator"),
    ("HomeDomain", "Library/SpringBoard/IconState.plist", "IconState.plist", "Home screen layout", "iphone2android layout"),
]


def backups(root: Path = DEFAULT_ROOT) -> list[dict]:
    """Every backup under root, with what its Info.plist says (no password needed)."""
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        info = d / "Info.plist"
        if not info.is_file():
            continue
        with open(info, "rb") as f:
            p = plistlib.load(f)
        out.append({
            "udid": d.name,
            "name": p.get("Device Name", ""),
            "model": p.get("Product Type", ""),
            "ios": p.get("Product Version", ""),
            "date": str(p.get("Last Backup Date", "")),
            "apps": len(p.get("Installed Applications", []) or []),
        })
    return out


def installed_apps(udid: str, root: Path = DEFAULT_ROOT) -> list[str]:
    """Bundle ids of the apps installed when the backup was made (no password needed)."""
    with open(root / udid / "Info.plist", "rb") as f:
        return list(plistlib.load(f).get("Installed Applications", []) or [])


@dataclass
class Backup:
    udid: str
    impl: object  # the iOSbackup object
    manifest: Path  # durable copy of the decrypted Manifest.db

    def _row(self, domain: str, relative_path: str) -> dict | None:
        con = sqlite3.connect(self.manifest)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute("SELECT * FROM Files WHERE domain=? AND relativePath=?", (domain, relative_path)).fetchone()
        finally:
            con.close()
        return dict(r) if r else None

    def rows(self, sql_where: str, params: tuple = ()) -> list[dict]:
        con = sqlite3.connect(self.manifest)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(f"SELECT * FROM Files WHERE {sql_where}", params)]
        finally:
            con.close()

    def copy_entry(self, row: dict, target_folder: Path, target_name: str) -> Path:
        entry = dict(row)
        entry["manifest"] = entry.pop("file")  # the library wants the blob under this key
        target_folder.mkdir(parents=True, exist_ok=True)
        self.impl.getFileDecryptedCopy(manifestEntry=entry, targetName=target_name, targetFolder=str(target_folder))
        return target_folder / target_name

    def copy(self, domain: str, relative_path: str, target_folder: Path, target_name: str) -> Path | None:
        row = self._row(domain, relative_path)
        if not row:
            return None
        return self.copy_entry(row, target_folder, target_name)

    def inventory(self) -> dict:
        """Files and bytes per domain, read from the manifest's own size field."""
        from iOSbackup import iOSbackup

        files, size = Counter(), defaultdict(int)
        for r in self.rows("flags=1"):
            files[r["domain"]] += 1
            try:
                size[r["domain"]] += int(iOSbackup.getFileInfo(r["file"]).get("size") or 0)
            except Exception:  # noqa: BLE001 - an unreadable blob only loses its size
                pass
        return {d: {"files": n, "bytes": size[d]} for d, n in files.most_common()}


def open_backup(udid: str, password: str, workdir: Path, root: Path = DEFAULT_ROOT) -> Backup:
    from iOSbackup import iOSbackup

    impl = iOSbackup(udid=udid, cleartextpassword=password, backuproot=str(root))
    workdir.mkdir(parents=True, exist_ok=True)
    # The decrypted manifest lives in a temp folder that is cleaned up, so keep a copy.
    durable = workdir / "Manifest.decrypted.db"
    shutil.copyfile(impl.manifestDB, durable)
    return Backup(udid=udid, impl=impl, manifest=durable)


def password_from_env_or_prompt() -> str:
    pw = os.environ.get("IPHONE_BACKUP_PASSWORD")
    if pw:
        return pw
    import getpass

    return getpass.getpass("Backup password: ")


def extract_known(b: Backup, out: Path) -> list[tuple[str, str, Path | None]]:
    """Copy every known database out. Returns (label, destination format, path or None)."""
    got = []
    for domain, rel, name, label, dest in KNOWN:
        try:
            p = b.copy(domain, rel, out, name)
        except Exception:  # noqa: BLE001 - a file that fails to decrypt is reported as missing
            p = None
        got.append((label, dest, p))
    return got
