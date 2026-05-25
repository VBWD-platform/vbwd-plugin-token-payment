"""Unit tests for TokenPaymentService — fake TokenService, no DB."""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from plugins.token_payment.token_payment.service import TokenPaymentService
from vbwd.models.enums import TokenTransactionType


def test_compute_tokens_needed_rounds_up():
    assert TokenPaymentService.compute_tokens_needed("9.99", "0.05") == 200
    assert TokenPaymentService.compute_tokens_needed("10.00", "0.05") == 200
    assert TokenPaymentService.compute_tokens_needed("0.01", "0.05") == 1
    assert TokenPaymentService.compute_tokens_needed("0.00", "0.05") == 0


def test_rate_lookup_is_case_insensitive():
    service = TokenPaymentService(MagicMock(), {"usd": 0.05})
    assert service.rate_for("USD") == Decimal("0.05")
    assert service.rate_for("usd") == Decimal("0.05")


def test_missing_or_nonpositive_rate_is_none():
    service = TokenPaymentService(MagicMock(), {"USD": 0})
    assert service.rate_for("USD") is None
    assert service.rate_for("JPY") is None


def test_quote_available_and_sufficient(fake_token_service, make_invoice):
    fake_token_service.get_balance.return_value = 500
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    quote = service.quote(uuid4(), make_invoice("9.99", "USD"))
    assert quote["available"] is True
    assert quote["tokens_needed"] == 200
    assert quote["balance"] == 500
    assert quote["balance_after"] == 300
    assert quote["sufficient"] is True


def test_quote_insufficient(fake_token_service, make_invoice):
    fake_token_service.get_balance.return_value = 100
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    quote = service.quote(uuid4(), make_invoice("9.99", "USD"))
    assert quote["sufficient"] is False
    assert quote["balance_after"] == -100


def test_quote_unavailable_when_no_rate_for_currency(fake_token_service, make_invoice):
    fake_token_service.get_balance.return_value = 100
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    quote = service.quote(uuid4(), make_invoice("9.99", "JPY"))
    assert quote["available"] is False
    assert quote["reason"] == "no_rate_for_currency"
    assert quote["balance"] == 100


def test_debit_for_invoice_uses_usage_type_and_invoice_reference(
    fake_token_service, make_invoice
):
    from types import SimpleNamespace

    fake_token_service.debit_tokens.return_value = SimpleNamespace(balance=300)
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    invoice = make_invoice()
    new_balance = service.debit_for_invoice(uuid4(), invoice, 200)
    assert new_balance == 300
    _, kwargs = fake_token_service.debit_tokens.call_args
    assert kwargs["amount"] == 200
    assert kwargs["transaction_type"] == TokenTransactionType.USAGE
    assert kwargs["reference_id"] == invoice.id


def test_debit_propagates_insufficient_balance(fake_token_service, make_invoice):
    fake_token_service.debit_tokens.side_effect = ValueError("Insufficient token balance")
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    with pytest.raises(ValueError):
        service.debit_for_invoice(uuid4(), make_invoice(), 999)


def test_refund_credits_back_with_refund_type(fake_token_service, make_invoice):
    from types import SimpleNamespace

    fake_token_service.credit_tokens.return_value = SimpleNamespace(balance=500)
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    invoice = make_invoice()
    service.refund_for_invoice(uuid4(), invoice, 200)
    _, kwargs = fake_token_service.credit_tokens.call_args
    assert kwargs["amount"] == 200
    assert kwargs["transaction_type"] == TokenTransactionType.REFUND
    assert kwargs["reference_id"] == invoice.id
