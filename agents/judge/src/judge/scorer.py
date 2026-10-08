"""An AI judge (Milestone 8 core feature #8, second half): scores a
completed conversation between the simulated user (or a scenario's
fixed user_message) and the agent under test, against the scenario's
own persona/goal - "AI judges scoring conversation quality" in the
spec's words. Calibration against a human-labelled set lives in
judge.calibration, not here, so this module stays a plain,
single-purpose scorer that the calibration script and the worker both
call the same way.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from eval_common.gemini import generate_text

_SYSTEM_INSTRUCTION = """\
You are an impartial judge evaluating a customer-support conversation.

You will be given the customer's persona, their goal for the
conversation, and the full transcript. Score how well the support
agent handled the conversation.

Respond with ONLY a JSON object, no markdown fences, no extra text, in
exactly this shape:
{"resolved": true or false, "score": integer 1-5, "rationale": "one sentence"}

- "resolved": true only if the agent actually achieved the customer's
  stated goal by the end of the transcript (not just was polite).
- "score": 1 (handled badly - wrong info, rude, or failed the goal
  despite being able to) to 5 (handled excellently).
- Be strict: a wrong refund amount, a skipped verification step, or an
  unresolved goal should pull both resolved and score down even if the
  tone was pleasant.
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class JudgeResult:
    resolved: bool
    score: int
    rationale: str
    model: str


def _format_transcript(transcript: list[dict[str, str]]) -> str:
    lines = [f"{turn['role']}: {turn['text']}" for turn in transcript]
    return "\n".join(lines)


def _parse_response(raw: str) -> tuple[bool, int, str]:
    match = _JSON_BLOCK.search(raw)
    if match is None:
        raise ValueError(f"judge response had no JSON object: {raw!r}")
    data = json.loads(match.group(0))
    score = int(data["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"judge score out of range 1-5: {score}")
    return bool(data["resolved"]), score, str(data["rationale"])


async def score_conversation(
    persona: str, goal: str, transcript: list[dict[str, str]]
) -> JudgeResult:
    prompt = (
        f"Persona: {persona}\nGoal: {goal}\n\nTranscript:\n{_format_transcript(transcript)}"
    )
    raw, model = await generate_text(_SYSTEM_INSTRUCTION, [("user", prompt)])
    resolved, score, rationale = _parse_response(raw)
    return JudgeResult(resolved=resolved, score=score, rationale=rationale, model=model)
