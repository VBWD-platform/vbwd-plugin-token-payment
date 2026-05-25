# How to develop this further

Practical next steps, each kept small and in keeping with the agnostic design.

## Ground rules

- **Don't touch core for this feature.** No new column on `invoice`, no token-rate
  table in core, no `if method == "token"` in core. Everything lives in this
  plugin; it depends on core ports (`TokenService`, `emit_payment_captured`).
- **TDD.** Add/extend a test in `tests/unit/` first. The service is pure (fake
  `TokenService`), so most logic is testable without a DB.
- **Lint:** `flake8 plugins/token_payment --max-line-length=120`.

## Likely enhancements

### 1. Automated refunds
Today `refund_payment()` returns "not automated". To automate: add an admin
route (or hook the core refund flow) that calls
`TokenPaymentService.refund_for_invoice(...)` (already implemented — it credits
`TokenTransactionType.REFUND`). Needs the original `tokens_spent`; read it from
the `TokenTransaction` whose `reference_id == invoice.id`.

### 2. Admin-editable rates with a real UI
Rates are a JSON object in `config.json` today, edited as text in admin. If you
want a proper grid (add/remove currency rows), either:
- enrich `admin-config.json` once the admin UI grows an object/grid component, or
- give the plugin its own `token_payment_rate` table + Alembic migration under
  `plugins/token_payment/migrations/versions/` and CRUD routes. Only do this when
  text-JSON config genuinely stops being enough.

### 3. Concurrency hardening
`debit_tokens` already raises on insufficient balance, and `/pay` re-checks after
the quote. For very high contention, wrap the read-modify-write of the balance in
a row lock inside `TokenService` (core change — coordinate separately) or rely on
the existing optimistic check. Add a test that simulates a stale quote.

### 4. Show the method in checkout (not just invoice detail)
Currently the fe-user plugin renders on the invoice page. To offer it at checkout
time, register the method in the fe-user checkout selector and call `/pay` after
the invoice is created.

## Testing the full path

Unit tests don't need the stack. For the end-to-end path (debit → PAID →
line items activate), use an integration test that builds the app, seeds a
balance via `TokenService.credit_tokens`, creates a PENDING invoice, and POSTs
`/pay`, then asserts the invoice is PAID and the balance dropped.

## Releasing

This plugin is its own repo (`vbwd-plugin-token-payment`). Commit + push to
`main`; its CI (`.github/workflows/tests.yml`) checks out vbwd-backend and runs
`pre-commit-check.sh --plugin token_payment`. Keep the plugin `enabled: false` in
the SDK's `plugins/plugins.json` so installs stay opt-in.
