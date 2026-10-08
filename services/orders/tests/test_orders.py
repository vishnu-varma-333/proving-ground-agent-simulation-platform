import importlib
import sys

import pytest


@pytest.fixture()
def server_module(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.db"
    monkeypatch.setenv("ORDERS_DB_PATH", str(db_path))
    sys.modules.pop("orders_service.server", None)
    sys.modules.pop("orders_service.db", None)
    return importlib.import_module("orders_service.server")


def test_get_order_found(server_module):
    order = server_module.get_order("ord_1001")
    assert order["customer_id"] == "cust_amy"
    assert "error" not in order


def test_get_order_not_found(server_module):
    assert "error" in server_module.get_order("does_not_exist")


def test_list_orders_by_customer(server_module):
    orders = server_module.list_orders_by_customer("cust_amy")
    assert {o["id"] for o in orders} == {"ord_1001", "ord_1002"}


def test_update_order_status(server_module):
    updated = server_module.update_order_status("ord_1001", "refunded")
    assert updated["status"] == "refunded"
    assert server_module.get_order("ord_1001")["status"] == "refunded"


def test_update_order_status_rejects_invalid_status(server_module):
    result = server_module.update_order_status("ord_1001", "not_a_real_status")
    assert "error" in result
