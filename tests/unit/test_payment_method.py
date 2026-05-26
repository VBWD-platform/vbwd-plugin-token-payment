"""Unit tests for the payment-method record upsert/deactivate helpers.

The plugin registers a ``token_balance`` row in ``vbwd_payment_method`` on enable
so the data-driven checkout selector lists it. On disable the row is deactivated
(not deleted — keep historical references).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from plugins.token_payment.token_payment.payment_method import (
    upsert_token_balance_method,
    deactivate_token_balance_method,
)


def test_upsert_creates_when_absent():
    repo = MagicMock()
    repo.find_by_code.return_value = None
    upsert_token_balance_method(repo)
    repo.find_by_code.assert_called_once_with("token_balance")
    repo.save.assert_called_once()
    saved = repo.save.call_args.args[0]
    assert saved.code == "token_balance"
    assert saved.plugin_id == "token_payment"
    assert saved.is_active is True


def test_upsert_activates_when_present_but_inactive():
    existing = SimpleNamespace(code="token_balance", is_active=False)
    repo = MagicMock()
    repo.find_by_code.return_value = existing
    upsert_token_balance_method(repo)
    assert existing.is_active is True
    repo.save.assert_called_once_with(existing)


def test_upsert_is_idempotent_when_already_active():
    existing = SimpleNamespace(code="token_balance", is_active=True)
    repo = MagicMock()
    repo.find_by_code.return_value = existing
    upsert_token_balance_method(repo)
    # Still active; saved (idempotent — no harm).
    assert existing.is_active is True


def test_deactivate_marks_inactive():
    existing = SimpleNamespace(code="token_balance", is_active=True)
    repo = MagicMock()
    repo.find_by_code.return_value = existing
    deactivate_token_balance_method(repo)
    assert existing.is_active is False
    repo.save.assert_called_once_with(existing)


def test_deactivate_is_a_noop_when_absent():
    repo = MagicMock()
    repo.find_by_code.return_value = None
    deactivate_token_balance_method(repo)
    repo.save.assert_not_called()
