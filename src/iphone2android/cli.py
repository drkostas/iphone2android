"""iphone2android command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, backup, convert, layout, media
from .android import debloat, play
from .android.adb import Adb


def _open(args) -> backup.Backup:
    udid = args.udid or _only_backup(args)
    return backup.open_backup(udid, backup.password_from_env_or_prompt(), Path(args.work), _root(args))


def _root(args) -> Path:
    return Path(args.backup_root) if args.backup_root else backup.DEFAULT_ROOT


def _only_backup(args) -> str:
    found = backup.backups(_root(args))
    if len(found) != 1:
        sys.exit(f"found {len(found)} backups; pass --udid (see `iphone2android backups`)")
    return found[0]["udid"]


def cmd_backups(args) -> int:
    for b in backup.backups(_root(args)):
        print(f"{b['udid']}  {b['name']} ({b['model']}, iOS {b['ios']})  {b['apps']} apps  {b['date']}")
    return 0


def cmd_apps(args) -> int:
    for a in sorted(backup.installed_apps(args.udid or _only_backup(args), _root(args))):
        print(a)
    return 0


def cmd_extract(args) -> int:
    b = _open(args)
    out = Path(args.work)
    for label, dest, path in backup.extract_known(b, out):
        print(f"{'ok' if path else '--'}  {label:20s} {('-> ' + dest) if path else 'not in this backup'}")
    if args.inventory:
        (out / "inventory.json").write_text(json.dumps(b.inventory(), indent=1))
        print(f"inventory written to {out / 'inventory.json'}")
    return 0


def cmd_convert(args) -> int:
    for name, n, err in convert.convert_all(Path(args.work), Path(args.out)):
        print(f"{name:10s} {n if n is not None else 'FAILED ' + err}")
    return 0


def cmd_layout(args) -> int:
    ios = layout.read_iconstate(Path(args.iconstate))
    if not args.mapping:
        print(json.dumps(ios, indent=1, ensure_ascii=False))
        return 0
    android, missing = layout.to_android(ios, layout.load_json(Path(args.mapping)))
    print(json.dumps(android, indent=1, ensure_ascii=False))
    if missing:
        print(f"no Android mapping for {len(missing)} apps: " + ", ".join(missing), file=sys.stderr)
    return 0


def cmd_media(args) -> int:
    b = _open(args)
    adb = Adb(args.serial)
    for name in args.sets:
        domain, prefix, dest = media.SETS[name]
        print(f"{name} -> {dest}")
        r = media.push_set(b, adb, domain, prefix, dest)
        print(f"  done: {r['copied']}/{r['files']} files, {len(r['failed'])} failed")
    return 0


def cmd_verify(args) -> int:
    mapping = layout.load_json(Path(args.mapping))
    bad = 0
    for bundle, m in sorted(mapping.items()):
        pkg = m.get("package")
        if not pkg:
            continue
        ok = play.listed(pkg)
        bad += ok is not True
        print(f"{'ok  ' if ok else 'MISSING' if ok is False else 'ERROR'}  {pkg:45s} {bundle}")
    return 1 if bad else 0


def cmd_install(args) -> int:
    adb = Adb(args.serial)
    packages = layout.packages_in(layout.load_json(Path(args.mapping))) if args.mapping else args.packages
    failed = 0
    for i, pkg in enumerate(packages, 1):
        r = play.install(adb, pkg)
        failed += r in ("no-button", "timeout")
        print(f"[{i}/{len(packages)}] {pkg}: {r}", flush=True)
    return 1 if failed else 0


def cmd_debloat(args) -> int:
    adb = Adb(args.serial)
    packages = [p.strip() for p in Path(args.list).read_text().splitlines() if p.strip() and not p.startswith("#")]
    keep = set(layout.packages_in(layout.load_json(Path(args.keep_mapping)))) if args.keep_mapping else set()
    for pkg, r in debloat.remove(adb, packages, keep, dry_run=args.dry_run).items():
        print(f"{r:14s} {pkg}")
    return 0


def _builder(args):
    from .android.build import Builder
    from .android.launcher import Launcher

    return Builder(Launcher(Adb(args.serial)), Path(args.state) if args.state else None)


def cmd_build(args) -> int:
    lay = layout.load_json(Path(args.layout))
    b = _builder(args)
    b.l.set_autofill(False)
    b.build(lay)
    ok = b.order_all(lay)
    if args.autofill:
        b.l.set_autofill(True)
    return 0 if ok else 1


def cmd_order(args) -> int:
    return 0 if _builder(args).order_all(layout.load_json(Path(args.layout))) else 1


def cmd_autofill(args) -> int:
    from .android.launcher import Launcher

    print(Launcher(Adb(args.serial)).set_autofill(args.state == "on"))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iphone2android", description="Move from an iPhone to an Android phone.")
    p.add_argument("--version", action="version", version=f"iphone2android {__version__}")
    p.add_argument("--backup-root", help="folder that holds the backups (default: the Finder location on macOS)")
    p.add_argument("--udid", help="which backup (default: the only one)")
    p.add_argument("--work", default="extracted", help="where decrypted files go (default: ./extracted)")
    p.add_argument("--serial", help="adb serial of the phone, when more than one is connected")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backups", help="list the backups on this computer").set_defaults(fn=cmd_backups)
    sub.add_parser("apps", help="bundle ids of the apps in a backup (no password needed)").set_defaults(fn=cmd_apps)

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

    for name, fn, text in (("build", cmd_build, "build the home screen from a layout file"),
                           ("order", cmd_order, "put each page of the home screen in the layout's order")):
        s = sub.add_parser(name, help=text)
        s.add_argument("layout")
        s.add_argument("--state", help="progress file, so an interrupted build continues")
        if name == "build":
            s.add_argument("--autofill", action="store_true", help="turn Icon autofill on at the end to pack the grid")
        s.set_defaults(fn=fn)

    s = sub.add_parser("autofill", help="turn the launcher's Icon autofill on or off")
    s.add_argument("state", choices=["on", "off"])
    s.set_defaults(fn=cmd_autofill)

    args = p.parse_args(argv)
    from .android.adb import DeviceUnavailable

    try:
        return args.fn(args)
    except DeviceUnavailable as e:
        print(f"the phone did not answer adb: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
