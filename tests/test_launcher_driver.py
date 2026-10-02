"""The real Launcher class, driven against a recording adb, so the gestures sent match the profile."""
from iphone2android.android.launcher import Item, Launcher
from iphone2android.android.profile import load
from iphone2android.android.ui import parse

PROFILE = load("coloros-16")

DUMP = """<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation="0">
<node package="com.android.systemui" class="android.widget.TextView" text="Wi-Fi" content-desc="" clickable="true" bounds="[0,500][300,600]"/>
<node package="com.android.launcher" class="android.appwidget.CustomLauncherAppWidgetHostView" text="" content-desc="Spotify" clickable="false" bounds="[92,277][1180,1052]"/>
<node package="com.android.launcher" class="android.widget.FrameLayout" text="" content-desc="Folder:Travel" clickable="true" bounds="[100,1295][304,1409]"/>
<node package="com.android.launcher" class="android.widget.TextView" text="Travel" content-desc="" clickable="true" bounds="[100,1410][304,1500]"/>
<node package="com.android.launcher" class="android.widget.TextView" text="Camera" content-desc="" clickable="true" bounds="[389,1300][593,1404]"/>
<node package="com.android.launcher" class="android.widget.TextView" text="Phone" content-desc="" clickable="true" bounds="[100,2480][304,2600]"/>
</hierarchy>"""


class RecordingAdb:
    def __init__(self):
        self.calls = []

    def screen_size(self):
        return 1272, 2772

    def shell(self, cmd, timeout=90):
        self.calls.append(cmd)
        if "uiautomator dump" in cmd:
            return DUMP
        if "topResumedActivity" in cmd:
            return "topResumedActivity=ActivityRecord{1 u0 com.android.launcher/.Launcher t1}"
        return ""


def launcher():
    return Launcher(RecordingAdb(), PROFILE, speed=0)


def test_items_ignore_the_shade_and_the_dock_and_map_widget_cells():
    L = launcher()
    items = L.items()
    assert [(i.kind, i.label, i.cell) for i in items if i.kind != "widget"] == [("folder", "Folder:Travel", (0, 3)), ("app", "Camera", (1, 3))]
    widget = [i for i in items if i.kind == "widget"][0]
    assert widget.label == "Widget:Spotify"
    assert set(widget.cells) >= {(0, 0), (3, 0), (0, 1), (3, 1)}  # a 4x2 widget covers the top two rows
    free = L.free_cells(items)
    assert (0, 0) not in free and (0, 3) not in free and (2, 3) in free


def test_overlay_is_detected():
    L = launcher()
    assert L.overlay() == ["com.android.systemui"]
    assert L.launcher_in_front() is False  # the shade is drawn over the launcher


def test_long_press_is_one_shell_with_the_profile_hold():
    L = launcher()
    L.long_press(10, 20)
    assert "input motionevent DOWN 10 20; sleep 1.4; input motionevent UP 10 20" in L.adb.calls


def test_hover_merge_follows_the_profile_steps():
    L = launcher()
    L.hover_merge(Item("Fit", 100, 200, "app", (0, 0)), Item("Folder:Sports", 300, 600, "folder", (1, 1)))
    cmd = [c for c in L.adb.calls if "motionevent" in c][-1]
    assert cmd == ("input motionevent DOWN 100 200; sleep 0.9; input motionevent MOVE 100 200; sleep 0.2; "
                   "input motionevent MOVE 200 400; sleep 0.3; input motionevent MOVE 300 600; sleep 0.5; "
                   "input motionevent MOVE 300 600; sleep 0.8; input motionevent UP 300 600")


def test_move_to_page_holds_once_per_page_and_drops_on_the_chosen_cell():
    L = launcher()
    L.move_to_page(Item("Maps", 202, 1035, "app", (0, 2)), 2, (3, 5))
    cmd = [c for c in L.adb.calls if "motionevent" in c][-1]
    edge = int(1272 * PROFILE["geometry"]["page_edge_right_x"])
    assert cmd.count(f"MOVE {edge} 1035; sleep 0.9") == 2
    dx, dy = L.cell_center(3, 5)
    assert cmd.endswith(f"input motionevent UP {dx} {dy}")
    assert abs(dx - 1069) < 3 and abs(dy - 1986) < 3  # the measured column and row of that cell


def test_page_swipe_uses_250_ms():
    L = launcher()
    L.page_next()
    assert L.adb.calls[-1] == "input swipe 1100 1599 199 1599 250"


def test_drawer_find_prefers_the_exact_name():
    L = launcher()
    results = """<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation="0">
<node package="com.android.launcher" class="android.widget.EditText" text="Search" content-desc="" clickable="true" bounds="[197,2545][1061,2686]"/>
<node package="com.android.launcher" class="android.widget.TextView" text="WhatsApp" content-desc="" clickable="true" bounds="[56,1300][331,1430]"/>
<node package="com.android.launcher" class="android.widget.TextView" text="WHAT'S UP" content-desc="" clickable="true" bounds="[351,1300][626,1430]"/>
</hierarchy>"""
    L.adb.shell = lambda cmd, timeout=90: (L.adb.calls.append(cmd), results if "uiautomator" in cmd else "")[1]
    hit = L.drawer_find("WHAT", want="WHAT'S UP")
    assert hit.label == "WHAT'S UP"
    assert "input keycombination 113 29" in L.adb.calls  # the old query is cleared first
