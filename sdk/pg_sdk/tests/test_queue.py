from pg_sdk.queue import FairDispatcher, SimulationJob, build_weighted_cycle, subject_for_run


def test_build_weighted_cycle_default_priority_one_turn_each():
    cycle = build_weighted_cycle([("run-a", 1), ("run-b", 1)])
    assert cycle.count("run-a") == 1
    assert cycle.count("run-b") == 1


def test_build_weighted_cycle_higher_priority_gets_more_turns():
    cycle = build_weighted_cycle([("run-big", 1), ("run-vip", 3)])
    assert cycle.count("run-vip") == 3
    assert cycle.count("run-big") == 1


def test_build_weighted_cycle_priority_zero_still_gets_one_turn():
    """A priority of 0 must not mean "never scheduled" - every active
    run gets at least one turn, or a misconfigured priority could starve
    a run entirely, which is the exact failure this feature exists to
    prevent."""
    cycle = build_weighted_cycle([("run-a", 0)])
    assert cycle.count("run-a") == 1


def test_subject_for_run_is_distinct_per_run():
    assert subject_for_run("run-1") != subject_for_run("run-2")


def test_simulation_job_round_trips_through_json():
    job = SimulationJob(
        sim_id="sim-1",
        run_id="run-1",
        scenario_id="scenario-1",
        seed=42,
        agent_version_id="agent-v1",
    )
    restored = SimulationJob.from_json(job.to_json())
    assert restored == job


class _FakeSub:
    """Stands in for a JetStreamContext.PullSubscription: returns one
    canned message the first time fetch() is called, then times out."""

    def __init__(self, message: str | None) -> None:
        self._message = message
        self._served = False

    async def fetch(self, batch: int, timeout: float):
        if self._served or self._message is None:
            raise TimeoutError
        self._served = True
        return [self._message]


async def test_fair_dispatcher_alternates_between_two_equal_priority_runs():
    dispatcher = FairDispatcher(js=None)
    dispatcher._subs = {"run-a": _FakeSub("msg-a"), "run-b": _FakeSub("msg-b")}
    dispatcher._cycle = build_weighted_cycle([("run-a", 1), ("run-b", 1)])

    first = await dispatcher.fetch_one()
    second = await dispatcher.fetch_one()

    assert {first, second} == {"msg-a", "msg-b"}, "both runs must be served within one cycle"


async def test_fair_dispatcher_skips_a_run_with_nothing_pending_right_now():
    dispatcher = FairDispatcher(js=None)
    dispatcher._subs = {"run-empty": _FakeSub(None), "run-ready": _FakeSub("msg-ready")}
    dispatcher._cycle = build_weighted_cycle([("run-empty", 1), ("run-ready", 1)])

    result = await dispatcher.fetch_one()

    assert result == "msg-ready", "a run with nothing pending must not block the one that has work"


async def test_fair_dispatcher_vip_run_gets_more_turns_within_one_cycle():
    dispatcher = FairDispatcher(js=None)
    # run-vip "has" 3 messages worth of priority-weighted turns; our fake
    # only ever serves one, so this checks the CYCLE gives it 3 attempts
    # before run-normal gets its single turn, not that 3 messages exist.
    dispatcher._cycle = build_weighted_cycle([("run-vip", 3), ("run-normal", 1)])

    assert dispatcher._cycle == ["run-vip", "run-vip", "run-vip", "run-normal"]


class _FakeJS:
    """Just enough of JetStreamContext for refresh() to call
    add_consumer/pull_subscribe against - returns an endless fake sub per
    run so fetch() always has something to serve, letting these tests
    isolate the rotation logic from message availability entirely."""

    async def add_consumer(self, stream, config):
        pass

    async def pull_subscribe(self, subject, durable, stream):
        return _EndlessFakeSub(durable)


class _EndlessFakeSub:
    def __init__(self, name: str) -> None:
        self.name = name

    async def fetch(self, batch: int, timeout: float):
        return [f"msg-from-{self.name}"]


async def test_refresh_does_not_reset_rotation_when_the_active_run_set_is_unchanged():
    """The real bug this guards against: the worker calls refresh() before
    EVERY fetch_one(), since active runs can change between fetches. If
    refresh() unconditionally reset _cycle_pos to 0, rotation would never
    actually advance across separate fetch_one() calls - the first run in
    Postgres's sort order would be tried first on every single fetch and
    would dominate for as long as it has anything pending, which is
    exactly the starvation this whole mechanism exists to prevent."""
    dispatcher = FairDispatcher(js=_FakeJS())
    active_runs = [("run-a", 1), ("run-b", 1)]

    served = []
    for _ in range(4):
        await dispatcher.refresh(active_runs)
        msg = await dispatcher.fetch_one()
        served.append(msg)

    assert served == [
        "msg-from-worker-run-a",
        "msg-from-worker-run-b",
        "msg-from-worker-run-a",
        "msg-from-worker-run-b",
    ], f"rotation must advance across refresh+fetch cycles, got {served}"
