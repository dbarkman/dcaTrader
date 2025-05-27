"""
Tests for Phase 9: Order Cancellation/Rejection/Expiration Handling

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

# Import the function under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import update_cycle_on_order_cancellation


@pytest.mark.asyncio
@pytest.mark.unit
async def test_order_cancellation_for_unknown_order_logs_warning(caplog):
    """Test that canceling an order not linked to any cycle logs a warning and takes no action."""
    mock_order = MagicMock()
    mock_order.symbol = 'SOL/USD'
    mock_order.id = 'orphan_order_789'
    
    with patch('main_app.execute_query') as mock_execute_query:
        # Setup: No cycle found
        mock_execute_query.return_value = None
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify warning was logged
        warning_logs = [record.message for record in caplog.records if record.levelname == 'WARNING']
        assert any('Received canceled for order orphan_order_789 not actively tracked or already processed' in msg for msg in warning_logs)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_order_cancellation_handles_update_failure(caplog):
    """Test proper error handling when cycle update fails."""
    mock_order = MagicMock()
    mock_order.symbol = 'AVAX/USD'
    mock_order.id = 'failed_update_order'
    
    # Mock cycle data - cycle in 'buying' status
    mock_cycle_data = {
        'id': 99, 'asset_id': 4, 'status': 'buying',
        'quantity': Decimal('0'), 'average_purchase_price': Decimal('0'),
        'safety_orders': 0, 'latest_order_id': 'failed_update_order',
        'latest_order_created_at': None, 'last_order_fill_price': None,
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_update_cycle.return_value = False  # Update fails
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify error was logged
        error_logs = [record.message for record in caplog.records if record.levelname == 'ERROR']
        assert any('Failed to update cycle 99 after canceled order failed_update_order' in msg for msg in error_logs)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_buy_order_cancellation_calls_update_cycle_correctly():
    """Test that BUY order cancellation calls update_cycle with the correct parameters."""
    mock_order = MagicMock()
    mock_order.symbol = 'BTC/USD'
    mock_order.id = 'test_order_123'
    mock_order.side = 'buy'  # Explicitly set as BUY order
    
    # Mock cycle data - cycle in 'buying' status
    mock_cycle_data = {
        'id': 42, 'asset_id': 1, 'status': 'buying',
        'quantity': Decimal('0'), 'average_purchase_price': Decimal('0'),
        'safety_orders': 0, 'latest_order_id': 'test_order_123',
        'latest_order_created_at': None, 'last_order_fill_price': None,
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_trading_client') as mock_get_client, \
         patch('main_app.get_alpaca_position_by_symbol') as mock_get_position, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_get_client.return_value = MagicMock()
        mock_get_position.return_value = None  # No position found
        mock_update_cycle.return_value = True
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify correct update_cycle call for BUY order
        mock_update_cycle.assert_called_once_with(42, {
            'status': 'watching',
            'latest_order_id': None,
            'latest_order_created_at': None
        })


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_order_cancellation_with_remaining_position():
    """Test SELL order cancellation when Alpaca position shows remaining quantity - should revert to watching."""
    mock_order = MagicMock()
    mock_order.symbol = 'ETH/USD'
    mock_order.id = 'sell_order_456'
    mock_order.side = 'sell'
    mock_order.filled_qty = '0.5'  # Partial fill
    mock_order.filled_avg_price = '3200.00'
    
    # Mock cycle data - cycle in 'selling' status
    mock_cycle_data = {
        'id': 77, 'asset_id': 2, 'status': 'selling',
        'quantity': Decimal('1.0'), 'average_purchase_price': Decimal('3000.0'),
        'safety_orders': 1, 'latest_order_id': 'sell_order_456',
        'latest_order_created_at': None, 'last_order_fill_price': Decimal('2950.0'),
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    # Mock Alpaca position showing remaining quantity
    mock_alpaca_position = MagicMock()
    mock_alpaca_position.qty = '0.5'  # Remaining after partial fill
    mock_alpaca_position.avg_entry_price = '3000.00'
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_trading_client') as mock_get_client, \
         patch('main_app.get_alpaca_position_by_symbol') as mock_get_position, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_get_client.return_value = MagicMock()
        mock_get_position.return_value = mock_alpaca_position
        mock_update_cycle.return_value = True
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify correct update_cycle call for remaining position
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == 77
        assert updates['status'] == 'watching'
        assert updates['latest_order_id'] is None
        assert updates['latest_order_created_at'] is None
        assert updates['quantity'] == Decimal('0.5')  # Synced from Alpaca
        assert updates['average_purchase_price'] == Decimal('3000.00')  # Synced from Alpaca


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_order_cancellation_with_zero_position():
    """Test SELL order cancellation when Alpaca position is zero - should complete cycle."""
    mock_order = MagicMock()
    mock_order.symbol = 'BTC/USD'
    mock_order.id = 'sell_order_789'
    mock_order.side = 'sell'
    mock_order.filled_qty = '0.01'  # Full fill before cancellation
    mock_order.filled_avg_price = '52000.00'
    
    # Mock cycle data - cycle in 'selling' status
    mock_cycle_data = {
        'id': 88, 'asset_id': 1, 'status': 'selling',
        'quantity': Decimal('0.01'), 'average_purchase_price': Decimal('50000.0'),
        'safety_orders': 0, 'latest_order_id': 'sell_order_789',
        'latest_order_created_at': None, 'last_order_fill_price': Decimal('49000.0'),
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    # Mock asset config
    mock_asset_config = MagicMock()
    mock_asset_config.id = 1
    mock_asset_config.cooldown_period = 60
    
    # Mock new cooldown cycle
    mock_cooldown_cycle = MagicMock()
    mock_cooldown_cycle.id = 99
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_trading_client') as mock_get_client, \
         patch('main_app.get_alpaca_position_by_symbol') as mock_get_position, \
         patch('main_app.get_asset_config') as mock_get_asset_config, \
         patch('main_app.update_asset_config') as mock_update_asset, \
         patch('main_app.create_cycle') as mock_create_cycle, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_get_client.return_value = MagicMock()
        mock_get_position.return_value = None  # No position found (zero quantity)
        mock_get_asset_config.return_value = mock_asset_config
        mock_update_asset.return_value = True
        mock_create_cycle.return_value = mock_cooldown_cycle
        mock_update_cycle.return_value = True
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify correct update_cycle call for completion
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == 88
        assert updates['status'] == 'complete'
        assert updates['latest_order_id'] is None
        assert updates['latest_order_created_at'] is None
        assert updates['quantity'] == Decimal('0')
        assert 'completed_at' in updates
        
        # Verify asset last_sell_price was updated
        mock_update_asset.assert_called_once_with(1, {'last_sell_price': Decimal('52000.00')})
        
        # Verify new cooldown cycle was created
        mock_create_cycle.assert_called_once()
        create_kwargs = mock_create_cycle.call_args[1]
        assert create_kwargs['asset_id'] == 1
        assert create_kwargs['status'] == 'cooldown'
        assert create_kwargs['quantity'] == Decimal('0')


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sell_order_cancellation_alpaca_client_failure():
    """Test SELL order cancellation when Alpaca client fails - should use fallback logic."""
    mock_order = MagicMock()
    mock_order.symbol = 'SOL/USD'
    mock_order.id = 'sell_order_fail'
    mock_order.side = 'sell'
    
    # Mock cycle data - cycle in 'selling' status
    mock_cycle_data = {
        'id': 55, 'asset_id': 3, 'status': 'selling',
        'quantity': Decimal('2.0'), 'average_purchase_price': Decimal('150.0'),
        'safety_orders': 1, 'latest_order_id': 'sell_order_fail',
        'latest_order_created_at': None, 'last_order_fill_price': Decimal('145.0'),
        'highest_trailing_price': None, 'sell_price': None,
        'completed_at': None, 'created_at': None, 'updated_at': None
    }
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('main_app.get_trading_client') as mock_get_client, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_get_client.return_value = None  # Client failure
        mock_update_cycle.return_value = True
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify fallback behavior - simple revert to watching
        mock_update_cycle.assert_called_once_with(55, {
            'status': 'watching',
            'latest_order_id': None,
            'latest_order_created_at': None
        }) 