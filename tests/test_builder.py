import json

from iphone2android.android.build import Builder

from sim_launcher import SimLauncher

DRAWER = ["Camera", "Photos", "WhatsApp", "WHAT'S UP", "Telegram", "Viber", "Maps", "Uber", "Lime", "Spotify", "Instagram"]

LAYOUT = {
    "pages": [
        ["Camera", {"folder": "Social", "apps": ["WhatsApp", "Telegram", "Viber"]}, "Photos",
         {"widget": ["Spotify"], "size": "medium"}],
        [{"folder": "Travel", "apps": ["Maps", "Uber", "Lime"]}, "WHAT'S UP"],
    ]
}


def quiet():
    return lambda *_: None


def test_full_build_matches_the_layout_and_lists_widgets(tmp_path):
    sim = SimLauncher(DRAWER)
    b = Builder(sim, tmp_path / "state.json", log=quiet())
    b.build(LAYOUT)
    assert b.order_all(LAYOUT)
    assert b.check(LAYOUT) == []
    assert b.todo == [{"page": 1, "widget": ["Spotify"], "size": "medium"}]
    assert not b.problems
    # page 2's items were made on page 1 and carried, because drawer drops land on page 1
    assert ("carry", "Folder:Travel", 1) in sim.gestures and ("carry", "WHAT'S UP", 1) in sim.gestures


def test_exact_drawer_name_beats_substring():
    sim = SimLauncher(["WhatsApp", "WHAT'S UP"])
    b = Builder(sim, log=quiet())
    b.build({"pages": [["WHAT'S UP"]]})
    assert list(sim.grid[0].values()) == ["WHAT'S UP"]


def test_new_folder_is_found_by_position_when_names_collide():
    # A folder called "Social" already exists, and the launcher auto-names the new one "Social" too.
    sim = SimLauncher(["Maps", "Uber", "Lime"], pages=[{(3, 5): "Folder:Social"}])
    sim.folders["Folder:Social"] = ["Old"]
    b = Builder(sim, log=quiet())
    b.build({"pages": [[{"folder": "Travel", "apps": ["Maps", "Uber", "Lime"]}]]})
    assert sim.folders["Folder:Travel"] == ["Maps", "Uber", "Lime"]
    assert sim.folders["Folder:Social"] == ["Old"]  # the existing folder was not renamed


def test_extras_in_a_folder_are_removed_from_inside():
    sim = SimLauncher(["Maps", "Uber", "Lime", "Instagram"], pages=[{(0, 0): "Folder:Travel"}])
    sim.folders["Folder:Travel"] = ["Maps", "Instagram"]
    b = Builder(sim, log=quiet())
    b.fill_folder(0, "Travel", ["Maps", "Uber", "Lime"])
    assert sorted(sim.folders["Folder:Travel"]) == ["Lime", "Maps", "Uber"]


def test_carrying_onto_a_full_page_is_refused_not_merged():
    full = {(c, r): f"App{c}{r}" for c in range(4) for r in range(6)}
    sim = SimLauncher(["Maps", "Uber"], pages=[{}, full])
    b = Builder(sim, log=quiet())
    b.build({"pages": [[], [{"folder": "Travel", "apps": ["Maps", "Uber"]}]]})
    assert any("page 2 is full" in p for p in b.problems)
    assert "Folder:Travel" in sim.grid[0].values()  # left where it was made, not dropped on a folder


def test_order_is_one_swap_per_reading():
    sim = SimLauncher([], pages=[{(0, 0): "C", (1, 0): "A", (2, 0): "Folder:F", (3, 0): "B"}])
    sim.folders["Folder:F"] = ["x"]
    b = Builder(sim, log=quiet())
    assert b.order(0, ["A", "B", "C", "Folder:F"])
    assert [sim.grid[0][(c, 0)] for c in range(4)] == ["A", "B", "C", "Folder:F"]
    assert len([g for g in sim.gestures if g[0] == "swap"]) == 3


def test_order_stops_when_a_swap_makes_a_folder():
    sim = SimLauncher([], pages=[{(0, 0): "B", (1, 0): "A"}])

    def bad_swap(a, b):
        sim.grid[0] = {(0, 0): "Folder:Oops"}
        sim.folders["Folder:Oops"] = ["A", "B"]

    sim.swap = bad_swap
    b = Builder(sim, log=quiet())
    assert b.order(0, ["A", "B"]) is False and "created a folder" in b.problems[0]


def test_an_interrupted_build_continues_without_repeating(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"done": ["p0:Camera"]}))
    sim = SimLauncher(["Camera", "Photos"])
    Builder(sim, state, log=quiet()).build({"pages": [["Camera", "Photos"]]})
    assert list(sim.grid[0].values()) == ["Photos"]
    assert "p0:Photos" in json.loads(state.read_text())["done"]


def test_missing_drawer_app_is_reported():
    sim = SimLauncher(["Camera"])
    b = Builder(sim, log=quiet())
    b.build({"pages": [["Camera", "Gboard"]]})
    assert "not in the drawer: Gboard" in b.problems
