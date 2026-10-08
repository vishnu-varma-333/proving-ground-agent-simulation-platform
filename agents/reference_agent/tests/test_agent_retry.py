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
    assert load_api_keys() == ["key-one", "key-two", "key-three"]


def test_load_api_keys_empty_without_primary(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    assert load_api_keys() == []


class _FakeToolbox:
    def __init__(self) -> None:
        self.function_declarations: list = []


def test_rotate_key_cycles_then_reports_exhausted():
    agent = ReferenceAgent(_FakeToolbox(), api_keys=["key-a", "key-b", "key-c"])
    assert agent._key_index == 0
    assert agent._rotate_key() is True
    assert agent._key_index == 1
    assert agent._rotate_key() is True
    assert agent._key_index == 2
    assert agent._rotate_key() is False, "no fourth key configured"
    assert agent._key_index == 2, "index must not advance past the last real key"


def test_single_key_cannot_rotate():
    agent = ReferenceAgent(_FakeToolbox(), api_keys=["only-key"])
    assert agent._rotate_key() is False
