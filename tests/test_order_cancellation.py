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
        'last_order_fill_price': None, 'completed_at': None,
        'created_at': None, 'updated_at': None
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
async def test_order_cancellation_calls_update_cycle_correctly():
    """Test that order cancellation calls update_cycle with the correct parameters."""
    mock_order = MagicMock()
    mock_order.symbol = 'BTC/USD'
    mock_order.id = 'test_order_123'
    
    # Mock cycle data - cycle in 'buying' status
    mock_cycle_data = {
        'id': 42, 'asset_id': 1, 'status': 'buying',
        'quantity': Decimal('0'), 'average_purchase_price': Decimal('0'),
        'safety_orders': 0, 'latest_order_id': 'test_order_123',
        'last_order_fill_price': None, 'completed_at': None,
        'created_at': None, 'updated_at': None
    }
    
    with patch('main_app.execute_query') as mock_execute_query, \
         patch('models.cycle_data.update_cycle') as mock_update_cycle:
        
        mock_execute_query.return_value = mock_cycle_data
        mock_update_cycle.return_value = True
        
        # Call the function
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify correct update_cycle call
        mock_update_cycle.assert_called_once_with(42, {
            'status': 'watching',
            'latest_order_id': None
        }) 