"""token_payment opts into the core RecurringChargeProvider capability (S103.1).

The off-session charge re-uses the SAME building blocks as the interactive
``POST /pay`` route — quote → debit → ``emit_payment_captured`` → refund-on-
failure — so the trial-end / renewal path and the manual path can never drift.
These specs pin the capability surface + the four outcomes (no rate, insufficient
balance, captured, capture-failed) without needing a Flask app: they drive
``charge_invoice_with_tokens`` with a fake service and a patched capture seam.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from vbwd.plugins.payment_provider import ChargeResult, RecurringChargeProvider

from plugins.token_payment import TokenPaymentPlugin
from plugins.token_payment.token_payment.routes import charge_invoice_with_tokens


def _invoice():
    return SimpleNamespace(
        id=uuid4(),
        invoice_number="INV-1",
        total_amount=Decimal("10.00"),
        currency="EUR",
    )


class _FakeService:
    """Mimics the slice of TokenPaymentService the charge path uses."""

    def __init__(self, quote):
        self._quote = quote
        self.debited = None
        self.refunded = None
        self.raise_on_debit = False

    def quote(self, user_id, invoice):
        return self._quote

    def debit_for_invoice(self, user_id, invoice, tokens_needed):
        if self.raise_on_debit:
            raise ValueError("insufficient")
        self.debited = tokens_needed
        return 0

    def refund_for_invoice(self, user_id, invoice, tokens_needed):
        self.refunded = tokens_needed
        return tokens_needed


class TestPluginOptsIntoCapability:
    def test_plugin_is_a_recurring_charge_provider(self):
        assert isinstance(TokenPaymentPlugin(), RecurringChargeProvider)

    def test_plugin_implements_the_abstract_method(self):
        assert "charge_saved_method" not in TokenPaymentPlugin.__abstractmethods__


class TestChargeInvoiceWithTokens:
    def test_no_rate_for_currency_fails_without_charging(self):
        service = _FakeService({"available": False, "reason": "no_rate_for_currency"})
        result = charge_invoice_with_tokens(service, uuid4(), _invoice())
        assert isinstance(result, ChargeResult)
        assert result.success is False
        assert result.error == "no_rate_for_currency"
        assert service.debited is None

    def test_insufficient_balance_fails_without_charging(self):
        service = _FakeService(
            {"available": True, "sufficient": False, "tokens_needed": 222}
        )
        result = charge_invoice_with_tokens(service, uuid4(), _invoice())
        assert result.success is False
        assert result.error == "insufficient_token_balance"
        assert service.debited is None

    def test_sufficient_balance_debits_and_captures(self):
        service = _FakeService(
            {"available": True, "sufficient": True, "tokens_needed": 222}
        )
        with patch(
            "plugins.token_payment.token_payment.routes.emit_payment_captured",
            return_value=SimpleNamespace(success=True),
        ) as captured:
            result = charge_invoice_with_tokens(service, uuid4(), _invoice())
        assert result.success is True
        assert service.debited == 222
        assert service.refunded is None
        captured.assert_called_once()

    def test_capture_failure_refunds_and_fails(self):
        service = _FakeService(
            {"available": True, "sufficient": True, "tokens_needed": 222}
        )
        with patch(
            "plugins.token_payment.token_payment.routes.emit_payment_captured",
            return_value=SimpleNamespace(success=False),
        ):
            result = charge_invoice_with_tokens(service, uuid4(), _invoice())
        assert result.success is False
        assert result.error == "capture_failed"
        assert service.refunded == 222

    def test_debit_race_is_reported_as_insufficient(self):
        service = _FakeService(
            {"available": True, "sufficient": True, "tokens_needed": 222}
        )
        service.raise_on_debit = True
        result = charge_invoice_with_tokens(service, uuid4(), _invoice())
        assert result.success is False
        assert result.error == "insufficient_token_balance"
