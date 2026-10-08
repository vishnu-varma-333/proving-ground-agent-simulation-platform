import simulated_user.user as sim_user_module
from pg_worker.runner import run_conversation


class _FakeAgent:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.messages_received: list[str] = []

    async def respond(self, message: str) -> str:
        self.messages_received.append(message)
        return self._replies.pop(0)


async def test_fixed_message_scenario_calls_agent_once_and_builds_two_turn_transcript():
    agent = _FakeAgent(["Your refund has been issued."])
    scenario = {"simulated_user": False, "user_message": "I want a refund for ord_1001"}

    reply, transcript = await run_conversation(agent, scenario)

    assert reply == "Your refund has been issued."
    assert agent.messages_received == ["I want a refund for ord_1001"]
    assert transcript == [
        {"role": "user", "text": "I want a refund for ord_1001"},
        {"role": "agent", "text": "Your refund has been issued."},
    ]


async def test_simulated_user_scenario_drives_multiple_turns_until_done(monkeypatch):
    # Opening message, then one follow-up, then DONE once the agent's
    # second reply "satisfies" the persona.
    scripted_user_turns = iter(
        [
            ("Hi, I'd like a refund for ord_1001.", "gemini-flash-lite-latest"),
            ("Great, thanks!", "gemini-flash-lite-latest"),
            ("DONE", "gemini-flash-lite-latest"),
        ]
    )

    async def fake_generate(system, turns):
        return next(scripted_user_turns)

    monkeypatch.setattr(sim_user_module, "generate_text", fake_generate)

    agent = _FakeAgent(["Sure, what's the order id?", "Refund issued, anything else?"])
    scenario = {
        "simulated_user": True,
        "persona": "a customer wanting a refund",
        "goal": "get refunded for ord_1001",
        "max_turns": 4,
    }

    reply, transcript = await run_conversation(agent, scenario)

    assert reply == "Refund issued, anything else?"
    assert agent.messages_received == [
        "Hi, I'd like a refund for ord_1001.",
        "Great, thanks!",
    ]
    assert transcript == [
        {"role": "user", "text": "Hi, I'd like a refund for ord_1001."},
        {"role": "agent", "text": "Sure, what's the order id?"},
        {"role": "user", "text": "Great, thanks!"},
        {"role": "agent", "text": "Refund issued, anything else?"},
    ]


async def test_simulated_user_scenario_records_each_user_turn_when_a_recorder_is_given(monkeypatch):
    class _FakeRecorder:
        def __init__(self) -> None:
            self.recorded: list[str] = []

        def record_user_turn(self, message: str) -> None:
            self.recorded.append(message)

    scripted_user_turns = iter(
        [
            ("Hi, I'd like a refund for ord_1001.", "gemini-flash-lite-latest"),
            ("DONE", "gemini-flash-lite-latest"),
        ]
    )

    async def fake_generate(system, turns):
        return next(scripted_user_turns)

    monkeypatch.setattr(sim_user_module, "generate_text", fake_generate)

    agent = _FakeAgent(["Sure, what's the order id?"])
    recorder = _FakeRecorder()
    scenario = {
        "simulated_user": True,
        "persona": "a customer wanting a refund",
        "goal": "get refunded for ord_1001",
        "max_turns": 4,
    }

    await run_conversation(agent, scenario, recorder=recorder)

    assert recorder.recorded == ["Hi, I'd like a refund for ord_1001."]


async def test_simulated_user_scenario_stops_at_max_turns_even_if_never_says_done(monkeypatch):
    async def fake_generate(system, turns):
        return "Another message.", "gemini-flash-lite-latest"

    monkeypatch.setattr(sim_user_module, "generate_text", fake_generate)

    agent = _FakeAgent(["reply 1", "reply 2"])
    scenario = {
        "simulated_user": True,
        "persona": "a relentless customer",
        "goal": "never be satisfied",
        "max_turns": 2,
    }

    reply, _transcript = await run_conversation(agent, scenario)

    assert reply == "reply 2"
    assert len(agent.messages_received) == 2
