from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from contextlib import contextmanager
from collections.abc import Iterator

from core import clean_record

DATA_DIR = Path(os.environ.get("REDIAL_DATA_DIR", Path(__file__).resolve().parent / "data"))
DB_PATH = DATA_DIR / "redial.sqlite3"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS contacts (
        phone TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', format_valid INTEGER NOT NULL,
        validation_note TEXT NOT NULL, line_type TEXT NOT NULL, line_type_source TEXT NOT NULL DEFAULT '', line_type_checked_at TEXT NOT NULL DEFAULT '',
        carrier TEXT NOT NULL DEFAULT '', carrier_source TEXT NOT NULL DEFAULT '', carrier_checked_at TEXT NOT NULL DEFAULT '',
        sms_consent INTEGER NOT NULL DEFAULT 0, sms_consent_at TEXT NOT NULL DEFAULT '', sms_consent_source TEXT NOT NULL DEFAULT '',
        whatsapp_consent INTEGER NOT NULL DEFAULT 0, whatsapp_consent_at TEXT NOT NULL DEFAULT '', whatsapp_consent_source TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    present = {row[1] for row in con.execute("PRAGMA table_info(contacts)")}
    migrations = {
        "line_type_source": "TEXT NOT NULL DEFAULT ''",
        "line_type_checked_at": "TEXT NOT NULL DEFAULT ''",
        "carrier_source": "TEXT NOT NULL DEFAULT ''",
        "carrier_checked_at": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in migrations.items():
        if column not in present:
            con.execute(f"ALTER TABLE contacts ADD COLUMN {column} {definition}")
    con.commit()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert(raw: dict[str, Any]) -> dict[str, Any]:
    row = clean_record(raw)
    cols = list(row)
    vals = [int(row[k]) if k in {"format_valid", "sms_consent", "whatsapp_consent"} else row[k] for k in cols]
    with connect() as con:
        con.execute(
            f"INSERT INTO contacts ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
            "ON CONFLICT(phone) DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in cols if k != "phone"),
            vals,
        )
    return row


def import_records(records: list[dict[str, Any]]) -> dict[str, int]:
    inserted = 0
    for row in records:
        row = clean_record(row)
        existed = get(row["phone"]) is not None
        upsert(row)
        inserted += not existed
    return {"processed": len(records), "new": inserted, "updated": len(records) - inserted}


def get(phone: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM contacts WHERE phone=?", (phone,)).fetchone()
        return dict(row) if row else None


def list_contacts(limit: int = 5000) -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM contacts ORDER BY created_at DESC LIMIT ?", (limit,))]


def metrics() -> dict[str, int]:
    with connect() as con:
        row = con.execute("""SELECT COUNT(*) total,
            SUM(format_valid) valid,
            SUM(line_type='mobile') mobile,
            SUM(line_type='fixed') fixed,
            SUM(line_type='unknown') unknown,
            SUM(sms_consent=1) sms_optin,
            SUM(whatsapp_consent=1) whatsapp_optin FROM contacts""").fetchone()
    return {k: int(row[k] or 0) for k in row.keys()}


