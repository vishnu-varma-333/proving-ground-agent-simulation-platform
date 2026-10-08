"""Interactive CLI for the reference agent.

    uv run --package reference-agent python -m reference_agent
    uv run --package reference-agent python -m reference_agent "message"
    uv run --package reference-agent python -m reference_agent --record "message"
    uv run --package reference-agent python -m reference_agent --replay <run_id> "message"

Reads GEMINI_API_KEY from the environment or a .env.local in the current
directory. Mock-service SQLite files live under ./data by default
(override with PG_DATA_DIR). --record captures a tape of every model
call, tool call and clock read to S3-compatible storage (PG_S3_* env
vars; see sdk/pg_sdk) and prints the run id to fetch it by afterward.

--replay feeds a previously recorded tape back instead of making any
live call - no API key, no running MCP servers, no network. It needs
the SAME message that produced that run_id originally: the tape records
model/tool/clock outputs, not the human's own input, since that was
never non-deterministic in the first place.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pg_sdk import BlobStore, Player, Recorder

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


async def run_replay(run_id: str, message: str) -> None:
    load_dotenv(".env.local")
    store = BlobStore()
    player = Player(store, run_id)
    total_steps = player.steps_total
    print(f"Replaying run {run_id} ({total_steps} recorded steps) - no live API, no MCP servers.")

    # Never connected: proves replay touches neither a real model API nor
    # the real mock services, only the tape.
    async with MockServiceToolbox() as toolbox:
        agent = ReferenceAgent(toolbox, player=player)
        reply = await agent.respond(message)
        print(reply)

    if player.finished:
        print(f"Replay complete: all {total_steps} recorded steps consumed, no mismatch.")
    else:
        remaining = total_steps - player.steps_consumed
        print(f"Replay ended with {remaining} recorded step(s) unused.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="reference_agent")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--record", action="store_true", help="capture a tape of this conversation to S3"
    )
    mode.add_argument(
        "--replay", metavar="RUN_ID", help="replay a previously recorded tape, no live calls"
    )
    parser.add_argument("message", nargs="*", help="a single message; omit for an interactive REPL")
    args = parser.parse_args()

    if args.replay:
        if not args.message:
            print("--replay needs the same message that produced that run", file=sys.stderr)
            raise SystemExit(2)
        asyncio.run(run_replay(args.replay, " ".join(args.message)))
    elif args.message:
        asyncio.run(run_single_message(" ".join(args.message), args.record))
    else:
        asyncio.run(run_repl(args.record))


if __name__ == "__main__":
    main()
