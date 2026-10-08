import importlib
import sys

import pytest


@pytest.fixture()
def server_module(tmp_path, monkeypatch):
    db_path = tmp_path / "payments.db"
    monkeypatch.setenv("PAYMENTS_DB_PATH", str(db_path))
    sys.modules.pop("payments_service.server", None)
    sys.modules.pop("payments_service.db", None)
    module = importlib.import_module("payments_service.server")
    return module


def test_issue_refund_is_idempotent(server_module):
    first = server_module.issue_refund("ord_1001", 2499, "customer request")
    assert first["already_refunded"] is False
    assert first["amount_cents"] == 2499

    second = server_module.issue_refund("ord_1001", 2499, "customer request, again")
    assert second["already_refunded"] is True
    assert second["id"] == first["id"], "second call must return the SAME refund, not a new one"

    refunds = server_module.list_refunds("ord_1001")
    assert len(refunds) == 1, "exactly one refund must exist no matter how many times it's requested"


def test_issue_refund_rejects_amount_over_captured(server_module):
    result = server_module.issue_refund("ord_1001", 999_999, "too much")
    assert "error" in result
    assert server_module.list_refunds("ord_1001") == []


def test_issue_refund_unknown_order(server_module):
    result = server_module.issue_refund("ord_does_not_exist", 100, "n/a")
    assert "error" in result
