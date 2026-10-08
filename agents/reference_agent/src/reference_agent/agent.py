"""The reference agent: a customer-support assistant that can look up
orders, check payments, issue refunds, and send confirmation emails by
calling the three mock services' MCP tools through Gemini function
calling.

Nothing here talks to the simulation platform - that's Milestone 3's SDK,
which will sit between an agent like this one and its model/tool calls to
record and replay them. This agent just needs to work, standalone, as the
realistic system under test everything else will run against.
"""

from __future__ import annotations

import asyncio
import os
import random

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from reference_agent.mcp_tools import MockServiceToolbox

DEFAULT_MODEL = "gemini-3.8-flash"

SYSTEM_INSTRUCTION = """\
You are a customer-support agent for an online electronics store.

You can look up a customer's orders, check the payment behind an order,
issue a refund, and send confirmation emails. Rules:

- Never invent an order id, amount, or payment detail - always look it up
  with a tool first.
- Before issuing a refund, confirm the order exists and get its payment
  record so you refund the correct amount.
- After a refund is issued, send the customer a confirmation email
  summarizing what was refunded and why.
- If an order or payment can't be found, say so plainly and don't guess.
- Keep replies short and concrete: state what you found and what you did.
"""

MAX_TOOL_ROUNDS = 8
MAX_MODEL_RETRIES = 3
MAX_RETRY_DELAY_SECONDS = 20.0
RETRYABLE_STATUS_CODES = {429, 500, 503, 504}

# A 429 suggesting a wait longer than this is the free tier's *daily* quota
# talking (observed live: "Please retry in 22h36m...") - not the kind of
# brief throttle worth sleeping through. Rotate to the next configured key
# instead. Below this threshold it's treated as transient (Milestone 2's
# earlier finding: a per-minute quota blip) and retried on the same key.
KEY_EXHAUSTED_THRESHOLD_SECONDS = 120.0


def load_api_keys() -> list[str]:
    """GEMINI_API_KEY, plus GEMINI_API_KEY_2, GEMINI_API_KEY_3, ... if
    present. Multiple personal free-tier keys are a dev-time workaround for
    the 20-requests/day cap (see DECISIONS.md) - not how the platform's
    own model-call layer will handle cost/throughput in Milestone 3+."""
    keys = []
    primary = os.environ.get("GEMINI_API_KEY")
    if primary:
        keys.append(primary)
    i = 2
    while True:
        extra = os.environ.get(f"GEMINI_API_KEY_{i}")
        if not extra:
            break
        keys.append(extra)
        i += 1
    return keys


class ReferenceAgent:
    def __init__(
        self,
        toolbox: MockServiceToolbox,
        model: str = DEFAULT_MODEL,
        api_keys: list[str] | None = None,
    ) -> None:
        self._toolbox = toolbox
        self._model = model
        self._api_keys = api_keys if api_keys is not None else load_api_keys()
        if not self._api_keys:
            raise RuntimeError("no Gemini API key set (GEMINI_API_KEY)")
        self._key_index = 0
        self._client = genai.Client(api_key=self._api_keys[0])
        self._tool = types.Tool(function_declarations=toolbox.function_declarations)
        self._contents: list[types.Content] = []

    def _rotate_key(self) -> bool:
        if self._key_index + 1 >= len(self._api_keys):
            return False
        self._key_index += 1
        self._client = genai.Client(api_key=self._api_keys[self._key_index])
        print(
            f"[reference_agent] key {self._key_index} exhausted its quota, "
            f"switching to key {self._key_index + 1}/{len(self._api_keys)}",
            flush=True,
        )
        return True

    async def respond(self, user_message: str) -> str:
        self._contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
        )

        for _round in range(MAX_TOOL_ROUNDS):
            response = await self._generate_with_retry()

            candidate_content = response.candidates[0].content
            self._contents.append(candidate_content)

            calls = response.function_calls
            if not calls:
                return response.text or ""

            response_parts = []
            for call in calls:
                result = await self._toolbox.call(call.name, dict(call.args or {}))
                response_parts.append(
                    types.Part.from_function_response(name=call.name, response=result)
                )
            self._contents.append(types.Content(role="user", parts=response_parts))

        raise RuntimeError(f"agent did not produce a final answer within {MAX_TOOL_ROUNDS} tool rounds")

    async def _generate_with_retry(self) -> types.GenerateContentResponse:
        """The Gemini API genuinely returns transient 503s under load and
        429s on the free tier's quota (both observed live while building
        this agent, not hypothetical - a single customer message can cost
        4-5 calls through the tool-calling loop). A 429's response body
        names its own RetryInfo.retryDelay; honor that instead of a fixed
        backoff schedule for short waits, and rotate to the next API key
        for long ones (the daily cap, not a brief throttle). Anything else
        (bad request, auth, missing model) is a real bug and should raise
        immediately, not be retried."""
        last_error: Exception | None = None
        while True:
            for attempt in range(MAX_MODEL_RETRIES):
                try:
                    return self._client.models.generate_content(
                        model=self._model,
                        contents=self._contents,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            tools=[self._tool],
                        ),
                    )
                except genai_errors.APIError as exc:
                    if exc.code not in RETRYABLE_STATUS_CODES:
                        raise
                    last_error = exc
                    suggested = _retry_delay_seconds(exc)
                    if suggested is not None and suggested > KEY_EXHAUSTED_THRESHOLD_SECONDS:
                        break  # this key's quota is done for a long while - rotate, don't sleep
                    if attempt < MAX_MODEL_RETRIES - 1:
                        # Capped rather than honored verbatim for short waits: a
                        # quota blip can suggest ~60s, and that compounds across
                        # every tool-calling round in one respond() call
                        # (observed live: an uncapped version of this once hung
                        # for 30+ minutes mid-conversation).
                        delay = min(
                            suggested or (2**attempt) + random.uniform(0, 1),
                            MAX_RETRY_DELAY_SECONDS,
                        )
                        await asyncio.sleep(delay)
            # Exhausted this key's retry budget (or its quota is long-exhausted).
            if not self._rotate_key():
                assert last_error is not None
                raise last_error


def _retry_delay_seconds(exc: genai_errors.APIError) -> float | None:
    """Pull RetryInfo.retryDelay (e.g. "4.35s") out of a 429's error body,
    if the server sent one."""
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
