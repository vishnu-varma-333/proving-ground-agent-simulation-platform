"""`pg replay <sim-id>`: reproduces a previously recorded simulation
locally, step by step, from its tape alone - no live model API, no
running MCP servers, no network (the MockServiceToolbox below is never
connected; same proof-by-construction reference_agent's own lower-level
`--replay` flag already relied on). Looks the simulation's scenario up
in Postgres so the caller never has to already know, or retype, what
message originally drove it - reference_agent's `--replay RUN_ID
"message"` needs that message as a second argument, which is the
ergonomic gap this command exists to close, matching the spec's own
`pg replay <sim-id>` with no second argument.
"""

from __future__ import annotations

from pg_sdk import BlobStore, MetadataStore, Player
from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox


async def replay_simulation(
    store: MetadataStore, sim_id: str, verbose: bool = True, blob_store: BlobStore | None = None
) -> None:
    """`verbose=False` is for scripts/scale_test.py - dozens of parallel
    replay-bench workers each printing every turn would be noise, not
    signal, for a benchmark that only cares about throughput.

    `blob_store`: pass one in to reuse it across repeated calls (exactly
    what pg_scheduler.replay_bench does) - constructing a fresh
    `BlobStore` (a boto3 client) turned out to be the dominant per-call
    cost in the scale test, found live by timing replay_simulation in
    isolation (~0.02-0.1s, matching this function's own real work)
    against the same call through replay_bench's loop (~1-10s/call) and
    narrowing it down to repeated client construction, not anything
    about NATS, Postgres or S3 themselves (each measured independently
    and found fast). `pg replay`'s own one-shot CLI usage is unaffected
    either way - constructing one client for one call was never the
    expensive part there."""
    blob_store = blob_store if blob_store is not None else BlobStore()
    simulation = await store.get_simulation(sim_id)
    scenario = await store.get_scenario(simulation["scenario_id"])

    player = Player(blob_store, sim_id)
    if verbose:
        print(
            f"Replaying {sim_id} ({player.steps_total} recorded steps) - "
            "no live API, no MCP servers, no network."
        )

    async with MockServiceToolbox() as toolbox:
        agent = ReferenceAgent(toolbox, player=player)

        if not scenario["simulated_user"]:
            reply = await agent.respond(scenario["user_message"])
            if verbose:
                print(f"user> {scenario['user_message']}")
                print(f"agent> {reply}")
        else:
            while player.next_step_kind == "user":
                message = player.replay_user_turn()
                if verbose:
                    print(f"user> {message}")
                reply = await agent.respond(message)
                if verbose:
                    print(f"agent> {reply}")

    if verbose:
        if player.finished:
            print(f"Replay complete: all {player.steps_total} recorded steps consumed, no mismatch.")
        else:
            remaining = player.steps_total - player.steps_consumed
            print(f"Replay ended with {remaining} recorded step(s) unused.")
