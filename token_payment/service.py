"""Token-balance payment logic.

Convert an invoice total to a token amount at the configured currency rate, and
spend / refund tokens through the core ``TokenService``. Deliberately free of
Flask so it is unit-testable with a fake ``TokenService`` (no app, no DB).
"""
import json
import logging
import math
from decimal import Decimal
from typing import Any, Dict, Optional

from vbwd.models.enums import TokenTransactionType

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        token_service: Any,
        rates: Optional[Any] = None,
        transaction_repo: Optional[Any] = None,
        token_manager_email: str = "",
        user_repo: Optional[Any] = None,
    ) -> None:
        self._token_service = token_service
        # currency code -> price of ONE token in that currency, e.g. {"USD": 0.05}
        self._rates: Dict[str, Decimal] = {
            str(currency).upper(): Decimal(str(price))
            for currency, price in _coerce_rates(rates).items()
        }
        # Used only by tokens_paid_for_invoice — optional for backward-compat
        # with older callers that built the service without it.
        self._transaction_repo = transaction_repo
        # Token payment is an instant charge: when an admin configures a
        # "Token manager" user, the debited tokens are TRANSFERRED to that
        # user (payer debit + manager credit) instead of merely vanishing.
        # Both optional so unit tests / older callers keep debit-only behaviour.
        self._token_manager_email = (token_manager_email or "").strip()
        self._user_repo = user_repo

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

    def quote_for_amount(
        self, user_id: Any, amount: Any, currency: str
    ) -> Dict[str, Any]:
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
        """Spend ``tokens_needed`` for this invoice. Raises ValueError if insufficient.

        When a token manager is configured (and resolvable, and not the payer),
        the same amount is credited to that manager so the charge is a real
        transfer. Otherwise falls back to debit-only.
        """
        invoice_label = getattr(invoice, "invoice_number", None) or invoice.id
        updated_balance = self._token_service.debit_tokens(
            user_id=user_id,
            amount=tokens_needed,
            transaction_type=TokenTransactionType.USAGE,
            reference_id=invoice.id,
            description=f"Paid invoice {invoice_label} with token balance",
        )
        self._credit_token_manager(user_id, invoice, tokens_needed, invoice_label)
        return int(updated_balance.balance)

    def _credit_token_manager(
        self, payer_id: Any, invoice: Any, tokens_needed: int, invoice_label: Any
    ) -> None:
        """Credit the configured token-manager user (transfer leg of the charge).

        No-op (debit-only fallback) when the manager is unset, unresolvable, or
        is the payer — never breaks the payment; logs a warning on misconfig.
        """
        if not self._token_manager_email:
            return
        if self._user_repo is None:
            logger.warning(
                "token_payment: token_manager_email set but no user lookup "
                "available; tokens debited but not transferred."
            )
            return
        manager = self._user_repo.find_by_email(self._token_manager_email)
        if manager is None:
            logger.warning(
                "token_payment: token manager '%s' not found; tokens debited "
                "but not transferred.",
                self._token_manager_email,
            )
            return
        if str(manager.id) == str(payer_id):
            logger.warning(
                "token_payment: token manager '%s' is the payer; skipping "
                "self-transfer (debit only).",
                self._token_manager_email,
            )
            return
        self._token_service.credit_tokens(
            user_id=manager.id,
            amount=tokens_needed,
            transaction_type=TokenTransactionType.ADJUSTMENT,
            reference_id=invoice.id,
            description=f"Token transfer from invoice {invoice_label}",
        )

    def tokens_paid_for_invoice(self, invoice_id: Any) -> Optional[int]:
        """Tokens debited for this invoice via the token-balance USAGE entry.

        Returns the absolute amount (positive integer), or None if the repo
        wasn't injected, no transaction exists for the invoice, or the
        transaction isn't a USAGE debit.
        """
        if self._transaction_repo is None:
            return None
        transaction = self._transaction_repo.find_by_reference_id(invoice_id)
        if transaction is None:
            return None
        if transaction.transaction_type != TokenTransactionType.USAGE:
            return None
        return abs(int(transaction.amount))

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
