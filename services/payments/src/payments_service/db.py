"""SQLite storage for the payments mock service."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    order_id TEXT PRIMARY KEY,
    amount_cents INTEGER NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'captured',
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (order_id)
);
"""

# Mirrors services/orders seed data: same order ids and amounts, so a
# reference-agent scenario that looks up an order and then its payment
# gets consistent numbers.
SEED_PAYMENTS = [
    ("ord_1001", 2499, "card_visa_4242", "captured", "2026-09-20T14:00:05Z"),
    ("ord_1002", 4599, "card_visa_4242", "captured", "2026-09-28T09:30:05Z"),
    ("ord_1003", 8999, "card_mc_5555", "captured", "2026-10-02T11:15:05Z"),
    ("ord_1004", 3299, "paypal", "captured", "2026-09-15T16:45:05Z"),
]


def default_db_path() -> Path:
    return Path("data/payments.db")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not db_path.exists()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if is_new:
        conn.executemany(
            "INSERT INTO payments (order_id, amount_cents, method, status, captured_at) "
            "VALUES (?, ?, ?, ?, ?)",
            SEED_PAYMENTS,
        )
        conn.commit()
    return conn


@contextmanager
def connection(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
