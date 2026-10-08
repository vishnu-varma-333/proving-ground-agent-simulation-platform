"""MCP server exposing the payments mock service as tools.

Run with: python -m payments_service
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from payments_service.db import connection, default_db_path

mcp = MCPServer("payments")


def _db_path() -> Path:
    return Path(os.environ.get("PAYMENTS_DB_PATH", default_db_path()))


@mcp.tool()
def get_payment(order_id: str) -> dict:
    """Look up the payment captured for an order."""
    with connection(_db_path()) as conn:
        row = conn.execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return {"error": f"no payment for order {order_id!r}"}
        return dict(row)


@mcp.tool()
def issue_refund(order_id: str, amount_cents: int, reason: str) -> dict:
    """Refund a captured payment. Idempotent: a second call for the same
    order returns the refund already issued rather than creating a
    duplicate - this is the mock service's own guarantee that a refund is
    issued at most once per order, which is exactly the invariant later
    evaluation checks (Milestone 8) will assert against real agent runs."""
    with connection(_db_path()) as conn:
        payment = conn.execute(
            "SELECT * FROM payments WHERE order_id = ?", (order_id,)
        ).fetchone()
        if payment is None:
            return {"error": f"no payment for order {order_id!r}, cannot refund"}

        existing = conn.execute(
            "SELECT * FROM refunds WHERE order_id = ?", (order_id,)
        ).fetchone()
        if existing is not None:
            return {"already_refunded": True, **dict(existing)}

        if amount_cents > payment["amount_cents"]:
            return {
                "error": (
                    f"refund amount {amount_cents} exceeds captured amount "
                    f"{payment['amount_cents']} for order {order_id!r}"
                )
            }

        refund_id = f"ref_{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO refunds (id, order_id, amount_cents, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (refund_id, order_id, amount_cents, reason, created_at),
        )
        conn.execute("UPDATE payments SET status = 'refunded' WHERE order_id = ?", (order_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM refunds WHERE id = ?", (refund_id,)).fetchone()
        return {"already_refunded": False, **dict(row)}


@mcp.tool()
def list_refunds(order_id: str) -> list[dict]:
    """List refunds issued for an order (0 or 1, since refunds are capped at one per order)."""
    with connection(_db_path()) as conn:
        rows = conn.execute(
            "SELECT * FROM refunds WHERE order_id = ?", (order_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
