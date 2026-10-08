# What is and isn't deterministic

The spec's own Documentation requirement for v1: "a document stating
exactly what is and isn't deterministic." The short version: everything
the reference agent's own logic depends on to decide what to do next is
recorded and replayed exactly, hash-verified at every step; a few
things outside that boundary are not, and are listed here rather than
left for someone to discover by a replay that silently doesn't match.

## What's recorded and replayed, hash-verified

Every one of these goes through `pg_sdk.Recorder` while live, and
`pg_sdk.Player` while replaying - replay recomputes each step's
*request* the same way the recorder did and compares its hash against
what was recorded (`pg_sdk/player.py`'s `_next`), not just "serve the
next recorded output in order." A mismatch (`ReplayMismatch`) means the
code *surrounding* the model/tool/clock answers took a different path
than it did when recorded, given the exact same answers - that's the
real determinism violation a replay is for catching.

- **Every model call** (`record_model_call` / `replay_model_call`):
  the full request (conversation history, system instruction, model
  name) and response.
- **Every tool call** (`record_tool_call` / `replay_tool_call`):
  arguments and result - including a fault-injected result
  (`FaultInjectingToolbox` is a wrapper the agent calls through; what
  it returns, error or delayed-then-real response, is what gets
  recorded, so a faulted run replays the same observed behavior. The
  injected *latency itself* is not replayed - see below).
- **Every clock read** (`record_clock_read` / `replay_clock_read`):
  the `SimulatedClock`'s value at that point.
- **Every simulated-user turn** (`record_user_turn` /
  `replay_user_turn`, Milestone 10): the persona-generated message
  that drove each turn of a `simulated_user: true` scenario. Added
  this milestone - the spec's own Step data model already named `user`
  as one of four step kinds; `pg_sdk.recorder.StepKind` only had three
  until this was noticed while building `pg replay`, meaning every
  multi-turn scenario recorded before Milestone 10 can't be replayed
  (the agent's own steps are on the tape, but nothing recorded what the
  persona actually said to produce them). Scenarios recorded afterward
  replay fully; this is a genuine compatibility break with Milestone 8's
  own tapes and is why it's called out explicitly rather than only in
  DECISIONS.md.

A user turn is replayed *as given*, not independently re-verified the
way a model/tool request is: there's no deterministic way to recompute
"what the persona would have said" to hash-check against, since that
message came from a second, independent live model call at record
time (`agents/simulated_user`). What replay *does* verify is everything
downstream of it - the agent's own request/response for having reacted
to that exact message.

## What replay does NOT reproduce

- **Model/key rotation state.** If a live run's free-tier quota ran
  out mid-conversation and rotated to a different (key, model) slot
  (`ReferenceAgent._rotate_slot`), replay has no record of *when* that
  happened - replaying starts at the same first candidate every time,
  since nothing during replay ever raises the quota error that
  triggers rotation live. A recording that rotated mid-conversation
  will correctly fail its hash check on a later step, but not for a
  reason that's useful to read at face value. See DECISIONS.md,
  decision 15.
- **Injected latency.** `FaultInjectingToolbox`'s `latency` fault
  really sleeps during recording; replay never touches
  `FaultInjectingToolbox` at all (it talks only to the tape), so a
  replayed run finishes in roughly the time its real model/tool calls
  would have taken minus every second of real network latency, fault-
  injected or not - consistent with virtual time's own "multi-day
  scenario in seconds" goal, just via tape-serving instead of a
  simulated clock.
- **Live-run retry jitter.** `_generate_with_retry`'s backoff
  (`random.uniform(0, 1)` added to each delay) only affects how long a
  *live* run waits between retries - it has no effect on what ends up
  recorded, so it isn't a replay concern at all, just not literally
  reproducible if someone timed a live run stopwatch-in-hand.
- **Concurrency inside the agent.** `ReferenceAgent.respond()` issues
  tool calls in a plain sequential `for` loop, one at a time, and the
  recorder assigns sequence numbers in call order - this agent has no
  concurrency to go wrong today. A future agent integration that
  issued several tool calls in parallel (`asyncio.gather` over
  multiple `toolbox.call()`s) would have its steps race for sequence
  numbers non-deterministically, which the SDK does not protect
  against - the spec's own prompt ("what can still break replay, such
  as concurrency inside the agent") names exactly this as the kind of
  thing to watch for; it's a real, open boundary of the current SDK,
  not yet needed by any agent integration this project has built.

## Scope: this is about the reference agent's logic, not infrastructure

Determinism here means "does the agent, judge, and simulated user
*decide the same things* given the same upstream answers" - not "does
a rerun of the whole distributed system produce byte-identical wall-
clock timestamps, worker ids, or NATS message ids." `worker_lease`
(`uuid.uuid4()`), `recorded_at` timestamps on each step, and which
physical worker pod processed a simulation are expected to differ
between a live run and any later replay (replay doesn't even go
through the scheduler/queue at all - `pg replay <sim-id>` runs the
agent directly against the tape, same proof-by-construction as
`reference_agent`'s own lower-level `--replay` flag: no live API, no
MCP servers, no network).
