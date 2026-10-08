from pg_sdk.environment import fork_environment


def test_fork_copies_every_db_file(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    (template / "orders.db").write_bytes(b"orders-data")
    (template / "payments.db").write_bytes(b"payments-data")
    (template / "notes.txt").write_bytes(b"not a db file")

    target = tmp_path / "fork-1"
    fork_environment(template, target)

    assert (target / "orders.db").read_bytes() == b"orders-data"
    assert (target / "payments.db").read_bytes() == b"payments-data"
    assert not (target / "notes.txt").exists(), "only *.db files should be forked"


def test_fork_is_isolated_from_the_template(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    (template / "orders.db").write_bytes(b"original")

    target = tmp_path / "fork-1"
    fork_environment(template, target)
    (target / "orders.db").write_bytes(b"mutated by this simulation")

    assert (template / "orders.db").read_bytes() == b"original", (
        "writing to a fork must never affect the template or any other fork"
    )


def test_two_forks_from_the_same_template_are_independent(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    (template / "orders.db").write_bytes(b"seed")

    fork_a = tmp_path / "fork-a"
    fork_b = tmp_path / "fork-b"
    fork_environment(template, fork_a)
    fork_environment(template, fork_b)
    (fork_a / "orders.db").write_bytes(b"mutated by fork-a only")

    assert (fork_b / "orders.db").read_bytes() == b"seed"
