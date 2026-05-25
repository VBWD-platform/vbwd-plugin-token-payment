# How it works (now)

A reader-friendly tour of the token-balance payment plugin.

## The idea

Users accumulate **tokens** (they buy bundles, get bonuses, receive transfers in
meinchat). This plugin lets them **spend those tokens to pay an invoice** instead
of paying with money through Stripe/PayPal.

It is an *internal* payment method: there is no external gateway to call. Paying
is just "move tokens out of the wallet, then mark the invoice paid."

## The wallet is not ours

The token wallet lives in **core** and is shared by everything token-related:

- `UserTokenBalance` — how many tokens a user has.
- `TokenTransaction` — the ledger (every credit/debit).
- `TokenService` — `get_balance`, `debit_tokens`, `credit_tokens`.

This plugin **only spends from that wallet**. It never owns balances. That is why
turning the plugin off changes nothing about a user's tokens or any invoice.

## The rate

An invoice is in money (e.g. `$9.99`). To pay it with tokens we need a price for a
token. That is the **rate**, set per currency in `config.json`:

```
rates = { "USD": 0.05 }   // one token is worth $0.05
```

So `$9.99` needs `ceil(9.99 / 0.05) = 200` tokens. If no rate is set for the
invoice's currency, token payment is simply **unavailable** for that invoice.

## The flow

```
GET  /quote   →  "this invoice = 200 tokens; you have 500; 300 left after"
POST /pay     →  1. re-check it's PENDING and yours
                 2. debit 200 tokens (ledger entry, type USAGE, linked to invoice)
                 3. tell core "payment captured"  ← the shared seam
                 4. core marks the invoice PAID and activates its line items
                    (subscription goes ACTIVE, token bundles credit, …)
              →  { tokens_spent: 200, new_balance: 300, status: PAID }
```

If step 3/4 fails for any reason, step 2 is **refunded** — you never lose tokens
without getting the thing you paid for.

## What it deliberately does NOT do

- No partial payment (tokens + card). All-or-nothing.
- No automated refund of a token payment yet (an admin credits tokens back
  manually). See *how-to-develop*.
- No per-item token pricing, no token expiry.

## Where the pieces live

```
__init__.py                  the plugin (registers as a payment provider)
token_payment/service.py     the rate math + debit/refund (pure, unit-tested)
token_payment/routes.py      the /quote and /pay HTTP endpoints
config.json / admin-config   the rates + debug toggle
```
