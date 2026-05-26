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
    return TokenPaymentService(token_service, config.get("rates", {}))


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
        return jsonify({"error": "Token payment is not available for this currency"}), 422
    if not quote_result["sufficient"]:
        return jsonify({"error": "Insufficient token balance", **quote_result}), 400

    tokens_needed = quote_result["tokens_needed"]
    try:
        service.debit_for_invoice(g.user_id, invoice, tokens_needed)
    except ValueError:
        # balance dropped between quote and debit (concurrent spend)
        return jsonify({"error": "Insufficient token balance"}), 400

    result = emit_payment_captured(
        invoice_id=invoice.id,
        payment_reference=f"token-balance:{invoice.id}",
        amount=invoice.total_amount,
        currency=invoice.currency,
        provider=PROVIDER,
        transaction_id=str(invoice.id),
    )
    if not result.success:
        # atomic: capture/activation failed → give the tokens back
        service.refund_for_invoice(g.user_id, invoice, tokens_needed)
        logger.error(
            "token_payment capture failed for invoice %s; refunded %s tokens",
            invoice.id,
            tokens_needed,
        )
        return jsonify({"error": "Payment could not be completed; tokens were refunded"}), 500

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
