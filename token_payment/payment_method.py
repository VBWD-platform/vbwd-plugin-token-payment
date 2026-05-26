"""Idempotent upsert/deactivate of the ``token_balance`` payment-method record.

The checkout payment selector is **data-driven** (`PaymentMethodsBlock.vue`
iterates `GET /api/v1/payment-methods`), which reads from the
``vbwd_payment_method`` table. So this plugin advertises itself by ensuring a
row exists with ``code = "token_balance"`` while enabled, and deactivates it on
disable — no fe-user core list edit required.
"""
from typing import Any

from vbwd.models.payment_method import PaymentMethod

PAYMENT_METHOD_CODE = "token_balance"
PAYMENT_METHOD_NAME = "Token balance"
PLUGIN_ID = "token_payment"


def upsert_token_balance_method(repo: Any) -> None:
    """Ensure a row exists (creating it if absent) and is active."""
    existing = repo.find_by_code(PAYMENT_METHOD_CODE)
    if existing is None:
        method = PaymentMethod(
            code=PAYMENT_METHOD_CODE,
            name=PAYMENT_METHOD_NAME,
            plugin_id=PLUGIN_ID,
            is_active=True,
        )
        repo.save(method)
        return
    existing.is_active = True
    repo.save(existing)


def deactivate_token_balance_method(repo: Any) -> None:
    """Mark the row inactive (kept for historical references; not deleted)."""
    existing = repo.find_by_code(PAYMENT_METHOD_CODE)
    if existing is None:
        return
    existing.is_active = False
    repo.save(existing)
