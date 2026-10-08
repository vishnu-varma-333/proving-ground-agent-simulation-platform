import pg_worker.runner as runner_module


async def test_ensure_template_actually_creates_seeded_db_files(tmp_path, monkeypatch):
    """Regression test for a real bug: the first version of this function
    connected to the mock services and disconnected without calling any
    tool, and each service's db file is only created *inside* its first
    tool call - so the template directory came out empty every time,
    silently, with no error. Uses the real services as real subprocesses
    (same as scripts/smoke_test_mcp.py), not mocks, because the bug was
    specifically about what a real MCP connect does and doesn't trigger."""
    monkeypatch.setattr(runner_module, "TEMPLATES_DIR", tmp_path)

    template_dir = await runner_module.ensure_template("default")

    assert (template_dir / "orders.db").exists()
    assert (template_dir / "payments.db").exists()
    assert (template_dir / "email.db").exists()
    assert (template_dir / "orders.db").stat().st_size > 0


async def test_ensure_template_is_idempotent_and_does_not_reseed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "TEMPLATES_DIR", tmp_path)

    first = await runner_module.ensure_template("default")
    original_bytes = (first / "orders.db").read_bytes()

    second = await runner_module.ensure_template("default")

    assert second == first
    assert (second / "orders.db").read_bytes() == original_bytes
