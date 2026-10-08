import importlib
import sys

import pytest


@pytest.fixture()
def server_module(tmp_path, monkeypatch):
    db_path = tmp_path / "email.db"
    monkeypatch.setenv("EMAIL_DB_PATH", str(db_path))
    sys.modules.pop("email_service.server", None)
    sys.modules.pop("email_service.db", None)
    return importlib.import_module("email_service.server")


def test_send_and_list_email(server_module):
    sent = server_module.send_email("amy@example.com", "Your refund", "It's processed.")
    assert sent["to_address"] == "amy@example.com"

    emails = server_module.list_emails("amy@example.com")
    assert len(emails) == 1
    assert emails[0]["subject"] == "Your refund"


def test_list_emails_empty_for_unknown_address(server_module):
    assert server_module.list_emails("nobody@example.com") == []
