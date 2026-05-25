"""Token-balance payment logic.

Convert an invoice total to a token amount at the configured currency rate, and
spend / refund tokens through the core ``TokenService``. Deliberately free of
Flask so it is unit-testable with a fake ``TokenService`` (no app, no DB).
"""
import math
from decimal import Decimal
from typing import Any, Dict, Optional

from vbwd.models.enums import TokenTransactionType


class TokenPaymentService:
    """Quote an invoice in tokens and debit/credit the user's balance."""

    def __init__(self, token_service: Any, rates: Optional[Dict[str, Any]] = None) -> None:
        self._token_service = token_service
        # currency code -> price of ONE token in that currency, e.g. {"USD": 0.05}
        self._rates: Dict[str, Decimal] = {
            str(currency).upper(): Decimal(str(price))
            for currency, price in (rates or {}).items()
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
        balance = int(self._token_service.get_balance(user_id))
        rate = self.rate_for(invoice.currency)
        if rate is None:
            return {
                "available": False,
                "reason": "no_rate_for_currency",
                "currency": invoice.currency,
                "balance": balance,
            }
        tokens_needed = self.compute_tokens_needed(invoice.total_amount, rate)
        return {
            "available": True,
            "currency": invoice.currency,
            "amount": str(invoice.total_amount),
            "rate": str(rate),
            "tokens_needed": tokens_needed,
            "balance": balance,
            "balance_after": balance - tokens_needed,
            "sufficient": balance >= tokens_needed,
        }

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
