import simulated_user.user as user_module
from simulated_user import SimulatedUser


async def test_opening_message_returns_generated_text_and_records_transcript(monkeypatch):
    async def fake_generate(system, turns):
        assert "Begin the conversation" in turns[-1][1]
        return "Hi, my order hasn't arrived yet.", "gemini-flash-lite-latest"

    monkeypatch.setattr(user_module, "generate_text", fake_generate)
    sim_user = SimulatedUser(persona="a frustrated customer", goal="get a refund", max_turns=4)

    message = await sim_user.opening_message()

    assert message == "Hi, my order hasn't arrived yet."
    assert sim_user.transcript == [{"role": "user", "text": message}]


async def test_next_message_feeds_agent_reply_and_continues(monkeypatch):
    calls = []

    async def fake_generate(system, turns):
        calls.append(list(turns))
        return "Yes, order ord_1001 please.", "gemini-flash-lite-latest"

    monkeypatch.setattr(user_module, "generate_text", fake_generate)
    sim_user = SimulatedUser(persona="customer", goal="get a refund", max_turns=4)
    await sim_user.opening_message()

    message = await sim_user.next_message("Sure, what's your order id?")

    assert message == "Yes, order ord_1001 please."
    assert calls[-1][-1] == ("user", "Sure, what's your order id?")
    assert sim_user.transcript[-2] == {"role": "agent", "text": "Sure, what's your order id?"}
    assert sim_user.transcript[-1] == {"role": "user", "text": message}


async def test_next_message_returns_none_when_model_signals_done(monkeypatch):
    async def fake_generate(system, turns):
        return "DONE", "gemini-flash-lite-latest"

    monkeypatch.setattr(user_module, "generate_text", fake_generate)
    sim_user = SimulatedUser(persona="customer", goal="get a refund", max_turns=4)
    await sim_user.opening_message()

    message = await sim_user.next_message("Your refund has been issued.")

    assert message is None


async def test_next_message_returns_none_once_max_turns_reached_without_calling_model():
    sim_user = SimulatedUser(persona="customer", goal="get a refund", max_turns=1)
    sim_user._turns_taken = 1  # simulate having already taken the one allowed turn

    message = await sim_user.next_message("Here is your answer.")

    assert message is None
    assert sim_user.transcript[-1] == {"role": "agent", "text": "Here is your answer."}
