"""What is on the iPhone (from the backup) and what reached the Android phone.

Run it after the official transfer to see what that missed, and again at the end to check the
migration. Every number on the phone side comes from the phone itself over adb. A count the phone
refuses to give (some vendors block the content providers to adb) is reported as null, not as 0.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .android.adb import Adb, DeviceUnavailable


def _count(db: Path, sql: str) -> int | None:
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = con.execute(sql).fetchone()[0]
        con.close()
        return n
    except sqlite3.DatabaseError:
        return None


def iphone_counts(extracted: Path) -> dict:
    sms = extracted / "sms_recovered.db"
    if not sms.exists():
        sms = extracted / "sms.db"
    return {
        "messages": _count(sms, "SELECT count(*) FROM message WHERE text IS NOT NULL AND text != ''"),
        "calls": _count(extracted / "CallHistory.storedata", "SELECT count(*) FROM ZCALLRECORD"),
        "contacts": _count(extracted / "AddressBook.sqlitedb", "SELECT count(*) FROM ABPerson"),
        "calendar_events": _count(extracted / "Calendar.sqlitedb", "SELECT count(*) FROM CalendarItem"),
    }


def _provider_count(adb: Adb, uri: str) -> int | None:
    out = adb.shell(f"content query --uri {uri} --projection _id 2>&1 | grep -c '^Row:'")
    if "Permission Denial" in out or "SecurityException" in out:
        return None
    try:
        return int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


CALL_LOG_CAP = 6000  # Android keeps at most this many calls; a count of exactly 6000 is a cap, not a total


def phone_counts(adb: Adb) -> dict:
    sms = _provider_count(adb, "content://sms")
    mms = _provider_count(adb, "content://mms")
    calls = _provider_count(adb, "content://call_log/calls")
    return {
        # iMessages are restored as MMS, so the iPhone's message count compares with SMS plus MMS.
        "messages": (sms or 0) + (mms or 0) if sms is not None else None,
        "sms": sms,
        "mms": mms,
        "calls": calls,
        "calls_capped": calls == CALL_LOG_CAP,
        "contacts": _provider_count(adb, "content://com.android.contacts/contacts"),
        "calendar_events": _provider_count(adb, "content://com.android.calendar/events"),
    }


def phone_media_names(adb: Adb, roots=("/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Movies")) -> set[str]:
    names: set[str] = set()
    for root in roots:
        out = adb.shell(f"find {root} -type f 2>/dev/null")
        names.update(os.path.basename(line.strip()) for line in out.splitlines() if line.strip())
    return names


def camera_roll_names(backup) -> list[str]:
    from .media import media_rows

    return sorted({os.path.basename(r["relativePath"]) for r in media_rows(backup, "CameraRollDomain", "Media/DCIM/")})


def run(adb: Adb, extracted: Path, mapping: dict | None = None, backup=None) -> dict:
    report: dict = {"iphone": iphone_counts(extracted)}
    try:
        report["phone"] = phone_counts(adb)
        packages = {m["package"] for m in (mapping or {}).values() if m.get("package")}
        if packages:
            installed = {line.split(":", 1)[1].strip() for line in adb.shell("pm list packages").splitlines() if ":" in line}
            report["apps"] = {"mapped": len(packages), "missing": sorted(packages - installed)}
        if backup is not None:
            want = camera_roll_names(backup)
            have = phone_media_names(adb)
            missing = [n for n in want if n not in have]
            report["photos"] = {"camera_roll": len(want), "missing_by_name": len(missing), "examples": missing[:20]}
    except DeviceUnavailable as e:
        report["phone"] = {"error": str(e)}
    phone = report.get("phone") if isinstance(report.get("phone"), dict) else {}
    report["gaps"] = {k: (report["iphone"][k] or 0) - (phone.get(k) or 0)
                      for k in report["iphone"]
                      if phone.get(k) is not None and report["iphone"][k] is not None
                      and not (k == "calls" and phone.get("calls_capped"))}
    return report
