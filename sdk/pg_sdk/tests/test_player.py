import pytest
from pg_sdk.player import Player, ReplayMismatch, TapeExhausted, TapeOrderMismatch
from pg_sdk.recorder import Recorder


class FakeBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.manifests: dict[str, dict] = {}

    def put_blob(self, data: bytes) -> str:
        from pg_sdk.hashing import content_hash

        digest = content_hash(data)
        self.blobs[digest] = data
        return digest

    def get_blob(self, digest: str) -> bytes:
        return self.blobs[digest]

    def put_step(self, run_id: str, seq: int, step: dict) -> None:
        pass  # Player only reads the manifest, not individual step files

    def put_manifest(self, run_id: str, manifest: dict) -> None:
        self.manifests[run_id] = manifest

    def get_manifest(self, run_id: str) -> dict:
        return self.manifests[run_id]


def _recorded_run(store: FakeBlobStore, run_id: str = "run-1") -> None:
    recorder = Recorder(store=store, run_id=run_id, agent_name="test-agent")
    recorder.record_model_call("gemini", {"prompt": "hi"}, {"text": "hello"})
    recorder.record_tool_call("get_order", {"order_id": "a"}, {"status": "delivered"})
    recorder.finalize()


def test_replay_serves_recorded_outputs_in_order():
    store = FakeBlobStore()
    _recorded_run(store)
    player = Player(store, "run-1")

    model_out = player.replay_model_call("gemini", {"prompt": "hi"})
    assert model_out == {"text": "hello"}

    tool_out = player.replay_tool_call("get_order", {"order_id": "a"})
    assert tool_out == {"status": "delivered"}

    assert player.finished


def test_replay_raises_when_tape_exhausted():
    store = FakeBlobStore()
    _recorded_run(store)
    player = Player(store, "run-1")
    player.replay_model_call("gemini", {"prompt": "hi"})
    player.replay_tool_call("get_order", {"order_id": "a"})

    with pytest.raises(TapeExhausted):
        player.replay_tool_call("get_order", {"order_id": "a"})


def test_replay_raises_on_kind_name_mismatch():
    store = FakeBlobStore()
    _recorded_run(store)
    player = Player(store, "run-1")

    with pytest.raises(TapeOrderMismatch):
        # tape's first step is a model call, not a tool call
        player.replay_tool_call("get_order", {"order_id": "a"})


def test_replay_raises_determinism_violation_on_different_request():
    store = FakeBlobStore()
    _recorded_run(store)
    player = Player(store, "run-1")

    with pytest.raises(ReplayMismatch) as exc_info:
        # same kind/name as the tape's first step, but different content
        player.replay_model_call("gemini", {"prompt": "a completely different prompt"})

    assert exc_info.value.seq == 0
    assert "determinism violation" in str(exc_info.value)


def test_replay_clock_read_returns_the_recorded_value():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-2", agent_name="test-agent")
    recorder.record_clock_read("2026-01-01T00:00:00+00:00")
    recorder.finalize()

    player = Player(store, "run-2")
    assert player.replay_clock_read() == "2026-01-01T00:00:00+00:00"


def test_replay_user_turn_returns_the_recorded_message():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-4", agent_name="test-agent")
    recorder.record_user_turn("Hi, I need a refund for ord_1001")
    recorder.record_model_call("gemini", {"prompt": "hi"}, {"text": "hello"})
    recorder.finalize()

    player = Player(store, "run-4")
    assert player.replay_user_turn() == "Hi, I need a refund for ord_1001"
    assert player.replay_model_call("gemini", {"prompt": "hi"}) == {"text": "hello"}


def test_replay_user_turn_raises_order_mismatch_when_next_step_isnt_a_user_turn():
    store = FakeBlobStore()
    _recorded_run(store, run_id="run-5")
    player = Player(store, "run-5")

    with pytest.raises(TapeOrderMismatch):
        player.replay_user_turn()


def test_next_step_kind_reports_without_consuming():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-6", agent_name="test-agent")
    recorder.record_user_turn("hi")
    recorder.finalize()

    player = Player(store, "run-6")
    assert player.next_step_kind == "user"
    assert player.next_step_kind == "user"  # calling it again must not advance the cursor
    player.replay_user_turn()
    assert player.next_step_kind is None  # tape exhausted


def test_player_reads_manifest_fresh_not_sharing_recorder_state():
    """Player only ever talks to the store, never to the Recorder object
    that produced the tape - this proves replay genuinely doesn't depend
    on the original recording session still being alive."""
    store = FakeBlobStore()
    _recorded_run(store, run_id="run-3")

    # Simulate a brand new process: a fresh store object with the same
    # backing data, no reference to the original Recorder at all.
    fresh_store = FakeBlobStore()
    fresh_store.blobs = dict(store.blobs)
    fresh_store.manifests = dict(store.manifests)

    player = Player(fresh_store, "run-3")
    assert player.replay_model_call("gemini", {"prompt": "hi"}) == {"text": "hello"}
