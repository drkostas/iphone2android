import plistlib
import sqlite3
import stat

from iphone2android import backup, media
from iphone2android.android.adb import Adb


def manifest(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    rows = [
        ("aaa111", "HomeDomain", "Library/SMS/sms.db", 1, b"blob-sms"),
        ("bbb222", "AppDomain-com.other", "Library/SMS/sms.db", 1, b"blob-other"),  # same path, other domain
        ("ccc333", "CameraRollDomain", "Media/DCIM/100APPLE/IMG_1.HEIC", 1, b"b1"),
        ("ddd444", "CameraRollDomain", "Media/DCIM/101APPLE/IMG_1.HEIC", 1, b"b2"),  # same name, other folder
        ("eee555", "CameraRollDomain", "Media/DCIM/100APPLE/notes.txt", 1, b"b3"),  # not media
        ("fff666", "CameraRollDomain", "Media/DCIM", 2, b"dir"),  # a folder
    ]
    con.executemany("INSERT INTO Files VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()


class FakeDecryptor:
    def __init__(self):
        self.calls = []

    def getFileDecryptedCopy(self, relativePath=None, manifestEntry=None, targetName=None, targetFolder=None):
        self.calls.append(manifestEntry)
        open(f"{targetFolder}/{targetName}", "wb").write(manifestEntry["manifest"] + b"-decrypted")


def make(tmp_path):
    m = tmp_path / "Manifest.db"
    manifest(m)
    return backup.Backup(udid="X", impl=FakeDecryptor(), manifest=m)


def test_copy_looks_up_by_domain_and_path(tmp_path):
    b = make(tmp_path)
    p = b.copy("HomeDomain", "Library/SMS/sms.db", tmp_path / "out", "sms.db")
    assert p.read_bytes() == b"blob-sms-decrypted"
    assert b.impl.calls[0]["manifest"] == b"blob-sms" and "file" not in b.impl.calls[0]
    assert b.copy("HomeDomain", "missing", tmp_path / "out", "x") is None


def test_backups_reads_info_plist_without_a_password(tmp_path):
    d = tmp_path / "00000000-TEST"
    d.mkdir()
    (d / "Info.plist").write_bytes(plistlib.dumps({"Device Name": "Phone", "Product Type": "iPhone15,2",
                                                   "Product Version": "18.0", "Installed Applications": ["a", "b"]}))
    found = backup.backups(tmp_path)
    assert found[0]["udid"] == "00000000-TEST" and found[0]["apps"] == 2
    assert backup.installed_apps("00000000-TEST", tmp_path) == ["a", "b"]


def test_push_set_batches_renames_clashes_and_skips_non_media(tmp_path, monkeypatch):
    log = tmp_path / "adb.log"
    fake = tmp_path / "adb"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\ncase "$*" in *push*) ls "$2" >> {log} ;; esac\nexit 0\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    b = make(tmp_path)
    r = media.push_set(b, Adb(binary=str(fake)), "CameraRollDomain", "Media/DCIM/", "/sdcard/DCIM/iPhone", batch=10, log=lambda *_: None)
    assert r["files"] == 2 and r["copied"] == 2 and not r["failed"]
    text = log.read_text()
    assert "IMG_1.HEIC" in text and "IMG_1_ddd444.HEIC" in text
    assert "notes.txt" not in text
