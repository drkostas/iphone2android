"""Remove preinstalled apps for the current user, without root.

`pm uninstall --user 0` keeps the app on the system partition, so it can come back with
`cmd package install-existing <package>`. Some system parts refuse and are disabled instead.
"""
from __future__ import annotations

from .adb import Adb

# Never removed, whatever the list says.
PROTECTED = {
    "com.google.android.euicc",  # eSIM
    "com.android.vending",  # Play Store
    "com.google.android.gms",  # Play services
    "com.android.phone",
    "com.android.settings",
    "com.android.systemui",
    "com.google.android.dialer",
    "com.android.dialer",
    "com.google.android.apps.messaging",
    "com.android.mms",
    "com.android.launcher",
}


def remove(adb: Adb, packages: list[str], keep: set[str] = frozenset(), dry_run: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for pkg in packages:
        if pkg in PROTECTED or pkg in keep:
            out[pkg] = "kept"
            continue
        if not adb.installed(pkg):
            out[pkg] = "absent"
            continue
        if dry_run:
            out[pkg] = "would remove"
            continue
        r = adb.shell(f"pm uninstall --user 0 {pkg}")
        if "Success" in r:
            out[pkg] = "removed"
            continue
        r2 = adb.shell(f"pm disable-user --user 0 {pkg}")
        out[pkg] = "disabled" if "disabled" in r2.lower() else f"failed: {r.strip()[:80]}"
    return out


def restore(adb: Adb, package: str) -> bool:
    return "installed" in adb.shell(f"cmd package install-existing {package}").lower()
