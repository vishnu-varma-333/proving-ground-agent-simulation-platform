from pg_sdk.clock import RecordingClock
from pg_sdk.hashing import content_hash
from pg_sdk.recorder import Recorder


class FakeBlobStore:
    """Records every call instead of talking to S3, so these tests exercise
    the recorder's own logic (sequencing, hashing, manifest shape) without
    needing a real object store."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.steps: dict[tuple[str, int], dict] = {}
        self.manifests: dict[str, dict] = {}

    def put_blob(self, data: bytes) -> str:
        digest = content_hash(data)
        self.blobs[digest] = data
        return digest

    def put_step(self, run_id: str, seq: int, step: dict) -> None:
        self.steps[(run_id, seq)] = step

    def put_manifest(self, run_id: str, manifest: dict) -> None:
        self.manifests[run_id] = manifest


def test_record_model_call_assigns_sequential_seq_numbers():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-1", agent_name="test-agent")

    step0 = recorder.record_model_call("gemini", {"prompt": "hi"}, {"text": "hello"})
    step1 = recorder.record_model_call("gemini", {"prompt": "bye"}, {"text": "goodbye"})

    assert step0.seq == 0
    assert step1.seq == 1


def test_identical_requests_produce_identical_input_hash():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-1", agent_name="test-agent")

    step0 = recorder.record_model_call("gemini", {"prompt": "hi"}, {"text": "hello"})
    step1 = recorder.record_model_call("gemini", {"prompt": "hi"}, {"text": "hello, again"})

    assert step0.input_hash == step1.input_hash, "same request content must hash the same"
    assert step0.output_hash != step1.output_hash, "different responses must hash differently"


def test_dict_key_order_does_not_change_the_hash():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-1", agent_name="test-agent")

    step0 = recorder.record_tool_call("get_order", {"order_id": "a", "x": 1}, {"ok": True})
    step1 = recorder.record_tool_call("get_order", {"x": 1, "order_id": "a"}, {"ok": True})

    assert step0.input_hash == step1.input_hash


def test_tool_call_dedup_means_only_distinct_blobs_are_stored():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-1", agent_name="test-agent")

    recorder.record_tool_call("get_order", {"order_id": "a"}, {"status": "delivered"})
    recorder.record_tool_call("get_order", {"order_id": "a"}, {"status": "delivered"})

    # two identical (request, response) pairs -> exactly 2 distinct blobs
    # (one for the shared request, one for the shared response), not 4.
    assert len(store.blobs) == 2


def test_clock_read_is_recorded_as_its_own_kind():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-1", agent_name="test-agent")
    clock = RecordingClock(recorder)

    value = clock.now()

    assert len(recorder._steps) == 1
    step = recorder._steps[0]
    assert step.kind == "clock"
    assert value  # a real ISO timestamp string was returned to the caller


def test_finalize_produces_an_ordered_manifest():
    store = FakeBlobStore()
    recorder = Recorder(store=store, run_id="run-42", agent_name="test-agent")

    recorder.record_model_call("gemini", {"a": 1}, {"b": 1})
    recorder.record_tool_call("send_email", {"to": "x"}, {"sent": True})

    manifest = recorder.finalize()

    assert manifest["run_id"] == "run-42"
    assert manifest["step_count"] == 2
    assert [s["kind"] for s in manifest["steps"]] == ["model", "tool"]
    assert [s["seq"] for s in manifest["steps"]] == [0, 1]
    assert store.manifests["run-42"] == manifest
