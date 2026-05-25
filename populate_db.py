"""Idempotent demo data for token-payment.

The plugin owns no tables — the currency→token rates live in ``config.json`` —
so there is nothing to seed. Kept for the unified plugin convention.
"""


def populate_db() -> None:
    return None


if __name__ == "__main__":
    populate_db()
