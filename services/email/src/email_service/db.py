"""SQLite storage for the email mock service. No real email is ever sent -
this just records what the agent asked to send, for later inspection and
evaluation checks."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    return Path("data/email.db")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


@contextmanager
def connection(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
