"""Plugin contract tests — metadata, prefix, internal-payment provider behaviour."""
from plugins.token_payment import TokenPaymentPlugin, DEFAULT_CONFIG
from vbwd.plugins.payment_provider import PaymentProviderPlugin, PaymentStatus


def test_is_a_payment_provider_with_expected_metadata():
    plugin = TokenPaymentPlugin()
    assert isinstance(plugin, PaymentProviderPlugin)
    assert plugin.metadata.name == "token_payment"
    assert plugin.metadata.version


def test_url_prefix_and_blueprint_resolve():
    plugin = TokenPaymentPlugin()
    assert plugin.get_url_prefix() == "/api/v1/plugins/token-payment"
    assert plugin.get_blueprint() is not None


def test_internal_method_has_no_webhooks():
    plugin = TokenPaymentPlugin()
    assert plugin.verify_webhook(b"", "") is False
    assert plugin.handle_webhook({}) is None


def test_refund_is_not_automated():
    plugin = TokenPaymentPlugin()
    result = plugin.refund_payment("token-balance:x")
    assert result.success is False
    assert result.status == PaymentStatus.FAILED


def test_default_config_ships_rates_and_debug_mode():
    assert "debug_mode" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["rates"].get("USD")
