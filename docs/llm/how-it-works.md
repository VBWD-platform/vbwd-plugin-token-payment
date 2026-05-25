# how-it-works (LLM)

Machine-oriented map of the token-balance payment plugin. Paths are relative to
`vbwd-backend/`.

## Identity
- Plugin name (config_store key, `plugins.json`): `token_payment`
- Class: `plugins/token_payment/__init__.py::TokenPaymentPlugin(PaymentProviderPlugin)`
- URL prefix: `/api/v1/plugins/token-payment`
- Blueprint: `plugins/token_payment/token_payment/routes.py::token_payment_plugin_bp`
- Default state: disabled (`plugins/plugins.json` → `token_payment.enabled = false`)

## Core ports consumed (do not reimplement)
- `vbwd/services/token_service.py::TokenService`
  - `get_balance(user_id) -> int`
  - `debit_tokens(user_id, amount, transaction_type, reference_id, description) -> UserTokenBalance` (raises `ValueError("Insufficient token balance")`)
  - `credit_tokens(...)` (same shape)
  - obtained in routes via `current_app.container.token_service()`
- `vbwd/plugins/payment_route_helpers.py`
  - `check_plugin_enabled("token_payment") -> (config|None, err|None)`
  - `validate_invoice_for_payment(invoice_id, user_id) -> (invoice|None, err|None)` (PENDING + ownership)
  - `emit_payment_captured(invoice_id, payment_reference, amount, currency, provider, transaction_id="")` → emits `PaymentCapturedEvent`
- `vbwd/models/enums.py::TokenTransactionType` — uses `USAGE` (debit) and `REFUND` (refund). **No `PAYMENT` value is added** (core untouched).
- Auth: `vbwd/middleware/auth.py::require_auth` → `g.user_id`.

## Capture seam (invoice → PAID)
`emit_payment_captured` → `vbwd/handlers/payment_handler.py::PaymentCapturedHandler`
marks `invoice.mark_paid(ref, "token_payment")` and runs
`vbwd/events/line_item_registry.py` (each plugin activates its own line-item
types). The plugin never mutates the invoice directly.

## Conversion contract (`token_payment/service.py::TokenPaymentService`)
- `rate_for(currency) -> Decimal | None` (case-insensitive; None if missing or ≤ 0)
- `compute_tokens_needed(amount, rate) -> int = ceil(Decimal(amount) / Decimal(rate))`
- `quote(user_id, invoice) -> dict` keys: `available, reason?, currency, amount, rate, tokens_needed, balance, balance_after, sufficient`
- `debit_for_invoice(user_id, invoice, tokens_needed) -> int` (USAGE, `reference_id=invoice.id`)
- `refund_for_invoice(user_id, invoice, tokens_needed) -> int` (REFUND, `reference_id=invoice.id`)

## Route contract (`routes.py`)
- `GET /invoices/<id>/quote` → `check_plugin_enabled` → `validate_invoice_for_payment` → `service.quote` → 200
- `POST /invoices/<id>/pay` → enabled → validate → quote → `422` if `not available` → `400` if `not sufficient` → `debit_for_invoice` (`400` on `ValueError`) → `emit_payment_captured` → on failure `refund_for_invoice` + `500` → else `200 {invoice_id, tokens_spent, new_balance, status:"PAID"}`

## Invariants (must hold)
- No core schema change (no `invoice.tokens_total`, no core token-rate table).
- Atomicity: a successful debit without a successful capture is always refunded.
- `provider` string in events is `"token_payment"`; `payment_reference` is `"token-balance:<invoice_id>"`.
- The `PaymentProviderPlugin` gateway methods are minimal but return valid `PaymentResult` (Liskov); `verify_webhook → False`, `handle_webhook → None`.

## Config
`config.json` (schema) / `plugins/config.json` (values): `debug_mode: bool`,
`rates: { CURRENCY: price_per_token }`. Read via `config.get("rates", {})`.

## Tests
`plugins/token_payment/tests/unit/{test_service.py,test_plugin.py}` — fake
`TokenService` (MagicMock), `SimpleNamespace` invoices, no app/DB. 14 cases.
Run: `docker compose run --rm test python -m pytest plugins/token_payment/tests/unit/ -v`.
