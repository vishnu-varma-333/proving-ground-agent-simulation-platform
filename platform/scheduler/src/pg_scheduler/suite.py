"""Suite/scenario file format: the first real formalization of "Scenario
definitions" (core feature #1 in the spec), kept deliberately minimal.
A scenario here is a persona/goal label plus the one user message that
drives the reference agent - a full multi-turn simulated-user persona
that roleplays goal-directed conversation is Milestone 8's job
(evaluation's "simulated users"), not this one's. This milestone needs
something real to schedule, not a complete scenario-authoring system.
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
            user_message=s["user_message"],
            env_template=s.get("env_template", "default"),
            version=s.get("version", 1),
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
