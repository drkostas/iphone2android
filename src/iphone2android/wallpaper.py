"""The iPhone wallpaper, out of the backup and onto the Android phone.

iOS 16 and later keep wallpapers in the PosterBoard app as ordinary images inside `output.layerStack`
folders (a background layer and, for depth effects, a foreground layer). Older versions keep them in
HomeDomain as `HomeBackground.cpbitmap` and `LockBackground.cpbitmap`, Apple's raw BGRA format,
which is converted to PNG here.

Setting a wallpaper is not open to adb, so `set_on_phone` copies the image to the phone and opens the
system's "Set as" screen for it. The last tap is on the phone (or for Claude, through screenshots).
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .android.adb import Adb

IMAGE_EXT = (".heic", ".heif", ".png", ".jpg", ".jpeg")


def candidates(backup) -> list[dict]:
    rows = backup.rows("flags=1 AND domain='AppDomain-com.apple.PosterBoard' AND relativePath LIKE '%output.layerStack%'")
    rows = [r for r in rows if r["relativePath"].lower().endswith(IMAGE_EXT)]
    rows += backup.rows("flags=1 AND relativePath LIKE '%Background.cpbitmap'")
    return rows


def _name(row: dict) -> str:
    rel = row["relativePath"]
    if "output.layerStack" in rel:
        poster = rel.split("/output.layerStack")[0].rsplit("/", 1)[-1]
        return f"{poster}-{rel.rsplit('/', 1)[-1]}"
    return rel.rsplit("/", 1)[-1]


def extract(backup, out: Path, ios_major: int = 17) -> list[Path]:
    """Copy every wallpaper image out. cpbitmap files are converted to PNG."""
    out.mkdir(parents=True, exist_ok=True)
    got = []
    for row in candidates(backup):
        p = backup.copy_entry(row, out, _name(row))
        if p.suffix == ".cpbitmap":
            png = p.with_suffix(".png")
            png.write_bytes(cpbitmap_to_png(p.read_bytes(), ios_major))
            p.unlink()
            p = png
        got.append(p)
    return got


def cpbitmap_to_png(data: bytes, ios_major: int = 17) -> bytes:
    """Decode Apple's cpbitmap: BGRA rows padded to a multiple of 16 pixels (8 before iOS 12, 4 before 10),
    with width and height as little-endian ints 20 and 16 bytes from the end."""
    width = struct.unpack_from("<i", data, len(data) - 20)[0]
    height = struct.unpack_from("<i", data, len(data) - 16)[0]
    align = 16 if ios_major >= 12 else 8 if ios_major >= 10 else 4
    stride = -(-width // align) * align * 4
    rows = []
    for y in range(height):
        line = data[y * stride: y * stride + width * 4]
        rgba = bytearray(len(line))
        rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = line[2::4], line[1::4], line[0::4], line[3::4]
        rows.append(b"\x00" + bytes(rgba))
    return _png(width, height, b"".join(rows))


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def set_on_phone(adb: Adb, image: Path, folder: str = "/sdcard/Pictures/iPhone_Wallpaper") -> str:
    """Copy the image to the phone and open the system screen that sets it as wallpaper."""
    dest = f"{folder}/{image.name}"
    adb.run("shell", "mkdir", "-p", folder)
    adb.run("push", str(image), dest)
    adb.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dest}")
    out = adb.shell(f"content query --uri content://media/external/images/media --projection _id --where \"_display_name='{image.name}'\"")
    ids = [part.split("=", 1)[1] for line in out.splitlines() for part in line.split(", ") if part.startswith("_id=")]
    if not ids:
        return f"copied to {dest}; open it in the gallery and choose Set as wallpaper"
    uri = f"content://media/external/images/media/{ids[-1]}"
    adb.shell(f"am start -a android.intent.action.ATTACH_DATA -d {uri} -t image/* -f 1")
    return f"opened Set as for {dest}; choose the wallpaper app, then home screen, lock screen or both"
