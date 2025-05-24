"""
Functional tests for main_app.py WebSocket handlers and utilities.

Since testing live WebSocket connections is complex, these tests focus on
the handler functions and utility logic that can be tested with mock data.
"""

import pytest
import logging
import os
from unittest.mock import patch, MagicMock
from datetime import datetime

# Import the functions we want to test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import (
    validate_environment,
    on_crypto_quote,
    on_crypto_trade,
    on_crypto_bar,
    on_trade_update
)


@pytest.mark.unit
@patch('main_app.os.getenv')
def test_validate_environment_success(mock_getenv):
    """Test successful environment validation."""
    # Mock environment variables present
    mock_getenv.side_effect = lambda key, default=None: {
        'APCA_API_KEY_ID': 'test_key',
        'APCA_API_SECRET_KEY': 'test_secret'
    }.get(key, default)
    
    result = validate_environment()
    assert result == True


@pytest.mark.unit
@patch('main_app.os.getenv')
def test_validate_environment_missing_key(mock_getenv):
    """Test environment validation with missing API key."""
    # Mock missing API key
    mock_getenv.side_effect = lambda key, default=None: {
        'APCA_API_SECRET_KEY': 'test_secret'
    }.get(key, default)
    
    result = validate_environment()
    assert result == False


@pytest.mark.unit
@patch('main_app.os.getenv')
def test_validate_environment_missing_secret(mock_getenv):
    """Test environment validation with missing API secret."""
    # Mock missing API secret
    mock_getenv.side_effect = lambda key, default=None: {
        'APCA_API_KEY_ID': 'test_key'
    }.get(key, default)
    
    result = validate_environment()
    assert result == False


@pytest.mark.unit
@patch('main_app.os.getenv')
def test_validate_environment_missing_both(mock_getenv):
    """Test environment validation with both credentials missing."""
    # Mock both credentials missing
    mock_getenv.return_value = None
    
    result = validate_environment()
    assert result == False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_crypto_quote_handler(caplog):
    """Test cryptocurrency quote handler with mock quote data."""
    # Create a mock quote object
    mock_quote = MagicMock()
    mock_quote.symbol = 'BTC/USD'
    mock_quote.bid_price = 50000.50
    mock_quote.bid_size = 1.5
    mock_quote.ask_price = 50001.00
    mock_quote.ask_size = 2.0
    
    # Set logging level to capture INFO messages
    caplog.set_level(logging.INFO)
    
    # Call the handler
    await on_crypto_quote(mock_quote)
    
    # Verify the log message was created
    assert len(caplog.records) == 1
    log_message = caplog.records[0].message
    assert 'Quote: BTC/USD' in log_message
    assert 'Bid: $50000.5 @ 1.5' in log_message
    assert 'Ask: $50001.0 @ 2.0' in log_message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_crypto_trade_handler(caplog):
    """Test cryptocurrency trade handler with mock trade data."""
    # Create a mock trade object
    mock_trade = MagicMock()
    mock_trade.symbol = 'BTC/USD'
    mock_trade.price = 50000.75
    mock_trade.size = 0.25
    mock_trade.timestamp = datetime(2024, 1, 1, 12, 0, 0)
    
    # Set logging level to capture INFO messages
    caplog.set_level(logging.INFO)
    
    # Call the handler
    await on_crypto_trade(mock_trade)
    
    # Verify the log message was created
    assert len(caplog.records) == 1
    log_message = caplog.records[0].message
    assert 'Trade: BTC/USD' in log_message
    assert 'Price: $50000.75' in log_message
    assert 'Size: 0.25' in log_message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_crypto_bar_handler(caplog):
    """Test cryptocurrency bar handler with mock bar data."""
    # Create a mock bar object
    mock_bar = MagicMock()
    mock_bar.symbol = 'BTC/USD'
    mock_bar.open = 49900.00
    mock_bar.high = 50100.00
    mock_bar.low = 49800.00
    mock_bar.close = 50000.00
    mock_bar.volume = 125.5
    
    # Set logging level to capture INFO messages
    caplog.set_level(logging.INFO)
    
    # Call the handler
    await on_crypto_bar(mock_bar)
    
    # Verify the log message was created
    assert len(caplog.records) == 1
    log_message = caplog.records[0].message
    assert 'Bar: BTC/USD' in log_message
    assert 'Open: $49900.0' in log_message
    assert 'High: $50100.0' in log_message
    assert 'Low: $49800.0' in log_message
    assert 'Close: $50000.0' in log_message
    assert 'Volume: 125.5' in log_message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_trade_update_handler_basic(caplog):
    """Test trade update handler with basic order data."""
    # Create a mock trade update object
    mock_trade_update = MagicMock()
    mock_trade_update.event = 'fill'
    
    # Create a mock order object
    mock_order = MagicMock()
    mock_order.id = 'test_order_123'
    mock_order.symbol = 'BTC/USD'
    mock_order.side = 'buy'
    mock_order.status = 'filled'
    
    mock_trade_update.order = mock_order
    mock_trade_update.execution_id = None  # No execution details
    
    # Set logging level to capture INFO messages
    caplog.set_level(logging.INFO)
    
    # Call the handler
    await on_trade_update(mock_trade_update)
    
    # Verify the basic log message was created
    assert len(caplog.records) == 1
    log_message = caplog.records[0].message
    assert 'Trade Update: fill' in log_message
    assert 'Order ID: test_order_123' in log_message
    assert 'Symbol: BTC/USD' in log_message
    assert 'Side: buy' in log_message
    assert 'Status: filled' in log_message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_trade_update_handler_with_execution(caplog):
    """Test trade update handler with execution details."""
    # Create a mock trade update object
    mock_trade_update = MagicMock()
    mock_trade_update.event = 'partial_fill'
    mock_trade_update.execution_id = 'exec_456'
    mock_trade_update.price = 50000.25
    mock_trade_update.qty = 0.1
    
    # Create a mock order object
    mock_order = MagicMock()
    mock_order.id = 'test_order_456'
    mock_order.symbol = 'ETH/USD'
    mock_order.side = 'sell'
    mock_order.status = 'partially_filled'
    
    mock_trade_update.order = mock_order
    
    # Set logging level to capture INFO messages
    caplog.set_level(logging.INFO)
    
    # Call the handler
    await on_trade_update(mock_trade_update)
    
    # Verify both log messages were created
    assert len(caplog.records) == 2
    
    # Check the basic trade update message
    basic_message = caplog.records[0].message
    assert 'Trade Update: partial_fill' in basic_message
    assert 'Order ID: test_order_456' in basic_message
    
    # Check the execution details message
    execution_message = caplog.records[1].message
    assert 'Execution: Price $50000.25' in execution_message
    assert 'Qty: 0.1' in execution_message 