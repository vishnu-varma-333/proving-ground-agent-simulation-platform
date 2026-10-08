import judge.scorer as scorer_module
from judge.scorer import JudgeResult, score_conversation


async def test_score_conversation_parses_clean_json(monkeypatch):
    async def fake_generate(system, turns):
        return '{"resolved": true, "score": 5, "rationale": "Handled perfectly."}', "gemini-flash-lite-latest"

    monkeypatch.setattr(scorer_module, "generate_text", fake_generate)

    result = await score_conversation(
        persona="a customer wanting a refund",
        goal="get refunded",
        transcript=[{"role": "user", "text": "I want a refund"}, {"role": "agent", "text": "Done!"}],
    )

    assert result == JudgeResult(
        resolved=True, score=5, rationale="Handled perfectly.", model="gemini-flash-lite-latest"
    )


async def test_score_conversation_strips_markdown_fences_around_json(monkeypatch):
    async def fake_generate(system, turns):
        raw = '```json\n{"resolved": false, "score": 2, "rationale": "Wrong amount."}\n```'
        return raw, "gemini-3.8-flash"

    monkeypatch.setattr(scorer_module, "generate_text", fake_generate)

    result = await score_conversation(persona="p", goal="g", transcript=[])

    assert result.resolved is False
    assert result.score == 2


async def test_score_conversation_raises_on_out_of_range_score(monkeypatch):
    async def fake_generate(system, turns):
        return '{"resolved": true, "score": 9, "rationale": "x"}', "gemini-flash-lite-latest"

    monkeypatch.setattr(scorer_module, "generate_text", fake_generate)

    try:
        await score_conversation(persona="p", goal="g", transcript=[])
        raised = False
    except ValueError:
        raised = True
    assert raised
