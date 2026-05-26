"""Idempotent demo data for token-payment.

Seeds the ``token_balance`` row in ``vbwd_payment_method`` so a fresh data
import (e.g. ``bin/install_demo_data.py`` or any "install all plugins"
recipe) ends up with the method available — no admin click required. The
runtime ``on_enable`` path stays as-is for late enables.

The plugin owns no tables of its own (rates live in ``config.json``); this
is the only row it ever writes.
"""
from vbwd.extensions import db
from vbwd.repositories.payment_method_repository import PaymentMethodRepository

from plugins.token_payment.token_payment.payment_method import (
    upsert_token_balance_method,
)


def populate_db() -> None:
    repo = PaymentMethodRepository(db.session)
    upsert_token_balance_method(repo)
    db.session.commit()


if __name__ == "__main__":
    populate_db()
