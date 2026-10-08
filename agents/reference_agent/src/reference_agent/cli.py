"""Interactive CLI for the reference agent.

    uv run --package reference-agent python -m reference_agent

Reads GEMINI_API_KEY from the environment or a .env.local in the current
directory. Mock-service SQLite files live under ./data by default
(override with PG_DATA_DIR).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox


async def run_repl() -> None:
    load_dotenv(".env.local")
    data_dir = Path(os.environ.get("PG_DATA_DIR", "data"))

    async with MockServiceToolbox() as toolbox:
        await toolbox.connect(data_dir)
        agent = ReferenceAgent(toolbox)
        print(f"Reference agent ready (data dir: {data_dir.resolve()}). Type 'exit' to quit.")
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.lower() in {"exit", "quit"}:
                break
            if not line:
                continue
            reply = await agent.respond(line)
            print(f"agent> {reply}")


async def run_single_message(message: str) -> None:
    load_dotenv(".env.local")
    data_dir = Path(os.environ.get("PG_DATA_DIR", "data"))

    async with MockServiceToolbox() as toolbox:
        await toolbox.connect(data_dir)
        agent = ReferenceAgent(toolbox)
        reply = await agent.respond(message)
        print(reply)


def main() -> None:
    if len(sys.argv) > 1:
        asyncio.run(run_single_message(" ".join(sys.argv[1:])))
    else:
        asyncio.run(run_repl())


if __name__ == "__main__":
    main()
