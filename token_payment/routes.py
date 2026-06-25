"""Token-balance payment routes.

GET  /api/v1/plugins/token-payment/invoices/<id>/quote  → cost + balance (no side effects)
POST /api/v1/plugins/token-payment/invoices/<id>/pay    → debit balance, mark invoice PAID

The pay route reuses the shared payment seam (``emit_payment_captured``) so the
invoice transitions to PAID and its line items activate exactly like any other
payment method — core never learns about tokens.
"""
import logging

from flask import Blueprint, current_app, g, jsonify, request

from vbwd.middleware.auth import require_auth
from vbwd.plugins.payment_provider import ChargeResult
from vbwd.plugins.payment_route_helpers import (
    check_plugin_enabled,
    validate_invoice_for_payment,
    emit_payment_captured,
)

from plugins.token_payment.token_payment.service import TokenPaymentService

logger = logging.getLogger(__name__)

token_payment_plugin_bp = Blueprint("token_payment_plugin", __name__)

PLUGIN_NAME = "token_payment"
PROVIDER = "token_payment"


def _build_service(config) -> TokenPaymentService:
    token_service = current_app.container.token_service()
    transaction_repo = current_app.container.token_transaction_repository()
    # Token manager is resolved by email via the CORE user repository (allowed:
    # token_payment may depend on core, never on another plugin).
    user_repo = current_app.container.user_repository()
    return TokenPaymentService(
        token_service,
        config.get("rates", {}),
        transaction_repo=transaction_repo,
        token_manager_email=config.get("token_manager_email", ""),
        user_repo=user_repo,
    )


def _capture_token_payment(service, user_id, invoice, tokens_needed) -> ChargeResult:
    """Debit + capture + refund-on-failure — the atomic core shared by the
    interactive ``POST /pay`` route and the off-session recurring charge so the
    two flows can never drift. ``tokens_needed`` is the already-quoted amount.
    Returns a ChargeResult; never raises a provider-specific error (Liskov)."""
    try:
        service.debit_for_invoice(user_id, invoice, tokens_needed)
    except ValueError:
        # balance dropped between quote and debit (concurrent spend)
        return ChargeResult(success=False, error="insufficient_token_balance")

    # Persist the plugin's payment-method details under its own namespace on
    # the invoice's generic metadata column via the agnostic event seam —
    # core's PaymentCapturedHandler merges ``event.metadata`` into
    # ``invoice.metadata`` in the same save as ``mark_paid``. One write, DRY.
    reference = f"token-balance:{invoice.id}"
    result = emit_payment_captured(
        invoice_id=invoice.id,
        payment_reference=reference,
        amount=invoice.total_amount,
        currency=invoice.currency,
        provider=PROVIDER,
        transaction_id=str(invoice.id),
        metadata={"tokens_paid": {"amount": int(tokens_needed)}},
    )
    if not result.success:
        # atomic: capture/activation failed → give the tokens back
        service.refund_for_invoice(user_id, invoice, tokens_needed)
        logger.error(
            "token_payment capture failed for invoice %s; refunded %s tokens",
            invoice.id,
            tokens_needed,
        )
        return ChargeResult(success=False, error="capture_failed")
    return ChargeResult(
        success=True, provider_reference=reference, transaction_id=str(invoice.id)
    )


def charge_invoice_with_tokens(service, user_id, invoice) -> ChargeResult:
    """Off-session token charge: quote the invoice in tokens, then debit +
    capture. The token balance IS the user's "saved method"; this is what the
    core ``RecurringChargeProvider`` capability calls at trial-end / renewal.
    Returns a ChargeResult (no rate / insufficient / captured / capture-failed)
    — never raises."""
    quote_result = service.quote(user_id, invoice)
    if not quote_result["available"]:
        return ChargeResult(
            success=False,
            error=quote_result.get("reason", "no_rate_for_currency"),
        )
    if not quote_result["sufficient"]:
        return ChargeResult(success=False, error="insufficient_token_balance")
    return _capture_token_payment(
        service, user_id, invoice, quote_result["tokens_needed"]
    )


@token_payment_plugin_bp.route("/invoices/<invoice_id>/quote", methods=["GET"])
@require_auth
def quote(invoice_id):
    config, err = check_plugin_enabled(PLUGIN_NAME)
    if err:
        return err
    invoice, err = validate_invoice_for_payment(invoice_id, g.user_id)
    if err:
        return err
    service = _build_service(config)
    return jsonify(service.quote(g.user_id, invoice)), 200


@token_payment_plugin_bp.route("/invoices/<invoice_id>/tokens-paid", methods=["GET"])
@require_auth
def tokens_paid(invoice_id):
    """How many tokens were spent on this invoice (for the paid-invoice UI).

    Authenticated; returns ``{ tokens_paid: N | null }``. ``null`` is returned
    for invoices the user doesn't own, invoices not paid with tokens, or when
    the plugin is disabled — so the caller can safely hide its UI without
    leaking info.
    """
    from uuid import UUID

    config, err = check_plugin_enabled(PLUGIN_NAME)
    if err:
        return jsonify({"tokens_paid": None}), 200

    try:
        invoice_uuid = UUID(invoice_id)
    except (ValueError, TypeError):
        return jsonify({"tokens_paid": None}), 200

    invoice_repo = current_app.container.invoice_repository()
    invoice = invoice_repo.find_by_id(invoice_uuid)
    if invoice is None or str(invoice.user_id) != str(g.user_id):
        return jsonify({"tokens_paid": None}), 200

    service = _build_service(config)
    return jsonify({"tokens_paid": service.tokens_paid_for_invoice(invoice_uuid)}), 200


@token_payment_plugin_bp.route("/quote", methods=["GET"])
@require_auth
def quote_amount():
    """Amount-based quote (s12) — used by the checkout selector before an invoice exists."""
    from decimal import Decimal, InvalidOperation

    config, err = check_plugin_enabled(PLUGIN_NAME)
    if err:
        return err
    amount_raw = request.args.get("amount", "")
    currency = request.args.get("currency", "")
    try:
        amount = Decimal(amount_raw)
    except (InvalidOperation, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0 or not currency:
        return jsonify({"error": "amount and currency are required"}), 400
    service = _build_service(config)
    return jsonify(service.quote_for_amount(g.user_id, amount, currency)), 200


@token_payment_plugin_bp.route("/invoices/<invoice_id>/pay", methods=["POST"])
@require_auth
def pay(invoice_id):
    config, err = check_plugin_enabled(PLUGIN_NAME)
    if err:
        return err
    invoice, err = validate_invoice_for_payment(invoice_id, g.user_id)
    if err:
        return err

    service = _build_service(config)
    quote_result = service.quote(g.user_id, invoice)
    if not quote_result["available"]:
        return (
            jsonify({"error": "Token payment is not available for this currency"}),
            422,
        )
    if not quote_result["sufficient"]:
        return jsonify({"error": "Insufficient token balance", **quote_result}), 400

    tokens_needed = quote_result["tokens_needed"]
    # Shared atomic core (debit → capture → refund-on-failure) — identical to
    # the off-session recurring charge, so the two can never drift.
    charge = _capture_token_payment(service, g.user_id, invoice, tokens_needed)
    if not charge.success:
        if charge.error == "capture_failed":
            return (
                jsonify(
                    {"error": "Payment could not be completed; tokens were refunded"}
                ),
                500,
            )
        return jsonify({"error": "Insufficient token balance"}), 400

    # Post-capture balance — captures any line-item credits (e.g. a token bundle
    # whose activation credits more tokens than the debit just spent).
    new_balance = service.read_balance(g.user_id)
    return (
        jsonify(
            {
                "invoice_id": str(invoice.id),
                "tokens_spent": tokens_needed,
                "new_balance": new_balance,
                "status": "PAID",
            }
        ),
        200,
    )
