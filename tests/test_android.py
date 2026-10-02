import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from iphone2android.android import debloat, play, ui
from iphone2android.android.adb import Adb

DUMP = """<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation="0">
<node text="" content-desc="Folder:Social" class="android.widget.FrameLayout" clickable="true" bounds="[100,200][300,400]"/>
<node text="Social" content-desc="" class="android.widget.TextView" clickable="true" bounds="[100,400][300,450]"/>
<node text="Install" content-desc="" class="android.widget.Button" clickable="true" bounds="[10,20][30,40]"/>
<node text="" content-desc="" class="android.view.View" clickable="false" bounds="[0,0][1,1]"/>
</hierarchy>"""


def test_ui_parse():
    nodes = ui.parse(DUMP)
    assert [n.label for n in nodes] == ["Folder:Social", "Social", "Install"]
    assert nodes[0].folder and (nodes[0].x, nodes[0].y) == (200, 300)
    assert ui.parse("not xml") == []


def fake_adb(tmp_path, installed=("com.present",), uninstall="Success", name="a"):
    (tmp_path / name).mkdir(exist_ok=True)
    log = tmp_path / name / "adb.log"
    p = tmp_path / name / "adb"
    pkgs = "".join(f"echo package:{x}; " for x in installed)
    p.write_text(f"""#!/bin/sh
echo "$@" >> {log}
case "$*" in
  *"pm list packages"*) {pkgs} ;;
  *"pm uninstall"*) echo "{uninstall}" ;;
  *"pm disable-user"*) echo "Package x new state: disabled-user" ;;
  *"wm size"*) echo "Physical size: 1264x2780" ;;
esac
exit 0
""")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return Adb(binary=str(p)), log


def test_adb_closes_stdin_and_reads_state(tmp_path):
    adb, _ = fake_adb(tmp_path)
    assert adb.installed("com.present") and not adb.installed("com.pres")
    assert adb.screen_size() == (1264, 2780)


def test_an_unreachable_phone_raises_instead_of_reading_empty(tmp_path):
    import pytest
    from iphone2android.android.adb import DeviceUnavailable

    p = tmp_path / "adb"
    p.write_text("#!/bin/sh\necho \"adb: device '1.2.3.4:5555' not found\" >&2\nexit 1\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    adb = Adb(binary=str(p))
    with pytest.raises(DeviceUnavailable):
        adb.installed("com.whatsapp")
    with pytest.raises(DeviceUnavailable):
        adb.screen_size()


def test_debloat_protects_and_falls_back(tmp_path):
    adb, log = fake_adb(tmp_path, installed=("com.bloat", "com.android.vending", "com.mine"))
    r = debloat.remove(adb, ["com.bloat", "com.android.vending", "com.mine", "com.gone"], keep={"com.mine"})
    assert r == {"com.bloat": "removed", "com.android.vending": "kept", "com.mine": "kept", "com.gone": "absent"}
    adb2, _ = fake_adb(tmp_path, installed=("com.sys",), uninstall="Failure [DELETE_FAILED_INTERNAL_ERROR]", name="b")
    assert debloat.remove(adb2, ["com.sys"]) == {"com.sys": "disabled"}
    assert debloat.remove(adb, ["com.bloat"], dry_run=True) == {"com.bloat": "would remove"}


def test_play_listing_check():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if "id=real" in self.path else 404)
            self.end_headers()

        def log_message(self, *_):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{s.server_address[1]}/store?id={{package}}"
    assert play.listed("real", url) is True
    assert play.listed("fake", url) is False
    s.shutdown()
    assert play.listed("x", "http://127.0.0.1:1/?id={package}") is None
