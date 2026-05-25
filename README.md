# Token-Balance Payment Plugin (Backend)

Pay **any** PENDING invoice with the user's **token balance**. An *internal*
payment method — no external gateway. On payment it debits the core token
balance and finalizes the invoice through the same event seam every other
payment method uses, so the core stays agnostic.

> Off by default. An admin enables the plugin and sets the currency→token rate.

## API routes

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET  | `/api/v1/plugins/token-payment/invoices/:id/quote` | Bearer (own invoice) | Token cost + balance for a PENDING invoice (no side effects) |
| POST | `/api/v1/plugins/token-payment/invoices/:id/pay`   | Bearer (own invoice) | Debit balance, mark invoice PAID, activate its line items |

`quote` →
```json
{ "available": true, "currency": "USD", "amount": "9.99", "rate": "0.05",
  "tokens_needed": 200, "balance": 500, "balance_after": 300, "sufficient": true }
```
`pay` (200) → `{ "invoice_id": "...", "tokens_spent": 200, "new_balance": 300, "status": "PAID" }`
(`400` insufficient balance · `422` no rate for the invoice currency).

## Configuration (`config.json`)

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `debug_mode` | boolean | `false` | Verbose logging |
| `rates` | object | `{ "USD": 0.05, "EUR": 0.045 }` | **Currency → price of one token.** `tokens_needed = ceil(invoice_total / rate)`. Omit a currency to disable token payment for it. |

## How it works (no core changes)

1. The plugin owns **no tables** and adds **no columns** to core. The token cost
   is computed on demand from `rates`.
2. `pay` validates the invoice, debits the **core** `TokenService`
   (`TokenTransactionType.USAGE`, `reference_id = invoice.id`), then calls
   `emit_payment_captured(...)`.
3. Core's `PaymentCapturedHandler` marks the invoice PAID and runs the line-item
   registry — subscriptions activate, token bundles credit — identical to Stripe
   et al.
4. If capture/activation fails, the debit is **refunded** (atomic).

## No data loss / agnostic

The token **wallet** (`UserTokenBalance`, `TokenTransaction`, `TokenService`) is
core, shared with the chat plugin and meinchat token transfer. This plugin only
*spends* from it. Disable the plugin or remove a currency's rate and the core
invoice flow is unchanged.

## Frontend bundle

- User: [`vbwd-fe-user-plugin-token-payment`](https://github.com/VBWD-platform/vbwd-fe-user-plugin-token-payment) — the "Pay with tokens" panel on PENDING invoices.

## Develop / run tests

```bash
# from vbwd-backend/
docker compose run --rm test python -m pytest plugins/token_payment/tests/unit/ -v
docker compose run --rm test flake8 plugins/token_payment --max-line-length=120 --extend-ignore=E203,W503
```

## Docs

- [`docs/human/`](docs/human/) — how it works now & how to develop further (for people).
- [`docs/llm/`](docs/llm/) — the same, machine-oriented (for coding agents).

License: BSL 1.1 — see [`LICENSE`](LICENSE).
