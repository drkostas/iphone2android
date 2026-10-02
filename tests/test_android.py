import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from iphone2android.android import debloat, play, ui
from iphone2android.android.adb import Adb
from iphone2android.android.build import Builder

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


class FakeLauncher:
    """A home screen as a list of pages. Positions are (index, page) so a drop can be found again."""

    def __init__(self, drawer):
        self.drawer = set(drawer)
        self.pages = [[]]
        self.folders = {}
        self.renamed = []
        self.drops = []

    def at(self, fx, fy):
        return (-1, -1)  # an empty spot

    def _node(self, label, i):
        return ui.Node(label, i, 0, "FrameLayout", True)

    def icons(self, page):
        return [self._node(lbl, i) for i, lbl in enumerate(self.pages[page])]

    def drawer_search(self, term):
        return ui.Node(term, 999, 999, "TextView", True) if term in self.drawer else None

    def _page_of_drop(self):
        return self.pages[0]

    def drag(self, x1, y1, x2, y2, ms=600):
        page = self.pages[0]
        if x1 == 999:  # from the drawer
            label = self._drawer_label
            if x2 == -1:
                page.append(label)
            else:
                target = page[x2]
                if target.startswith("Folder:"):
                    self.folders[target].append(label)
                else:
                    name = f"Folder:Auto{len(self.folders)}"
                    self.folders[name] = [target, label]
                    page[x2] = name
            return
        page[x1], page[x2] = page[x2], page[x1]  # a swap within the page

    def tap(self, x, y):
        self._open = self.pages[0][x]

    def rename_open_folder(self, name):
        old = self._open
        new = f"Folder:{name}"
        self.folders[new] = self.folders.pop(old)
        self.pages[0][self.pages[0].index(old)] = new
        self.renamed.append(name)
        return True


def builder(drawer):
    fl = FakeLauncher(drawer)
    orig = fl.drawer_search

    def search(term):
        fl._drawer_label = term
        return orig(term)

    fl.drawer_search = search
    return fl, Builder(fl, log=lambda *_: None)


def test_build_places_loose_apps_and_folders(tmp_path):
    fl, b = builder(["Camera", "WhatsApp", "Telegram", "Signal", "Photos"])
    b.state_file = tmp_path / "state.json"
    b.build({"pages": [["Camera", {"folder": "Social", "apps": ["WhatsApp", "Telegram", "Signal"]}, "Photos", "Missing"]]})
    assert fl.pages[0] == ["Camera", "Folder:Social", "Photos"]
    assert fl.folders["Folder:Social"] == ["WhatsApp", "Telegram", "Signal"]
    assert "p0:Folder:Social" in b.state_file.read_text()


def test_an_interrupted_build_continues_without_repeating(tmp_path):
    fl, b = builder(["Camera", "Photos"])
    state = tmp_path / "state.json"
    state.write_text('{"done": ["p0:Camera"]}')
    b2 = Builder(fl, state_file=state, log=lambda *_: None)
    fl.drawer_search = b.l.drawer_search
    b2.build({"pages": [["Camera", "Photos"]]})
    assert fl.pages[0] == ["Photos"]  # Camera was already done, so it is not added again


def test_order_converges_with_one_swap_per_reading():
    fl, b = builder([])
    fl.pages[0] = ["C", "A", "Folder:F", "B"]
    assert b.order(0, ["A", "B", "C", "Folder:F"])
    assert fl.pages[0] == ["A", "B", "C", "Folder:F"]


def test_order_stops_when_a_swap_makes_a_folder():
    fl, b = builder([])
    fl.pages[0] = ["B", "A"]

    def merging_drag(x1, y1, x2, y2, ms=600):
        fl.pages[0] = ["Folder:Oops"]

    fl.drag = merging_drag
    assert b.order(0, ["A", "B"]) is False
