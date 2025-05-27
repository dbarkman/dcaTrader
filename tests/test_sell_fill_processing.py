"""
Tests for Phase 8: TradingStream SELL Fill Processing

Simple, pragmatic tests focused on core error handling behavior.
Complex end-to-end functionality is covered by integration tests.

These tests follow our development principles:
- KISS: Simple, straightforward test logic
- Focused: One behavior per test
- Pragmatic: Test what matters without over-engineering
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone

# Import the function under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import update_cycle_on_sell_fill


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_fill_no_cycle_found(caplog):
    """Test SELL fill processing when no cycle is found - should log error and return."""
    mock_order = MagicMock()
    mock_order.symbol = 'ETH/USD'
    mock_order.id = 'unknown_order_456'
    
    mock_trade_update = MagicMock()
    
    with patch('main_app.execute_query') as mock_execute_query:
        # Setup: No cycle found
        mock_execute_query.return_value = None
        
        # Call the function
        await update_cycle_on_sell_fill(mock_order, mock_trade_update)
        
        # Verify error was logged
        error_logs = [record.message for record in caplog.records if record.levelname == 'ERROR']
        assert any('No cycle found with latest_order_id=unknown_order_456' in msg for msg in error_logs)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_fill_no_asset_config_found(caplog):
    """Test SELL fill processing when asset config is not found - should log error and return."""
    mock_order = MagicMock()
    mock_order.symbol = 'UNKNOWN/USD'
    mock_order.id = 'sell_order_789'
    
    mock_trade_update = MagicMock()
    
    # Mock cycle data (cycle found)
    mock_cycle_data = {
        'id': 55, 'asset_id': 99, 'status': 'selling',
        'quantity': Decimal('0.02'), 'average_purchase_price': Decimal('48000.0'),
        'safety_orders': 2, 'latest_order_id': 'sell_order_789',
        'latest_order_created_at': None, 'last_order_fill_price': Decimal('47000.0'),
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_asset_config') as mock_get_asset_config:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_get_asset_config.return_value = None  # No asset config found
        
        # Call the function
        await update_cycle_on_sell_fill(mock_order, mock_trade_update)
        
        # Verify error was logged
        error_logs = [record.message for record in caplog.records if record.levelname == 'ERROR']
        assert any('No asset config found for UNKNOWN/USD' in msg for msg in error_logs)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_fill_invalid_fill_price(caplog):
    """Test SELL fill processing with invalid fill price - should log error and return."""
    mock_order = MagicMock()
    mock_order.symbol = 'SOL/USD'
    mock_order.id = 'sell_order_invalid'
    mock_order.filled_avg_price = None  # No fill price
    
    mock_trade_update = MagicMock()
    mock_trade_update.price = None  # No fallback price either
    
    mock_cycle_data = {
        'id': 66, 'asset_id': 2, 'status': 'selling',
        'quantity': Decimal('1.5'), 'average_purchase_price': Decimal('150.0'),
        'safety_orders': 0, 'latest_order_id': 'sell_order_invalid',
        'latest_order_created_at': None, 'last_order_fill_price': Decimal('145.0'),
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    mock_asset_config = MagicMock()
    mock_asset_config.id = 2
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_asset_config') as mock_get_asset_config:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_get_asset_config.return_value = mock_asset_config
        
        # Call the function
        await update_cycle_on_sell_fill(mock_order, mock_trade_update)
        
        # Verify error was logged
        error_logs = [record.message for record in caplog.records if record.levelname == 'ERROR']
        assert any('Missing fill price data' in msg for msg in error_logs)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_fill_clears_latest_order_created_at():
    """Test that SELL fill processing clears both latest_order_id and latest_order_created_at fields."""
    mock_order = MagicMock()
    mock_order.symbol = 'BTC/USD'
    mock_order.id = 'sell_order_123'
    mock_order.filled_avg_price = '52000.00'
    
    mock_trade_update = MagicMock()
    
    # Mock cycle data with latest_order_created_at set (from Phase 6 enhancement)
    order_timestamp = datetime.now(timezone.utc)
    mock_cycle_data = {
        'id': 77, 'asset_id': 3, 'status': 'selling',
        'quantity': Decimal('0.01'), 'average_purchase_price': Decimal('50000.0'),
        'safety_orders': 1, 'latest_order_id': 'sell_order_123',
        'latest_order_created_at': order_timestamp, 'last_order_fill_price': Decimal('49000.0'),
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    # Mock asset config
    mock_asset_config = MagicMock()
    mock_asset_config.id = 3
    mock_asset_config.cooldown_period = 60
    
    # Mock new cooldown cycle
    mock_cooldown_cycle = MagicMock()
    mock_cooldown_cycle.id = 88
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_asset_config') as mock_get_asset_config, \
         patch('main_app.get_trading_client') as mock_get_client, \
         patch('main_app.get_alpaca_position_by_symbol') as mock_get_position, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle, \
         patch('main_app.update_asset_config') as mock_update_asset, \
         patch('main_app.create_cycle') as mock_create_cycle:
        
        # Setup mocks
        mock_execute_query.return_value = mock_cycle_data
        mock_get_asset_config.return_value = mock_asset_config
        mock_get_client.return_value = MagicMock()
        mock_get_position.return_value = None  # No position after sell
        mock_update_cycle.return_value = True
        mock_update_asset.return_value = True
        mock_create_cycle.return_value = mock_cooldown_cycle
        
        # Call the function
        await update_cycle_on_sell_fill(mock_order, mock_trade_update)
        
        # Verify update_cycle was called with correct parameters
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == 77
        assert updates['status'] == 'complete'
        assert updates['latest_order_id'] is None
        assert updates['latest_order_created_at'] is None  # This is the key enhancement
        assert 'completed_at' in updates
        
        # Verify asset last_sell_price was updated
        mock_update_asset.assert_called_once_with(3, {'last_sell_price': Decimal('52000.00')})
        
        # Verify new cooldown cycle was created
        mock_create_cycle.assert_called_once()
        create_kwargs = mock_create_cycle.call_args[1]
        assert create_kwargs['asset_id'] == 3
        assert create_kwargs['status'] == 'cooldown'
        assert create_kwargs['quantity'] == Decimal('0')
        assert create_kwargs['latest_order_id'] is None
        # latest_order_created_at defaults to None in create_cycle, so it's not explicitly passed 