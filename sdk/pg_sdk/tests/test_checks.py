import sqlite3

from pg_sdk.checks import CheckSpec, run_check, run_checks


def _make_payments_db(tmp_path):
    db_path = tmp_path / "payments.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE refunds (
            id TEXT PRIMARY KEY, order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (order_id)
        );
        """
    )
    conn.close()
    return tmp_path


def _insert_refund(tmp_path, order_id="ord_1001", amount_cents=2499):
    conn = sqlite3.connect(tmp_path / "payments.db")
    conn.execute(
        "INSERT INTO refunds (id, order_id, amount_cents, reason, created_at) "
        "VALUES ('rf_1', ?, ?, 'customer request', '2026-10-08T00:00:00Z')",
        (order_id, amount_cents),
    )
    conn.commit()
    conn.close()


def test_refund_issued_exactly_once_passes_when_exactly_one_row_matches(tmp_path):
    _make_payments_db(tmp_path)
    _insert_refund(tmp_path)

    check = CheckSpec(
        description="refund issued exactly once for ord_1001",
        service="payments",
        sql="SELECT COUNT(*) AS n FROM refunds WHERE order_id = ?",
        params=("ord_1001",),
        expect={"n": 1},
    )
    result = run_check(tmp_path, check)

    assert result.passed
    assert result.actual == {"n": 1}


def test_refund_check_fails_when_no_refund_was_issued(tmp_path):
    _make_payments_db(tmp_path)

    check = CheckSpec(
        description="refund issued exactly once for ord_1001",
        service="payments",
        sql="SELECT COUNT(*) AS n FROM refunds WHERE order_id = ?",
        params=("ord_1001",),
        expect={"n": 1},
    )
    result = run_check(tmp_path, check)

    assert not result.passed
    assert result.actual == {"n": 0}


def test_check_fails_when_service_database_does_not_exist(tmp_path):
    check = CheckSpec(
        description="refund issued",
        service="payments",
        sql="SELECT COUNT(*) AS n FROM refunds",
        expect={"n": 1},
    )
    result = run_check(tmp_path, check)

    assert not result.passed
    assert "no such service database" in result.detail


def test_check_without_expect_passes_on_any_matching_row(tmp_path):
    _make_payments_db(tmp_path)
    _insert_refund(tmp_path)

    check = CheckSpec(
        description="a refund exists for ord_1001",
        service="payments",
        sql="SELECT * FROM refunds WHERE order_id = ?",
        params=("ord_1001",),
    )
    result = run_check(tmp_path, check)

    assert result.passed


def test_run_checks_runs_every_check_independently(tmp_path):
    _make_payments_db(tmp_path)
    _insert_refund(tmp_path)

    checks = [
        CheckSpec(
            description="refund amount correct",
            service="payments",
            sql="SELECT amount_cents AS n FROM refunds WHERE order_id = ?",
            params=("ord_1001",),
            expect={"n": 2499},
        ),
        CheckSpec(
            description="no refund for a different order",
            service="payments",
            sql="SELECT COUNT(*) AS n FROM refunds WHERE order_id = ?",
            params=("ord_9999",),
            expect={"n": 0},
        ),
    ]
    results = run_checks(tmp_path, checks)

    assert [r.passed for r in results] == [True, True]


def test_check_spec_from_dict_round_trips():
    spec = CheckSpec.from_dict(
        {
            "description": "refund issued exactly once",
            "service": "payments",
            "sql": "SELECT COUNT(*) AS n FROM refunds WHERE order_id = ?",
            "params": ["ord_1001"],
            "expect": {"n": 1},
        }
    )
    assert spec == CheckSpec(
        description="refund issued exactly once",
        service="payments",
        sql="SELECT COUNT(*) AS n FROM refunds WHERE order_id = ?",
        params=("ord_1001",),
        expect={"n": 1},
    )
