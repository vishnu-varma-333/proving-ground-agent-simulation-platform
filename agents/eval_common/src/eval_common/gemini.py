"""Shared plain-text Gemini calling for Milestone 8's two new evaluation
components (simulated_user, judge). Deliberately separate from
reference_agent.agent's own Gemini plumbing: that module is the system
under test (tool-calling, recorder/replay, fault injection) and is
already tested and working, so it isn't touched here. Evaluation calls
are plain text in/text out, much lower volume than the agent's own
tool-calling loop, and don't need recording or replay - so this is a
smaller, independent implementation of the same key-rotation idea
(agents/reference_agent/src/reference_agent/agent.py's load_api_keys/
MODEL_CANDIDATES), not a shared dependency between the two.
"""

from __future__ import annotations

import asyncio
import os
import random
import re

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

MODEL_CANDIDATES = ("gemini-flash-lite-latest", "gemini-3.8-flash")
REQUEST_TIMEOUT_MS = 30_000
MAX_RETRIES_PER_SLOT = 2
MAX_RETRY_DELAY_SECONDS = 15.0
RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
KEY_EXHAUSTED_THRESHOLD_SECONDS = 120.0

_KEY_VAR_PATTERN = re.compile(r"^GEMINI_API_KEY_?(\d*)$")


def load_api_keys() -> list[str]:
    matches = []
    for name, value in os.environ.items():
        if not value:
            continue
        m = _KEY_VAR_PATTERN.match(name)
        if m:
            suffix = m.group(1)
            order = -1 if suffix == "" else int(suffix)
            matches.append((order, value))
    matches.sort(key=lambda pair: pair[0])
    return [value for _, value in matches]


def _retry_delay_seconds(exc: genai_errors.APIError) -> float | None:
    details = exc.details if isinstance(exc.details, dict) else {}
    for item in details.get("error", {}).get("details", []):
        if item.get("@type", "").endswith("RetryInfo"):
            raw = item.get("retryDelay", "")
            if raw.endswith("s"):
                try:
                    return float(raw[:-1]) + random.uniform(0, 1)
                except ValueError:
                    return None
    return None


async def generate_text(
    system_instruction: str,
    turns: list[tuple[str, str]],
    api_keys: list[str] | None = None,
) -> tuple[str, str]:
    """`turns` is [(role, text), ...] with role "user" or "model". Tries
    every (key, model) slot, same exhaustion-rotation idea as the
    reference agent, until one succeeds or all are exhausted. Returns
    (text, model_used) - callers that record results (judge.scorer)
    need the real model, not just MODEL_CANDIDATES[0]."""
    keys = api_keys if api_keys is not None else load_api_keys()
    if not keys:
        raise RuntimeError("no Gemini API key set (GEMINI_API_KEY)")

    contents = [
        types.Content(role=role, parts=[types.Part.from_text(text=text)]) for role, text in turns
    ]

    last_error: Exception | None = None
    for key in keys:
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
        for model in MODEL_CANDIDATES:
            for attempt in range(MAX_RETRIES_PER_SLOT):
                try:
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(system_instruction=system_instruction),
                    )
                    return response.text or "", model
                except genai_errors.APIError as exc:
                    last_error = exc
                    if exc.code not in RETRYABLE_STATUS_CODES:
                        raise
                    suggested = _retry_delay_seconds(exc)
                    if suggested is not None and suggested > KEY_EXHAUSTED_THRESHOLD_SECONDS:
                        break  # this slot's quota is done for a while - try the next model/key
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    last_error = exc
                    suggested = None
                if attempt < MAX_RETRIES_PER_SLOT - 1:
                    delay = min(suggested or (2**attempt) + random.uniform(0, 1), MAX_RETRY_DELAY_SECONDS)
                    await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error
