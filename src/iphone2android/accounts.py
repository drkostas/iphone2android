"""The accounts the iPhone was signed in to (Google, Exchange, iCloud and others), from Accounts3.sqlite.

This is the reliable list of accounts to add on Android. Searching app data for email addresses
instead finds other people's addresses and typos. The output holds your addresses, so keep it local.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def read(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """SELECT a.ZUSERNAME, a.ZACCOUNTDESCRIPTION, t.ZACCOUNTTYPEDESCRIPTION, t.ZIDENTIFIER
               FROM ZACCOUNT a LEFT JOIN ZACCOUNTTYPE t ON a.ZACCOUNTTYPE = t.Z_PK"""
        ).fetchall()
    finally:
        con.close()
    out = []
    for user, desc, type_desc, ident in rows:
        if not user:
            continue
        out.append({"username": user, "description": desc, "type": type_desc, "type_id": ident,
                    "google": bool(ident and "google" in ident.lower()) or str(user).lower().endswith(("@gmail.com", "@googlemail.com"))})
    seen, unique = set(), []
    for a in out:
        key = (a["username"].lower(), a["type_id"])
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique
