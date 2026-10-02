"""Turn the extracted iPhone databases into files Android and Google can import.

    sms.db                  -> sms_backup.xml     (SMS Backup & Restore)
    CallHistory.storedata   -> calls_backup.xml   (SMS Backup & Restore)
    AddressBook.sqlitedb    -> contacts.vcf       (Google Contacts)
    Calendar.sqlitedb       -> calendar.ics       (Google Calendar)
    Safari_Bookmarks.db     -> safari_bookmarks.html (any browser's bookmark import)

Apple stores dates as seconds since 2001-01-01. Newer sms.db files use nanoseconds.
"""
from __future__ import annotations

import datetime
import html
import shutil
import sqlite3
import subprocess
from pathlib import Path

APPLE_EPOCH = 978307200  # 2001-01-01 in unix seconds


def _open(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.text_factory = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else b
    return c


def apple_ms(value) -> int:
    if not value:
        return 0
    v = int(value)
    if v > 10**12:  # nanoseconds on newer iOS
        v //= 1_000_000_000
    return (v + APPLE_EPOCH) * 1000


def recover_sms(src: Path, dst: Path) -> bool:
    """Rebuild a truncated sms.db with sqlite3's .recover.

    Apple sometimes snapshots sms.db in the middle of a write, so the backup holds fewer pages than
    the file's header declares and SQLite refuses to open it. .recover reads what is there.
    """
    if not shutil.which("sqlite3"):
        return False
    dump = subprocess.run(["sqlite3", str(src), ".recover"], capture_output=True, text=True)
    if dump.returncode != 0 or not dump.stdout:
        return False
    if dst.exists():
        dst.unlink()
    load = subprocess.run(["sqlite3", str(dst)], input=dump.stdout, capture_output=True, text=True)
    return load.returncode == 0 and dst.exists()


def sms(src_dir: Path, out_dir: Path) -> int:
    src = src_dir / "sms_recovered.db"
    if not src.exists():
        src = src_dir / "sms.db"
        try:
            _open(src).execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            fixed = src_dir / "sms_recovered.db"
            if not shutil.which("sqlite3"):
                raise RuntimeError("sms.db is damaged and the sqlite3 command is needed to repair it (install sqlite3)")
            if not recover_sms(src, fixed):
                raise RuntimeError("sms.db is damaged and sqlite3 .recover could not repair it")
            src = fixed
    rows = _open(src).execute(
        """SELECT m.text, m.date, m.is_from_me, h.id FROM message m
           LEFT JOIN handle h ON m.handle_id = h.ROWID
           WHERE m.text IS NOT NULL AND m.text != ''"""
    ).fetchall()
    rows = [r for r in rows if r[3]]
    with open(out_dir / "sms_backup.xml", "w", encoding="utf-8") as f:
        f.write(f"<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<smses count=\"{len(rows)}\">\n")
        for text, date, from_me, addr in rows:
            f.write(
                f'  <sms protocol="0" address="{html.escape(str(addr), True)}" date="{apple_ms(date)}" '
                f'type="{2 if from_me else 1}" subject="null" body="{html.escape(str(text), True)}" '
                'toa="null" sc_toa="null" service_center="null" read="1" status="-1" locked="0" />\n'
            )
        f.write("</smses>\n")
    return len(rows)


def calls(src_dir: Path, out_dir: Path) -> int:
    rows = _open(src_dir / "CallHistory.storedata").execute(
        "SELECT ZADDRESS, ZDATE, ZDURATION, ZORIGINATED, ZANSWERED FROM ZCALLRECORD WHERE ZADDRESS IS NOT NULL"
    ).fetchall()
    with open(out_dir / "calls_backup.xml", "w", encoding="utf-8") as f:
        f.write(f"<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<calls count=\"{len(rows)}\">\n")
        for addr, date, dur, outgoing, answered in rows:
            kind = 2 if outgoing else (1 if answered else 3)  # 1 incoming, 2 outgoing, 3 missed
            f.write(
                f'  <call number="{html.escape(str(addr), True)}" duration="{int(dur or 0)}" '
                f'date="{int(((date or 0) + APPLE_EPOCH) * 1000)}" type="{kind}" presentation="1" />\n'
            )
        f.write("</calls>\n")
    return len(rows)


def contacts(src_dir: Path, out_dir: Path) -> int:
    c = _open(src_dir / "AddressBook.sqlitedb")
    n = 0
    with open(out_dir / "contacts.vcf", "w", encoding="utf-8") as f:
        for pid, first, last, org in c.execute("SELECT ROWID, First, Last, Organization FROM ABPerson").fetchall():
            first, last, org = first or "", last or "", org or ""
            # property 3 is a phone number and 4 an email address
            values = [v[0] for v in c.execute(
                "SELECT value FROM ABMultiValue WHERE record_id=? AND property IN (3, 4)", (pid,)
            ).fetchall() if v[0]]
            if not (first or last or org or values):
                continue
            f.write("BEGIN:VCARD\nVERSION:3.0\n")
            f.write(f"N:{last};{first};;;\nFN:{(first + ' ' + last).strip() or org}\n")
            if org:
                f.write(f"ORG:{org}\n")
            for v in values:
                f.write(f"EMAIL;TYPE=INTERNET:{v}\n" if "@" in str(v) else f"TEL;TYPE=CELL:{v}\n")
            f.write("END:VCARD\n")
            n += 1
    return n


def _ics_time(value) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(float(value) + APPLE_EPOCH, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _ics_text(s) -> str:
    return str(s).replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def calendar(src_dir: Path, out_dir: Path) -> int:
    c = _open(src_dir / "Calendar.sqlitedb")
    cols = {r[1] for r in c.execute("PRAGMA table_info(CalendarItem)")}
    sel = ["ROWID", "summary", "start_date", "end_date"] + (["description"] if "description" in cols else [])
    n = 0
    with open(out_dir / "calendar.ics", "w", encoding="utf-8") as f:
        f.write("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//iphone2android//EN\nCALSCALE:GREGORIAN\n")
        for r in c.execute(f"SELECT {', '.join(sel)} FROM CalendarItem WHERE summary IS NOT NULL").fetchall():
            d = dict(zip(sel, r))
            start, end = _ics_time(d.get("start_date")), _ics_time(d.get("end_date"))
            if not start:
                continue
            f.write(f"BEGIN:VEVENT\nUID:ios-{d['ROWID']}@iphone2android\nDTSTAMP:{start}\nDTSTART:{start}\n")
            if end:
                f.write(f"DTEND:{end}\n")
            f.write(f"SUMMARY:{_ics_text(d.get('summary') or '')}\n")
            if d.get("description"):
                f.write(f"DESCRIPTION:{_ics_text(d['description'])}\n")
            f.write("END:VEVENT\n")
            n += 1
        f.write("END:VCALENDAR\n")
    return n


def bookmarks(src_dir: Path, out_dir: Path) -> int:
    rows = _open(src_dir / "Safari_Bookmarks.db").execute(
        "SELECT title, url FROM bookmarks WHERE url IS NOT NULL AND url != ''"
    ).fetchall()
    with open(out_dir / "safari_bookmarks.html", "w", encoding="utf-8") as f:
        f.write('<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
                "<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n<DL><p>\n")
        for title, url in rows:
            f.write(f'    <DT><A HREF="{html.escape(str(url), True)}">{html.escape(str(title or url))}</A>\n')
        f.write("</DL><p>\n")
    return len(rows)


ALL = (sms, calls, contacts, calendar, bookmarks)


def convert_all(src_dir: Path, out_dir: Path) -> list[tuple[str, int | None, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for fn in ALL:
        try:
            results.append((fn.__name__, fn(src_dir, out_dir), ""))
        except Exception as e:  # noqa: BLE001 - one missing database must not stop the others
            results.append((fn.__name__, None, f"{type(e).__name__}: {e}"))
    return results
