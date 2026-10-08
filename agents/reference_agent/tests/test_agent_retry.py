import os

from google.genai import errors as genai_errors
from reference_agent.agent import (
    KEY_EXHAUSTED_THRESHOLD_SECONDS,
    ReferenceAgent,
    _retry_delay_seconds,
    load_api_keys,
)


def _make_429(retry_delay: str) -> genai_errors.ClientError:
    body = {
        "error": {
            "code": 429,
            "message": "quota exceeded",
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}],
        }
    }
    return genai_errors.ClientError(429, body, None)


def test_retry_delay_seconds_parses_short_wait():
    exc = _make_429("4.35s")
    delay = _retry_delay_seconds(exc)
    assert delay is not None
    assert 4.35 <= delay < 5.35  # includes jitter


def test_retry_delay_seconds_parses_long_wait_over_threshold():
    exc = _make_429("81400s")
    delay = _retry_delay_seconds(exc)
    assert delay is not None
    assert delay > KEY_EXHAUSTED_THRESHOLD_SECONDS


def test_retry_delay_seconds_none_when_absent():
    exc = genai_errors.ClientError(429, {"error": {"code": 429, "details": []}}, None)
    assert _retry_delay_seconds(exc) is None


def test_load_api_keys_collects_numbered_vars(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key-one")
    monkeypatch.setenv("GEMINI_API_KEY_2", "key-two")
    monkeypatch.setenv("GEMINI_API_KEY_3", "key-three")
    monkeypatch.delenv("GEMINI_API_KEY_4", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY4", raising=False)
    assert load_api_keys() == ["key-one", "key-two", "key-three"]


def test_load_api_keys_accepts_bare_number_spelling(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key-one")
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY2", "key-two")
    monkeypatch.delenv("GEMINI_API_KEY_3", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)
    assert load_api_keys() == ["key-one", "key-two"]


def test_load_api_keys_empty_without_primary(monkeypatch):
    for name in list(os.environ):
        if name.startswith("GEMINI_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    assert load_api_keys() == []


def test_load_api_keys_handles_gaps_and_no_bare_key(monkeypatch):
    # Observed live: a key landed as GEMINI_API_KEY5 with no GEMINI_API_KEY,
    # _2, _3 or _4 ever set. Must still be picked up.
    for name in list(os.environ):
        if name.startswith("GEMINI_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY5", "key-five")
    assert load_api_keys() == ["key-five"]


class _FakeToolbox:
    def __init__(self) -> None:
        self.function_declarations: list = []


def test_rotate_slot_tries_every_model_before_the_next_key():
    # model=None (default) rotates across every MODEL_CANDIDATES entry.
    agent = ReferenceAgent(_FakeToolbox(), api_keys=["key-a", "key-b"])
    num_models = len(agent._models)
    assert agent._key_index == 0
    assert agent._model_index == 0

    for expected_model_index in range(1, num_models):
        assert agent._rotate_slot() is True
        assert agent._key_index == 0
        assert agent._model_index == expected_model_index

    # every model exhausted on key 0 - next rotation moves to key 1, model 0
    assert agent._rotate_slot() is True
    assert agent._key_index == 1
    assert agent._model_index == 0

    for expected_model_index in range(1, num_models):
        assert agent._rotate_slot() is True
        assert agent._key_index == 1
        assert agent._model_index == expected_model_index

    # every (key, model) slot now exhausted
    assert agent._rotate_slot() is False


def test_single_key_single_model_cannot_rotate():
    agent = ReferenceAgent(_FakeToolbox(), model="pinned-model", api_keys=["only-key"])
    assert agent._models == ["pinned-model"]
    assert agent._rotate_slot() is False
