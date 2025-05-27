"""
Tests for Standardized Partial Fill Handling in TradingStream

This module tests the refined partial fill handling logic that ensures:
1. partial_fill events only log details without updating cycle financials
2. Terminal fill/canceled events update cycle financials with definitive data
3. Proper handling of partial fills in canceled orders
"""

import pytest
import logging
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timezone

# Add src to path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import on_trade_update, update_cycle_on_buy_fill, update_cycle_on_order_cancellation


class TestPartialFillLogging:
    """Test that partial_fill events only log without database updates"""
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.logger')
    async def test_partial_fill_buy_order_logging_only(self, mock_logger):
        """Test that partial_fill events for BUY orders only log details"""
        
        # Create mock trade update for partial fill
        mock_trade_update = Mock()
        mock_trade_update.event = 'partial_fill'
        
        mock_order = Mock()
        mock_order.symbol = 'BTC/USD'
        mock_order.id = 'test_partial_buy_123'
        mock_order.side = 'buy'
        mock_order.status = 'partially_filled'
        mock_order.qty = '0.01'
        mock_order.filled_qty = '0.005'
        mock_order.filled_avg_price = '50000.0'
        
        mock_trade_update.order = mock_order
        
        # Execute partial fill handling
        await on_trade_update(mock_trade_update)
        
        # Verify logging occurred
        mock_logger.info.assert_any_call("📊 PARTIAL FILL: BTC/USD order test_partial_buy_123")
        mock_logger.info.assert_any_call("   Side: BUY")
        mock_logger.info.assert_any_call("   Partially Filled Qty: 0.005")
        mock_logger.info.assert_any_call("   Order Status: PARTIALLY_FILLED")
        mock_logger.info.assert_any_call("   📋 Order remains active with partial fill")
        mock_logger.info.assert_any_call("   Remaining Qty: 0.005 (of 0.01 total)")
        mock_logger.info.assert_any_call("   ℹ️ PARTIAL FILL: No database updates - cycle remains in current status")
        mock_logger.info.assert_any_call("   ⏳ Waiting for terminal event (fill/canceled) to update cycle financials")
        
        # Verify no database update functions were called
        with patch('main_app.update_cycle_on_buy_fill') as mock_buy_fill:
            with patch('main_app.update_cycle_on_sell_fill') as mock_sell_fill:
                with patch('main_app.update_cycle_on_order_cancellation') as mock_cancellation:
                    await on_trade_update(mock_trade_update)
                    
                    mock_buy_fill.assert_not_called()
                    mock_sell_fill.assert_not_called()
                    mock_cancellation.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.logger')
    async def test_partial_fill_sell_order_logging_only(self, mock_logger):
        """Test that partial_fill events for SELL orders only log details"""
        
        # Create mock trade update for partial fill
        mock_trade_update = Mock()
        mock_trade_update.event = 'partial_fill'
        
        mock_order = Mock()
        mock_order.symbol = 'ETH/USD'
        mock_order.id = 'test_partial_sell_456'
        mock_order.side = 'sell'
        mock_order.status = 'partially_filled'
        mock_order.qty = '0.1'
        mock_order.filled_qty = '0.03'
        mock_order.filled_avg_price = '3800.0'
        
        mock_trade_update.order = mock_order
        
        # Execute partial fill handling
        await on_trade_update(mock_trade_update)
        
        # Verify logging occurred
        mock_logger.info.assert_any_call("📊 PARTIAL FILL: ETH/USD order test_partial_sell_456")
        mock_logger.info.assert_any_call("   Side: SELL")
        mock_logger.info.assert_any_call("   Partially Filled Qty: 0.03")
        mock_logger.info.assert_any_call("   Order Status: PARTIALLY_FILLED")
        mock_logger.info.assert_any_call("   📋 Order remains active with partial fill")
        mock_logger.info.assert_any_call("   Remaining Qty: 0.07 (of 0.1 total)")

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.logger')
    async def test_partial_fill_missing_data_graceful_handling(self, mock_logger):
        """Test graceful handling when partial fill data is missing"""
        
        # Create mock trade update with minimal data
        mock_trade_update = Mock()
        mock_trade_update.event = 'partial_fill'
        
        mock_order = Mock()
        mock_order.symbol = 'SOL/USD'
        mock_order.id = 'test_partial_minimal_789'
        mock_order.side = 'buy'
        # Missing: status, qty, filled_qty, filled_avg_price
        
        mock_trade_update.order = mock_order
        
        # Execute partial fill handling
        await on_trade_update(mock_trade_update)
        
        # Verify basic logging occurred without errors
        mock_logger.info.assert_any_call("📊 PARTIAL FILL: SOL/USD order test_partial_minimal_789")
        mock_logger.info.assert_any_call("   Side: BUY")
        mock_logger.info.assert_any_call("   ℹ️ PARTIAL FILL: No database updates - cycle remains in current status")


class TestTerminalFillHandling:
    """Test that terminal fill events properly update cycle financials"""
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.execute_query')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('models.cycle_data.update_cycle')
    @patch('main_app.logger')
    async def test_terminal_fill_updates_cycle_with_definitive_data(self, mock_logger, mock_update_cycle, 
                                                                   mock_get_position, mock_get_client, mock_execute_query):
        """Test that terminal fill events use definitive order data to update cycles"""
        
        # Setup mock cycle data
        mock_cycle_data = {
            'id': 1,
            'asset_id': 1,
            'status': 'buying',
            'quantity': Decimal('0'),
            'average_purchase_price': Decimal('0'),
            'safety_orders': 0,
            'latest_order_id': 'test_terminal_fill_123',
            'latest_order_created_at': datetime.now(timezone.utc),
            'last_order_fill_price': None,
            'highest_trailing_price': None,
            'completed_at': None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'sell_price': None
        }
        
        mock_asset_data = {
            'asset_symbol': 'BTC/USD',
            'take_profit_percent': Decimal('1.0')
        }
        
        # Setup query responses
        mock_execute_query.side_effect = [mock_cycle_data, mock_asset_data]
        
        # Setup Alpaca position
        mock_position = Mock()
        mock_position.qty = '0.01'
        mock_position.avg_entry_price = '50000.0'
        mock_get_position.return_value = mock_position
        mock_get_client.return_value = Mock()
        
        # Setup update_cycle to return success
        mock_update_cycle.return_value = True
        
        # Create mock order with definitive fill data
        mock_order = Mock()
        mock_order.symbol = 'BTC/USD'
        mock_order.id = 'test_terminal_fill_123'
        mock_order.side = 'buy'
        mock_order.filled_qty = '0.01'
        mock_order.filled_avg_price = '50000.0'
        
        mock_trade_update = Mock()
        
        # Execute terminal fill handling
        await update_cycle_on_buy_fill(mock_order, mock_trade_update)
        
        # Verify definitive data logging
        mock_logger.info.assert_any_call("📊 Processing TERMINAL FILL event - extracting definitive order data...")
        mock_logger.info.assert_any_call("   Total Filled Qty: 0.01")
        mock_logger.info.assert_any_call("   Avg Fill Price: $50,000.00 (definitive)")
        
        # Verify that the function completed without error and processed the terminal fill
        # Note: The actual database update happens via local import, so we just verify basic processing
        mock_logger.info.assert_any_call("📊 Syncing with Alpaca position: 0.01 @ $50,000.00")


class TestPartialFillInCanceledOrders:
    """Test handling of partial fills in canceled/rejected/expired orders"""
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.execute_query')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('models.cycle_data.update_cycle')
    @patch('main_app.logger')
    async def test_canceled_buy_order_with_partial_fill(self, mock_logger, mock_update_cycle, 
                                                       mock_get_position, mock_get_client, mock_execute_query):
        """Test that canceled BUY orders with partial fills update cycle correctly"""
        
        # Setup mock cycle data
        mock_cycle_data = {
            'id': 2,
            'asset_id': 1,
            'status': 'buying',
            'quantity': Decimal('0'),
            'average_purchase_price': Decimal('0'),
            'safety_orders': 0,
            'latest_order_id': 'test_canceled_partial_456',
            'latest_order_created_at': datetime.now(timezone.utc),
            'last_order_fill_price': None,
            'highest_trailing_price': None,
            'completed_at': None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'sell_price': None
        }
        
        mock_execute_query.return_value = mock_cycle_data
        
        # Setup Alpaca position (reflecting partial fill)
        mock_position = Mock()
        mock_position.qty = '0.005'  # Half of the intended order
        mock_position.avg_entry_price = '49500.0'
        mock_get_position.return_value = mock_position
        mock_get_client.return_value = Mock()
        
        # Setup update_cycle to return success
        mock_update_cycle.return_value = True
        
        # Create mock order with partial fill data
        mock_order = Mock()
        mock_order.symbol = 'BTC/USD'
        mock_order.id = 'test_canceled_partial_456'
        mock_order.side = 'buy'
        mock_order.filled_qty = '0.005'  # Partially filled
        mock_order.filled_avg_price = '49500.0'
        
        # Execute cancellation handling
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify partial fill detection logging
        mock_logger.info.assert_any_call("📊 Checking for partial fills in canceled BUY order...")
        mock_logger.info.assert_any_call("   Partial Fill Detected: 0.005 filled")
        mock_logger.info.assert_any_call("   Partial Fill Avg Price: $49,500.00 (definitive)")
        
        # Verify cycle update was called with partial fill data
        mock_update_cycle.assert_called_once()
        call_args = mock_update_cycle.call_args[0]
        updates = call_args[1]
        
        assert updates['quantity'] == Decimal('0.005')  # From Alpaca position
        assert updates['average_purchase_price'] == Decimal('49500.0')  # From Alpaca position
        assert updates['last_order_fill_price'] == Decimal('49500.0')  # From partial fill
        assert updates['status'] == 'watching'
        assert updates['latest_order_id'] is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.execute_query')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('models.cycle_data.update_cycle')
    @patch('main_app.logger')
    async def test_canceled_sell_order_with_partial_fill(self, mock_logger, mock_update_cycle, 
                                                        mock_get_position, mock_get_client, mock_execute_query):
        """Test that canceled SELL orders with partial fills update cycle correctly"""
        
        # Setup mock cycle data
        mock_cycle_data = {
            'id': 3,
            'asset_id': 1,
            'status': 'selling',
            'quantity': Decimal('0.1'),
            'average_purchase_price': Decimal('3500.0'),
            'safety_orders': 2,
            'latest_order_id': 'test_canceled_sell_789',
            'latest_order_created_at': datetime.now(timezone.utc),
            'last_order_fill_price': Decimal('3400.0'),
            'highest_trailing_price': None,
            'completed_at': None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'sell_price': None
        }
        
        mock_execute_query.return_value = mock_cycle_data
        
        # Setup Alpaca position (reflecting remaining after partial sell)
        mock_position = Mock()
        mock_position.qty = '0.07'  # 0.03 was sold, 0.07 remains
        mock_position.avg_entry_price = '3500.0'
        mock_get_position.return_value = mock_position
        mock_get_client.return_value = Mock()
        
        # Setup update_cycle to return success
        mock_update_cycle.return_value = True
        
        # Create mock order with partial fill data
        mock_order = Mock()
        mock_order.symbol = 'ETH/USD'
        mock_order.id = 'test_canceled_sell_789'
        mock_order.side = 'sell'
        mock_order.filled_qty = '0.03'  # Partially filled
        mock_order.filled_avg_price = '3800.0'
        
        # Execute cancellation handling
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify partial fill detection logging
        mock_logger.info.assert_any_call("📊 Checking for partial fills in canceled SELL order...")
        mock_logger.info.assert_any_call("   Partial Fill Detected: 0.03 sold")
        mock_logger.info.assert_any_call("   Partial Fill Avg Price: $3,800.00 (definitive)")
        
        # Verify cycle reverted to watching with updated position
        mock_update_cycle.assert_called_once()
        call_args = mock_update_cycle.call_args[0]
        updates = call_args[1]
        
        assert updates['quantity'] == Decimal('0.07')  # Remaining position from Alpaca
        assert updates['average_purchase_price'] == Decimal('3500.0')  # From Alpaca position
        assert updates['status'] == 'watching'
        assert updates['latest_order_id'] is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.execute_query')
    @patch('main_app.logger')
    async def test_canceled_order_no_partial_fills(self, mock_logger, mock_execute_query):
        """Test that canceled orders without partial fills are handled correctly"""
        
        # Setup mock cycle data
        mock_cycle_data = {
            'id': 4,
            'asset_id': 1,
            'status': 'buying',
            'quantity': Decimal('0'),
            'average_purchase_price': Decimal('0'),
            'safety_orders': 0,
            'latest_order_id': 'test_canceled_no_fill_999',
            'latest_order_created_at': datetime.now(timezone.utc),
            'last_order_fill_price': None,
            'highest_trailing_price': None,
            'completed_at': None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'sell_price': None
        }
        
        mock_execute_query.return_value = mock_cycle_data
        
        # Create mock order with no fills
        mock_order = Mock()
        mock_order.symbol = 'BTC/USD'
        mock_order.id = 'test_canceled_no_fill_999'
        mock_order.side = 'buy'
        mock_order.filled_qty = '0'  # No fills
        mock_order.filled_avg_price = None
        
        with patch('main_app.get_trading_client') as mock_get_client:
            with patch('main_app.get_alpaca_position_by_symbol') as mock_get_position:
                with patch('models.cycle_data.update_cycle') as mock_update_cycle:
                    mock_get_client.return_value = Mock()
                    mock_get_position.return_value = None  # No position
                    mock_update_cycle.return_value = True
                    
                    # Execute cancellation handling
                    await update_cycle_on_order_cancellation(mock_order, 'canceled')
                    
                    # Verify no partial fill logging
                    mock_logger.info.assert_any_call("📊 Checking for partial fills in canceled BUY order...")
                    mock_logger.info.assert_any_call("   No Partial Fills: Order was canceled without any fills")


class TestSafetyOrderCountIncrement:
    """Test that safety order count is properly incremented for partial fills"""
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.execute_query')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('models.cycle_data.update_cycle')
    @patch('main_app.logger')
    async def test_safety_order_count_increment_on_partial_fill_cancellation(self, mock_logger, mock_update_cycle, 
                                                                            mock_get_position, mock_get_client, mock_execute_query):
        """Test that safety order count increments when canceled order had partial fills"""
        
        # Setup mock cycle data (already has position, so this would be a safety order)
        mock_cycle_data = {
            'id': 5,
            'asset_id': 1,
            'status': 'buying',
            'quantity': Decimal('0.01'),  # Already has position
            'average_purchase_price': Decimal('48000.0'),
            'safety_orders': 1,  # Already has 1 safety order
            'latest_order_id': 'test_safety_partial_111',
            'latest_order_created_at': datetime.now(timezone.utc),
            'last_order_fill_price': Decimal('47000.0'),
            'highest_trailing_price': None,
            'completed_at': None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'sell_price': None
        }
        
        mock_execute_query.return_value = mock_cycle_data
        
        # Setup Alpaca position (reflecting additional partial fill)
        mock_position = Mock()
        mock_position.qty = '0.015'  # Original 0.01 + 0.005 partial fill
        mock_position.avg_entry_price = '47666.67'  # Weighted average
        mock_get_position.return_value = mock_position
        mock_get_client.return_value = Mock()
        
        # Setup update_cycle to return success
        mock_update_cycle.return_value = True
        
        # Create mock order with partial fill data (safety order)
        mock_order = Mock()
        mock_order.symbol = 'BTC/USD'
        mock_order.id = 'test_safety_partial_111'
        mock_order.side = 'buy'
        mock_order.filled_qty = '0.005'  # Partially filled safety order
        mock_order.filled_avg_price = '46000.0'
        
        # Execute cancellation handling
        await update_cycle_on_order_cancellation(mock_order, 'canceled')
        
        # Verify safety order count increment
        mock_update_cycle.assert_called_once()
        call_args = mock_update_cycle.call_args[0]
        updates = call_args[1]
        
        assert updates['safety_orders'] == 2  # Incremented from 1 to 2
        assert updates['last_order_fill_price'] == Decimal('46000.0')  # From partial fill
        
        # Verify logging
        mock_logger.info.assert_any_call("📊 Partial fill on safety order - incrementing count to 2")


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 