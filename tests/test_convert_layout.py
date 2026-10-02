import plistlib
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

from iphone2android import convert, layout

T = 700000000  # seconds after 2001-01-01


def db(path: Path, script: str) -> None:
    con = sqlite3.connect(path)
    con.executescript(script)
    con.commit()
    con.close()


def make_sources(d: Path) -> None:
    db(d / "sms.db", f"""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, date INTEGER, is_from_me INTEGER, handle_id INTEGER);
        INSERT INTO handle VALUES (1, '+301234567');
        INSERT INTO message VALUES (1, 'hi & <bye>', {T}, 0, 1);
        INSERT INTO message VALUES (2, 'reply', {T * 1_000_000_000}, 1, 1);
        INSERT INTO message VALUES (3, '', {T}, 1, 1);
        INSERT INTO message VALUES (4, 'no handle', {T}, 1, NULL);""")
    db(d / "CallHistory.storedata", f"""
        CREATE TABLE ZCALLRECORD (ZADDRESS TEXT, ZDATE REAL, ZDURATION REAL, ZORIGINATED INTEGER, ZANSWERED INTEGER);
        INSERT INTO ZCALLRECORD VALUES ('+301', {T}, 61.5, 1, 1);
        INSERT INTO ZCALLRECORD VALUES ('+302', {T}, 0, 0, 0);""")
    db(d / "AddressBook.sqlitedb", """
        CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, First TEXT, Last TEXT, Organization TEXT);
        CREATE TABLE ABMultiValue (record_id INTEGER, property INTEGER, value TEXT);
        INSERT INTO ABPerson VALUES (1, 'Ada', 'Lovelace', NULL);
        INSERT INTO ABPerson VALUES (2, NULL, NULL, NULL);
        INSERT INTO ABMultiValue VALUES (1, 3, '+3069'), (1, 4, 'ada@example.com'), (1, 22, 'ignored');""")
    db(d / "Calendar.sqlitedb", f"""
        CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, summary TEXT, start_date REAL, end_date REAL, description TEXT);
        INSERT INTO CalendarItem VALUES (1, 'Dentist, 10am; bring card', {T}, {T + 3600}, 'line1\nline2');""")
    db(d / "Safari_Bookmarks.db", """
        CREATE TABLE bookmarks (title TEXT, url TEXT);
        INSERT INTO bookmarks VALUES ('Example', 'https://example.com/?a=1&b=2'), ('Folder', NULL);""")


def test_convert_all(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    make_sources(src)
    results = {name: n for name, n, _ in convert.convert_all(src, out)}
    assert results == {"sms": 2, "calls": 2, "contacts": 1, "calendar": 1, "bookmarks": 1}

    smses = ET.parse(out / "sms_backup.xml").getroot()
    first, second = smses.findall("sms")
    assert first.get("body") == "hi & <bye>" and first.get("type") == "1"
    assert second.get("type") == "2"
    assert first.get("date") == second.get("date") == str((T + convert.APPLE_EPOCH) * 1000)  # ns handled

    calls = ET.parse(out / "calls_backup.xml").getroot().findall("call")
    assert [c.get("type") for c in calls] == ["2", "3"]

    vcf = (out / "contacts.vcf").read_text()
    assert "FN:Ada Lovelace" in vcf and "TEL;TYPE=CELL:+3069" in vcf and "EMAIL;TYPE=INTERNET:ada@example.com" in vcf
    assert "ignored" not in vcf

    ics = (out / "calendar.ics").read_text()
    assert r"SUMMARY:Dentist\, 10am\; bring card" in ics and r"DESCRIPTION:line1\nline2" in ics

    assert "https://example.com/?a=1&amp;b=2" in (out / "safari_bookmarks.html").read_text()


def test_a_missing_database_does_not_stop_the_rest(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    make_sources(src)
    (src / "Calendar.sqlitedb").unlink()
    results = {name: (n, err) for name, n, err in convert.convert_all(src, out)}
    assert results["calendar"][0] is None and results["calendar"][1]
    assert results["sms"][0] == 2


def test_a_damaged_sms_db_without_sqlite3_says_so(tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    make_sources(src)
    data = (src / "sms.db").read_bytes()
    (src / "sms.db").write_bytes(data[:28] + b"\x00\x00\x00\x40" + data[32:])
    monkeypatch.setattr(convert.shutil, "which", lambda _name: None)
    results = {name: err for name, _, err in convert.convert_all(src, out)}
    assert "install sqlite3" in results["sms"]


def test_truncated_sms_db_is_recovered(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    make_sources(src)
    data = (src / "sms.db").read_bytes()
    (src / "sms.db").write_bytes(data[:28] + b"\x00\x00\x00\x40" + data[32:])  # header claims 64 pages
    results = {name: n for name, n, _ in convert.convert_all(src, out)}
    assert results["sms"] == 2
    assert (src / "sms_recovered.db").exists()  # the recovery really ran


ICONSTATE = {
    "buttonBar": ["com.apple.mobilephone", "com.apple.MobileSMS", {"bundleIdentifier": "com.google.chrome.ios"}],
    "iconLists": [
        ["com.apple.camera", {"displayName": "Social", "iconLists": [["net.whatsapp.WhatsApp", "ph.telegra.Telegraph"]]},
         {"iconType": "widget", "displayName": "Weather", "iconLists": []}],
        ["com.unknown.app"],
    ],
}


def test_iconstate_and_mapping(tmp_path):
    p = tmp_path / "IconState.plist"
    p.write_bytes(plistlib.dumps(ICONSTATE))
    ios = layout.read_iconstate(p)
    assert ios["dock"] == ["com.apple.mobilephone", "com.apple.MobileSMS", "com.google.chrome.ios"]
    assert ios["pages"][0][1] == {"folder": "Social", "apps": ["net.whatsapp.WhatsApp", "ph.telegra.Telegraph"]}

    mapping = {
        "com.apple.mobilephone": {"package": "com.google.android.dialer", "label": "Phone"},
        "com.google.chrome.ios": {"package": "com.android.chrome", "label": "Chrome"},
        "com.apple.camera": {"label": "Camera"},
        "net.whatsapp.WhatsApp": {"package": "com.whatsapp", "label": "WhatsApp"},
    }
    android, missing = layout.to_android(ios, mapping)
    assert android["dock"] == ["Phone", "Chrome"]
    assert android["pages"] == [["Camera", {"folder": "Social", "apps": ["WhatsApp"]}]]  # empty page dropped
    assert missing == ["com.apple.MobileSMS", "com.unknown.app", "ph.telegra.Telegraph"]
    assert layout.packages_in(mapping) == ["com.android.chrome", "com.google.android.dialer", "com.whatsapp"]
