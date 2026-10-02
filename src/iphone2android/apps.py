"""Find the Android app for each iPhone app.

The iPhone side gives bundle ids (com.spotify.client). Apple's public lookup turns a bundle id into
the app's name and developer. The Play Store's own search page then gives candidate packages for that
name. A candidate is picked automatically only when its Play Store title matches the iPhone name;
everything else is left for a person (or Claude) to choose from the candidates.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
ITUNES_LOOKUP = "https://itunes.apple.com/lookup?bundleId={bundle}&country={country}"
PLAY_SEARCH = "https://play.google.com/store/search?{query}"
PLAY_DETAILS = "https://play.google.com/store/apps/details?id={package}&hl=en"

# Apple's own apps are not in the App Store lookup, and most have a Google or system equivalent.
APPLE_BUILTINS = {
    "com.apple.mobilephone": ("Phone", "com.google.android.dialer"),
    "com.apple.MobileSMS": ("Messages", "com.google.android.apps.messaging"),
    "com.apple.mobilesafari": ("Safari", "com.android.chrome"),
    "com.apple.mobilemail": ("Mail", "com.google.android.gm"),
    "com.apple.mobilecal": ("Calendar", "com.google.android.calendar"),
    "com.apple.camera": ("Camera", None),
    "com.apple.mobileslideshow": ("Photos", "com.google.android.apps.photos"),
    "com.apple.Maps": ("Maps", "com.google.android.apps.maps"),
    "com.apple.MobileAddressBook": ("Contacts", "com.google.android.contacts"),
    "com.apple.mobilenotes": ("Notes", "com.google.android.keep"),
    "com.apple.reminders": ("Reminders", "com.google.android.apps.tasks"),
    "com.apple.Preferences": ("Settings", None),
    "com.apple.AppStore": ("App Store", "com.android.vending"),
    "com.apple.weather": ("Weather", None),
    "com.apple.mobiletimer": ("Clock", "com.google.android.deskclock"),
    "com.apple.calculator": ("Calculator", "com.google.android.calculator"),
    "com.apple.Music": ("Music", None),
    "com.apple.Health": ("Health", "com.google.android.apps.healthdata"),
    "com.apple.DocumentsApp": ("Files", "com.google.android.apps.nbu.files"),
    "com.apple.findmy": ("Find My", "com.google.android.apps.adm"),
    "com.apple.Passbook": ("Wallet", "com.google.android.apps.walletnfcrel"),
    "com.apple.VoiceMemos": ("Voice Memos", None),
    "com.apple.compass": ("Compass", None),
    "com.apple.tv": ("TV", None),
    "com.apple.podcasts": ("Podcasts", None),
    "com.apple.shortcuts": ("Shortcuts", None),
    "com.apple.Translate": ("Translate", "com.google.android.apps.translate"),
}


def _get(url: str, timeout: float = 20.0, tries: int = 3) -> str | None:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(2 + attempt * 3)
    return None


def ios_info(bundle: str, country: str = "us", lookup_url: str = ITUNES_LOOKUP) -> dict | None:
    """Name, developer and store link for a bundle id, from Apple's public lookup."""
    if bundle in APPLE_BUILTINS:
        name, _ = APPLE_BUILTINS[bundle]
        return {"name": name, "developer": "Apple", "builtin": True}
    body = _get(lookup_url.format(bundle=urllib.parse.quote(bundle), country=country))
    if not body:
        return None
    results = (json.loads(body) or {}).get("results") or []
    if not results:
        return None
    r = results[0]
    return {"name": r.get("trackName"), "developer": r.get("sellerName") or r.get("artistName"),
            "genre": r.get("primaryGenreName"), "builtin": False}


def play_search(query: str, country: str = "us", search_url: str = PLAY_SEARCH, limit: int = 6) -> list[str]:
    """Package ids the Play Store search page lists for a query, in order."""
    body = _get(search_url.format(query=urllib.parse.urlencode({"q": query, "c": "apps", "gl": country.upper(), "hl": "en"})))
    if not body:
        return []
    out: list[str] = []
    for m in re.finditer(r"/store/apps/details\?id=([A-Za-z0-9_.]+)", body):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out[:limit]


def play_title(package: str, details_url: str = PLAY_DETAILS) -> str | None:
    body = _get(details_url.format(package=package))
    if not body:
        return None
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S)
    if not m:
        return None
    return re.sub(r"\s*-\s*Apps on Google Play\s*$", "", m.group(1).strip())


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.split(r"[:\-–|(]", s)[0]  # "Spotify: Music and Podcasts" -> "spotify"
    return re.sub(r"[^a-z0-9]+", "", s)


def suggest(bundle: str, country: str = "us", **urls) -> dict:
    """One mapping suggestion: the iPhone app, the candidates, and a pick when the titles agree."""
    out = {"bundle": bundle, "name": None, "developer": None, "candidates": [], "package": None, "label": None, "confident": False}
    if bundle in APPLE_BUILTINS:
        name, pkg = APPLE_BUILTINS[bundle]
        out.update(name=name, developer="Apple", package=pkg, label=name, confident=True)
        return out
    info = ios_info(bundle, country, urls.get("lookup_url", ITUNES_LOOKUP))
    if not info or not info.get("name"):
        return out
    out.update(name=info["name"], developer=info.get("developer"))
    want = _norm(info["name"])
    for pkg in play_search(info["name"], country, urls.get("search_url", PLAY_SEARCH)):
        title = play_title(pkg, urls.get("details_url", PLAY_DETAILS))
        out["candidates"].append({"package": pkg, "title": title})
        if title and not out["package"] and _norm(title) == want:
            out.update(package=pkg, label=title.split(":")[0].strip(), confident=True)
    return out


def suggest_all(bundles: list[str], country: str = "us", log=print, **urls) -> dict:
    """A draft mapping for every bundle id. Entries without a confident pick keep their candidates."""
    draft = {}
    for i, b in enumerate(bundles, 1):
        s = suggest(b, country, **urls)
        draft[b] = s
        log(f"[{i}/{len(bundles)}] {b}: " + (f"{s['package']} ({s['label']})" if s["confident"] else f"{len(s['candidates'])} candidates, pick one"))
    return draft


def to_mapping(draft: dict) -> dict:
    """The confident part of a draft, in the mapping format the other commands read."""
    return {b: {"package": s["package"], "label": s["label"]} for b, s in draft.items() if s.get("confident") and s.get("label")}
