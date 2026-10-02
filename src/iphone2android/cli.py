"""iphone2android command line. Every command that reports something takes --json, for Claude."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, accounts, apps, appdata, audit, backup, convert, layout, media, wallpaper
from .android import debloat, play, ui
from .android.adb import Adb, DeviceUnavailable

SKILL_SRC = Path(__file__).parent / "skill" / "SKILL.md"


def _emit(args, data, text=None) -> None:
    if args.json:
        print(json.dumps(data, indent=1, ensure_ascii=False, default=str))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(data, indent=1, ensure_ascii=False, default=str))


def _root(args) -> Path:
    return Path(args.backup_root) if args.backup_root else backup.DEFAULT_ROOT


def _udid(args) -> str:
    if args.udid:
        return args.udid
    found = backup.backups(_root(args))
    if len(found) != 1:
        sys.exit(f"found {len(found)} backups; pass --udid (see `iphone2android backups`)")
    return found[0]["udid"]


def _open(args) -> backup.Backup:
    return backup.open_backup(_udid(args), backup.password_from_env_or_prompt(), Path(args.work), _root(args))


# ---------------------------------------------------------------- iPhone side

def cmd_backups(args) -> int:
    found = backup.backups(_root(args))
    _emit(args, found, "\n".join(f"{b['udid']}  {b['name']} ({b['model']}, iOS {b['ios']})  {b['apps']} apps  {b['date']}" for b in found) or "no backups found")
    return 0


def cmd_apps(args) -> int:
    bundles = sorted(backup.installed_apps(_udid(args), _root(args)))
    if not args.names:
        _emit(args, bundles, "\n".join(bundles))
        return 0
    out = []
    for b in bundles:
        info = apps.ios_info(b) or {}
        out.append({"bundle": b, "name": info.get("name"), "developer": info.get("developer")})
    _emit(args, out, "\n".join(f"{o['bundle']:45s} {o['name'] or '?'}" for o in out))
    return 0


def cmd_extract(args) -> int:
    b = _open(args)
    out = Path(args.work)
    res = [{"what": label, "import_with": dest, "file": str(p) if p else None} for label, dest, p in backup.extract_known(b, out)]
    if args.inventory:
        (out / "inventory.json").write_text(json.dumps(b.inventory(), indent=1))
    _emit(args, res, "\n".join(f"{'ok' if r['file'] else '--'}  {r['what']:20s} {('-> ' + r['import_with']) if r['file'] else 'not in this backup'}" for r in res))
    return 0


def cmd_convert(args) -> int:
    res = [{"what": n, "count": c, "error": e} for n, c, e in convert.convert_all(Path(args.work), Path(args.out))]
    _emit(args, res, "\n".join(f"{r['what']:10s} {r['count'] if r['count'] is not None else 'FAILED ' + r['error']}" for r in res))
    return 0


def cmd_layout(args) -> int:
    ios = layout.read_iconstate(Path(args.iconstate))
    if not args.mapping:
        _emit(args, ios)
        return 0
    android, missing = layout.to_android(ios, layout.load_json(Path(args.mapping)))
    _emit(args, android)
    if missing:
        print(f"no Android mapping for {len(missing)} apps: " + ", ".join(missing), file=sys.stderr)
    return 0


def cmd_media(args) -> int:
    b = _open(args)
    adb = Adb(args.serial)
    res = {}
    for name in args.sets:
        domain, prefix, dest = media.SETS[name]
        res[name] = media.push_set(b, adb, domain, prefix, dest, log=lambda *_: None if args.json else print(*_))
    _emit(args, res, "\n".join(f"{k}: {v['copied']}/{v['files']} files, {len(v['failed'])} failed" for k, v in res.items()))
    return 0


def cmd_wallpaper(args) -> int:
    if args.action == "set":
        _emit(args, {"result": wallpaper.set_on_phone(Adb(args.serial), Path(args.image))}, None)
        return 0
    got = wallpaper.extract(_open(args), Path(args.out), args.ios)
    _emit(args, [str(p) for p in got], "\n".join(str(p) for p in got) or "no wallpaper found in the backup")
    return 0


def cmd_appdata(args) -> int:
    if args.action == "survey":
        bundles = backup.installed_apps(_udid(args), _root(args))
        res = appdata.survey(_open(args), bundles)
        _emit(args, res, "\n".join(f"{r['total_bytes'] / 1e6:9.1f} MB  {r['bundle']}" for r in res))
        return 0
    b = _open(args)
    out = []
    for bundle in args.bundles:
        if args.action == "settings":
            out.append(appdata.settings_summary(b, bundle))
            continue
        r = appdata.extract(b, bundle, Path(args.out))
        if args.push:
            r["pushed"] = appdata.push(Adb(args.serial), Path(r["folder"]))
        out.append(r)
    _emit(args, out)
    return 0


def cmd_accounts(args) -> int:
    res = accounts.read(Path(args.work) / "Accounts3.sqlite")
    _emit(args, res, "\n".join(f"{'G ' if a['google'] else '  '}{a['username']:40s} {a['type'] or a['type_id'] or ''}" for a in res))
    return 0


# ---------------------------------------------------------------- apps

def cmd_find_app(args) -> int:
    res = [{"package": p, "title": apps.play_title(p)} for p in apps.play_search(args.name, args.country)]
    _emit(args, res, "\n".join(f"{r['package']:45s} {r['title'] or ''}" for r in res) or "nothing found")
    return 0


def cmd_suggest(args) -> int:
    bundles = sorted(backup.installed_apps(_udid(args), _root(args)))
    draft = apps.suggest_all(bundles, args.country, log=(lambda *_: None) if args.json else print)
    Path(args.draft).write_text(json.dumps(draft, indent=1, ensure_ascii=False))
    mapping = apps.to_mapping(draft)
    Path(args.mapping).write_text(json.dumps(mapping, indent=1, ensure_ascii=False))
    unsure = [b for b, s in draft.items() if not s.get("confident")]
    _emit(args, {"mapped": len(mapping), "to_review": unsure, "draft": args.draft, "mapping": args.mapping},
          f"{len(mapping)} mapped into {args.mapping}; {len(unsure)} need a choice, with candidates in {args.draft}")
    return 0


def cmd_verify(args) -> int:
    mapping = layout.load_json(Path(args.mapping))
    res = [{"bundle": b, "package": m["package"], "listed": play.listed(m["package"])} for b, m in sorted(mapping.items()) if m.get("package")]
    _emit(args, res, "\n".join(f"{'ok  ' if r['listed'] else 'MISSING' if r['listed'] is False else 'ERROR'}  {r['package']:45s} {r['bundle']}" for r in res))
    return 1 if any(r["listed"] is not True for r in res) else 0


def cmd_install(args) -> int:
    adb = Adb(args.serial)
    packages = layout.packages_in(layout.load_json(Path(args.mapping))) if args.mapping else args.packages
    res = []
    for i, pkg in enumerate(packages, 1):
        r = play.install(adb, pkg)
        res.append({"package": pkg, "result": r})
        if not args.json:
            print(f"[{i}/{len(packages)}] {pkg}: {r}", flush=True)
    if args.json:
        _emit(args, res)
    return 1 if any(r["result"] in ("no-button", "timeout") for r in res) else 0


def cmd_debloat(args) -> int:
    adb = Adb(args.serial)
    packages = [p.strip() for p in Path(args.list).read_text().splitlines() if p.strip() and not p.startswith("#")]
    keep = set(layout.packages_in(layout.load_json(Path(args.keep_mapping)))) if args.keep_mapping else set()
    res = debloat.remove(adb, packages, keep, dry_run=args.dry_run)
    _emit(args, res, "\n".join(f"{r:14s} {p}" for p, r in res.items()))
    return 0


# ---------------------------------------------------------------- checking

def cmd_audit(args) -> int:
    mapping = layout.load_json(Path(args.mapping)) if args.mapping else None
    b = _open(args) if args.photos else None
    _emit(args, audit.run(Adb(args.serial), Path(args.work), mapping, b))
    return 0


def cmd_screenshot(args) -> int:
    from .android.adb import png_is_black

    data = Adb(args.serial).screenshot()
    Path(args.out).write_bytes(data)
    if png_is_black(data):
        _emit(args, {"file": args.out, "black": True, "error": "the screen is off or locked; wake and unlock the phone"},
              f"{args.out}: the picture is all black, so the screen is off or locked")
        return 5
    _emit(args, {"file": args.out, "black": False}, args.out)
    return 0


def cmd_screen(args) -> int:
    nodes = ui.dump(Adb(args.serial))
    _emit(args, [n.__dict__ for n in nodes], "\n".join(f"{n.label}  ({n.x},{n.y}) {n.cls}{' clickable' if n.clickable else ''}" for n in nodes))
    return 0


# ---------------------------------------------------------------- home screen

USER_PROFILES = Path("~/.config/iphone2android/profiles").expanduser()


def _launcher(args):
    from .android.launcher import Launcher
    from .android.profile import detect, load

    adb = Adb(args.serial)
    prof = load(args.profile) if getattr(args, "profile", None) else detect(adb, USER_PROFILES)
    return Launcher(adb, prof)


def _builder(args):
    from .android.build import Builder

    return Builder(_launcher(args), Path(args.state) if getattr(args, "state", None) else None,
                   log=(lambda *_: None) if args.json else print)


def cmd_build(args) -> int:
    lay = layout.load_json(Path(args.layout))
    b = _builder(args)
    if b.l.p.get("uncalibrated"):
        print("this launcher has no calibrated profile; calibrate it first (see the skill), or pass --profile", file=sys.stderr)
        if not args.force:
            return 4
    if not b.l.launcher_in_front():
        b.l.home()
    b.l.set_autofill(False)
    b.build(lay)
    ordered = b.order_all(lay)
    diffs = b.check(lay)
    if args.autofill and not diffs:
        b.l.set_autofill(True)
        diffs = b.check(lay)  # autofill packed the grid correctly once and scrambled it once (#3063)
    _emit(args, {"ordered": ordered, "differences": diffs, "problems": b.problems, "widgets_to_place": b.todo},
          "\n".join([f"ordered: {ordered}", *[f"diff: {d}" for d in diffs], *[f"problem: {p}" for p in b.problems],
                     *[f"widget to place: page {w['page']} {w['widget']} ({w['size']})" for w in b.todo]]))
    return 0 if ordered and not diffs else 1


def cmd_order(args) -> int:
    b = _builder(args)
    ok = b.order_all(layout.load_json(Path(args.layout)))
    _emit(args, {"ordered": ok, "problems": b.problems}, f"ordered: {ok}")
    return 0 if ok else 1


def cmd_check(args) -> int:
    diffs = _builder(args).check(layout.load_json(Path(args.layout)))
    _emit(args, {"differences": diffs}, "\n".join(diffs) or "the home screen matches the layout")
    return 0 if not diffs else 1


def cmd_snapshot(args) -> int:
    L = _launcher(args)
    pages = L.pages()
    out = {"dock": L.dock(), "pages": []}
    for p, items in enumerate(pages):
        page = []
        for i in items:
            entry = {"label": i.label, "kind": i.kind, "cell": list(i.cell)}
            if i.kind == "folder":
                entry["apps"] = L.open_folder(p, i.label)
            if i.cells:
                entry["cells"] = [list(c) for c in i.cells]
            page.append(entry)
        out["pages"].append(page)
    L.home()
    _emit(args, out)
    return 0


def cmd_launcher(args) -> int:
    from .android.profile import available, detect, launcher_package

    if args.action == "profiles":
        names = list(available()) + sorted(p.stem for p in USER_PROFILES.glob("*.json"))
        _emit(args, names, "\n".join(names))
        return 0
    if args.action == "drawer":
        L = _launcher(args)
        L.drawer_find(args.file or "")
        dock_top = L.h * L.p["geometry"]["dock_top"]
        names = [n.label for n in L.own(L.dump()) if n.cls == "TextView" and n.clickable and n.y < dock_top]
        L.home()
        _emit(args, names, "\n".join(names) or "no results")
        return 0
    if args.action == "save-profile":
        src = json.loads(Path(args.file).read_text())
        for key in ("name", "match", "grid", "geometry", "timing", "gestures", "labels"):
            if key not in src:
                sys.exit(f"profile is missing {key!r}")
        USER_PROFILES.mkdir(parents=True, exist_ok=True)
        dest = USER_PROFILES / f"{src['name']}.json"
        dest.write_text(json.dumps(src, indent=2, ensure_ascii=False))
        _emit(args, {"saved": str(dest)}, f"saved {dest}")
        return 0
    # probe: read-only facts for calibration
    adb = Adb(args.serial)
    from .android.launcher import Launcher

    prof = detect(adb, USER_PROFILES)
    L = Launcher(adb, prof)
    nodes = L.dump(allow_empty=True)
    own = L.own(nodes)
    xs = sorted({n.x for n in own if n.clickable and n.y < L.h * prof["geometry"]["dock_top"]})
    ys = sorted({n.y for n in own if n.clickable and n.label.startswith(prof["labels"]["folder_prefix"])} or
                {n.y for n in own if n.clickable and n.y < L.h * prof["geometry"]["dock_top"]})
    facts = {
        "launcher_package": launcher_package(adb),
        "profile": prof["name"], "uncalibrated": bool(prof.get("uncalibrated")),
        "screen": [L.w, L.h],
        "density": adb.shell("wm density").strip().splitlines(),
        "android": adb.shell("getprop ro.build.version.release").strip(),
        "rom": {k: adb.shell(f"getprop {k}").strip() for k in ("ro.build.version.oplusrom", "ro.build.display.id", "ro.miui.ui.version.name", "ro.build.version.oneui")},
        "grid_setting": adb.shell("settings get secure launcher_card_size_info").strip()[:300],
        "launcher_in_front": L.launcher_in_front(),
        "overlay": L.overlay(),
        "icon_x": xs, "icon_y": ys,
        "items": [{"label": i.label, "kind": i.kind, "cell": list(i.cell), "x": i.x, "y": i.y} for i in L.items(nodes)],
    }
    _emit(args, facts)
    return 0


def cmd_autofill(args) -> int:
    _emit(args, {"autofill": _launcher(args).set_autofill(args.state == "on")}, None)
    return 0


def cmd_skill(args) -> int:
    dest = Path(args.dir).expanduser() / "iphone2android"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL_SRC, dest / "SKILL.md")
    _emit(args, {"installed": str(dest / "SKILL.md")}, f"installed {dest / 'SKILL.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iphone2android", description="Move from an iPhone to an Android phone.")
    p.add_argument("--version", action="version", version=f"iphone2android {__version__}")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.add_argument("--backup-root", help="folder that holds the backups (default: the Finder location on macOS)")
    p.add_argument("--udid", help="which backup (default: the only one)")
    p.add_argument("--work", default="extracted", help="where decrypted files go (default: ./extracted)")
    p.add_argument("--serial", help="adb serial of the phone, when more than one is connected")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backups", help="list the backups on this computer").set_defaults(fn=cmd_backups)
    s = sub.add_parser("apps", help="bundle ids of the apps in a backup (no password needed)")
    s.add_argument("--names", action="store_true", help="also look up each app's name")
    s.set_defaults(fn=cmd_apps)

    s = sub.add_parser("extract", help="decrypt the backup and copy out the useful databases")
    s.add_argument("--inventory", action="store_true", help="also write files and bytes per domain")
    s.set_defaults(fn=cmd_extract)

    s = sub.add_parser("convert", help="turn the extracted databases into Android and Google formats")
    s.add_argument("--out", default="android-import")
    s.set_defaults(fn=cmd_convert)

    s = sub.add_parser("layout", help="read IconState.plist; with --mapping, write an Android layout")
    s.add_argument("iconstate")
    s.add_argument("--mapping")
    s.set_defaults(fn=cmd_layout)

    s = sub.add_parser("media", help="copy media from the backup to the phone over adb")
    s.add_argument("sets", nargs="+", choices=sorted(media.SETS))
    s.set_defaults(fn=cmd_media)

    s = sub.add_parser("wallpaper", help="extract the iPhone wallpaper, or set an image on the phone")
    s.add_argument("action", choices=["extract", "set"])
    s.add_argument("image", nargs="?", help="with set: the image to use")
    s.add_argument("--out", default="wallpaper")
    s.add_argument("--ios", type=int, default=17, help="iOS major version of the backup, for old cpbitmap files")
    s.set_defaults(fn=cmd_wallpaper)

    s = sub.add_parser("appdata", help="find, copy or read the local data of iPhone apps")
    s.add_argument("action", choices=["survey", "extract", "settings"])
    s.add_argument("bundles", nargs="*")
    s.add_argument("--out", default="appdata")
    s.add_argument("--push", action="store_true", help="with extract: also copy to the phone")
    s.set_defaults(fn=cmd_appdata)

    sub.add_parser("accounts", help="the accounts the iPhone was signed in to (after extract)").set_defaults(fn=cmd_accounts)

    s = sub.add_parser("find-app", help="search the Play Store for an app by name")
    s.add_argument("name")
    s.add_argument("--country", default="us")
    s.set_defaults(fn=cmd_find_app)

    s = sub.add_parser("suggest", help="draft a mapping for every app in the backup")
    s.add_argument("--country", default="us")
    s.add_argument("--draft", default="mapping.draft.json")
    s.add_argument("--mapping", default="mapping.json")
    s.set_defaults(fn=cmd_suggest)

    s = sub.add_parser("verify", help="check every package in a mapping file exists on the Play Store")
    s.add_argument("mapping")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("install", help="install free apps through the Play Store app")
    s.add_argument("packages", nargs="*")
    s.add_argument("--mapping", help="install every package in a mapping file")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("debloat", help="remove preinstalled apps listed in a file (reversible)")
    s.add_argument("list")
    s.add_argument("--keep-mapping", help="never remove a package that appears in this mapping file")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_debloat)

    s = sub.add_parser("audit", help="compare what the iPhone had with what the phone has")
    s.add_argument("--mapping", help="also check which mapped apps are not installed")
    s.add_argument("--photos", action="store_true", help="also compare camera roll file names (needs the backup)")
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("screenshot", help="save a screenshot of the phone")
    s.add_argument("out", nargs="?", default="screen.png")
    s.set_defaults(fn=cmd_screenshot)
    sub.add_parser("screen", help="list what is on the phone's screen").set_defaults(fn=cmd_screen)

    for name, fn, text in (("build", cmd_build, "build the home screen from a layout file"),
                           ("order", cmd_order, "put each page of the home screen in the layout's order"),
                           ("check", cmd_check, "compare the home screen and its folders with a layout file")):
        s = sub.add_parser(name, help=text)
        s.add_argument("layout")
        s.add_argument("--state", help="progress file, so an interrupted build continues")
        s.add_argument("--profile", help="launcher profile name or JSON file (default: detected)")
        if name == "build":
            s.add_argument("--autofill", action="store_true", help="turn Icon autofill on at the end to pack the grid")
            s.add_argument("--force", action="store_true", help="build even with an uncalibrated profile")
        s.set_defaults(fn=fn)

    s = sub.add_parser("snapshot", help="read every home screen page and folder into JSON")
    s.add_argument("--profile")
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("launcher", help="launcher profiles: probe this phone, list profiles, save a calibrated one")
    s.add_argument("action", choices=["probe", "profiles", "save-profile", "drawer"])
    s.add_argument("file", nargs="?", help="with save-profile: the profile JSON; with drawer: the search term")
    s.set_defaults(fn=cmd_launcher)

    s = sub.add_parser("autofill", help="turn the launcher's Icon autofill on or off")
    s.add_argument("state", choices=["on", "off"])
    s.set_defaults(fn=cmd_autofill)

    s = sub.add_parser("skill", help="install the Claude Code skill that runs the whole migration")
    s.add_argument("--dir", default="~/.claude/skills")
    s.set_defaults(fn=cmd_skill)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except DeviceUnavailable as e:
        print(f"the phone did not answer adb: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
