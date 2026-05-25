"""Shared fixtures for token-payment plugin tests.

Pure unit tests — no Flask app, no DB. The ``TokenService`` is faked with
``MagicMock`` and invoices are lightweight ``SimpleNamespace`` stand-ins.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


@pytest.fixture
def fake_token_service():
    return MagicMock()


@pytest.fixture
def make_invoice():
    def _make(total: str = "9.99", currency: str = "USD"):
        return SimpleNamespace(
            id=uuid4(),
            invoice_number="INV-TEST-1",
            total_amount=Decimal(total),
            currency=currency,
        )

    return _make
