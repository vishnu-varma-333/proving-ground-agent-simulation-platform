"""The reference agent: a customer-support assistant that can look up
orders, check payments, issue refunds, and send confirmation emails by
calling the three mock services' MCP tools through Gemini function
calling.

Recording (Milestone 3) is opt-in via an optional pg_sdk.Recorder passed
to the constructor: with none, this is exactly the Milestone 2 agent with
no platform dependency at all. With one, every model call, tool call and
clock read is captured to a tape. Converting Gemini's own types to and
from the plain dicts pg_sdk.Recorder expects happens here, not in the
SDK - the SDK doesn't know or care what model this agent uses.
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
from pg_sdk import Player, Recorder, RecordingClock

from reference_agent.mcp_tools import MockServiceToolbox

# Quota is tracked per (API key, model) pair - confirmed live via each 429's
# own quotaId naming the model (e.g.
# "GenerateRequestsPerDayPerProjectPerModel-FreeTier") - so a different
# model on the SAME key is a genuinely separate daily budget, not a
# workaround that merely feels like one. Free-tier RPD differs hugely by
# model (per ai.google.dev/gemini-api/docs/rate-limits: the lite tier is
# ~500/day vs. the full flash tier's ~20/day), and this agent's own task
# (a handful of simple lookup/refund/email tool calls) doesn't need
# frontier-level reasoning, so the cheap/high-quota model goes first.
MODEL_CANDIDATES = ("gemini-flash-lite-latest", "gemini-3.8-flash")
DEFAULT_MODEL = MODEL_CANDIDATES[0]

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

# google-genai leaves HttpOptions.timeout unset by default, which means NO
# timeout reaches the underlying httpx client at all (None means "wait
# forever", not "use some sane default"). Observed live: a stalled request
# with this unset blocked silently for 30+ minutes with zero output and
# zero exception, because nothing ever fired to interrupt it - not a retry
# problem, there was nothing for a retry wrapper to catch. Every request
# gets this bound explicitly for that reason.
REQUEST_TIMEOUT_MS = 30_000

# A 429 suggesting a wait longer than this is the free tier's *daily* quota
# talking (observed live: "Please retry in 22h36m...") - not the kind of
# brief throttle worth sleeping through. Rotate to the next configured key
# instead. Below this threshold it's treated as transient (Milestone 2's
# earlier finding: a per-minute quota blip) and retried on the same key.
KEY_EXHAUSTED_THRESHOLD_SECONDS = 120.0


_KEY_VAR_PATTERN = re.compile(r"^GEMINI_API_KEY_?(\d*)$")


def load_api_keys() -> list[str]:
    """Every env var matching GEMINI_API_KEY, GEMINI_API_KEY2,
    GEMINI_API_KEY_2, GEMINI_API_KEY5, ... - any numeric suffix, with or
    without an underscore, gaps allowed. Deliberately lenient: observed
    live that keys added by hand didn't follow a fixed convention (one
    arrived as GEMINI_API_KEY2, a later one as GEMINI_API_KEY5 with no
    GEMINI_API_KEY/2/3/4 ever set) - a strict sequential scanner silently
    missed keys that didn't fit the pattern it expected. Sorted so
    GEMINI_API_KEY (bare, suffix "") always goes first, then by numeric
    suffix. Multiple personal free-tier keys are a dev-time workaround for
    the daily quota cap (see DECISIONS.md) - not how the platform's own
    model-call layer will handle cost/throughput in Milestone 3+."""
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


class ReferenceAgent:
    def __init__(
        self,
        toolbox: MockServiceToolbox,
        model: str | None = None,
        api_keys: list[str] | None = None,
        recorder: Recorder | None = None,
        player: Player | None = None,
    ) -> None:
        """`model=None` (the default) rotates across MODEL_CANDIDATES on
        quota exhaustion; passing an explicit model pins to just that one
        (used by tests that don't care about model rotation). `recorder`
        is None by default (plain Milestone 2 behavior, no platform
        dependency); pass a pg_sdk.Recorder to capture a tape.

        `player` replays a previously recorded tape instead of making any
        live call: no Gemini API key, no running MCP servers, and no
        network at all are needed in this mode - every model call, tool
        call and clock read is served from the tape (and checked against
        it; see pg_sdk.Player). Mutually exclusive with `recorder` - a
        run is either being recorded or replayed, never both."""
        if recorder is not None and player is not None:
            raise ValueError("pass recorder or player, not both")
        self._toolbox = toolbox
        self._models = [model] if model is not None else list(MODEL_CANDIDATES)
        self._model_index = 0
        self._player = player
        self._recorder = recorder
        self._clock = RecordingClock(recorder) if recorder is not None else None
        self._contents: list[types.Content] = []

        if player is None:
            self._api_keys = api_keys if api_keys is not None else load_api_keys()
            if not self._api_keys:
                raise RuntimeError("no Gemini API key set (GEMINI_API_KEY)")
            self._key_index = 0
            self._client = self._make_client(self._api_keys[0])
            self._tool = types.Tool(function_declarations=toolbox.function_declarations)
        else:
            # Replay touches none of this - no key, no client, no live
            # tool schema (the toolbox itself never needs to be connected).
            self._api_keys = []
            self._key_index = 0
            self._client = None
            self._tool = None

    @property
    def _model(self) -> str:
        return self._models[self._model_index]

    @staticmethod
    def _make_client(api_key: str) -> genai.Client:
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )

    def _rotate_slot(self) -> bool:
        """Quota is exhausted for the current (key, model) pair. Try the
        next model on the SAME key first (a separate quota bucket, same
        account - decision 9/MODEL_CANDIDATES above); only rotate to the
        next key once every model has been tried on this one."""
        if self._model_index + 1 < len(self._models):
            self._model_index += 1
            print(
                f"[reference_agent] {self._models[self._model_index - 1]} exhausted its "
                f"quota on key {self._key_index + 1}, switching to model "
                f"{self._model!r}",
                flush=True,
            )
            return True
        if self._key_index + 1 < len(self._api_keys):
            self._key_index += 1
            self._model_index = 0
            self._client = self._make_client(self._api_keys[self._key_index])
            print(
                f"[reference_agent] every model exhausted on key {self._key_index}, "
                f"switching to key {self._key_index + 1}/{len(self._api_keys)}",
                flush=True,
            )
            return True
        return False

    async def respond(self, user_message: str) -> str:
        if self._player is not None:
            await asyncio.to_thread(self._player.replay_clock_read)
        elif self._clock is not None:
            await asyncio.to_thread(self._clock.now)

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
                args = dict(call.args or {})
                if self._player is not None:
                    result = await asyncio.to_thread(
                        self._player.replay_tool_call, call.name, args
                    )
                else:
                    try:
                        result = await self._toolbox.call(call.name, args)
                    except Exception as exc:  # noqa: BLE001 - any tool failure must become a result, not a crash
                        # A tool call can genuinely fail now (Milestone 7's
                        # fault injection: a simulated timeout/outage) - feed
                        # the failure back to the model as a tool result
                        # instead of crashing the whole conversation, so the
                        # agent can react (retry, apologize, try another
                        # path) the way a real agent would have to.
                        result = {"error": f"{call.name} failed: {exc}"}
                    if self._recorder is not None:
                        await asyncio.to_thread(
                            self._recorder.record_tool_call, call.name, args, result
                        )
                response_parts.append(
                    types.Part.from_function_response(name=call.name, response=result)
                )
            self._contents.append(types.Content(role="user", parts=response_parts))

        raise RuntimeError(f"agent did not produce a final answer within {MAX_TOOL_ROUNDS} tool rounds")

    def _call_model(self) -> types.GenerateContentResponse:
        request_dict = {
            "model": self._model,
            "system_instruction": SYSTEM_INSTRUCTION,
            "contents": [c.model_dump(mode="json", exclude_none=True) for c in self._contents],
        }

        if self._player is not None:
            # No live call at all: the exact recorded response comes back,
            # or pg_sdk.Player raises if this request doesn't match what
            # was recorded for this step (a real determinism violation).
            response_dict = self._player.replay_model_call(self._model, request_dict)
            return types.GenerateContentResponse.model_validate(response_dict)

        response = self._client.models.generate_content(
            model=self._model,
            contents=self._contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[self._tool],
            ),
        )
        if self._recorder is not None:
            response_dict = response.model_dump(mode="json", exclude_none=True)
            self._recorder.record_model_call(self._model, request_dict, response_dict)
        return response

    async def _generate_with_retry(self) -> types.GenerateContentResponse:
        """The Gemini API genuinely returns transient 503s under load and
        429s on the free tier's quota (both observed live while building
        this agent, not hypothetical - a single customer message can cost
        4-5 calls through the tool-calling loop). A 429's response body
        names its own RetryInfo.retryDelay; honor that instead of a fixed
        backoff schedule for short waits, and rotate to the next API key
        for long ones (the daily cap, not a brief throttle). A timeout or
        connect error (REQUEST_TIMEOUT_MS firing) is retried the same way
        as a 503 - it's not quota-related, so never triggers key rotation.
        Anything else (bad request, auth, missing model) is a real bug and
        should raise immediately, not be retried."""
        last_error: Exception | None = None
        while True:
            for attempt in range(MAX_MODEL_RETRIES):
                try:
                    # generate_content is synchronous; run it off-thread so
                    # it can't block the event loop (and so REQUEST_TIMEOUT_MS
                    # is actually what bounds this call, not an unbounded
                    # synchronous wait inside an async function).
                    return await asyncio.to_thread(self._call_model)
                except genai_errors.APIError as exc:
                    if exc.code not in RETRYABLE_STATUS_CODES:
                        raise
                    last_error = exc
                    suggested = _retry_delay_seconds(exc)
                    if suggested is not None and suggested > KEY_EXHAUSTED_THRESHOLD_SECONDS:
                        break  # this key's quota is done for a long while - rotate, don't sleep
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    last_error = exc
                    suggested = None

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
            if not self._rotate_slot():
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
