"""MCP server exposing the email mock service as tools.

Run with: python -m email_service
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from email_service.db import connection, default_db_path

mcp = MCPServer("email")


def _db_path() -> Path:
    return Path(os.environ.get("EMAIL_DB_PATH", default_db_path()))


@mcp.tool()
def send_email(to_address: str, subject: str, body: str) -> dict:
    """Send an email (simulated - recorded, not actually delivered)."""
    email_id = f"eml_{uuid.uuid4().hex[:12]}"
    sent_at = datetime.now(UTC).isoformat()
    with connection(_db_path()) as conn:
        conn.execute(
            "INSERT INTO emails (id, to_address, subject, body, sent_at) VALUES (?, ?, ?, ?, ?)",
            (email_id, to_address, subject, body, sent_at),
        )
        conn.commit()
        return {"id": email_id, "to_address": to_address, "subject": subject, "sent_at": sent_at}


@mcp.tool()
def list_emails(to_address: str) -> list[dict]:
    """List emails sent to an address, newest first."""
    with connection(_db_path()) as conn:
        rows = conn.execute(
            "SELECT * FROM emails WHERE to_address = ? ORDER BY sent_at DESC",
            (to_address,),
        ).fetchall()
        return [dict(row) for row in rows]


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
