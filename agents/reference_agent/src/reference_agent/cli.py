"""Interactive CLI for the reference agent.

    uv run --package reference-agent python -m reference_agent
    uv run --package reference-agent python -m reference_agent "message"
    uv run --package reference-agent python -m reference_agent --record "message"

Reads GEMINI_API_KEY from the environment or a .env.local in the current
directory. Mock-service SQLite files live under ./data by default
(override with PG_DATA_DIR). --record captures a tape of every model
call, tool call and clock read to S3-compatible storage (PG_S3_* env
vars; see sdk/pg_sdk) and prints the run id to fetch it by afterward.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pg_sdk import BlobStore, Recorder

from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox


def _make_recorder() -> tuple[Recorder, str]:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    store = BlobStore()
    return Recorder(store=store, run_id=run_id, agent_name="reference_agent"), run_id


async def run_repl(record: bool) -> None:
    load_dotenv(".env.local")
    data_dir = Path(os.environ.get("PG_DATA_DIR", "data"))

    recorder, run_id = _make_recorder() if record else (None, None)
    if record:
        print(f"Recording to run id: {run_id}")

    async with MockServiceToolbox() as toolbox:
        await toolbox.connect(data_dir)
        agent = ReferenceAgent(toolbox, recorder=recorder)
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

    if recorder is not None:
        manifest = await asyncio.to_thread(recorder.finalize)
        print(f"Tape finalized: run {run_id}, {manifest['step_count']} steps.")


async def run_single_message(message: str, record: bool) -> None:
    load_dotenv(".env.local")
    data_dir = Path(os.environ.get("PG_DATA_DIR", "data"))

    recorder, run_id = _make_recorder() if record else (None, None)

    async with MockServiceToolbox() as toolbox:
        await toolbox.connect(data_dir)
        agent = ReferenceAgent(toolbox, recorder=recorder)
        reply = await agent.respond(message)
        print(reply)

    if recorder is not None:
        manifest = await asyncio.to_thread(recorder.finalize)
        print(f"Tape finalized: run {run_id}, {manifest['step_count']} steps.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="reference_agent")
    parser.add_argument(
        "--record", action="store_true", help="capture a tape of this conversation to S3"
    )
    parser.add_argument("message", nargs="*", help="a single message; omit for an interactive REPL")
    args = parser.parse_args()

    if args.message:
        asyncio.run(run_single_message(" ".join(args.message), args.record))
    else:
        asyncio.run(run_repl(args.record))


if __name__ == "__main__":
    main()
