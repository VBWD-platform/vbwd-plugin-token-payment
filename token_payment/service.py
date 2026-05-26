"""Token-balance payment logic.

Convert an invoice total to a token amount at the configured currency rate, and
spend / refund tokens through the core ``TokenService``. Deliberately free of
Flask so it is unit-testable with a fake ``TokenService`` (no app, no DB).
"""
import json
import math
from decimal import Decimal
from typing import Any, Dict, Optional

from vbwd.models.enums import TokenTransactionType


def _coerce_rates(rates: Any) -> Dict[str, Any]:
    """Accept rates as a dict OR a JSON-encoded string (admin text-input field)."""
    if isinstance(rates, str):
        try:
            parsed = json.loads(rates)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return rates or {}


class TokenPaymentService:
    """Quote an invoice in tokens and debit/credit the user's balance."""

    def __init__(self, token_service: Any, rates: Optional[Any] = None) -> None:
        self._token_service = token_service
        # currency code -> price of ONE token in that currency, e.g. {"USD": 0.05}
        self._rates: Dict[str, Decimal] = {
            str(currency).upper(): Decimal(str(price))
            for currency, price in _coerce_rates(rates).items()
        }

    def rate_for(self, currency: str) -> Optional[Decimal]:
        """Price of one token in ``currency``, or None when not configured / non-positive."""
        rate = self._rates.get((currency or "").upper())
        if rate is None or rate <= 0:
            return None
        return rate

    @staticmethod
    def compute_tokens_needed(amount: Any, rate: Any) -> int:
        """Tokens required to cover ``amount`` at ``rate`` (currency per token), rounded up."""
        return int(math.ceil(Decimal(str(amount)) / Decimal(str(rate))))

    def quote(self, user_id: Any, invoice: Any) -> Dict[str, Any]:
        """Token cost + the user's balance for a PENDING invoice (no side effects)."""
        return self.quote_for_amount(user_id, invoice.total_amount, invoice.currency)

    def quote_for_amount(self, user_id: Any, amount: Any, currency: str) -> Dict[str, Any]:
        """Amount-based quote — used at checkout time when no invoice exists yet (s12)."""
        balance = int(self._token_service.get_balance(user_id))
        rate = self.rate_for(currency)
        if rate is None:
            return {
                "available": False,
                "reason": "no_rate_for_currency",
                "currency": currency,
                "balance": balance,
            }
        tokens_needed = self.compute_tokens_needed(amount, rate)
        return {
            "available": True,
            "currency": currency,
            "amount": str(amount),
            "rate": str(rate),
            "tokens_needed": tokens_needed,
            "balance": balance,
            "balance_after": balance - tokens_needed,
            "sufficient": balance >= tokens_needed,
        }

    def read_balance(self, user_id: Any) -> int:
        """Current wallet balance — used by the pay route to report the
        post-capture balance (after line-item activation may have credited
        further tokens, e.g. token-bundle invoices)."""
        return int(self._token_service.get_balance(user_id))

    def debit_for_invoice(self, user_id: Any, invoice: Any, tokens_needed: int) -> int:
        """Spend ``tokens_needed`` for this invoice. Raises ValueError if insufficient."""
        invoice_label = getattr(invoice, "invoice_number", None) or invoice.id
        updated_balance = self._token_service.debit_tokens(
            user_id=user_id,
            amount=tokens_needed,
            transaction_type=TokenTransactionType.USAGE,
            reference_id=invoice.id,
            description=f"Paid invoice {invoice_label} with token balance",
        )
        return int(updated_balance.balance)

    def refund_for_invoice(self, user_id: Any, invoice: Any, tokens_needed: int) -> int:
        """Give tokens back (used to keep the pay flow atomic if capture fails)."""
        updated_balance = self._token_service.credit_tokens(
            user_id=user_id,
            amount=tokens_needed,
            transaction_type=TokenTransactionType.REFUND,
            reference_id=invoice.id,
            description=f"Refund token payment for invoice {invoice.id}",
        )
        return int(updated_balance.balance)
