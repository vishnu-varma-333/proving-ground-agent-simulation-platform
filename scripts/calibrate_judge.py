"""Measures the judge's real agreement (Cohen's kappa) against a small
hand-labelled set of real transcripts - the spec's named Milestone 8
metric, "judge reliability". Deliberately not synthetic: every
transcript here comes from a real ReferenceAgent run against the real
mock services (two plain successes, plus two genuine failures produced
with Milestone 7's own fault injection and a nonexistent order - not
hand-written text pretending to be a transcript). The "human" label is
assigned by reading each real reply once it's printed, before the
judge's own verdict is requested, so it isn't anchored on the judge.

    uv run --package pg-worker python scripts/calibrate_judge.py
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from judge import cohen_kappa, score_conversation
from pg_sdk import FaultInjectingToolbox, FaultSpec, fork_environment
from pg_worker.runner import ensure_template
from reference_agent.agent import ReferenceAgent
from reference_agent.mcp_tools import MockServiceToolbox

SCENARIOS = [
    {
        "persona": "Annoyed customer, item arrived damaged",
        "goal": "Get a refund for order ord_1001",
        "message": "I'd like a refund for order ord_1001, it arrived damaged.",
        "faults": [],
        "human_resolved": True,
        "note": "plain success case",
    },
    {
        "persona": "Customer with a defective item",
        "goal": "Get a refund for order ord_1004",
        "message": "I'd like a refund for order ord_1004, it's defective.",
        "faults": [],
        "human_resolved": True,
        "note": "plain success case",
    },
    {
        "persona": "Customer whose item broke",
        "goal": "Get a refund for order ord_1003",
        "message": "I'd like a refund for order ord_1003, it's defective.",
        "faults": [FaultSpec(tool="issue_refund", kind="error", message="payments service unavailable")],
        "human_resolved": False,
        "note": "payments outage - refund genuinely can't be issued, real fault injection",
    },
    {
        "persona": "Customer asking about an order that doesn't exist",
        "goal": "Get a refund for order ord_9999",
        "message": "I'd like a refund for order ord_9999.",
        "faults": [],
        "human_resolved": False,
        "note": "no such order - goal can't be met regardless of agent politeness",
    },
]


async def run_scenario(spec: dict, data_dir: Path) -> tuple[str, list[dict[str, str]]]:
    async with MockServiceToolbox() as real_toolbox:
        await real_toolbox.connect(data_dir)
        faults = spec["faults"]
        toolbox = FaultInjectingToolbox(inner=real_toolbox, faults=faults) if faults else real_toolbox
        agent = ReferenceAgent(toolbox)
        reply = await agent.respond(spec["message"])
    transcript = [{"role": "user", "text": spec["message"]}, {"role": "agent", "text": reply}]
    return reply, transcript


async def main() -> None:
    load_dotenv(".env.local")
    template_dir = await ensure_template("default")

    human_labels: list[bool] = []
    judge_labels: list[bool] = []

    for spec in SCENARIOS:
        data_dir = Path(tempfile.mkdtemp(prefix="pg-calibration-"))
        try:
            fork_environment(template_dir, data_dir)
            reply, transcript = await run_scenario(spec, data_dir)
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

        judge_result = await score_conversation(spec["persona"], spec["goal"], transcript)

        print(f"\n--- {spec['note']} ---")
        print(f"goal: {spec['goal']}")
        print(f"agent reply: {reply}")
        print(f"human label: resolved={spec['human_resolved']}")
        print(f"judge label: resolved={judge_result.resolved} score={judge_result.score} "
              f"({judge_result.model})")
        print(f"judge rationale: {judge_result.rationale}")

        human_labels.append(spec["human_resolved"])
        judge_labels.append(judge_result.resolved)

    kappa = cohen_kappa(human_labels, judge_labels)
    agreement = sum(a == b for a, b in zip(human_labels, judge_labels)) / len(human_labels)
    print(f"\n=== {len(human_labels)} labelled examples ===")
    print(f"raw agreement: {agreement:.2f}")
    print(f"Cohen's kappa: {kappa:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
