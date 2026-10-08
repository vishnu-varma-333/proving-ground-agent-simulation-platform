"""Suite/scenario file format: the first real formalization of "Scenario
definitions" (core feature #1 in the spec), kept deliberately minimal.
A scenario is a persona/goal label plus either a single fixed
user_message (the original, deterministic-input form) or
simulated_user: true, which instead drives the agent through a
multi-turn conversation generated live by a Gemini-backed persona
(Milestone 8's "simulated users" - see agents/simulated_user). `checks`
is a list of deterministic state-check specs (pg_sdk.checks.CheckSpec)
run against the simulation's forked mock-service data once the agent
finishes - Milestone 8's other half, "state checks".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ScenarioDef:
    id: str
    persona: str
    goal: str
    user_message: str
    env_template: str
    version: int = 1
    faults: tuple[dict, ...] = ()
    checks: tuple[dict, ...] = ()
    simulated_user: bool = False
    max_turns: int = 4


@dataclass(frozen=True)
class SuiteDef:
    id: str
    name: str
    agent_version_id: str
    agent_image: str
    agent_git_sha: str
    priority: int
    scenarios: list[ScenarioDef]
    seeds: list[int]


def load_suite(path: str | Path) -> SuiteDef:
    data = yaml.safe_load(Path(path).read_text())

    scenarios = [
        ScenarioDef(
            id=s["id"],
            persona=s["persona"],
            goal=s["goal"],
            user_message=s.get("user_message", ""),
            env_template=s.get("env_template", "default"),
            version=s.get("version", 1),
            faults=tuple(s.get("faults", [])),
            checks=tuple(s.get("checks", [])),
            simulated_user=s.get("simulated_user", False),
            max_turns=s.get("max_turns", 4),
        )
        for s in data["scenarios"]
    ]

    agent = data.get("agent_version", {})
    return SuiteDef(
        id=data["suite"]["id"],
        name=data["suite"]["name"],
        agent_version_id=agent.get("id", "reference-agent-dev"),
        agent_image=agent.get("image", "reference-agent"),
        agent_git_sha=agent.get("git_sha", "unknown"),
        priority=data.get("priority", 1),
        scenarios=scenarios,
        seeds=data.get("seeds", [1]),
    )
