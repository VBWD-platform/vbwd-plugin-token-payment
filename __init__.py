"""Token-balance payment plugin.

Pay any PENDING invoice with the user's token balance. Internal payment method
(no external gateway): on ``pay`` it debits the **core** token balance via
``TokenService`` and finalizes through the shared ``PaymentCapturedEvent`` seam,
exactly like every other payment plugin — core stays agnostic. Off by default;
the admin sets the currency→token rate in this plugin's config.
"""
from decimal import Decimal
from typing import Any, Dict, Optional, TYPE_CHECKING
from uuid import UUID

from vbwd.plugins.base import PluginMetadata
from vbwd.plugins.payment_provider import (
    ChargeResult,
    PaymentProviderPlugin,
    PaymentResult,
    PaymentStatus,
    RecurringChargeProvider,
)

if TYPE_CHECKING:
    from flask import Blueprint


DEFAULT_CONFIG: Dict[str, Any] = {
    "debug_mode": False,
    # currency code -> price of ONE token in that currency.
    # tokens_needed = ceil(invoice_total / rate). Omit a currency to disable
    # token payment for invoices in that currency.
    "rates": {"USD": 0.05, "EUR": 0.045},
    # Email of the user who receives tokens paid via token balance. When set,
    # a token payment becomes a transfer (payer debited, this user credited).
    # Empty = debit-only (legacy behaviour).
    "token_manager_email": "",
}


class TokenPaymentPlugin(PaymentProviderPlugin, RecurringChargeProvider):
    """Pay an invoice from the user's token balance."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="token_payment",
            version="1.0.0",
            author="VBWD Team",
            description=(
                "Pay any invoice with the user's token balance. Internal, no "
                "external gateway; admin-configurable currency→token rate."
            ),
            dependencies=[],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.token_payment.token_payment.routes import token_payment_plugin_bp

        return token_payment_plugin_bp

    def get_url_prefix(self) -> Optional[str]:
        return "/api/v1/plugins/token-payment"

    @property
    def admin_permissions(self):
        return [
            {
                "key": "payments.configure",
                "label": "Payment provider settings",
                "group": "Payments",
            },
        ]

    def on_enable(self) -> None:
        """Register the ``token_balance`` payment method in the DB so the
        data-driven checkout selector lists it (s12). Idempotent; preserves
        the row's id/history."""
        self._sync_method_record(active=True)

    def on_disable(self) -> None:
        """Deactivate (keep the row for historical references)."""
        self._sync_method_record(active=False)

    def _sync_method_record(self, *, active: bool) -> None:
        """Best-effort upsert/deactivate of the payment-method row. Swallows
        errors so a misconfigured DB never blocks plugin enable/disable."""
        import logging

        try:
            from vbwd.extensions import db
            from vbwd.repositories.payment_method_repository import (
                PaymentMethodRepository,
            )
            from plugins.token_payment.token_payment.payment_method import (
                upsert_token_balance_method,
                deactivate_token_balance_method,
            )

            repo = PaymentMethodRepository(db.session)
            if active:
                upsert_token_balance_method(repo)
            else:
                deactivate_token_balance_method(repo)
            db.session.commit()
        except Exception as error:  # pragma: no cover — operational guard
            logging.getLogger(__name__).warning(
                "token_payment %s: method-record op skipped: %s",
                "enable" if active else "disable",
                error,
            )

    # ── PaymentProviderPlugin contract ─────────────────────────────────────
    # This is an INTERNAL payment method: the real charge happens in the
    # plugin's POST /pay route (debit balance → emit PaymentCapturedEvent).
    # The gateway-oriented methods below are intentionally minimal but honour
    # the PaymentResult contract (Liskov) so the plugin is a valid provider.

    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        subscription_id: UUID,
        user_id: UUID,
        metadata: Optional[Dict[str, Any]] = None,
        capture: bool = True,
    ) -> PaymentResult:
        return PaymentResult(
            success=True,
            status=PaymentStatus.PENDING,
            metadata={"note": "token-balance payment is captured via POST /pay"},
        )

    def capture_payment(
        self, payment_id: str, amount: Optional[Decimal] = None
    ) -> PaymentResult:
        return PaymentResult(
            success=True, status=PaymentStatus.COMPLETED, transaction_id=payment_id
        )

    def release_authorization(self, payment_id: str) -> PaymentResult:
        return PaymentResult(
            success=True, status=PaymentStatus.CANCELLED, transaction_id=payment_id
        )

    def process_payment(
        self, payment_intent_id: str, payment_method: str
    ) -> PaymentResult:
        return self.capture_payment(payment_intent_id)

    def refund_payment(
        self, transaction_id: str, amount: Optional[Decimal] = None
    ) -> PaymentResult:
        return PaymentResult(
            success=False,
            status=PaymentStatus.FAILED,
            error_message=(
                "Token-balance refunds are not automated; credit the user's "
                "tokens manually."
            ),
        )

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return False  # internal method — no webhooks

    def handle_webhook(self, payload: Dict[str, Any]) -> None:
        pass

    # ── RecurringChargeProvider contract (S103.1) ──────────────────────────
    def charge_saved_method(self, *, user_id: UUID, invoice: Any) -> ChargeResult:
        """Off-session recurring charge: the user's token balance is the saved
        method. Re-uses the exact quote→debit→capture path as ``POST /pay`` so
        the trial-end / renewal flow and the interactive flow never drift.
        Reads this plugin's live config; returns a ChargeResult, never raises.
        """
        from flask import current_app
        from plugins.token_payment.token_payment.routes import (
            _build_service,
            charge_invoice_with_tokens,
        )

        config_store = getattr(current_app, "config_store", None)
        config = (
            config_store.get_config("token_payment")
            if config_store is not None
            else None
        ) or {**DEFAULT_CONFIG}
        service = _build_service(config)
        return charge_invoice_with_tokens(service, user_id, invoice)
