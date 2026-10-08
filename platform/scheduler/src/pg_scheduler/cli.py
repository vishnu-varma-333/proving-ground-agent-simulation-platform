"""The `pg` CLI (the spec's own two examples):

    pg run suites/refunds.yaml              # submit a suite, wait for it to finish
    pg run suites/refunds.yaml --no-wait     # submit and exit, don't poll for results
    pg replay <sim-id>                       # reproduce a recorded simulation locally, step by step
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pg_sdk import MetadataStore, apply_schema, connect_js, connect_pool

from pg_scheduler.replay import replay_simulation
from pg_scheduler.run import submit_suite
from pg_scheduler.suite import load_suite

POLL_INTERVAL_SECONDS = 1.0


async def run_suite(suite_path: str, wait: bool, timeout: float) -> int:
    pool = await connect_pool()
    await apply_schema(pool)
    store = MetadataStore(pool)

    nc, js = await connect_js()
    try:
        suite = load_suite(suite_path)
        run_id = await submit_suite(store, js, suite)
        print(f"Run {run_id}: {len(suite.scenarios) * len(suite.seeds)} simulation(s) queued.")

        if not wait:
            return 0

        elapsed = 0.0
        while elapsed < timeout:
            sims = await store.list_simulations_for_run(run_id)
            if all(s["state"] in ("completed", "failed") for s in sims):
                completed = sum(1 for s in sims if s["state"] == "completed")
                failed = sum(1 for s in sims if s["state"] == "failed")
                print(f"Run {run_id} finished: {completed} completed, {failed} failed.")
                return 0 if failed == 0 else 1
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS

        print(f"Run {run_id} did not finish within {timeout}s", file=sys.stderr)
        return 2
    finally:
        await nc.close()
        await pool.close()


async def run_replay_command(sim_id: str) -> int:
    pool = await connect_pool()
    await apply_schema(pool)
    store = MetadataStore(pool)
    try:
        await replay_simulation(store, sim_id)
        return 0
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="pg")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="submit a suite and optionally wait for it")
    run_parser.add_argument("suite", help="path to a suite YAML file")
    run_parser.add_argument(
        "--no-wait", action="store_true", help="submit and exit, don't poll for results"
    )
    run_parser.add_argument("--timeout", type=float, default=120.0, help="max seconds to wait")

    replay_parser = subparsers.add_parser(
        "replay", help="reproduce a recorded simulation locally, step by step"
    )
    replay_parser.add_argument("sim_id", help="simulation id to replay")

    args = parser.parse_args()

    if args.command == "run":
        exit_code = asyncio.run(run_suite(args.suite, wait=not args.no_wait, timeout=args.timeout))
    else:
        exit_code = asyncio.run(run_replay_command(args.sim_id))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
