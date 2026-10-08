"""The `pg run` half of the spec's CLI ("pg run suite.yaml starts a
run"). Submits a suite's scenarios as queued simulation jobs and,
unless --no-wait is given, polls Postgres until every simulation for
that run has finished, then reports a summary.

    uv run --package pg-scheduler python -m pg_scheduler suites/refunds.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pg_sdk import MetadataStore, apply_schema, connect_js, connect_pool

from pg_scheduler.run import submit_suite
from pg_scheduler.suite import load_suite

POLL_INTERVAL_SECONDS = 1.0


async def run(suite_path: str, wait: bool, timeout: float) -> int:
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="pg_scheduler")
    parser.add_argument("suite", help="path to a suite YAML file")
    parser.add_argument("--no-wait", action="store_true", help="submit and exit, don't poll for results")
    parser.add_argument("--timeout", type=float, default=120.0, help="max seconds to wait for the run")
    args = parser.parse_args()

    exit_code = asyncio.run(run(args.suite, wait=not args.no_wait, timeout=args.timeout))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
