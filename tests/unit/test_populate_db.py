"""Unit tests for populate_db — a fresh data import seeds the
``token_balance`` payment-method row idempotently, so the checkout selector
lists it without any admin click."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_populate_db_creates_the_token_balance_method_on_fresh_install():
    with patch(
        "plugins.token_payment.populate_db.PaymentMethodRepository"
    ) as repo_cls, patch("plugins.token_payment.populate_db.db") as db_mock:
        repo = MagicMock()
        repo.find_by_code.return_value = None  # fresh DB
        repo_cls.return_value = repo

        from plugins.token_payment.populate_db import populate_db

        populate_db()

        repo.find_by_code.assert_called_once_with("token_balance")
        repo.save.assert_called_once()
        saved = repo.save.call_args.args[0]
        assert saved.code == "token_balance"
        assert saved.plugin_id == "token_payment"
        assert saved.is_active is True
        db_mock.session.commit.assert_called_once()


def test_populate_db_is_idempotent_when_row_already_active():
    existing = SimpleNamespace(code="token_balance", is_active=True)
    with patch(
        "plugins.token_payment.populate_db.PaymentMethodRepository"
    ) as repo_cls, patch("plugins.token_payment.populate_db.db"):
        repo = MagicMock()
        repo.find_by_code.return_value = existing
        repo_cls.return_value = repo

        from plugins.token_payment.populate_db import populate_db

        populate_db()

        # No new row created; existing one re-saved (still active — no-op effect).
        repo.save.assert_called_once_with(existing)
        assert existing.is_active is True
