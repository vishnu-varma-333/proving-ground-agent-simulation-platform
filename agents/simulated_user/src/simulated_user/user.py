"""A goal-directed simulated user (Milestone 8 core feature #8, "simulated
users"): a Gemini-backed persona that holds a real multi-turn
conversation with the agent under test, instead of the single canned
user_message every scenario used before this milestone. It decides for
itself, turn by turn, whether its goal has been met and the conversation
should end - not a fixed turn count - capped by max_turns only as a
safety bound against a persona that never signals satisfaction.

Deliberately not recorded/replayed: the thing under deterministic test
is the agent (pg_sdk.Recorder/Player already cover that), not this
test-harness persona generating realistic input for it - same role a
human tester typing messages would play.
"""

from __future__ import annotations

from eval_common.gemini import generate_text

_SYSTEM_TEMPLATE = """\
You are roleplaying as a customer contacting an online electronics
store's support chat. Stay fully in character as this persona:

{persona}

Your goal for this conversation: {goal}

Rules:
- Write only the customer's next message, in plain conversational text.
  No labels, no quotes, no "Customer:" prefix.
- Keep messages short and natural, like a real chat message.
- Once the support agent's latest reply has genuinely satisfied your
  goal, respond with exactly the single word DONE and nothing else.
- If the agent asks a clarifying question, answer it plausibly based on
  your persona rather than inventing contradictory details.
"""


class SimulatedUser:
    def __init__(self, persona: str, goal: str, max_turns: int = 4) -> None:
        self.persona = persona
        self.goal = goal
        self.max_turns = max_turns
        self._system = _SYSTEM_TEMPLATE.format(persona=persona, goal=goal)
        self._gemini_turns: list[tuple[str, str]] = []
        self.transcript: list[dict[str, str]] = []
        self._turns_taken = 0

    async def opening_message(self) -> str:
        self._gemini_turns.append(("user", "Begin the conversation with the support agent."))
        message, _ = await generate_text(self._system, self._gemini_turns)
        self._gemini_turns.append(("model", message))
        self.transcript.append({"role": "user", "text": message})
        self._turns_taken += 1
        return message

    async def next_message(self, agent_reply: str) -> str | None:
        self.transcript.append({"role": "agent", "text": agent_reply})
        if self._turns_taken >= self.max_turns:
            return None

        self._gemini_turns.append(("user", agent_reply))
        message, _ = await generate_text(self._system, self._gemini_turns)
        if message.strip().upper().rstrip(".") == "DONE":
            return None

        self._gemini_turns.append(("model", message))
        self.transcript.append({"role": "user", "text": message})
        self._turns_taken += 1
        return message
