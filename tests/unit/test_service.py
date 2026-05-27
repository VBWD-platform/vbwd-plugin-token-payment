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
    fake_token_service.debit_tokens.side_effect = ValueError(
        "Insufficient token balance"
    )
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    with pytest.raises(ValueError):
        service.debit_for_invoice(uuid4(), make_invoice(), 999)


def test_quote_for_amount_available_and_sufficient(fake_token_service):
    """s12: amount-based quote at checkout time (no invoice yet)."""
    fake_token_service.get_balance.return_value = 500
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    quote = service.quote_for_amount(uuid4(), Decimal("9.99"), "USD")
    assert quote["available"] is True
    assert quote["tokens_needed"] == 200
    assert quote["balance"] == 500
    assert quote["balance_after"] == 300
    assert quote["sufficient"] is True


def test_quote_for_amount_no_rate(fake_token_service):
    fake_token_service.get_balance.return_value = 500
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    quote = service.quote_for_amount(uuid4(), Decimal("100"), "JPY")
    assert quote["available"] is False
    assert quote["reason"] == "no_rate_for_currency"


def test_quote_for_amount_insufficient(fake_token_service):
    fake_token_service.get_balance.return_value = 50
    service = TokenPaymentService(fake_token_service, {"USD": 0.05})
    quote = service.quote_for_amount(uuid4(), Decimal("9.99"), "USD")
    assert quote["available"] is True
    assert quote["sufficient"] is False


def test_rates_can_be_a_json_string(fake_token_service):
    """Admin UIs render object fields as text inputs; the service must accept
    either a dict or a JSON-encoded string for `rates`."""
    service = TokenPaymentService(fake_token_service, '{"USD": 0.05}')
    assert service.rate_for("USD") == Decimal("0.05")


def test_read_balance_returns_current_wallet_balance(fake_token_service):
    """For the post-capture balance read in the pay route (s11 item 2)."""
    fake_token_service.get_balance.return_value = 1234
    service = TokenPaymentService(fake_token_service, {})
    assert service.read_balance(uuid4()) == 1234


def test_tokens_paid_for_invoice_returns_abs_of_the_usage_debit(
    fake_token_service, make_invoice
):
    """For a token-paid invoice, return the absolute tokens debited via USAGE."""
    from types import SimpleNamespace
    from vbwd.models.enums import TokenTransactionType

    invoice = make_invoice()
    transaction_repo = MagicMock()
    transaction_repo.find_by_reference_id.return_value = SimpleNamespace(
        amount=-200,
        transaction_type=TokenTransactionType.USAGE,
        reference_id=invoice.id,
    )
    service = TokenPaymentService(
        fake_token_service, {"USD": 0.05}, transaction_repo=transaction_repo
    )
    assert service.tokens_paid_for_invoice(invoice.id) == 200


def test_tokens_paid_for_invoice_returns_none_when_no_transaction(
    fake_token_service, make_invoice
):
    transaction_repo = MagicMock()
    transaction_repo.find_by_reference_id.return_value = None
    service = TokenPaymentService(
        fake_token_service, {}, transaction_repo=transaction_repo
    )
    assert service.tokens_paid_for_invoice(make_invoice().id) is None


def test_tokens_paid_for_invoice_returns_none_without_repo(
    fake_token_service, make_invoice
):
    """Backward-compat: omitting transaction_repo (older callers) is non-throwing."""
    service = TokenPaymentService(fake_token_service, {})
    assert service.tokens_paid_for_invoice(make_invoice().id) is None


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
