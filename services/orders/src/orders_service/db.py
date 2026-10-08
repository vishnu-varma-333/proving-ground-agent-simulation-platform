"""SQLite storage for the orders mock service.

One file per simulation in the real platform (Milestone 7 forks this file
to isolate simulations from each other); for now it's just a single local
file, overridable via ORDERS_DB_PATH so the reference agent and tests don't
collide.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    item TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'placed',
    created_at TEXT NOT NULL
);
"""

SEED_ORDERS = [
    ("ord_1001", "cust_amy", "Wireless Mouse", 2499, "delivered", "2026-09-20T14:00:00Z"),
    ("ord_1002", "cust_amy", "USB-C Hub", 4599, "delivered", "2026-09-28T09:30:00Z"),
    ("ord_1003", "cust_ben", "Mechanical Keyboard", 8999, "shipped", "2026-10-02T11:15:00Z"),
    ("ord_1004", "cust_cara", "Laptop Stand", 3299, "delivered", "2026-09-15T16:45:00Z"),
]


def default_db_path() -> Path:
    return Path("data/orders.db")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not db_path.exists()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    if is_new:
        conn.executemany(
            "INSERT INTO orders (id, customer_id, item, amount_cents, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            SEED_ORDERS,
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
