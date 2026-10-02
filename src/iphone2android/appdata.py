"""The data iPhone apps keep on the phone itself: databases, documents and settings.

An app's data is in AppDomain-<bundle id> and AppDomainGroup-group.<bundle id> in the backup. The
Android version of an app cannot read it directly (different formats, and Android keeps each app's
data private without root), so this finds which apps hold real data and copies it out, for an app
that has its own import, for a dedicated migrator (WhatsApp), or just to keep.

Settings files often contain account names and email addresses. `settings_summary` reads those keys
to help set each app up again, skips anything that looks like a secret, and is meant to stay on your
computer.
"""
from __future__ import annotations

import plistlib
import re
import tempfile
from pathlib import Path

SKIP = ("Caches/", "/Cache", "tmp/", "Crashlytics", "Logs/", "GoogleAnalytics", "Firebase",
        "com.crashlytics", "AppCenter", ".log", ".ttf", ".car", ".nib")
DB_EXT = (".sqlite", ".db", ".sqlite3", ".realm")
SECRET = ("password", "passwd", "secret", "token", "refresh", "private", "pin", "cvv", "apikey", "api_key", "cookie", "session")
INTEREST = ("account", "user", "email", "login", "server", "host", "device", "pair", "region", "locale", "profile")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _domains(bundle: str) -> tuple[str, str]:
    return f"AppDomain-{bundle}", f"AppDomainGroup-group.{bundle}"


def _size(row: dict) -> int:
    from iOSbackup import iOSbackup

    try:
        return int(iOSbackup.getFileInfo(row["file"]).get("size") or 0)
    except Exception:  # noqa: BLE001
        return 0


def survey(backup, bundles: list[str], size=_size) -> list[dict]:
    """Which apps hold real local data, biggest first."""
    out = []
    for b in bundles:
        rows = backup.rows("flags=1 AND (domain=? OR domain=?)", _domains(b))
        dbs, doc_files, doc_bytes = [], 0, 0
        for r in rows:
            rel = r["relativePath"] or ""
            if any(s in rel for s in SKIP):
                continue
            n = size(r)
            if rel.lower().endswith(DB_EXT) and n > 20_000:
                dbs.append({"path": rel, "bytes": n})
            if rel.startswith("Documents/") and n > 0:
                doc_files += 1
                doc_bytes += n
        if dbs or doc_bytes > 200_000:
            out.append({"bundle": b, "databases": sorted(dbs, key=lambda d: -d["bytes"])[:5],
                        "documents": doc_files, "document_bytes": doc_bytes,
                        "total_bytes": sum(d["bytes"] for d in dbs) + doc_bytes})
    return sorted(out, key=lambda x: -x["total_bytes"])


def extract(backup, bundle: str, out: Path) -> dict:
    """Copy one app's whole container, keeping its folder structure."""
    base = out / bundle
    copied, failed = 0, 0
    for r in backup.rows("flags=1 AND (domain=? OR domain=?)", _domains(bundle)):
        rel = r["relativePath"] or "root"
        folder = base / Path(rel).parent
        try:
            backup.copy_entry(r, folder, Path(rel).name or "root")
            copied += 1
        except Exception:  # noqa: BLE001
            failed += 1
    return {"bundle": bundle, "folder": str(base), "files": copied, "failed": failed}


def push(adb, folder: Path, dest_root: str = "/sdcard/iPhoneMigration/AppData") -> bool:
    adb.run("shell", "mkdir", "-p", dest_root)
    return adb.run("push", str(folder), dest_root + "/", timeout=3600).returncode == 0


def settings_summary(backup, bundle: str, limit: int = 40) -> dict:
    """Account names, emails and non-secret settings from an app's plist files."""
    emails: set[str] = set()
    keys: dict[str, str] = {}
    rows = [r for r in backup.rows("flags=1 AND (domain=? OR domain=?)", _domains(bundle))
            if (r["relativePath"] or "").endswith(".plist")][:limit]
    with tempfile.TemporaryDirectory() as tmp:
        for r in rows:
            try:
                p = backup.copy_entry(r, Path(tmp), "t.plist")
                d = plistlib.loads(p.read_bytes())
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                kl = str(k).lower()
                if any(s in kl for s in SECRET) or not isinstance(v, (str, int, float)):
                    continue
                s = str(v)
                emails.update(EMAIL.findall(s))
                if any(t in kl for t in INTEREST) and len(s) < 90:
                    keys[str(k)] = s
    return {"bundle": bundle, "emails": sorted(emails)[:10], "settings": dict(list(keys.items())[:20])}
