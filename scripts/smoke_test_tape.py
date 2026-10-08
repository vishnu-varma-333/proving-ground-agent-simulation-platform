"""Live smoke test: writes a blob and a run manifest through pg_sdk's real
BlobStore against whatever S3-compatible endpoint PG_S3_* points at (the
local SeaweedFS gateway by default), then reads them back. Proves the SDK
actually talks to real object storage, not just a fake store in unit
tests. Run with:

    uv run python scripts/smoke_test_tape.py
"""

from __future__ import annotations

from pg_sdk import BlobStore, Recorder


def main() -> None:
    store = BlobStore()
    run_id = "smoke-test-run"
    recorder = Recorder(store=store, run_id=run_id, agent_name="smoke-test")

    step = recorder.record_model_call(
        "fake-model", {"prompt": "hello"}, {"text": "hello back"}
    )
    print(f"recorded model step: seq={step.seq} input_hash={step.input_hash[:12]}...")

    step2 = recorder.record_tool_call("get_order", {"order_id": "ord_1"}, {"status": "ok"})
    print(f"recorded tool step: seq={step2.seq}")

    manifest = recorder.finalize()
    print(f"manifest written: {manifest['step_count']} steps")

    # Read everything back from real storage, independent of the recorder
    # that wrote it - this is the part that actually proves round-tripping
    # through S3 works, not just that local Python objects are consistent.
    fetched_manifest = store.get_manifest(run_id)
    assert fetched_manifest == manifest, "manifest read back from S3 must match what was written"

    fetched_step0 = store.get_step(run_id, 0)
    assert fetched_step0["kind"] == "model"

    input_blob = store.get_blob(step.input_hash)
    assert b"hello" in input_blob

    assert store.blob_exists(step.output_hash)
    assert not store.blob_exists("0" * 64), "a hash that was never written must not exist"

    print("All blobs, steps and the manifest round-tripped through real S3-compatible storage.")


if __name__ == "__main__":
    main()
