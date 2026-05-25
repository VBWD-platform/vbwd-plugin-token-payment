# how-to-develop (LLM)

Rules and recipes for an agent extending this plugin. Keep changes inside
`plugins/token_payment/`.

## Hard constraints
- **Agnostic core:** never edit `vbwd/` for this feature. No `invoice.tokens_total`,
  no token-rate table in core, no token branch in core routes/handlers. Depend on
  `TokenService` + `emit_payment_captured` only.
- **TDD-first:** add the failing test in `tests/unit/` before the code. The
  service is pure; mock `TokenService` with `MagicMock`, build invoices with
  `types.SimpleNamespace(id=..., invoice_number=..., total_amount=Decimal(...), currency=...)`.
- **DI/Liskov:** new collaborators are injected into `TokenPaymentService`'s
  constructor or resolved from `current_app.container`. Any `PaymentResult` you
  return must satisfy the base contract.
- **Lint:** `flake8 plugins/token_payment --max-line-length=120 --extend-ignore=E203,W503`. Full readable names (no single letters).
- **No overengineering:** smallest change that satisfies the requirement.

## Extension recipes

### Automate refund
1. Test: refunding a token-paid invoice credits back exactly `tokens_spent` (REFUND).
2. Find `tokens_spent`: query `TokenTransaction` where `reference_id == invoice.id`
   and `transaction_type == USAGE` (negative amount). Add a `TokenTransactionRepository`
   lookup if needed (read-only).
3. Wire `TokenPaymentService.refund_for_invoice` into an admin route or the core
   refund hook for invoices whose `payment_method == "token_payment"`.

### Plugin-owned rate table (only if config text is insufficient)
1. `token_payment/models.py::TokenPaymentRate` (BaseModel: `currency UNIQUE`, `rate NUMERIC`).
2. Migration in `plugins/token_payment/migrations/versions/` + register the path
   in `alembic.ini` `version_locations` (per the plugin-migrations rule).
3. CRUD admin routes (`@require_permission("payments.configure")`).
4. `_build_service` reads rates from the repo instead of `config.get("rates")`.

### Surface at checkout (not just invoice page)
Add the method to the fe-user checkout selector (frontend repo). Backend already
supports it — `/pay` works on any PENDING invoice id.

## Validation checklist before "done"
- [ ] `python -m pytest plugins/token_payment/tests/unit/ -v` green.
- [ ] `flake8` clean @120.
- [ ] No diff under `vbwd/` (agnostic).
- [ ] Plugin still `enabled: false` by default in `plugins/plugins.json`.
- [ ] If a table was added: migration upgrades AND downgrades cleanly.

## Repo / release
Own repo `vbwd-plugin-token-payment`. CI: `.github/workflows/tests.yml` runs
`pre-commit-check.sh --plugin token_payment`. Commit to `main`; do not tag until
deployed + smoke-tested.
