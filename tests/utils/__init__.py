"""
Test utilities package for DCA Trading Bot.

This package contains helper functions and mock objects for testing.
"""

# Make key functions available at package level for easier imports
from .test_utils import (
    create_mock_crypto_quote_event,
    create_mock_crypto_trade_event,
    create_mock_trade_update_event,
    create_mock_base_order_fill_event,
    create_mock_safety_order_fill_event,
    create_realistic_btc_quote,
    create_realistic_eth_quote
)

__all__ = [
    'create_mock_crypto_quote_event',
    'create_mock_crypto_trade_event',
    'create_mock_trade_update_event',
    'create_mock_base_order_fill_event',
    'create_mock_safety_order_fill_event',
    'create_realistic_btc_quote',
    'create_realistic_eth_quote'
] 