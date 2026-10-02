import json
import plistlib
import sqlite3
import stat
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from iphone2android import apps, appdata, audit, backup, layout, wallpaper
from iphone2android.android.adb import Adb, DeviceUnavailable
from iphone2android.cli import main


# ---------------------------------------------------------------- apps

@pytest.fixture
def store():
    """A fake Apple lookup and Play Store: search pages and details pages."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/lookup"):
                body = {"results": [{"trackName": "Spotify: Music and Podcasts", "sellerName": "Spotify AB"}]} if "spotify" in self.path else {"results": []}
                data = json.dumps(body).encode()
            elif self.path.startswith("/search"):
                data = b'<a href="/store/apps/details?id=com.fake.clone">x</a><a href="/store/apps/details?id=com.spotify.music">y</a><a href="/store/apps/details?id=com.spotify.music">dup</a>'
            elif "id=com.spotify.music" in self.path:
                data = b"<html><title>Spotify: Music and Podcasts - Apps on Google Play</title></html>"
            elif "id=com.fake.clone" in self.path:
                data = b"<html><title>Music Player Free - Apps on Google Play</title></html>"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    yield {"lookup_url": base + "/lookup?bundleId={bundle}&c={country}",
           "search_url": base + "/search?{query}",
           "details_url": base + "/details?id={package}"}
    s.shutdown()


def test_suggest_picks_only_when_the_titles_agree(store):
    s = apps.suggest("com.spotify.client", **store)
    assert s["name"] == "Spotify: Music and Podcasts" and s["confident"]
    assert s["package"] == "com.spotify.music" and s["label"] == "Spotify"
    assert [c["package"] for c in s["candidates"]] == ["com.fake.clone", "com.spotify.music"]


def test_unknown_apps_stay_for_review_and_builtins_map_directly(store):
    draft = apps.suggest_all(["com.unknown.app", "com.apple.MobileSMS", "com.spotify.client"], log=lambda *_: None, **store)
    assert not draft["com.unknown.app"]["confident"]
    assert draft["com.apple.MobileSMS"]["package"] == "com.google.android.apps.messaging"
    mapping = apps.to_mapping(draft)
    assert set(mapping) == {"com.apple.MobileSMS", "com.spotify.client"}


# ---------------------------------------------------------------- layout widgets

def test_widgets_and_library_are_read_and_mapped(tmp_path):
    p = tmp_path / "IconState.plist"
    p.write_bytes(plistlib.dumps({
        "buttonBar": [],
        "iconLists": [[
            {"gridSize": "small", "elementType": "widget", "containerBundleIdentifier": "com.apple.weather"},
            {"gridSize": "medium", "elements": [
                {"elementType": "widget", "containerBundleIdentifier": "com.apple.weather"},
                {"elementType": "widget", "containerBundleIdentifier": "com.spotify.client"}]},
            "com.spotify.client",
        ]],
        "ignored": ["com.rarely.used"],
    }))
    ios = layout.read_iconstate(p)
    assert ios["pages"][0][0] == {"widget": ["com.apple.weather"], "size": "small"}
    assert ios["pages"][0][1] == {"widget": ["com.apple.weather", "com.spotify.client"], "size": "medium"}
    assert ios["library"] == ["com.rarely.used"]
    android, _ = layout.to_android(ios, {"com.apple.weather": {"label": "Weather"}, "com.spotify.client": {"label": "Spotify"}})
    assert android["pages"][0] == [{"widget": ["Weather"], "size": "small"}, {"widget": ["Weather", "Spotify"], "size": "medium"}, "Spotify"]


# ---------------------------------------------------------------- wallpaper

def make_cpbitmap(width, height, pixel_bgra, align=16):
    stride = -(-width // align) * align
    rows = b"".join(bytes(pixel_bgra) * width + b"\x00" * 4 * (stride - width) for _ in range(height))
    return rows + struct.pack("<iiiii", width, height, 0, 0, 0)


def read_png(data):
    assert data.startswith(b"\x89PNG")
    pos, idat, w = 8, b"", None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        if kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    return w, h, raw


def test_cpbitmap_decodes_to_the_right_pixels():
    w, h, raw = read_png(wallpaper.cpbitmap_to_png(make_cpbitmap(5, 3, (10, 20, 30, 255))))
    assert (w, h) == (5, 3)
    row = raw[: 1 + 5 * 4]
    assert row[0] == 0 and row[1:5] == bytes((30, 20, 10, 255))  # BGRA became RGBA
    assert len(raw) == 3 * (1 + 5 * 4)


# ---------------------------------------------------------------- fake backup for appdata and wallpaper

class FakeDecryptor:
    def getFileDecryptedCopy(self, relativePath=None, manifestEntry=None, targetName=None, targetFolder=None):
        Path(targetFolder, targetName).write_bytes(manifestEntry["manifest"])


def fake_backup(tmp_path, rows):
    m = tmp_path / "Manifest.db"
    con = sqlite3.connect(m)
    con.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    con.executemany("INSERT INTO Files VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return backup.Backup(udid="X", impl=FakeDecryptor(), manifest=m)


def test_wallpaper_candidates_and_extract(tmp_path):
    cp = make_cpbitmap(2, 2, (0, 0, 255, 255))
    b = fake_backup(tmp_path, [
        ("a1", "AppDomain-com.apple.PosterBoard", "Library/Posters/ABC/output.layerStack/portrait-background.HEIC", 1, b"heic"),
        ("a2", "AppDomain-com.apple.PosterBoard", "Library/Posters/ABC/output.layerStack/Contents.json", 1, b"{}"),
        ("a3", "HomeDomain", "Library/SpringBoard/HomeBackground.cpbitmap", 1, cp),
    ])
    got = wallpaper.extract(b, tmp_path / "wp")
    names = sorted(p.name for p in got)
    assert names == ["ABC-portrait-background.HEIC", "HomeBackground.png"]
    assert (tmp_path / "wp" / "HomeBackground.png").read_bytes().startswith(b"\x89PNG")


def test_names_android_refuses_are_made_safe():
    from iphone2android.media import safe_name

    assert safe_name('IMG 10:24:01 "a"|b?.jpg') == "IMG 10_24_01 _a__b_.jpg"


def test_appdata_survey_extract_and_settings(tmp_path):
    settings = plistlib.dumps({"accountEmail": "ada@example.com", "authToken": "SECRET", "serverHost": "eu.example.com"})
    b = fake_backup(tmp_path, [
        ("b1", "AppDomain-com.data.app", "Documents/db.sqlite", 1, b"x" * 30),
        ("b2", "AppDomain-com.data.app", "Library/Caches/huge.db", 1, b"x"),
        ("b3", "AppDomainGroup-group.com.data.app", "Library/Preferences/com.data.app.plist", 1, settings),
        ("b4", "AppDomain-com.empty.app", "Library/Preferences/x.plist", 1, b"y"),
    ])
    sizes = {"b1": 50_000, "b2": 9_000_000, "b3": 100, "b4": 10}
    survey = appdata.survey(b, ["com.data.app", "com.empty.app"], size=lambda r: sizes[r["fileID"]])
    assert [s["bundle"] for s in survey] == ["com.data.app"]
    assert survey[0]["databases"] == [{"path": "Documents/db.sqlite", "bytes": 50_000}]  # the cache is skipped

    r = appdata.extract(b, "com.data.app", tmp_path / "out")
    assert r["files"] == 3 and (tmp_path / "out/com.data.app/Documents/db.sqlite").exists()

    s = appdata.settings_summary(b, "com.data.app")
    assert s["emails"] == ["ada@example.com"]
    assert "authToken" not in s["settings"] and s["settings"]["serverHost"] == "eu.example.com"


# ---------------------------------------------------------------- audit and screenshots against a fake phone

def fake_phone(tmp_path, sms_rows=3, denied_calls=True):
    p = tmp_path / "adb"
    p.write_text(f"""#!/bin/sh
case "$*" in
  *"content://sms"*) echo {sms_rows} ;;
  *"content://mms"*) echo 1 ;;
  *"call_log"*) {'echo "Error: java.lang.SecurityException: Permission Denial"' if denied_calls else 'echo 1'} ;;
  *"contacts/contacts"*) echo 1 ;;
  *"calendar/events"*) echo 0 ;;
  *"pm list packages"*) echo package:com.whatsapp ;;
  *"find /sdcard/DCIM"*) echo /sdcard/DCIM/Camera/IMG_1.HEIC ;;
  *"find"*) ;;
  *"screencap"*) printf '\\211PNG\\r\\n\\032\\nrest' ;;
esac
exit 0
""")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return Adb(binary=str(p))


def test_audit_reports_gaps_and_unknowns(tmp_path):
    from test_convert_layout import make_sources

    ex = tmp_path / "extracted"
    ex.mkdir()
    make_sources(ex)
    b = fake_backup(tmp_path, [
        ("c1", "CameraRollDomain", "Media/DCIM/100APPLE/IMG_1.HEIC", 1, b"p"),
        ("c2", "CameraRollDomain", "Media/DCIM/100APPLE/IMG_2.HEIC", 1, b"p"),
    ])
    r = audit.run(fake_phone(tmp_path, sms_rows=1), ex, {"x": {"package": "com.whatsapp"}, "y": {"package": "com.telegram"}}, b)
    assert r["iphone"]["messages"] == 3 and r["phone"]["messages"] == 2  # 1 SMS + 1 MMS
    assert r["phone"]["calls"] is None  # refused by the phone, not zero
    assert r["gaps"]["messages"] == 1 and "calls" not in r["gaps"]
    assert r["apps"]["missing"] == ["com.telegram"]
    assert r["photos"] == {"camera_roll": 2, "missing_by_name": 1, "examples": ["IMG_2.HEIC"]}


def test_screenshot_is_binary_safe(tmp_path):
    assert fake_phone(tmp_path).screenshot().startswith(b"\x89PNG\r\n\x1a\n")


def test_screenshot_failure_raises(tmp_path):
    p = tmp_path / "adb2"
    p.write_text("#!/bin/sh\necho 'error: no devices' >&2\nexit 1\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    with pytest.raises(DeviceUnavailable):
        Adb(binary=str(p)).screenshot()


# ---------------------------------------------------------------- cli

def test_skill_install_and_json_output(tmp_path, capsys):
    assert main(["--json", "skill", "--dir", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    skill = Path(out["installed"]).read_text()
    assert skill.startswith("---\nname: iphone2android") and "Phase 1. The official transfer" in skill
    assert main(["--json", "--backup-root", str(tmp_path / "none"), "backups"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_accounts_lists_signed_in_accounts(tmp_path):
    from iphone2android import accounts

    db = tmp_path / "Accounts3.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE ZACCOUNTTYPE (Z_PK INTEGER PRIMARY KEY, ZACCOUNTTYPEDESCRIPTION TEXT, ZIDENTIFIER TEXT);
        CREATE TABLE ZACCOUNT (Z_PK INTEGER PRIMARY KEY, ZUSERNAME TEXT, ZACCOUNTDESCRIPTION TEXT, ZACCOUNTTYPE INTEGER);
        INSERT INTO ZACCOUNTTYPE VALUES (1, 'Gmail', 'com.apple.account.Google'), (2, 'Exchange', 'com.apple.account.Exchange');
        INSERT INTO ZACCOUNT VALUES (1, 'ada@gmail.com', 'Gmail', 1), (2, 'ada@gmail.com', 'Gmail', 1),
                                    (3, 'ada@work.example', 'Work', 2), (4, NULL, 'local', NULL);""")
    con.commit()
    con.close()
    got = accounts.read(db)
    assert [(a["username"], a["google"]) for a in got] == [("ada@gmail.com", True), ("ada@work.example", False)]
