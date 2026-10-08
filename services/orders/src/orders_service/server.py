"""MCP server exposing the orders mock service as tools.

Run with: python -m orders_service
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from orders_service.db import connection, default_db_path

mcp = MCPServer("orders")


def _db_path() -> Path:
    return Path(os.environ.get("ORDERS_DB_PATH", default_db_path()))


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Look up a single order by its id. Returns an error field if not found."""
    with connection(_db_path()) as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            return {"error": f"no order with id {order_id!r}"}
        return dict(row)


@mcp.tool()
def list_orders_by_customer(customer_id: str) -> list[dict]:
    """List every order placed by a customer, newest first."""
    with connection(_db_path()) as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
        return [dict(row) for row in rows]


@mcp.tool()
def update_order_status(order_id: str, status: str) -> dict:
    """Set an order's status (e.g. 'refunded', 'cancelled'). Returns the updated order."""
    valid_statuses = {"placed", "shipped", "delivered", "refunded", "cancelled"}
    if status not in valid_statuses:
        return {"error": f"invalid status {status!r}, must be one of {sorted(valid_statuses)}"}
    with connection(_db_path()) as conn:
        existing = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if existing is None:
            return {"error": f"no order with id {order_id!r}"}
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
